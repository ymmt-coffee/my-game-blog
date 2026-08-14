"""外部送信を行わないX投稿案の作成と入力検証。"""

from __future__ import annotations

from urllib.parse import urlparse


PUBLIC_BASE_URL = "https://ymmt-coffee.github.io/my-game-blog/"
PLATFORM = "X"
MAX_MESSAGE_LENGTH = 280


class SocialError(RuntimeError):
    """利用者へ安全に表示できるX投稿案エラー。"""


def article_url(slug: str) -> str:
    return f"{PUBLIC_BASE_URL}articles/{slug}/"


def generate_message(title: str, description: str, slug: str) -> str:
    clean_title, clean_description, url = title.strip(), description.strip(), article_url(slug)
    fixed = f"{clean_title}\n\n{url}"
    if clean_description:
        available = MAX_MESSAGE_LENGTH - len(fixed) - 2
        if available > 1:
            excerpt = clean_description if len(clean_description) <= available else clean_description[:available - 1].rstrip() + "…"
            fixed = f"{clean_title}\n\n{excerpt}\n\n{url}"
    return validate_message(fixed)


def validate_message(value: str) -> str:
    message = value.strip()
    if not message:
        raise SocialError("投稿文を入力してください。")
    if len(message) > MAX_MESSAGE_LENGTH:
        raise SocialError(f"投稿文は{MAX_MESSAGE_LENGTH}文字以内にしてください。")
    return message


def validate_posted_url(value: str) -> str | None:
    url = value.strip()
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or len(url) > 500:
        raise SocialError("投稿URLはhttpまたはhttpsで始まる正しいURLを入力してください。")
    return url
