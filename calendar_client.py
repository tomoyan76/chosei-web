"""
Google Calendar API クライアント

OAuth2フロー（環境変数ベース）とイベントCRUDを提供する。
credentials.json は不要 — GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET を環境変数で設定する。
"""
import os
import json
import logging
from datetime import date, datetime
from typing import Optional, Dict, Any, Tuple

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google_auth_oauthlib.flow import Flow

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TIMEZONE = "Asia/Tokyo"

ANSWER_STATUS_MAP = {
    "maru": "confirmed",
    "sankaku": "tentative",
}


def _get_redirect_uri() -> str:
    base = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
    return f"{base}/api/auth/callback"


def _build_client_config() -> dict:
    return {
        "web": {
            "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
            "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [_get_redirect_uri()],
        }
    }


# ────────────────────────────────────────────────
# 認証
# ────────────────────────────────────────────────

def is_configured() -> bool:
    """GOOGLE_CLIENT_ID / SECRET が設定されているか確認"""
    return bool(
        os.environ.get("GOOGLE_CLIENT_ID")
        and os.environ.get("GOOGLE_CLIENT_SECRET")
    )


def get_auth_url(state: str) -> Tuple[str, Any]:
    """OAuth認証URLを生成して (auth_url, flow) タプルを返す"""
    flow = Flow.from_client_config(
        _build_client_config(),
        scopes=SCOPES,
        redirect_uri=_get_redirect_uri(),
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        state=state,
        prompt="consent",
    )
    return auth_url, flow


def exchange_code_for_token(code: str, flow: Any = None) -> Dict[str, Any]:
    """認証コードをトークンに交換する。flowが渡された場合はPKCEのcode_verifierを引き継ぐ"""
    if flow is None:
        flow = Flow.from_client_config(
            _build_client_config(),
            scopes=SCOPES,
            redirect_uri=_get_redirect_uri(),
        )
    flow.fetch_token(code=code)
    creds = flow.credentials
    return _credentials_to_dict(creds)


def get_service(token_dict: Dict[str, Any]) -> Tuple[Optional[Any], Dict[str, Any]]:
    """
    トークン辞書からGoogle Calendar APIサービスを取得する。
    トークンが期限切れなら自動リフレッシュする。
    (service, updated_token_dict) を返す。
    """
    try:
        creds = Credentials(
            token=token_dict.get("token"),
            refresh_token=token_dict.get("refresh_token"),
            token_uri=token_dict.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=token_dict.get("client_id") or os.environ.get("GOOGLE_CLIENT_ID"),
            client_secret=token_dict.get("client_secret") or os.environ.get("GOOGLE_CLIENT_SECRET"),
            scopes=token_dict.get("scopes") or SCOPES,
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        return service, _credentials_to_dict(creds)
    except Exception as e:
        logger.error(f"Googleサービス取得失敗: {e}")
        return None, token_dict


def _credentials_to_dict(creds: Credentials) -> Dict[str, Any]:
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id or os.environ.get("GOOGLE_CLIENT_ID"),
        "client_secret": creds.client_secret or os.environ.get("GOOGLE_CLIENT_SECRET"),
        "scopes": list(creds.scopes) if creds.scopes else SCOPES,
    }


# ────────────────────────────────────────────────
# カレンダーイベント CRUD
# ────────────────────────────────────────────────

def create_calendar_event(
    service: Any,
    summary: str,
    date_text: str,
    answer: str,
    description: str = "",
) -> Optional[str]:
    """
    カレンダーイベントを作成して event_id を返す。
    answer: "maru" → confirmed, "sankaku" → tentative
    """
    from scraper import parse_date_text

    status = ANSWER_STATUS_MAP.get(answer, "confirmed")
    all_day_date, start_dt, end_dt = parse_date_text(date_text)

    if all_day_date is None and start_dt is None:
        logger.warning(f"日付パース失敗: {date_text}")
        return None

    if all_day_date is not None:
        # 終日イベント
        date_str = all_day_date.strftime("%Y-%m-%d")
        event_body = {
            "summary": summary,
            "description": description,
            "start": {"date": date_str},
            "end": {"date": date_str},
            "status": status,
            "transparency": "transparent" if status == "tentative" else "opaque",
        }
    else:
        # 時間指定イベント
        event_body = {
            "summary": summary,
            "description": description,
            "start": {
                "dateTime": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                "timeZone": TIMEZONE,
            },
            "end": {
                "dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                "timeZone": TIMEZONE,
            },
            "status": status,
            "transparency": "transparent" if status == "tentative" else "opaque",
        }

    try:
        result = (
            service.events()
            .insert(calendarId="primary", body=event_body)
            .execute()
        )
        logger.info(f"イベント作成: {result.get('id')} [{summary}]")
        return result.get("id")
    except HttpError as e:
        logger.error(f"イベント作成失敗: {e}")
        return None


def update_event_status(
    service: Any,
    event_id: str,
    new_status: str = "confirmed",
) -> bool:
    """イベントのステータスを更新する（確定時に使用）"""
    try:
        event = service.events().get(calendarId="primary", eventId=event_id).execute()
        event["status"] = new_status
        event["transparency"] = "opaque"
        service.events().update(
            calendarId="primary", eventId=event_id, body=event
        ).execute()
        logger.info(f"イベント更新: {event_id} → {new_status}")
        return True
    except HttpError as e:
        logger.error(f"イベント更新失敗: {e}")
        return False


def delete_calendar_event(service: Any, event_id: str) -> bool:
    """カレンダーイベントを削除する"""
    try:
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        logger.info(f"イベント削除: {event_id}")
        return True
    except HttpError as e:
        if e.resp.status == 410:
            # すでに削除済み
            logger.info(f"イベントは既に削除済み: {event_id}")
            return True
        logger.error(f"イベント削除失敗: {e}")
        return False
