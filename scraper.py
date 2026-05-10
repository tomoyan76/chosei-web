"""
調整さん（chouseisan.com）スクレイパー

新HTML構造（SPA版）:
  window.Chouseisan = {
    "event": {
      "name": "イベント名",
      "members": [
        {"name": "参加者A", "kouho": [1, 3, 2], "is_mine": false},
        ...
      ],
      ...
    },
    "choices": [
      {"num": 1, "choice": "5/17(日) 19:30～", "fixed": 0},
      ...
    ]
  }

kouho の値: 1=○, 2=△, 3=×
"""
import re
import json
import logging
from datetime import datetime, date
from typing import Optional, Dict, Any, List, Tuple

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.9",
}

# kouho の値マッピング
KOUHO_MAP = {
    1: "maru",
    2: "sankaku",
    3: "batsu",
}


def scrape_event(url: str) -> Dict[str, Any]:
    """
    調整さんURLをスクレイピングしてイベント情報を返す。

    返り値:
        {
          "title": str,
          "candidates": [
            {
              "date_text": str,
              "is_confirmed": bool,
              "respondents": {
                "参加者名": "maru"|"sankaku"|"batsu"|None,
                ...
              }
            },
            ...
          ],
          "confirmed_date_text": str | None,
          "respondent_names": [str, ...],
          "error": str | None
        }
    """
    result = {
        "title": "",
        "candidates": [],
        "confirmed_date_text": None,
        "respondent_names": [],
        "error": None,
    }

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        html = resp.text
    except requests.RequestException as e:
        result["error"] = f"ページの取得に失敗しました: {e}"
        return result

    soup = BeautifulSoup(html, "lxml")

    # ── window.Chouseisan JSON を探す ──
    chouseisan_data = _extract_chouseisan_json(soup)

    if chouseisan_data:
        return _parse_from_json(chouseisan_data, result)

    # ── フォールバック: 旧HTMLテーブル構造 ──
    logger.warning("window.Chouseisan not found, trying legacy table parser")
    return _parse_from_table(soup, result)


def _extract_chouseisan_json(soup: BeautifulSoup) -> Optional[Dict]:
    """window.Chouseisan = {...} を抽出してパースする（文字列内の{}を無視）"""
    for script in soup.find_all("script"):
        txt = script.get_text() or ""
        if "window.Chouseisan" not in txt:
            continue

        m = re.search(r"window\.Chouseisan\s*=\s*", txt)
        if not m:
            continue

        start = m.end()
        # 文字列を考慮したブレース対応マッチング
        depth = 0
        end = start
        in_string = False
        escaped = False
        for i, c in enumerate(txt[start:], start):
            if escaped:
                escaped = False
                continue
            if c == "\\" and in_string:
                escaped = True
                continue
            if c == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break

        try:
            json_str = txt[start:end]
            # JavaScript の末尾カンマを除去（JSON非対応）
            json_str = re.sub(r",\s*([}\]])", r"\1", json_str)
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            return None

    return None


def _parse_from_json(data: Dict, result: Dict) -> Dict:
    """window.Chouseisan JSONからイベント情報を抽出する"""
    event = data.get("event", {})
    result["title"] = event.get("name", "")

    # choices（候補日）は event 内または トップレベルにある
    choices = event.get("choices") or data.get("choices", [])
    members = event.get("members", [])

    if not choices:
        result["error"] = "候補日が見つかりませんでした"
        return result

    # 参加者名リスト
    respondent_names = [m.get("name", "") for m in members if m.get("name")]
    result["respondent_names"] = respondent_names

    # 確定日を検出
    confirmed_choice_indices = [i for i, c in enumerate(choices) if c.get("fixed")]

    for i, choice in enumerate(choices):
        date_text = choice.get("choice", "").strip()
        if not date_text:
            continue

        is_confirmed = bool(choice.get("fixed"))

        # 各メンバーの回答を収集
        respondents: Dict[str, Optional[str]] = {}
        for member in members:
            name = member.get("name", "")
            if not name:
                continue
            kouho_list = member.get("kouho", [])
            if i < len(kouho_list):
                val = kouho_list[i]
                respondents[name] = KOUHO_MAP.get(val)
            else:
                respondents[name] = None

        result["candidates"].append(
            {
                "date_text": date_text,
                "is_confirmed": is_confirmed,
                "respondents": respondents,
            }
        )

    # 確定日テキスト
    confirmed = [c for c in result["candidates"] if c["is_confirmed"]]
    if confirmed:
        result["confirmed_date_text"] = confirmed[0]["date_text"]

    return result


