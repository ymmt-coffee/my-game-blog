#!/usr/bin/env python3
"""架空の短い記事だけを使い、Gemini校正を1回確認する手動疎通テスト。"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import review_article


TEST_ARTICLE = """---
title: "Gemini接続テスト"
date: 2026-08-02
lastmod: 2026-08-02
draft: true
description: "外部公開しない短い架空原稿です"
images: []
article_type: monthly_essay
spoiler_warning: ""
provided: false
author: テスト
---

このゲームは昨日発売された。画面はきれいで、操作も分かりやすいです。
"""


def main() -> int:
    review_article.configure_stdio()
    try:
        with tempfile.TemporaryDirectory(prefix="my-game-blog-gemini-smoke-") as temp_name:
            article_dir = Path(temp_name) / "gemini-smoke"
            article_dir.mkdir()
            index_path = article_dir / "index.md"
            index_path.write_text(TEST_ARTICLE, encoding="utf-8", newline="\n")
            before = index_path.read_bytes()
            review_article.create_review(
                "gemini-smoke",
                article_dir,
                index_path,
                review_article.call_gemini,
                review_article.GEMINI_METHOD + " / smoke test",
                replace=False,
            )
            if index_path.read_bytes() != before:
                raise review_article.ReviewError("疎通テストで架空原稿が変更されました")
            report_path = article_dir / review_article.REPORT_NAME
            review_article.review_status("gemini-smoke", article_dir, index_path)
            if not report_path.is_file():
                raise review_article.ReviewError("疎通テストのレポートが作成されませんでした")
        print("Gemini疎通テスト成功: 架空原稿のみ送信、本文変更なし、6分類レポート確認、一時データ削除済み")
        return 0
    except review_article.ReviewError as exc:
        print(f"[停止] {exc}", file=sys.stderr)
        return 1
    except OSError:
        print("[停止] Gemini疎通テストの一時ファイル処理に失敗しました", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
