"""記事ファイルを通常のMarkdownとして安全に管理する。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import BinaryIO

import frontmatter

from admin import article_templates


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTENT_ROOT = PROJECT_ROOT / "content" / "articles"
DEFAULT_STATE_ROOT = PROJECT_ROOT / "var" / "admin"
LEGACY_ROOT = Path(r"C:\Users\ymmt_\Documents\Life_and_Div\30_Projects\01_blog")
SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
TAB_RE = re.compile(r"[A-Za-z0-9_-]{8,80}")
IMAGE_EXTENSIONS = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
STATES = {"draft", "review_pending", "ready", "scheduled", "published", "archived"}
ARTICLE_TYPES = frozenset(article_templates.TEMPLATES)


class ArticleError(RuntimeError):
    """利用者へ安全に表示できる記事操作エラー。"""


class ArticleConflict(ArticleError):
    """別タブまたは外部変更による保存競合。"""


@dataclass(frozen=True)
class ArticleFile:
    article_id: str
    slug: str
    path: Path
    metadata: dict[str, object]
    body: str
    file_hash: str


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_hash(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def validate_slug(slug: str) -> str:
    slug = slug.strip().lower()
    if not SLUG_RE.fullmatch(slug):
        raise ArticleError("slugは半角小文字・数字・ハイフンだけで入力してください。")
    return slug


def next_daily_slug(content_root: Path, day: date | None = None) -> str:
    """Return YYYYMMDD-NNN using the next unused number for that day."""
    content_root.mkdir(parents=True, exist_ok=True)
    prefix = (day or date.today()).strftime("%Y%m%d")
    pattern = re.compile(rf"{prefix}-(\d{{3}})")
    used = {
        int(match.group(1))
        for path in content_root.iterdir() if path.is_dir()
        if (match := pattern.fullmatch(path.name))
    }
    number = 1
    while number in used:
        number += 1
    if number > 999:
        raise ArticleError("本日作成できる記事番号の上限に達しました。")
    return f"{prefix}-{number:03d}"


def validate_article_type(article_type: str) -> str:
    if article_type not in ARTICLE_TYPES:
        raise ArticleError("カテゴリーが正しくありません。")
    return article_type


def article_dir(content_root: Path, slug: str) -> Path:
    slug = validate_slug(slug)
    root = content_root.resolve()
    result = (root / slug).resolve()
    if result.parent != root:
        raise ArticleError("記事の保存場所が許可範囲外です。")
    return result


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def render_markdown(metadata: dict[str, object], body: str) -> bytes:
    post = frontmatter.Post(body.rstrip() + "\n", **metadata)
    return frontmatter.dumps(post).replace("\r\n", "\n").encode("utf-8")


def read_article(path: Path, article_id: str, slug: str) -> ArticleFile:
    index_path = path / "index.md"
    try:
        raw = index_path.read_bytes()
        post = frontmatter.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ArticleError("記事ファイルを読み込めません。元ファイルは変更していません。") from exc
    return ArticleFile(article_id, slug, path, dict(post.metadata), post.content, sha256_bytes(raw))


def create_article_files(
    content_root: Path,
    slug: str,
    title: str,
    article_type: str,
    author: str,
    description: str = "",
    play_time: str = "",
    game_completed: bool = False,
) -> tuple[str, Path, str]:
    slug = validate_slug(slug)
    article_type = validate_article_type(article_type)
    title = title.strip()
    author = author.strip()
    description = description.strip()
    if not title or not author or not description:
        raise ArticleError("タイトル、概要、著者を入力してください。")
    if article_type == "play_note" and not play_time.strip():
        raise ArticleError("プレイログではプレイ時間を入力してください。")
    target = article_dir(content_root, slug)
    if target.exists():
        raise ArticleError("同じslugの記事がすでにあります。")
    article_id = uuid.uuid5(uuid.NAMESPACE_URL, f"my-game-blog:{slug}").hex
    metadata = article_templates.initial_metadata(
        title, article_type, author, description, play_time, game_completed
    )
    target.mkdir(parents=True)
    try:
        (target / "images").mkdir()
        data = render_markdown(metadata, article_templates.get_template(article_type).body)
        atomic_write(target / "index.md", data)
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return article_id, target, sha256_bytes(data)


def updated_markdown(
    article: ArticleFile,
    *,
    title: str,
    description: str,
    article_type: str,
    body: str,
    play_time: str = "",
    game_completed: bool = False,
) -> bytes:
    title = title.strip()
    if not title:
        raise ArticleError("タイトルを入力してください。")
    validate_article_type(article_type)
    metadata = dict(article.metadata)
    metadata.update(
        {
            "title": title,
            "description": description.strip(),
            "article_type": article_type,
            "lastmod": date.today().isoformat(),
            "draft": True,
        }
    )
    if article_type == "play_note":
        metadata["play_time"] = play_time.strip()
        metadata["game_completed"] = game_completed
    else:
        metadata.pop("play_time", None)
        metadata.pop("game_completed", None)
    return render_markdown(metadata, body)


def header_image_name(article: ArticleFile) -> str:
    cover = article.metadata.get("cover")
    if not isinstance(cover, dict):
        return ""
    value = str(cover.get("image") or "")
    if not value.startswith("images/"):
        return ""
    name = Path(value).name
    return name if value == f"images/{name}" else ""


def updated_header_image_markdown(article: ArticleFile, image_name: str | None) -> bytes:
    metadata = dict(article.metadata)
    cover_value = metadata.get("cover")
    cover = dict(cover_value) if isinstance(cover_value, dict) else {}
    if image_name:
        if Path(image_name).name != image_name or Path(image_name).suffix.casefold() not in IMAGE_EXTENSIONS:
            raise ArticleError("ヘッダー画像名が正しくありません。")
        if not (article.path / "images" / image_name).is_file():
            raise ArticleError("指定した画像が見つかりません。")
        cover.update({"image": f"images/{image_name}", "alt": Path(image_name).stem})
        metadata["cover"] = cover
    else:
        cover.pop("image", None)
        cover.pop("alt", None)
        if cover:
            metadata["cover"] = cover
        else:
            metadata.pop("cover", None)
    metadata["lastmod"] = date.today().isoformat()
    metadata["draft"] = True
    return render_markdown(metadata, article.body)


def save_autosave(state_root: Path, article_id: str, tab_id: str, data: bytes) -> Path:
    if not TAB_RE.fullmatch(tab_id):
        raise ArticleError("編集画面の識別情報が正しくありません。")
    target = state_root / "autosave" / article_id / f"{tab_id}.md"
    atomic_write(target, data)
    return target


def save_history(state_root: Path, article_id: str, current: bytes, revision: int) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = state_root / "history" / article_id / f"r{revision:06d}-{timestamp}.md"
    atomic_write(target, current)
    return target


def commit_article(
    article: ArticleFile,
    data: bytes,
    state_root: Path,
    expected_hash: str,
    revision: int,
) -> tuple[str, Path]:
    index_path = article.path / "index.md"
    current = index_path.read_bytes()
    actual_hash = sha256_bytes(current)
    if actual_hash != expected_hash or actual_hash != article.file_hash:
        raise ArticleConflict("別の画面または外部アプリで記事が変更されました。保存を停止しました。")
    history_path = save_history(state_root, article.article_id, current, revision)
    atomic_write(index_path, data)
    if index_path.read_bytes() != data:
        raise ArticleError("保存後の確認に失敗しました。履歴から復元できます。")
    return sha256_bytes(data), history_path


def list_images(article: ArticleFile) -> list[dict[str, object]]:
    root = article.path / "images"
    if not root.exists():
        return []
    return [
        {"name": path.name, "size": path.stat().st_size}
        for path in sorted(root.iterdir(), key=lambda item: item.name.casefold())
        if path.is_file()
    ]


def safe_image_filename(filename: str) -> str:
    original = Path(filename.replace("\\", "/")).name
    extension = Path(original).suffix.casefold()
    if extension not in IMAGE_EXTENSIONS:
        raise ArticleError("対応している画像形式はJPG、PNG、GIF、WebP、AVIFです。")
    normalized = unicodedata.normalize("NFKC", Path(original).stem)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", normalized).strip(".-_").lower()
    if not stem:
        stem = "image-" + sha256_bytes(original.encode("utf-8"))[:8]
    maximum = 120 - len(extension)
    return stem[:maximum].rstrip(".-_") + extension


def save_image(article: ArticleFile, filename: str, stream: BinaryIO) -> Path:
    safe_name = safe_image_filename(filename)
    target = article.path / "images" / safe_name
    if target.exists():
        raise ArticleError(f"保存名「{safe_name}」の画像がすでにあります。既存画像は上書きしません。")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    total = 0
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".upload-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            while block := stream.read(1024 * 1024):
                total += len(block)
                if total > MAX_IMAGE_BYTES:
                    raise ArticleError("画像は10MB以下にしてください。")
                handle.write(block)
            handle.flush()
            os.fsync(handle.fileno())
        if total == 0:
            raise ArticleError("空の画像は追加できません。")
        os.replace(temporary, target)
        temporary = None
        return target
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def history_files(state_root: Path, article_id: str) -> list[Path]:
    root = state_root / "history" / article_id
    return sorted(root.glob("*.md"), reverse=True) if root.exists() else []


def autosave_files(state_root: Path, article_id: str) -> list[Path]:
    root = state_root / "autosave" / article_id
    return sorted(root.glob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True) if root.exists() else []


def has_uncommitted_autosave(state_root: Path, article: ArticleFile) -> bool:
    index = article.path / "index.md"
    canonical = index.read_bytes()
    canonical_time = index.stat().st_mtime_ns
    return any(path.stat().st_mtime_ns > canonical_time and path.read_bytes() != canonical for path in autosave_files(state_root, article.article_id))


def read_recovery_candidate(state_root: Path, article_id: str, name: str) -> frontmatter.Post:
    if Path(name).name != name or not name.endswith(".md"):
        raise ArticleError("復元候補名が正しくありません。")
    path = state_root / "autosave" / article_id / name
    if not path.is_file():
        raise ArticleError("復元候補が見つかりません。")
    try:
        return frontmatter.load(path)
    except Exception as exc:
        raise ArticleError("復元候補を読み込めません。") from exc


def restore_candidate(state_root: Path, article_id: str, tab_id: str, history_name: str) -> Path:
    if Path(history_name).name != history_name:
        raise ArticleError("履歴名が正しくありません。")
    source = state_root / "history" / article_id / history_name
    if not source.is_file():
        raise ArticleError("指定した履歴が見つかりません。")
    return save_autosave(state_root, article_id, tab_id, source.read_bytes())


def legacy_dry_run(legacy_root: Path = LEGACY_ROOT) -> list[dict[str, object]]:
    if not legacy_root.is_dir():
        return []
    results: list[dict[str, object]] = []
    for index in sorted(legacy_root.rglob("index.md")):
        relative = index.parent.relative_to(legacy_root)
        slug = relative.as_posix()
        warnings: list[str] = []
        try:
            post = frontmatter.load(index)
            keys = sorted(str(key) for key in post.metadata)
            if not post.metadata.get("article_type"):
                warnings.append("カテゴリーがありません")
            images = list((index.parent / "images").glob("*")) if (index.parent / "images").is_dir() else []
            results.append(
                {
                    "slug": slug,
                    "title": str(post.metadata.get("title") or "（タイトルなし）"),
                    "keys": keys,
                    "images": len([item for item in images if item.is_file()]),
                    "review_report": (index.parent / "review-report.md").is_file(),
                    "hash": file_hash(index),
                    "warnings": warnings,
                }
            )
        except Exception:
            results.append({"slug": slug, "title": "（読込エラー）", "warnings": ["front matterを解析できません"]})
    return results


def write_migration_manifest(state_root: Path, results: list[dict[str, object]]) -> Path:
    target = state_root / "migrations" / "latest-dry-run.json"
    data = json.dumps({"generated_at": now_iso(), "mode": "dry-run", "articles": results}, ensure_ascii=False, indent=2)
    atomic_write(target, (data + "\n").encode("utf-8"))
    return target
