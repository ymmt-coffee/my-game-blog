#!/usr/bin/env python3
"""01_blog フォルダの記事を Hugo 形式に変換して content/posts/ へ同期する。"""

from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import datetime, timezone, timedelta
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

# --- 設定 ---
BLOG_DIR = Path(r"C:\Users\ymmt_\Documents\Life_and_Div\30_Projects\01_blog")
OUTPUT_DIR = "content/posts"
IMAGE_OUTPUT_DIR = "static/images"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SYNC_STATE_FILE = Path(__file__).resolve().parent / ".synced_files.json"
JST = timezone(timedelta(hours=9))

WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|([^\]]+))?\]\]")
IMAGE_EMBED_RE = re.compile(r"!\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def configure_stdio() -> None:
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def load_sync_state() -> list[str]:
    if not SYNC_STATE_FILE.exists():
        return []
    try:
        data = json.loads(SYNC_STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Warning: 同期記録の読み込みに失敗しました ({exc})。空の状態で続行します。")
    return []


def save_sync_state(filenames: list[str]) -> None:
    SYNC_STATE_FILE.write_text(
        json.dumps(sorted(filenames), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def mtime_to_date(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=JST)


def title_from_filename(path: Path) -> str:
    stem = path.stem
    if len(stem) > 11 and stem[4] == "-" and stem[7] == "-" and stem[10] == "-":
        stem = stem[11:]
    return stem.replace("-", " ").replace("_", " ")


def find_image(source_md: Path, image_name: str) -> Path | None:
    """記事周辺から画像ファイルを探す。"""
    blog_root = BLOG_DIR.resolve()
    candidates: list[Path] = []

    for parent in [source_md.parent, *source_md.parents]:
        if not parent.is_relative_to(blog_root):
            break
        candidates.extend([parent / image_name, parent / "attachments" / image_name])

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_file() and resolved.is_relative_to(blog_root):
            return resolved
    return None


def convert_wikilinks(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        alias = match.group(2)
        page = match.group(1).strip()
        return alias if alias else page

    return WIKILINK_RE.sub(repl, text)


def convert_images(text: str, source_md: Path, image_dir: Path) -> str:
    image_dir.mkdir(parents=True, exist_ok=True)

    def repl(match: re.Match[str]) -> str:
        image_name = match.group(1).strip()
        alt = (match.group(2) or Path(image_name).stem).strip()
        src = find_image(source_md, image_name)
        if src is None:
            print(f"Warning: 画像が見つかりません [{source_md.name}]: {image_name}")
            return alt
        dest = image_dir / src.name
        if not dest.exists() or src.stat().st_mtime > dest.stat().st_mtime:
            shutil.copy2(src, dest)
        return f"![{alt}](/images/{src.name})"

    return IMAGE_EMBED_RE.sub(repl, text)


def normalize_frontmatter(post: frontmatter.Post, source_md: Path) -> frontmatter.Post:
    if not post.metadata.get("title"):
        post.metadata["title"] = title_from_filename(source_md)
    if not post.metadata.get("date"):
        post.metadata["date"] = mtime_to_date(source_md)
    post.metadata.pop("publish", None)
    return post


def convert_file(source_md: Path, output_dir: Path, image_dir: Path) -> bool:
    try:
        post = frontmatter.loads(source_md.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Warning: フロントマターの解析に失敗しました [{source_md}]: {exc}")
        return False

    post = normalize_frontmatter(post, source_md)
    post.content = convert_images(convert_wikilinks(post.content), source_md, image_dir)
    (output_dir / source_md.name).write_text(frontmatter.dumps(post), encoding="utf-8")
    return True


def collect_source_files() -> list[Path]:
    blog_root = BLOG_DIR.resolve()
    return sorted(
        p for p in blog_root.rglob("*.md") if p.is_file() and p.is_relative_to(blog_root)
    )


def delete_removed_posts(
    output_dir: Path, previous_synced: set[str], current_outputs: set[str]
) -> int:
    deleted = 0
    for filename in previous_synced - current_outputs:
        target = output_dir / filename
        if target.exists():
            target.unlink()
            deleted += 1
            print(f"Deleted: {filename}")
    return deleted


def print_report(converted: int, skipped: int, deleted: int, output_dir: Path) -> None:
    print()
    print("--- 同期レポート ---")
    print(f"  変換: {converted} 件")
    print(f"  スキップ: {skipped} 件")
    print(f"  削除: {deleted} 件")
    print(f"  出力先: {output_dir}")


def main() -> int:
    configure_stdio()

    if not BLOG_DIR.is_dir():
        print(
            f"Error: BLOG_DIR が存在しません: {BLOG_DIR}\n"
            "  パスを確認するか、01_blog フォルダを作成してください。",
            file=sys.stderr,
        )
        return 1

    output_dir = PROJECT_ROOT / OUTPUT_DIR
    image_dir = PROJECT_ROOT / IMAGE_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    image_dir.mkdir(parents=True, exist_ok=True)

    current_outputs: list[str] = []
    converted = skipped = 0

    for source_md in collect_source_files():
        if convert_file(source_md, output_dir, image_dir):
            current_outputs.append(source_md.name)
            converted += 1
        else:
            skipped += 1

    deleted = delete_removed_posts(
        output_dir, set(load_sync_state()), set(current_outputs)
    )
    save_sync_state(current_outputs)
    print_report(converted, skipped, deleted, output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
