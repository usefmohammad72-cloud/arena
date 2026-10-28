# web/command_center.py — اتاق فرمان لحظه‌ای — STM
import sqlite3, sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))
from app_paths import get_db_path


def _conn():
    c = sqlite3.connect(str(get_db_path()))
    c.row_factory = sqlite3.Row
    return c


def _count(con, sql, params=()):
    try:
        r = con.execute(sql, params).fetchone()
        return (r[0] if r else 0) or 0
    except Exception:
        return 0


def get_snapshot(scope=None, last_event_id=0):
    con = _conn()
    scope_clause = ""
    scope_params = []
    if scope:
        placeholders = ",".join("?" for _ in scope)
        scope_clause = f" AND COALESCE(r.deputy,'') IN ({placeholders})"
        scope_params = list(scope)

    total_records = _count(con, "SELECT COUNT(*) FROM records")
    total_persons = _count(con, "SELECT COUNT(*) FROM persons")

    total_approved = _count(con, f"""
        SELECT COUNT(*) FROM records r
        LEFT JOIN calculated_results cr ON cr.record_id = r.id
        WHERE COALESCE(cr.manager_approved,0)=1 {scope_clause}
    """, scope_params)

    total_pending = _count(con, f"""
        SELECT COUNT(*) FROM records r
        LEFT JOIN calculated_results cr ON cr.record_id = r.id
        WHERE COALESCE(cr.manager_approved,0)=0 {scope_clause}
    """, scope_params)

    approved_amount = _count(con, f"""
        SELECT COALESCE(SUM(COALESCE(r.monthly_wage,0)),0)
        FROM records r
        LEFT JOIN calculated_results cr ON cr.record_id = r.id
        WHERE COALESCE(cr.manager_approved,0)=1 {scope_clause}
    """, scope_params)

    pending_amount = _count(con, f"""
        SELECT COALESCE(SUM(COALESCE(r.monthly_wage,0)),0)
        FROM records r
        LEFT JOIN calculated_results cr ON cr.record_id = r.id
        WHERE COALESCE(cr.manager_approved,0)=0 {scope_clause}
    """, scope_params)

    online_users = _count(con, """
        SELECT COUNT(*) FROM auth_users
        WHERE is_active=1 AND last_login >= datetime('now','-15 minutes')
    """)

    online_list = []
    try:
        online_list = [dict(r) for r in con.execute("""
            SELECT username, full_name, last_login FROM auth_users
            WHERE is_active=1 AND last_login >= datetime('now','-15 minutes')
            ORDER BY last_login DESC LIMIT 10
        """).fetchall()]
    except Exception:
        pass

    heat_rows = []
    try:
        heat_rows = con.execute(f"""
            SELECT COALESCE(NULLIF(r.deputy,''),'نامشخص') AS deputy,
                   COUNT(*) AS total,
                   SUM(CASE WHEN COALESCE(cr.manager_approved,0)=1 THEN 1 ELSE 0 END) AS approved
            FROM records r
            LEFT JOIN calculated_results cr ON cr.record_id = r.id
            WHERE 1=1 {scope_clause}
            GROUP BY r.deputy ORDER BY total DESC
        """, scope_params).fetchall()
    except Exception:
        pass
    heatmap = []
    for r in heat_rows:
        t = r['total'] or 0
        a = r['approved'] or 0
        pct = round((a / t) * 100, 1) if t else 0
        heatmap.append({
            'deputy': r['deputy'], 'total': t, 'approved': a,
            'pending': t - a, 'pct': pct,
        })

    feed = []
    try:
        rows = con.execute("""
            SELECT id, 'approval' AS kind, action, username, created_at,
                   deputy, cost_center, amount, period_month,
                   NULL AS details
            FROM approval_log ORDER BY id DESC LIMIT 25
        """).fetchall()
        for r in rows:
            feed.append(dict(r))
    except Exception:
        pass
    try:
        rows = con.execute("""
            SELECT id, 'audit' AS kind, action, username, created_at,
                   NULL AS deputy, NULL AS cost_center, NULL AS amount,
                   NULL AS period_month, details
            FROM audit_log ORDER BY id DESC LIMIT 15
        """).fetchall()
        for r in rows:
            feed.append(dict(r))
    except Exception:
        pass
    feed.sort(key=lambda x: (x.get('created_at') or ''), reverse=True)
    feed = feed[:40]

    alerts = []
    for h in heatmap:
        if h['total'] >= 5 and h['approved'] == 0:
            alerts.append({'level': 'danger', 'icon': '🚨',
                           'text': f"معاونت {h['deputy']} هیچ تأییدی ندارد ({h['total']} رکورد)"})
        elif h['total'] >= 10 and h['pct'] < 30:
            alerts.append({'level': 'warn', 'icon': '⚠️',
                           'text': f"معاونت {h['deputy']} فقط {h['pct']}٪ تأیید شده"})
        elif h['total'] >= 10 and h['pct'] == 100:
            alerts.append({'level': 'ok', 'icon': '✅',
                           'text': f"معاونت {h['deputy']} تأیید کامل ({h['total']} رکورد)"})

    neg = _count(con, """
        SELECT COUNT(*) FROM calculated_results
        WHERE six_month_ceiling < 0 AND COALESCE(manager_approved,0)=0
    """)
    if neg > 0:
        alerts.append({'level': 'danger', 'icon': '📉',
                       'text': f"{neg} رکورد با سقف منفی در انتظار"})

    emp = _count(con, """
        SELECT COUNT(*) FROM calculated_results
        WHERE ceiling_status='حذف شود' AND COALESCE(manager_approved,0)=0
    """)
    if emp > 0:
        alerts.append({'level': 'warn', 'icon': '👥',
                       'text': f"{emp} رکورد شاغل شناسایی شده"})

    days = []
    try:
        for i in range(13, -1, -1):
            d = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
            c = _count(con, """
                SELECT COUNT(*) FROM approval_log WHERE date(created_at) = ?
            """, (d,))
            days.append({'date': d, 'count': c})
    except Exception:
        days = []

    con.close()

    return {
        'kpi': {
            'total_records': total_records,
            'total_persons': total_persons,
            'total_approved': total_approved,
            'total_pending': total_pending,
            'approved_amount': float(approved_amount),
            'pending_amount': float(pending_amount),
            'online_users': online_users,
            'alerts_count': len([a for a in alerts if a['level'] in ('danger', 'warn')]),
        },
        'heatmap': heatmap,
        'feed': feed,
        'alerts': alerts,
        'online_list': online_list,
        'trend_14d': days,
        'server_time': datetime.now().strftime('%H:%M:%S'),
    }
