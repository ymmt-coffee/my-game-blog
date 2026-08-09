"""管理画面用の校正、プレビュー、公開前検査、記事限定公開。"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.request import urlopen

import frontmatter

from admin import article_templates, articles
from tools.publishing import review_article, sync_diary, validate_blog


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BLOG_ROOT = PROJECT_ROOT / "blog"
BLOG_CONTENT = BLOG_ROOT / "content"
PUBLIC_POSTS = BLOG_CONTENT / "posts"
PAGES_URL = "https://ymmt-coffee.github.io/my-game-blog/"
REPOSITORY = "ymmt-coffee/my-game-blog"
CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class PublishError(RuntimeError):
    """公開を安全停止する利用者向けエラー。"""


@dataclass(frozen=True)
class CheckResult:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    preview_url: str = ""

    @property
    def ok(self) -> bool:
        return not self.errors


def run_command(args: list[str], *, cwd: Path = PROJECT_ROOT, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, cwd=cwd, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PublishError("固定コマンドの実行に失敗または時間切れになりました。") from exc


def review_paths(state_root: Path, article_id: str) -> tuple[Path, Path]:
    root = state_root / "reviews" / article_id
    return root / "latest.md", root / "latest.json"


def perform_review(article: articles.ArticleFile, state_root: Path, supplier: Callable[[dict[str, object]], object] | None = None) -> dict[str, object]:
    index = article.path / "index.md"
    before = articles.file_hash(index)
    request = review_article.build_request(article.slug, index, "sha256:" + before)
    response = review_article.validate_response((supplier or review_article.call_gemini)(request))
    if articles.file_hash(index) != before:
        raise PublishError("校正中に原稿が変更されたため停止しました。")
    reviewed_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    method = "test stub" if supplier else review_article.GEMINI_METHOD
    report = review_article.render_report(article.slug, "sha256:" + before, method, response, reviewed_at)
    report = report.replace("本文の変更はObsidianでユーザーが行います。", "本文は自動変更しません。採用する修正だけを管理画面でユーザーが反映します。")
    payload = {"article_id": article.article_id, "slug": article.slug, "file_hash": before, "reviewed_at": reviewed_at, "method": method, "response": response, "decisions": {}}
    report_path, json_path = review_paths(state_root, article.article_id)
    articles.atomic_write(report_path, report.encode("utf-8"))
    articles.atomic_write(json_path, (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    if articles.file_hash(index) != before:
        raise PublishError("校正結果の保存中に原稿が変更されたため停止しました。")
    return payload


def load_review(state_root: Path, article: articles.ArticleFile) -> dict[str, object] | None:
    _report, path = review_paths(state_root, article.article_id)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PublishError("校正結果を安全に読み込めません。") from exc
    if value.get("article_id") != article.article_id or value.get("slug") != article.slug:
        raise PublishError("校正結果の対象記事が一致しません。")
    return value


def finding_keys(review: dict[str, object]) -> list[str]:
    keys: list[str] = []
    response = review.get("response", {})
    for category in response.get("categories", []):
        for index, _finding in enumerate(category.get("findings", [])):
            keys.append(f"{category['id']}:{index}")
    return keys


def save_decision(state_root: Path, article: articles.ArticleFile, finding_key: str, decision: str) -> None:
    if decision not in {"accepted", "rejected"}:
        raise PublishError("指摘の判断が正しくありません。")
    review = load_review(state_root, article)
    if review is None or review.get("file_hash") != article.file_hash:
        raise PublishError("現在の原稿に対応する校正結果がありません。")
    if finding_key not in finding_keys(review):
        raise PublishError("指定した校正指摘が見つかりません。")
    review.setdefault("decisions", {})[finding_key] = decision
    _report, path = review_paths(state_root, article.article_id)
    articles.atomic_write(path, (json.dumps(review, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def review_is_complete(state_root: Path, article: articles.ArticleFile) -> bool:
    review = load_review(state_root, article)
    if review is None or review.get("file_hash") != article.file_hash:
        return False
    return set(finding_keys(review)) <= set(review.get("decisions", {}))


def _copy_blog_content(destination: Path) -> None:
    shutil.copytree(BLOG_CONTENT, destination)


def _temporary_source(article: articles.ArticleFile, root: Path, publishable: bool) -> Path:
    source = root / "source" / article.slug
    shutil.copytree(article.path, source)
    if publishable:
        post = frontmatter.load(source / "index.md")
        post.metadata["draft"] = False
        articles.atomic_write(source / "index.md", articles.render_markdown(dict(post.metadata), post.content))
    return root / "source"


def _sync_article(article: articles.ArticleFile, source_root: Path, output_posts: Path, publishable: bool) -> None:
    candidates = sync_diary.collect_articles(source_root)
    selected = [item for item in candidates if item.slug == article.slug]
    if len(selected) != 1:
        raise PublishError("同期対象の記事を一意に特定できません。")
    try:
        sync_diary.convert_article(selected[0], output_posts, publishable, False)
    except sync_diary.SyncError as exc:
        raise PublishError(str(exc)) from exc


def _validate(content: Path, slug: str, production: bool, public: Path | None = None) -> CheckResult:
    report = validate_blog.Report()
    validate_blog.validate_content(content, slug, production, report)
    if public is not None:
        validate_blog.validate_public(public, report)
    return CheckResult(tuple(report.errors), tuple(report.warnings))


def build_preview(article: articles.ArticleFile, state_root: Path, runner: CommandRunner = run_command) -> CheckResult:
    root = state_root / "previews" / article.article_id
    staging = Path(tempfile.mkdtemp(prefix="preview-", dir=state_root))
    try:
        content = staging / "content"
        public = staging / "public"
        _copy_blog_content(content)
        source_root = _temporary_source(article, staging, False)
        _sync_article(article, source_root, content / "posts", False)
        checked = _validate(content, article.slug, False)
        if not checked.ok:
            return checked
        result = runner(["hugo", "--source", str(BLOG_ROOT), "--buildDrafts", "--contentDir", str(content), "--destination", str(public), "--cleanDestinationDir", "--baseURL", f"http://127.0.0.1:8765/previews/{article.article_id}/"], cwd=PROJECT_ROOT, timeout=120)
        if result.returncode != 0:
            return CheckResult(("Hugoプレビューの生成に失敗しました。",), checked.warnings)
        if root.exists():
            shutil.rmtree(root)
        root.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(public), root)
        return CheckResult((), checked.warnings, f"/previews/{article.article_id}/posts/{article.slug}/")
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def prepublish_check(article: articles.ArticleFile, state_root: Path, runner: CommandRunner = run_command) -> tuple[CheckResult, Path | None]:
    metadata_errors = article_templates.validate_metadata(article.metadata)
    if metadata_errors:
        return CheckResult(tuple(metadata_errors), ()), None
    try:
        review_article.require_no_secrets((article.path / "index.md").read_text(encoding="utf-8"), "原稿")
    except review_article.ReviewError as exc:
        return CheckResult((str(exc),), ()), None
    if not review_is_complete(state_root, article):
        return CheckResult(("現在の原稿に対応する校正と、全指摘の採否確認が必要です。",), ()), None
    staging = Path(tempfile.mkdtemp(prefix="publish-check-", dir=state_root))
    content = staging / "content"
    public = staging / "public"
    try:
        _copy_blog_content(content)
        source_root = _temporary_source(article, staging, True)
        _sync_article(article, source_root, content / "posts", True)
        checked = _validate(content, article.slug, True)
        if not checked.ok:
            return checked, None
        result = runner(["hugo", "--source", str(BLOG_ROOT), "--minify", "--environment", "production", "--contentDir", str(content), "--destination", str(public), "--cleanDestinationDir"], cwd=PROJECT_ROOT, timeout=120)
        if result.returncode != 0:
            return CheckResult(("Hugo本番ビルドに失敗しました。",), checked.warnings), None
        final = _validate(content, article.slug, True, public)
        if not final.ok:
            return final, None
        prepared = state_root / "publish-prepared" / article.article_id / article.file_hash
        if prepared.exists():
            shutil.rmtree(prepared)
        prepared.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(content / "posts" / article.slug, prepared)
        return final, prepared
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def approval_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_matches(token: str, expected_hash: str) -> bool:
    return secrets.compare_digest(hashlib.sha256(token.encode("utf-8")).hexdigest(), expected_hash)


def publish_article(article: articles.ArticleFile, prepared: Path, runner: CommandRunner = run_command) -> tuple[str, str]:
    if not prepared.is_dir() or prepared.name != article.file_hash:
        raise PublishError("公開前チェック済みのコピーが見つかりません。")
    staged = runner(["git", "diff", "--cached", "--quiet"], timeout=30)
    if staged.returncode != 0:
        raise PublishError("すでに登録済みの変更があるため公開を停止しました。")
    destination = PUBLIC_POSTS / article.slug
    backup = destination.with_name(destination.name + ".publish-backup")
    committed = False
    try:
        unexpected = []
        for path in article.path.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(article.path)
            allowed_file = relative.as_posix() == "index.md" or (
                len(relative.parts) >= 2 and relative.parts[0] == "images" and path.suffix.casefold() in articles.IMAGE_EXTENSIONS
            )
            if not allowed_file:
                unexpected.append(relative.as_posix())
        if unexpected:
            raise PublishError("記事フォルダーに公開対象外ファイルがあります。review-reportや個人メモは登録しません。")
        public_rel = destination.relative_to(PROJECT_ROOT).as_posix()
        existing = runner(["git", "status", "--porcelain", "--", public_rel], timeout=30)
        if existing.returncode != 0 or existing.stdout.strip():
            raise PublishError("公開用コピーに未コミット変更があるため上書きを停止しました。")
        if backup.exists():
            shutil.rmtree(backup)
        if destination.exists():
            destination.rename(backup)
        shutil.copytree(prepared, destination)
        source_rel = article.path.relative_to(PROJECT_ROOT).as_posix()
        source_index = f"{source_rel}/index.md"
        source_images = f"{source_rel}/images"
        result = runner(["git", "add", "-A", "--", source_index, source_images, public_rel], timeout=30)
        if result.returncode != 0:
            raise PublishError("対象記事をGitへ登録できませんでした。")
        names = runner(["git", "diff", "--cached", "--name-only"], timeout=30)
        allowed = (source_rel + "/", public_rel + "/")
        changed = [line.strip().replace("\\", "/") for line in names.stdout.splitlines() if line.strip()]
        if not changed or any(not path.startswith(allowed) for path in changed):
            raise PublishError("対象記事以外の変更が混ざったため公開を停止しました。")
        committed = runner(["git", "commit", "-m", f"publish: {article.slug}", "--", source_index, source_images, public_rel], timeout=60)
        if committed.returncode != 0:
            raise PublishError("記事のcommitに失敗しました。")
        committed = True
        if backup.exists():
            shutil.rmtree(backup)
        pushed = runner(["git", "push", "origin", "main"], timeout=120)
        if pushed.returncode != 0:
            raise PublishError("commitは完了しましたがpushに失敗しました。")
        sha = runner(["git", "rev-parse", "HEAD"], timeout=30).stdout.strip()
        pages = wait_for_pages(sha, runner)
        if backup.exists():
            shutil.rmtree(backup)
        return sha, pages
    except Exception:
        if not committed:
            runner(["git", "restore", "--staged", "--", str(article.path.relative_to(PROJECT_ROOT)), str(destination.relative_to(PROJECT_ROOT))], timeout=30)
            if destination.exists():
                shutil.rmtree(destination)
            if backup.exists():
                backup.rename(destination)
        raise


def wait_for_pages(commit_sha: str, runner: CommandRunner = run_command) -> str:
    for _ in range(120):
        result = runner(["gh", "run", "list", "--repo", REPOSITORY, "--workflow", "hugo.yml", "--event", "push", "--commit", commit_sha, "--limit", "1", "--json", "status,conclusion,url"], timeout=30)
        if result.returncode != 0:
            raise PublishError("GitHub Pagesの状態を確認できません。")
        try:
            runs = json.loads(result.stdout or "[]")
        except json.JSONDecodeError as exc:
            raise PublishError("GitHub Pagesの応答を確認できません。") from exc
        if runs and runs[0].get("status") == "completed":
            if runs[0].get("conclusion") != "success":
                raise PublishError("GitHub Pagesの公開に失敗しました。")
            try:
                with urlopen(PAGES_URL, timeout=30) as response:
                    if response.status != 200:
                        raise PublishError("公開URLが正常応答を返しませんでした。")
            except PublishError:
                raise
            except Exception as exc:
                raise PublishError("Pagesは完了しましたが公開URLを確認できませんでした。") from exc
            return str(runs[0].get("url") or PAGES_URL)
        time.sleep(5)
    raise PublishError("GitHub Pagesの完了確認が時間切れになりました。")


def new_attempt_values() -> tuple[str, str, str, str]:
    attempt_id = uuid.uuid4().hex
    token, token_hash = approval_token()
    expires = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(timespec="seconds")
    return attempt_id, token, token_hash, expires