def _parse_from_table(soup: BeautifulSoup, result: Dict) -> Dict:
    """旧HTMLテーブル構造のフォールバックパーサー"""
    # タイトル取得
    title_el = (
        soup.find("h1", class_="title")
        or soup.find("h1")
        or soup.find("h2", class_="title")
    )
    if title_el:
        result["title"] = title_el.get_text(strip=True)

    table = _find_schedule_table(soup)
    if table is None:
        result["error"] = "スケジュールテーブルが見つかりませんでした"
        return result

    rows = table.find_all("tr")
    if len(rows) < 2:
        result["error"] = "テーブルの行が不足しています"
        return result

    header_row = rows[0]
    header_cells = header_row.find_all(["th", "td"])
    respondent_names: List[str] = []
    for cell in header_cells[1:]:
        name_el = cell.find(class_="name") or cell.find("span") or cell
        name = name_el.get_text(strip=True)
        if name and name not in ("日程", "コメント", "comment"):
            respondent_names.append(name)

    result["respondent_names"] = respondent_names
    confirmed_text = _detect_confirmed(soup)
    result["confirmed_date_text"] = confirmed_text

    for row in rows[1:]:
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        date_cell = cells[0]
        date_text = date_cell.get_text(strip=True)
        if not date_text or date_text in ("コメント", "comment", ""):
            continue
        if not re.search(r"\d", date_text):
            continue

        is_confirmed = _is_confirmed_row(row, date_text, confirmed_text)
        respondents: Dict[str, Optional[str]] = {}
        for i, name in enumerate(respondent_names):
            if i + 1 < len(cells):
                cell = cells[i + 1]
                answer_text = cell.get_text(strip=True)
                respondents[name] = _normalize_answer(answer_text)
            else:
                respondents[name] = None

        result["candidates"].append(
            {
                "date_text": date_text,
                "is_confirmed": is_confirmed,
                "respondents": respondents,
            }
        )

    return result


def _find_schedule_table(soup: BeautifulSoup) -> Optional[Any]:
    for cls in ["schedule", "list", "timetable", "honbun"]:
        tbl = soup.find("table", class_=cls)
        if tbl:
            return tbl
    tables = soup.find_all("table")
    best = None
    best_count = 0
    for tbl in tables:
        count = len(tbl.find_all("td"))
        if count > best_count:
            best_count = count
            best = tbl
    return best


def _detect_confirmed(soup: BeautifulSoup) -> Optional[str]:
    for tag in soup.find_all(text=re.compile(r"確定|決定|Confirmed|confirmed")):
        parent = tag.parent
        text = parent.get_text(strip=True)
        date_match = re.search(
            r"(\d{4}年\d{1,2}月\d{1,2}日|\d{1,2}月\d{1,2}日|\d{1,2}/\d{1,2})", text
        )
        if date_match:
            return date_match.group(1)
    for cls in ["kakutei", "confirmed", "kettei", "kimari"]:
        el = soup.find(class_=re.compile(cls, re.I))
        if el:
            text = el.get_text(strip=True)
            if text:
                return text
    return None


def _is_confirmed_row(row: Any, date_text: str, confirmed_text: Optional[str]) -> bool:
    if confirmed_text and confirmed_text in date_text:
        return True
    row_classes = " ".join(row.get("class", []))
    if re.search(r"kakutei|confirmed|kettei|kimari|active|selected", row_classes, re.I):
        return True
    return False


