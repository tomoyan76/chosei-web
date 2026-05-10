"""
調整さん自動カレンダー登録ツール - FastAPI メインアプリ

起動方法:
    uvicorn main:app --reload --port 8000
"""
import os
import logging
import secrets
import urllib.parse
from pathlib import Path
from typing import Optional, List

# .env ファイルを自動読み込み（本番では実際の環境変数が優先される）
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from apscheduler.schedulers.background import BackgroundScheduler

import db
import scraper as sc
import calendar_client as cal

# ローカル開発用: HTTPでのOAuthを許可（本番では不要）
if os.environ.get("BASE_URL", "").startswith("http://"):
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────
# アプリ初期化
# ────────────────────────────────────────────────

app = FastAPI(title="調整さん自動カレンダー登録ツール", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

db.init_db()

# OAuthステート管理（メモリ内）
_oauth_states: dict = {}

# ────────────────────────────────────────────────
# バックグラウンド定期実行
# ────────────────────────────────────────────────

scheduler = BackgroundScheduler(timezone="Asia/Tokyo")


def auto_check_all():
    """全アイテムを自動チェック（1時間ごと）"""
    logger.info("自動チェック開始")
    items = db.list_items()
    for item in items:
        if item["status"] == "confirmed":
            continue
        try:
            _refresh_item(item["id"])
        except Exception as e:
            logger.error(f"自動チェックエラー (id={item['id']}): {e}")
    logger.info(f"自動チェック完了: {len(items)}件")


@app.on_event("startup")
async def startup_event():
    scheduler.add_job(auto_check_all, "interval", hours=1, id="auto_check")
    scheduler.start()
    logger.info("APScheduler 起動: 1時間ごとに自動チェック")


@app.on_event("shutdown")
async def shutdown_event():
    scheduler.shutdown(wait=False)


# ────────────────────────────────────────────────
# ルートページ
# ────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    index_path = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(content=index_path.read_text(encoding="utf-8"))


@app.get("/manifest.json")
async def serve_manifest():
    return FileResponse(
        Path(__file__).parent / "static" / "manifest.json",
        media_type="application/manifest+json",
    )


@app.get("/sw.js")
async def serve_sw():
    return FileResponse(
        Path(__file__).parent / "static" / "sw.js",
        media_type="application/javascript",
    )


@app.get("/share")
async def share_target(url: str = "", text: str = "", title: str = ""):
    """PWA share_target エンドポイント：シェアシートからURLを受け取り一覧画面へ遷移"""
    shared_url = (url or text).strip()
    if shared_url and "chouseisan.com" in shared_url:
        return RedirectResponse(f"/?shared={urllib.parse.quote(shared_url, safe='')}")
    return RedirectResponse("/")


# ────────────────────────────────────────────────
# 設定 API
# ────────────────────────────────────────────────

class SettingsPayload(BaseModel):
    full_name: str
    nickname: str


@app.get("/api/settings")
async def api_get_settings():
    settings = db.get_settings()
    token = db.get_google_token()
    return {
        "full_name": settings.get("full_name", ""),
        "nickname": settings.get("nickname", ""),
        "google_connected": token is not None,
        "tokens": sc.generate_name_tokens(
            settings.get("full_name", ""), settings.get("nickname", "")
        ),
        "oauth_configured": cal.is_configured(),
    }


@app.post("/api/settings")
async def api_update_settings(payload: SettingsPayload):
    db.update_settings(payload.full_name.strip(), payload.nickname.strip())
    return {"ok": True}


@app.delete("/api/settings/google")
async def api_disconnect_google():
    db.clear_google_token()
    return {"ok": True}


# ────────────────────────────────────────────────
# Google OAuth
# ────────────────────────────────────────────────

@app.get("/api/auth/google")
async def api_auth_google():
    if not cal.is_configured():
        raise HTTPException(
            status_code=400,
            detail="GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET が設定されていません。.env ファイルを確認してください。",
        )
    state = secrets.token_urlsafe(16)
    try:
        auth_url, flow = cal.get_auth_url(state)
        _oauth_states[state] = flow  # Flowオブジェクトを保存してPKCEを引き継ぐ
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OAuth URL生成失敗: {e}")
    return RedirectResponse(url=auth_url)


@app.get("/api/auth/callback")
async def api_auth_callback(request: Request, code: str = None, state: str = None, error: str = None):
    if error:
        return RedirectResponse(url=f"/?auth_error={error}")
    if not state or state not in _oauth_states:
        return RedirectResponse(url="/?auth_error=invalid_state")
    flow = _oauth_states.pop(state, None)

    if not code:
        return RedirectResponse(url="/?auth_error=no_code")

    try:
        token_dict = cal.exchange_code_for_token(code, flow=flow)
        db.save_google_token(token_dict)
    except Exception as e:
        logger.error(f"OAuth交換失敗: {e}")
        return RedirectResponse(url=f"/?auth_error={str(e)[:100]}")

    return RedirectResponse(url="/?auth_success=1")


# ────────────────────────────────────────────────
# 調整さん管理 API
# ────────────────────────────────────────────────

class AddItemPayload(BaseModel):
    url: str


@app.get("/api/chouseisan")
async def api_list_items():
    items = db.list_items()
    result = []
    for item in items:
        candidates = db.list_candidate_dates(item["id"])
        result.append({**item, "candidates": candidates})
    summary = {
        "total": len(items),
        "pending": sum(1 for i in items if i["status"] == "pending"),
        "confirmed": sum(1 for i in items if i["status"] == "confirmed"),
    }
    return {"items": result, "summary": summary}


@app.post("/api/chouseisan")
async def api_add_item(payload: AddItemPayload):
    url = payload.url.strip()
    if not url.startswith("https://chouseisan.com"):
        raise HTTPException(status_code=400, detail="調整さんのURLを入力してください")

    # 既存チェック
    existing = db.get_item_by_url(url)
    if existing:
        raise HTTPException(status_code=409, detail="このURLはすでに登録済みです")

    # スクレイピング
    event_data = sc.scrape_event(url)
    if event_data.get("error"):
        raise HTTPException(status_code=422, detail=event_data["error"])

    title = event_data["title"] or url
    item_id = db.create_item(url, title)

    # 名前マッチング
    settings = db.get_settings()
    tokens = sc.generate_name_tokens(
        settings.get("full_name", ""), settings.get("nickname", "")
    )
    respondent_names = event_data.get("respondent_names", [])
    matches = sc.find_matching_respondents(respondent_names, tokens)

    # 保存済み選択があれば使う
    saved = db.get_saved_respondent(url)
    if saved and saved in respondent_names:
        my_name = saved
    elif len(matches) == 1:
        my_name = matches[0]
        db.save_respondent_selection(url, my_name)
    elif len(matches) == 0:
        # マッチなし → ユーザーに選ばせる（フロント側で対応）
        my_name = None
    else:
        # 複数マッチ → フロント側で選択させる
        return JSONResponse(
            status_code=200,
            content={
                "status": "need_selection",
                "item_id": item_id,
                "url": url,
                "title": title,
                "matches": matches,
                "all_respondents": respondent_names,
                "event_data": event_data,
            },
        )

    if my_name:
        db.update_item_simple(item_id, my_respondent_name=my_name)

    # カレンダー登録
    await _register_candidates(item_id, url, title, event_data, my_name)

    return {"ok": True, "item_id": item_id, "title": title, "my_name": my_name}


class SelectRespondentPayload(BaseModel):
    item_id: int
    respondent_name: str


@app.post("/api/chouseisan/select-respondent")
async def api_select_respondent(payload: SelectRespondentPayload):
    item = db.get_item(payload.item_id)
    if not item:
        raise HTTPException(status_code=404, detail="アイテムが見つかりません")

    db.save_respondent_selection(item["url"], payload.respondent_name)
    db.update_item_simple(payload.item_id, my_respondent_name=payload.respondent_name)

    event_data = sc.scrape_event(item["url"])
    if event_data.get("error"):
        raise HTTPException(status_code=422, detail=event_data["error"])

    await _register_candidates(
        payload.item_id, item["url"], item["title"], event_data, payload.respondent_name
    )
    return {"ok": True}


@app.post("/api/chouseisan/{item_id}/refresh")
async def api_refresh_item(item_id: int):
    item = db.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="アイテムが見つかりません")
    try:
        result = _refresh_item(item_id)
        return {"ok": True, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/chouseisan/{item_id}")
async def api_delete_item(item_id: int):
    item = db.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="アイテムが見つかりません")

    # カレンダーイベントを削除
    candidates = db.list_candidate_dates(item_id)
    token = db.get_google_token()
    if token:
        service, updated_token = cal.get_service(token)
        if updated_token != token:
            db.save_google_token(updated_token)
        if service:
            for c in candidates:
                if c.get("calendar_event_id"):
                    cal.delete_calendar_event(service, c["calendar_event_id"])

    db.delete_item(item_id)
    return {"ok": True}


