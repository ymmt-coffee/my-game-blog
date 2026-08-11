"""FastAPIで動くlocalhost限定のブログ管理画面。"""

from __future__ import annotations

import secrets
import shutil
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import frontmatter
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.middleware.trustedhost import TrustedHostMiddleware

from admin import article_templates, articles, db, publishing


ADMIN_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ADMIN_ROOT / "static"
APP_VERSION = (ADMIN_ROOT / "app-version.txt").read_text(encoding="utf-8").strip()
AI_REVIEW_ENABLED = False
STATE_LABELS = {
    "draft": "下書き", "review_pending": "校正待ち", "ready": "公開準備完了",
    "scheduled": "予約済み", "published": "公開済み", "archived": "アーカイブ",
}
TYPE_LABELS = {key: template.label for key, template in article_templates.TEMPLATES.items()}
NAV_ITEMS = (
    ("/articles", "記事管理", "Phase F"), ("/schedule", "スケジュール", "Phase G"),
    ("/editorial", "AI編集部", "Phase K"), ("/releases", "リリース・セール情報", "Phase L"),
    ("/social", "SNS分析", "Phase I"), ("/analytics", "アクセス解析", "Phase H"),
    ("/settings", "設定・履歴", "Phase B"),
)


def state_label(record: dict[str, object]) -> str:
    sync_status = str(record.get("sync_status") or "")
    if sync_status == "matched":
        return "公開済み"
    if sync_status == "update":
        return "更新あり"
    if sync_status == "missing" and record.get("published_at"):
        return "公開差異・要確認"
    if str(record.get("state")) == "ready" and record.get("published_at"):
        return "更新版・公開準備完了"
    if str(record.get("state")) == "draft" and (str(record.get("previous_state")) == "published" or record.get("published_at")):
        return "公開記事の更新下書き"
    return STATE_LABELS.get(str(record.get("state")), str(record.get("state")))


def layout(
    title: str,
    current: str,
    body: str,
    csrf_token: str = "",
    script: str | tuple[str, ...] = "",
    body_class: str = "",
) -> str:
    nav = "".join(
        f'<a class="nav-item{" active" if path == current else ""}" href="{path}">{escape(label)}</a>'
        for path, label, phase in NAV_ITEMS
    )
    meta = f'<meta name="csrf-token" content="{escape(csrf_token)}">' if csrf_token else ""
    scripts = (script,) if isinstance(script, str) and script else script
    script_tag = "".join(f'<script src="{item}" defer></script>' for item in scripts)
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">{meta}
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)} | ゲームブログ管理</title>
<link rel="stylesheet" href="/static/admin.css">{script_tag}</head><body class="{escape(body_class)}">
<aside><a class="brand" href="/">ゲームブログ管理</a><nav>{nav}</nav></aside>
<main><header><h1>{escape(title)}</h1></header>{body}</main></body></html>"""


def error_page(message: str, csrf_token: str, status_code: int = 400) -> HTMLResponse:
    body = f'<section class="card error-card"><h2>処理を停止しました</h2><p>{escape(message)}</p><a class="button secondary" href="/articles">記事一覧へ戻る</a></section>'
    return HTMLResponse(layout("安全停止", "/articles", body, csrf_token), status_code=status_code)


def hidden_csrf(token: str) -> str:
    return f'<input type="hidden" name="csrf_token" value="{escape(token)}">'


def article_workspace(
    request: Request,
    title: str,
    detail: str,
    selected_id: str = "",
    extra_script: str = "",
) -> str:
    records = db.list_articles(request.app.state.db_path, include_archived=True)
    for item in records:
        try:
            candidate = articles.read_article(Path(str(item["source_path"])), str(item["id"]), str(item["slug"]))
            item["sync_status"] = publishing.public_sync_status(candidate, request.app.state.public_posts)
        except articles.ArticleError:
            item["sync_status"] = "missing"
    selected = db.get_article(selected_id, request.app.state.db_path) if selected_id else None
    requested_tab = request.query_params.get("status", "")
    active_tab = requested_tab if requested_tab in {"draft", "published"} else ("published" if selected and str(selected["state"]) == "published" else "draft")
    records = [item for item in records if str(item["state"]) != "archived" and (((item.get("sync_status") != "missing" or bool(item.get("published_at"))) if active_tab == "published" else item.get("sync_status") == "missing" and not bool(item.get("published_at"))))]
    links: list[str] = []
    for item in records:
        item_title = str(item["slug"])
        item_date = ""
        try:
            article = articles.read_article(Path(str(item["source_path"])), str(item["id"]), str(item["slug"]))
            item_title = str(article.metadata.get("title") or item["slug"])
            item_date = str(article.metadata.get("date") or "")[:10]
        except articles.ArticleError:
            pass
        active = " active" if str(item["id"]) == selected_id else ""
        search_text = escape(f"{item_title} {item['slug']}".casefold())
        action = (f'<a class="picker-delete" href="/articles/{item["id"]}/unpublish">公開停止</a>' if item.get("sync_status") != "missing" else f'<form method="post" action="/articles/{item["id"]}/archive">{hidden_csrf(request.app.state.csrf_token)}<button class="picker-delete" type="submit" title="削除">削除</button></form>')
        links.append(f'''<div class="picker-item-row" data-search="{search_text}"><a class="article-picker-item{active}" href="/articles/{item["id"]}/edit">
<span class="picker-title">{escape(item_title)}</span><span class="picker-meta">{escape(item_date)} · {escape(state_label(item))}</span></a>
{action}</div>''')
    article_links = "".join(links) or '<p class="picker-empty">記事はまだありません。</p>'
    middle = f"""<section class="article-picker" id="article-picker"><div class="picker-top">
