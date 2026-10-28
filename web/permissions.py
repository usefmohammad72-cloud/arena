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
    'tab_personnel':        'مشاهدهٔ تب منابع انسانی',
    'box_approval':         'مشاهدهٔ ستون و باکس «تأییدیه مدیر»',
    'search_person':        'جست‌وجوی فرد با کد ملی',
    'view_payments':        'مشاهدهٔ پرداختی‌های ماه',
    'view_personnel':       'مشاهدهٔ پرسنل',
    'export_excel':         'گرفتن خروجی اکسل',
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
    'دسترسی به تب‌ها': ['tab_dashboard', 'tab_report', 'tab_input', 'tab_personnel',
                        'command_center'],
    'داخل داشبورد': ['dash_charts', 'dash_summary', 'dash_approval'],
    'دیدن اطلاعات حساس': ['box_approval', 'search_person', 'view_payments',
                          'view_personnel', 'export_excel'],
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
    """دامنهٔ معاونت‌ها بر اساس موتور جدید (web/scope.py).

    None = همه | [] = هیچ | لیست = همان معاونت‌ها
    """
    from web import scope as _scope

    grants = _scope.get_grants(user_id)
    if grants is None:
        return None
    if not grants:
        return []
    if any(g["deputy"] == _scope.WILDCARD for g in grants):
        return None
    return sorted({g["deputy"] for g in grants})


def get_center_scope(user_id):
    """دامنهٔ مراکز بر اساس موتور جدید (web/scope.py).

    None = همه | [] = هیچ | لیست = همان مراکز
    """
    from web import scope as _scope

    grants = _scope.get_grants(user_id)
    if grants is None:
        return None
    if not grants:
        return []
    centers = _scope.visible_centers(None, user_id)
    return sorted(centers) if centers is not None else None


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