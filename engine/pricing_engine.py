"""
موتور قیمت‌گذاری — سقف پرداختی و مقادیر وابسته.
- برای معاونت سیما (نه دوبلاژ): category از ترکیب زیر:
    ۱) ماده ۳۸ → پیمانکار/رسمی
    ۲) employment_status = بازنشسته → بازنشسته
    ۳) contract_subject → تامین / پخش / فنی
    (has_second_salary نادیده)
- برای بقیه معاونت‌ها: has_second_salary → contract_subject
- بدون fallback — اگه قانون نبود یا خالی بود، سقف «» می‌مونه
"""
import sqlite3
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

FIRST_3_MONTHS = ("فروردین", "اردیبهشت", "خرداد")

PERSIAN_MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
                  "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]


def month_name_of(period_month):
    if not period_month:
        return ""
    pm = str(period_month).strip()
    if "-" in pm:
        return pm.split("-", 1)[1].strip()
    return pm


def year_of(period_month):
    if not period_month:
        return None
    pm = str(period_month).strip()
    if "-" in pm:
        try:
            return int(pm.split("-", 1)[0])
        except ValueError:
            return None
    return None


def _month_multiplier(period_month):
    name = month_name_of(period_month)
    try:
        return PERSIAN_MONTHS.index(name)
    except (ValueError, AttributeError):
        return 5


def _resolve_pricing_deputy(record: dict) -> str:
    deputy = (record.get("deputy") or "").strip()
    center = (record.get("cost_center") or "").strip()

    if deputy == "معاونت سیما" and "ستاد معاونت سیما" in center:
        return "دوبلاژ"

    return deputy


def _determine_category(record: dict, pricing_deputy: str):
    article  = (record.get("legal_article") or "").strip()
    has_sec  = (record.get("has_second_salary") or "").strip()
    emp      = (record.get("employment_status") or "").strip()
    contract = (record.get("contract_subject") or "").strip()

    # ۱) ماده ۳۸
    if "38" in article or "۳۸" in article:
        return "پیمانکار/رسمی"

    # ۲) معاونت سیما (نه دوبلاژ) — has_second_salary بی‌اثر
    if pricing_deputy == "معاونت سیما":
        if emp == "بازنشسته":
            return "بازنشسته"
        if "تولید و فنی" in contract or "فنی" in contract:
            return "فنی"
        if "تامین" in contract:
            return "تامین"
        if "پخش" in contract:
            return "پخش"
        return None

    # ۳) بقیه معاونت‌ها
    if has_sec == "بلی":
        return "بازنشسته" if emp == "بازنشسته" else "رسمی"
    if has_sec == "خیر":
        return "خیر"

    if "تولید و فنی" in contract or "فنی" in contract:
        return "فنی"
    if "تامین" in contract:
        return "تامین"
    if "پخش" in contract:
        return "پخش"

    return None


def calculate_ceiling(conn: sqlite3.Connection, record: dict):
    emp = (record.get("employment_status") or "").strip()
    if emp == "شاغل":
        return "حذف شود", None

    article = (record.get("legal_article") or "").strip()
    if not article:
        return "", None

    pricing_deputy = _resolve_pricing_deputy(record)
    category = _determine_category(record, pricing_deputy)
    if not category:
        return "", None

    for with_job, with_cc in [(True, True), (False, True), (True, False), (False, False)]:
        q = """SELECT id, amount FROM pricing_rules
               WHERE deputy = ? AND legal_article = ? AND category = ?
                 AND valid_to IS NULL"""
        p = [pricing_deputy, article, category]

        if with_job:
            if record.get("job_title"):
                q += " AND job_title = ?"; p.append(record["job_title"])
            else:
                continue
        else:
            q += " AND job_title IS NULL"

        if with_cc:
            if record.get("cost_center"):
                q += " AND cost_center_filter = ?"; p.append(record["cost_center"])
            else:
                continue
        else:
            q += " AND cost_center_filter IS NULL"

        q += " ORDER BY priority DESC, id DESC LIMIT 1"
        row = conn.execute(q, p).fetchone()
        if row:
            if row["amount"] is None:
                return "", row["id"]
            return row["amount"], row["id"]

    return "", None


def get_manual_monthly_ceiling(conn, center_name, supply_type, period_month):
    if not center_name or not period_month:
        return None
    for st in (supply_type or '', '', 'ندارد'):
        row = conn.execute("""
            SELECT amount FROM manual_monthly_ceilings
            WHERE center_name = ? AND supply_type = ? AND period_month = ?
        """, (center_name, st or '', period_month)).fetchone()
        if row:
            return float(row["amount"] or 0)
    return None


