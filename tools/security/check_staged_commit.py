"""Gitへ登録する直前のファイルから秘密情報とローカル専用データを検出する。"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MAX_TEXT_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class Finding:
    path: str
    reason: str


FORBIDDEN_PATH_PATTERNS = (
    (re.compile(r"(?:^|/)review-report\.md$", re.IGNORECASE), "校正記録 review-report.md"),
    (re.compile(r"(?:^|/)\.env(?:\..+)?$", re.IGNORECASE), "環境変数ファイル"),
    (re.compile(r"^(?:var|backup-source)/", re.IGNORECASE), "ローカル専用データ"),
    (re.compile(r"\.(?:p12|pfx)$", re.IGNORECASE), "秘密鍵を含む可能性が高いファイル"),
)

CONTENT_PATTERNS = (
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), "秘密鍵"),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b"), "GitHub token"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b"), "GitHub fine-grained token"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"), "Google API key"),
    (re.compile(r"\bapify_api_[A-Za-z0-9]{20,}\b", re.IGNORECASE), "Apify API token"),
    (re.compile(r"https://(?:canary\.)?discord(?:app)?\.com/api/webhooks/\d{10,}/[A-Za-z0-9._-]{20,}", re.IGNORECASE), "Discord webhook URL"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"), "Slack token"),
    (re.compile(r"(?i)\bSTEAM_WEB_API_KEY\b\s*[:=]\s*['\"]?[0-9a-f]{32}\b"), "Steam Web API key"),
    (re.compile(r"(?i)\bC:[\\/]Users[\\/](?!<(?:user|username)>)([A-Za-z0-9._-]+)[\\/]"), "Windowsの個人ユーザーパス"),
    (re.compile(r"(?i)(?:^|[\s'\"])/(?:Users|home)/(?!<(?:user|username)>)([A-Za-z0-9._-]+)/"), "個人ホームディレクトリの絶対パス"),
)


class GitReadError(RuntimeError):
    pass


def _git(args: list[str], *, input_bytes: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", *args], cwd=PROJECT_ROOT, input=input_bytes, capture_output=True, check=False
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise GitReadError(message or "Gitの検査に失敗しました。")
    return result.stdout


def candidate_paths(all_tracked: bool = False) -> list[str]:
    args = ["ls-files", "-z"] if all_tracked else ["diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"]
    return [item.decode("utf-8", errors="surrogateescape") for item in _git(args).split(b"\0") if item]


def staged_bytes(path: str, all_tracked: bool = False) -> bytes:
    return _git(["show", f":{path}"])


def is_gitlink(path: str) -> bool:
    return _git(["ls-files", "-s", "--", path]).startswith(b"160000 ")


def inspect_path(path: str, data: bytes) -> list[Finding]:
    normalized = path.replace("\\", "/")
    findings = [Finding(normalized, reason) for pattern, reason in FORBIDDEN_PATH_PATTERNS if pattern.search(normalized)]
    if findings or len(data) > MAX_TEXT_BYTES or b"\0" in data:
        return findings
    text = data.decode("utf-8", errors="replace")
    for pattern, reason in CONTENT_PATTERNS:
        if pattern.search(text):
            findings.append(Finding(normalized, reason))
    return findings


def scan(all_tracked: bool = False) -> list[Finding]:
    findings: list[Finding] = []
    for path in candidate_paths(all_tracked):
        try:
            if is_gitlink(path):
                continue
            data = staged_bytes(path, all_tracked)
        except GitReadError:
            findings.append(Finding(path, "登録内容を安全に読み取れません"))
            continue
        findings.extend(inspect_path(path, data))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Git登録内容の安全検査")
    parser.add_argument("--all-tracked", action="store_true", help="HEADの全追跡ファイルを検査する")
    args = parser.parse_args(argv)
    try:
        findings = scan(args.all_tracked)
    except GitReadError as exc:
        print(f"安全検査を実行できませんでした: {exc}", file=sys.stderr)
        return 2
    if findings:
        print("commitを停止しました。次の公開対象外情報を確認してください:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding.path}: {finding.reason}", file=sys.stderr)
        print("値を削除してから再度commitしてください。検査の無効化は推奨しません。", file=sys.stderr)
        return 1
    print("Git登録内容の安全検査に合格しました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