ANSWER_MAP = {
    "○": "maru", "〇": "maru", "◎": "maru",
    "△": "sankaku", "▲": "sankaku",
    "×": "batsu", "✕": "batsu", "✗": "batsu",
    "ー": "batsu", "-": "batsu", "－": "batsu",
}


def _normalize_answer(text: str) -> Optional[str]:
    text = text.strip()
    if not text:
        return None
    if text in ANSWER_MAP:
        return ANSWER_MAP[text]
    first = text[0]
    if first in ANSWER_MAP:
        return ANSWER_MAP[first]
    if "○" in text or "〇" in text or "◎" in text:
        return "maru"
    if "△" in text or "▲" in text:
        return "sankaku"
    if "×" in text or "✕" in text or "✗" in text:
        return "batsu"
    return None


# ────────────────────────────────────────────────
# 名前マッチング
# ────────────────────────────────────────────────

def generate_name_tokens(full_name: str, nickname: str) -> List[str]:
    tokens = []
    full_name = full_name.strip()
    nickname = nickname.strip()
    if full_name:
        tokens.append(full_name.replace(" ", "").replace("　", ""))
        parts = re.split(r"[\s　]+", full_name)
        tokens.extend(p for p in parts if p)
    if nickname:
        tokens.append(nickname)
    seen = set()
    result = []
    for t in tokens:
        if t and t not in seen:
            seen.add(t)
            result.append(t)
    return result


def find_matching_respondents(
    respondent_names: List[str], name_tokens: List[str]
) -> List[str]:
    if not name_tokens:
        return []
    matched = []
    for name in respondent_names:
        for token in name_tokens:
            if token and token in name:
                matched.append(name)
                break
    return matched


# ────────────────────────────────────────────────
# 日付パーサー
# ────────────────────────────────────────────────

def parse_date_text(date_text: str) -> Tuple[Optional[date], Optional[datetime], Optional[datetime]]:
    """
    調整さんの日付テキストをパースする。
    例: "5/17(日) 19:30～(0次会)", "2024年1月15日(月)"

    返り値: (all_day_date, start_datetime, end_datetime)
    """
    # 曜日を除去
    text = re.sub(r"[（(][月火水木金土日祝][）)]?", "", date_text).strip()

    year = month = day = None

    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日?", text)
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.search(r"(\d{1,2})月(\d{1,2})日?", text)
        if m:
            year = datetime.now().year
            month, day = int(m.group(1)), int(m.group(2))
        else:
            m = re.search(r"(\d{1,2})/(\d{1,2})", text)
            if m:
                year = datetime.now().year
                month, day = int(m.group(1)), int(m.group(2))

    if not (year and month and day):
        return None, None, None

    # 時間帯: 10:00〜12:00
    time_m = re.search(
        r"(\d{1,2}):(\d{2})\s*[〜～~－\-]\s*(\d{1,2}):(\d{2})", text
    )
    if time_m:
        sh, sm = int(time_m.group(1)), int(time_m.group(2))
        eh, em = int(time_m.group(3)), int(time_m.group(4))
        start_dt = datetime(year, month, day, sh, sm)
        end_dt = datetime(year, month, day, eh, em)
        if end_dt <= start_dt:
            from datetime import timedelta
            end_dt += timedelta(days=1)
        return None, start_dt, end_dt

    # 開始時間のみ: 19:30～
    time_start_m = re.search(r"(\d{1,2}):(\d{2})", text)
    if time_start_m:
        sh, sm = int(time_start_m.group(1)), int(time_start_m.group(2))
        start_dt = datetime(year, month, day, sh, sm)
        from datetime import timedelta
        end_dt = start_dt + timedelta(hours=2)
        return None, start_dt, end_dt

    # 終日
    try:
        return date(year, month, day), None, None
    except ValueError:
        return None, None, None
