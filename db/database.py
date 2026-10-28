"""
لایهٔ اتصال به پایگاه داده + مهاجرت‌های ساده
"""
import sqlite3
import os
import sys
from datetime import date

# ==== STM PATCH: مسیرها از app_paths ====
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app_paths import get_db_path, get_resource_dir


def _resolve_schema_path():
    """مسیر schema.sql — هم dev هم frozen"""
    if getattr(sys, 'frozen', False):
        # تلاش ۱: کنار exe
        p1 = os.path.join(os.path.dirname(sys.executable), "db", "schema.sql")
        if os.path.exists(p1):
            return p1
        # تلاش ۲: مسیر _MEIPASS
        base = getattr(sys, '_MEIPASS', None)
        if base:
            p2 = os.path.join(base, "db", "schema.sql")
            if os.path.exists(p2):
                return p2
        # تلاش ۳: از app_paths
        p3 = os.path.join(get_resource_dir(), "db", "schema.sql")
        if os.path.exists(p3):
            return p3
        # تلاش ۴: کنار خود فایل
        return os.path.join(os.path.dirname(__file__), "schema.sql")
    return os.path.join(os.path.dirname(__file__), "schema.sql")


SCHEMA_PATH = _resolve_schema_path()
DEFAULT_DB_PATH = str(get_db_path())

PERSIAN_MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
                  "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]


def get_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    # ==== STM: WAL mode + timeout برای جلوگیری از lock ====
    conn = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 30000;")
    return conn


def _ensure_column(conn, table, column, definition):
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _migrate_monthly_payments_check(conn):
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='monthly_payments'"
    ).fetchone()
    if not row or not row[0]:
        return
    sql = row[0]
    if "'approved'" in sql or '"approved"' in sql:
        return

    conn.execute("PRAGMA foreign_keys = OFF;")
    conn.executescript("""
        BEGIN;
        CREATE TABLE monthly_payments_new (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            national_code  TEXT NOT NULL,
            period_month   TEXT NOT NULL,
            amount         REAL NOT NULL DEFAULT 0,
            source         TEXT NOT NULL DEFAULT 'manual'
                            CHECK(source IN ('manual','auto','approved')),
            record_id      INTEGER REFERENCES records(id),
            note           TEXT,
            created_at     TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(national_code, period_month)
        );
        INSERT INTO monthly_payments_new
            (id, national_code, period_month, amount, source, record_id, note, created_at)
        SELECT id, national_code, period_month, amount, source, record_id, note, created_at
        FROM monthly_payments;
        DROP TABLE monthly_payments;
        ALTER TABLE monthly_payments_new RENAME TO monthly_payments;
        CREATE INDEX IF NOT EXISTS idx_payments_nc ON monthly_payments(national_code);
        CREATE INDEX IF NOT EXISTS idx_payments_period ON monthly_payments(period_month);
        COMMIT;
    """)
    conn.execute("PRAGMA foreign_keys = ON;")


def current_jalali_year() -> int:
    today = date.today()
    return today.year - 621


def _migrate_add_year_to_period_month(conn):
    """period_month های قدیمی رو به فرمت «سال-ماه» تبدیل می‌کنه."""
    year = current_jalali_year()
    tables = ["records", "employment_monthly", "monthly_payments"]

    for table in tables:
        try:
            rows = conn.execute(f"SELECT DISTINCT period_month FROM {table}").fetchall()
        except sqlite3.OperationalError:
            continue

        for r in rows:
            pm = r[0]
            if not pm or "-" in pm:
                continue
            if pm not in PERSIAN_MONTHS:
                continue

            new_pm = f"{year}-{pm}"
            try:
                conn.execute(
                    f"UPDATE {table} SET period_month = ? WHERE period_month = ?",
                    (new_pm, pm)
                )
            except sqlite3.IntegrityError:
                conn.execute(f"DELETE FROM {table} WHERE period_month = ?", (pm,))

    conn.commit()



def _migrate_add_period_to_specialists(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(specialists_equipment_bonus)").fetchall()]
    if 'period_month' in cols:
        return
    periods = [r[0] for r in conn.execute(
        "SELECT DISTINCT period_month FROM records WHERE period_month IS NOT NULL AND period_month != ''"
    ).fetchall()]
    if periods:
        def _sk(pm):
            try:
                y, m = pm.split("-", 1)
                return (int(y), PERSIAN_MONTHS.index(m) if m in PERSIAN_MONTHS else 99)
            except Exception:
                return (0, 99)
        default = sorted(periods, key=_sk)[-1]
    else:
        from datetime import date as _d
        _t = _d.today()
        default = f"{_t.year - 621}-{PERSIAN_MONTHS[_t.month - 1]}"
    conn.execute("PRAGMA foreign_keys = OFF;")
    conn.executescript(f"""
        BEGIN;
        CREATE TABLE specialists_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            center_name TEXT NOT NULL,
            supply_type TEXT NOT NULL DEFAULT '',
            period_month TEXT NOT NULL DEFAULT '{default}',
            specialists REAL DEFAULT 0,
            equipment REAL DEFAULT 0,
            bonus REAL DEFAULT 0,
            UNIQUE(center_name, supply_type, period_month)
        );
        INSERT INTO specialists_new (id, center_name, supply_type, period_month, specialists, equipment, bonus)
            SELECT id, center_name, supply_type, '{default}', specialists, equipment, bonus
            FROM specialists_equipment_bonus;
        DROP TABLE specialists_equipment_bonus;
        ALTER TABLE specialists_new RENAME TO specialists_equipment_bonus;
        COMMIT;
    """)
    conn.execute("PRAGMA foreign_keys = ON;")

def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    if not os.path.exists(SCHEMA_PATH):
        raise FileNotFoundError(
            f"فایل schema.sql پیدا نشد در: {SCHEMA_PATH}\n"
            f"مسیرهای جستجو شده:\n"
            f"  - sys.executable: {os.path.dirname(sys.executable) if getattr(sys,'frozen',False) else '(dev)'}\n"
            f"  - sys._MEIPASS: {getattr(sys,'_MEIPASS','(none)')}\n"
            f"  - resource_dir: {get_resource_dir()}\n"
            f"  - module dir: {os.path.dirname(__file__)}\n"
        )
    conn = get_connection(db_path)
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    _ensure_column(conn, "calculated_results", "manager_approved", "INTEGER DEFAULT 0")
    conn.commit()
    _migrate_monthly_payments_check(conn)
    _migrate_add_year_to_period_month(conn)
    _migrate_add_period_to_specialists(conn)
    from db.seed_data import seed_all
    seed_all(conn)
    conn.close()


def log_action(conn: sqlite3.Connection, username: str, action: str, details: str = ""):
    conn.execute(
        "INSERT INTO audit_log (username, action, details) VALUES (?, ?, ?)",
        (username, action, details),
    )
    conn.commit()


if __name__ == "__main__":
    init_db()
    print("پایگاه داده:", DEFAULT_DB_PATH)
    print("Schema:", SCHEMA_PATH)