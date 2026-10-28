# web/analytics.py — موتور تحلیل جامع — STM
import sqlite3, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app_paths import get_db_path

PERSIAN_MONTHS = ["فروردین","اردیبهشت","خرداد","تیر","مرداد","شهریور",
                  "مهر","آبان","آذر","دی","بهمن","اسفند"]


def _conn():
    c = sqlite3.connect(str(get_db_path()))
    c.row_factory = sqlite3.Row
    return c


def _sort_period(pm):
    try:
        y, m = pm.split('-', 1)
        return (int(y), PERSIAN_MONTHS.index(m) if m in PERSIAN_MONTHS else 99)
    except Exception:
        return (0, 99)


def get_analytics(scope=None):
    """تحلیل‌ها — همیشه محدود به دامنهٔ دسترسی کاربر (بسته به‌طور پیش‌فرض)."""
    con = _conn()
    from web.scope import scope_sql
    sc, sp = scope_sql("r.deputy", "r.cost_center", "r.contract_subject")

    def rows(sql, p=None):
        try:
            return [dict(x) for x in con.execute(sql, p or sp).fetchall()]
        except Exception as e:
            print("analytics err:", e)
            return []

    def one(sql, p=None):
        try:
            r = con.execute(sql, p or sp).fetchone()
            return (r[0] if r else 0) or 0
        except Exception:
            return 0

    monthly = rows(f"""
        SELECT r.period_month,
               COUNT(*) AS total,
               SUM(CASE WHEN COALESCE(cr.manager_approved,0)=1 THEN 1 ELSE 0 END) AS approved,
               SUM(COALESCE(r.monthly_wage,0)) AS wage_sum,
               COALESCE(AVG(COALESCE(r.monthly_wage,0)),0) AS wage_avg
        FROM records r
        LEFT JOIN calculated_results cr ON cr.record_id = r.id
        WHERE r.period_month IS NOT NULL AND r.period_month != '' {sc}
        GROUP BY r.period_month
    """)
    monthly.sort(key=lambda r: _sort_period(r['period_month']))
    monthly = monthly[-6:]

    top_wages = rows(f"""
        SELECT r.id, r.monthly_wage, r.cost_center, r.deputy, r.period_month,
               r.legal_article, r.employment_status,
               p.first_name, p.last_name, p.national_code,
               COALESCE(cr.manager_approved,0) AS approved
        FROM records r
        JOIN persons p ON p.id = r.person_id
        LEFT JOIN calculated_results cr ON cr.record_id = r.id
        WHERE r.monthly_wage IS NOT NULL AND r.monthly_wage > 0 {sc}
        ORDER BY r.monthly_wage DESC LIMIT 15
    """)

    legal = rows(f"""
        SELECT COALESCE(NULLIF(r.legal_article,''),'نامشخص') AS label,
               COUNT(*) AS count
        FROM records r WHERE 1=1 {sc}
        GROUP BY r.legal_article ORDER BY count DESC LIMIT 8
    """)

    employment = rows(f"""
        SELECT COALESCE(NULLIF(r.employment_status,''),'نامشخص') AS label,
               COUNT(*) AS count
        FROM records r WHERE 1=1 {sc}
        GROUP BY r.employment_status ORDER BY count DESC LIMIT 8
    """)

    wage_hist = []
    for lbl, lo, hi in [
        ("۰-۵۰ م.ر", 0, 50_000_000),
        ("۵۰-۱۰۰", 50_000_000, 100_000_000),
        ("۱۰۰-۱۵۰", 100_000_000, 150_000_000),
        ("۱۵۰-۲۰۰", 150_000_000, 200_000_000),
        ("۲۰۰-۳۰۰", 200_000_000, 300_000_000),
        ("۳۰۰-۵۰۰", 300_000_000, 500_000_000),
        ("+۵۰۰", 500_000_000, 10**15),
    ]:
        try:
            c = con.execute(
                f"SELECT COUNT(*) FROM records r WHERE r.monthly_wage >= ? AND r.monthly_wage < ? {sc}",
                [lo, hi] + sp).fetchone()[0]
        except Exception:
            c = 0
        wage_hist.append({'label': lbl, 'count': c})

    per_dep = rows(f"""
        SELECT COALESCE(NULLIF(r.deputy,''),'نامشخص') AS deputy,
               COUNT(*) AS total,
               SUM(CASE WHEN COALESCE(cr.manager_approved,0)=1 THEN 1 ELSE 0 END) AS approved,
               SUM(COALESCE(r.monthly_wage,0)) AS wage_sum,
               COALESCE(AVG(COALESCE(r.monthly_wage,0)),0) AS wage_avg,
               COALESCE(MAX(COALESCE(r.monthly_wage,0)),0) AS wage_max
        FROM records r
        LEFT JOIN calculated_results cr ON cr.record_id = r.id
        WHERE 1=1 {sc}
        GROUP BY r.deputy ORDER BY wage_sum DESC
    """)

    cum = rows(f"""
        SELECT r.period_month,
               COUNT(*) AS cnt,
               SUM(COALESCE(r.monthly_wage,0)) AS amount
        FROM records r WHERE 1=1 {sc}
        GROUP BY r.period_month
    """)
    cum.sort(key=lambda r: _sort_period(r['period_month']))
    cumulative = []
    run = 0
    for r in cum:
        run += r['amount'] or 0
        cumulative.append({
            'period': r['period_month'],
            'count': r['cnt'],
            'amount': r['amount'] or 0,
            'cumulative': run,
        })

    risk = {
        'wage_over_ceiling': one(f"""
            SELECT COUNT(*) FROM records r
            LEFT JOIN calculated_results cr ON cr.record_id = r.id
            WHERE r.monthly_wage > CAST(cr.ceiling_status AS REAL)
              AND cr.ceiling_status NOT IN ('', 'حذف شود') {sc}
        """),
        'negative_ceiling': one(f"""
            SELECT COUNT(*) FROM records r
            LEFT JOIN calculated_results cr ON cr.record_id = r.id
            WHERE cr.six_month_ceiling < 0 {sc}
        """),
        'employed': one(f"""
            SELECT COUNT(*) FROM records r
            LEFT JOIN calculated_results cr ON cr.record_id = r.id
            WHERE cr.ceiling_status = 'حذف شود' {sc}
        """),
        'unresolved': one(f"""
            SELECT COUNT(*) FROM records r
            LEFT JOIN calculated_results cr ON cr.record_id = r.id
            WHERE (cr.ceiling_status IS NULL OR cr.ceiling_status = '') {sc}
        """),
        'approved': one(f"""
            SELECT COUNT(*) FROM records r
            LEFT JOIN calculated_results cr ON cr.record_id = r.id
            WHERE COALESCE(cr.manager_approved,0)=1 {sc}
        """),
    }

    centers = rows(f"""
        SELECT COALESCE(NULLIF(r.cost_center,''),'نامشخص') AS center,
               COALESCE(NULLIF(r.deputy,''),'') AS deputy,
               COUNT(*) AS total,
               SUM(COALESCE(r.monthly_wage,0)) AS wage_sum
        FROM records r WHERE 1=1 {sc}
        GROUP BY r.cost_center ORDER BY total DESC LIMIT 12
    """)

    hourly = [[0]*24 for _ in range(7)]
    try:
        for r in con.execute("""
            SELECT CAST(strftime('%w', created_at) AS INTEGER) AS w,
                   CAST(strftime('%H', created_at) AS INTEGER) AS h,
                   COUNT(*) AS c
            FROM approval_log
            WHERE created_at >= datetime('now','-30 days')
            GROUP BY w, h
        """).fetchall():
            w, h, c = r['w'], r['h'], r['c']
            if 0 <= w < 7 and 0 <= h < 24:
                hourly[w][h] = c
    except Exception:
        pass

    kpi = {
        'total_persons': one("SELECT COUNT(*) FROM persons", []),
        'total_records': one(f"SELECT COUNT(*) FROM records r WHERE 1=1 {sc}"),
        'total_amount': float(one(f"SELECT COALESCE(SUM(monthly_wage),0) FROM records r WHERE 1=1 {sc}")),
        'total_approved': risk['approved'],
        'avg_wage': float(one(f"SELECT COALESCE(AVG(monthly_wage),0) FROM records r WHERE monthly_wage > 0 {sc}")),
        'max_wage': float(one(f"SELECT COALESCE(MAX(monthly_wage),0) FROM records r WHERE 1=1 {sc}")),
    }

    con.close()

    return {
        'kpi': kpi,
        'monthly': monthly,
        'top_wages': top_wages,
        'legal_articles': legal,
        'employment': employment,
        'wage_histogram': wage_hist,
        'deputy_performance': per_dep,
        'year_cumulative': cumulative,
        'risk': risk,
        'top_centers': centers,
        'hourly': hourly,
    }
