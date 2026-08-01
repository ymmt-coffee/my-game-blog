#!/usr/bin/env python3
"""Obsidian原稿をHugoのPage Bundleへ安全に同期する。"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import frontmatter
except ImportError:
    print(
        "Error: python-frontmatter がインストールされていません。\n"
        "  pip install -r requirements.txt",
        file=sys.stderr,
    )
    sys.exit(1)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BLOG_DIR = Path(r"C:\Users\ymmt_\Documents\Life_and_Div\30_Projects\01_blog")
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "content" / "posts"
JST = timezone(timedelta(hours=9))

REVIEW_REPORT_NAME = "review-report.md"
IMAGE_EXTENSIONS = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}
WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|([^\]]+))?\]\]")
IMAGE_EMBED_RE = re.compile(r"!\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)(?:\s+[^)]*)?\)")


class SyncError(RuntimeError):
    """公開を停止すべき同期エラー。"""


@dataclass(frozen=True)
class Article:
    slug: str
    source_md: Path
    source_dir: Path
    bundle_style: bool


def configure_stdio() -> None:
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_BLOG_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--article",
        help="指定したslugの記事だけを同期する（公開処理では必須）",
    )
    parser.add_argument(
        "--require-publishable",
        action="store_true",
        help="対象記事に draft: false が明示されていなければ停止する",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="変換対象と検査結果だけを表示し、ファイルを書き込まない",
    )
    return parser.parse_args()


def safe_relative(path: Path, root: Path) -> Path:
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise SyncError(f"パスが許可範囲外です: {path}") from exc


def slug_from_relative(relative: Path) -> str:
    slug = relative.as_posix().strip("/")
    if not slug or slug in {".", ".."} or any(part in {"", ".", ".."} for part in relative.parts):
        raise SyncError(f"無効な記事slugです: {slug}")
    return slug


def collect_articles(source_root: Path) -> list[Article]:
    source_root = source_root.resolve()
    bundle_indexes = sorted(
        path
        for path in source_root.rglob("index.md")
        if path.is_file() and path.name.casefold() != REVIEW_REPORT_NAME
    )
    bundle_dirs = {path.parent.resolve() for path in bundle_indexes}
    articles: list[Article] = []

    for index_md in bundle_indexes:
        relative_dir = safe_relative(index_md.parent, source_root)
        articles.append(
            Article(
                slug=slug_from_relative(relative_dir),
                source_md=index_md,
                source_dir=index_md.parent,
                bundle_style=True,
            )
        )

    for source_md in sorted(source_root.rglob("*.md")):
        if source_md.name.casefold() in {"index.md", REVIEW_REPORT_NAME}:
            continue
        resolved = source_md.resolve()
        if any(bundle_dir in resolved.parents for bundle_dir in bundle_dirs):
            # Page Bundle内は index.md 以外を公開しない。
            continue
        relative = safe_relative(source_md, source_root).with_suffix("")
        articles.append(
            Article(
                slug=slug_from_relative(relative),
                source_md=source_md,
                source_dir=source_md.parent,
                bundle_style=False,
            )
        )

    slugs = [article.slug.casefold() for article in articles]
    duplicates = sorted({slug for slug in slugs if slugs.count(slug) > 1})
    if duplicates:
        raise SyncError("記事slugが重複しています: " + ", ".join(duplicates))
    return sorted(articles, key=lambda article: article.slug.casefold())


def mtime_to_date(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=JST)


def title_from_article(article: Article) -> str:
    stem = Path(article.slug).name
    if len(stem) > 11 and stem[4] == "-" and stem[7] == "-" and stem[10] == "-":
        stem = stem[11:]
    return stem.replace("-", " ").replace("_", " ")


def load_post(article: Article) -> frontmatter.Post:
    try:
        post = frontmatter.loads(article.source_md.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SyncError(f"front matterを解析できません [{article.source_md}]: {exc}") from exc
    if not post.metadata.get("title"):
        post.metadata["title"] = title_from_article(article)
    if not post.metadata.get("date"):
        post.metadata["date"] = mtime_to_date(article.source_md)
    return post


def require_publishable(post: frontmatter.Post, article: Article) -> None:
    if post.metadata.get("draft") is not False:
        raise SyncError(
            f"公開対象には front matter の draft: false が必要です [{article.slug}]"
        )


def convert_wikilinks(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        page = match.group(1).strip()
        return (match.group(2) or page).strip()

    return WIKILINK_RE.sub(repl, text)


def image_candidates(article: Article, image_name: str) -> list[Path]:
    normalized = Path(image_name.replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts:
        raise SyncError(f"許可されていない画像パスです [{article.slug}]: {image_name}")

    candidates = [article.source_dir / normalized]
    if normalized.parts and normalized.parts[0].casefold() != "images":
        candidates.append(article.source_dir / "images" / normalized)
        candidates.append(article.source_dir / "attachments" / normalized)
    return candidates


def find_image(article: Article, image_name: str) -> Path:
    for candidate in image_candidates(article, image_name):
        if candidate.is_file() and candidate.suffix.casefold() in IMAGE_EXTENSIONS:
            safe_relative(candidate, article.source_dir)
            return candidate.resolve()
    raise SyncError(f"参照画像が見つかりません [{article.slug}]: {image_name}")


def copy_image(source: Path, article: Article, bundle_dir: Path) -> str:
    images_root = article.source_dir / "images"
    if source.is_relative_to(images_root.resolve()):
        relative = source.relative_to(images_root.resolve())
    else:
        relative = Path(source.name)
    destination = bundle_dir / "images" / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return (Path("images") / relative).as_posix()


def copy_bundle_images(article: Article, bundle_dir: Path) -> None:
    images_root = article.source_dir / "images"
    if not images_root.is_dir():
        return
    for source in sorted(images_root.rglob("*")):
        if not source.is_file():
            continue
        if source.suffix.casefold() not in IMAGE_EXTENSIONS:
            continue
        relative = safe_relative(source, images_root)
        destination = bundle_dir / "images" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def convert_embedded_images(text: str, article: Article, bundle_dir: Path) -> str:
    def repl(match: re.Match[str]) -> str:
        image_name = match.group(1).strip()
        alt = (match.group(2) or Path(image_name).stem).strip()
        source = find_image(article, image_name)
        relative = copy_image(source, article, bundle_dir)
        return f"![{alt}]({relative})"

    return IMAGE_EMBED_RE.sub(repl, text)


def validate_markdown_images(text: str, article: Article) -> None:
    for match in MARKDOWN_IMAGE_RE.finditer(text):
        raw_path = match.group(1).strip().strip("<>")
        if raw_path.startswith(("http://", "https://", "data:")) or raw_path.startswith("/"):
            continue
        clean_path = raw_path.split("#", 1)[0].split("?", 1)[0]
        candidate = article.source_dir / clean_path
        if not candidate.is_file():
            raise SyncError(f"参照画像が見つかりません [{article.slug}]: {raw_path}")
        safe_relative(candidate, article.source_dir)


def replace_bundle_atomically(staged_bundle: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    backup = destination.with_name(destination.name + ".sync-backup")
    if backup.exists():
        shutil.rmtree(backup)
    try:
        if destination.exists():
            destination.rename(backup)
        staged_bundle.rename(destination)
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        if destination.exists() and not staged_bundle.exists():
            shutil.rmtree(destination)
        if backup.exists() and not destination.exists():
            backup.rename(destination)
        raise


def convert_article(
    article: Article,
    output_root: Path,
    publishable_required: bool,
    dry_run: bool,
) -> None:
    post = load_post(article)
    if publishable_required:
        require_publishable(post, article)

    with tempfile.TemporaryDirectory(prefix="my-game-blog-sync-") as temp_name:
        staged_bundle = Path(temp_name) / "bundle"
        staged_bundle.mkdir(parents=True)
        copy_bundle_images(article, staged_bundle)
        post.content = convert_embedded_images(
            convert_wikilinks(post.content), article, staged_bundle
        )
        validate_markdown_images(post.content, article)
        (staged_bundle / "index.md").write_text(
            frontmatter.dumps(post), encoding="utf-8"
        )

        if dry_run:
            return
        destination = output_root / Path(article.slug)
        replace_bundle_atomically(staged_bundle, destination)


def main() -> int:
    configure_stdio()
    args = parse_args()
    source_root = args.source.resolve()
    output_root = args.output.resolve()

    if not source_root.is_dir():
        print(f"Error: 原稿フォルダが存在しません: {source_root}", file=sys.stderr)
        return 1

    try:
        articles = collect_articles(source_root)
        if args.article:
            requested = args.article.replace("\\", "/").strip("/")
            articles = [article for article in articles if article.slug == requested]
            if not articles:
                raise SyncError(f"指定した記事が見つかりません: {requested}")
        elif args.require_publishable:
            raise SyncError("公開同期では --article による記事指定が必要です")

        if not articles:
            print("同期対象の記事はありません。")
            return 0

        for article in articles:
            convert_article(
                article,
                output_root,
                publishable_required=args.require_publishable,
                dry_run=args.dry_run,
            )
            action = "検査" if args.dry_run else "同期"
            print(f"{action}: {article.slug}")

        print()
        print("--- 同期レポート ---")
        print(f"  対象: {len(articles)} 件")
        print(f"  出力先: {output_root}")
        print("  review-report.md: 常に除外")
        print("  原稿削除による自動削除: 無効")
        return 0
    except SyncError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
