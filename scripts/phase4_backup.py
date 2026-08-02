#!/usr/bin/env python3
"""Phase 4 Google Driveバックアップの安全なローカル制御層。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "data" / "backup" / "phase4.json"
FILTER_PATH = PROJECT_ROOT / "data" / "backup" / "exclude-rules.txt"
MONTHLY_FILTER_PATH = PROJECT_ROOT / "data" / "backup" / "monthly-filter-rules.txt"
MONTH_RE = re.compile(r"20\d{2}-(?:0[1-9]|1[0-2])")
RUN_ID_RE = re.compile(r"[0-9a-f]{32}")
SAFE_FAILURES = {"connection_test", "capacity", "authentication", "network", "drive_api", "source_changed", "verification", "configuration"}


class BackupError(RuntimeError):
    """秘密や個人ファイル名を含めず表示できる停止理由。"""

    def __init__(self, kind: str, message: str):
        if kind not in SAFE_FAILURES:
            kind = "configuration"
        self.kind = kind
        super().__init__(message)


@dataclass(frozen=True)
class Summary:
    files: int
    bytes: int
    excluded_files: int = 0
    excluded_bytes: int = 0
    reparse_points: int = 0


@dataclass(frozen=True)
class FileRecord:
    relative: str
    size: int
    mtime_ns: int


def load_config(path: Path = CONFIG_PATH) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def is_within(path: Path, root: Path) -> bool:
    try:
        _resolved(path).relative_to(_resolved(root))
        return True
    except ValueError:
        return False


def validate_source(source: Path) -> Path:
    source = _resolved(source)
    if not source.is_dir():
        raise BackupError("configuration", "バックアップ元を確認できません。")
    return source


def validate_destination(destination: Path, source: Path) -> Path:
    destination = _resolved(destination)
    source = _resolved(source)
    if destination == source or is_within(destination, source):
        raise BackupError("configuration", "保存先をバックアップ元の内部には指定できません。")
    return destination


def validate_restore_destination(destination: Path, source: Path) -> Path:
    destination = _resolved(destination)
    if destination == _resolved(source) or is_within(destination, source):
        raise BackupError("configuration", "現在のLife_and_Divへ復元することは禁止されています。")
    return destination


def _is_reparse(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _filter_rules(path: Path = FILTER_PATH) -> list[tuple[bool, str]]:
    rules: list[tuple[bool, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if len(line) < 3 or line[0] not in "+-" or line[1] != " ":
            raise BackupError("configuration", "除外規則の形式が正しくありません。")
        rules.append((line[0] == "+", line[2:]))
    return rules


def included(relative: str, rules: Sequence[tuple[bool, str]] | None = None) -> bool:
    posix = PurePosixPath(relative.replace("\\", "/"))
    for allow, pattern in rules or _filter_rules():
        patterns = (pattern, pattern[3:]) if pattern.startswith("**/") else (pattern,)
        path_text = posix.as_posix().strip("/")
        matched = False
        for candidate in patterns:
            normalized = candidate.strip("/")
            if normalized.endswith("/**"):
                base = normalized[:-3].rstrip("/")
                if path_text == base or path_text.startswith(base + "/") or ("/" + base + "/") in ("/" + path_text + "/"):
                    matched = True
                    break
            elif posix.match(candidate):
                matched = True
                break
        if matched:
            return allow
    return True


def _required_parent(relative: str, rules: Sequence[tuple[bool, str]]) -> bool:
    prefix = relative.replace("\\", "/").strip("/") + "/"
    for allow, pattern in rules:
        if not allow:
            continue
        normalized = pattern.lstrip("/")
        static = re.split(r"[*?[]", normalized, maxsplit=1)[0]
        if static and static.startswith(prefix):
            return True
    return False


def inventory(source: Path, rules: Sequence[tuple[bool, str]] | None = None) -> tuple[list[FileRecord], Summary]:
    source = validate_source(source)
    rules = list(rules or _filter_rules())
    records: list[FileRecord] = []
    total = excluded_files = excluded_bytes = reparse = 0
    stack = [source]
    while stack:
        directory = stack.pop()
        for entry in os.scandir(directory):
            path = Path(entry.path)
            relative = path.relative_to(source).as_posix()
            if _is_reparse(path):
                reparse += 1
                continue
            if entry.is_dir(follow_symlinks=False):
                if included(relative + "/sentinel", rules) or _required_parent(relative, rules):
                    stack.append(path)
                else:
                    excluded_stack = [path]
                    while excluded_stack:
                        for child in os.scandir(excluded_stack.pop()):
                            child_path = Path(child.path)
                            if _is_reparse(child_path):
                                reparse += 1
                            elif child.is_dir(follow_symlinks=False):
                                excluded_stack.append(child_path)
                            elif child.is_file(follow_symlinks=False):
                                child_stat = child_path.stat()
                                excluded_files += 1
                                excluded_bytes += child_stat.st_size
                continue
            if not entry.is_file(follow_symlinks=False):
                continue
            item = path.stat()
            total += item.st_size
            if included(relative, rules):
                records.append(FileRecord(relative, item.st_size, item.st_mtime_ns))
            else:
                excluded_files += 1
                excluded_bytes += item.st_size
    return sorted(records, key=lambda row: row.relative), Summary(
        files=len(records), bytes=sum(row.size for row in records), excluded_files=excluded_files,
        excluded_bytes=excluded_bytes, reparse_points=reparse
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def copy_one_atomic(source: Path, destination: Path, expected: FileRecord, run_id: str) -> str:
    before = source.stat()
    if (before.st_size, before.st_mtime_ns) != (expected.size, expected.mtime_ns):
        raise BackupError("source_changed", "コピー開始前に対象ファイルが変更されました。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.phase4-part-{run_id}")
    try:
        shutil.copyfile(source, temporary)
        source_hash = sha256(source)
        copied_hash = sha256(temporary)
        after = source.stat()
        if (after.st_size, after.st_mtime_ns) != (expected.size, expected.mtime_ns) or source_hash != copied_hash:
            raise BackupError("source_changed", "コピー中の変更または内容不一致を検出しました。")
        os.replace(temporary, destination)
        return copied_hash
    finally:
        temporary.unlink(missing_ok=True)


def local_copy(source: Path, destination: Path, records: Sequence[FileRecord], run_id: str | None = None) -> Summary:
    source = validate_source(source)
    destination = validate_destination(destination, source)
    run_id = run_id or uuid.uuid4().hex
    if not RUN_ID_RE.fullmatch(run_id):
        raise BackupError("configuration", "実行IDの形式が正しくありません。")
    copied_files = copied_bytes = 0
    for record in records:
        relative = PurePosixPath(record.relative)
        if relative.is_absolute() or ".." in relative.parts:
            raise BackupError("configuration", "対象パスが許可範囲外です。")
        origin = source.joinpath(*relative.parts)
        target = destination.joinpath(*relative.parts)
        if target.exists() and target.is_file() and target.stat().st_size == record.size and sha256(target) == sha256(origin):
            continue
        copy_one_atomic(origin, target, record, run_id)
        copied_files += 1
        copied_bytes += record.size
    return Summary(copied_files, copied_bytes)


class RunLock(AbstractContextManager["RunLock"]):
    def __init__(self, path: Path):
        self.path = path
        self.fd: int | None = None

    def __enter__(self) -> "RunLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(self.fd, str(os.getpid()).encode("ascii"))
        except FileExistsError as exc:
            raise BackupError("configuration", "バックアップはすでに実行中です。") from exc
        return self

    def __exit__(self, *_args: object) -> None:
        if self.fd is not None:
            os.close(self.fd)
        self.path.unlink(missing_ok=True)


def snapshot_name(now: datetime) -> str:
    return now.strftime("%Y-%m")


def validate_snapshot_name(name: str) -> str:
    if not MONTH_RE.fullmatch(name):
        raise BackupError("configuration", "月次スナップショット名が安全なYYYY-MM形式ではありません。")
    return name


def retention_candidates(names: Iterable[str], keep: int = 12, latest_verified: bool = True) -> list[str]:
    if not latest_verified or keep < 1:
        return []
    names = list(names)
    if any(not MONTH_RE.fullmatch(name) for name in names) or len(names) <= keep:
        return []
    return sorted(names)[:-keep]


def create_monthly_snapshot(source: Path, monthly_root: Path, records: Sequence[FileRecord], month: str) -> tuple[Path, bool]:
    month = validate_snapshot_name(month)
    monthly_root = validate_destination(monthly_root, source)
    target = monthly_root / month
    marker = target / ".phase4-complete.json"
    if marker.is_file():
        return target, False
    local_copy(source, target, records)
    verify_local(source, target, records)
    marker.parent.mkdir(parents=True, exist_ok=True)
    temporary = marker.with_suffix(".tmp")
    temporary.write_text(json.dumps({"month": month, "files": len(records)}, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, marker)
    return target, True


def verify_local(source: Path, destination: Path, records: Sequence[FileRecord]) -> Summary:
    destination = validate_destination(destination, source)
    for record in records:
        relative = PurePosixPath(record.relative)
        target = destination.joinpath(*relative.parts)
        origin = source.joinpath(*relative.parts)
        if not target.is_file() or target.stat().st_size != record.size or sha256(target) != sha256(origin):
            raise BackupError("verification", "コピー後の件数・容量・ハッシュ検証に失敗しました。")
    return Summary(len(records), sum(row.size for row in records))


def restore_file(backup_file: Path, destination: Path, source_root: Path, expected_sha256: str) -> Path:
    destination = validate_restore_destination(destination, source_root)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / "phase4-restore-test.txt"
    shutil.copyfile(backup_file, target)
    if sha256(target) != expected_sha256:
        target.unlink(missing_ok=True)
        raise BackupError("verification", "復元後のハッシュが一致しません。")
    return target


def capacity_is_sufficient(free_bytes: int, total_bytes: int, planned_bytes: int, minimum_bytes: int, minimum_percent: int) -> bool:
    reserve = max(minimum_bytes, total_bytes * minimum_percent // 100)
    return free_bytes - planned_bytes >= reserve


def parse_rclone_about(payload: str) -> tuple[int, int]:
    try:
        value = json.loads(payload)
        return int(value["free"]), int(value["total"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise BackupError("capacity", "Google Driveの空き容量を安全に確認できません。") from exc


def rclone_copy_command(source: Path, remote: str, filter_path: Path = FILTER_PATH, dry_run: bool = False) -> list[str]:
    if not re.fullmatch(r"[A-Za-z0-9_-]+:[A-Za-z0-9_./-]+", remote) or ".." in remote:
        raise BackupError("configuration", "rclone保存先の形式が安全ではありません。")
    command = ["rclone", "copy", str(validate_source(source)), remote, "--filter-from", str(filter_path), "--skip-links", "--checkers", "8", "--transfers", "4", "--retries", "2", "--low-level-retries", "2", "--stats-one-line", "--log-level", "ERROR"]
    if dry_run:
        command.append("--dry-run")
    return command


def safe_notification_request(kind: str, run_id: str, occurred_at: str) -> dict[str, str]:
    if kind not in SAFE_FAILURES or not RUN_ID_RE.fullmatch(run_id) or not re.fullmatch(r"[0-9T:+-]{20,35}", occurred_at):
        raise BackupError("configuration", "通知依頼の形式が安全ではありません。")
    return {"failure_kind": kind, "backup_run_id": run_id, "occurred_at": occurred_at}


def write_state(path: Path, status: str, kind: str, run_id: str, summary: Summary | None = None) -> None:
    if status not in {"success", "failure"} or not RUN_ID_RE.fullmatch(run_id):
        raise BackupError("configuration", "状態記録の形式が正しくありません。")
    data: dict[str, object] = {"status": status, "failure_kind": kind if status == "failure" else "", "run_id": run_id, "recorded_at": datetime.now(timezone.utc).isoformat()}
    if summary:
        data.update({"files": summary.files, "bytes": summary.bytes})
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, path)


def task_xml(command: Path, working_directory: Path, remote: str, mode: str = "Daily") -> str:
    if mode not in {"Daily", "Monthly"}:
        raise BackupError("configuration", "タスク種別が正しくありません。")
    if not re.fullmatch(r"[A-Za-z0-9_-]+:[A-Za-z0-9_./-]+", remote) or ".." in remote:
        raise BackupError("configuration", "タスクのrclone保存先が安全ではありません。")
    command_text = str(command).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    work_text = str(working_directory).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    remote_text = remote.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    first_day = (datetime.now().astimezone().date() + timedelta(days=1)).isoformat()
    if mode == "Daily":
        trigger = f"<StartBoundary>{first_day}T02:00:00</StartBoundary><Enabled>true</Enabled><ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>"
    else:
        trigger = f"<StartBoundary>{first_day}T03:00:00</StartBoundary><Enabled>true</Enabled><ScheduleByMonth><DaysOfMonth><Day>1</Day></DaysOfMonth><Months><January/><February/><March/><April/><May/><June/><July/><August/><September/><October/><November/><December/></Months></ScheduleByMonth>"
    return f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers><CalendarTrigger>{trigger}</CalendarTrigger></Triggers>
  <Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>true</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><StartWhenAvailable>true</StartWhenAvailable><WakeToRun>true</WakeToRun><ExecutionTimeLimit>PT2H</ExecutionTimeLimit><RestartOnFailure><Interval>PT15M</Interval><Count>2</Count></RestartOnFailure></Settings>
  <Actions Context="Author"><Exec><Command>powershell.exe</Command><Arguments>-NoProfile -NonInteractive -ExecutionPolicy Bypass -File &quot;{command_text}&quot; -Mode {mode} -Remote &quot;{remote_text}&quot;</Arguments><WorkingDirectory>{work_text}</WorkingDirectory></Exec></Actions>
</Task>'''


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    inv = sub.add_parser("inventory")
    inv.add_argument("--source", type=Path, default=Path(str(load_config()["source"])))
    inv.add_argument("--filter", type=Path, default=FILTER_PATH)
    plan = sub.add_parser("rclone-plan")
    plan.add_argument("--source", type=Path, default=Path(str(load_config()["source"])))
    plan.add_argument("--remote", required=True)
    plan.add_argument("--dry-run", action="store_true")
    task = sub.add_parser("task-xml")
    task.add_argument("--remote", required=True)
    task.add_argument("--mode", required=True, choices=["Daily", "Monthly"])
    task.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "inventory":
            _records, summary = inventory(args.source, rules=_filter_rules(args.filter))
            print(json.dumps(asdict(summary), separators=(",", ":")))
        elif args.command == "rclone-plan":
            print(json.dumps(rclone_copy_command(args.source, args.remote, dry_run=args.dry_run), ensure_ascii=False))
        else:
            output = _resolved(args.output)
            if is_within(output, Path(str(load_config()["source"]))):
                raise BackupError("configuration", "タスク設定の出力先をバックアップ元内に指定できません。")
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = output.with_suffix(output.suffix + ".tmp")
            temporary.write_text(task_xml(PROJECT_ROOT / "scripts" / "run_phase4_backup.ps1", PROJECT_ROOT, args.remote, args.mode), encoding="utf-16")
            os.replace(temporary, output)
            print("Task XML generated without registration.")
        return 0
    except BackupError as exc:
        print(f"[BACKUP ERROR:{exc.kind}] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
