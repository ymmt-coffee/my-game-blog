#!/usr/bin/env python3
"""Send a minimal weekly-research summary and PDF to a dedicated Discord webhook."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


SECRET_NAME = "DISCORD_WEBHOOK_WEEKLY_RESEARCH"
MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_ATTEMPTS = 3
CONNECTION_TEST_SUMMARY = {
    "content": "【接続テスト】週次リサーチWebhook\nWebhookとPDF添付を確認しています。実記事の通知ではありません。",
    "allowed_mentions": {"parse": [], "users": [], "roles": [], "replied_user": False},
}


class NotifyError(RuntimeError):
    pass


@dataclass(frozen=True)
class HttpResult:
    status: int


def validate_webhook(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {"discord.com", "canary.discord.com", "ptb.discord.com"}:
        raise NotifyError("Discord Webhookの接続先が不正です")
    if not re.fullmatch(r"/api/webhooks/\d+/[A-Za-z0-9._-]+", parsed.path) or parsed.query or parsed.fragment:
        raise NotifyError("Discord Webhookの形式が不正です")


def load_summary(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NotifyError("Discord要約を安全に読み取れません") from exc
    if not isinstance(value, dict) or set(value) != {"content", "allowed_mentions"}:
        raise NotifyError("Discord要約の形式が不正です")
    content = value.get("content")
    if not isinstance(content, str) or not content.strip() or len(content) > 1500:
        raise NotifyError("Discord要約の長さが不正です")
    if value.get("allowed_mentions") != {"parse": [], "users": [], "roles": [], "replied_user": False}:
        raise NotifyError("Discordのメンション無効化を確認できません")
    return value


def multipart_body(summary: dict[str, Any], pdf_path: Path, boundary: str | None = None) -> tuple[bytes, str]:
    try:
        pdf = pdf_path.read_bytes()
    except OSError as exc:
        raise NotifyError("Discord添付PDFを読み取れません") from exc
    if not pdf.startswith(b"%PDF") or not 0 < len(pdf) <= MAX_PDF_BYTES:
        raise NotifyError("Discord添付PDFの形式またはサイズが不正です")
    token = boundary or ("codex-" + secrets.token_hex(16))
    payload = json.dumps(summary, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    chunks = [
        f"--{token}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\nContent-Type: application/json; charset=utf-8\r\n\r\n".encode(), payload, b"\r\n",
        f"--{token}\r\nContent-Disposition: form-data; name=\"files[0]\"; filename=\"weekly-research.pdf\"\r\nContent-Type: application/pdf\r\n\r\n".encode(), pdf, b"\r\n",
        f"--{token}--\r\n".encode(),
    ]
    return b"".join(chunks), f"multipart/form-data; boundary={token}"


def discord_transport(url: str, body: bytes, content_type: str, timeout: float) -> HttpResult:
    request = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": content_type, "User-Agent": "my-game-blog-weekly-research/1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return HttpResult(response.status)
    except urllib.error.HTTPError as exc:
        return HttpResult(exc.code)


def send(webhook: str, summary: dict[str, Any], pdf: Path, transport: Callable[[str, bytes, str, float], HttpResult] = discord_transport, sleeper: Callable[[float], None] = time.sleep) -> int:
    validate_webhook(webhook)
    body, content_type = multipart_body(summary, pdf)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = transport(webhook, body, content_type, 20.0)
        except Exception as exc:
            raise NotifyError("Discordへの接続結果を確認できませんでした。重複防止のため再試行しません") from exc
        if result.status in {200, 204}:
            return attempt
        if result.status == 429 or 500 <= result.status <= 599:
            if attempt < MAX_ATTEMPTS:
                sleeper(float(attempt))
                continue
        raise NotifyError(f"Discord週次リサーチ通知に失敗しました（HTTP {result.status}、試行 {attempt} 回）")
    raise NotifyError("Discord週次リサーチ通知を完了できませんでした")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--connection-test", action="store_true", help="固定の接続テスト文面で送信します")
    args = parser.parse_args(argv)
    try:
        webhook = os.environ.get(SECRET_NAME, "")
        if not webhook:
            raise NotifyError(f"{SECRET_NAME}が未設定です。値は表示しません")
        summary = CONNECTION_TEST_SUMMARY if args.connection_test else load_summary(args.summary)
        attempts = send(webhook, summary, args.pdf)
        print(f"Discord週次リサーチ通知に成功しました（{attempts}回目）")
        return 0
    except NotifyError as exc:
        print(f"停止: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
