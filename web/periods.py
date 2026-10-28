# -*- coding: utf-8 -*-
"""مدیریت دوره‌های باز/بسته — فقط مدیر می‌تواند باز کند."""
import sqlite3, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app_paths import get_db_path

PERSIAN_MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
                  "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]


def _conn():
    c = sqlite3.connect(str(get_db_path()))
    c.row_factory = sqlite3.Row
    return c


def init_periods_table():
    con = _conn()
    con.execute("""
        CREATE TABLE IF NOT EXISTS opened_periods (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            period_month TEXT UNIQUE NOT NULL,
            opened_by    INTEGER,
            opened_at    TEXT DEFAULT (datetime('now')),
            note         TEXT DEFAULT ''
        )
    """)
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_opened_period ON opened_periods(period_month)"
    )
    con.commit()
    con.close()


def is_period_open(period_month):
    """آیا این ماه توسط مدیر باز شده؟"""
    if not period_month:
        return False
    con = _conn()
    row = con.execute(
        "SELECT id FROM opened_periods WHERE period_month = ? LIMIT 1",
        (period_month,)
    ).fetchone()
    con.close()
    return row is not None


def list_opened():
    """لیست همه ماه‌های باز."""
    con = _conn()
    rows = con.execute("""
        SELECT period_month, opened_at, note
        FROM opened_periods
        ORDER BY period_month DESC
    """).fetchall()
    con.close()
    return [dict(r) for r in rows]


def open_period(period_month, user_id=None, note=""):
    """باز کردن یک ماه — اگه از قبل بازه، فقط به‌روزرسانی کن."""
    if not period_month:
        raise ValueError("دوره معتبر نیست")
    # اعتبارسنجی فرمت
    if "-" not in period_month:
        raise ValueError("فرمت دوره باید «سال-ماه» باشد (مثلاً 1405-شهریور)")
    y, m = period_month.split("-", 1)
    if not y.isdigit() or m not in PERSIAN_MONTHS:
        raise ValueError("فرمت دوره نامعتبر است")
    con = _conn()
    con.execute("""
        INSERT INTO opened_periods (period_month, opened_by, note)
        VALUES (?, ?, ?)
        ON CONFLICT(period_month) DO UPDATE SET
            opened_at = datetime('now'),
            opened_by = excluded.opened_by,
            note = excluded.note
    """, (period_month, user_id, note))
    con.commit()
    con.close()
    return True


def close_period(period_month):
    """بستن یک ماه."""
    if not period_month:
        raise ValueError("دوره معتبر نیست")
    con = _conn()
    con.execute("DELETE FROM opened_periods WHERE period_month = ?", (period_month,))
    con.commit()
    con.close()
    return True


def toggle_period(period_month, user_id=None, note=""):
    """اگه بازه → ببند. اگه بسته‌ست → باز کن."""
    if is_period_open(period_month):
        close_period(period_month)
        return "closed"
    else:
        open_period(period_month, user_id, note)
        return "opened"


def get_available_periods_for_user():
    """لیست ماه‌های باز (برای پر کردن سلکت‌ها)."""
    return list_opened()