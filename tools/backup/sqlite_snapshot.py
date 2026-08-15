"""Create and verify a consistent backup copy of the local admin SQLite DB."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path


class SnapshotError(RuntimeError):
    pass


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve()


def verify_database(path: Path) -> None:
    path = _resolved(path)
    if not path.is_file():
        raise SnapshotError("SQLite file was not found.")
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            result = connection.execute("PRAGMA quick_check").fetchone()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise SnapshotError("SQLite integrity verification failed.") from exc
    if result != ("ok",):
        raise SnapshotError("SQLite integrity verification failed.")


def create_snapshot(source: Path, output: Path) -> str:
    source = _resolved(source)
    output = _resolved(output)
    if not source.exists():
        if output.exists():
            raise SnapshotError("Source DB is missing while an older snapshot remains.")
        return "skipped"
    if not source.is_file() or source == output:
        raise SnapshotError("Invalid SQLite snapshot path.")

    verify_database(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        handle, name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
        os.close(handle)
        temporary = Path(name)
        source_connection = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
        destination_connection = sqlite3.connect(temporary)
        try:
            source_connection.backup(destination_connection)
        finally:
            destination_connection.close()
            source_connection.close()
        verify_database(temporary)
        os.replace(temporary, output)
        temporary = None
        verify_database(output)
        return "created"
    except (OSError, sqlite3.Error) as exc:
        raise SnapshotError("Could not create a consistent SQLite snapshot.") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def restore_to_staging(snapshot: Path, destination: Path, live_source: Path) -> None:
    snapshot = _resolved(snapshot)
    destination = _resolved(destination)
    live_source = _resolved(live_source)
    if destination == live_source or destination.parent == live_source.parent:
        raise SnapshotError("Restore destination must be outside the live DB directory.")
    verify_database(snapshot)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.restore.tmp")
    try:
        temporary.unlink(missing_ok=True)
        source_connection = sqlite3.connect(f"file:{snapshot.as_posix()}?mode=ro", uri=True)
        destination_connection = sqlite3.connect(temporary)
        try:
            source_connection.backup(destination_connection)
        finally:
            destination_connection.close()
            source_connection.close()
        verify_database(temporary)
        os.replace(temporary, destination)
        verify_database(destination)
    except (OSError, sqlite3.Error) as exc:
        raise SnapshotError("Could not restore the SQLite snapshot to staging.") from exc
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--source", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--snapshot", type=Path, required=True)
    restore = subparsers.add_parser("restore")
    restore.add_argument("--snapshot", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    restore.add_argument("--live-source", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            status = create_snapshot(args.source, args.output)
        elif args.command == "verify":
            verify_database(args.snapshot)
            status = "verified"
        else:
            restore_to_staging(args.snapshot, args.destination, args.live_source)
            status = "restored_to_staging"
        print(json.dumps({"status": status}, ensure_ascii=False))
        return 0
    except SnapshotError as exc:
        print(json.dumps({"status": "failure", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
