"""FastAPIで動くlocalhost限定のブログ管理画面。"""

from __future__ import annotations

import asyncio
import calendar
import secrets
import shutil
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path

import frontmatter
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.middleware.trustedhost import TrustedHostMiddleware

from admin import analytics, article_templates, articles, db, editorial_explanations, game_collection, game_information, game_scheduling, publishing, scheduling, social
from admin.article_input import ArticleInput


ADMIN_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ADMIN_ROOT / "static"
ADMIN_DB_SNAPSHOT = ADMIN_ROOT.parent / "backup-source" / "admin" / "admin.sqlite3"
APP_VERSION = (ADMIN_ROOT / "app-version.txt").read_text(encoding="utf-8").strip()
AI_REVIEW_ENABLED = False
ANALYTICS_REVIEW_DAY = 1
ANALYTICS_REVIEW_HOUR = 20
STATE_LABELS = {
    "draft": "下書き", "review_pending": "校正待ち", "ready": "公開準備完了",
    "scheduled": "予約済み", "published": "公開済み", "archived": "アーカイブ",
}
TYPE_LABELS = {key: template.label for key, template in article_templates.TEMPLATES.items()}
NAV_ITEMS = (
    ("/articles", "記事管理", "Phase F"), ("/schedule", "スケジュール", "Phase G"),
    ("/editorial", "AI編集部", "Phase K"), ("/releases", "リリース・セール情報", "Phase J"),
    ("/social", "X投稿", "Phase I"), ("/analytics", "アクセス解析", "Phase H"),
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
    script_tag = "".join(f'<script src="{item}?v={escape(APP_VERSION)}" defer></script>' for item in scripts)
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">{meta}
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)} | ゲームブログ管理</title>
<link rel="stylesheet" href="/static/admin.css?v={escape(APP_VERSION)}">{script_tag}</head><body class="{escape(body_class)}">
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
        task = None
        if not testing:
            async def schedule_worker() -> None:
                while True:
                    try:
                        await asyncio.to_thread(
                            scheduling.process_due_schedules, db_path, state_root,
                            _app.state.command_runner,
                        )
                        await asyncio.to_thread(game_scheduling.process_due_weekly_collection, db_path)
                    except Exception:
                        try:
                            db.record_event(
                                "schedule_worker", "failure", "schedule_worker_failed",
                                "予約確認処理で異常が発生しました。次回確認時に再試行します。", db_path,
                            )
                        except Exception:
                            pass
                    await asyncio.sleep(30)
            task = asyncio.create_task(schedule_worker())
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

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
<label data-play-time>プレイ時間<input name="play_time" placeholder="例：12時間"></label><label data-play-status>クリア状況<select name="game_completed"><option value="false" selected>未クリア</option><option value="true">クリア</option></select></label><label>著者<input name="author" required value="やまもと"></label>
<button class="button" type="submit">作成</button></form></section>"""
        return article_workspace(request, "新しい記事", body, extra_script="/static/template-form.js")

    @app.post("/articles/new")
    async def article_create(request: Request):
        form = await request.form()
        try:
            require_csrf(request, str(form.get("csrf_token") or ""))
            slug = str(form.get("slug") or "").strip() or articles.next_daily_slug(content_root)
            article_input = ArticleInput.from_mapping(form)
            article_id, path, digest = articles.create_article_files(
                content_root, slug, article_input.title, article_input.article_type,
                article_input.author, article_input.description, article_input.play_time,
                article_input.game_completed,
            )
            db.create_article(article_id, path.name, article_input.article_type, str(path.resolve()), digest, db_path)
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
        if str(record["state"]) == "scheduled" and record.get("scheduled_at"):
            notice += f'<div class="flash publish-note"><strong>{escape(scheduling.display_datetime(record["scheduled_at"]))} に公開予約済みです。</strong> 予約後に編集する場合は、先に予約を解除してください。</div>'
        if record.get("schedule_error"):
            notice += f'<div class="flash error"><strong>予約公開を安全停止しました。</strong> {escape(str(record["schedule_error"]))}</div>'
        if conflict:
            notice += f'<div class="flash error"><strong>外部変更を検出しました。保存を停止しています。</strong><p>ファイル内容を確認し、この内容を管理画面へ取り込む場合だけ次を押してください。</p><form method="post" action="/articles/{article_id}/accept-external">{hidden_csrf(request.app.state.csrf_token)}<input type="hidden" name="revision" value="{record["revision"]}"><input type="hidden" name="actual_hash" value="{escape(article.file_hash)}"><button class="button danger" type="submit">外部変更を取り込む</button></form></div>'
        inspection = article_templates.validate_metadata(article.metadata)
        inspection_badge = f'<span class="validation-count" title="{escape(" ".join(inspection))}">未入力 {len(inspection)}</span>' if inspection else ""
        current_type = str(article.metadata.get("article_type") or record["article_type"])
        play_time_hidden = "" if current_type == "play_note" else " hidden"
        game_completed = article.metadata.get("game_completed") is True
        game_completed_options = f'<option value="false"{"" if game_completed else " selected"}>未クリア</option><option value="true"{" selected" if game_completed else ""}>クリア</option>'
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
<label data-play-status{play_time_hidden}>クリア状況<select name="game_completed">{game_completed_options}</select></label>
<div class="save-line"><span>{escape(state_label(record))} {inspection_badge}</span><span id="save-status">保存済み</span></div></section>
<section class="card body-card"><div class="section-head"><h2>本文</h2><div class="editor-actions"><button class="button" type="submit" {'disabled' if conflict or archived else ''}>手動保存</button><a class="button secondary" href="/articles/{article_id}/history">履歴・復元</a></div></div>
<textarea class="body-editor" name="body" rows="24" aria-label="本文">{escape(article.body)}</textarea></section></form>
<section class="card"><h2>画像</h2><ul class="image-list">{image_rows}</ul><form class="image-upload" method="post" action="/articles/{article_id}/images" enctype="multipart/form-data">{hidden_csrf(request.app.state.csrf_token)}
<input type="file" name="image" accept="image/png,image/jpeg,image/gif,image/webp,image/avif" required><button class="button secondary" type="submit" {'disabled' if archived else ''}>追加</button></form></section>
<section class="card"><h2>公開</h2><div class="editor-actions"><form method="post" action="/articles/{article_id}/preview">{hidden_csrf(request.app.state.csrf_token)}<button class="button secondary" {'disabled' if conflict or archived else ''}>プレビュー</button></form><form method="post" action="/articles/{article_id}/prepublish">{hidden_csrf(request.app.state.csrf_token)}<button class="button" {'disabled' if conflict or archived or str(record['state']) == 'scheduled' else ''}>公開前チェック</button></form></div></section>
<section class="card"><h2>予約公開</h2>{(f'''<p><strong>{escape(scheduling.display_datetime(record['scheduled_at']))}</strong> に公開します。</p><form method="post" action="/articles/{article_id}/schedule/cancel">{hidden_csrf(request.app.state.csrf_token)}<button class="button secondary" type="submit">予約を解除</button></form>''' if str(record['state']) == 'scheduled' else f'''<p class="muted">管理画面が停止中でも、次回起動時に期限を過ぎた予約を処理します。</p><form class="schedule-form" method="post" action="/articles/{article_id}/schedule/check">{hidden_csrf(request.app.state.csrf_token)}<label>公開日時<input type="datetime-local" name="scheduled_at" min="{datetime.now(scheduling.JST).strftime('%Y-%m-%dT%H:%M')}" required></label><button class="button" type="submit" {'disabled' if conflict or archived else ''}>予約前チェック</button></form>''')}</section>
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

    @app.post("/articles/{article_id}/schedule/check", response_class=HTMLResponse)
    async def article_schedule_check(article_id: str, request: Request):
        form = await request.form()
        try:
            require_csrf(request, str(form.get("csrf_token") or ""))
            record, article = load_record(article_id, request)
            if str(record["state"]) == "scheduled":
                raise publishing.PublishError("すでに予約済みです。変更する場合は予約を解除してください。")
            if form.get("title") is not None:
                if str(record["state"]) == "archived":
                    raise articles.ArticleError("アーカイブ中の記事は予約できません。")
                revision = int(str(form.get("revision") or "0"))
                expected_hash = str(form.get("expected_hash") or "")
                if revision != int(record["revision"]) or expected_hash != str(record["file_hash"]):
                    raise articles.ArticleConflict("別の画面で保存済みです。再読み込みしてください。")
                article_input = ArticleInput.from_mapping(form)
                data = articles.updated_markdown(
                    article, title=article_input.title, description=article_input.description,
                    article_type=article_input.article_type, body=article_input.body,
                    play_time=article_input.play_time, game_completed=article_input.game_completed,
                )
                if data != (article.path / "index.md").read_bytes():
                    new_hash, _history = articles.commit_article(article, data, state_root, expected_hash, revision)
                    db.update_saved_article(article_id, article_input.article_type, expected_hash, new_hash, revision, db_path)
                    record, article = load_record(article_id, request)
            if str(record["file_hash"]) != article.file_hash:
                raise publishing.PublishError("外部変更があるため予約前チェックを停止しました。")
            if articles.has_uncommitted_autosave(state_root, article):
                raise publishing.PublishError("手動保存されていない編集内容があります。手動保存してからやり直してください。")
            scheduled = scheduling.parse_local_datetime(str(form.get("scheduled_at") or ""))
            result, prepared = publishing.prepublish_check(article, state_root, request.app.state.command_runner)
            if not result.ok or prepared is None:
                raise publishing.PublishError(" ".join(result.errors))
            db.mark_ready(article_id, article.file_hash, db_path)
            attempt_id, token, token_hash, expires = publishing.new_attempt_values()
            utc_value = scheduled.isoformat(timespec="seconds")
            db.create_publish_attempt(attempt_id, article_id, article.file_hash, token_hash, expires, db_path, scheduled_for=utc_value)
            warning_rows = "".join(f"<li>{escape(item)}</li>" for item in result.warnings) or "<li>警告はありません。</li>"
            body = f'''<section class="card notice"><h2>予約前チェックに合格しました</h2><dl><dt>対象記事</dt><dd>{escape(article.slug)}</dd><dt>公開日時</dt><dd>{escape(scheduling.display_datetime(utc_value))}</dd><dt>公開先</dt><dd>GitHub Pages</dd></dl><h3>警告</h3><ul>{warning_rows}</ul></section><section class="card danger-zone"><h2>予約の最終確認</h2><p>指定時刻以降に対象記事だけをcommit・pushします。</p><form method="post" action="/articles/{article_id}/schedule/confirm">{hidden_csrf(request.app.state.csrf_token)}<input type="hidden" name="attempt_id" value="{attempt_id}"><input type="hidden" name="approval_token" value="{escape(token)}"><input type="hidden" name="scheduled_at" value="{escape(utc_value)}"><button class="button danger">この日時で予約する</button></form></section>'''
            return article_workspace(request, "予約の最終確認", body, article_id)
        except (articles.ArticleError, publishing.PublishError, RuntimeError, ValueError) as exc:
            return error_page(str(exc), request.app.state.csrf_token)

    @app.post("/articles/{article_id}/schedule/confirm")
    async def article_schedule_confirm(article_id: str, request: Request):
        form = await request.form()
        attempt_id = str(form.get("attempt_id") or "")
        try:
            require_csrf(request, str(form.get("csrf_token") or ""))
            record, article = load_record(article_id, request)
            attempt = db.get_publish_attempt(attempt_id, db_path)
            if attempt is None or str(attempt["article_id"]) != article_id or str(attempt["result"]) != "checked":
                raise publishing.PublishError("予約承認が見つからないか、すでに使用済みです。")
            if datetime.fromisoformat(str(attempt["expires_at"])) < datetime.now(timezone.utc):
                db.update_publish_attempt(attempt_id, "expired", "予約承認の期限が切れました。", db_path=db_path)
                raise publishing.PublishError("予約承認の期限が切れました。再検査してください。")
            if not publishing.token_matches(str(form.get("approval_token") or ""), str(attempt["token_hash"])):
                raise publishing.PublishError("予約承認情報が一致しません。")
            scheduled = scheduling.parse_local_datetime(str(form.get("scheduled_at") or ""))
            if str(attempt.get("scheduled_for") or "") != scheduled.isoformat(timespec="seconds"):
                raise publishing.PublishError("確認した予約日時と一致しません。再検査してください。")
            if str(attempt["file_hash"]) != article.file_hash or str(record["file_hash"]) != article.file_hash or str(record["state"]) != "ready":
                raise publishing.PublishError("検査後に記事または状態が変わりました。再検査してください。")
            db.mark_scheduled(article_id, article.file_hash, scheduled.isoformat(timespec="seconds"), db_path)
            db.update_publish_attempt(attempt_id, "success", "記事の公開を予約しました。", db_path=db_path)
            return RedirectResponse(f"/articles/{article_id}/edit", status_code=303)
        except (articles.ArticleError, publishing.PublishError, RuntimeError, ValueError) as exc:
            return error_page(str(exc), request.app.state.csrf_token)

    @app.post("/articles/{article_id}/schedule/cancel")
    async def article_schedule_cancel(article_id: str, request: Request):
        form = await request.form()
        try:
            require_csrf(request, str(form.get("csrf_token") or ""))
            db.cancel_schedule(article_id, db_path)
            return RedirectResponse(f"/articles/{article_id}/edit", status_code=303)
        except (articles.ArticleError, RuntimeError) as exc:
            return error_page(str(exc), request.app.state.csrf_token)

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
            article_input = ArticleInput.from_mapping(payload)
            data = articles.updated_markdown(
                article, title=article_input.title, description=article_input.description,
                article_type=article_input.article_type, body=article_input.body,
                play_time=article_input.play_time, game_completed=article_input.game_completed,
            )
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
            article_input = ArticleInput.from_mapping(form)
            data = articles.updated_markdown(
                article, title=article_input.title, description=article_input.description,
                article_type=article_input.article_type, body=article_input.body,
                play_time=article_input.play_time, game_completed=article_input.game_completed,
            )
            new_hash, _history = articles.commit_article(article, data, state_root, expected_hash, revision)
            db.update_saved_article(article_id, article_input.article_type, expected_hash, new_hash, revision, db_path)
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

    @app.get("/schedule", response_class=HTMLResponse)
    async def schedule_page(request: Request, view: str = "month", date_value: str = "") -> str:
        view = view if view in {"month", "week"} else "month"
        try:
            focus = date.fromisoformat(date_value) if date_value else datetime.now(scheduling.JST).date()
        except ValueError:
            focus = datetime.now(scheduling.JST).date()
        records = db.list_calendar_articles(db_path)
        events: dict[date, list[tuple[dict[str, object], str, str]]] = {}
        for item in records:
            value = item.get("scheduled_at") or item.get("published_at")
            if not value:
                continue
            local = datetime.fromisoformat(str(value)).astimezone(scheduling.JST)
            title = str(item["slug"])
            try:
                article = articles.read_article(Path(str(item["source_path"])), str(item["id"]), str(item["slug"]))
                title = str(article.metadata.get("title") or title)
            except articles.ArticleError:
                pass
            label = "予約" if item.get("scheduled_at") else "公開"
            events.setdefault(local.date(), []).append((item, title, f"{local:%H:%M} {label}"))
        if view == "week":
            start = focus - timedelta(days=focus.weekday())
            days = [start + timedelta(days=i) for i in range(7)]
            previous, following = start - timedelta(days=7), start + timedelta(days=7)
            heading = f"{start:%Y年%m月%d日} - {days[-1]:%m月%d日}"
        else:
            start = focus.replace(day=1)
            _, count = calendar.monthrange(start.year, start.month)
            pad = start.weekday()
            days = [start - timedelta(days=pad) + timedelta(days=i) for i in range(((pad + count + 6) // 7) * 7)]
            previous = (start - timedelta(days=1)).replace(day=1)
            following = (start + timedelta(days=count)).replace(day=1)
            heading = f"{start:%Y年%m月}"
        cells = []
        for day in days:
            event_html = "".join(f'<a class="calendar-event {"scheduled" if item.get("scheduled_at") else "published"}" href="/articles/{item["id"]}/edit"><span>{escape(meta)}</span>{escape(title)}</a>' for item, title, meta in events.get(day, []))
            if day.day == ANALYTICS_REVIEW_DAY:
                event_html += f'<a class="calendar-event analytics-review" href="/analytics"><span>{ANALYTICS_REVIEW_HOUR:02d}:00 定期</span>前月アクセス解析レビュー</a>'
            outside = " outside" if view == "month" and day.month != start.month else ""
            cells.append(f'<div class="calendar-day{outside}"><time>{day.day}</time>{event_html}</div>')
        body = f'''<section class="calendar-toolbar"><div class="picker-tabs calendar-tabs"><a class="{'active' if view == 'month' else ''}" href="/schedule?view=month&date_value={focus.isoformat()}">月</a><a class="{'active' if view == 'week' else ''}" href="/schedule?view=week&date_value={focus.isoformat()}">週</a></div><a class="button secondary" href="/schedule?view={view}&date_value={previous.isoformat()}">前へ</a><h2>{heading}</h2><a class="button secondary" href="/schedule?view={view}&date_value={following.isoformat()}">次へ</a></section><div class="calendar-grid {'week' if view == 'week' else ''}">{''.join(cells)}</div><section class="card calendar-help"><p>毎月1日20:00に前月のUmamiデータをエクスポートし、よく読まれた記事と次に書く方向性を確認します。記事の自動決定・自動公開は行いません。</p><p>記事の予約・公開予定も表示します。SNS投稿、発売日、セール終了日は各Phaseの実装後に追加します。</p></section>'''
        return layout("スケジュール", "/schedule", body, request.app.state.csrf_token)

    @app.get("/analytics", response_class=HTMLResponse)
    async def analytics_page(request: Request, days: int = 30, imported: int = 0) -> str:
        days = days if days in {7, 30, 90} else 30
        start, end, previous_start, previous_end = analytics.period(days)
        current = db.analytics_summary(start.isoformat(), end.isoformat(), db_path)
        previous = db.analytics_summary(previous_start.isoformat(), previous_end.isoformat(), db_path)
        maximum = max((int(item["views"]) for item in current["daily"]), default=0)
        chart_rows = "".join(
            f'''<div class="analytics-bar-row"><time>{escape(str(item["day"])[5:])}</time><div class="analytics-bar"><i style="width:{(int(item['views']) * 100 / maximum) if maximum else 0:.1f}%"></i></div><b>{item['views']}</b></div>'''
            for item in current["daily"]
        ) or '<p class="muted">この期間のデータはありません。</p>'
        page_titles: dict[str, str] = {}
        for record in db.list_articles(db_path, include_archived=True):
            try:
                article = articles.read_article(Path(str(record["source_path"])), str(record["id"]), str(record["slug"]))
                page_titles[f"/posts/{record['slug']}/"] = str(article.metadata.get("title") or record["slug"])
            except articles.ArticleError:
                pass
        page_row_parts: list[str] = []
        for item in current["pages"]:
            path_value = str(item["path"])
            title_value = f'<strong>{escape(page_titles[path_value])}</strong><br>' if path_value in page_titles else ""
            page_row_parts.append(
                f"<tr><td>{title_value}<code>{escape(path_value)}</code></td><td>{item['views']}</td><td>{item['visitors']}</td></tr>"
            )
        page_rows = "".join(page_row_parts) or '<tr><td colspan="3" class="muted">データはありません。</td></tr>'
        suggestion_rows = "".join(f"<li>{escape(item)}</li>" for item in analytics.suggestions(current, previous))
        import_rows = "".join(
            f"<tr><td>{escape(str(item['created_at'])[:16])}</td><td>{escape(str(item['source']))}</td><td>{escape(str(item['filename']))}</td><td>{item['row_count']}行</td></tr>"
            for item in db.recent_analytics_imports(db_path)
        ) or '<tr><td colspan="4" class="muted">取込履歴はありません。</td></tr>'
        flash = '<div class="flash success">解析データを取り込みました。</div>' if imported else ""
        body = f'''{flash}<section class="analytics-toolbar"><div class="picker-tabs analytics-tabs"><a class="{'active' if days == 7 else ''}" href="/analytics?days=7">7日</a><a class="{'active' if days == 30 else ''}" href="/analytics?days=30">30日</a><a class="{'active' if days == 90 else ''}" href="/analytics?days=90">90日</a></div><span class="muted">{start.isoformat()} ～ {end.isoformat()}</span></section>
<section class="analytics-metrics"><article class="card"><span>閲覧数</span><strong>{current['views']}</strong><small>直前期間 {analytics.change_percent(int(current['views']), int(previous['views']))}</small></article><article class="card"><span>訪問者数（延べ）</span><strong>{current['visitors']}</strong><small>直前期間 {analytics.change_percent(int(current['visitors']), int(previous['visitors']))}</small></article></section>
<section class="card"><h2>日別閲覧数</h2><div class="analytics-chart">{chart_rows}</div></section>
<section class="card"><h2>よく読まれたページ</h2><div class="table-wrap"><table><thead><tr><th>ページ</th><th>閲覧数</th><th>訪問者数（延べ）</th></tr></thead><tbody>{page_rows}</tbody></table></div></section>
<section class="card"><h2>確認候補</h2><ul>{suggestion_rows}</ul></section>
<section class="card analytics-import"><h2>アクセス解析CSVを取り込む</h2><p class="muted">Umamiのエクスポートに含まれる <code>website_event.csv</code>、またはひな形と同じ集計済みCSVに対応します。個別のセッションID、端末、地域、参照元などは保存せず、日別・ページ別の表示数と訪問者数だけを保存します。</p><form method="post" action="/analytics/import" enctype="multipart/form-data">{hidden_csrf(request.app.state.csrf_token)}<label>CSVファイル<input type="file" name="file" accept="text/csv,.csv" required></label><div class="editor-actions"><button class="button" type="submit">取り込む</button><a class="button secondary" href="/analytics/template.csv">ひな形CSV</a></div></form></section>
<section class="card"><h2>取込履歴</h2><div class="table-wrap"><table><tbody>{import_rows}</tbody></table></div></section>
<section class="card notice"><h2>Umami Cloudを利用しています</h2><p>公開サイトの計測は有効です。API自動取得は行わず、毎月1日にUmamiから手動でエクスポートした <code>website_event.csv</code> を取り込みます。</p></section>'''
        return layout("アクセス解析", "/analytics", body, request.app.state.csrf_token)

    @app.get("/analytics/template.csv", response_class=PlainTextResponse)
    async def analytics_template() -> PlainTextResponse:
        return PlainTextResponse(
            analytics.TEMPLATE, media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="analytics-template.csv"'},
        )

    @app.post("/analytics/import")
    async def analytics_import(request: Request):
        form = await request.form()
        upload = form.get("file")
        try:
            require_csrf(request, str(form.get("csrf_token") or ""))
            if not isinstance(upload, StarletteUploadFile) or not upload.filename:
                raise analytics.AnalyticsError("CSVファイルを選択してください。")
            filename = Path(upload.filename).name
            if not filename.casefold().endswith(".csv"):
                raise analytics.AnalyticsError("CSVファイルを選択してください。")
            rows, source = analytics.parse_import(await upload.read(analytics.MAX_CSV_BYTES + 1))
            db.import_analytics_rows(rows, source, filename, db_path)
            db.record_event("analytics_import", "success", "analytics_imported", "解析データを取り込みました。", db_path)
            return RedirectResponse("/analytics?imported=1", status_code=303)
        except (analytics.AnalyticsError, articles.ArticleError) as exc:
            body = f'<section class="card error-card"><h2>取込を停止しました</h2><p>{escape(str(exc))}</p><a class="button secondary" href="/analytics">アクセス解析へ戻る</a></section>'
            return HTMLResponse(layout("安全停止", "/analytics", body, request.app.state.csrf_token), status_code=400)
        finally:
            if isinstance(upload, StarletteUploadFile):
                await upload.close()

    @app.get("/social", response_class=HTMLResponse)
    async def social_page(request: Request, created: int = 0) -> str:
        article_options: list[str] = []
        for record in db.list_articles(request.app.state.db_path):
            if str(record.get("state")) != "published" or record.get("file_hash") != record.get("published_file_hash"):
                continue
            try:
                article = articles.read_article(Path(str(record["source_path"])), str(record["id"]), str(record["slug"]))
                title = str(article.metadata.get("title") or article.slug)
                article_options.append(f'<option value="{escape(article.article_id)}">{escape(title)}</option>')
            except articles.ArticleError:
                continue
        options = "".join(article_options)
        draft_rows: list[str] = []
        status_labels = {"draft": "下書き", "reviewed": "確認済み", "posted": "手動投稿済み"}
        for item in db.list_social_drafts(request.app.state.db_path):
            try:
                article = articles.read_article(Path(str(item["source_path"])), str(item["article_id"]), str(item["slug"]))
                title = str(article.metadata.get("title") or item["slug"])
                changed = article.file_hash != str(item["article_file_hash"])
            except articles.ArticleError:
                title, changed = str(item["slug"]), True
            draft_id, status = str(item["id"]), str(item["status"])
            changed_notice = '<p class="flash error">記事が変更されています。この記事から新しい投稿案を作成してください。</p>' if changed and status != "posted" else ""
            if status == "draft":
                next_action = f'''<form method="post" action="/social/drafts/{escape(draft_id)}/review">{hidden_csrf(request.app.state.csrf_token)}<button class="button" type="submit" {'disabled' if changed else ''}>内容を確認済みにする</button></form>'''
            elif status == "reviewed":
                next_action = f'''<form class="social-posted-form x-only" method="post" action="/social/drafts/{escape(draft_id)}/posted">{hidden_csrf(request.app.state.csrf_token)}<label>Xの投稿URL（任意）<input name="posted_url" type="url" maxlength="500" placeholder="https://x.com/..."></label><button class="button" type="submit" {'disabled' if changed else ''}>Xへ投稿済みにする</button></form>'''
            else:
                platform, posted_url = escape(str(item.get("platform") or social.PLATFORM)), str(item.get("posted_url") or "")
                link = f' · <a class="text-link" href="{escape(posted_url)}" target="_blank" rel="noopener">投稿を開く</a>' if posted_url else ""
                next_action = f'<p class="muted">{platform}へ手動投稿した記録があります{link}</p>'
            draft_rows.append(f'''<section class="card social-draft"><div class="section-head"><div><h2>{escape(title)}</h2><span class="state">{status_labels.get(status, escape(status))}</span></div><button class="button secondary" type="button" data-copy-social="social-{escape(draft_id)}">コピー</button></div>{changed_notice}<form method="post" action="/social/drafts/{escape(draft_id)}/save">{hidden_csrf(request.app.state.csrf_token)}<label>投稿文<textarea id="social-{escape(draft_id)}" name="message" rows="6" maxlength="{social.MAX_MESSAGE_LENGTH}" {'readonly' if status == 'posted' else ''}>{escape(str(item['message']))}</textarea></label>{'' if status == 'posted' else '<button class="button secondary" type="submit">投稿案を保存</button>'}</form>{next_action}</section>''')
        draft_html = "".join(draft_rows) or '<section class="card empty"><h2>投稿案はまだありません</h2></section>'
        flash = '<div class="flash">X投稿案を作成しました。</div>' if created else ""
        if options:
            create_form = f'<form method="post" action="/social/drafts">{hidden_csrf(request.app.state.csrf_token)}<label>公開記事<select name="article_id" required>{options}</select></label><button class="button" type="submit">投稿案を作る</button></form>'
        else:
            create_form = '<p>投稿案を作成できる公開済み記事はありません。</p>'
        body = f'''{flash}<section class="card notice"><h2>当面はXだけで運用します</h2><p>投稿案の作成、内容確認、Xへの手動投稿記録までをPC内で管理します。X APIによる予約投稿・結果取得・自動投稿は保留しています。</p></section><section class="card social-create"><h2>公開記事からX投稿案を作る</h2><p class="muted">記事タイトル・概要・URLから案を作ります。Xへの送信は行いません。最終的な文字数はXの投稿画面でも確認してください。</p>{create_form}</section><div class="social-list">{draft_html}</div>'''
        return layout("X投稿", "/social", body, request.app.state.csrf_token, "/static/social.js")

    def social_error(request: Request, message: str) -> HTMLResponse:
        body = f'<section class="card error-card"><h2>処理を停止しました</h2><p>{escape(message)}</p><a class="button secondary" href="/social">SNSへ戻る</a></section>'
        return HTMLResponse(layout("安全停止", "/social", body, request.app.state.csrf_token), status_code=400)

    def require_current_social_article(draft: dict[str, object], request: Request) -> None:
        record, article = load_record(str(draft["article_id"]), request)
        if article.file_hash != str(draft["article_file_hash"]) or str(record["state"]) != "published":
            raise social.SocialError("記事が変更されています。この記事から新しい投稿案を作成してください。")

    @app.post("/social/drafts")
    async def social_create(request: Request):
        try:
            form = await request.form(); require_csrf(request, str(form.get("csrf_token") or ""))
            article_id = str(form.get("article_id") or "")
            record, article = load_record(article_id, request)
            if str(record["state"]) != "published" or record.get("published_file_hash") != article.file_hash:
                raise social.SocialError("公開中の内容と一致する記事だけから投稿案を作成できます。")
            message = social.generate_message(str(article.metadata.get("title") or article.slug), str(article.metadata.get("description") or ""), article.slug)
            db.create_social_draft(uuid.uuid4().hex, article_id, article.file_hash, message, request.app.state.db_path)
            return RedirectResponse("/social?created=1", status_code=303)
        except (articles.ArticleError, social.SocialError, RuntimeError) as exc:
            return social_error(request, str(exc))

    @app.post("/social/drafts/{draft_id}/save")
    async def social_save(draft_id: str, request: Request):
        try:
            form = await request.form(); require_csrf(request, str(form.get("csrf_token") or ""))
            draft = db.get_social_draft(draft_id, request.app.state.db_path)
            if draft is None or str(draft["status"]) == "posted":
                raise social.SocialError("編集できるSNS投稿案が見つかりません。")
            db.update_social_draft(draft_id, social.validate_message(str(form.get("message") or "")), request.app.state.db_path)
            return RedirectResponse("/social", status_code=303)
        except (articles.ArticleError, social.SocialError, RuntimeError) as exc:
            return social_error(request, str(exc))

    @app.post("/social/drafts/{draft_id}/review")
    async def social_review(draft_id: str, request: Request):
        try:
            form = await request.form(); require_csrf(request, str(form.get("csrf_token") or ""))
            draft = db.get_social_draft(draft_id, request.app.state.db_path)
            if draft is None: raise social.SocialError("SNS投稿案が見つかりません。")
            require_current_social_article(draft, request)
            db.review_social_draft(draft_id, request.app.state.db_path)
            return RedirectResponse("/social", status_code=303)
        except (articles.ArticleError, social.SocialError, RuntimeError) as exc:
            return social_error(request, str(exc))

    @app.post("/social/drafts/{draft_id}/posted")
    async def social_posted(draft_id: str, request: Request):
        try:
            form = await request.form(); require_csrf(request, str(form.get("csrf_token") or ""))
            draft = db.get_social_draft(draft_id, request.app.state.db_path)
            if draft is None: raise social.SocialError("SNS投稿案が見つかりません。")
            require_current_social_article(draft, request)
            db.mark_social_draft_posted(draft_id, social.PLATFORM, social.validate_posted_url(str(form.get("posted_url") or "")), request.app.state.db_path)
            return RedirectResponse("/social", status_code=303)
        except (articles.ArticleError, social.SocialError, RuntimeError) as exc:
            return social_error(request, str(exc))

    @app.get("/releases", response_class=HTMLResponse)
    async def releases_page(request: Request) -> str:
        summary = db.game_information_summary(request.app.state.db_path)
        readiness = game_collection.collection_readiness()
        decision_labels = {
            "play_candidate": "プレイ候補", "article_candidate": "記事候補",
            "hold": "保留", "not_interested": "興味なし",
        }
        candidate_row_parts: list[str] = []
        for item in db.list_game_candidates(request.app.state.db_path):
            options = "".join(
                f'<option value="{value}"{" selected" if item.get("latest_decision") == value else ""}>{label}</option>'
                for value, label in decision_labels.items()
            )
            if not item.get("latest_decision"):
                options = '<option value="" disabled hidden selected>選択</option>' + options
            kind_label = "新作" if item["candidate_kind"] == "new_release" else (
                "セール" if item["candidate_kind"] == "sale" else escape(str(item["candidate_kind"]))
            )
            status_label = "候補" if item["status"] == "active" else (
                "要確認" if item["status"] == "unconfirmed" else "除外"
            )
            candidate_row_parts.append(
                f'<tr><td><a href="{escape(str(item["store_url"]))}" target="_blank" rel="noopener">{escape(str(item["title"]))}</a></td>'
                f'<td>{kind_label}</td><td>{status_label}</td><td>{item["total_score"]}</td>'
                f'<td>{escape(str(item.get("exclusion_reason") or ""))}</td>'
                f'<td>{escape(decision_labels.get(str(item.get("latest_decision") or ""), "未判断"))}</td>'
                f'<td><form class="candidate-decision-form" method="post" action="/releases/candidates/{item["steam_app_id"]}/decision">'
                f'{hidden_csrf(request.app.state.csrf_token)}<select name="decision" aria-label="候補の判断">{options}</select>'
                '<button class="button secondary" type="submit">記録</button></form></td></tr>'
            )
        candidate_rows = "".join(candidate_row_parts) or '<tr><td colspan="7" class="muted">試運転前のため候補はありません。</td></tr>'
        suitable_labels = {"play": "プレイ向き", "article": "記事向き", "sale_article": "セール記事向き", "hold": "保留"}
        explanation_parts = [
            f'<article class="candidate-explanation"><h3><a href="{escape(str(item["store_url"]))}" target="_blank" rel="noopener">{escape(str(item["title"]))}</a></h3>'
            f'<span class="state">{escape(suitable_labels.get(str(item["suitable_for"]), str(item["suitable_for"])))}</span>'
            f'<p>{escape(str(item["explanation"]))}</p></article>'
            for item in db.list_candidate_explanations(request.app.state.db_path, 13)
        ]
        explanations = "".join(explanation_parts) or '<p class="muted">AI説明はまだありません。固定採点の候補はそのまま利用できます。</p>'
        last_run = summary["last_run"]
        if isinstance(last_run, dict):
            run_text = (
                f"{escape(str(last_run['started_at'])[:16])} · "
                f"{escape(str(last_run['status']))} · {escape(str(last_run['safe_message']))}"
            )
        else:
            run_text = "まだ実行していません。"
        trial_notice = '<section class="notice success">Apify APIの3件接続確認が完了しました。</section>' if request.query_params.get("trial") == "success" else ""
        if request.query_params.get("candidate_trial") == "success":
            trial_notice = '<section class="notice success">最大10件の候補試運転が完了しました。</section>'
        if request.query_params.get("ownership") == "success":
            count = escape(str(request.query_params.get("count") or "0"))
            trial_notice = f'<section class="notice success">Steam所有ゲームを{count}件同期しました。</section>'
        trial_control = (
            f'<form method="post" action="/releases/apify-trial">{hidden_csrf(request.app.state.csrf_token)}'
            '<button class="button" type="submit">3件でAPI接続を確認</button></form>'
            if readiness.trial_ready else
            '<button class="button" type="button" disabled>APIトークン設定後に接続確認</button>'
        )
        candidate_trial_control = (
            f'<form method="post" action="/releases/candidate-trial">{hidden_csrf(request.app.state.csrf_token)}'
            '<button class="button" type="submit">最大10件で候補試運転</button></form>'
            if readiness.trial_ready else ""
        )
        gemini_ready = bool(game_collection._environment_secret("GEMINI_API_KEY"))
        explanation_control = (
            f'<form method="post" action="/releases/explanations">{hidden_csrf(request.app.state.csrf_token)}'
            '<button class="button secondary" type="submit">候補説明を更新</button></form>'
            if gemini_ready and summary["candidates"] else ""
        )
        ownership_control = (
            f'<form method="post" action="/releases/ownership-sync">{hidden_csrf(request.app.state.csrf_token)}'
            '<button class="button secondary" type="submit">所有ゲームを今すぐ同期</button></form>'
            if readiness.ownership_sync_ready else ""
        )
        body = f'''{trial_notice}<section class="analytics-metrics game-metrics">
<article class="card"><span>ゲーム</span><strong>{summary['games']}</strong></article>
<article class="card"><span>有効候補</span><strong>{summary['candidates']}</strong></article>
<article class="card"><span>未確認</span><strong>{summary['unconfirmed']}</strong></article>
<article class="card"><span>情報源 / 価格履歴</span><strong>{summary['sources']} / {summary['prices']}</strong></article></section>
<section class="card"><h2>収集準備</h2><p class="ok">RSSとSteam日本向け情報を最大10件で検査する処理は準備できています。</p>
<dl class="readiness-list"><dt>4Gamer公式RSS</dt><dd>週次候補へ接続済み</dd><dt>AUTOMATON / Game*Spark</dt><dd>公式取得口が確認できるまで保留</dd><dt>Apify APIトークン</dt><dd>{'設定済み' if readiness.apify_token else '未設定'}</dd><dt>Gemini候補説明</dt><dd>{'設定済み' if gemini_ready else 'APIキー未設定（固定採点は利用可能）'}</dd><dt>採用Actor</dt><dd>{escape(game_collection.APIFY_ACTOR_ID)}</dd><dt>Steam所有情報</dt><dd>{'設定済み' if readiness.ownership_sync_ready else 'APIキーとSteam IDが未設定'}</dd></dl>
<p class="muted">秘密情報の値は画面・DB・ログへ保存しません。週次収集は木曜8:00以降の起動時に同じ週を一度だけ処理します。</p><div class="button-row">{trial_control}{candidate_trial_control}{ownership_control}{explanation_control}</div></section>
<section class="card"><h2>最終収集</h2><p>{run_text}</p></section>
<section class="card"><h2>固定採点の補足</h2>{explanations}</section>
<section class="card"><h2>候補</h2><div class="table-wrap"><table><thead><tr><th>ゲーム</th><th>種類</th><th>状態</th><th>点数</th><th>除外・確認理由</th><th>判断</th><th>操作</th></tr></thead><tbody>{candidate_rows}</tbody></table></div></section>'''
        return layout("リリース・セール情報", "/releases", body, request.app.state.csrf_token)

    @app.post("/releases/apify-trial")
    async def run_releases_apify_trial(request: Request):
        form = await request.form()
        run_id = uuid.uuid4().hex
        started = False
        try:
            require_csrf(request, str(form.get("csrf_token") or ""))
            token = game_collection.apify_api_token()
            if not token:
                raise game_information.GameInformationError("Apify APIトークンが管理画面へ反映されていません。設定後に管理画面を起動し直してください。")
            last_run = db.game_information_summary(request.app.state.db_path).get("last_run")
            if isinstance(last_run, dict) and last_run.get("run_kind") == "trial":
                started_at = datetime.fromisoformat(str(last_run["started_at"]))
                if datetime.now(timezone.utc) - started_at < timedelta(hours=24):
                    raise game_information.GameInformationError("前回の試運転から24時間以内のため、再実行を停止しました。")
            db.start_game_collection_run(run_id, "trial", len(game_collection.APIFY_TRIAL_APP_IDS), request.app.state.db_path)
            started = True
            observations = await asyncio.to_thread(game_collection.run_apify_trial, token)
            for game, price in observations:
                source = game_information.SourceRecord(
                    source_kind="steam", source_name="Apify Steam Store Games Scraper",
                    url=str(game["store_url"]), article_title=str(game["title"]),
                    candidate_reason="API接続確認用の固定ゲーム", discovered_at=str(game.get("verified_at") or db.utc_now()),
                ).validated()
                db.save_game_observation(game, source, price, request.app.state.db_path)
            complete = len(observations) == len(game_collection.APIFY_TRIAL_APP_IDS)
            db.finish_game_collection_run(
                run_id, "success" if complete else "partial",
                "Apify APIの接続確認を完了しました。" if complete else "一部のゲームだけ確認できました。",
                items_discovered=len(observations), items_stored=len(observations),
                apify_items=len(observations), db_path=request.app.state.db_path,
            )
            return RedirectResponse("/releases?trial=success", status_code=303)
        except game_information.GameInformationError as exc:
            if started:
                try:
                    db.finish_game_collection_run(run_id, "failure", str(exc), db_path=request.app.state.db_path)
                except RuntimeError:
                    pass
            return error_page(str(exc), request.app.state.csrf_token)

    @app.post("/releases/candidate-trial")
    async def run_releases_candidate_trial(request: Request):
        form = await request.form()
        run_id = uuid.uuid4().hex
        started = False
        try:
            require_csrf(request, str(form.get("csrf_token") or ""))
            token = game_collection.apify_api_token()
            if not token:
                raise game_information.GameInformationError("Apify APIトークンが管理画面へ反映されていません。")
            last_run = db.game_information_summary(request.app.state.db_path).get("last_run")
            if (isinstance(last_run, dict) and last_run.get("run_kind") == "trial"
                    and int(last_run.get("item_limit") or 0) == game_collection.TRIAL_ITEM_LIMIT):
                started_at = datetime.fromisoformat(str(last_run["started_at"]))
                if datetime.now(timezone.utc) - started_at < timedelta(hours=24):
                    raise game_information.GameInformationError("前回の候補試運転から24時間以内のため、再実行を停止しました。")
            db.start_game_collection_run(run_id, "trial", game_collection.TRIAL_ITEM_LIMIT, request.app.state.db_path)
            started = True
            result = await asyncio.to_thread(
                game_collection.run_weekly_collection,
                token,
                item_limit=game_collection.TRIAL_ITEM_LIMIT,
            )
            game_scheduling.store_collection_result(result, request.app.state.db_path)
            media_count = sum(len(item.media_items) for item in result.items)
            db.finish_game_collection_run(
                run_id, "success" if len(result.items) == game_collection.TRIAL_ITEM_LIMIT and not result.media_failures else "partial",
                f"最大10件の候補試運転を完了し、{len(result.items)}件と媒体掲載{media_count}件を保存しました。",
                items_discovered=len(result.items), items_stored=len(result.items),
                apify_items=result.apify_items,
                db_path=request.app.state.db_path,
            )
            return RedirectResponse("/releases?candidate_trial=success", status_code=303)
        except game_information.GameInformationError as exc:
            if started:
                try:
                    db.finish_game_collection_run(run_id, "failure", str(exc), db_path=request.app.state.db_path)
                except RuntimeError:
                    pass
            return error_page(str(exc), request.app.state.csrf_token)

    @app.post("/releases/candidates/{steam_app_id}/decision")
    async def save_release_candidate_decision(steam_app_id: str, request: Request):
        form = await request.form()
        try:
            require_csrf(request, str(form.get("csrf_token") or ""))
            db.record_game_decision(
                steam_app_id, str(form.get("decision") or ""), db_path=request.app.state.db_path,
            )
            return RedirectResponse("/releases", status_code=303)
        except ValueError as exc:
            return error_page(str(exc), request.app.state.csrf_token)

    @app.post("/releases/explanations")
    async def update_release_explanations(request: Request):
        form = await request.form()
        try:
            require_csrf(request, str(form.get("csrf_token") or ""))
            count = await asyncio.to_thread(editorial_explanations.generate, request.app.state.db_path)
            db.record_event("candidate_explanations", "success", "candidate_explanations_updated", f"候補説明を{count}件更新しました。", request.app.state.db_path)
            return RedirectResponse("/releases", status_code=303)
        except game_information.GameInformationError as exc:
            return error_page(str(exc), request.app.state.csrf_token)

    @app.post("/releases/ownership-sync")
    async def sync_steam_ownership(request: Request):
        form = await request.form()
        try:
            require_csrf(request, str(form.get("csrf_token") or ""))
            api_key = game_collection._environment_secret("STEAM_WEB_API_KEY")
            steam_id = game_collection._environment_secret("STEAM_ID64")
            if not api_key or not steam_id:
                raise game_information.GameInformationError("Steam APIキーとSteam ID64を設定してから管理画面を起動し直してください。")
            owned_games = await asyncio.to_thread(game_collection.fetch_owned_games, api_key, steam_id)
            db.save_owned_games_snapshot(owned_games, request.app.state.db_path)
            db.record_event(
                "steam_ownership", "success", "steam_ownership_synced",
                f"Steam所有ゲームを{len(owned_games)}件同期しました。", request.app.state.db_path,
            )
            return RedirectResponse(f"/releases?ownership=success&count={len(owned_games)}", status_code=303)
        except game_information.GameInformationError as exc:
            db.record_event(
                "steam_ownership", "failure", "steam_ownership_failed",
                "Steam所有ゲーム同期を安全停止しました。", request.app.state.db_path,
            )
            return error_page(str(exc), request.app.state.csrf_token)

    descriptions = {
        "/editorial": "共通情報基盤の試運転後に、候補3本と推薦理由を表示します。",
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
        game_summary = db.game_information_summary(db_path)
        snapshot_status = "準備済み" if ADMIN_DB_SNAPSHOT.is_file() else "次回バックアップ時に作成"
        body = f"""<section class="grid"><article class="card"><h2>稼働設定</h2><dl><dt>接続範囲</dt><dd>このPCのみ</dd><dt>状態DB</dt><dd>var/admin/admin.sqlite3</dd><dt>現在</dt><dd>Phase J（共通情報基盤）</dd><dt>ゲーム情報</dt><dd>{game_summary['games']}件</dd><dt>DBバックアップ</dt><dd>{snapshot_status}</dd></dl></article>
<article class="card"><h2>安全性</h2><p class="ok">公開は検査と最終確認後だけ実行します。</p><p class="muted">DBの安全な複製は日次・月次バックアップの直前に更新します。</p></article></section><section class="card"><h2>削除した記事の復元</h2><div class="table-wrap"><table><tbody>{deleted_table}</tbody></table></div></section><section class="card"><h2>最近の履歴</h2><div class="table-wrap"><table><tbody>{rows}</tbody></table></div></section>"""
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
        return {"status": "ok", "scope": "localhost_only", "phase": "J", "version": APP_VERSION}

    return app


app = create_app()
