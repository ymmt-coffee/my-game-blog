"""FastAPIで動くlocalhost限定のブログ管理画面。"""

from __future__ import annotations

import secrets
import uuid
from contextlib import asynccontextmanager
from html import escape
from pathlib import Path

import frontmatter
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.middleware.trustedhost import TrustedHostMiddleware

from admin import article_templates, articles, db


ADMIN_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ADMIN_ROOT / "static"
APP_VERSION = (ADMIN_ROOT / "app-version.txt").read_text(encoding="utf-8").strip()
STATE_LABELS = {
    "draft": "下書き", "review_pending": "校正待ち", "ready": "公開準備完了",
    "scheduled": "予約済み", "published": "公開済み", "archived": "アーカイブ",
}
TYPE_LABELS = {key: template.label for key, template in article_templates.TEMPLATES.items()}
NAV_ITEMS = (
    ("/articles", "記事管理", "Phase D"), ("/schedule", "スケジュール", "Phase G"),
    ("/editorial", "AI編集部", "Phase K"), ("/releases", "リリース・セール情報", "Phase L"),
    ("/social", "SNS分析", "Phase I"), ("/analytics", "アクセス解析", "Phase H"),
    ("/settings", "設定・履歴", "Phase B"),
)


def layout(
    title: str,
    current: str,
    body: str,
    csrf_token: str = "",
    script: str | tuple[str, ...] = "",
    body_class: str = "",
) -> str:
    nav = "".join(
        f'<a class="nav-item{" active" if path == current else ""}" href="{path}"><span>{escape(label)}</span><small>{escape(phase)}</small></a>'
        for path, label, phase in NAV_ITEMS
    )
    meta = f'<meta name="csrf-token" content="{escape(csrf_token)}">' if csrf_token else ""
    scripts = (script,) if isinstance(script, str) and script else script
    script_tag = "".join(f'<script src="{item}" defer></script>' for item in scripts)
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">{meta}
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)} | ゲームブログ管理</title>
<link rel="stylesheet" href="/static/admin.css">{script_tag}</head><body class="{escape(body_class)}">
<aside><a class="brand" href="/">ゲームブログ管理<small>このPC内だけで動作</small></a><nav>{nav}</nav></aside>
<main><header><div><p class="eyebrow">LOCAL ADMIN</p><h1>{escape(title)}</h1></div><span class="local-badge">● localhost</span></header>{body}</main></body></html>"""


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
        links.append(
            f'<a class="article-picker-item{active}" href="/articles/{item["id"]}/edit">'
            f'<span class="picker-title">{escape(item_title)}</span><span class="picker-meta">{escape(item_date)} · {escape(STATE_LABELS.get(str(item["state"]), str(item["state"])))}</span></a>'
        )
    article_links = "".join(links) or '<p class="picker-empty">記事はまだありません。</p>'
    middle = f"""<section class="article-picker" id="article-picker"><div class="picker-top">
<button class="picker-toggle" type="button" aria-expanded="true" aria-controls="picker-content" title="記事一覧を折り畳む"><span aria-hidden="true">◀</span><b>記事一覧</b></button></div>
<div class="picker-content" id="picker-content"><a class="button picker-new" href="/articles/new">＋ 新規作成</a>
<div class="picker-list">{article_links}</div><a class="picker-migration" href="/articles/migration">既存原稿を確認</a></div></section>"""
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
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        db.initialize(db_path)
        scan_canonical(content_root, db_path)
        db.record_event("application", "success", "app_started", "管理画面を起動しました。", db_path)
        yield

    app = FastAPI(title="ゲームブログ管理", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.db_path, app.state.content_root, app.state.state_root = db_path, content_root, state_root
    app.state.legacy_root, app.state.csrf_token = legacy_root, secrets.token_urlsafe(32)
    allowed_hosts = ["127.0.0.1", "localhost"] + (["testserver"] if testing else [])
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
    app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> str:
        count = len(db.list_articles(db_path))
        body = f"""<section class="hero card"><div><span class="phase">Phase D</span><h2>カテゴリー別の雛形で記事を作れます</h2>
