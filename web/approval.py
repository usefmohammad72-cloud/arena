# web/approval.py — ثبت و رهگیری تأییدها — STM PATCH
import sqlite3, sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from app_paths import get_db_path


def _conn():
    c = sqlite3.connect(str(get_db_path()))
    c.row_factory = sqlite3.Row
    return c


def init_approval_log():
    con = _conn()
    con.execute("""
        CREATE TABLE IF NOT EXISTS approval_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id    INTEGER NOT NULL,
            user_id      INTEGER,
            username     TEXT,
            action       TEXT NOT NULL CHECK(action IN ('approve','unapprove','undo')),
            deputy       TEXT,
            cost_center  TEXT,
            period_month TEXT,
            amount       REAL,
            note         TEXT,
            created_at   TEXT DEFAULT (datetime('now'))
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_appr_rec ON approval_log(record_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_appr_period ON approval_log(period_month)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_appr_user ON approval_log(user_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_appr_center ON approval_log(cost_center)")
    con.commit()
    con.close()


def log_approval(record_id, user_id, username, action,
                 deputy="", cost_center="", period_month="", amount=0, note=""):
    con = _conn()
    con.execute("""
        INSERT INTO approval_log
            (record_id, user_id, username, action,
             deputy, cost_center, period_month, amount, note)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (record_id, user_id, username, action,
          deputy, cost_center, period_month, amount, note))
    con.commit()
    con.close()


def get_status_by_deputy(period=None):
    con = _conn()
    q = """
        SELECT
            COALESCE(NULLIF(r.deputy,''), 'نامشخص') AS deputy,
            COUNT(*) AS total,
            SUM(CASE WHEN COALESCE(cr.manager_approved,0)=1 THEN 1 ELSE 0 END) AS approved,
            SUM(CASE WHEN COALESCE(cr.manager_approved,0)=0 THEN 1 ELSE 0 END) AS pending,
            SUM(CASE WHEN COALESCE(cr.manager_approved,0)=1 THEN COALESCE(r.monthly_wage,0) ELSE 0 END) AS approved_amount,
            SUM(CASE WHEN COALESCE(cr.manager_approved,0)=0 THEN COALESCE(r.monthly_wage,0) ELSE 0 END) AS pending_amount
        FROM records r
        LEFT JOIN calculated_results cr ON cr.record_id = r.id
        WHERE 1=1
    """
    p = []
    if period:
        q += " AND r.period_month = ?"
        p.append(period)
    q += " GROUP BY r.deputy ORDER BY total DESC"
    rows = con.execute(q, p).fetchall()
    con.close()
    return [dict(r) for r in rows]


def get_status_by_center(period=None, deputy=None):
    con = _conn()
    q = """
        SELECT
            COALESCE(NULLIF(r.deputy,''), 'نامشخص') AS deputy,
            COALESCE(NULLIF(r.cost_center,''), 'نامشخص') AS center,
            COUNT(*) AS total,
            SUM(CASE WHEN COALESCE(cr.manager_approved,0)=1 THEN 1 ELSE 0 END) AS approved,
            SUM(CASE WHEN COALESCE(cr.manager_approved,0)=0 THEN 1 ELSE 0 END) AS pending,
            SUM(CASE WHEN COALESCE(cr.manager_approved,0)=1 THEN COALESCE(r.monthly_wage,0) ELSE 0 END) AS approved_amount,
            SUM(CASE WHEN COALESCE(cr.manager_approved,0)=0 THEN COALESCE(r.monthly_wage,0) ELSE 0 END) AS pending_amount
        FROM records r
        LEFT JOIN calculated_results cr ON cr.record_id = r.id
        WHERE 1=1
    """
    p = []
    if period:
        q += " AND r.period_month = ?"
        p.append(period)
    if deputy:
        q += " AND r.deputy = ?"
        p.append(deputy)
    q += " GROUP BY r.deputy, r.cost_center ORDER BY r.deputy, r.cost_center"
    rows = con.execute(q, p).fetchall()
    con.close()
    return [dict(r) for r in rows]


def get_recent_approvals(limit=100):
    con = _conn()
    rows = con.execute("""
        SELECT al.id, al.record_id, al.username, al.action,
               al.deputy, al.cost_center, al.period_month, al.amount,
               al.note, al.created_at,
               p.first_name, p.last_name, p.national_code
        FROM approval_log al
        LEFT JOIN records r ON r.id = al.record_id
        LEFT JOIN persons p ON p.id = r.person_id
        ORDER BY al.id DESC LIMIT ?
    """, (limit,)).fetchall()
    con.close()
    return [dict(r) for r in rows]


def get_user_activity(user_id, limit=50):
    con = _conn()
    rows = con.execute("""
        SELECT * FROM approval_log WHERE user_id=?
        ORDER BY id DESC LIMIT ?
    """, (user_id, limit)).fetchall()
    con.close()
    return [dict(r) for r in rows]