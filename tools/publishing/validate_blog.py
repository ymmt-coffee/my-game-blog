#!/usr/bin/env python3
"""Hugo記事と生成サイトを、公開前の停止条件と警告に分けて検査する。"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

import frontmatter


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BLOG_ROOT = PROJECT_ROOT / "blog"
BASE_PATH = "/my-game-blog/"
ARTICLE_TYPES = {"play_note", "weekly_picks", "monthly_essay"}
COMMON_REQUIRED = ("title", "date", "lastmod", "draft", "description", "images", "article_type", "author")
IMAGE_EXTENSIONS = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+[^)]*)?\)")
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)(?:\s+[^)]*)?\)")


def configure_stdio() -> None:
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def metadata_get(metadata: dict[object, object], key: str, default: object = None) -> object:
    wanted = key.casefold()
    for actual, value in metadata.items():
        if str(actual).casefold() == wanted:
            return value
    return default


def load_post(source: Path) -> frontmatter.Post:
    text = source.read_text(encoding="utf-8")
    if text.startswith("+++"):
        parts = text.split("+++", 2)
        if len(parts) != 3:
            raise ValueError("TOML front matterの終端+++がありません")
        return frontmatter.Post(parts[2].lstrip("\r\n"), **tomllib.loads(parts[1]))
    return frontmatter.loads(text)


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def print(self) -> None:
        for message in self.errors:
            print(f"[停止] {message}")
        for message in self.warnings:
            print(f"[警告] {message}")
        print(f"検査結果: 停止 {len(self.errors)}件 / 警告 {len(self.warnings)}件")


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.titles: list[str] = []
        self._in_title = False
        self._title_parts: list[str] = []
        self.metas: list[dict[str, str]] = []
        self.canonicals: list[str] = []
        self.links: list[str] = []
        self.json_ld: list[str] = []
        self._in_json_ld = False
        self._json_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.casefold(): value or "" for key, value in attrs}
        if tag == "title":
            self._in_title = True
            self._title_parts = []
        elif tag == "meta":
            self.metas.append(values)
        elif tag == "link":
            if "canonical" in values.get("rel", "").casefold().split():
                self.canonicals.append(values.get("href", ""))
            if values.get("href"):
                self.links.append(values["href"])
        elif tag in {"a", "img", "script", "source"}:
            attribute = "href" if tag == "a" else "src"
            if values.get(attribute):
                self.links.append(values[attribute])
            if tag in {"img", "source"} and values.get("srcset"):
                for candidate in values["srcset"].split(","):
                    url = candidate.strip().split(" ", 1)[0]
                    if url:
                        self.links.append(url)
        if tag == "script" and values.get("type", "").casefold() == "application/ld+json":
            self._in_json_ld = True
            self._json_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._in_title:
            self.titles.append("".join(self._title_parts).strip())
            self._in_title = False
        elif tag == "script" and self._in_json_ld:
            self.json_ld.append("".join(self._json_parts).strip())
            self._in_json_ld = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        if self._in_json_ld:
            self._json_parts.append(data)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content-dir", type=Path, default=BLOG_ROOT / "content")
    parser.add_argument("--public-dir", type=Path)
    parser.add_argument("--article", help="posts配下で厳格検査する記事slug")
    parser.add_argument("--production", action="store_true", help="本番公開用の厳格検査")
    return parser.parse_args()


def clean_target(raw: str) -> str:
    return raw.strip().strip("<>").split("#", 1)[0].split("?", 1)[0]


def is_external(raw: str) -> bool:
    return raw.startswith(("http://", "https://", "mailto:", "tel:", "data:", "javascript:"))


def validate_image_references(post: frontmatter.Post, source: Path, report: Report) -> None:
    references: list[str] = []
    images = post.metadata.get("images", [])
    if isinstance(images, list):
        references.extend(str(item) for item in images)
    for match in MARKDOWN_IMAGE_RE.finditer(post.content):
        references.append(match.group(1))
    for raw in references:
        target = clean_target(raw)
        if not target or is_external(target) or target.startswith("/"):
            continue
        candidate = (source.parent / unquote(target)).resolve()
        try:
            candidate.relative_to(source.parent.resolve())
        except ValueError:
            report.error(f"記事外を参照する画像です [{source}]: {raw}")
            continue
        if not candidate.is_file():
            report.error(f"参照画像がありません [{source}]: {raw}")
        elif candidate.suffix.casefold() not in IMAGE_EXTENSIONS:
            report.error(f"未対応の画像形式です [{source}]: {raw}")


def validate_markdown_links(post: frontmatter.Post, source: Path, report: Report) -> None:
    for match in MARKDOWN_LINK_RE.finditer(post.content):
        raw = match.group(1)
        target = clean_target(raw)
        if not target or is_external(target) or target.startswith("/"):
            continue
        candidate = (source.parent / unquote(target)).resolve()
        options = (candidate, candidate / "index.md")
        if not any(path.exists() for path in options):
            report.error(f"壊れた内部リンクです [{source}]: {raw}")


def validate_corrections(value: object, source: Path, report: Report) -> None:
    if value in (None, []):
        return
    if not isinstance(value, list):
        report.error(f"correctionsは一覧形式で指定してください [{source}]")
        return
    for index, entry in enumerate(value, 1):
        if not isinstance(entry, dict) or not entry.get("date") or not entry.get("summary"):
            report.error(f"corrections {index}件目にはdateとsummaryが必要です [{source}]")


def validate_post(source: Path, post: frontmatter.Post, strict: bool, report: Report) -> None:
    metadata = post.metadata
    article_type = metadata.get("article_type")
    if metadata.get("test_content") is True and metadata.get("draft") is False:
        if metadata.get("allow_published_test") is True:
            report.warn(f"明示許可された公開テスト記事です（noindexを確認してください） [{source}]")
        else:
            report.error(f"テスト用コンテンツがdraft: falseです [{source}]")
        return
    legacy_test = metadata_get(metadata, "robotsNoIndex") is True and "テスト" in str(metadata.get("title", ""))
    if article_type not in ARTICLE_TYPES:
        if legacy_test:
            report.warn(f"既存の公開フローテスト記事を検出しました（noindex維持） [{source}]")
            return
        message = f"article_typeが未設定または未対応です [{source}]"
        (report.error if strict else report.warn)(message)
        return
    for key in COMMON_REQUIRED:
        if key not in metadata or metadata[key] in (None, ""):
            report.error(f"必須front matter `{key}` がありません [{source}]")
    if not isinstance(metadata.get("draft"), bool):
        report.error(f"draftはtrue/falseで指定してください [{source}]")
    if not isinstance(metadata.get("images"), list):
        report.error(f"imagesは一覧形式で指定してください [{source}]")
    elif not metadata.get("images"):
        report.warn(f"OGP画像が未設定です（画像なしの安全な表示を使用） [{source}]")
    if article_type == "play_note" and not str(metadata.get("play_time", "")).strip():
        report.error(f"プレイ途中記にはplay_timeが必要です [{source}]")
    if "provided" in metadata and not isinstance(metadata["provided"], bool):
        report.error(f"providedはtrue/falseで指定してください [{source}]")
    spoiler = metadata.get("spoiler_warning", "")
    if spoiler is not None and not isinstance(spoiler, str):
        report.error(f"spoiler_warningは警告文または空文字で指定してください [{source}]")
    canonical = str(metadata.get("canonicalURL", "")).strip()
    if canonical and (urlparse(canonical).scheme != "https" or not urlparse(canonical).netloc):
        report.error(f"canonicalURLは完全なhttps URLで指定してください [{source}]")
    validate_corrections(metadata.get("corrections"), source, report)


def validate_content(content_dir: Path, article: str | None, production: bool, report: Report) -> None:
    if not content_dir.is_dir():
        report.error(f"contentフォルダがありません: {content_dir}")
        return
    review_reports = list(content_dir.rglob("review-report.md"))
    for path in review_reports:
        report.error(f"review-report.mdが公開用contentに入っています: {path}")
    requested = (content_dir / "posts" / Path(article) / "index.md").resolve() if article else None
    found_requested = False
    for source in sorted(content_dir.rglob("index.md")):
        try:
            post = load_post(source)
        except Exception as exc:
            report.error(f"front matterを解析できません [{source}]: {exc}")
            continue
        is_post = source.parent.parent.name == "posts" or (content_dir / "posts") in source.parents
        if is_post:
            is_requested = requested == source.resolve()
            found_requested = found_requested or is_requested
            if post.metadata.get("draft") is not True or is_requested:
                validate_post(source, post, strict=production or is_requested, report=report)
            if is_requested and production and post.metadata.get("draft") is not False:
                report.error(f"公開対象にはdraft: falseが必要です [{source}]")
        validate_image_references(post, source, report)
        validate_markdown_links(post, source, report)
    if requested and not found_requested:
        report.error(f"指定記事がcontentにありません: {article}")


def meta_values(parser: PageParser, key: str, value: str) -> list[str]:
    return [meta.get("content", "").strip() for meta in parser.metas if meta.get(key, "").casefold() == value]


def resolve_public_target(public_dir: Path, raw: str) -> Path | None:
    parsed = urlparse(raw)
    if parsed.scheme and parsed.netloc and parsed.netloc != "ymmt-coffee.github.io":
        return None
    path = unquote(parsed.path)
    if not path or path == "#" or (not path.startswith("/") and parsed.scheme):
        return None
    if path.startswith(BASE_PATH):
        path = path[len(BASE_PATH):]
    elif path.startswith("/"):
        return None
    else:
        return None
    candidate = public_dir / path
    if path.endswith("/") or candidate.is_dir():
        candidate = candidate / "index.html"
    return candidate


def validate_html_page(path: Path, public_dir: Path, canonical_map: dict[str, Path], report: Report) -> None:
    parser = PageParser()
    parser.feed(path.read_text(encoding="utf-8"))
    label = path.relative_to(public_dir)
    if label.as_posix() == "404.html" or any(
        meta.get("http-equiv", "").casefold() == "refresh" for meta in parser.metas
    ):
        return
    if len(parser.titles) != 1 or not parser.titles[0]:
        report.error(f"titleが1件ではありません [{label}]")
    descriptions = meta_values(parser, "name", "description")
    if len(descriptions) != 1 or not descriptions[0]:
        report.error(f"descriptionが1件ではないか空です [{label}]")
    if len(parser.canonicals) != 1:
        report.error(f"canonicalが1件ではありません [{label}]")
    else:
        canonical = parser.canonicals[0].strip()
        parsed = urlparse(canonical)
        if parsed.scheme != "https" or not parsed.netloc:
            report.error(f"canonicalが不正です [{label}]: {canonical}")
        elif canonical in canonical_map:
            report.error(f"canonicalが別ページと重複しています [{label}] / [{canonical_map[canonical]}]")
        else:
            canonical_map[canonical] = label
    for prop in ("og:url", "og:title", "og:description"):
        values = meta_values(parser, "property", prop)
        if len(values) != 1 or not values[0]:
            report.error(f"{prop}が1件ではないか空です [{label}]")
    og_images = meta_values(parser, "property", "og:image")
    if len(og_images) != len(set(og_images)):
        report.error(f"同じog:imageが重複しています [{label}]")
    for name in ("twitter:card", "twitter:title", "twitter:description"):
        values = meta_values(parser, "name", name)
        if len(values) != 1 or not values[0]:
            report.error(f"{name}が1件ではないか空です [{label}]")
    valid_json: list[object] = []
    for raw in parser.json_ld:
        try:
            valid_json.append(json.loads(raw))
        except json.JSONDecodeError as exc:
            report.error(f"JSON-LDが壊れています [{label}]: {exc}")
    is_home = label.as_posix() == "index.html"
    is_post_page = len(label.parts) > 2 and label.parts[0] == "posts" and label.name == "index.html"
    is_regular_page = (
        len(label.parts) == 2
        and label.name == "index.html"
        and label.parts[0] not in {"posts", "categories", "tags"}
    )
    if (is_home or is_post_page or is_regular_page) and not valid_json:
        report.error(f"JSON-LDがありません [{label}]")
    if is_post_page:
        postings = [item for item in valid_json if isinstance(item, dict) and item.get("@type") == "BlogPosting"]
        if len(postings) != 1:
            report.error(f"BlogPosting JSON-LDが1件ではありません [{label}]")
        else:
            for key in ("author", "datePublished", "dateModified", "headline"):
                if not postings[0].get(key):
                    report.error(f"BlogPostingの{key}がありません [{label}]")
    for raw in parser.links:
        target = resolve_public_target(public_dir, raw)
        if target is not None and not target.exists():
            report.error(f"生成サイト内のリンク先がありません [{label}]: {raw}")


def validate_public(public_dir: Path, report: Report) -> None:
    if not public_dir.is_dir():
        report.error(f"生成サイトフォルダがありません: {public_dir}")
        return
    for required in ("index.xml", "sitemap.xml", "robots.txt"):
        if not (public_dir / required).is_file():
            report.error(f"生成物がありません: {required}")
    robots = public_dir / "robots.txt"
    if robots.is_file() and "Sitemap:" not in robots.read_text(encoding="utf-8"):
        report.error("robots.txtにsitemapの場所がありません")
    if any("review-report" in path.as_posix().casefold() for path in public_dir.rglob("*")):
        report.error("生成サイトにreview-reportが含まれています")
    canonical_map: dict[str, Path] = {}
    for path in sorted(public_dir.rglob("*.html")):
        validate_html_page(path, public_dir, canonical_map, report)


def main() -> int:
    configure_stdio()
    args = parse_args()
    report = Report()
    validate_content(args.content_dir.resolve(), args.article, args.production, report)
    if args.public_dir:
        validate_public(args.public_dir.resolve(), report)
    report.print()
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