<p>3種類のテンプレートと必須項目検査を利用できます。</p></div>
<div class="status-box"><strong>{count}件の記事</strong><span>外部公開なし</span><span>自動保存あり</span></div></section>
<section class="grid"><article class="card"><h3>記事管理</h3><p>カテゴリー別の作成、編集、検査、画像、履歴、アーカイブを利用できます。</p><a class="button" href="/articles">記事一覧を開く</a></article>
<article class="card"><h3>既存原稿</h3><p>移行前の原稿は読み取り専用で検査できます。</p><a class="button secondary" href="/articles/migration">移行dry-run</a></article></section>"""
        return layout("ホーム", "/", body, request.app.state.csrf_token)

    @app.get("/articles", response_class=HTMLResponse)
    async def article_list(request: Request, archived: int = 0) -> str:
        detail = """<section class="card empty article-empty"><span class="phase">ARTICLE MANAGEMENT</span><h2>記事を選択してください</h2>
<p>中央の記事一覧から編集する記事を選ぶか、「新規作成」で新しい下書きを作成します。</p></section>"""
        return article_workspace(request, "記事管理", detail)

    @app.get("/articles/new", response_class=HTMLResponse)
    async def article_new(request: Request) -> str:
        options = "".join(f'<option value="{key}">{escape(label)}</option>' for key, label in TYPE_LABELS.items())
        guidance = "".join(f'<p data-template-help="{key}"{"" if key == "play_note" else " hidden"}><strong>{escape(template.label)}</strong><br>{escape(template.guidance)}</p>' for key, template in article_templates.TEMPLATES.items())
        body = f"""<section class="card form-card"><form method="post" action="/articles/new">{hidden_csrf(request.app.state.csrf_token)}