def _get_payment_totals(conn, national_code, year=None):
    nc = str(national_code).strip().zfill(10)
    if year:
        prefix = f"{year}-%"
        yearly_total = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM monthly_payments "
            "WHERE national_code = ? AND period_month LIKE ?",
            (nc, prefix)
        ).fetchone()[0]
        yearly_excl_first3 = conn.execute(
            """SELECT COALESCE(SUM(amount),0) FROM monthly_payments
               WHERE national_code = ? AND period_month LIKE ?
                 AND NOT (
                     period_month LIKE '%-فروردین' OR
                     period_month LIKE '%-اردیبهشت' OR
                     period_month LIKE '%-خرداد'
                 )""",
            (nc, prefix)
        ).fetchone()[0]
    else:
        yearly_total = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM monthly_payments WHERE national_code = ?",
            (nc,)
        ).fetchone()[0]
        yearly_excl_first3 = conn.execute(
            """SELECT COALESCE(SUM(amount),0) FROM monthly_payments
               WHERE national_code = ?
                 AND NOT (
                     period_month LIKE '%-فروردین' OR
                     period_month LIKE '%-اردیبهشت' OR
                     period_month LIKE '%-خرداد'
                 )""",
            (nc,)
        ).fetchone()[0]
    return float(yearly_total or 0), float(yearly_excl_first3 or 0)


def calculate_extended_fields(conn, record, ceiling_status, monthly_wage, national_code):
    period_month = (record.get("period_month") or "").strip()
    multiplier = _month_multiplier(period_month)
    year = year_of(period_month)

    yearly_total, yearly_excl_first3 = _get_payment_totals(conn, national_code, year)

    try:
        ceiling_numeric = float(ceiling_status)
    except (TypeError, ValueError):
        ceiling_numeric = None

    monthly_wage = monthly_wage or 0

    exempted_ceiling = None
    if (ceiling_numeric is not None
            and monthly_wage > ceiling_numeric
            and yearly_excl_first3 > 0):
        exempted_ceiling = yearly_excl_first3 / 2

    dynamic_ceiling = None
    if ceiling_numeric is not None:
        dynamic_ceiling = (ceiling_numeric * multiplier + monthly_wage) - yearly_total

    if monthly_wage == 0:
        payment_list_status = ""
    elif ceiling_status == "حذف شود":
        payment_list_status = ""
    elif ceiling_numeric is None:
        payment_list_status = ""
    elif monthly_wage > ceiling_numeric:
        payment_list_status = "بزرگتر از سقف ماهانه"
    elif dynamic_ceiling is not None and dynamic_ceiling < 0:
        payment_list_status = "بزرگتر از مجموع پرداختی"
    else:
        payment_list_status = monthly_wage

    warn_yellow = (ceiling_numeric is not None and monthly_wage > ceiling_numeric)
    warn_orange = (dynamic_ceiling is not None and dynamic_ceiling < 0)

    return {
        "yearly_paid_total": yearly_total,
        "exempted_ceiling": exempted_ceiling,
        "six_month_ceiling": dynamic_ceiling,
        "payment_list_status": payment_list_status,
        "warn_yellow": warn_yellow,
        "warn_orange": warn_orange,
        "month_multiplier": multiplier,
    }


def get_setting(conn, key, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def recalculate_all(db_path: str, username: str = "سیستم") -> dict:
    from db.database import get_connection, log_action
    conn = get_connection(db_path)

    rows = conn.execute("""
        SELECT r.*, p.national_code AS national_code
        FROM records r JOIN persons p ON p.id = r.person_id
    """).fetchall()

    updated = 0
    for r in rows:
        rec = dict(r)
        status, rule_id = calculate_ceiling(conn, rec)
        ext = calculate_extended_fields(
            conn, rec, status, rec.get("monthly_wage"), rec["national_code"]
        )
        conn.execute("""
            INSERT INTO calculated_results
                (record_id, ceiling_status, applied_rule_id, yearly_paid_total,
                 exempted_ceiling, six_month_ceiling, payment_list_status)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(record_id) DO UPDATE SET
                ceiling_status=excluded.ceiling_status,
                applied_rule_id=excluded.applied_rule_id,
                yearly_paid_total=excluded.yearly_paid_total,
                exempted_ceiling=excluded.exempted_ceiling,
                six_month_ceiling=excluded.six_month_ceiling,
                payment_list_status=excluded.payment_list_status,
                calculated_at=CURRENT_TIMESTAMP
        """, (r["id"], str(status), rule_id, ext["yearly_paid_total"],
              ext["exempted_ceiling"], ext["six_month_ceiling"],
              str(ext["payment_list_status"])))
        updated += 1

    conn.commit()
    log_action(conn, username, "محاسبهٔ مجدد", f"{updated} رکورد")
    conn.close()
    return {"updated": updated}