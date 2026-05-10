"""
調整さん（chouseisan.com）スクレイパー

HTML構造：
  <h1 class="title">イベント名</h1>
  <table>
    <tr>
      <th></th>  <!-- 日程列ヘッダ（空or「日程」） -->
      <th><div class="name">参加者A</div></th>
      ...
    </tr>
    <tr>
      <td class="kouho">2024年1月15日(月)</td>
      <td>○</td>   <!-- 参加者Aの回答 -->
      ...
    </tr>
  </table>
"""
import re
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

# 回答文字のマッピング
ANSWER_MAP = {
    "○": "maru",
    "〇": "maru",
    "◎": "maru",
    "△": "sankaku",
    "▲": "sankaku",
    "×": "batsu",
    "✕": "batsu",
    "✗": "batsu",
    "×": "batsu",
    "ー": "batsu",
    "-": "batsu",
    "－": "batsu",
}


def scrape_event(url: str) -> Dict[str, Any]:
    """
    調整さんURLをスクレイピングしてイベント情報を返す。

    返り値:
        {
          "title": str,
          "candidates": [
            {
              "date_text": str,       # 生テキスト（例: 2024年1月15日(月)）
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

    # ── タイトル取得 ──
    title_el = (
        soup.find("h1", class_="title")
        or soup.find("h1")
        or soup.find("h2", class_="title")
    )
    if title_el:
        result["title"] = title_el.get_text(strip=True)

    # ── 確定日テキストを探す ──
    confirmed_text = _detect_confirmed(soup)
    result["confirmed_date_text"] = confirmed_text

    # ── スケジュールテーブルを取得 ──
    table = _find_schedule_table(soup)
    if table is None:
        result["error"] = "スケジュールテーブルが見つかりませんでした"
        return result

    rows = table.find_all("tr")
    if len(rows) < 2:
        result["error"] = "テーブルの行が不足しています"
        return result

    # ── ヘッダ行から参加者名を取得 ──
    header_row = rows[0]
    header_cells = header_row.find_all(["th", "td"])
    respondent_names: List[str] = []
    for cell in header_cells[1:]:  # 最初のセルは「日程」列
        name_el = cell.find(class_="name") or cell.find("span") or cell
        name = name_el.get_text(strip=True)
        if name and name not in ("日程", "コメント", "comment"):
            respondent_names.append(name)

    result["respondent_names"] = respondent_names

    # ── データ行から候補日と回答を取得 ──
    # コメント行など不要な行を除外しながら処理
    for row in rows[1:]:
        cells = row.find_all(["td", "th"])
        if not cells:
            continue

        # 日程セルを判定
        date_cell = cells[0]
        date_text = date_cell.get_text(strip=True)
        if not date_text or date_text in ("コメント", "comment", ""):
            continue

        # 日付らしい文字列かチェック（数字が含まれる）
        if not re.search(r"\d", date_text):
            continue

        # 確定日かどうかチェック
        is_confirmed = _is_confirmed_row(row, date_text, confirmed_text)

        # 回答を取得
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
    """スケジュールテーブルを見つける"""
    # クラス名で探す
    for cls in ["schedule", "list", "timetable", "honbun"]:
        tbl = soup.find("table", class_=cls)
        if tbl:
            return tbl

    # テーブルの中で最もセル数が多いものを選ぶ
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
    """確定日テキストを検出する"""
    # 「確定」「決定」を含むテキストを探す
    for tag in soup.find_all(text=re.compile(r"確定|決定|Confirmed|confirmed")):
        parent = tag.parent
        # 確定日テキストを隣接する要素から探す
        text = parent.get_text(strip=True)
        date_match = re.search(
            r"(\d{4}年\d{1,2}月\d{1,2}日|\d{1,2}月\d{1,2}日|\d{1,2}/\d{1,2})", text
        )
        if date_match:
            return date_match.group(1)

    # class に "kakutei" や "confirmed" を含む要素
    for cls in ["kakutei", "confirmed", "kettei", "kimari"]:
        el = soup.find(class_=re.compile(cls, re.I))
        if el:
            text = el.get_text(strip=True)
            if text:
                return text

    return None


def _is_confirmed_row(row: Any, date_text: str, confirmed_text: Optional[str]) -> bool:
    """この行が確定日かどうか判定"""
    if confirmed_text and confirmed_text in date_text:
        return True
    # row のクラスに "kakutei" "confirmed" などが含まれるか
    row_classes = " ".join(row.get("class", []))
    if re.search(r"kakutei|confirmed|kettei|kimari|active|selected", row_classes, re.I):
        return True
    return False


def _normalize_answer(text: str) -> Optional[str]:
    """回答テキストを正規化して maru/sankaku/batsu/None を返す"""
    text = text.strip()
    if not text:
        return None
    # 直接マッピング
    if text in ANSWER_MAP:
        return ANSWER_MAP[text]
    # 先頭文字で判定
    first = text[0]
    if first in ANSWER_MAP:
        return ANSWER_MAP[first]
    # ○が含まれる
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
    """
    本名・ニックネームからマッチングトークンを生成する。
    例: "山田 太郎", "たろう" → ["山田", "太郎", "山田太郎", "たろう"]
    """
    tokens = []
    full_name = full_name.strip()
    nickname = nickname.strip()

    if full_name:
        tokens.append(full_name.replace(" ", "").replace("　", ""))
        parts = re.split(r"[\s　]+", full_name)
        tokens.extend(p for p in parts if p)

    if nickname:
        tokens.append(nickname)

    # 重複除去・空文字除去
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
    """
    回答者名リストの中から name_tokens のいずれかに部分一致するものを返す。
    """
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

    返り値: (all_day_date, start_datetime, end_datetime)
    - 終日イベントの場合: (date_obj, None, None)
    - 時間指定の場合:     (None, start_dt, end_dt)
    """
    # 曜日を除去
    text = re.sub(r"[（(][月火水木金土日祝][）)]?", "", date_text).strip()
    text = re.sub(r"[（(][月火水木金土日祝][）)]", "", text).strip()

    # 年月日を取得
    year = month = day = None

    # 2024年1月15日
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日?", text)
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        # 1月15日
        m = re.search(r"(\d{1,2})月(\d{1,2})日?", text)
        if m:
            year = datetime.now().year
            month, day = int(m.group(1)), int(m.group(2))
        else:
            # 1/15
            m = re.search(r"(\d{1,2})/(\d{1,2})", text)
            if m:
                year = datetime.now().year
                month, day = int(m.group(1)), int(m.group(2))

    if not (year and month and day):
        return None, None, None

    # 時間帯を取得: 10:00〜12:00 or 10:00-12:00
    time_m = re.search(
        r"(\d{1,2}):(\d{2})\s*[〜～~－\-]\s*(\d{1,2}):(\d{2})", text
    )
    if time_m:
        sh, sm = int(time_m.group(1)), int(time_m.group(2))
        eh, em = int(time_m.group(3)), int(time_m.group(4))
        start_dt = datetime(year, month, day, sh, sm)
        end_dt = datetime(year, month, day, eh, em)
        # 終了が開始より早い場合は翌日
        if end_dt <= start_dt:
            from datetime import timedelta
            end_dt += timedelta(days=1)
        return None, start_dt, end_dt

    # 開始時間のみ: 10:00〜 or 10時〜
    time_start_m = re.search(r"(\d{1,2}):(\d{2})", text)
    if time_start_m:
        sh, sm = int(time_start_m.group(1)), int(time_start_m.group(2))
        start_dt = datetime(year, month, day, sh, sm)
        from datetime import timedelta
        end_dt = start_dt + timedelta(hours=1)
        return None, start_dt, end_dt

    # 終日イベント
    try:
        return date(year, month, day), None, None
    except ValueError:
        return None, None, None
