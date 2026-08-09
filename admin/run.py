"""固定された安全な設定で管理画面を起動する。"""

from __future__ import annotations

import atexit
import os
from pathlib import Path

import uvicorn


HOST = "127.0.0.1"
PORT = 8765
PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = PROJECT_ROOT / "var" / "admin" / "admin.lock"
_lock_handle = None


def acquire_single_instance() -> None:
    global _lock_handle
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle = LOCK_PATH.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise RuntimeError("管理画面はすでに起動しています。") from exc
    _lock_handle = handle


def release_single_instance() -> None:
    global _lock_handle
    if _lock_handle is None:
        return
    try:
        if os.name == "nt":
            import msvcrt
            _lock_handle.seek(0)
            msvcrt.locking(_lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(_lock_handle.fileno(), fcntl.LOCK_UN)
    finally:
        _lock_handle.close()
        _lock_handle = None
        LOCK_PATH.unlink(missing_ok=True)


def main() -> None:
    acquire_single_instance()
    atexit.register(release_single_instance)
    print(f"管理画面を起動します: http://{HOST}:{PORT}/")
    print("終了するには Ctrl+C を押してください。")
    uvicorn.run("admin.app:app", host=HOST, port=PORT, access_log=False)


if __name__ == "__main__":
    main()