<button class="picker-toggle" type="button" aria-expanded="true" aria-controls="picker-content" title="記事一覧を折り畳む"><span aria-hidden="true">◀</span><b>記事一覧</b></button></div>
<div class="picker-content" id="picker-content"><a class="button picker-new" href="/articles/new">＋ 新規作成</a>
<div class="picker-tabs"><a class="{'active' if active_tab == 'draft' else ''}" href="/articles?status=draft">下書き</a><a class="{'active' if active_tab == 'published' else ''}" href="/articles?status=published">公開済</a></div>
<input class="picker-search" id="article-search" type="search" placeholder="記事を検索" aria-label="記事を検索">
<div class="picker-list">{article_links}</div></div></section>"""
    body = f'<div class="article-workspace">{middle}<section class="article-detail">{detail}</section></div>'
    scripts: tuple[str, ...] = ("/static/workspace.js",) + ((extra_script,) if extra_script else ())
    return layout(title, "/articles", body, request.app.state.csrf_token, scripts, "article-mode")


def require_csrf(request: Request, submitted: str | None) -> None:
    expected = request.app.state.csrf_token
    if not submitted or not secrets.compare_digest(submitted, expected):
        raise articles.ArticleError("画面の確認情報が一致しません。画面を再読み込みしてください。")


def load_record(article_id: str, request: Request) -> tuple[dict[str, object], articles.ArticleFile]:
    record = db.get_article(article_id, request.app.state.db_path)
    if record is None:
        raise articles.ArticleError("記事が見つかりません。")
    path = Path(str(record["source_path"]))
    article = articles.read_article(path, article_id, str(record["slug"]))
    return record, article


def scan_canonical(content_root: Path, db_path: Path) -> None:
    content_root.mkdir(parents=True, exist_ok=True)
    for index in sorted(content_root.glob("*/index.md")):
        slug = index.parent.name
        try:
            articles.validate_slug(slug)
            post = frontmatter.load(index)
            article_type = str(post.metadata.get("article_type") or "play_note")
            if article_type not in articles.ARTICLE_TYPES:
                article_type = "play_note"
            article_id = uuid.uuid5(uuid.NAMESPACE_URL, f"my-game-blog:{slug}").hex
            db.register_scanned_article(article_id, slug, article_type, str(index.parent.resolve()), articles.file_hash(index), db_path)
        except Exception:
            db.record_event("article_scan", "warning", "article_scan_skipped", "読み込めない記事を検出しました。", db_path)


def create_app(
    *, db_path: Path = db.DEFAULT_DB_PATH,
    content_root: Path = articles.DEFAULT_CONTENT_ROOT,
    state_root: Path = articles.DEFAULT_STATE_ROOT,
    legacy_root: Path = articles.LEGACY_ROOT,
    testing: bool = False,
    command_runner=None,
    review_supplier=None,
    public_posts: Path = publishing.PUBLIC_POSTS,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        db.initialize(db_path)
        scan_canonical(content_root, db_path)
        db.record_event("application", "success", "app_started", "管理画面を起動しました。", db_path)
        yield

    app = FastAPI(title="ゲームブログ管理", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.db_path, app.state.content_root, app.state.state_root = db_path, content_root, state_root
    app.state.public_posts = public_posts
    app.state.legacy_root, app.state.csrf_token = legacy_root, secrets.token_urlsafe(32)
    app.state.command_runner = command_runner or publishing.run_command
    app.state.review_supplier = review_supplier
    allowed_hosts = ["127.0.0.1", "localhost"] + (["testserver"] if testing else [])
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
    app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> str:
        body = """<section class="home-actions"><a class="button" href="/articles">記事管理</a><a class="text-link" href="/articles/migration">既存原稿</a></section>"""
        return layout("ホーム", "/", body, request.app.state.csrf_token)

    @app.get("/articles", response_class=HTMLResponse)
    async def article_list(request: Request, status: str = "draft") -> str:
        detail = '''<section class="card empty article-empty"><h2>記事を選択</h2></section>'''
        return article_workspace(request, "記事管理", detail)

    @app.get("/articles/new", response_class=HTMLResponse)
    async def article_new(request: Request) -> str:
        options = "".join(f'<option value="{key}">{escape(label)}</option>' for key, label in TYPE_LABELS.items())
        body = f"""<section class="card form-card"><form method="post" action="/articles/new">{hidden_csrf(request.app.state.csrf_token)}
<label>タイトル<input name="title" required maxlength="160"></label>
<label>概要<textarea name="description" rows="2" required maxlength="300"></textarea></label>
<label>カテゴリー<select name="article_type" id="new-article-type">{options}</select></label>
<label data-play-time>プレイ時間<input name="play_time" placeholder="例：12時間"></label><label>著者<input name="author" required value="やまもと"></label>
<button class="button" type="submit">作成</button></form></section>"""
        return article_workspace(request, "新しい記事", body, extra_script="/static/template-form.js")

    @app.post("/articles/new")
    async def article_create(request: Request):
        form = await request.form()
        try:
            require_csrf(request, str(form.get("csrf_token") or ""))
            slug = str(form.get("slug") or "").strip() or articles.next_daily_slug(content_root)
            article_id, path, digest = articles.create_article_files(content_root, slug, str(form.get("title") or ""), str(form.get("article_type") or ""), str(form.get("author") or ""), str(form.get("description") or ""), str(form.get("play_time") or ""))
            db.create_article(article_id, path.name, str(form.get("article_type")), str(path.resolve()), digest, db_path)
            return RedirectResponse(f"/articles/{article_id}/edit?created=1", status_code=303)
        except (articles.ArticleError, Exception) as exc:
            if not isinstance(exc, articles.ArticleError):
                return error_page("記事の作成に失敗しました。既存ファイルは変更していません。", request.app.state.csrf_token, 500)
            return error_page(str(exc), request.app.state.csrf_token)

    @app.get("/articles/migration", response_class=HTMLResponse)
    async def migration_dry_run(request: Request) -> str:
        results = articles.legacy_dry_run(legacy_root)
        manifest = articles.write_migration_manifest(state_root, results)
        rows = "".join(
            f"<tr><td>{escape(str(item.get('slug', '')))}</td><td>{escape(str(item.get('title', '')))}</td><td>{escape(str(item.get('images', 0)))}</td>"
            f"<td>{escape('、'.join(item.get('warnings', [])) or '問題なし')}</td></tr>" for item in results
        ) or '<tr><td colspan="4" class="muted">移行候補は見つかりませんでした。</td></tr>'
        try:
            manifest_label = str(manifest.relative_to(articles.PROJECT_ROOT))
        except ValueError:
            manifest_label = str(manifest)
        body = f"""<section class="card notice"><strong>読み取り専用dry-run</strong><p>原稿のコピー、移動、削除は行いません。</p>
