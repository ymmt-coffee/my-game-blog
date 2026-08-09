"""FastAPIで動くlocalhost限定の管理画面。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from html import escape
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from admin import db


ADMIN_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ADMIN_ROOT / "static"

NAV_ITEMS = (
    ("/articles", "記事管理", "Phase C"),
    ("/schedule", "スケジュール", "Phase G"),
    ("/editorial", "AI編集部", "Phase K"),
    ("/releases", "リリース・セール情報", "Phase L"),
    ("/social", "SNS分析", "Phase I"),
    ("/analytics", "アクセス解析", "Phase H"),
    ("/settings", "設定・履歴", "Phase B"),
)


def layout(title: str, current: str, body: str) -> str:
    nav = "".join(
        f'<a class="nav-item{" active" if path == current else ""}" href="{path}">'
        f"<span>{escape(label)}</span><small>{escape(phase)}</small></a>"
        for path, label, phase in NAV_ITEMS
    )
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} | ゲームブログ管理</title>
<link rel="stylesheet" href="/static/admin.css"></head>
<body><aside><a class="brand" href="/">ゲームブログ管理<small>このPC内だけで動作</small></a>
<nav>{nav}</nav></aside><main><header><div><p class="eyebrow">LOCAL ADMIN</p>
<h1>{escape(title)}</h1></div><span class="local-badge">● localhost</span></header>{body}</main></body></html>"""


def coming_soon(title: str, phase: str, description: str) -> str:
    body = f"""<section class="card empty"><span class="phase">{escape(phase)}</span>
<h2>準備中です</h2><p>{escape(description)}</p>
<p class="muted">現在は画面の土台だけを提供しています。既存の記事や設定は変更されません。</p></section>"""
    return layout(title, next(path for path, label, _ in NAV_ITEMS if label == title), body)


def create_app(*, db_path: Path = db.DEFAULT_DB_PATH, testing: bool = False) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        db.initialize(db_path)
        db.record_event("application", "success", "app_started", "管理画面を起動しました。", db_path)
        yield

    app = FastAPI(
        title="ゲームブログ管理",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    allowed_hosts = ["127.0.0.1", "localhost"]
    if testing:
        allowed_hosts.append("testserver")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
    app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(_request: Request) -> str:
        body = """<section class="hero card"><div><span class="phase">Phase B</span>
<h2>管理画面の土台ができました</h2><p>記事管理などの機能は、左のメニューから今後段階的に追加します。</p></div>
<div class="status-box"><strong>安全な状態</strong><span>外部公開なし</span><span>記事変更なし</span></div></section>
<section class="grid"><article class="card"><h3>現在できること</h3><p>画面の移動、稼働状態、ローカル履歴とエラーの確認。</p></article>
<article class="card"><h3>次の段階</h3><p>Phase Cで記事一覧、編集、画像、自動保存、復元を実装します。</p></article></section>"""
        return layout("ホーム", "/", body)

    descriptions = {
        "/articles": "記事一覧・編集・画像管理はPhase Cで実装します。",
        "/schedule": "予約とカレンダーは記事投稿機能の完成後に実装します。",
        "/editorial": "AI編集部は共通情報収集基盤の完成後に実装します。",
        "/releases": "新作・セール情報は後続Phaseで実装します。",
        "/social": "SNS連携は記事投稿MVPの完成後に実装します。",
        "/analytics": "アクセス解析は記事投稿MVPの完成後に実装します。",
    }
    for path, label, phase in NAV_ITEMS:
        if path in descriptions:
            async def placeholder(
                _request: Request, *, page_label: str = label, page_phase: str = phase, page_path: str = path
            ) -> str:
                return coming_soon(page_label, page_phase, descriptions[page_path])
            app.add_api_route(path, placeholder, methods=["GET"], response_class=HTMLResponse)

    @app.get("/settings", response_class=HTMLResponse)
    async def settings(_request: Request) -> str:
        events = db.recent_events(db_path)
        rows = "".join(
            f"<tr><td>{escape(str(item['created_at']))}</td><td>{escape(str(item['event_type']))}</td>"
            f"<td><span class=\"result {escape(str(item['result']))}\">{escape(str(item['result']))}</span></td>"
            f"<td>{escape(str(item['safe_message']))}</td></tr>"
            for item in events
        ) or '<tr><td colspan="4" class="muted">履歴はまだありません。</td></tr>'
        body = f"""<section class="grid"><article class="card"><h2>稼働設定</h2>
<dl><dt>接続範囲</dt><dd>このPCのみ（127.0.0.1）</dd><dt>状態DB</dt><dd>var/admin/admin.sqlite3</dd>
<dt>記事操作</dt><dd>未実装・変更なし</dd></dl></article>
<article class="card"><h2>エラー表示</h2><p class="ok">現在、起動を妨げるエラーはありません。</p>
<p class="muted">秘密情報や記事本文は履歴へ保存しません。</p></article></section>
<section class="card"><h2>最近の履歴</h2><div class="table-wrap"><table><thead><tr>
<th>日時（UTC）</th><th>種類</th><th>結果</th><th>内容</th></tr></thead><tbody>{rows}</tbody></table></div></section>"""
        return layout("設定・履歴", "/settings", body)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "scope": "localhost_only", "phase": "B"}

    return app


app = create_app()
