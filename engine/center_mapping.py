"""
ماژول تشخیص و اصلاح نام‌های اشتباه مرکز در ستون «نام برنامه».
گام ۱: نگاشت دقیق از جدول center_name_mappings.
گام ۲: اگر نگاشت دقیق نبود، با فاصلهٔ شباهت متنی (بدون نیاز به اینترنت یا کتابخانهٔ خارجی)
        نزدیک‌ترین نام مرکز واقعی را پیشنهاد می‌دهد؛ این پیشنهاد باید توسط کاربر تأیید شود.
"""
import difflib
import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db.database import get_connection


def _normalize(text: str) -> str:
    if not text:
        return ""
    text = text.strip()
    text = text.replace("ي", "ی").replace("ك", "ک")  # یکسان‌سازی ی/ک عربی و فارسی
    text = re.sub(r"\s+", " ", text)
    return text


def resolve_center_name(conn, raw_text: str, known_centers: list, threshold: float = 0.85):
    """
    raw_text: مقدار خام ستون «نام برنامه»
    known_centers: فهرست نام‌های واقعی و درست مراکز هزینه (از دیتابیس گرفته می‌شود)
    خروجی: (resolved_name یا None, matched_by) — matched_by یکی از "exact_mapping" / "fuzzy_suggestion" / None
    """
    if not raw_text:
        return None, None

    norm = _normalize(raw_text)

    # گام ۱: نگاشت دقیق ثبت‌شده
    row = conn.execute(
        "SELECT correct_center FROM center_name_mappings WHERE wrong_text = ?", (norm,)
    ).fetchone()
    if row:
        return row["correct_center"], "exact_mapping"

    # اگر خود متن دقیقاً نام یک مرکز واقعی است، نیازی به اصلاح نیست
    if norm in known_centers:
        return norm, None

    # گام ۲: نزدیک‌ترین شباهت متنی
    best, best_score = None, 0.0
    for center in known_centers:
        score = difflib.SequenceMatcher(None, norm, _normalize(center)).ratio()
        if score > best_score:
            best, best_score = center, score

    if best and best_score >= threshold:
        return best, "fuzzy_suggestion"

    return None, None


def suggest_corrections(db_path: str, period_month: str = None) -> list:
    """
    برای همهٔ رکوردهایی که ستون نام برنامه‌شان با هیچ نام مرکز واقعی یکی نیست،
    پیشنهاد اصلاح می‌سازد و به کاربر (نه خودکار) نشان می‌دهد.
    """
    conn = get_connection(db_path)
    known_centers = [r["cost_center"] for r in conn.execute(
        "SELECT DISTINCT cost_center FROM records WHERE cost_center IS NOT NULL"
    )]

    query = "SELECT id, program_name_raw FROM records WHERE program_name_raw IS NOT NULL"
    params = []
    if period_month:
        query += " AND period_month = ?"
        params.append(period_month)
    rows = conn.execute(query, params).fetchall()

    suggestions = []
    for row in rows:
        resolved, matched_by = resolve_center_name(conn, row["program_name_raw"], known_centers)
        if matched_by == "fuzzy_suggestion":
            suggestions.append({
                "record_id": row["id"],
                "raw_text": row["program_name_raw"],
                "suggested_center": resolved,
            })
    conn.close()
    return suggestions


def approve_mapping(db_path: str, wrong_text: str, correct_center: str, approved_by: str = "کاربر"):
    """کاربر یک پیشنهاد را تأیید می‌کند؛ این نگاشت از این پس خودکار اعمال می‌شود."""
    conn = get_connection(db_path)
    conn.execute(
        """INSERT INTO center_name_mappings (wrong_text, correct_center, approved_by)
           VALUES (?, ?, ?)
           ON CONFLICT(wrong_text) DO UPDATE SET
               correct_center = excluded.correct_center, approved_by = excluded.approved_by""",
        (_normalize(wrong_text), correct_center, approved_by),
    )
    conn.commit()
    conn.close()