<p class="muted">結果は {escape(manifest_label)}</p></section><section class="card"><div class="table-wrap"><table><thead><tr><th>slug</th><th>タイトル</th><th>画像</th><th>確認事項</th></tr></thead><tbody>{rows}</tbody></table></div></section>"""
        return article_workspace(request, "既存原稿の確認", body)

    @app.get("/articles/{article_id}/edit", response_class=HTMLResponse)
    async def article_edit(article_id: str, request: Request, created: int = 0, saved: int = 0, recovery: str = ""):
        try:
            record, article = load_record(article_id, request)
        except articles.ArticleError as exc:
            return error_page(str(exc), request.app.state.csrf_token, 404)
        recovery_notice = ""
        if recovery:
            try:
                candidate = articles.read_recovery_candidate(state_root, article_id, recovery)
                article = articles.ArticleFile(article.article_id, article.slug, article.path, dict(candidate.metadata), candidate.content, article.file_hash)
                recovery_notice = '<div class="flash">復元候補を読み込みました。内容を確認し、採用する場合だけ手動保存してください。</div>'
            except articles.ArticleError as exc:
                recovery_notice = f'<div class="flash error">{escape(str(exc))}</div>'
        db_hash = str(record["file_hash"])
        conflict = db_hash != article.file_hash
        archived = str(record["state"]) == "archived"
        images = articles.list_images(article)
        header_image = articles.header_image_name(article)
        options = "".join(f'<option value="{key}"{" selected" if key == str(record["article_type"]) else ""}>{escape(label)}</option>' for key, label in TYPE_LABELS.items())
        image_rows_parts: list[str] = []
        for item in images:
            image_name = str(item["name"])
            markdown = f"![{Path(image_name).stem}](images/{image_name})"
            header_label = '<span class="header-image-label">ヘッダー画像</span>' if image_name == header_image else ""
            header_action = "解除" if image_name == header_image else "ヘッダー画像に設定"
            header_value = "" if image_name == header_image else image_name
            image_rows_parts.append(f'''<li class="image-row"><img class="image-thumb" src="/articles/{article_id}/images/{escape(image_name)}" alt=""><div class="image-info"><code>{escape(markdown)}</code><span class="muted">{item["size"]} bytes</span>{header_label}</div><div class="image-actions"><button class="button secondary image-copy" type="button" data-copy-markdown="{escape(markdown)}">コピー</button><form method="post" action="/articles/{article_id}/header-image">{hidden_csrf(request.app.state.csrf_token)}<input type="hidden" name="expected_hash" value="{escape(article.file_hash)}"><input type="hidden" name="revision" value="{record['revision']}"><input type="hidden" name="image_name" value="{escape(header_value)}"><button class="button secondary" type="submit" {'disabled' if conflict or archived else ''}>{header_action}</button></form></div></li>''')
        image_rows = "".join(image_rows_parts) or '<li class="muted">画像はありません。</li>'
        notice = recovery_notice + ('<div class="flash success">記事を保存しました。</div>' if saved else ('<div class="flash success">下書きを作成しました。</div>' if created else ""))
        if articles.has_uncommitted_autosave(state_root, article):
            notice += f'<div class="flash error"><strong>手動保存されていない編集内容があります。</strong> <a href="/articles/{article_id}/history">履歴・復元から自動保存内容を確認</a>し、必要な内容を手動保存してください。</div>'
        if str(record["state"]) == "published":
            notice += '<div class="flash publish-note"><strong>公開済み記事を編集中です。</strong> 入力中と自動保存は公開ページへ反映されません。手動保存すると更新下書きになり、公開前チェックと投稿の完了後に公開ページが更新されます。</div>'
        elif str(record["state"]) == "draft" and str(record.get("previous_state")) == "published":
            notice += '<div class="flash publish-note"><strong>公開記事の更新下書きです。</strong> 現在の公開ページは旧版のまま維持されています。</div>'
        if conflict:
            notice += f'<div class="flash error"><strong>外部変更を検出しました。保存を停止しています。</strong><p>ファイル内容を確認し、この内容を管理画面へ取り込む場合だけ次を押してください。</p><form method="post" action="/articles/{article_id}/accept-external">{hidden_csrf(request.app.state.csrf_token)}<input type="hidden" name="revision" value="{record["revision"]}"><input type="hidden" name="actual_hash" value="{escape(article.file_hash)}"><button class="button danger" type="submit">外部変更を取り込む</button></form></div>'
        inspection = article_templates.validate_metadata(article.metadata)
        inspection_badge = f'<span class="validation-count" title="{escape(" ".join(inspection))}">未入力 {len(inspection)}</span>' if inspection else ""
        current_type = str(article.metadata.get("article_type") or record["article_type"])
        play_time_hidden = "" if current_type == "play_note" else " hidden"
        review = publishing.load_review(state_root, article)
        review_fresh = review is not None and review.get("file_hash") == article.file_hash
        review_html = '<p class="muted">現在の原稿に対応する校正結果はありません。</p>'
        if review_fresh:
            decisions = review.get("decisions", {})
            findings: list[str] = []
            for category in review.get("response", {}).get("categories", []):
                for index, finding in enumerate(category.get("findings", [])):
                    key = f"{category['id']}:{index}"
                    decided = decisions.get(key, "")
                    decision_label = {"accepted": "採用", "rejected": "見送り"}.get(decided, "未確認")
                    findings.append(f'''<article class="review-finding"><strong>{escape(str(finding['location']))}</strong><p>{escape(str(finding['reason']))}</p><p>提案: {escape(str(finding['suggestion']))}</p><span class="state">{decision_label}</span><div class="editor-actions"><form method="post" action="/articles/{article_id}/review/decision">{hidden_csrf(request.app.state.csrf_token)}<input type="hidden" name="finding_key" value="{escape(key)}"><button class="button secondary" name="decision" value="accepted">採用する</button><button class="button secondary" name="decision" value="rejected">見送る</button></form></div></article>''')
            overall = escape(str(review.get("response", {}).get("overall_result", "")))
            review_html = f'<p><strong>校正結果:</strong> {overall}</p>' + ("".join(findings) or '<p class="ok">指摘はありません。</p>')
        body = f"""{notice}<form class="editor" method="post" action="/articles/{article_id}/save" data-article-id="{article_id}" data-conflict="{str(conflict).lower()}">
{hidden_csrf(request.app.state.csrf_token)}<input type="hidden" name="expected_hash" value="{escape(article.file_hash)}"><input type="hidden" name="revision" value="{record['revision']}">
<input type="hidden" name="tab_id" id="tab-id"><section class="card editor-meta"><label>タイトル<input name="title" value="{escape(str(article.metadata.get('title') or ''))}" required></label>
<label>概要<textarea name="description" rows="2">{escape(str(article.metadata.get('description') or ''))}</textarea></label><label>カテゴリー<select name="article_type" id="edit-article-type">{options}</select></label>
<label data-play-time{play_time_hidden}>プレイ時間<input name="play_time" value="{escape(str(article.metadata.get('play_time') or ''))}" placeholder="例：12時間"></label>
<div class="save-line"><span>{escape(state_label(record))} {inspection_badge}</span><span id="save-status">保存済み</span></div></section>
<section class="card body-card"><div class="section-head"><h2>本文</h2><div class="editor-actions"><button class="button" type="submit" {'disabled' if conflict or archived else ''}>手動保存</button><a class="button secondary" href="/articles/{article_id}/history">履歴・復元</a></div></div>
<textarea class="body-editor" name="body" rows="24" aria-label="本文">{escape(article.body)}</textarea></section></form>
<section class="card"><h2>画像</h2><ul class="image-list">{image_rows}</ul><form class="image-upload" method="post" action="/articles/{article_id}/images" enctype="multipart/form-data">{hidden_csrf(request.app.state.csrf_token)}
<input type="file" name="image" accept="image/png,image/jpeg,image/gif,image/webp,image/avif" required><button class="button secondary" type="submit" {'disabled' if archived else ''}>追加</button></form></section>
<section class="card"><h2>公開</h2><div class="editor-actions"><form method="post" action="/articles/{article_id}/preview">{hidden_csrf(request.app.state.csrf_token)}<button class="button secondary" {'disabled' if conflict or archived else ''}>プレビュー</button></form><form method="post" action="/articles/{article_id}/prepublish">{hidden_csrf(request.app.state.csrf_token)}<button class="button" {'disabled' if conflict or archived else ''}>公開前チェック</button></form></div></section>
{(f'''<section class="card danger-zone"><h2>{'アーカイブから戻す' if archived else 'アーカイブ'}</h2><p>ファイルは削除も移動もしません。</p><form method="post" action="/articles/{article_id}/{'restore' if archived else 'archive'}">{hidden_csrf(request.app.state.csrf_token)}<button class="button {'secondary' if archived else 'danger'}" type="submit">{'下書きへ戻す' if archived else 'アーカイブする'}</button></form></section>''' if archived or str(record['state']) == 'published' else '')}"""
        saved_title = str(article.metadata.get("title") or record["slug"])
        return article_workspace(request, f"編集: {saved_title}", body, article_id, "/static/editor.js")

    @app.post("/articles/{article_id}/review")
    async def article_review(article_id: str, request: Request):
        form = await request.form()
        try:
            require_csrf(request, str(form.get("csrf_token") or ""))
            if not AI_REVIEW_ENABLED:
                raise publishing.PublishError("AI校正は現在停止しています。")
            record, article = load_record(article_id, request)
            if str(record["file_hash"]) != article.file_hash:
                raise publishing.PublishError("外部変更があるため校正を停止しました。")
            publishing.perform_review(article, state_root, request.app.state.review_supplier)
            db.mark_reviewed(article_id, article.file_hash, db_path)
            return RedirectResponse(f"/articles/{article_id}/edit", status_code=303)
        except (articles.ArticleError, publishing.PublishError, RuntimeError) as exc:
            db.record_article_event(article_id, "review", "failure", "review_failed", "校正を安全停止しました。", db_path)
            return error_page(str(exc), request.app.state.csrf_token)

    @app.post("/articles/{article_id}/review/decision")
    async def review_decision(article_id: str, request: Request):
        form = await request.form()
        try:
            require_csrf(request, str(form.get("csrf_token") or ""))
            if not AI_REVIEW_ENABLED:
                raise publishing.PublishError("AI校正は現在停止しています。")
            _record, article = load_record(article_id, request)
            publishing.save_decision(state_root, article, str(form.get("finding_key") or ""), str(form.get("decision") or ""))
            db.record_article_event(article_id, "review_decision", "success", "review_decision_saved", "校正指摘の判断を保存しました。", db_path)
            return RedirectResponse(f"/articles/{article_id}/edit", status_code=303)
        except (articles.ArticleError, publishing.PublishError) as exc:
            return error_page(str(exc), request.app.state.csrf_token)

    @app.post("/articles/{article_id}/preview")
    async def article_preview(article_id: str, request: Request):
        form = await request.form()
        try:
            require_csrf(request, str(form.get("csrf_token") or ""))
            record, article = load_record(article_id, request)
            if str(record["file_hash"]) != article.file_hash:
                raise publishing.PublishError("外部変更があるためプレビューを停止しました。")
            if articles.has_uncommitted_autosave(state_root, article):
                raise publishing.PublishError("手動保存されていない編集内容があります。手動保存してからプレビューをやり直してください。")
            result = publishing.build_preview(article, state_root, request.app.state.command_runner)
            if not result.ok:
                raise publishing.PublishError(" ".join(result.errors))
            db.record_article_event(article_id, "preview", "success", "preview_created", "プレビューを作成しました。", db_path)
            return RedirectResponse(result.preview_url, status_code=303)
        except (articles.ArticleError, publishing.PublishError) as exc:
            return error_page(str(exc), request.app.state.csrf_token)

    @app.get("/previews/{article_id}/{asset_path:path}")
    async def preview_asset(article_id: str, asset_path: str):
        root = (state_root / "previews" / article_id).resolve()
        requested = (root / asset_path).resolve()
        if requested.is_dir():
            requested = requested / "index.html"
        try:
            requested.relative_to(root)
        except ValueError:
            return HTMLResponse("Not found", status_code=404)
        if not requested.is_file():
            return HTMLResponse("Not found", status_code=404)
        return FileResponse(requested)

    @app.post("/articles/{article_id}/prepublish", response_class=HTMLResponse)
    async def article_prepublish(article_id: str, request: Request):
        form = await request.form()
        try:
            require_csrf(request, str(form.get("csrf_token") or ""))
            record, article = load_record(article_id, request)
            if str(record["file_hash"]) != article.file_hash:
                raise publishing.PublishError("外部変更があるため公開前チェックを停止しました。")
            if articles.has_uncommitted_autosave(state_root, article):
                raise publishing.PublishError("手動保存されていない編集内容があります。手動保存してから公開前チェックをやり直してください。")
            result, prepared = publishing.prepublish_check(article, state_root, request.app.state.command_runner)
            if not result.ok or prepared is None:
                raise publishing.PublishError(" ".join(result.errors))
            db.mark_ready(article_id, article.file_hash, db_path)
            attempt_id, token, token_hash, expires = publishing.new_attempt_values()
            db.create_publish_attempt(attempt_id, article_id, article.file_hash, token_hash, expires, db_path)
            warning_rows = "".join(f"<li>{escape(item)}</li>" for item in result.warnings) or "<li>警告はありません。</li>"
            body = f'''<section class="card notice"><h2>公開前チェックに合格しました</h2><dl><dt>対象記事</dt><dd>{escape(article.slug)}</dd><dt>公開先</dt><dd>GitHub Pages</dd><dt>原稿ハッシュ</dt><dd><code>{escape(article.file_hash[:16])}…</code></dd></dl><h3>警告</h3><ul>{warning_rows}</ul></section><section class="card danger-zone"><h2>最終確認</h2><p>実行すると対象記事だけをcommitし、GitHubへpushして公開します。取り消せません。</p><form method="post" action="/articles/{article_id}/publish">{hidden_csrf(request.app.state.csrf_token)}<input type="hidden" name="attempt_id" value="{attempt_id}"><input type="hidden" name="approval_token" value="{escape(token)}"><button class="button danger">投稿を実行</button></form></section>'''
            return article_workspace(request, "投稿の最終確認", body, article_id)
        except (articles.ArticleError, publishing.PublishError, RuntimeError) as exc:
            db.record_article_event(article_id, "prepublish", "failure", "prepublish_failed", "公開前チェックを安全停止しました。", db_path)
            return error_page(str(exc), request.app.state.csrf_token)

    @app.post("/articles/{article_id}/publish", response_class=HTMLResponse)
    async def article_publish(article_id: str, request: Request):
        form = await request.form()
        attempt_id = str(form.get("attempt_id") or "")
        try:
            require_csrf(request, str(form.get("csrf_token") or ""))
            record, article = load_record(article_id, request)
            attempt = db.get_publish_attempt(attempt_id, db_path)
            if attempt is None or str(attempt["article_id"]) != article_id or str(attempt["result"]) != "checked":
                raise publishing.PublishError("公開承認が見つからないか、すでに使用済みです。")
            if datetime.fromisoformat(str(attempt["expires_at"])) < datetime.now(timezone.utc):
                db.update_publish_attempt(attempt_id, "expired", "公開承認の期限が切れました。", db_path=db_path)
                raise publishing.PublishError("公開承認の期限が切れました。再検査してください。")
            if not publishing.token_matches(str(form.get("approval_token") or ""), str(attempt["token_hash"])):
                raise publishing.PublishError("公開承認情報が一致しません。")
            if str(attempt["file_hash"]) != article.file_hash or str(record["file_hash"]) != article.file_hash or str(record["state"]) != "ready":
                raise publishing.PublishError("検査後に記事または状態が変わりました。再検査してください。")
            db.update_publish_attempt(attempt_id, "running", "公開処理を実行中です。", db_path=db_path)
            prepared = state_root / "publish-prepared" / article_id / article.file_hash
            sha, pages_url = publishing.publish_article(article, prepared, request.app.state.command_runner)
            db.mark_published(article_id, article.file_hash, db_path)
            db.update_publish_attempt(attempt_id, "success", "記事を公開しました。", sha, pages_url, db_path)
            body = f'<section class="card notice"><h2>投稿が完了しました</h2><p>commit: <code>{escape(sha)}</code></p><p><a class="button" href="{escape(publishing.PAGES_URL)}">公開ブログを開く</a></p></section>'
            return article_workspace(request, "投稿完了", body, article_id)
        except Exception as exc:
            try:
                if attempt_id and db.get_publish_attempt(attempt_id, db_path):
                    db.update_publish_attempt(attempt_id, "failure", "公開処理を安全停止しました。", db_path=db_path)
                if isinstance(exc, publishing.PublishError) and exc.before_commit and 'article' in locals():
                    db.restore_after_precommit_publish_failure(article_id, article.file_hash, db_path)
            except Exception:
                pass
            message = str(exc) if isinstance(exc, (articles.ArticleError, publishing.PublishError, RuntimeError)) else "予期しないエラーが発生しました。管理原稿は保持されています。"
            return error_page(message, request.app.state.csrf_token)

    @app.post("/api/articles/{article_id}/autosave")
    async def autosave(article_id: str, request: Request):
        try:
            require_csrf(request, request.headers.get("x-csrf-token"))
            payload = await request.json()
            record, article = load_record(article_id, request)
            if str(record["state"]) == "archived":
                raise articles.ArticleError("アーカイブ中の記事は編集できません。")
            if int(payload.get("revision", -1)) != int(record["revision"]) or str(payload.get("expected_hash")) != article.file_hash or str(record["file_hash"]) != article.file_hash:
                raise articles.ArticleConflict("別の変更を検出しました。")
            data = articles.updated_markdown(article, title=str(payload.get("title", "")), description=str(payload.get("description", "")), article_type=str(payload.get("article_type", "")), body=str(payload.get("body", "")), play_time=str(payload.get("play_time", "")))
            path = articles.save_autosave(state_root, article_id, str(payload.get("tab_id", "")), data)
            return {"status": "autosaved", "saved_at": articles.now_iso(), "path": path.name}
        except articles.ArticleConflict as exc:
            return JSONResponse({"status": "conflict", "message": str(exc)}, status_code=409)
        except articles.ArticleError as exc:
            return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)

    @app.post("/articles/{article_id}/save")
    async def article_save(article_id: str, request: Request):
        form = await request.form()
        try:
            require_csrf(request, str(form.get("csrf_token") or ""))
            record, article = load_record(article_id, request)
            if str(record["state"]) == "archived":
                raise articles.ArticleError("アーカイブ中の記事は編集できません。")
            revision = int(str(form.get("revision") or "0"))
            expected_hash = str(form.get("expected_hash") or "")
            if revision != int(record["revision"]) or expected_hash != str(record["file_hash"]):
                raise articles.ArticleConflict("別の画面で保存済みです。再読み込みしてください。")
            data = articles.updated_markdown(article, title=str(form.get("title") or ""), description=str(form.get("description") or ""), article_type=str(form.get("article_type") or ""), body=str(form.get("body") or ""), play_time=str(form.get("play_time") or ""))
            new_hash, _history = articles.commit_article(article, data, state_root, expected_hash, revision)
            db.update_saved_article(article_id, str(form.get("article_type")), expected_hash, new_hash, revision, db_path)
            return RedirectResponse(f"/articles/{article_id}/edit?saved=1", status_code=303)
        except articles.ArticleConflict as exc:
            db.record_article_event(article_id, "save", "warning", "save_conflict", "保存競合を検出しました。", db_path)
            return error_page(str(exc), request.app.state.csrf_token, 409)
        except (articles.ArticleError, ValueError) as exc:
            return error_page(str(exc), request.app.state.csrf_token)

    @app.post("/articles/{article_id}/images")
    async def image_upload(article_id: str, request: Request):
        form = await request.form()
        try:
            require_csrf(request, str(form.get("csrf_token") or ""))
            record, article = load_record(article_id, request)
            if str(record["state"]) == "archived":
                raise articles.ArticleError("アーカイブ中の記事へ画像を追加できません。")
            upload = form.get("image")
            if not isinstance(upload, StarletteUploadFile) or not upload.filename:
                raise articles.ArticleError("画像を選択してください。")
            try:
                articles.save_image(article, upload.filename, upload.file)
                db.record_article_event(article_id, "image_add", "success", "image_added", "画像を追加しました。", db_path)
            finally:
                await upload.close()
            return RedirectResponse(f"/articles/{article_id}/edit", status_code=303)
        except articles.ArticleError as exc:
            return error_page(str(exc), request.app.state.csrf_token)

    @app.post("/articles/{article_id}/header-image")
    async def set_header_image(article_id: str, request: Request):
        form = await request.form()
        try:
            require_csrf(request, str(form.get("csrf_token") or ""))
            record, article = load_record(article_id, request)
            if str(record["state"]) == "archived":
                raise articles.ArticleError("削除済みの記事は変更できません。")
            revision = int(str(form.get("revision") or "0"))
            expected_hash = str(form.get("expected_hash") or "")
            if revision != int(record["revision"]) or expected_hash != str(record["file_hash"]):
                raise articles.ArticleConflict("別の画面で保存済みです。再読み込みしてください。")
            image_name = str(form.get("image_name") or "").strip() or None
            data = articles.updated_header_image_markdown(article, image_name)
            new_hash, _history = articles.commit_article(article, data, state_root, expected_hash, revision)
            db.update_saved_article(article_id, str(record["article_type"]), expected_hash, new_hash, revision, db_path)
            message = "ヘッダー画像を設定しました。" if image_name else "ヘッダー画像を解除しました。"
            db.record_article_event(article_id, "header_image", "success", "header_image_updated", message, db_path)
            return RedirectResponse(f"/articles/{article_id}/edit?saved=1", status_code=303)
        except articles.ArticleConflict as exc:
            return error_page(str(exc), request.app.state.csrf_token, 409)
        except (articles.ArticleError, RuntimeError, ValueError) as exc:
            return error_page(str(exc), request.app.state.csrf_token)

    @app.get("/articles/{article_id}/images/{filename}")
    async def article_image(article_id: str, filename: str, request: Request):
        try:
            _record, article = load_record(article_id, request)
            if Path(filename).name != filename:
                raise articles.ArticleError("画像名が正しくありません。")
            image_path = (article.path / "images" / filename).resolve()
            image_path.relative_to((article.path / "images").resolve())
            if not image_path.is_file() or image_path.suffix.casefold() not in articles.IMAGE_EXTENSIONS:
                raise articles.ArticleError("画像が見つかりません。")
            return FileResponse(image_path)
        except (articles.ArticleError, ValueError) as exc:
            return error_page(str(exc), request.app.state.csrf_token, 404)

    @app.post("/articles/{article_id}/accept-external")
    async def accept_external(article_id: str, request: Request):
        form = await request.form()
        try:
            require_csrf(request, str(form.get("csrf_token") or ""))
            record, article = load_record(article_id, request)
            revision = int(str(form.get("revision") or "0"))
            actual_hash = str(form.get("actual_hash") or "")
            if revision != int(record["revision"]) or actual_hash != article.file_hash:
                raise articles.ArticleConflict("確認後にファイルが再び変更されました。取り込みを停止しました。")
            db.accept_external_change(article_id, actual_hash, revision, db_path)
            return RedirectResponse(f"/articles/{article_id}/edit", status_code=303)
        except (articles.ArticleError, RuntimeError, ValueError) as exc:
            return error_page(str(exc), request.app.state.csrf_token, 409)

    @app.post("/articles/{article_id}/archive")
    async def archive_article(article_id: str, request: Request):
        form = await request.form()
        try:
            require_csrf(request, str(form.get("csrf_token") or "")); db.set_archive(article_id, True, db_path)
            return RedirectResponse("/articles", status_code=303)
        except (articles.ArticleError, RuntimeError) as exc:
            return error_page(str(exc), request.app.state.csrf_token)

    @app.post("/articles/{article_id}/restore")
    async def restore_article(article_id: str, request: Request):
        form = await request.form()
        try:
            require_csrf(request, str(form.get("csrf_token") or "")); db.set_archive(article_id, False, db_path)
            record, restored = load_record(article_id, request)
            if publishing.public_sync_status(restored, request.app.state.public_posts) == "matched":
                db.reconcile_published_article(article_id, restored.file_hash, db_path)
            return RedirectResponse(f"/articles/{article_id}/edit", status_code=303)
        except (articles.ArticleError, RuntimeError) as exc:
            return error_page(str(exc), request.app.state.csrf_token)

    @app.get("/articles/{article_id}/unpublish", response_class=HTMLResponse)
    async def unpublish_confirm(article_id: str, request: Request) -> str:
        try:
            _record, article = load_record(article_id, request)
            if publishing.public_sync_status(article, request.app.state.public_posts) == "missing":
                raise articles.ArticleError("公開中の記事が見つかりません。")
            body = f'''<section class="card danger-zone"><h2>公開を停止します</h2><p>公開サイトからこの記事を取り下げます。管理原稿は削除せず、設定・履歴から復元できます。</p><form method="post" action="/articles/{article_id}/unpublish">{hidden_csrf(request.app.state.csrf_token)}<label>確認のためslugを入力<input name="confirm_slug" required></label><button class="button danger" type="submit">公開停止を実行</button></form></section>'''
            return article_workspace(request, f"公開停止: {article.slug}", body, article_id)
        except articles.ArticleError as exc:
            return error_page(str(exc), request.app.state.csrf_token)

    @app.post("/articles/{article_id}/unpublish")
    async def unpublish_execute(article_id: str, request: Request):
        form = await request.form()
        try:
            require_csrf(request, str(form.get("csrf_token") or ""))
            _record, article = load_record(article_id, request)
            if str(form.get("confirm_slug") or "").strip() != article.slug:
                raise articles.ArticleError("確認用slugが一致しません。")
            sha, pages_url = publishing.unpublish_article(article, request.app.state.command_runner)
            db.mark_unpublished_archived(article_id, db_path)
            db.record_event("unpublish", "success", "unpublish_completed", f"記事 {article.slug} の公開を停止しました。", db_path)
            body = f'<section class="card notice"><h2>公開を停止しました</h2><p>管理原稿は削除済みに保持しています。</p><p><code>{escape(sha[:12])}</code></p><a class="button secondary" href="/settings">設定・履歴へ</a></section>'
            return HTMLResponse(layout("公開停止完了", "/articles", body, request.app.state.csrf_token))
        except (articles.ArticleError, publishing.PublishError, RuntimeError) as exc:
            return error_page(str(exc), request.app.state.csrf_token)

    @app.get("/articles/{article_id}/history", response_class=HTMLResponse)
    async def article_history(article_id: str, request: Request):
        try:
            record, _article = load_record(article_id, request)
        except articles.ArticleError as exc:
            return error_page(str(exc), request.app.state.csrf_token, 404)
        files = articles.history_files(state_root, article_id)
        autosaves = articles.autosave_files(state_root, article_id)
        rows = "".join(f'<tr><td>{escape(path.name)}</td><td>{path.stat().st_size} bytes</td><td><form method="post" action="/articles/{article_id}/history/{escape(path.name)}/restore">{hidden_csrf(request.app.state.csrf_token)}<input type="hidden" name="tab_id" value="restore-{uuid.uuid4().hex[:12]}"><button class="button secondary" type="submit">復元候補にする</button></form></td></tr>' for path in files) or '<tr><td colspan="3" class="muted">確定保存前の履歴はまだありません。</td></tr>'
        autosave_rows = "".join(f'<tr><td>{escape(path.name)}</td><td>{path.stat().st_size} bytes</td><td><a class="button secondary" href="/articles/{article_id}/edit?recovery={escape(path.name)}">編集画面で確認</a></td></tr>' for path in autosaves) or '<tr><td colspan="3" class="muted">自動保存・復元候補はありません。</td></tr>'
        events = db.recent_article_events(article_id, db_path)
        event_rows = "".join(f"<tr><td>{escape(str(item['created_at']))}</td><td>{escape(str(item['safe_message']))}</td><td>{escape(str(item['result']))}</td></tr>" for item in events)
        body = f"""<section class="card notice"><p>復元は正本を直接上書きせず、自動保存領域へ候補を作ります。</p><a href="/articles/{article_id}/edit">編集画面へ戻る</a></section>
