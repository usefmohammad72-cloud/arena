# web/deadline.py — مدیریت مهلت ماهانه (دریافت ۲۵، تأیید ۳۰) — STM
import sqlite3, sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).parent.parent))
from app_paths import get_db_path

PERSIAN_MONTHS = ["فروردین","اردیبهشت","خرداد","تیر","مرداد","شهریور",
                  "مهر","آبان","آذر","دی","بهمن","اسفند"]


def g_to_j(gy, gm, gd):
    g_d_m = [0,31,59,90,120,151,181,212,243,273,304,334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + (365*gy) + ((gy2+3)//4) - ((gy2+99)//100) + ((gy2+399)//400) + gd + g_d_m[gm-1]
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd


def j_is_leap(jy):
    return ((jy + 12) % 33) % 4 == 1


def j_days_in_month(jy, jm):
    if jm <= 6: return 31
    if jm <= 11: return 30
    return 30 if j_is_leap(jy) else 29


def get_deadline_status():
    today = date.today()
    jy, jm, jd = g_to_j(today.year, today.month, today.day)
    month_days = j_days_in_month(jy, jm)
    deadline_day = min(30, month_days)
    days_left = deadline_day - jd
    days_to_receive = 25 - jd
    period = f"{jy}-{PERSIAN_MONTHS[jm-1]}"

    if jd < 25:
        phase, phase_label = "waiting", "در انتظار دریافت اطلاعات"
    elif jd <= 26:
        phase, phase_label = "received", "اطلاعات دریافت شد — فرصت تأیید"
    elif jd <= 28:
        phase, phase_label = "urgent", "زمان فوری برای تأیید"
    elif jd <= deadline_day:
        phase, phase_label = "critical", "آخرین روز — همین امروز!"
    else:
        phase, phase_label = "overdue", "مهلت تأیید گذشته"

    con = sqlite3.connect(str(get_db_path()))
    con.row_factory = sqlite3.Row

    def _c(sql, p=()):
        try:
            return con.execute(sql, p).fetchone()[0] or 0
        except Exception:
            return 0

    total = _c("SELECT COUNT(*) FROM records WHERE period_month = ?", (period,))
    approved = _c("""
        SELECT COUNT(*) FROM records r
        LEFT JOIN calculated_results cr ON cr.record_id = r.id
        WHERE r.period_month = ? AND COALESCE(cr.manager_approved,0)=1
    """, (period,))
    pending = total - approved
    progress = round((approved / total * 100), 1) if total else 0.0

    per_dep = []
    try:
        rows = con.execute("""
            SELECT COALESCE(NULLIF(r.deputy,''),'نامشخص') AS deputy,
                   COUNT(*) AS total,
                   SUM(CASE WHEN COALESCE(cr.manager_approved,0)=1 THEN 1 ELSE 0 END) AS approved,
                   SUM(COALESCE(r.monthly_wage,0)) AS wage_sum
            FROM records r
            LEFT JOIN calculated_results cr ON cr.record_id = r.id
            WHERE r.period_month = ?
            GROUP BY r.deputy
            HAVING SUM(CASE WHEN COALESCE(cr.manager_approved,0)=0 THEN 1 ELSE 0 END) > 0
            ORDER BY (COUNT(*) - SUM(CASE WHEN COALESCE(cr.manager_approved,0)=1 THEN 1 ELSE 0 END)) DESC
        """, (period,)).fetchall()
        for r in rows:
            t = r['total'] or 0
            a = r['approved'] or 0
            per_dep.append({
                'deputy': r['deputy'], 'total': t, 'approved': a,
                'pending': t - a, 'wage_sum': r['wage_sum'] or 0,
                'pct': round((a / t * 100), 1) if t else 0,
            })
    except Exception:
        pass

    con.close()
    month_progress = round((jd / month_days * 100), 1)

    return {
        'jalali_year': jy, 'jalali_month': jm, 'jalali_day': jd,
        'jalali_month_name': PERSIAN_MONTHS[jm-1],
        'period': period,
        'deadline_day': deadline_day,
        'month_days': month_days,
        'days_left': days_left,
        'days_to_receive': days_to_receive,
        'phase': phase,
        'phase_label': phase_label,
        'pending': pending,
        'approved': approved,
        'total': total,
        'progress_pct': progress,
        'month_progress_pct': month_progress,
        'per_deputy_pending': per_dep,
    }
