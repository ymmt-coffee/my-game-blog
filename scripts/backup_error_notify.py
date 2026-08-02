#!/usr/bin/env python3
"""固定フィールドだけでPhase 4バックアップ失敗をDiscordへ通知する。"""

from __future__ import annotations

import argparse
import os
import sys

from discord_notify import NotificationError, send_notification
from phase4_backup import BackupError, safe_notification_request


def fields() -> dict[str, str]:
    return safe_notification_request(
        os.environ.get("FAILURE_KIND", ""), os.environ.get("BACKUP_RUN_ID", ""), os.environ.get("OCCURRED_AT", "")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate", "send"])
    args = parser.parse_args()
    try:
        values = fields()
        if args.command == "validate":
            print("Backup failure fields are safe.")
            return 0
        webhook = os.environ.get("DISCORD_WEBHOOK_ERROR", "")
        if not webhook:
            raise NotificationError("GitHub Secret DISCORD_WEBHOOK_ERROR が設定されていません。値は表示しません。")
        run_url = os.environ.get("ACTIONS_RUN_URL", "")
        heading = (
            "【接続テスト】Google Driveバックアップのエラー通知経路を確認しました。"
            if values["failure_kind"] == "connection_test"
            else "【バックアップエラー】Google Driveバックアップを完了できませんでした。"
        )
        payload = {
            "content": "\n".join((
                heading,
                f"失敗種別: {values['failure_kind']}", f"日時: {values['occurred_at']}",
                f"バックアップ実行ID: {values['backup_run_id']}", f"確認手順: {run_url}",
            )),
            "allowed_mentions": {"parse": [], "roles": [], "users": [], "replied_user": False},
        }
        send_notification(webhook, payload)
        print("Backup error notification succeeded.")
        return 0
    except (BackupError, NotificationError) as exc:
        print(f"[BACKUP NOTIFICATION ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
