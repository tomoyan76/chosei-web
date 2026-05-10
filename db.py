"""
SQLite データベース管理モジュール
"""
import os
import sqlite3
import json
from pathlib import Path
from typing import Optional, List, Dict, Any

# Railway ボリューム (/data) があればそこを使う、なければアプリ直下
_data_dir = Path("/data") if Path("/data").exists() else Path(__file__).parent
DB_PATH = Path(os.environ.get("DATABASE_PATH", str(_data_dir / "chosei.db")))


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """データベースとテーブルを初期化する"""
    with get_conn() as conn:
        conn.executescript("""
        -- 設定テーブル（シングルトン）
        CREATE TABLE IF NOT EXISTS settings (
            id          INTEGER PRIMARY KEY CHECK (id = 1),
            full_name   TEXT    NOT NULL DEFAULT '',
            nickname    TEXT    NOT NULL DEFAULT '',
            google_token TEXT   DEFAULT NULL
        );
        INSERT OR IGNORE INTO settings (id, full_name, nickname)
        VALUES (1, '', '');

        -- 調整さん管理テーブル
        CREATE TABLE IF NOT EXISTS chouseisan_items (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            url                 TEXT    UNIQUE NOT NULL,
            title               TEXT    NOT NULL DEFAULT '',
            status              TEXT    NOT NULL DEFAULT 'pending',
            confirmed_date_text TEXT    DEFAULT NULL,
            my_respondent_name  TEXT    DEFAULT NULL,
            created_at          TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at          TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        -- 候補日テーブル
        CREATE TABLE IF NOT EXISTS candidate_dates (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            chouseisan_id     INTEGER NOT NULL,
            date_text         TEXT    NOT NULL,
            my_answer         TEXT    DEFAULT NULL,
            calendar_event_id TEXT    DEFAULT NULL,
            is_confirmed      INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (chouseisan_id) REFERENCES chouseisan_items(id) ON DELETE CASCADE
        );

        -- 回答者選択の記憶テーブル
        CREATE TABLE IF NOT EXISTS respondent_selections (
            url             TEXT PRIMARY KEY,
            respondent_name TEXT NOT NULL
        );
        """)


# ────────────────────────────────────────────────
# 設定
# ────────────────────────────────────────────────

def get_settings() -> Dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
        return dict(row) if row else {}


def update_settings(full_name: str, nickname: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE settings SET full_name = ?, nickname = ? WHERE id = 1",
            (full_name, nickname)
        )


def get_google_token() -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT google_token FROM settings WHERE id = 1").fetchone()
        if row and row["google_token"]:
            return json.loads(row["google_token"])
        return None


def save_google_token(token_dict: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE settings SET google_token = ? WHERE id = 1",
            (json.dumps(token_dict),)
        )


def clear_google_token() -> None:
    with get_conn() as conn:
        conn.execute("UPDATE settings SET google_token = NULL WHERE id = 1")


# ────────────────────────────────────────────────
# 調整さんアイテム
# ────────────────────────────────────────────────

def list_items() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM chouseisan_items ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_item(item_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM chouseisan_items WHERE id = ?", (item_id,)
        ).fetchone()
        return dict(row) if row else None


def get_item_by_url(url: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM chouseisan_items WHERE url = ?", (url,)
        ).fetchone()
        return dict(row) if row else None


def create_item(url: str, title: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO chouseisan_items (url, title) VALUES (?, ?)",
            (url, title)
        )
        return cur.lastrowid


def update_item(item_id: int, **kwargs) -> None:
    allowed = {"title", "status", "confirmed_date_text", "my_respondent_name", "updated_at"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    fields["updated_at"] = "datetime('now', 'localtime')"
    set_clause = ", ".join(
        f"{k} = datetime('now', 'localtime')" if k == "updated_at" else f"{k} = ?"
        for k in fields
    )
    values = [v for k, v in fields.items() if k != "updated_at"]
    with get_conn() as conn:
        conn.execute(
            f"UPDATE chouseisan_items SET {set_clause} WHERE id = ?",
            (*values, item_id)
        )


def update_item_simple(item_id: int, **kwargs) -> None:
    """updated_at も含めてシンプルに更新"""
    allowed = {"title", "status", "confirmed_date_text", "my_respondent_name"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_parts = [f"{k} = ?" for k in fields]
    set_parts.append("updated_at = datetime('now', 'localtime')")
    set_clause = ", ".join(set_parts)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE chouseisan_items SET {set_clause} WHERE id = ?",
            (*fields.values(), item_id)
        )


def delete_item(item_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM chouseisan_items WHERE id = ?", (item_id,))


# ────────────────────────────────────────────────
# 候補日
# ────────────────────────────────────────────────

def list_candidate_dates(chouseisan_id: int) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM candidate_dates WHERE chouseisan_id = ? ORDER BY id",
            (chouseisan_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def upsert_candidate_date(
    chouseisan_id: int,
    date_text: str,
    my_answer: Optional[str],
    calendar_event_id: Optional[str] = None,
    is_confirmed: int = 0
) -> int:
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM candidate_dates WHERE chouseisan_id = ? AND date_text = ?",
            (chouseisan_id, date_text)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE candidate_dates
                   SET my_answer = ?, is_confirmed = ?
                   WHERE id = ?""",
                (my_answer, is_confirmed, existing["id"])
            )
            return existing["id"]
        else:
            cur = conn.execute(
                """INSERT INTO candidate_dates
                   (chouseisan_id, date_text, my_answer, calendar_event_id, is_confirmed)
                   VALUES (?, ?, ?, ?, ?)""",
                (chouseisan_id, date_text, my_answer, calendar_event_id, is_confirmed)
            )
            return cur.lastrowid


def update_candidate_event_id(candidate_id: int, event_id: Optional[str]) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE candidate_dates SET calendar_event_id = ? WHERE id = ?",
            (event_id, candidate_id)
        )


def delete_candidate_dates(chouseisan_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM candidate_dates WHERE chouseisan_id = ?", (chouseisan_id,)
        )


# ────────────────────────────────────────────────
# 回答者選択の記憶
# ────────────────────────────────────────────────

def get_saved_respondent(url: str) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT respondent_name FROM respondent_selections WHERE url = ?", (url,)
        ).fetchone()
        return row["respondent_name"] if row else None


def save_respondent_selection(url: str, respondent_name: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO respondent_selections (url, respondent_name)
               VALUES (?, ?)
               ON CONFLICT(url) DO UPDATE SET respondent_name = excluded.respondent_name""",
            (url, respondent_name)
        )
