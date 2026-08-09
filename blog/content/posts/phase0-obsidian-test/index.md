---
date: 2026-08-02 00:00:00+09:00
description: ObsidianからHugoへのプレビュー・公開フローを確認するためのテスト原稿です。
draft: false
images:
- images/test-card.svg
robotsNoIndex: true
title: Obsidian公開フローのテスト
---

このページは、Obsidianからゲームブログへ記事を公開する流れを確認するためのテスト原稿です。

## 確認する内容

- 記事タイトルと本文が表示されること
- 記事フォルダ内の画像が表示されること
- `review-report.md` がブログに表示されないこと
- プレビューと公開が別の操作になっていること

## 画像の確認

![公開フロー確認用の画像](images/test-card.svg)

## 最後の確認

この文章が表示され、上の画像が読めればプレビュー用同期は成功です。

公開テストへ進むときだけ、front matterの `draft: true` を `draft: false` に変更してください。