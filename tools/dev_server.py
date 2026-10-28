"""
اجرای سامانه برای توسعه/تست، بدون باز کردن مرورگر و روی پورت دلخواه.

    python tools/dev_server.py                 # 0.0.0.0:8080
    python tools/dev_server.py --demo          # با داده و کاربران نمونه
    STM_PORT=5000 python tools/dev_server.py

با متغیر STM_DATA_DIR می‌توان دیتابیس تست را جای دیگری گذاشت تا به
دیتابیس واقعی کاربر دست نزنیم.
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

# مسیر داده‌ها را قبل از ایمپورت ماژول‌ها ست می‌کنیم.
_data_dir = os.path.join(ROOT, ".devdata")
os.environ.setdefault("XDG_DATA_HOME", _data_dir)
os.environ["LOCALAPPDATA"] = os.environ.get("LOCALAPPDATA", _data_dir)

from db.database import get_connection, init_db, DEFAULT_DB_PATH  # noqa: E402
from engine.pricing_engine import recalculate_all  # noqa: E402
import web.auth as auth  # noqa: E402
import web.permissions as perms  # noqa: E402
import web.approval as approval  # noqa: E402
import web.periods as periods  # noqa: E402
import web.personnel as personnel  # noqa: E402
import web.personnel_templates as personnel_templates  # noqa: E402
import web.scope as scope  # noqa: E402
from web.app import app  # noqa: E402


def bootstrap():
    init_db(DEFAULT_DB_PATH)
    conn = get_connection(DEFAULT_DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.close()
    auth.init_users_table()
    perms.init_permissions()
    scope.ensure_schema()
    periods.init_periods_table()
    personnel.init_personnel_tables()
    personnel_templates.init_templates_table()
    approval.init_approval_log()
    try:
        recalculate_all(DEFAULT_DB_PATH, username="سیستم (dev)")
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] recalculate skipped: {exc}")


if __name__ == "__main__":
    bootstrap()
    if "--demo" in sys.argv:
        from tools.demo_seed import seed_demo, print_demo_box
        print_demo_box(seed_demo())
    port = int(os.environ.get("STM_PORT", "8080"))
    print(f"DB: {DEFAULT_DB_PATH}")
    print(f"http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
