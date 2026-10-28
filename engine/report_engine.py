"""
موتور گزارش خروجی — منطق per-person.
- ستون «سقف پرداختی» = سقف هر ردیف (بدون تغییر)
- ستون «پرداختی ماه» = مجموع دستمزد همه ردیف‌های شخص در همان ماه
- محاسبه خطاها:
    * max_ceiling = بیشترین سقف ماهانه بین ردیف‌های شخص
    * اگر مجموع پرداختی ماه > max_ceiling  → «بزرگ‌تر از سقف ماهانه»
    * سقف ماه شخص = (max_ceiling × عدد ماه) − (مجموع سال + پرداختی ماه)
    * اگر سقف ماه شخص < 0 → «بزرگ‌تر از مجموع پرداختی»
    * اگر وضعیت اشتغال = «شاغل» → «شاغل»
- تأیید مدیر همه هشدارها را خنثی می‌کند.
"""
import sqlite3
from collections import defaultdict

from engine.pricing_engine import get_manual_monthly_ceiling, year_of
import re


PERSIAN_MONTHS_NUM = {
    "فروردین": 1, "اردیبهشت": 2, "خرداد": 3, "تیر": 4,
    "مرداد": 5, "شهریور": 6, "مهر": 7, "آبان": 8,
    "آذر": 9, "دی": 10, "بهمن": 11, "اسفند": 12,
}



_MONTHS_FA_E = {
    "فروردین": "01", "اردیبهشت": "02", "خرداد": "03",
    "تیر": "04", "مرداد": "05", "شهریور": "06",
    "مهر": "07", "آبان": "08", "آذر": "09",
    "دی": "10", "بهمن": "11", "اسفند": "12",
}
_MONTHS_FA_E_REV = {v: k for k, v in _MONTHS_FA_E.items()}
_FA2EN_E = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

def _period_for_records(p):
    if not p:
        return p
    s = str(p).strip().translate(_FA2EN_E)
    for name, num in _MONTHS_FA_E.items():
        s = s.replace(name, num)
    s = s.replace("\\", "/").replace(".", "/").replace("-", "/")
    s = re.sub(r"\s+", "", s)
    m = re.match(r"^(\d{4})/(\d{1,2})(?:/.*)?$", s)
    if not m:
        return p
    year, month = m.group(1), int(m.group(2))
    name = _MONTHS_FA_E_REV.get(f"{month:02d}")
    if not name:
        return p
    return f"{year}-{name}"


def _month_number(pm):
    if not pm:
        return None
    if "-" in pm:
        pm = pm.split("-", 1)[1]
    return PERSIAN_MONTHS_NUM.get(pm.strip())


def _is_article_38(article):
    a = (article or "").strip()
    return ("38" in a) or ("۳۸" in a)


def _is_eligible_for_calc(d):
    # Manager approval always wins
    if d.get("manager_approved"):
        return True
    # Check payment_list_status for error labels (what user sees in "نوع خطا" column)
    status = d.get("payment_list_status")
    if isinstance(status, list):
        s = " ".join(str(x) for x in status if x)
    else:
        s = str(status or "")
    _err_labels = [
        "شاغل",
        "بزرگتر از سقف ماهانه",
        "بزرگتر از مجموع پرداختی",
        "بالاتر از سقف ماهانه",
        "بالاتر از مجموع پرداختی",
    ]
    for _lbl in _err_labels:
        if _lbl in s:
            return False
    # Fallback: check flags (in case payment_list_status is number/empty but flags say error)
    if d.get("is_employed"):
        return False
    if d.get("warn_yellow") or d.get("warn_orange"):
        return False
    return True


def _resolve_center_patterns(conn, deputy, center):
    if center in ("شبکه های نمایش", "شبکه نمایش", "شبکه تماشا"):
        return ["%شبکه%نمایش%", "%شبکه%تماشا%"]
    return [f"%{center}%"]


