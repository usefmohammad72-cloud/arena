# -*- coding: utf-8 -*-
"""دادهٔ نمونهٔ کوچک + کاربران آزمایشی (برای پیش‌نمایش و آزمون دسترسی)

این ماژول هیچ داده‌ای از نسخهٔ واقعی نمی‌خواند؛ همه‌چیز ساختگی است.
معاونت نمونه: «معاونت برونمرزی» — مرکز نمونه: «شبکه العالم»
"""
import io
import os
import sqlite3
import tempfile
from pathlib import Path

DEMO_PERIOD = "1404-مهر"
DEMO_PASSWORD = "Test!2345"
DEMO_DEPUTY = "معاونت برون‌مرزی"
DEMO_CENTER = "شبکه العالم"
OTHER_DEPUTY = "معاونت سیما"
OTHER_CENTER = "شبکه یک"

# (نام، نام خانوادگی، کد ملی، مرکز، موضوع قرارداد، دستمزد ماهانه)
DEMO_ROWS = [
    ("علی", "رضایی", "0012345678", DEMO_CENTER, "خبر", 35000000),
    ("سارا", "احمدی", "0022345679", DEMO_CENTER, "تولید", 28000000),
    ("مریم", "کاظمی", "0032345670", DEMO_CENTER, "پخش", 19000000),
    ("رضا", "کریمی", "0042345671", "شبکه الکوثر", "خبر", 24000000),
    ("نگار", "موسوی", "0052345672", "شبکه الکوثر", "تولید", 21000000),
    ("حسین", "شریفی", "0062345673", "شبکه الکوثر", "پخش", 16000000),
    ("فرهاد", "نادری", "0072345674", "شبکه سحاب", "خبر", 26000000),
    ("زهرا", "امینی", "0082345675", OTHER_CENTER, "خبر", 31000000),
    ("کامران", "توکلی", "0092345676", OTHER_CENTER, "تولید", 22000000),
]

ALL_DEMO_PERMS = {
    "tab_dashboard": True, "tab_report": True, "dash_charts": True,
    "dash_summary": True, "dash_approval": True, "box_approval": True,
    "can_approve": True, "view_payments": True, "search_person": True,
    "tab_personnel": True, "view_personnel": True, "export_excel": True,
    "can_upload": False, "can_edit_pricing": False, "can_edit_payments": False,
    "can_clear_month": False, "can_manage_users": False, "command_center": True,
}


def _build_xlsx(path: Path):
    """فایل اکسل ورودی نمونه با همان ستون‌های سامانه می‌سازد"""
    import openpyxl
    from openpyxl.utils import column_index_from_string as ci

    # شمارهٔ ستون‌ها (۱-پایه، مثل اکسل)
    cols = {"B": ci("B"), "C": ci("C"), "D": ci("D"), "L": ci("L"), "M": ci("M"),
            "AE": ci("AE"), "AG": ci("AG"), "AL": ci("AL"), "AN": ci("AN"),
            "BA": ci("BA"), "BB": ci("BB"), "BD": ci("BD")}
    maxc = max(cols.values())
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([None] * maxc)  # سرستون
    for first, last, nc, center, subject, wage in DEMO_ROWS:
        line = [None] * (maxc + 1)
        line[cols["B"]] = first
        line[cols["C"]] = last
        line[cols["D"]] = nc
        line[cols["L"]] = "خیر"
        line[cols["M"]] = "تبصره 2"
        line[cols["AE"]] = 800000
        line[cols["AG"]] = wage
        line[cols["AL"]] = 500000
        line[cols["AN"]] = 0
        line[cols["BA"]] = "تحریریه"
        line[cols["BB"]] = subject
        line[cols["BD"]] = center
        ws.append(line[1:])
    wb.save(path)