<section class="card"><h2>自動保存・復元候補</h2><div class="table-wrap"><table><tbody>{autosave_rows}</tbody></table></div></section>
<section class="card"><h2>確定保存前の履歴</h2><div class="table-wrap"><table><tbody>{rows}</tbody></table></div></section>
<section class="card"><h2>操作履歴</h2><div class="table-wrap"><table><tbody>{event_rows}</tbody></table></div></section>"""
        return article_workspace(request, f"履歴: {record['slug']}", body, article_id)

    @app.post("/articles/{article_id}/history/{history_name}/restore")
    async def history_restore(article_id: str, history_name: str, request: Request):
        form = await request.form()
        try:
            require_csrf(request, str(form.get("csrf_token") or "")); load_record(article_id, request)
            candidate_path = articles.restore_candidate(state_root, article_id, str(form.get("tab_id") or ""), history_name)
            db.record_article_event(article_id, "history_restore", "success", "restore_candidate_created", "履歴から復元候補を作成しました。", db_path)
            return RedirectResponse(f"/articles/{article_id}/edit?recovery={candidate_path.name}", status_code=303)
        except articles.ArticleError as exc:
            return error_page(str(exc), request.app.state.csrf_token)

    descriptions = {
        "/schedule": "予約とカレンダーは記事投稿機能の完成後に実装します。", "/editorial": "AI編集部は後続Phaseで実装します。",
        "/releases": "新作・セール情報は後続Phaseで実装します。", "/social": "SNS連携は後続Phaseで実装します。", "/analytics": "アクセス解析は後続Phaseで実装します。",
    }
    for path, label, phase in NAV_ITEMS:
        if path in descriptions:
            async def placeholder(request: Request, *, page_label: str = label, page_phase: str = phase, page_path: str = path) -> str:
                body = f'<section class="card empty"><span class="phase">{escape(page_phase)}</span><h2>準備中です</h2><p>{escape(descriptions[page_path])}</p></section>'
                return layout(page_label, page_path, body, request.app.state.csrf_token)
            app.add_api_route(path, placeholder, methods=["GET"], response_class=HTMLResponse)

    @app.get("/settings", response_class=HTMLResponse)
    async def settings(request: Request) -> str:
        events = db.recent_events(db_path)
        rows = "".join(f"<tr><td>{escape(str(item['created_at']))}</td><td>{escape(str(item['event_type']))}</td><td>{escape(str(item['result']))}</td><td>{escape(str(item['safe_message']))}</td></tr>" for item in events) or '<tr><td colspan="4">履歴はありません。</td></tr>'
        deleted_rows: list[str] = []
        for item in db.list_articles(db_path, include_archived=True):
            if str(item["state"]) != "archived":
                continue
            title = str(item["slug"])
            public_action = ""
            try:
                deleted = articles.read_article(Path(str(item["source_path"])), str(item["id"]), str(item["slug"]))
                title = str(deleted.metadata.get("title") or item["slug"])
                if publishing.public_sync_status(deleted, request.app.state.public_posts) != "missing":
                    public_action = f'<a class="button danger" href="/articles/{item["id"]}/unpublish">公開停止</a>'
            except articles.ArticleError:
                pass
            deleted_rows.append(f'''<tr><td>{escape(title)}</td><td>{escape(str(item["slug"]))}</td><td><div class="inline-actions"><form method="post" action="/articles/{item["id"]}/restore">{hidden_csrf(request.app.state.csrf_token)}<button class="button secondary" type="submit">復元</button></form>{public_action}</div></td></tr>''')
        deleted_table = "".join(deleted_rows) or '<tr><td colspan="3">削除した記事はありません。</td></tr>'
        public_only = publishing.public_only_slugs(content_root, request.app.state.public_posts)
        public_rows = "".join(f'''<tr><td>{escape(slug)}</td><td><form method="post" action="/settings/import-public/{escape(slug)}">{hidden_csrf(request.app.state.csrf_token)}<button class="button secondary" type="submit">管理画面へ取り込む</button></form></td></tr>''' for slug in public_only) or '<tr><td colspan="2">公開側だけの記事はありません。</td></tr>'
        body = f"""<section class="grid"><article class="card"><h2>稼働設定</h2><dl><dt>接続範囲</dt><dd>このPCのみ</dd><dt>状態DB</dt><dd>var/admin/admin.sqlite3</dd><dt>記事操作</dt><dd>Phase E有効</dd></dl></article>