def get_filtered_records(conn, deputy, center, supply_type, period_month=None):
    query = """
        SELECT r.*, p.national_code, p.first_name, p.last_name,
               cr.ceiling_status, cr.yearly_paid_total, cr.exempted_ceiling,
               cr.six_month_ceiling,
               COALESCE(cr.manager_approved, 0) AS manager_approved
        FROM records r
        JOIN persons p ON p.id = r.person_id
        LEFT JOIN calculated_results cr ON cr.record_id = r.id
        WHERE 1=1
    """
    params = []

    if period_month and period_month != "همه":
        query += " AND r.period_month = ?"; params.append(period_month)

    if deputy and deputy != "همه":
        dep_list = [d.strip() for d in str(deputy).split(',') if d.strip() and d.strip() != "همه"]
        if dep_list:
            ph = ','.join(['?'] * len(dep_list))
            query += f" AND r.deputy IN ({ph})"
            params.extend(dep_list)

    if center and center != "همه":
        centers_list = [c.strip() for c in str(center).split(',') if c.strip() and c.strip() != "همه"]
        if centers_list:
            patterns = []
            for c_item in centers_list:
                if c_item in ("شبکه های نمایش", "شبکه نمایش", "شبکه تماشا"):
                    patterns.append("%شبکه%نمایش%")
                    patterns.append("%شبکه%تماشا%")
                else:
                    patterns.append(f"%{c_item}%")
            query += " AND (" + " OR ".join(["r.cost_center LIKE ?"] * len(patterns)) + ")"
            params.extend(patterns)

    dep_list_for_supply = [d.strip() for d in str(deputy).split(',') if d.strip()]
    has_sima = "معاونت سیما" in dep_list_for_supply
    center_list_for_supply = [c.strip() for c in str(center).split(',') if c.strip()]
    non_staff_centers = [c for c in center_list_for_supply if c not in ("ستاد معاونت سیما", "مرکز تولید و فنی", "همه", "", None)]

    supplies_list = [s.strip() for s in str(supply_type).split(',') if s.strip() and s.strip() != "همه"]
    apply_supply = has_sima and non_staff_centers and supplies_list
    if apply_supply:
        supply_clauses = []
        for s_item in supplies_list:
            if "شبکه خبر" in non_staff_centers and s_item == "تولید":
                supply_clauses.append("r.contract_subject LIKE '%تولید%'")
            else:
                supply_clauses.append("r.contract_subject LIKE ?")
                params.append(f"%{s_item}%")
        query += " AND (" + " OR ".join(supply_clauses) + ")"

    query += " ORDER BY p.national_code"
    return conn.execute(query, params).fetchall()


def get_month_ceiling(conn, deputy, center, supply_type, period_month=None):
    if not center or center == "همه":
        return None

    if period_month:
        manual = get_manual_monthly_ceiling(
            conn, center, supply_type or "", period_month
        )
        if manual is not None:
            return manual

    if deputy != "معاونت سیما":
        row = conn.execute(
            "SELECT monthly_quota FROM centers_structure WHERE center_name = ? LIMIT 1",
            (center,)).fetchone()
        return row["monthly_quota"] if row else None
    if supply_type == "همه" or not supply_type:
        row = conn.execute(
            "SELECT SUM(monthly_quota) s FROM centers_structure WHERE center_name = ?",
            (center,)).fetchone()
    else:
        row = conn.execute(
            "SELECT SUM(monthly_quota) s FROM centers_structure "
            "WHERE center_name = ? AND supply_type = ?",
            (center, supply_type)).fetchone()
    return row["s"] if row else None


def _compute_service_places(conn):
    rows = conn.execute("""
        SELECT p.national_code AS nc, r.period_month AS pm, r.cost_center AS cc
        FROM records r JOIN persons p ON p.id = r.person_id
        WHERE r.cost_center IS NOT NULL AND r.cost_center != ''
    """).fetchall()
    m = defaultdict(set)
    for r in rows:
        m[(r["nc"], r["pm"])].add(r["cc"])
    return m


def _compute_monthly_wage_sums(conn):
    rows = conn.execute("""
        SELECT p.national_code AS nc, r.period_month AS pm,
               COALESCE(SUM(r.monthly_wage), 0) AS s
        FROM records r JOIN persons p ON p.id = r.person_id
        GROUP BY nc, pm
    """).fetchall()
    m = {}
    for r in rows:
        m[(r["nc"], r["pm"])] = float(r["s"] or 0)
    return m


def _compute_monthly_ceiling_max(conn):
    rows = conn.execute("""
        SELECT p.national_code AS nc, r.period_month AS pm,
               MAX(CAST(cr.ceiling_status AS REAL)) AS s
        FROM records r
        JOIN persons p ON p.id = r.person_id
        JOIN calculated_results cr ON cr.record_id = r.id
        WHERE cr.ceiling_status IS NOT NULL
          AND cr.ceiling_status != ''
          AND cr.ceiling_status != 'حذف شود'
        GROUP BY nc, pm
    """).fetchall()
    m = {}
    for r in rows:
        try:
            m[(r["nc"], r["pm"])] = float(r["s"])
        except (TypeError, ValueError):
            pass
    return m