def seed_demo(db_path=None, force=False):
    """دادهٔ نمونه و کاربران آزمایشی را می‌سازد (تکرارش بی‌خطر است).

    force=True → دادهٔ نمونهٔ همان دوره پاک و از نو ساخته می‌شود.
    """
    import sys

    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from db.database import init_db, get_connection
    from db.seed_data import seed_all
    from engine.pricing_engine import recalculate_all
    import web.auth as auth
    import web.permissions as perms
    import web.scope as scope
    import web.periods as periods
    import web.personnel as personnel
    import web.personnel_templates as pt
    import web.approval as approval
    from importer.excel_importer import import_input_sheet

    # مسیر پایگاه‌داده از app_paths می‌آید (همان مسیری که برنامه استفاده می‌کند)
    from db.database import DEFAULT_DB_PATH
    db_path = db_path or DEFAULT_DB_PATH

    init_db(db_path)
    con = get_connection(db_path)
    seed_all(con)
    con.commit()
    con.close()
    auth.init_users_table()
    perms.init_permissions()
    scope.ensure_schema()
    periods.init_periods_table()
    personnel.init_personnel_tables()
    pt.init_templates_table()
    approval.init_approval_log()

    con = get_connection(db_path)
    if force:
        con.execute("DELETE FROM calculated_results WHERE record_id IN "
                    "(SELECT id FROM records WHERE period_month = ?)", (DEMO_PERIOD,))
        con.execute("DELETE FROM records WHERE period_month = ?", (DEMO_PERIOD,))
        con.execute("DELETE FROM monthly_payments WHERE period_month = ?", (DEMO_PERIOD,))
        con.commit()
    already = con.execute("SELECT COUNT(*) c FROM records WHERE period_month = ?",
                          (DEMO_PERIOD,)).fetchone()["c"]
    con.close()

    if not already:
        try:
            if not periods.is_period_open(DEMO_PERIOD):
                periods.open_period(DEMO_PERIOD, note="دادهٔ نمونه")
        except Exception:
            pass
        with tempfile.TemporaryDirectory() as td:
            xlsx = Path(td) / "demo.xlsx"
            _build_xlsx(xlsx)
            import_input_sheet(str(xlsx), DEMO_PERIOD, db_path, username="دادهٔ نمونه")
        try:
            recalculate_all(db_path, username="دادهٔ نمونه")
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] محاسبهٔ مجدد انجام نشد: {exc}")

    # ---------- نام دقیق معاونت/مرکز از خود پایگاه‌داده ----------
    dep_name, cen_name = DEMO_DEPUTY, DEMO_CENTER
    con = get_connection(db_path)
    try:
        row = con.execute(
            "SELECT center_name, deputy FROM centers_structure "
            "WHERE center_name LIKE ? AND COALESCE(deputy,'')<>'' LIMIT 1",
            ("%العالم%",)).fetchone()
        if row:
            cen_name, dep_name = row["center_name"], row["deputy"]
        else:
            row = con.execute(
                "SELECT center_name, deputy FROM centers_structure "
                "WHERE COALESCE(deputy,'')<>'' ORDER BY center_name LIMIT 1").fetchone()
            if row:
                cen_name, dep_name = row["center_name"], row["deputy"]
    finally:
        con.close()

    # ---------- کاربران آزمایشی ----------
    plans = [
        ("test_deputy", f"آزمون ۱ — فقط معاونت {dep_name}",
         [{"deputy": dep_name, "center": "*", "supply_type": "*"}]),
        ("test_center", f"آزمون ۲ — فقط مرکز {cen_name}",
         [{"deputy": dep_name, "center": cen_name, "supply_type": "*"}]),
        ("test_approver", f"آزمون ۳ — تأییدکنندهٔ {cen_name}",
         [{"deputy": dep_name, "center": cen_name, "supply_type": "*"}]),
        ("test_empty", "آزمون ۴ — بدون دامنه (باید هیچ‌چیز نبیند)", []),
    ]
    existing = {u["username"]: u["id"] for u in auth.list_users()}
    for username, full_name, grants in plans:
        try:
            uid = existing.get(username)
            if not uid:
                uid = auth.create_user(username, DEMO_PASSWORD, full_name=full_name,
                                       role="user", permissions=ALL_DEMO_PERMS)
            # تأییدکننده نباید بتواند پرداخت‌ها را دستی عوض کند
            scope.replace_grants(uid, grants, note="دادهٔ نمونه")
        except Exception as exc:  # noqa: BLE001
            print(f"  ! کاربر {username} ساخته نشد: {exc}")

    return {
        "period": DEMO_PERIOD,
        "deputy": dep_name,
        "center": cen_name,
        "users": [p[0] for p in plans],
        "password": DEMO_PASSWORD,
    }


def print_demo_box(info):
    line = "-" * 62
    print("=" * 62)
    print("  نسخهٔ نمایشی/آزمایشی — کنترل دسترسی")
    print("=" * 62)
    print(f"  معاونت نمونه: {info['deputy']}   |   مرکز نمونه: {info['center']}")
    print(f"  دورهٔ نمونه: {info['period']}")
    print(line)
    print("  کاربر مدیر:      4044588          /  4180261936")
    print(f"  test_deputy    (فقط یک معاونت)      /  {info['password']}")
    print(f"  test_center    (فقط {info['center']})  /  {info['password']}")
    print(f"  test_approver  (تأییدکنندهٔ همان مرکز) /  {info['password']}")
    print(f"  test_empty     (بدون دامنه)         /  {info['password']}")
    print(line)
    print("  هر کاربر فقط ردیف‌های دامنهٔ خودش را می‌بیند؛ test_empty هیچ‌چیز.")
    print("=" * 62, flush=True)


if __name__ == "__main__":
    import sys
    print_demo_box(seed_demo(force="--reset" in sys.argv))