@app.post("/api/chouseisan/{item_id}/manual-check")
async def api_manual_check(item_id: int):
    """手動でチェックを実行（デバッグ用）"""
    return await api_refresh_item(item_id)


# ────────────────────────────────────────────────
# 内部ヘルパー
# ────────────────────────────────────────────────

async def _register_candidates(
    item_id: int,
    url: str,
    title: str,
    event_data: dict,
    my_name: Optional[str],
):
    """候補日をDBに保存し、カレンダーに登録する"""
    token = db.get_google_token()
    service = None
    if token:
        service, updated_token = cal.get_service(token)
        if updated_token != token:
            db.save_google_token(updated_token)

    confirmed_detected = any(c["is_confirmed"] for c in event_data["candidates"])
    confirmed_date_text = event_data.get("confirmed_date_text")

    for candidate in event_data["candidates"]:
        date_text = candidate["date_text"]
        is_confirmed = candidate["is_confirmed"]

        # 自分の回答を取得
        my_answer = None
        if my_name and my_name in candidate["respondents"]:
            my_answer = candidate["respondents"][my_name]

        # DB保存
        cand_id = db.upsert_candidate_date(
            item_id, date_text, my_answer, is_confirmed=1 if is_confirmed else 0
        )

        # カレンダー登録（○か△のみ）
        if service and my_answer in ("maru", "sankaku"):
            description = f"調整さん: {url}"
            event_label = f"【仮】{title}" if my_answer == "sankaku" else title
            event_id = cal.create_calendar_event(
                service, event_label, date_text, my_answer, description
            )
            if event_id:
                db.update_candidate_event_id(cand_id, event_id)

    # 確定検知
    if confirmed_detected or confirmed_date_text:
        _handle_confirmation(item_id, event_data, service)