<label>タイトル<input name="title" required maxlength="160"></label><label>slug（URL用の名前）<input name="slug" required pattern="[a-z0-9]+(?:-[a-z0-9]+)*" placeholder="my-game-note"></label>
<label>概要<textarea name="description" rows="2" required maxlength="300"></textarea><small class="field-help">検索結果などに使う、記事の短い紹介文です。</small></label>
<label>カテゴリー<select name="article_type" id="new-article-type">{options}</select><small class="field-help">選んだカテゴリーに合う本文の雛形を作成します。</small></label>
<div class="template-guidance">{guidance}</div><label data-play-time>プレイ時間<input name="play_time" placeholder="例：12時間"><small class="field-help">プレイ途中記だけの必須項目です。</small></label><label>著者<input name="author" required value="やまもと"></label>
<p class="muted">作成時は必ず下書きになります。公開処理はまだ行いません。</p><button class="button" type="submit">下書きを作成</button></form></section>"""
        return article_workspace(request, "新しい記事", body, extra_script="/static/template-form.js")

    @app.post("/articles/new")
    async def article_create(request: Request):
        form = await request.form()
        try:
            require_csrf(request, str(form.get("csrf_token") or ""))
            article_id, path, digest = articles.create_article_files(content_root, str(form.get("slug") or ""), str(form.get("title") or ""), str(form.get("article_type") or ""), str(form.get("author") or ""), str(form.get("description") or ""), str(form.get("play_time") or ""))
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
        images = articles.list_images(article)
        options = "".join(f'<option value="{key}"{" selected" if key == str(record["article_type"]) else ""}>{escape(label)}</option>' for key, label in TYPE_LABELS.items())
        image_rows = "".join(f'<li><code>images/{escape(str(item["name"]))}</code> <span class="muted">{item["size"]} bytes</span></li>' for item in images) or '<li class="muted">画像はありません。</li>'
        notice = recovery_notice + ('<div class="flash success">記事を保存しました。</div>' if saved else ('<div class="flash success">下書きを作成しました。</div>' if created else ""))
        if conflict:
            notice += f'<div class="flash error"><strong>外部変更を検出しました。保存を停止しています。</strong><p>ファイル内容を確認し、この内容を管理画面へ取り込む場合だけ次を押してください。</p><form method="post" action="/articles/{article_id}/accept-external">{hidden_csrf(request.app.state.csrf_token)}<input type="hidden" name="revision" value="{record["revision"]}"><input type="hidden" name="actual_hash" value="{escape(article.file_hash)}"><button class="button danger" type="submit">外部変更を取り込む</button></form></div>'
        archived = str(record["state"]) == "archived"
        inspection = article_templates.validate_metadata(article.metadata)
        inspection_rows = "".join(f'<li>{escape(message)}</li>' for message in inspection)
        inspection_box = (f'<section class="template-check warning"><strong>必須項目：要確認</strong><ul>{inspection_rows}</ul></section>' if inspection else '<section class="template-check success"><strong>必須項目：すべて入力済み</strong></section>')
        current_type = str(article.metadata.get("article_type") or record["article_type"])
        template = article_templates.TEMPLATES.get(current_type, article_templates.TEMPLATES["play_note"])
        play_time_hidden = "" if current_type == "play_note" else " hidden"
        body = f"""{notice}<form class="editor" method="post" action="/articles/{article_id}/save" data-article-id="{article_id}" data-conflict="{str(conflict).lower()}">
{hidden_csrf(request.app.state.csrf_token)}<input type="hidden" name="expected_hash" value="{escape(article.file_hash)}"><input type="hidden" name="revision" value="{record['revision']}">
<input type="hidden" name="tab_id" id="tab-id"><section class="card editor-meta"><label>タイトル<input name="title" value="{escape(str(article.metadata.get('title') or ''))}" required></label>
<label>概要<textarea name="description" rows="2">{escape(str(article.metadata.get('description') or ''))}</textarea><small class="field-help">記事の短い紹介文です。記事ページ冒頭、検索結果、SNS共有時の説明などに使われます。本文の要点を1〜2文で入力します。</small></label><label>カテゴリー<select name="article_type" id="edit-article-type">{options}</select><small class="field-help">カテゴリーを変更しても本文は自動置換しません。</small></label>
<label data-play-time{play_time_hidden}>プレイ時間<input name="play_time" value="{escape(str(article.metadata.get('play_time') or ''))}" placeholder="例：12時間"><small class="field-help">プレイ途中記だけの必須項目です。</small></label>
<div class="template-guidance"><strong>{escape(template.label)}</strong><p>{escape(template.guidance)}</p></div>{inspection_box}
<div class="save-line"><span>状態: <b>{escape(STATE_LABELS.get(str(record['state']), str(record['state'])))}</b></span><span id="save-status">保存済み</span></div></section>
<section class="card"><label>本文<textarea class="body-editor" name="body" rows="24">{escape(article.body)}</textarea></label>
<div class="editor-actions"><button class="button" type="submit" {'disabled' if conflict or archived else ''}>手動保存</button><a class="button secondary" href="/articles/{article_id}/history">履歴・復元</a></div></section></form>
<section class="card"><h2>画像</h2><ul class="image-list">{image_rows}</ul><form method="post" action="/articles/{article_id}/images" enctype="multipart/form-data">{hidden_csrf(request.app.state.csrf_token)}
<input type="file" name="image" accept="image/png,image/jpeg,image/gif,image/webp,image/avif" required><p class="field-help">JPG、PNG、GIF、WebP、AVIF、10MB以下。日本語や空白を含むファイル名は安全な半角名へ自動変換します。</p><button class="button secondary" type="submit" {'disabled' if archived else ''}>画像を追加</button></form></section>
<section class="card publish-placeholder"><h2>校正・プレビュー・投稿</h2><p>この機能はPhase Eで実装します。管理画面で作った記事は、現時点ではここから投稿できません。</p>
<div class="editor-actions"><button class="button secondary" disabled>校正（Phase E）</button><button class="button secondary" disabled>プレビュー（Phase E）</button><button class="button secondary" disabled>投稿（Phase E）</button></div>
<p class="muted">Phase E完了までは、既存のObsidian原稿と従来の校正・プレビュー・公開ショートカットを使用してください。</p></section>
<section class="card danger-zone"><h2>{'アーカイブから戻す' if archived else 'アーカイブ'}</h2><p>ファイルは削除も移動もしません。</p><form method="post" action="/articles/{article_id}/{'restore' if archived else 'archive'}">{hidden_csrf(request.app.state.csrf_token)}<button class="button {'secondary' if archived else 'danger'}" type="submit">{'下書きへ戻す' if archived else 'アーカイブする'}</button></form></section>"""
        return article_workspace(request, f"編集: {record['slug']}", body, article_id, "/static/editor.js")

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
            return RedirectResponse(f"/articles/{article_id}/edit", status_code=303)
        except (articles.ArticleError, RuntimeError) as exc:
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
        body = f"""<section class="grid"><article class="card"><h2>稼働設定</h2><dl><dt>接続範囲</dt><dd>このPCのみ</dd><dt>状態DB</dt><dd>var/admin/admin.sqlite3</dd><dt>記事操作</dt><dd>Phase D有効</dd></dl></article>
<article class="card"><h2>安全性</h2><p class="ok">削除・公開・実移行は無効です。</p></article></section><section class="card"><h2>最近の履歴</h2><div class="table-wrap"><table><tbody>{rows}</tbody></table></div></section>"""
        return layout("設定・履歴", "/settings", body, request.app.state.csrf_token)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "scope": "localhost_only", "phase": "D", "version": APP_VERSION}

    return app


app = create_app()