def _compute_yearly_paid_sums(conn):
    from db.database import current_jalali_year, PERSIAN_MONTHS
    cur_year = current_jalali_year()

    rows = conn.execute("""
        SELECT national_code AS nc, period_month AS pm,
               COALESCE(SUM(amount), 0) AS a
        FROM monthly_payments
        GROUP BY national_code, period_month
    """).fetchall()

    m = defaultdict(float)
    for r in rows:
        pm = r["pm"]
        if not pm:
            continue
        y = year_of(pm)
        if y is None and pm in PERSIAN_MONTHS:
            y = cur_year
        if y:
            m[(r["nc"], y)] += float(r["a"] or 0)
    return m


def _get_specialists_totals(conn, deputy, center, supply_type, period_month=None):
    where = []
    params = []

    if period_month and period_month != "همه":
        where.append("s.period_month = ?"); params.append(period_month)

    centers_list = [c.strip() for c in str(center).split(',') if c.strip() and c.strip() != "همه"] if center and center != "همه" else []
    dep_list = [d.strip() for d in str(deputy).split(',') if d.strip() and d.strip() != "همه"] if deputy and deputy != "همه" else []

    if centers_list:
        ph = ','.join(['?'] * len(centers_list))
        where.append(f"s.center_name IN ({ph})")
        params.extend(centers_list)
        if supply_type and supply_type != "همه":
            supplies_list = [s.strip() for s in str(supply_type).split(',') if s.strip() and s.strip() != "همه"]
            if supplies_list:
                ph2 = ','.join(['?'] * len(supplies_list))
                where.append(f"s.supply_type IN ({ph2})")
                params.extend(supplies_list)
    elif dep_list:
        ph = ','.join(['?'] * len(dep_list))
        where.append(f"c.deputy IN ({ph})")
        params.extend(dep_list)

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    row = conn.execute(f"""
        SELECT COALESCE(SUM(s.specialists),0) sp,
               COALESCE(SUM(s.equipment),0) eq,
               COALESCE(SUM(s.bonus),0) bo
        FROM specialists_equipment_bonus s
        LEFT JOIN centers_structure c
            ON c.center_name = s.center_name
            AND COALESCE(c.supply_type,'') = s.supply_type
        {where_sql}
    """, params).fetchone()
    if row:
        return (row["sp"] or 0), (row["eq"] or 0), (row["bo"] or 0)
    return 0, 0, 0


