#!/usr/bin/env python3
"""Classify deployments, verify Pages, and send minimal Discord notifications."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping


SECRET_NAMES = {
    "publish": "DISCORD_WEBHOOK_PUBLISH",
    "error": "DISCORD_WEBHOOK_ERROR",
    "attention": "DISCORD_WEBHOOK_ATTENTION",
}
SAFE_SLUG = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:/[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*")
PUBLISH_SUBJECT = re.compile(r"publish: (.+)")
MAX_ATTEMPTS = 3
MAX_RETRY_DELAY_SECONDS = 10.0


class NotificationError(RuntimeError):
    """A safe-to-display notification error without secret values."""


@dataclass(frozen=True)
class Classification:
    kind: str
    slug: str = ""
    reason: str = ""


@dataclass(frozen=True)
class HttpResult:
    status: int
    headers: Mapping[str, str]


def _subject(commit_message: str) -> str:
    return commit_message.splitlines()[0].strip() if commit_message else ""


def is_safe_slug(slug: str) -> bool:
    return bool(SAFE_SLUG.fullmatch(slug))


def classify_deployment(event_name: str, commit_message: str, changed_paths: Iterable[str]) -> Classification:
    """Return publish/attention/none without trusting the commit message as a path."""
    if event_name != "push":
        return Classification("none")

    subject = _subject(commit_message)
    if not subject.startswith("publish:"):
        return Classification("none")

    match = PUBLISH_SUBJECT.fullmatch(subject)
    if not match:
        return Classification("attention", reason="公開用commitの形式を安全に解析できません")

    slug = match.group(1)
    if not is_safe_slug(slug):
        return Classification("attention", reason="記事slugが安全な形式ではありません")

    normalized = [path.replace("\\", "/").strip("/") for path in changed_paths if path.strip()]
    prefix = f"content/posts/{slug}/"
    if not normalized or any(not path.startswith(prefix) for path in normalized):
        return Classification("attention", reason="commitの変更範囲と記事slugが一致しません")

    return Classification("publish", slug=slug)


def build_payload(
    kind: str,
    *,
    repository: str,
    sha: str,
    event_name: str,
    run_url: str,
    page_url: str = "",
    article_url: str = "",
    slug: str = "",
    stage: str = "",
    reason: str = "",
    test_message: bool = False,
) -> dict[str, object]:
    short_sha = sha[:12] if sha else "不明"
    common = [f"Repository: {repository}", f"Trigger: {event_name}", f"Commit: {short_sha}", f"Actions: {run_url}"]

    if test_message:
        channel = {"publish": "公開通知", "error": "エラー通知", "attention": "要確認"}.get(kind)
        if not channel:
            raise ValueError(f"Unknown notification kind: {kind}")
        lines = ["【接続テスト】Phase 3のWebhook確認です。", f"通知先: {channel}", "実際の公開・失敗・要確認は発生していません。", *common]
    elif kind == "publish":
        lines = ["【公開成功】GitHub Pagesへの配置と記事URLを確認しました。", f"記事: {slug}", f"URL: {article_url}", *common]
    elif kind == "error":
        lines = ["【公開処理エラー】後続処理は開始していません。", f"失敗段階: {stage}", *common]
    elif kind == "attention":
        lines = ["【要確認】Pagesへの配置は完了しましたが、公開対象を安全に特定できません。", f"理由: {reason}", f"Pages: {page_url}", *common]
    else:
        raise ValueError(f"Unknown notification kind: {kind}")

    content = "\n".join(lines)
    if len(content) > 1900:
        raise NotificationError("通知内容が安全な上限を超えました。")
    return {
        "content": content,
        "allowed_mentions": {"parse": [], "roles": [], "users": [], "replied_user": False},
    }


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _discord_transport(webhook_url: str, body: bytes, timeout: float) -> HttpResult:
    request = urllib.request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "my-game-blog-notifier/1"},
        method="POST",
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=timeout) as response:
            return HttpResult(int(response.status), dict(response.headers.items()))
    except urllib.error.HTTPError as exc:
        return HttpResult(int(exc.code), dict(exc.headers.items()) if exc.headers else {})
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise NotificationError("Discordへの接続結果を確認できませんでした。重複防止のため再試行しません。") from exc


def _validate_discord_webhook(webhook_url: str) -> None:
    parsed = urllib.parse.urlsplit(webhook_url)
    if parsed.scheme != "https" or parsed.hostname not in {"discord.com", "discordapp.com"}:
        raise NotificationError("Webhookの設定形式が正しくありません。値は表示しません。")
    if not re.fullmatch(r"/api/webhooks/\d+/[A-Za-z0-9._-]+", parsed.path) or parsed.query or parsed.fragment:
        raise NotificationError("Webhookの設定形式が正しくありません。値は表示しません。")


def _retry_delay(result: HttpResult, attempt: int) -> float:
    if result.status == 429:
        raw = result.headers.get("Retry-After", "1")
        try:
            delay = float(raw)
        except (TypeError, ValueError):
            delay = 1.0
        return min(max(delay, 0.0), MAX_RETRY_DELAY_SECONDS)
    return min(float(2 ** (attempt - 1)), MAX_RETRY_DELAY_SECONDS)


def _is_retryable_status(status: int) -> bool:
    return status == 429 or 500 <= status <= 599


def send_notification(
    webhook_url: str,
    payload: Mapping[str, object],
    *,
    transport: Callable[[str, bytes, float], HttpResult] = _discord_transport,
    sleeper: Callable[[float], None] = time.sleep,
    validate_url: bool = True,
    timeout: float = 15.0,
) -> int:
    if validate_url:
        _validate_discord_webhook(webhook_url)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    for attempt in range(1, MAX_ATTEMPTS + 1):
        result = transport(webhook_url, body, timeout)
        if result.status in {200, 204}:
            return attempt
        if not _is_retryable_status(result.status) or attempt == MAX_ATTEMPTS:
            raise NotificationError(f"Discord通知に失敗しました（HTTP {result.status}、試行 {attempt} 回）。")
        sleeper(_retry_delay(result, attempt))
    raise AssertionError("unreachable")


def verify_pages(
    urls: Iterable[str],
    *,
    opener: Callable[[str, float], int],
    attempts: int = 12,
    sleeper: Callable[[float], None] = time.sleep,
) -> None:
    pending = list(dict.fromkeys(urls))
    for attempt in range(1, attempts + 1):
        failed: list[str] = []
        for url in pending:
            try:
                if opener(url, 20.0) != 200:
                    failed.append(url)
            except (urllib.error.URLError, TimeoutError, OSError):
                failed.append(url)
        if not failed:
            return
        pending = failed
        if attempt < attempts:
            sleeper(5.0)
    raise NotificationError("GitHub PagesのURL確認に失敗しました。応答本文は表示しません。")


def _url_status(url: str, timeout: float) -> int:
    request = urllib.request.Request(url, headers={"User-Agent": "my-game-blog-pages-check/1"}, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return int(response.status)


def determine_error_stage(build: str, deploy: str, verify: str, publish_notice: str, attention_notice: str) -> str:
    for label, result in (
        ("build", build),
        ("deploy", deploy),
        ("公開URL確認", verify),
        ("公開通知", publish_notice),
        ("要確認通知", attention_notice),
    ):
        if result in {"failure", "cancelled"}:
            return label
    return "不明"


def _git_text(arguments: list[str]) -> str:
    result = subprocess.run(["git", *arguments], check=True, capture_output=True, text=True, encoding="utf-8")
    return result.stdout


def _write_github_outputs(path: Path, values: Mapping[str, str]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for key, value in values.items():
            if "\n" in value or "\r" in value:
                raise NotificationError("Actions出力に改行を含む値は使用できません。")
            handle.write(f"{key}={value}\n")


def _run_classify(args: argparse.Namespace) -> None:
    message = _git_text(["show", "-s", "--format=%B", args.sha])
    before = args.before.strip()
    if args.event == "push" and re.fullmatch(r"[0-9a-fA-F]{40}", before) and set(before) != {"0"}:
        paths = _git_text(["diff", "--name-only", before, args.sha]).splitlines()
    else:
        paths = _git_text(["diff-tree", "--root", "--no-commit-id", "--name-only", "-r", args.sha]).splitlines()
    classification = classify_deployment(args.event, message, paths)
    _write_github_outputs(
        Path(args.output),
        {"notification_kind": classification.kind, "article_slug": classification.slug, "attention_reason": classification.reason},
    )
    print(f"Notification classification: {classification.kind}")


def _run_verify(args: argparse.Namespace) -> None:
    base_url = args.page_url.rstrip("/") + "/"
    urls = [base_url]
    if args.kind == "publish":
        if not is_safe_slug(args.slug):
            raise NotificationError("記事slugが安全な形式ではありません。")
        urls.append(urllib.parse.urljoin(base_url, f"posts/{args.slug}/"))
    verify_pages(urls, opener=_url_status)
    print(f"Pages URL verification succeeded ({len(urls)} URL).")


def _run_send(args: argparse.Namespace) -> None:
    secret_name = SECRET_NAMES[args.kind]
    webhook = os.environ.get(secret_name, "")
    if not webhook:
        raise NotificationError(f"GitHub Secret {secret_name} が設定されていません。値は表示しません。")
    stage = args.stage
    if args.kind == "error" and not stage:
        stage = determine_error_stage(
            args.build_result, args.deploy_result, args.verify_result, args.publish_notice_result, args.attention_notice_result
        )
    article_url = args.article_url
    if args.kind == "publish" and not article_url:
        base_url = args.page_url.rstrip("/") + "/"
        article_url = urllib.parse.urljoin(base_url, f"posts/{args.slug}/")
    payload = build_payload(
        args.kind,
        repository=args.repository,
        sha=args.sha,
        event_name=args.event,
        run_url=args.run_url,
        page_url=args.page_url,
        article_url=article_url,
        slug=args.slug,
        stage=stage,
        reason=args.reason,
        test_message=args.test_message,
    )
    attempts = send_notification(webhook, payload)
    print(f"Discord {args.kind} notification succeeded ({attempts} attempt(s)).")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    classify = subparsers.add_parser("classify")
    classify.add_argument("--event", required=True, choices=["push", "schedule", "workflow_dispatch"])
    classify.add_argument("--sha", required=True)
    classify.add_argument("--before", default="")
    classify.add_argument("--output", required=True)
    classify.set_defaults(func=_run_classify)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--page-url", required=True)
    verify.add_argument("--kind", required=True, choices=["publish", "attention", "none"])
    verify.add_argument("--slug", default="")
    verify.set_defaults(func=_run_verify)

    send = subparsers.add_parser("send")
    send.add_argument("--kind", required=True, choices=sorted(SECRET_NAMES))
    send.add_argument("--repository", required=True)
    send.add_argument("--sha", required=True)
    send.add_argument("--event", required=True)
    send.add_argument("--run-url", required=True)
    send.add_argument("--page-url", default="")
    send.add_argument("--article-url", default="")
    send.add_argument("--slug", default="")
    send.add_argument("--stage", default="")
    send.add_argument("--reason", default="")
    send.add_argument("--build-result", default="")
    send.add_argument("--deploy-result", default="")
    send.add_argument("--verify-result", default="")
    send.add_argument("--publish-notice-result", default="")
    send.add_argument("--attention-notice-result", default="")
    send.add_argument("--test-message", action="store_true")
    send.set_defaults(func=_run_send)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        args.func(args)
        return 0
    except (NotificationError, subprocess.CalledProcessError, ValueError) as exc:
        message = str(exc) if isinstance(exc, NotificationError) else "通知処理を安全に完了できませんでした。"
        print(f"[NOTIFICATION ERROR] {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
