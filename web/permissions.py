# web/permissions.py — سیستم سطح دسترسی + محدودیت مراکز — STM v2
import sqlite3, json, sys
from pathlib import Path
from functools import wraps
from flask import session, jsonify, request, redirect, url_for

sys.path.insert(0, str(Path(__file__).parent.parent))
from app_paths import get_db_path


PERMISSIONS = {
    'tab_dashboard':        'مشاهدهٔ تب داشبورد',
    'tab_report':           'مشاهدهٔ تب گزارش خروجی',
    'tab_input':            'مشاهدهٔ تب اطلاعات ورودی',
    'dash_charts':          'نمودارهای داشبورد',
    'dash_summary':         'جدول خلاصه تفکیکی',
    'dash_approval':        'وضعیت تأیید معاونت/مرکز',
    'command_center':       'اتاق فرمان لحظه‌ای',
    'can_approve':          'تأیید/رد رکوردها',
    'can_upload':           'بارگذاری فایل اکسل',
    'can_edit_pricing':     'ویرایش قوانین قیمت‌گذاری',
    'can_edit_ceilings':    'ویرایش سقف ماهانه دستی',
    'can_edit_specialists': 'ویرایش کارشناسان/تجهیزات/جوایز',
    'can_edit_payments':    'ویرایش پرداختی‌های ماهانه',
    'can_clear_month':      'پاک کردن داده‌های ماه',
    'can_manage_users':     'مدیریت کاربران',
    'can_view_audit':       'مشاهدهٔ لاگ عملیات',
    'scope_all_deputies':   'دسترسی به همهٔ معاونت‌ها',
    'scope_all_centers':    'دسترسی به همهٔ مراکز',
}

PERMISSION_GROUPS = {
    'دسترسی به تب‌ها': ['tab_dashboard', 'tab_report', 'tab_input', 'command_center'],
    'داخل داشبورد': ['dash_charts', 'dash_summary', 'dash_approval'],
    'عملیات روی داده‌ها': ['can_approve', 'can_upload', 'can_edit_pricing',
                          'can_edit_ceilings', 'can_edit_specialists',
                          'can_edit_payments', 'can_clear_month'],
    'مدیریت': ['can_manage_users', 'can_view_audit'],
    'دامنهٔ دسترسی': ['scope_all_deputies', 'scope_all_centers'],
}

ADMIN_PERMS = {k: True for k in PERMISSIONS}


def _conn():
    c = sqlite3.connect(str(get_db_path()))
    c.row_factory = sqlite3.Row
    return c


def init_permissions():
    con = _conn()
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(auth_users)").fetchall()]
        if 'permissions' not in cols:
            con.execute("ALTER TABLE auth_users ADD COLUMN permissions TEXT DEFAULT '{}'")
        if 'allowed_deputies' not in cols:
            con.execute("ALTER TABLE auth_users ADD COLUMN allowed_deputies TEXT DEFAULT '[]'")
        if 'allowed_centers' not in cols:
            con.execute("ALTER TABLE auth_users ADD COLUMN allowed_centers TEXT DEFAULT '[]'")
        con.commit()
    except Exception:
        pass
    con.close()


def get_perms(user_id):
    if not user_id:
        return {}, [], []
    con = _conn()
    row = con.execute(
        "SELECT role, permissions, allowed_deputies, allowed_centers "
        "FROM auth_users WHERE id=?",
        (user_id,)
    ).fetchone()
    con.close()
    if not row:
        return {}, [], []
    if row['role'] == 'admin':
        return dict(ADMIN_PERMS), [], []
    try:
        perms = json.loads(row['permissions'] or '{}')
    except Exception:
        perms = {}
    try:
        deputies = json.loads(row['allowed_deputies'] or '[]')
    except Exception:
        deputies = []
    try:
        centers = json.loads(row['allowed_centers'] or '[]')
    except Exception:
        centers = []
    merged = {k: bool(perms.get(k, False)) for k in PERMISSIONS}
    return merged, deputies, centers


def has_perm(user_id, key):
    perms, _, _ = get_perms(user_id)
    return perms.get(key, False)


def get_deputy_scope(user_id):
    """None = ??? ????????? | ???? = ??? ??? ????????? | [] = ???"""
    perms, deputies, _ = get_perms(user_id)
    if perms.get('scope_all_deputies', False):
        return None
    return deputies if deputies else []


def get_center_scope(user_id):
    """None = ??? ????? | ???? = ??? ??? ????? | [] = ???"""
    perms, _, centers = get_perms(user_id)
    if perms.get('scope_all_centers', False):
        return None
    return centers if centers else []


def current_perm(key):
    return has_perm(session.get('user_id'), key)


def current_scope():
    """دامنهٔ معاونت کاربر جاری"""
    return get_deputy_scope(session.get('user_id'))


def current_center_scope():
    """دامنهٔ مراکز کاربر جاری"""
    return get_center_scope(session.get('user_id'))


def perm_required(*keys):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            is_api = request.path.startswith('/api/')
            uid = session.get('user_id')
            if not uid:
                if is_api:
                    return jsonify({'error': 'unauthorized'}), 401
                return redirect(url_for('login', next=request.path))
            if session.get('role') == 'admin':
                return f(*a, **k)
            for kk in keys:
                if has_perm(uid, kk):
                    return f(*a, **k)
            if is_api:
                return jsonify({'error': 'forbidden', 'missing': list(keys)}), 403
            return 'دسترسی کافی ندارید', 403
        return w
    return deco


def get_user_perms_view(user_id):
    perms, deputies, centers = get_perms(user_id)
    out = []
    for k, label in PERMISSIONS.items():
        out.append({'key': k, 'label': label, 'value': perms.get(k, False)})
    return {
        'permissions': out,
        'allowed_deputies': deputies,
        'allowed_centers': centers,
    }


def filter_centers_for_user(conn, all_centers):
    """
    فیلتر لیست مراکز بر اساس دسترسی کاربر جاری.
    - اگه center_scope None باشه → همه مراکز
    - وگرنه → فقط مراکزی که در scope هستن
    """
    scope = current_center_scope()
    if scope is None:
        return all_centers
    allowed = set(scope)
    return [c for c in all_centers if c in allowed]