def build_report(db_path, deputy, center, supply_type, period_month=None):
    period_month = _period_for_records(period_month)
    from db.database import get_connection
    conn = get_connection(db_path)
    rows = get_filtered_records(conn, deputy, center, supply_type, period_month)
    places_map = _compute_service_places(conn)
    wage_sums = _compute_monthly_wage_sums(conn)
    ceiling_max_map = _compute_monthly_ceiling_max(conn)
    yearly_paid_sums = _compute_yearly_paid_sums(conn)

    # پیش‌محاسبه‌ی flags per-person
    person_cache = {}
    for r in rows:
        nc = r["national_code"]
        pm = r["period_month"]
        key = (nc, pm)
        if key in person_cache:
            continue

        total_wage_month = wage_sums.get(key, 0)
        max_ceiling = ceiling_max_map.get(key)

        y = year_of(pm)
        yearly_paid_total = yearly_paid_sums.get((nc, y), 0) if y else 0

        m_num = _month_number(pm)
        if m_num is not None and max_ceiling is not None:
            dynamic_ceiling = (max_ceiling * m_num) - (yearly_paid_total + total_wage_month)
        else:
            dynamic_ceiling = None

        person_cache[key] = {
            "total_wage_month": total_wage_month,
            "max_ceiling": max_ceiling,
            "yearly_paid_total": yearly_paid_total,
            "dynamic_ceiling": dynamic_ceiling,
        }

    person_employed = {}
    for r in rows:
        key = (r["national_code"], r["period_month"])
        if (r["employment_status"] or "").strip() == "شاغل":
            person_employed[key] = True
        elif key not in person_employed:
            person_employed[key] = False

    detail = []
    for i, r in enumerate(rows, start=1):
        nc = r["national_code"]
        pm = r["period_month"]
        key = (nc, pm)

        cache = person_cache.get(key, {})
        total_wage_month = cache.get("total_wage_month", 0)
        max_ceiling = cache.get("max_ceiling")
        yearly_paid_total = cache.get("yearly_paid_total", 0)
        dynamic_ceiling = cache.get("dynamic_ceiling")

        places = sorted(places_map.get(key, set()))
        service_places = " - ".join(places) if len(places) >= 2 else ""

        emp = (r["employment_status"] or "").strip()
        approved = bool(r["manager_approved"])
        wage = r["monthly_wage"] or 0

        # سه شرط per-person
        is_employed = person_employed.get(key, False)
        warn_yellow = (max_ceiling is not None and total_wage_month > max_ceiling)
        warn_orange = (dynamic_ceiling is not None and dynamic_ceiling < 0)

        warnings = []
        if is_employed:
            warnings.append("شاغل")
        if warn_yellow:
            warnings.append("بزرگ‌تر از سقف ماهانه")
        if warn_orange:
            warnings.append("بزرگ‌تر از مجموع پرداختی")

        if approved:
            is_employed = False
            warn_yellow = False
            warn_orange = False
            warnings = []

        detail.append({
            "row_num": i,
            "record_id": r["id"],
            "first_name": r["first_name"],
            "last_name": r["last_name"],
            "national_code": nc,
            "period_month": pm,
            "has_second_salary": r["has_second_salary"],
            "legal_article": r["legal_article"],
            "skill_card_bonus": r["skill_card_bonus"],
            "employer_insurance": r["employer_insurance"],
            "non_continuous_bonus": r["non_continuous_bonus"],
            "monthly_wage": wage,
            "cost_center": r["cost_center"],
            "main_cost_center": r["main_cost_center"],
            "service_places": service_places,
            "employment_status": r["employment_status"],
            "ceiling_status": r["ceiling_status"],
            "program_name": r["program_name_raw"],
            "payment_list_status": warnings,
            "yearly_paid_total": yearly_paid_total,
            "exempted_ceiling": r["exempted_ceiling"],
            "six_month_ceiling": dynamic_ceiling,
            "paid_amount": total_wage_month,
            "paid_source": "sum",
            "manager_approved": approved,
            "is_employed": is_employed,
            "warn_yellow": warn_yellow,
            "warn_orange": warn_orange,
        })

    eligible = [d for d in detail if _is_eligible_for_calc(d)]
    excluded_count = len(detail) - len(eligible)

    skill_card_all = sum((d["skill_card_bonus"] or 0) for d in eligible)
    skill_card_excl_38 = sum(
        (d["skill_card_bonus"] or 0) for d in eligible
        if not _is_article_38(d["legal_article"])
    )
    employer_insurance_sum = sum((d["employer_insurance"] or 0) for d in eligible)
    monthly_wage_sum = sum((d["monthly_wage"] or 0) for d in eligible)
    non_continuous_sum = sum((d["non_continuous_bonus"] or 0) for d in eligible)

    specialists, equipment, bonus = _get_specialists_totals(
        conn, deputy, center, supply_type, period_month
    )

    professional_qualification = (
        skill_card_all + (skill_card_excl_38 * 0.23)
    ) * 1.04

    # eligible = rows without warnings + rows approved by manager (see _is_eligible_for_calc)
    allocation_base = (
        monthly_wage_sum
        + non_continuous_sum
        + equipment
        + specialists
        + bonus
        + (employer_insurance_sum - (skill_card_excl_38 * 0.23))
    )
    monthly_allocation = allocation_base * 1.04

    persons_yellow = set()
    persons_orange = set()
    persons_employed = set()
    for d in detail:
        key = (d["national_code"], d["period_month"])
        if d["warn_yellow"]:
            persons_yellow.add(key)
        if d["warn_orange"]:
            persons_orange.add(key)
        if d["is_employed"]:
            persons_employed.add(key)

    summary = {
        "month_ceiling": get_month_ceiling(conn, deputy, center, supply_type, period_month),
        "skill_card_insurance_share": skill_card_excl_38 * 0.23,
        "employer_insurance_diff": employer_insurance_sum,
        "skill_card_bonus_total": skill_card_all,
        "skill_card_bonus_excl_38": skill_card_excl_38,
        "specialists": specialists,
        "equipment": equipment,
        "bonus": bonus,
        "monthly_wage_sum": monthly_wage_sum,
        "non_continuous_sum": non_continuous_sum,
        "allocation_base": allocation_base,
        "professional_qualification": professional_qualification,
        "monthly_allocation": monthly_allocation,
        "monthly_wage_sum_eligible": monthly_wage_sum,
        "eligible_wage_total": sum((d["monthly_wage"] or 0) for d in eligible),
        "excluded_details": [
            {"nc": d.get("national_code"), "status": str(d.get("payment_list_status") or "")[:60],
             "wage": (d.get("monthly_wage") or 0)}
            for d in detail if not _is_eligible_for_calc(d)
        ][:20],
        "row_count": len(rows),
        "eligible_count": len(eligible),
        "excluded_count": excluded_count,
        "warn_yellow_count": len(persons_yellow),
        "warn_orange_count": len(persons_orange),
        "negative_ceiling_count": len(persons_orange),
        "employed_count": len(persons_employed),
        "approved_count": sum(1 for d in detail if d["manager_approved"]),
    }
    conn.close()
    return {"summary": summary, "rows": detail}