<article class="card"><h2>安全性</h2><p class="ok">公開は検査と最終確認後だけ実行します。</p></article></section><section class="card"><h2>削除した記事の復元</h2><div class="table-wrap"><table><tbody>{deleted_table}</tbody></table></div></section><section class="card"><h2>最近の履歴</h2><div class="table-wrap"><table><tbody>{rows}</tbody></table></div></section>"""
        body = body.replace('<section class="card"><h2>最近の履歴</h2>', f'<section class="card"><h2>公開側だけの記事</h2><div class="table-wrap"><table><tbody>{public_rows}</tbody></table></div></section><section class="card"><h2>最近の履歴</h2>')
        return layout("設定・履歴", "/settings", body, request.app.state.csrf_token)

    @app.post("/settings/import-public/{slug}")
    async def import_public(slug: str, request: Request):
        form = await request.form()
        try:
            require_csrf(request, str(form.get("csrf_token") or ""))
            imported = publishing.import_public_article(content_root, slug, request.app.state.public_posts)
            try:
                db.register_imported_published_article(imported.article_id, imported.slug, str(imported.metadata.get("article_type") or "play_note"), str(imported.path.resolve()), imported.file_hash, db_path)
            except Exception:
                shutil.rmtree(imported.path, ignore_errors=True)
                raise
            return RedirectResponse(f"/articles/{imported.article_id}/edit?status=published", status_code=303)
        except (articles.ArticleError, publishing.PublishError, Exception) as exc:
            if isinstance(exc, (articles.ArticleError, publishing.PublishError)):
                return error_page(str(exc), request.app.state.csrf_token)
            return error_page("公開記事の取り込みに失敗しました。公開記事と既存原稿は変更していません。", request.app.state.csrf_token, 500)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "scope": "localhost_only", "phase": "F", "version": APP_VERSION}

    return app


app = create_app()