def _handle_confirmation(item_id: int, event_data: dict, service):
    """確定日が検知された場合の処理"""
    confirmed_candidates = [c for c in event_data["candidates"] if c["is_confirmed"]]
    confirmed_date_text = (
        confirmed_candidates[0]["date_text"] if confirmed_candidates
        else event_data.get("confirmed_date_text")
    )

    db.update_item_simple(
        item_id,
        status="confirmed",
        confirmed_date_text=confirmed_date_text,
    )

    if service:
        candidates = db.list_candidate_dates(item_id)
        for c in candidates:
            if not c.get("calendar_event_id"):
                continue
            if c.get("is_confirmed"):
                # 確定日 → confirmedに更新
                cal.update_event_status(service, c["calendar_event_id"], "confirmed")
            else:
                # 確定でない候補日 → 削除
                cal.delete_calendar_event(service, c["calendar_event_id"])
                db.update_candidate_event_id(c["id"], None)


def _refresh_item(item_id: int) -> dict:
    """アイテムを最新データで更新する（バックグラウンドでも使用）"""
    item = db.get_item(item_id)
    if not item:
        return {"error": "not_found"}

    event_data = sc.scrape_event(item["url"])
    if event_data.get("error"):
        return {"error": event_data["error"]}

    # タイトル更新
    if event_data["title"] and event_data["title"] != item["title"]:
        db.update_item_simple(item_id, title=event_data["title"])

    my_name = item.get("my_respondent_name")

    # 保存済み選択がない場合は再マッチング
    if not my_name:
        settings = db.get_settings()
        tokens = sc.generate_name_tokens(
            settings.get("full_name", ""), settings.get("nickname", "")
        )
        matches = sc.find_matching_respondents(event_data["respondent_names"], tokens)
        if len(matches) == 1:
            my_name = matches[0]
            db.update_item_simple(item_id, my_respondent_name=my_name)
            db.save_respondent_selection(item["url"], my_name)

    token = db.get_google_token()
    service = None
    if token:
        service, updated_token = cal.get_service(token)
        if updated_token != token:
            db.save_google_token(updated_token)

    # 候補日を更新
    existing_candidates = {c["date_text"]: c for c in db.list_candidate_dates(item_id)}

    for candidate in event_data["candidates"]:
        date_text = candidate["date_text"]
        is_confirmed = candidate["is_confirmed"]
        my_answer = None
        if my_name and my_name in candidate["respondents"]:
            my_answer = candidate["respondents"][my_name]

        existing = existing_candidates.get(date_text)
        cand_id = db.upsert_candidate_date(
            item_id, date_text, my_answer, is_confirmed=1 if is_confirmed else 0
        )

        # カレンダーが未登録で回答が○△なら登録
        if service and my_answer in ("maru", "sankaku"):
            event_id = existing.get("calendar_event_id") if existing else None
            if not event_id:
                title = item.get("title", "")
                event_label = f"【仮】{title}" if my_answer == "sankaku" else title
                new_event_id = cal.create_calendar_event(
                    service, event_label, date_text, my_answer, f"調整さん: {item['url']}"
                )
                if new_event_id:
                    db.update_candidate_event_id(cand_id, new_event_id)

    # 確定検知
    confirmed_detected = any(c["is_confirmed"] for c in event_data["candidates"])
    if confirmed_detected and item["status"] != "confirmed":
        _handle_confirmation(item_id, event_data, service)

    return {"ok": True, "title": event_data["title"]}


# ────────────────────────────────────────────────
# エントリーポイント
# ────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
