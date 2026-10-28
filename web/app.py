"""
سرور محلی نرم‌افزار — فقط روی 127.0.0.1.
"""
import sys, os, webbrowser, threading, logging, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for
from db.database import get_connection, init_db, DEFAULT_DB_PATH, log_action
from importer.excel_importer import (
    import_input_sheet, import_employment_status,
    import_monthly_payments, _apply_employment_for_month, PERSIAN_MONTHS,
    import_main_cost_centers,
)
from engine.pricing_engine import recalculate_all
from engine.report_engine import build_report
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Side, Border
from io import BytesIO

from app_paths import get_secret_key, get_uploads_dir, get_resource_dir
import web.auth as auth
import web.permissions as perms
import web.scope as scope
import web.approval as approval
import web.command_center as cc
import web.analytics as analytics
import web.deadline as deadline_mod
import web.master_routes as master_routes
import web.periods as periods
import web.personnel as personnel
import web.personnel_templates as personnel_templates
import web.period_routes as period_routes
from web.export_config import EXPORT_COLUMNS_REPORT
from importer.bulk_importer import import_bulk

def _templates_dir():
    if getattr(sys, 'frozen', False):
        p = os.path.join(get_resource_dir(), "web", "templates")
        if os.path.isdir(p): return p
    return os.path.join(os.path.dirname(__file__), "templates")

def _static_dir():
    if getattr(sys, 'frozen', False):
        p = os.path.join(get_resource_dir(), "web", "static")
        if os.path.isdir(p): return p
    return os.path.join(os.path.dirname(__file__), "static")

_static = _static_dir()
app = Flask(__name__, template_folder=_templates_dir(), static_folder=_static if os.path.isdir(_static) else None)
app.secret_key = get_secret_key()
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

logging.getLogger('werkzeug').setLevel(logging.ERROR)

DB_PATH = DEFAULT_DB_PATH
UPLOAD_DIR = str(get_uploads_dir())
os.makedirs(UPLOAD_DIR, exist_ok=True)

import re

_FA_DIGITS = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789"
)

def _to_en_digits(value):
    if value is None:
        return ""
    return str(value).translate(_FA_DIGITS)

def smart_nc(value):
    if value is None:
        return ""

    s = _to_en_digits(value).strip()
    if s.lower() in ("nan", "none", ""):
        return ""

    s = s.replace("٫", ".").replace(",", "")

    if re.search(r'[eE][+-]?\d+', s):
        try:
            s = str(int(float(s)))
        except Exception:
            pass

    if "." in s:
        s = s.split(".")[0]

    s = "".join(ch for ch in s if ch.isdigit())

    if not s:
        return ""

    if len(s) < 10:
        s = s.zfill(10)
    elif len(s) > 10:
        s = s[-10:]

    return s

def norm_period(value):
    if value is None:
        return ""

    s = _to_en_digits(value).strip()
    s = s.replace("\\", "/").replace("-", "/").replace(".", "/")
    s = re.sub(r"\s+", "", s)

    m = re.match(r'^(\d{4})/(\d{1,2})(?:/.*)?$', s)
    if m:
        s = f"{m.group(1)}/{int(m.group(2)):02d}"

    return s

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        u, p = (request.form.get("username") or "").strip(), request.form.get("password") or ""
        user = auth.authenticate(u, p)
        if user:
            session.update({'user_id': user['id'], 'username': user['username'], 'full_name': user.get('full_name', '') or user['username'], 'role': user.get('role', 'user')})
            auth.touch_last_login(user['id'])
            nxt = request.args.get("next") or "/"
            return redirect(nxt if nxt.startswith("/") else "/")
        error = "نام کاربری یا رمز عبور اشتباه است"
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/favicon.ico")
def favicon():
    return "", 204

@app.before_request
def _auth_guard():
    p = request.path
    if p.startswith("/login") or p.startswith("/logout") or p.startswith("/static") or p == "/favicon.ico": return None
    import web.master_control as _mc
    if _mc.is_locked() and not session.get('master_verified'):
        if p.startswith("/api/"): return jsonify({'error': 'lockdown'}), 503
        return "سامانه قفل است.", 503
    if 'user_id' not in session:
        if p.startswith("/api/"): return jsonify({'error': 'unauthorized'}), 401
        return redirect(url_for("login", next=p))
    return None

@app.route("/users")
@auth.admin_required
def users_page():
    return render_template("users.html")

@app.route("/api/menu-structure")
@auth.login_required
def api_menu_structure():
    """????????? ?????? ???? ????? + ????????? + ????? ?? ???????? ?????"""
    from web.permissions import PERMISSIONS
    conn = get_connection(DB_PATH)
    try:
        deputies = [r["deputy"] for r in conn.execute(
            "SELECT deputy FROM deputies_structure ORDER BY id").fetchall()]
        rows = conn.execute(
            "SELECT DISTINCT deputy, center_name FROM centers_structure "
            "WHERE center_name IS NOT NULL AND center_name != '' "
            "ORDER BY deputy, center_name").fetchall()
        centers = {}
        for r in rows:
            d = r["deputy"] or ""
            c = r["center_name"]
            if d not in centers:
                centers[d] = []
            if c not in centers[d]:
                centers[d].append(c)
    finally:
        conn.close()

    tabs = [
        {"key": "tab_dashboard", "label": "\u062f\u0627\u0634\u0628\u0648\u0631\u062f", "children": [
            {"key": "dash_charts", "label": "\u0646\u0645\u0648\u062f\u0627\u0631\u0647\u0627"},
            {"key": "dash_summary", "label": "\u062e\u0644\u0627\u0635\u0647 \u062a\u0641\u06a9\u06cc\u06a9\u06cc"},
            {"key": "dash_approval", "label": "\u0648\u0636\u0639\u06cc\u062a \u062a\u0623\u06cc\u06cc\u062f"},
        ]},
        {"key": "tab_report", "label": "\u06af\u0632\u0627\u0631\u0634 \u062e\u0631\u0648\u062c\u06cc", "children": [
            {"key": "can_approve", "label": "\u062a\u0623\u06cc\u06cc\u062f/\u0631\u062f \u0631\u06a9\u0648\u0631\u062f\u0647\u0627"},
        ]},
        {"key": "tab_input", "label": "\u0627\u0637\u0644\u0627\u0639\u0627\u062a \u0648\u0631\u0648\u062f\u06cc", "children": [
            {"key": "can_edit_pricing", "label": "\u0642\u0648\u0627\u0646\u06cc\u0646 \u0633\u0642\u0641"},
            {"key": "can_edit_specialists", "label": "\u06a9\u0627\u0631\u0634\u0646\u0627\u0633\u0627\u0646/\u062a\u062c\u0647\u06cc\u0632\u0627\u062a"},
            {"key": "can_edit_ceilings", "label": "\u0633\u0642\u0641 \u0645\u0627\u0647\u0627\u0646\u0647 \u062f\u0633\u062a\u06cc"},
            {"key": "can_edit_payments", "label": "\u067e\u0631\u062f\u0627\u062e\u062a\u06cc\u200c\u0647\u0627"},
            {"key": "can_upload", "label": "\u0627\u06cc\u0645\u067e\u0648\u0631\u062a / \u0648\u0636\u0639\u06cc\u062a \u0627\u0634\u062a\u063a\u0627\u0644"},
        ]},
        {"key": "can_upload", "label": "\u0645\u0646\u0627\u0628\u0639 \u0627\u0646\u0633\u0627\u0646\u06cc", "children": []},
        {"key": "command_center", "label": "\u0627\u062a\u0627\u0642 \u0641\u0631\u0645\u0627\u0646 (\u062a\u062d\u0644\u06cc\u0644 \u0645\u062f\u06cc\u0631\u06cc\u062a\u06cc)", "children": []},
        {"key": "can_manage_users", "label": "\u0645\u062f\u06cc\u0631\u06cc\u062a \u06a9\u0627\u0631\u0628\u0631\u0627\u0646", "children": []},
        {"key": "can_view_audit", "label": "\u0644\u0627\u06af \u0639\u0645\u0644\u06cc\u0627\u062a", "children": []},
        {"key": "can_clear_month", "label": "\u067e\u0627\u06a9 \u06a9\u0631\u062f\u0646 \u0645\u0627\u0647", "children": []},
    ]

    return jsonify({
        "tabs": tabs,
        "deputies": deputies,
        "centers": centers,
        "all_permissions": PERMISSIONS,
    })

@app.route("/api/users", methods=["GET"])
@auth.admin_required
def api_users_list():
    return jsonify(auth.list_users())

@app.route("/api/users", methods=["POST"])
@auth.admin_required
def api_users_create():
    data = request.get_json() or {}
    try:
        uid = auth.create_user(data.get("username", ""), data.get("password", ""), data.get("full_name", ""), data.get("role", "user"), permissions=data.get("permissions"), allowed_deputies=data.get("allowed_deputies"), allowed_centers=data.get("allowed_centers"))
        _scopes = data.get("scopes")
        if _scopes is None:
            _scopes = scope.grants_from_legacy(
                data.get("allowed_deputies"),
                data.get("allowed_centers"),
                data.get("permissions"),
            )
        scope.replace_grants(uid, _scopes, note="panel:create")
        return jsonify({"ok": True, "id": uid})
    except ValueError as e: return jsonify({"error": str(e)}), 400

@app.route("/api/users/<int:user_id>", methods=["PUT"])
@auth.admin_required
def api_users_update(user_id):
    data = request.get_json() or {}
    auth.update_user(user_id, full_name=data.get("full_name"), role=data.get("role"), is_active=data.get("is_active"), new_password=data.get("new_password"), permissions=data.get("permissions"), allowed_deputies=data.get("allowed_deputies"), allowed_centers=data.get("allowed_centers"))
    if any(k in data for k in ("scopes", "allowed_deputies", "allowed_centers", "permissions")):
        _scopes = data.get("scopes")
        if _scopes is None:
            _scopes = scope.grants_from_legacy(
                data.get("allowed_deputies"),
                data.get("allowed_centers"),
                data.get("permissions"),
            )
        scope.replace_grants(user_id, _scopes, note="panel:update")
    return jsonify({"ok": True})

@app.route("/api/users/<int:user_id>/scopes", methods=["GET"])
@auth.admin_required
def api_user_scopes(user_id):
    """دامنهٔ دسترسی فعلی کاربر + پیش‌نمایش اینکه چه چیزی می‌بیند."""
    return jsonify(scope.preview(user_id))


@app.route("/api/scope-options")
@auth.login_required
def api_scope_options():
    """درخت معاونت → مرکز/شبکه → نوع تأمین برای پنل مدیریت کاربران."""
    conn = get_connection(DB_PATH)
    try:
        deputies = [r["deputy"] for r in conn.execute(
            "SELECT deputy FROM deputies_structure ORDER BY id").fetchall() if r["deputy"]]
        rows = conn.execute(
            "SELECT DISTINCT deputy, center_name, COALESCE(supply_type,'') AS supply_type "
            "FROM centers_structure WHERE center_name IS NOT NULL AND center_name != '' "
            "ORDER BY deputy, center_name").fetchall()
        tree = {}
        for r in rows:
            dep = r["deputy"] or ""
            node = tree.setdefault(dep, [])
            node.append({"name": r["center_name"], "supply_type": r["supply_type"]})
        for d in deputies:
            tree.setdefault(d, [])
        return jsonify({"deputies": deputies, "tree": tree,
                        "supply_types": scope.SUPPLY_TYPES})
    finally:
        conn.close()


@app.route("/api/users/<int:user_id>", methods=["DELETE"])
@auth.admin_required
def api_users_delete(user_id):
    if user_id == session.get("user_id"): return jsonify({"error": "خودتان را حذف کنید"}), 400
    try:
        auth.delete_user(user_id)
        return jsonify({"ok": True})
    except ValueError as e: return jsonify({"error": str(e)}), 400

@app.route("/api/me")
@auth.login_required
def api_me():
    uid = session.get('user_id')
    user = auth.get_user(uid) if uid else None
    if not user: return jsonify({'error': 'unauthorized'}), 401
    pv = perms.get_user_perms_view(uid)
    _perm_dict = {item['key']: item['value'] for item in pv['permissions']}
    return jsonify({'id': user['id'], 'username': user['username'], 'full_name': user.get('full_name', ''), 'role': user.get('role', 'user'), 'permissions': pv['permissions'], 'permissions_dict': _perm_dict, 'allowed_deputies': pv['allowed_deputies'], 'allowed_centers': pv['allowed_centers']})

@app.route("/api/submitted-centers")
def api_submitted_centers():
    period = request.args.get("period")
    conn = get_connection(DB_PATH)
    try:
        t = "تامین"
        p = "پخش"
        u = "تولید"
        rows = conn.execute(
            "SELECT DISTINCT cost_center, "
            "CASE "
            "WHEN contract_subject LIKE ? THEN ? "
            "WHEN contract_subject LIKE ? THEN ? "
            "WHEN contract_subject LIKE ? THEN ? "
            "ELSE '' END AS st "
            "FROM records "
            "WHERE period_month = ? AND cost_center IS NOT NULL AND cost_center != ''",
            ("%" + t + "%", t,
             "%" + p + "%", p,
             "%" + u + "%", u,
             period)
        ).fetchall()
        return jsonify([{"center": r["cost_center"], "supply_type": r["st"]}
                        for r in rows
                        if scope.can_see(_deputy_of_center(r["cost_center"]), r["cost_center"])])
    finally:
        conn.close()

@app.route("/api/centers-with-quota")
def api_centers_with_quota():
    deputy = request.args.get("deputy", "").strip()
    conn = get_connection(DB_PATH)
    try:
        q = "SELECT id, center_name, deputy, COALESCE(supply_type,'') AS supply_type, COALESCE(monthly_quota,0) AS monthly_quota FROM centers_structure WHERE center_name IS NOT NULL AND center_name != ''"
        params = []
        if deputy and deputy not in ("", "همه"):
            q += " AND deputy = ?"
            params.append(deputy)
        q += " ORDER BY deputy, center_name, supply_type"
        rows = conn.execute(q, params).fetchall()
        return jsonify([dict(r) for r in rows
                        if scope.can_see(r["deputy"] or "", r["center_name"] or "")])
    finally:
        conn.close()

@app.route("/api/all-centers")
@auth.login_required
def api_all_centers():
    conn = get_connection(DB_PATH)
    rows = conn.execute("SELECT DISTINCT center_name, deputy, COALESCE(supply_type, '') AS supply_type FROM centers_structure WHERE center_name IS NOT NULL AND center_name != '' ORDER BY deputy, center_name, supply_type").fetchall()
    conn.close()
    return jsonify([{"name": r["center_name"], "deputy": r["deputy"] or "", "supply_type": r["supply_type"]}
                    for r in rows if scope.can_see(r["deputy"] or "", r["center_name"] or "")])

@app.route("/")
def index():
    return render_template("index.html", months=PERSIAN_MONTHS)

@app.route("/api/summary")
def api_summary():
    conn = get_connection(DB_PATH)
    total = conn.execute("SELECT COUNT(*) c FROM records").fetchone()["c"]
    removed = conn.execute("SELECT COUNT(*) c FROM calculated_results WHERE ceiling_status = 'حذف شود' AND COALESCE(manager_approved, 0) = 0").fetchone()["c"]
    unresolved = conn.execute("SELECT COUNT(*) c FROM calculated_results WHERE (ceiling_status IS NULL OR ceiling_status = '') AND COALESCE(manager_approved, 0) = 0").fetchone()["c"]
    total_amount = conn.execute("SELECT COALESCE(SUM(CAST(ceiling_status AS REAL)),0) s FROM calculated_results WHERE ceiling_status IS NOT NULL AND ceiling_status NOT IN ('', 'حذف شود')").fetchone()["s"]
    conn.close()
    return jsonify({"total_records": total, "removed_count": removed, "unresolved_count": unresolved, "total_amount": total_amount})

@app.route("/api/by-deputy")
def api_by_deputy():
    conn = get_connection(DB_PATH)
    rows = conn.execute("SELECT r.deputy AS deputy, COUNT(*) AS person_count, COALESCE(SUM(CASE WHEN cr.ceiling_status NOT IN ('', 'حذف شود') THEN CAST(cr.ceiling_status AS REAL) ELSE 0 END), 0) AS total_amount FROM records r LEFT JOIN calculated_results cr ON cr.record_id = r.id GROUP BY r.deputy ORDER BY total_amount DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows if scope.can_see(r["deputy"] or "", None)])

@app.route("/api/by-supply-type")
def api_by_supply_type():
    conn = get_connection(DB_PATH)
    rows = conn.execute("SELECT CASE WHEN r.contract_subject LIKE '%تامین%' THEN 'تامین' WHEN r.contract_subject LIKE '%پخش%' THEN 'پخش' WHEN r.contract_subject LIKE '%تولید و فنی%' THEN 'تولید و فنی' ELSE 'سایر' END AS supply_type, COUNT(*) AS person_count, COALESCE(SUM(CASE WHEN cr.ceiling_status NOT IN ('', 'حذف شود') THEN CAST(cr.ceiling_status AS REAL) ELSE 0 END), 0) AS total_amount FROM records r LEFT JOIN calculated_results cr ON cr.record_id = r.id WHERE r.deputy = 'معاونت سیما' GROUP BY supply_type ORDER BY total_amount DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/dashboard-charts")
@perms.perm_required('dash_charts')
def api_dashboard_charts():
    period = request.args.get("period") or None
    if period in ("همه", "", "all"): period = None
    conn = get_connection(DB_PATH)
    _pm_scope, _pm_params = scope.scope_sql("rr.deputy", "rr.cost_center", "rr.contract_subject")
    _pm_exists = ""
    if _pm_scope:
        _pm_exists = (" AND EXISTS (SELECT 1 FROM records rr JOIN persons pp ON pp.id = rr.person_id "
                      "WHERE pp.national_code = monthly_payments.national_code"
                      " AND rr.period_month = monthly_payments.period_month" + _pm_scope + ")")
    if period: by_month_rows = conn.execute("SELECT period_month, COALESCE(SUM(amount),0) s, COUNT(*) c FROM monthly_payments WHERE period_month = ?" + _pm_exists + " GROUP BY period_month", [period] + _pm_params).fetchall()
    else: by_month_rows = conn.execute("SELECT period_month, COALESCE(SUM(amount),0) s, COUNT(*) c FROM monthly_payments WHERE 1=1" + _pm_exists + " GROUP BY period_month", _pm_params).fetchall()
    def _sort_key(x):
        try:
            y, m = x["month"].split("-", 1)
            return (int(y), PERSIAN_MONTHS.index(m) if m in PERSIAN_MONTHS else 99)
        except: return (0, 99)
    by_month = sorted([{"month": r["period_month"], "amount": float(r["s"] or 0), "count": r["c"]} for r in by_month_rows], key=_sort_key)
    _ch_scope, _ch_params = scope.scope_sql("r.deputy", "r.cost_center", "r.contract_subject")
    where_month = " WHERE r.period_month = ? " if period else " WHERE 1=1 "
    params_month = ([period] if period else []) + _ch_params
    where_month += _ch_scope
    warn = conn.execute(f"SELECT SUM(CASE WHEN cr.ceiling_status = 'حذف شود' AND COALESCE(cr.manager_approved,0) = 0 THEN 1 ELSE 0 END) AS employed, SUM(CASE WHEN cr.six_month_ceiling < 0 AND COALESCE(cr.manager_approved,0) = 0 THEN 1 ELSE 0 END) AS orange_cnt, SUM(CASE WHEN cr.six_month_ceiling >= 0 AND cr.ceiling_status NOT IN ('', 'حذف شود') AND COALESCE(cr.manager_approved,0) = 0 AND r.monthly_wage > CAST(cr.ceiling_status AS REAL) THEN 1 ELSE 0 END) AS yellow_cnt, SUM(CASE WHEN COALESCE(cr.manager_approved,0) = 1 THEN 1 ELSE 0 END) AS approved_cnt, SUM(CASE WHEN cr.ceiling_status NOT IN ('', 'حذف شود') AND COALESCE(cr.manager_approved,0) = 0 AND (cr.six_month_ceiling IS NULL OR cr.six_month_ceiling >= 0) AND r.monthly_wage <= CAST(cr.ceiling_status AS REAL) THEN 1 ELSE 0 END) AS ok_cnt FROM records r LEFT JOIN calculated_results cr ON cr.record_id = r.id {where_month}", params_month).fetchone()
    buckets = [("۰ تا ۵۰ میلیون", 0, 50_000_000), ("۵۰ تا ۱۰۰ میلیون", 50_000_000, 100_000_000), ("۱۰۰ تا ۲۰۰ میلیون", 100_000_000, 200_000_000), ("۲۰۰ تا ۳۰۰ میلیون", 200_000_000, 300_000_000), ("۳۰۰ تا ۵۰۰ میلیون", 300_000_000, 500_000_000), ("بیش از ۵۰۰ میلیون", 500_000_000, 10**18)]
    wage_dist = []
    for label, lo, hi in buckets:
        c = conn.execute(f"SELECT COUNT(*) c FROM records r WHERE r.monthly_wage >= ? AND r.monthly_wage < ? {'AND r.period_month = ?' if period else ''}" + _ch_scope, ([lo, hi] + ([period] if period else []) + _ch_params)).fetchone()["c"]
        wage_dist.append({"label": label, "count": c})
    emp_rows = conn.execute(f"SELECT COALESCE(NULLIF(r.employment_status,''),'نامعلوم') AS s, COUNT(*) c FROM records r {where_month} GROUP BY s ORDER BY c DESC LIMIT 8", params_month).fetchall()
    employment_dist = [{"label": r["s"], "count": r["c"]} for r in emp_rows]
    dep_rows = conn.execute(f"SELECT COALESCE(NULLIF(r.deputy,''),'نامعلوم') AS d, COUNT(*) c, COALESCE(SUM(r.monthly_wage),0) s FROM records r {where_month} GROUP BY d ORDER BY s DESC LIMIT 10", params_month).fetchall()
    deputy_amounts = [{"deputy": r["d"], "count": r["c"], "amount": float(r["s"] or 0)} for r in dep_rows]
    if period: place_rows = conn.execute("SELECT cnt, COUNT(*) c FROM (SELECT p.national_code, r.period_month, COUNT(DISTINCT r.cost_center) AS cnt FROM records r JOIN persons p ON p.id = r.person_id WHERE r.cost_center IS NOT NULL AND r.cost_center != '' AND r.period_month = ?" + _ch_scope + " GROUP BY p.national_code, r.period_month) GROUP BY cnt ORDER BY cnt LIMIT 6", [period] + _ch_params).fetchall()
    else: place_rows = conn.execute("SELECT cnt, COUNT(*) c FROM (SELECT p.national_code, r.period_month, COUNT(DISTINCT r.cost_center) AS cnt FROM records r JOIN persons p ON p.id = r.person_id WHERE r.cost_center IS NOT NULL AND r.cost_center != ''" + _ch_scope + " GROUP BY p.national_code, r.period_month) GROUP BY cnt ORDER BY cnt LIMIT 6", _ch_params).fetchall()
    places_dist = [{"count": r["cnt"], "persons": r["c"]} for r in place_rows]
    conn.close()
    return jsonify({"period": period or "همه", "by_month": by_month, "warnings": {"employed": warn["employed"] or 0, "orange": warn["orange_cnt"] or 0, "yellow": warn["yellow_cnt"] or 0, "approved": warn["approved_cnt"] or 0, "ok": warn["ok_cnt"] or 0}, "wage_distribution": wage_dist, "employment_distribution": employment_dist, "deputy_amounts": deputy_amounts, "places_distribution": places_dist})

@app.route("/api/period-options")
def api_period_options():
    conn = get_connection(DB_PATH)
    rows = conn.execute("SELECT DISTINCT period_month FROM records UNION SELECT DISTINCT period_month FROM monthly_payments UNION SELECT DISTINCT period_month FROM employment_monthly UNION SELECT DISTINCT period_month FROM manual_monthly_ceilings").fetchall()
    conn.close()
    from engine.pricing_engine import year_of, month_name_of
    options = set()
    for r in rows:
        pm = r[0]
        if pm:
            y, m = year_of(pm), month_name_of(pm)
            if y and m: options.add(f"{y}-{m}")
    return jsonify(sorted(options, key=lambda pm: (int(pm.split('-')[0]), PERSIAN_MONTHS.index(pm.split('-')[1]) if pm.split('-')[1] in PERSIAN_MONTHS else 99), reverse=True))

@app.route("/api/person")
@perms.perm_required('search_person')
def api_person():
    nc = request.args.get("national_code", "").strip().zfill(10)
    if not nc:
        return jsonify({"error": "کد ملی وارد نشده است."}), 400
    conn = get_connection(DB_PATH)
    person = conn.execute("SELECT * FROM persons WHERE national_code=?", (nc,)).fetchone()
    if not person:
        conn.close()
        return jsonify({"error": "شخصی با این کد ملی پیدا نشد."}), 404
    records = conn.execute("SELECT r.*, cr.ceiling_status FROM records r LEFT JOIN calculated_results cr ON cr.record_id = r.id WHERE r.person_id = ? ORDER BY r.period_month DESC", (person["id"],)).fetchall()
    payments = conn.execute("SELECT period_month, amount, source FROM monthly_payments WHERE national_code = ? ORDER BY id", (nc,)).fetchall()
    conn.close()

    rec_out = [dict(r) for r in records
               if scope.can_see(r["deputy"] or "", r["cost_center"] or "")]
    if not rec_out and scope.get_grants() is not None:
        return jsonify({"error": "این فرد خارج از دامنهٔ دسترسی شماست."}), 403
    return jsonify({"person": dict(person), "records": rec_out,
                    "payments": [dict(r) for r in payments]})

@app.route("/api/pricing-rules", methods=["GET"])
def api_pricing_rules_list():
    conn = get_connection(DB_PATH)
    rows = conn.execute("SELECT * FROM pricing_rules WHERE valid_to IS NULL ORDER BY deputy, legal_article, category, job_title").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows
                    if scope.can_see(r["deputy"] or "", r["cost_center_filter"] or "",
                                     None, empty_center_is_any=True)])

@app.route("/api/pricing-rules/<int:rule_id>", methods=["PUT"])
@perms.perm_required('can_edit_pricing')
def api_pricing_rules_update(rule_id):
    payload = request.get_json() or {}
    new_amount, username = payload.get("amount"), payload.get("username", "کاربر")
    conn = get_connection(DB_PATH)
    old = conn.execute("SELECT * FROM pricing_rules WHERE id=?", (rule_id,)).fetchone()
    if not old:
        conn.close()
        return jsonify({"error": "قانون پیدا نشد."}), 404
    conn.execute("UPDATE pricing_rules SET valid_to=date('now') WHERE id=?", (rule_id,))
    cur = conn.execute("INSERT INTO pricing_rules (deputy, legal_article, category, job_title, cost_center_filter, amount, priority, valid_from, created_by) VALUES (?,?,?,?,?,?,?, date('now'), ?)", (old["deputy"], old["legal_article"], old["category"], old["job_title"], old["cost_center_filter"], new_amount, old["priority"], username))
    log_action(conn, username, "ویرایش قانون", f'{old["deputy"]}/{old["legal_article"]}/{old["category"]}: {old["amount"]} → {new_amount}')
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return jsonify({"ok": True, "new_id": new_id})

@app.route("/api/recalculate", methods=["POST"])
def api_recalculate():
    return jsonify(recalculate_all(DB_PATH, username="کاربر"))

@app.route("/api/manual-ceilings", methods=["GET"])
def api_manual_ceilings_list():
    period, center = request.args.get("period"), request.args.get("center")
    conn = get_connection(DB_PATH)
    q = "SELECT * FROM manual_monthly_ceilings WHERE 1=1"
    p = []
    if period: q += " AND period_month = ?"; p.append(period)
    if center: q += " AND center_name = ?"; p.append(center)
    q += " ORDER BY period_month DESC, center_name, supply_type"
    rows = conn.execute(q, p).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows
                    if scope.can_see(_deputy_of_center(r["center_name"]), r["center_name"], r["supply_type"] or "")])

@app.route("/api/manual-ceilings/save", methods=["POST"])
@perms.perm_required('can_edit_ceilings')
def api_manual_ceilings_save():
    data = request.get_json() or {}
    center, supply, period = (data.get("center_name") or "").strip(), (data.get("supply_type") or "").strip(), (data.get("period_month") or "").strip()
    try: amount = float(data.get("amount") or 0)
    except: return jsonify({"error": "مبلغ نامعتبر"}), 400
    if not center or not period: return jsonify({"error": "مرکز و دوره لازم است."}), 400
    conn = get_connection(DB_PATH)
    conn.execute("INSERT INTO manual_monthly_ceilings (center_name, supply_type, period_month, amount, note) VALUES (?,?,?,?,?) ON CONFLICT(center_name, supply_type, period_month) DO UPDATE SET amount = excluded.amount, note = excluded.note, updated_at = CURRENT_TIMESTAMP", (center, supply, period, amount, data.get("note", "")))
    log_action(conn, "کاربر", "سقف ماهانه دستی", f"{center}/{supply}/{period}: {amount}")
    conn.commit()
    conn.close()
    recalculate_all(DB_PATH)
    return jsonify({"ok": True})

@app.route("/api/manual-ceilings/<int:row_id>", methods=["DELETE"])
@perms.perm_required('can_edit_ceilings')
def api_manual_ceilings_delete(row_id):
    conn = get_connection(DB_PATH)
    conn.execute("DELETE FROM manual_monthly_ceilings WHERE id = ?", (row_id,))
    conn.commit()
    conn.close()
    recalculate_all(DB_PATH)
    return jsonify({"ok": True})

_DEPUTY_CACHE = {}


def _deputy_of_center(center):
    """معاونت یک مرکز را از ساختار مراکز می‌خواند (با کش)."""
    if not center:
        return ""
    if center in _DEPUTY_CACHE:
        return _DEPUTY_CACHE[center]
    conn = None
    try:
        conn = get_connection(DB_PATH)
        row = conn.execute(
            "SELECT deputy FROM centers_structure WHERE center_name = ? LIMIT 1",
            (center,),
        ).fetchone()
        value = (row["deputy"] or "") if row else ""
    except Exception:
        value = ""
    finally:
        try:
            conn.close()
        except Exception:
            pass
    _DEPUTY_CACHE[center] = value
    return value


@app.route("/api/import", methods=["POST"])
@perms.perm_required('can_upload')
def api_import():
    if "file" not in request.files: return jsonify({"error": "فایلی ارسال نشده است."}), 400
    f = request.files["file"]
    period = request.form.get("period", "").strip()
    if not period: return jsonify({"error": "دورهٔ ماهانه وارد نشده است."}), 400
    save_path = os.path.join(UPLOAD_DIR, f.filename)
    f.save(save_path)
    try: result = import_input_sheet(save_path, period, DB_PATH)
    except Exception as e: return jsonify({"error": f"خطا در ایمپورت: {e}"}), 500
    calc = recalculate_all(DB_PATH)
    return jsonify({"import_result": result, "calculation": calc, "unresolved_samples": result.get("unresolved_samples", [])})


@app.route("/api/import-employment", methods=["POST"])
@perms.perm_required('can_upload')
def api_import_employment():
    if "file" not in request.files:
        return jsonify({"error": "فایلی ارسال نشده است."}), 400

    f = request.files["file"]
    period = norm_period(request.form.get("period", ""))

    if not period:
        return jsonify({"error": "دورهٔ ماهانه وارد نشده است."}), 400

    save_path = os.path.join(UPLOAD_DIR, "employment_" + f.filename)
    f.save(save_path)

    conn = None
    updated = 0

    try:
        result = import_employment_status(save_path, period, DB_PATH)

        conn = get_connection(DB_PATH)

        # همه رکوردهای وضعیت اشتغال را می‌خوانیم و با norm_period فیلتر می‌کنیم
        em_rows = conn.execute("""
            SELECT national_code, period_month, employment_status
            FROM employment_monthly
        """).fetchall()

        em_map = {}
        for r in em_rows:
            if norm_period(r["period_month"]) != period:
                continue

            nc = smart_nc(r["national_code"])
            if nc:
                em_map[nc] = r["employment_status"]

        rec_rows = conn.execute("""
            SELECT r.id, p.national_code, r.period_month
            FROM records r
            JOIN persons p ON p.id = r.person_id
        """).fetchall()

        for r in rec_rows:
            if norm_period(r["period_month"]) != period:
                continue

            nc = smart_nc(r["national_code"])
            if nc in em_map:
                conn.execute(
                    "UPDATE records SET employment_status = ? WHERE id = ?",
                    (em_map[nc], r["id"])
                )
                updated += 1

        conn.commit()

    except Exception as e:
        return jsonify({"error": f"خطا: {e}"}), 500

    finally:
        if conn is not None:
            conn.close()

    calc = recalculate_all(DB_PATH)

    return jsonify({
        "import_result": result,
        "calculation": calc,
        "updated_records": updated
    })

@app.route("/api/import-monthly-payments", methods=["POST"])
@perms.perm_required('can_upload')
def api_import_monthly_payments():
    if "file" not in request.files: return jsonify({"error": "فایلی ارسال نشده است."}), 400
    f = request.files["file"]
    overwrite = request.form.get("overwrite", "false").lower() == "true"
    year_str = request.form.get("year", "").strip()
    year = int(year_str) if year_str.isdigit() else None
    save_path = os.path.join(UPLOAD_DIR, "payments_" + f.filename)
    f.save(save_path)
    try: result = import_monthly_payments(save_path, DB_PATH, overwrite=overwrite, year=year)
    except Exception as e: return jsonify({"error": f"خطا: {e}"}), 500
    calc = recalculate_all(DB_PATH)
    return jsonify({"import_result": result, "calculation": calc})

@app.route("/api/import-main-center", methods=["POST"])
@perms.perm_required('can_upload')
def api_import_main_center():
    if "file" not in request.files: return jsonify({"error": "فایلی ارسال نشده است."}), 400
    f = request.files["file"]
    period = request.form.get("period", "").strip()
    if not period: return jsonify({"error": "دوره (period) ارسال نشده"}), 400
    save_path = os.path.join(UPLOAD_DIR, "main_center_" + f.filename)
    f.save(save_path)
    try: result = import_main_cost_centers(save_path, DB_PATH, period_month=period)
    except Exception as e: return jsonify({"error": f"خطا: {e}"}), 500
    calc = recalculate_all(DB_PATH)
    return jsonify({"import_result": result, "calculation": calc})

@app.route("/api/apply-employment", methods=["POST"])
@perms.perm_required('can_upload')
def api_apply_employment():
    conn = get_connection(DB_PATH)
    months = [r["period_month"] for r in conn.execute("SELECT DISTINCT period_month FROM records")]
    total = 0
    for m in months:
        total += _apply_employment_for_month(conn, m)
        sync_employment_status(conn, m)
    conn.commit()
    conn.close()
    calc = recalculate_all(DB_PATH)
    return jsonify({"updated": total, "months": months, "calculation": calc})

@app.route("/api/centers-for-deputies")
def api_centers_for_deputies():
    deputies_arg = request.args.get("deputies", "").strip()
    deputies = [d.strip() for d in deputies_arg.split(",") if d.strip() and d.strip() != "همه"]
    period = request.args.get("period") or None
    conn = get_connection(DB_PATH)
    try:
        if deputies:
            placeholders = ",".join("?" * len(deputies))
            sql = f"SELECT DISTINCT cost_center AS name, deputy FROM records WHERE cost_center IS NOT NULL AND cost_center != '' AND deputy IN ({placeholders})"
            params = list(deputies)
        else:
            sql = "SELECT DISTINCT cost_center AS name, deputy FROM records WHERE cost_center IS NOT NULL AND cost_center != ''"
            params = []
        if period and period not in ("همه", "", "all"):
            sql += " AND period_month = ?"
            params.append(period)
        sql += " ORDER BY deputy, cost_center"
        rows = conn.execute(sql, params).fetchall()
        return jsonify([{"name": r["name"], "deputy": r["deputy"] or ""}
                        for r in rows if scope.can_see(r["deputy"] or "", r["name"] or "")])
    finally:
        conn.close()

@app.route("/api/filter-options")
def api_filter_options():
    conn = get_connection(DB_PATH)
    deputy_scope = perms.current_scope()
    center_scope = perms.current_center_scope()
    HAM = "\u0647\u0645\u0647"

    all_deputies_list = [r["deputy"] for r in conn.execute(
        "SELECT deputy FROM deputies_structure ORDER BY id")]

    allowed_deputies = set()
    if deputy_scope is None:
        allowed_deputies = set(all_deputies_list)
    else:
        allowed_deputies = set(deputy_scope)

    if center_scope:
        ph = ",".join(["?"] * len(center_scope))
        for r in conn.execute(
            f"SELECT DISTINCT deputy FROM centers_structure WHERE center_name IN ({ph}) AND deputy IS NOT NULL",
            center_scope):
            allowed_deputies.add(r["deputy"])

    deputies_list = [d for d in all_deputies_list if d in allowed_deputies]
    for d in allowed_deputies:
        if d not in deputies_list:
            deputies_list.append(d)

    dep_arg = request.args.get("deputy", "").strip()
    selected_deputies = [d.strip() for d in dep_arg.split(",") if d.strip() and d.strip() != HAM]

    if selected_deputies:
        centers_set = set()
        for d in selected_deputies:
            if d not in allowed_deputies:
                continue
            deputy_centers = [r["center_name"] for r in conn.execute(
                "SELECT DISTINCT center_name FROM centers_structure WHERE deputy=? ORDER BY center_name",
                (d,))]
            if deputy_scope is None or d in (deputy_scope or []):
                for c in deputy_centers:
                    centers_set.add(c)
            elif center_scope:
                for c in deputy_centers:
                    if c in center_scope:
                        centers_set.add(c)
        centers_list = sorted(centers_set)
    else:
        centers_set = set()
        if deputy_scope is None:
            for r in conn.execute("SELECT DISTINCT center_name FROM centers_structure ORDER BY center_name"):
                centers_set.add(r["center_name"])
        else:
            if deputy_scope:
                ph = ",".join(["?"] * len(deputy_scope))
                for r in conn.execute(
                    f"SELECT DISTINCT center_name FROM centers_structure WHERE deputy IN ({ph})",
                    deputy_scope):
                    centers_set.add(r["center_name"])
            if center_scope:
                for c in center_scope:
                    centers_set.add(c)
        centers_list = sorted(centers_set)

    conn.close()
    return jsonify({
        "deputies": [HAM] + deputies_list,
        "centers": [HAM] + centers_list,
        "supply_types": [HAM, "\u062a\u0648\u0644\u06cc\u062f", "\u062a\u0627\u0645\u06cc\u0646", "\u067e\u062e\u0634", "\u0641\u0646\u06cc"]
    })



def _to_float_safe(v):
    try:
        if v is None or v == "": return 0.0
        return float(v)
    except: return 0.0


def _apply_manual_ceiling_and_warnings(rows, period):
    # manual_monthly_ceilings = سقف ماهانه شبکه/مرکز
    # فقط در کارت «سقف ماه» استفاده می‌شود (توسط get_month_ceiling)
    # نباید ceiling_status هر نفر را override کند
    return rows


def _apply_scope_filters(deputy_raw, center_raw):
    """Returns (effective_deputies, effective_centers) considering user scope.
    Empty selection for admin => [???]."""
    scope = perms.current_scope()
    center_scope = perms.current_center_scope()

    def _split(s):
        if not s or s in ("همه", "", None):
            return []
        return [x.strip() for x in s.split(",") if x.strip()]

    user_deps = _split(deputy_raw)
    user_cens = _split(center_raw)

    if scope is None and center_scope is None:
        return (user_deps if user_deps else ["همه"], user_cens if user_cens else ["همه"])

    eff_deps = []
    if user_deps:
        for d in user_deps:
            if scope is None or d in scope:
                eff_deps.append(d)
    else:
        if scope is not None:
            eff_deps = list(scope)

    eff_cens = []
    if user_cens:
        for c in user_cens:
            if center_scope is None or c in center_scope:
                eff_cens.append(c)
    else:
        if center_scope is not None:
            eff_cens = list(center_scope)

    return (eff_deps, eff_cens)


def _build_report_scoped(deputy_raw, center_raw, supply_type, period):
    """گزارش خروجی، محدود به دامنهٔ دسترسی کاربر.

    ردیف‌ها «و» فیلتر انتخابی کاربر و «و» دامنهٔ مجاز است؛ اگر دامنه خالی باشد
    هیچ ردیفی برنمی‌گردد. خلاصه هم فقط روی همان ردیف‌ها حساب می‌شود.
    """
    grants = scope.get_grants()

    if grants is None:
        dep = deputy_raw if deputy_raw and deputy_raw != "همه" else "همه"
        cen = center_raw if center_raw and center_raw != "همه" else "همه"
        return build_report(DB_PATH, dep, cen, supply_type, period)

    if not grants:
        return {"summary": {}, "rows": []}

    def _allowed(deputy, center, supply):
        deputy = (deputy or "").strip() or _deputy_of_center(center)
        return scope.can_see(deputy, (center or "").strip(), (supply or "").strip())

    dep = deputy_raw if deputy_raw and deputy_raw != "همه" else "همه"
    cen = center_raw if center_raw and center_raw != "همه" else "همه"
    data = build_report(DB_PATH, dep, cen, supply_type, period, allowed=_allowed)
    return {"summary": data.get("summary", {}), "rows": data.get("rows", [])}


def copy_summary(summary):
    """کپی امن از خلاصهٔ گزارش."""
    return dict(summary or {})


@app.route("/api/report")
@perms.perm_required('tab_report')
def api_report():
    deputy_raw = request.args.get("deputy", "همه")
    center_raw = request.args.get("center", "همه")
    supply_type = request.args.get("supply_type", "همه")
    period = request.args.get("period") or None
    filter_type = request.args.get("filter_type", "").strip()

    data = _build_report_scoped(deputy_raw, center_raw, supply_type, period)

    _apply_manual_ceiling_and_warnings(data.get("rows", []), period)

    rows = data.get("rows", [])
    if filter_type == "yellow":
        rows = [r for r in rows if r.get("warn_yellow")]
    elif filter_type == "orange":
        rows = [r for r in rows if r.get("warn_orange")]
    elif filter_type == "red":
        rows = [r for r in rows if r.get("is_employed")]
    elif filter_type == "approved":
        rows = [r for r in rows if r.get("manager_approved")]

    conn = get_connection(DB_PATH)
    em_rows = conn.execute("SELECT national_code, period_month, employment_status FROM employment_monthly").fetchall()
    em_map = {}
    for r in em_rows:
        em_map[(smart_nc(r["national_code"]), str(r["period_month"]).strip())] = r["employment_status"]
    for row in rows:
        nc = smart_nc(row.get("national_code", ""))
        pm = str(row.get("period_month", "")).strip()
        if (nc, pm) in em_map and em_map[(nc, pm)]:
            row["employment_status"] = em_map[(nc, pm)]
    conn.close()

    data["rows"] = rows
    return jsonify(data)


@app.route("/api/export/columns")
@auth.login_required
def api_export_columns():
    return jsonify({"report": [{"key": k, "label": l, "default": d} for (k, l, d) in EXPORT_COLUMNS_REPORT]})

@app.route("/api/report-export")
@perms.perm_required('tab_report')
def api_report_export():
    # === scope enforcement ===
    scope = perms.current_scope()
    center_scope = perms.current_center_scope()
    _dep_raw = request.args.get("deputy", "\u0647\u0645\u0647")
    _cen_raw = request.args.get("center", "\u0647\u0645\u0647")
    def _split_s(s):
        if not s or s == "\u0647\u0645\u0647": return []
        return [x.strip() for x in s.split(",") if x.strip()]
    _deps = _split_s(_dep_raw)
    _cens = _split_s(_cen_raw)
    if scope is not None:
        _deps = ([d for d in _deps if d in scope] or list(scope)) if _deps else list(scope)
    if center_scope is not None:
        _cens = ([c for c in _cens if c in center_scope] or list(center_scope)) if _cens else list(center_scope)
    _first_dep = _deps[0] if _deps else "\u0647\u0645\u0647"
    _first_cen = _cens[0] if _cens else "\u0647\u0645\u0647"
    # === end scope ===
    deputy, center, supply_type = request.args.get("deputy", "همه"), request.args.get("center", "همه"), request.args.get("supply_type", "همه")
    period = request.args.get("period") or None
    filter_type = request.args.get("filter_type", "").strip()
    cols_str = request.args.get("columns", "").strip()
    show_summary = request.args.get("show_summary", "").strip() in ("1", "true", "yes")
    show_filters = request.args.get("show_filters", "").strip() in ("1", "true", "yes")
    selected_keys = [c.strip() for c in cols_str.split(",") if c.strip()] if cols_str else [k for (k, _, _) in EXPORT_COLUMNS_REPORT]
    label_map = {k: l for (k, l, _) in EXPORT_COLUMNS_REPORT}
    
    data = _build_report_scoped(deputy, center, supply_type, period)
    
    conn = get_connection(DB_PATH)
    em_rows = conn.execute("SELECT national_code, period_month, employment_status FROM employment_monthly").fetchall()
    em_map = {}
    for r in em_rows:
        em_map[(smart_nc(r['national_code']), str(r['period_month']).strip())] = r['employment_status']
    
    for row in data.get('rows', []):
        nc = smart_nc(row.get('national_code', ''))
        pm = str(row.get('period_month', '')).strip()
        if (nc, pm) in em_map and em_map[(nc, pm)]:
            row['employment_status'] = em_map[(nc, pm)]
    conn.close()
    
    rows = list(data.get("rows", []))
    # Removed broken redundant filter lines (build_report already filters)
    if filter_type == "yellow": rows = [r for r in rows if r.get("warn_yellow")]
    elif filter_type == "orange": rows = [r for r in rows if r.get("warn_orange")]
    elif filter_type == "red": rows = [r for r in rows if r.get("is_employed")]
    elif filter_type == "approved": rows = [r for r in rows if r.get("manager_approved")]
    search_str = request.args.get("search", "").strip()
    if search_str:
        try: search_map = json.loads(search_str)
        except: search_map = {}
        if search_map:
            def _match_search(r, smap):
                for key, val in smap.items():
                    if not val: continue
                    if str(val).lower() not in str(r.get(key, "")).lower(): return False
                return True
            rows = [r for r in rows if _match_search(r, search_map)]
            
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "\u06af\u0632\u0627\u0631\u0634 \u062e\u0631\u0648\u062c\u06cc"
    ws.sheet_view.rightToLeft = True
    try: ws.sheet_view.showGridLines = False
    except: pass

    PRIMARY = "1F4A7E"
    PRIMARY_DARK = "16395F"
    LIGHT_BLUE = "E8F0FE"
    GREEN = "10B981"
    RED = "EF4444"
    AMBER = "F59E0B"
    GRAY_BG = "F8FAFC"
    BORDER_GRAY = "CBD5E1"
    ZEBRA = "F1F5F9"

    title_font = Font(bold=True, color="FFFFFF", name="Tahoma", size=16)
    subtitle_font = Font(bold=True, color=PRIMARY, name="Tahoma", size=12)
    kpi_label_font = Font(bold=True, color="475569", name="Tahoma", size=9)
    header_font = Font(bold=True, color="FFFFFF", name="Tahoma", size=11)
    body_font = Font(name="Tahoma", size=10)
    filter_label_font = Font(bold=True, color="475569", name="Tahoma", size=10)

    title_fill = PatternFill("solid", fgColor=PRIMARY)
    section_fill = PatternFill("solid", fgColor=LIGHT_BLUE)
    kpi_bg_fill = PatternFill("solid", fgColor=GRAY_BG)
    header_fill = PatternFill("solid", fgColor=PRIMARY)
    zebra_fill = PatternFill("solid", fgColor=ZEBRA)
    green_fill = PatternFill("solid", fgColor="D1FAE5")
    red_fill = PatternFill("solid", fgColor="FEE2E2")

    thin = Side(style="thin", color=BORDER_GRAY)
    med = Side(style="medium", color=PRIMARY)

    def _n(v):
        try: return float(v or 0)
        except: return 0
    def _cell(r, k):
        v = r.get(k)
        if k == "manager_approved": return "✓" if v else ""
        if k == "payment_list_status":
            if isinstance(v, list): return " | ".join(v) if v else ""
            return str(v) if v else ""
        if k in ("skill_card_bonus", "employer_insurance", "non_continuous_bonus", "monthly_wage", "paid_amount", "yearly_paid_total"):
            try: return f"{int(round(float(v or 0))):,}".replace(",", ".")
            except: return ""
        if k in ("exempted_ceiling", "six_month_ceiling"):
            if v is None or v == "": return ""
            try: return f"{int(round(float(v))):,}".replace(",", ".")
            except: return v
        if k == "ceiling_status":
            if v is None or v == "": return ""
            try: return f"{int(round(float(v))):,}".replace(",", ".")
            except: return v
        return "" if v is None else v

    max_cols = max(len(selected_keys), 6)
    cur_row = 1

    # ===== TITLE BAR =====
    ws.merge_cells(start_row=cur_row, start_column=1, end_row=cur_row, end_column=max_cols)
    tcell = ws.cell(cur_row, 1, value="\u2605  \u06af\u0632\u0627\u0631\u0634 \u0645\u062f\u06cc\u0631\u06cc\u062a\u06cc")
    tcell.font = title_font
    tcell.fill = title_fill
    tcell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[cur_row].height = 34
    cur_row += 2

    # ===== SUMMARY =====
    if show_summary:
        ws.merge_cells(start_row=cur_row, start_column=1, end_row=cur_row, end_column=max_cols)
        sh = ws.cell(cur_row, 1, value="\u062e\u0644\u0627\u0635\u0647 \u062a\u062d\u0644\u06cc\u0644\u06cc")
        sh.font = subtitle_font
        sh.fill = section_fill
        sh.alignment = Alignment(horizontal="right", vertical="center", indent=1)
        ws.row_dimensions[cur_row].height = 24
        cur_row += 1

        _wage_sum = sum(_n(r.get("monthly_wage")) for r in rows)
        _paid_sum = sum(_n(r.get("paid_amount")) for r in rows)
        _approved = sum(1 for r in rows if r.get("manager_approved"))
        _with_err = 0
        for _r in rows:
            _e = _r.get("payment_list_status")
            if isinstance(_e, list): _e = " | ".join(_e) if _e else ""
            if (_e or "").strip(): _with_err += 1

        kpi_items = [
            ("\u062a\u0639\u062f\u0627\u062f \u06a9\u0644 \u0631\u06a9\u0648\u0631\u062f\u0647\u0627", len(rows), PRIMARY_DARK),
            ("\u0645\u062c\u0645\u0648\u0639 \u062f\u0633\u062a\u0645\u0632\u062f (\u0631\u06cc\u0627\u0644)", _wage_sum, PRIMARY_DARK),
            ("\u0645\u062c\u0645\u0648\u0639 \u067e\u0631\u062f\u0627\u062e\u062a\u06cc (\u0631\u06cc\u0627\u0644)", _paid_sum, PRIMARY_DARK),
            ("\u062a\u0627\u06cc\u06cc\u062f \u0634\u062f\u0647", _approved, GREEN),
            ("\u062f\u0627\u0631\u0627\u06cc \u062e\u0637\u0627", _with_err, RED),
        ]
        per_row = min(len(kpi_items), max_cols)
        block_start = cur_row
        for i, (lbl, val, color) in enumerate(kpi_items):
            col = (i % per_row) + 1
            if i > 0 and i % per_row == 0:
                cur_row += 3
            lc = ws.cell(cur_row, col, value=lbl)
            lc.font = kpi_label_font
            lc.fill = kpi_bg_fill
            lc.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            lc.border = Border(left=thin, right=thin, top=thin)
            try: _vtxt = f"{int(round(float(val or 0))):,}".replace(",", ".")
            except: _vtxt = str(val)
            vc = ws.cell(cur_row + 1, col, value=_vtxt)
            vc.font = Font(bold=True, color=color, name="Tahoma", size=16)
            vc.fill = kpi_bg_fill
            vc.alignment = Alignment(horizontal="center", vertical="center")
            vc.border = Border(left=thin, right=thin, bottom=thin)
            # KPI formatted as text
        ws.row_dimensions[block_start].height = 22
        ws.row_dimensions[block_start + 1].height = 32
        cur_row += 3

        # Employment status breakdown
        _status_counts = {}
        for _r in rows:
            _s = (_r.get("employment_status") or "").strip() or "\u0646\u0627\u0645\u0634\u062e\u0635"
            _status_counts[_s] = _status_counts.get(_s, 0) + 1
        if _status_counts:
            ws.cell(cur_row, 1, value="\u062a\u0641\u06a9\u06cc\u06a9 \u0648\u0636\u0639\u06cc\u062a \u0627\u0634\u062a\u063a\u0627\u0644").font = Font(bold=True, color=PRIMARY, name="Tahoma", size=10)
            cur_row += 1
            for _s, _cnt in sorted(_status_counts.items(), key=lambda x: -x[1]):
                ws.cell(cur_row, 1, value="  " + _s).font = body_font
                vc = ws.cell(cur_row, 2, value=_cnt)
                vc.font = body_font
                vc.alignment = Alignment(horizontal="center")
                cur_row += 1
            cur_row += 1

        # Error breakdown
        _err_counts = {}
        for _r in rows:
            _e = _r.get("payment_list_status")
            if isinstance(_e, list): _e = " | ".join(_e) if _e else ""
            _e = (_e or "").strip() or "\u0628\u062f\u0648\u0646 \u062e\u0637\u0627"
            _err_counts[_e] = _err_counts.get(_e, 0) + 1
        if _err_counts:
            ws.cell(cur_row, 1, value="\u062a\u0641\u06a9\u06cc\u06a9 \u0646\u0648\u0639 \u062e\u0637\u0627").font = Font(bold=True, color=PRIMARY, name="Tahoma", size=10)
            cur_row += 1
            for _e, _cnt in sorted(_err_counts.items(), key=lambda x: -x[1]):
                ws.cell(cur_row, 1, value="  " + _e).font = body_font
                vc = ws.cell(cur_row, 2, value=_cnt)
                vc.font = body_font
                vc.alignment = Alignment(horizontal="center")
                cur_row += 1
            cur_row += 1

    # ===== FILTERS =====
    if show_filters:
        ws.merge_cells(start_row=cur_row, start_column=1, end_row=cur_row, end_column=max_cols)
        sh2 = ws.cell(cur_row, 1, value="\u0641\u06cc\u0644\u062a\u0631\u0647\u0627\u06cc \u0633\u0631\u06cc\u0639")
        sh2.font = subtitle_font
        sh2.fill = section_fill
        sh2.alignment = Alignment(horizontal="right", vertical="center", indent=1)
        ws.row_dimensions[cur_row].height = 24
        cur_row += 1

        _filter_labels = {
            "yellow": "\u0628\u0627\u0644\u0627\u062a\u0631 \u0627\u0632 \u0633\u0642\u0641 \u0645\u0627\u0647\u0627\u0646\u0647",
            "orange": "\u0628\u0627\u0644\u0627\u062a\u0631 \u0627\u0632 \u0645\u062c\u0645\u0648\u0639 \u067e\u0631\u062f\u0627\u062e\u062a\u06cc",
            "red": "\u0634\u0627\u063a\u0644",
            "approved": "\u062a\u0627\u06cc\u06cc\u062f \u0634\u062f\u0647",
            "": "\u0647\u0645\u0647"
        }
        filter_items = [
            ("\u062f\u0648\u0631\u0647", period or "\u0647\u0645\u0647"),
            ("\u0645\u0639\u0627\u0648\u0646\u062a", deputy or "\u0647\u0645\u0647"),
            ("\u0645\u0631\u06a9\u0632 / \u0634\u0628\u06a9\u0647", center or "\u0647\u0645\u0647"),
            ("\u062a\u0627\u0645\u06cc\u0646 / \u067e\u062e\u0634", supply_type or "\u0647\u0645\u0647"),
            ("\u0646\u0648\u0639 \u0641\u06cc\u0644\u062a\u0631", _filter_labels.get(filter_type, filter_type or "\u0647\u0645\u0647")),
        ]
        for lbl, val in filter_items:
            lc = ws.cell(cur_row, 1, value=lbl)
            lc.font = filter_label_font
            lc.fill = kpi_bg_fill
            lc.alignment = Alignment(horizontal="right", vertical="center", indent=1)
            lc.border = Border(left=thin, top=thin, bottom=thin)
            vc = ws.cell(cur_row, 2, value=val)
            vc.font = body_font
            vc.fill = kpi_bg_fill
            vc.alignment = Alignment(horizontal="right", vertical="center", indent=1)
            vc.border = Border(right=thin, top=thin, bottom=thin)
            cur_row += 1
        cur_row += 1

    # ===== MAIN TABLE =====
    header_row = cur_row
    for i, k in enumerate(selected_keys, start=1):
        c = ws.cell(header_row, i, value=label_map.get(k, k))
        c.font = header_font
        c.fill = header_fill
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = Border(left=thin, right=thin, top=med, bottom=med)
    ws.row_dimensions[header_row].height = 36
    cur_row += 1

    num_cols = {"skill_card_bonus", "employer_insurance", "non_continuous_bonus",
                "monthly_wage", "paid_amount", "yearly_paid_total",
                "exempted_ceiling", "six_month_ceiling", "ceiling_status"}
    center_cols = {"row_num", "national_code", "has_second_salary", "legal_article",
                   "employment_status", "manager_approved"}

    for row_idx, r in enumerate(rows):
        for i, k in enumerate(selected_keys, start=1):
            val = _cell(r, k)
            c = ws.cell(cur_row, i, value=val)
            c.font = body_font
            if k in num_cols:
                c.alignment = Alignment(horizontal="left", vertical="center")
                if isinstance(val, (int, float)):
                    pass  # formatted as text
            elif k in center_cols:
                c.alignment = Alignment(horizontal="center", vertical="center")
            else:
                c.alignment = Alignment(horizontal="right", vertical="center", indent=1)
            if row_idx % 2 == 1:
                c.fill = zebra_fill
            c.border = Border(left=thin, right=thin, top=thin, bottom=thin)
            if k == "employment_status":
                if val == "\u0634\u0627\u063a\u0644":
                    c.fill = red_fill
                    c.font = Font(bold=True, color=RED, name="Tahoma", size=10)
                elif val == "\u0628\u0627\u0632\u0646\u0634\u0633\u062a\u0647":
                    c.font = Font(bold=True, color=AMBER, name="Tahoma", size=10)
            elif k == "payment_list_status" and val and str(val).strip():
                c.fill = red_fill
                c.font = Font(bold=True, color=RED, name="Tahoma", size=10)
            elif k == "manager_approved" and val == "\u2713":
                c.fill = green_fill
                c.font = Font(bold=True, color=GREEN, name="Tahoma", size=11)
        ws.row_dimensions[cur_row].height = 22
        cur_row += 1

    # widths
    col_widths = {
        "row_num": 6, "first_name": 14, "last_name": 20, "national_code": 14,
        "monthly_wage": 18, "cost_center": 24, "main_cost_center": 24,
        "employment_status": 14, "ceiling_status": 18, "program_name": 32,
        "payment_list_status": 22, "service_places": 18,
        "has_second_salary": 10, "legal_article": 14,
        "skill_card_bonus": 18, "employer_insurance": 18, "non_continuous_bonus": 18,
        "paid_amount": 18, "yearly_paid_total": 18, "exempted_ceiling": 16,
        "six_month_ceiling": 16, "manager_approved": 10,
    }
    for i, k in enumerate(selected_keys, start=1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = col_widths.get(k, 16)

    # freeze + filter
    ws.freeze_panes = ws.cell(header_row + 1, 1)
    try:
        last_row = cur_row - 1
        last_letter = openpyxl.utils.get_column_letter(len(selected_keys))
        ws.auto_filter.ref = "A" + str(header_row) + ":" + last_letter + str(last_row)
    except: pass

    # print settings
    try:
        ws.page_setup.orientation = 'landscape'
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
    except: pass

    try:
        ws.oddFooter.center.text = "\u06af\u0632\u0627\u0631\u0634 \u0645\u062f\u06cc\u0631\u06cc\u062a\u06cc - STM"
        ws.oddFooter.center.size = 9
    except: pass

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="گزارش-خروجی.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.route('/api/payments', methods=['GET'])
@perms.perm_required('view_payments')
def api_payments_list():
    period, nc = request.args.get("period"), request.args.get("national_code")
    conn = get_connection(DB_PATH)
    clause, params = scope.scope_sql("rr.deputy", "rr.cost_center", "rr.contract_subject")
    exists = ""
    if clause:
        exists = (" AND EXISTS (SELECT 1 FROM records rr JOIN persons pp ON pp.id = rr.person_id "
                  "WHERE pp.national_code = monthly_payments.national_code"
                  " AND rr.period_month = monthly_payments.period_month" + clause + ")")
    if period:
        rows = conn.execute("SELECT mp.id, mp.national_code, mp.period_month, mp.amount, mp.source, p.first_name, p.last_name, GROUP_CONCAT(DISTINCT r.deputy) AS deputies, GROUP_CONCAT(DISTINCT r.cost_center) AS centers FROM monthly_payments mp LEFT JOIN persons p ON p.national_code = mp.national_code LEFT JOIN records r ON r.person_id = p.id AND r.period_month = mp.period_month WHERE mp.period_month = ? GROUP BY mp.id ORDER BY p.last_name", (period,)).fetchall()
        out = [dict(r) for r in rows if scope.get_grants() is None
               or any(scope.can_see(d, c) for d in (r["deputies"] or "").split(",")
                      for c in (r["centers"] or "").split(","))]
    elif nc:
        rows = conn.execute("SELECT * FROM monthly_payments WHERE national_code = ? ORDER BY id", (nc,)).fetchall()
        out = [dict(r) for r in rows]
    else:
        rows = conn.execute("SELECT * FROM monthly_payments WHERE 1=1" + exists + " ORDER BY id LIMIT 500", params).fetchall()
        out = [dict(r) for r in rows]
    conn.close()
    return jsonify(out)

@app.route("/api/payments", methods=["POST"])
@perms.perm_required('can_edit_payments')
def api_payments_create():
    data = request.get_json() or {}
    nc, period = smart_nc(data.get("national_code")), (data.get("period_month") or "").strip()
    amount, source, note = data.get("amount", 0), data.get("source", "manual"), data.get("note", "")
    if not nc or not period: return jsonify({"error": "کد ملی و دوره لازم است."}), 400
    conn = get_connection(DB_PATH)
    conn.execute("INSERT INTO monthly_payments (national_code, period_month, amount, source, note) VALUES (?,?,?,?,?) ON CONFLICT(national_code, period_month) DO UPDATE SET amount=excluded.amount, source=excluded.source, note=excluded.note", (nc, period, float(amount or 0), source, note))
    conn.commit()
    log_action(conn, "کاربر", "ثبت پرداخت", f"{nc} / {period} / {amount}")
    conn.close()
    recalculate_all(DB_PATH)
    return jsonify({"ok": True})

@app.route("/api/payments/<int:pid>", methods=["DELETE"])
@perms.perm_required('can_edit_payments')
def api_payments_delete(pid):
    conn = get_connection(DB_PATH)
    conn.execute("DELETE FROM monthly_payments WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    recalculate_all(DB_PATH)
    return jsonify({"ok": True})

@app.route("/api/payments/confirm-month", methods=["POST"])
@perms.perm_required('can_edit_payments')
def api_payments_confirm_month():
    data = request.get_json() or {}
    period, record_ids = (data.get("period_month") or "").strip(), data.get("record_ids")
    if not period: return jsonify({"error": "دوره لازم است."}), 400
    conn = get_connection(DB_PATH)
    confirmed, skipped = 0, 0
    if record_ids:
        for rid in record_ids:
            row = conn.execute("SELECT r.id AS record_id, p.national_code, r.monthly_wage FROM records r JOIN persons p ON p.id = r.person_id WHERE r.id = ?", (rid,)).fetchone()
            if not row: continue
            amount = float(row["monthly_wage"] or 0)
            if amount <= 0: continue
            existing = conn.execute("SELECT source FROM monthly_payments WHERE national_code = ? AND period_month = ?", (row["national_code"], period)).fetchone()
            if existing and existing["source"] in ("manual", "approved"): skipped += 1; continue
            conn.execute("INSERT INTO monthly_payments (national_code, period_month, amount, source, record_id) VALUES (?,?,?,?,?) ON CONFLICT(national_code, period_month) DO UPDATE SET amount=excluded.amount, source='auto', record_id=excluded.record_id", (row["national_code"], period, amount, "auto", row["record_id"]))
            confirmed += 1
    conn.commit()
    conn.close()
    recalculate_all(DB_PATH)
    return jsonify({"ok": True, "confirmed": confirmed, "skipped_manual": skipped})

def _approval_scope_check(row):
    """بررسی دامنهٔ دسترسی برای عملیات تأیید/رد — بسته به‌طور پیش‌فرض (fail-closed).

    قاعده‌ها:
      ۱) ادمین: همهٔ رکوردها مجاز.
      ۲) کاربر بدون مجوز «تأیید رکوردها» (can_approve): رد.
      ۳) دامنهٔ معاونت/مرکز:
             None  → «همه» (مجاز)
             لیست  → فقط همان موارد
             []    → «هیچ»
      ۴) رکورد وقتی مجاز است که «یا» معاونتش در دامنه باشد «یا» مرکزش
         (اجتماع دامنه‌ها؛ مثلاً «کل معاونت برون مرزی» + «فقط شبکه فیلم»).
      ۵) رکورد بدون معاونت و بدون مرکز، برای کاربر محدود قابل تأیید نیست.
    """
    uid = session.get("user_id")
    if not uid:
        return False, 403, "نشست معتبر نیست؛ دوباره وارد شوید"

    if session.get("role") == "admin":
        return True, 200, ""

    if not perms.has_perm(uid, "can_approve"):
        return False, 403, "مجوز «تأیید/رد رکوردها» را ندارید"

    dep_scope = perms.get_deputy_scope(uid)
    ctr_scope = perms.get_center_scope(uid)

    # کاربری که دامنه‌اش «همهٔ معاونت‌ها» و «همهٔ مراکز» است
    if dep_scope is None and ctr_scope is None:
        return True, 200, ""

    keys = row.keys() if hasattr(row, "keys") else []
    deputy = ""
    center = ""
    if "deputy" in keys and row["deputy"] is not None:
        deputy = str(row["deputy"]).strip()
    if "cost_center" in keys and row["cost_center"] is not None:
        center = str(row["cost_center"]).strip()

    if not deputy and not center:
        return False, 403, "این رکورد معاونت/مرکز مشخصی ندارد و قابل تأیید نیست"

    dep_list = [str(d).strip() for d in (dep_scope or [])]
    ctr_list = [str(c).strip() for c in (ctr_scope or [])]

    ok_dep = bool(deputy) and (dep_scope is None or deputy in dep_list)
    ok_ctr = bool(center) and (ctr_scope is None or center in ctr_list)

    if not (ok_dep or ok_ctr):
        return False, 403, (
            "این رکورد خارج از دامنهٔ دسترسی شماست "
            f"(معاونت: {deputy or '—'} | مرکز: {center or '—'})"
        )

    return True, 200, ""


@app.route("/api/bulk-approve", methods=["POST"])
@perms.perm_required('can_approve')
def api_bulk_approve():
    data = request.get_json() or {}
    record_ids = data.get("record_ids") or []
    if not record_ids: return jsonify({"error": "هیچ ردیفی انتخاب نشده"}), 400
    conn = get_connection(DB_PATH)
    approved_count, errors = 0, []
    for rid in record_ids:
        try:
            row = conn.execute("SELECT r.id, r.period_month, r.monthly_wage, p.national_code, r.deputy, r.cost_center FROM records r JOIN persons p ON p.id = r.person_id WHERE r.id = ?", (rid,)).fetchone()
            if not row: continue
            _ok, _st, _msg = _approval_scope_check(row)
            if not _ok:
                errors.append(f"id={rid}: {_msg}"); continue
            nc, pm, wage = row["national_code"], row["period_month"], float(row["monthly_wage"] or 0)
            conn.execute("UPDATE calculated_results SET manager_approved = 1 WHERE record_id = ?", (rid,))
            if wage > 0:
                existing = conn.execute("SELECT source FROM monthly_payments WHERE national_code = ? AND period_month = ?", (nc, pm)).fetchone()
                if not (existing and existing["source"] == "manual"):
                    conn.execute("INSERT INTO monthly_payments (national_code, period_month, amount, source, record_id) VALUES (?, ?, ?, 'approved', ?) ON CONFLICT(national_code, period_month) DO UPDATE SET amount = excluded.amount, source = 'approved', record_id = excluded.record_id", (nc, pm, wage, rid))
            try: approval.log_approval(record_id=rid, user_id=session.get('user_id'), username=session.get('username', '?'), action='approve', deputy=row['deputy'] or '', cost_center=row['cost_center'] or '', period_month=pm, amount=wage)
            except: pass
            approved_count += 1
        except Exception as e: errors.append(f"id={rid}: {e}")
    conn.commit()
    conn.close()
    try: recalculate_all(DB_PATH)
    except: pass
    return jsonify({"ok": True, "approved_count": approved_count, "errors": errors[:10]})

@app.route("/api/bulk-unapprove", methods=["POST"])
@perms.perm_required('can_approve')
def api_bulk_unapprove():
    """لغو تأیید گروهی — با همان بررسی دامنهٔ دسترسی و ثبت در لاگ."""
    data = request.get_json() or {}
    record_ids = data.get("record_ids") or []
    if not record_ids:
        return jsonify({"error": "هیچ ردیفی انتخاب نشده"}), 400

    conn = get_connection(DB_PATH)
    unapproved_count, skipped = 0, []
    try:
        for rid in record_ids:
            try:
                row = conn.execute(
                    "SELECT r.id, r.period_month, r.monthly_wage, p.national_code, "
                    "r.deputy, r.cost_center "
                    "FROM records r JOIN persons p ON p.id = r.person_id "
                    "WHERE r.id = ?",
                    (rid,),
                ).fetchone()
                if not row:
                    skipped.append({"id": rid, "reason": "رکورد پیدا نشد"})
                    continue

                _ok, _st, _msg = _approval_scope_check(row)
                if not _ok:
                    skipped.append({"id": rid, "reason": _msg})
                    continue

                conn.execute(
                    "UPDATE calculated_results SET manager_approved = 0 WHERE record_id = ?",
                    (rid,),
                )
                conn.execute(
                    "DELETE FROM monthly_payments "
                    "WHERE national_code = ? AND period_month = ? AND source = 'approved'",
                    (row["national_code"], row["period_month"]),
                )
                try:
                    approval.log_approval(
                        record_id=rid,
                        user_id=session.get("user_id"),
                        username=session.get("username", "?"),
                        action="unapprove",
                        deputy=row["deputy"] or "",
                        cost_center=row["cost_center"] or "",
                        period_month=row["period_month"],
                        amount=float(row["monthly_wage"] or 0),
                    )
                except Exception:
                    pass
                unapproved_count += 1
            except Exception as exc:
                skipped.append({"id": rid, "reason": str(exc)})
        conn.commit()
    finally:
        conn.close()

    try:
        recalculate_all(DB_PATH)
    except Exception:
        pass

    return jsonify({
        "ok": True,
        "unapproved_count": unapproved_count,
        "skipped": skipped[:20],
    })


@app.route("/api/toggle-approval", methods=["POST"])
@perms.perm_required('can_approve')
def api_toggle_approval():
    data = request.get_json() or {}
    record_id, approved = data.get("record_id"), bool(data.get("approved"))
    if not record_id: return jsonify({"error": "record_id لازم است."}), 400
    conn = get_connection(DB_PATH)
    row = conn.execute("SELECT r.id, r.period_month, r.monthly_wage, p.national_code, r.deputy, r.cost_center FROM records r JOIN persons p ON p.id = r.person_id WHERE r.id = ?", (record_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "رکورد پیدا نشد."}), 404
    _ok, _st, _msg = _approval_scope_check(row)
    if not _ok:
        conn.close()
        return jsonify({"error": _msg}), _st
    conn.execute("UPDATE calculated_results SET manager_approved = ? WHERE record_id = ?", (1 if approved else 0, record_id))
    nc, pm, wage = row["national_code"], row["period_month"], float(row["monthly_wage"] or 0)
    existing = conn.execute("SELECT source FROM monthly_payments WHERE national_code = ? AND period_month = ?", (nc, pm)).fetchone()
    if approved and wage > 0:
        if not (existing and existing["source"] == "manual"):
            conn.execute("INSERT INTO monthly_payments (national_code, period_month, amount, source, record_id) VALUES (?, ?, ?, 'approved', ?) ON CONFLICT(national_code, period_month) DO UPDATE SET amount = excluded.amount, source = 'approved', record_id = excluded.record_id", (nc, pm, wage, record_id))
    elif not approved:
        conn.execute("DELETE FROM monthly_payments WHERE national_code=? AND period_month=? AND source='approved'", (nc, pm))
    conn.commit()
    conn.close()
    try: approval.log_approval(record_id=record_id, user_id=session.get('user_id'), username=session.get('username', '?'), action='approve' if approved else 'unapprove', deputy=row['deputy'] or '', cost_center=row['cost_center'] or '', period_month=pm, amount=wage)
    except: pass
    recalculate_all(DB_PATH)
    return jsonify({"ok": True, "approved": approved})

def _scoped_persons(conn, with_names=True):
    """فقط افرادی که در دامنهٔ کاربر حداقل یک رکورد دارند."""
    clause, params = scope.scope_sql("r.deputy", "r.cost_center", "r.contract_subject")
    if not clause:
        cols = "p.national_code, p.first_name, p.last_name" if with_names else "p.national_code"
        order = " ORDER BY p.last_name, p.first_name" if with_names else ""
        return conn.execute(f"SELECT DISTINCT {cols} FROM persons p{order}", []).fetchall()
    cols = "p.national_code, p.first_name, p.last_name" if with_names else "p.national_code"
    q = (f"SELECT DISTINCT {cols} FROM persons p JOIN records r ON r.person_id = p.id"
         f" WHERE 1=1 {clause}" + (" ORDER BY p.last_name, p.first_name" if with_names else ""))
    return conn.execute(q, params).fetchall()

@app.route("/api/payment-grid", methods=["GET"])
@perms.perm_required('view_payments')
def api_payment_grid():
    year = request.args.get("year", "").strip() or None
    conn = get_connection(DB_PATH)
    persons = _scoped_persons(conn, with_names=True)
    if year: payments = conn.execute("SELECT national_code, period_month, amount FROM monthly_payments WHERE period_month LIKE ?", (f"{year}-%",)).fetchall()
    else: payments = conn.execute("SELECT national_code, period_month, amount FROM monthly_payments").fetchall()
    conn.close()
    allowed_nc = {p["national_code"] for p in persons}
    by_nc = {}
    for p in payments:
        if p["national_code"] not in allowed_nc:
            continue
        pm = p["period_month"] or ""
        m = pm.split("-", 1)[1] if "-" in pm else pm
        by_nc.setdefault(p["national_code"], {})[m] = p["amount"]
    result = [{"national_code": p["national_code"], "first_name": p["first_name"], "last_name": p["last_name"], "amounts": by_nc.get(p["national_code"], {})} for p in persons]
    return jsonify(result)

@app.route("/api/payment-grid/save", methods=["POST"])
@perms.perm_required('can_edit_payments')
def api_payment_grid_save():
    data = request.get_json() or {}
    nc, period, amount = smart_nc(data.get("national_code")), (data.get("period_month") or "").strip(), data.get("amount", 0)
    if not nc or not period: return jsonify({"error": "کد ملی و ماه لازم است."}), 400
    try: amount = float(amount or 0)
    except: return jsonify({"error": "مبلغ نامعتبر"}), 400
    conn = get_connection(DB_PATH)
    if scope.is_restricted():
        clause, params = scope.scope_sql("r.deputy", "r.cost_center", "r.contract_subject")
        hit = conn.execute("SELECT 1 FROM records r JOIN persons p ON p.id = r.person_id WHERE p.national_code = ? " + clause + " LIMIT 1", [nc] + params).fetchone()
        if not hit:
            conn.close()
            return jsonify({"error": "این فرد خارج از دامنهٔ دسترسی شماست."}), 403
    if amount <= 0: conn.execute("DELETE FROM monthly_payments WHERE national_code=? AND period_month=?", (nc, period))
    else: conn.execute("INSERT INTO monthly_payments (national_code, period_month, amount, source) VALUES (?, ?, ?, 'manual') ON CONFLICT(national_code, period_month) DO UPDATE SET amount = excluded.amount, source = 'manual'", (nc, period, amount))
    conn.commit()
    conn.close()
    recalculate_all(DB_PATH)
    return jsonify({"ok": True})

@app.route("/api/payment-grid/export")
@perms.perm_required('export_excel')
def api_payment_grid_export():
    conn = get_connection(DB_PATH)
    persons = _scoped_persons(conn, with_names=True)
    payments = conn.execute("SELECT national_code, period_month, amount FROM monthly_payments").fetchall()
    conn.close()
    allowed_nc = {p["national_code"] for p in persons}
    by_nc = {}
    for p in payments:
        if p["national_code"] in allowed_nc:
            by_nc.setdefault(p["national_code"], {})[p["period_month"]] = p["amount"]
    all_periods = set()
    for pm_map in by_nc.values(): all_periods.update(pm_map.keys())
    def sort_key(pm):
        try:
            y, m = pm.split("-", 1)
            return (int(y), PERSIAN_MONTHS.index(m) if m in PERSIAN_MONTHS else 99)
        except: return (0, 99)
    periods = sorted(all_periods, key=sort_key)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "پرداختی‌های ماهانه"
    ws.sheet_view.rightToLeft = True
    header_font = Font(bold=True, color="FFFFFF", name="Tahoma")
    header_fill = PatternFill("solid", start_color="1F4A7E")
    header_align = Alignment(horizontal="center", vertical="center")
    headers = ["کد ملی", "نام", "نام خانوادگی"] + periods + ["مجموع سال"]
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=1, column=i, value=h)
        c.font, c.fill, c.alignment = header_font, header_fill, header_align
    for r_i, p in enumerate(persons, start=2):
        ws.cell(row=r_i, column=1, value=p["national_code"])
        ws.cell(row=r_i, column=2, value=p["first_name"] or "")
        ws.cell(row=r_i, column=3, value=p["last_name"] or "")
        total = 0
        amounts = by_nc.get(p["national_code"], {})
        for m_i, m in enumerate(periods, start=4):
            v = amounts.get(m)
            if v:
                ws.cell(row=r_i, column=m_i, value=float(v))
                total += float(v)
        ws.cell(row=r_i, column=4 + len(periods), value=total)
    ws.column_dimensions['A'].width = 14; ws.column_dimensions['B'].width = 16; ws.column_dimensions['C'].width = 20
    for i in range(4, 4 + len(periods) + 1): ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = 14
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="پرداختی‌های ماهانه.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.route("/api/specialists", methods=["GET"])
def api_specialists_list():
    period = request.args.get("period")
    conn = get_connection(DB_PATH)
    query = "SELECT s.id, s.center_name, s.supply_type, s.period_month, s.specialists, s.equipment, s.bonus, c.deputy FROM specialists_equipment_bonus s LEFT JOIN centers_structure c ON c.center_name = s.center_name AND COALESCE(c.supply_type,'') = s.supply_type"
    params = []
    if period and period != 'همه':
        query += " WHERE s.period_month = ?"
        params.append(period)
    query += " ORDER BY c.deputy, s.center_name, s.supply_type"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows
                    if scope.can_see(r["deputy"] or "", r["center_name"] or "", r["supply_type"] or "")])

@app.route("/api/bulk-import/<category>", methods=["POST"])
@perms.perm_required('can_edit_specialists')
def api_bulk_import(category):
    if category not in ("specialists", "equipment", "bonus"): return jsonify({"error": "دستهٔ نامعتبر"}), 400
    if "file" not in request.files: return jsonify({"error": "فایلی ارسال نشده است."}), 400
    f = request.files["file"]
    period = request.form.get("period", "").strip()
    if not period: return jsonify({"error": "دوره (period) ارسال نشده"}), 400
    save_path = os.path.join(UPLOAD_DIR, f"bulk_{category}_" + f.filename)
    f.save(save_path)
    try: result = import_bulk(save_path, category, DB_PATH, username=session.get("username", "کاربر"), period_month=period)
    except Exception as e: return jsonify({"error": f"خطا: {e}"}), 500
    return jsonify({"ok": True, "result": result})

@app.route("/api/bulk-import/remap", methods=["POST"])
@perms.perm_required('can_edit_specialists')
def api_bulk_import_remap():
    data = request.get_json() or {}
    source, target, category, amount, period = (data.get("source") or "").strip(), (data.get("target") or "").strip(), (data.get("category") or "").strip(), data.get("amount", 0), (data.get("period") or "").strip()
    if not source or not target or category not in ("specialists", "equipment", "bonus") or not period: return jsonify({"error": "پارامترها نامعتبر"}), 400
    try: amount = float(amount or 0)
    except: return jsonify({"error": "مبلغ نامعتبر"}), 400
    col_name = {"specialists": "specialists", "equipment": "equipment", "bonus": "bonus"}[category]
    conn = get_connection(DB_PATH)
    conn.execute("DELETE FROM specialists_equipment_bonus WHERE center_name = ? AND (supply_type = '' OR supply_type IS NULL) AND period_month = ?", (source, period))
    row = conn.execute("SELECT supply_type FROM centers_structure WHERE center_name = ? LIMIT 1", (target,)).fetchone()
    supply_type = (row["supply_type"] or "") if row else ""
    existing = conn.execute("SELECT id FROM specialists_equipment_bonus WHERE center_name = ? AND COALESCE(supply_type,'') = ? AND period_month = ?", (target, supply_type, period)).fetchone()
    if existing: conn.execute(f"UPDATE specialists_equipment_bonus SET {col_name} = ? WHERE id = ?", (amount, existing["id"]))
    else:
        defaults = {"specialists": 0.0, "equipment": 0.0, "bonus": 0.0}
        defaults[col_name] = amount
        conn.execute("INSERT INTO specialists_equipment_bonus (center_name, supply_type, period_month, specialists, equipment, bonus) VALUES (?, ?, ?, ?, ?, ?)", (target, supply_type, period, defaults["specialists"], defaults["equipment"], defaults["bonus"]))
    log_action(conn, "کاربر", "تخصیص دستی مرکز", f"{source} → {target} ({category})")
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/specialists/<int:row_id>", methods=["PUT"])
@perms.perm_required('can_edit_specialists')
def api_specialists_update(row_id):
    payload = request.get_json() or {}
    field, value = payload.get("field"), payload.get("value")
    if field not in ("specialists", "equipment", "bonus"): return jsonify({"error": "فیلد نامعتبر."}), 400
    try: value = float(value or 0)
    except: return jsonify({"error": "مقدار عددی لازم است."}), 400
    conn = get_connection(DB_PATH)
    conn.execute(f"UPDATE specialists_equipment_bonus SET {field} = ? WHERE id = ?", (value, row_id))
    log_action(conn, "کاربر", "ویرایش کارشناسان", f"row {row_id}: {field}")
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

def _build_summary_rows(conn, period, deputy_filter, center_filter, supply_filter):
    from collections import defaultdict

    clause, sc_params = scope.scope_sql("r.deputy", "r.cost_center", "r.contract_subject")

    q = ("SELECT r.deputy, r.cost_center, "
         "COALESCE(SUM(r.skill_card_bonus), 0) AS skill_card_all, "
         "COALESCE(SUM(CASE WHEN r.legal_article NOT LIKE '%38%' AND r.legal_article NOT LIKE '%۳۸%' "
         "THEN r.skill_card_bonus ELSE 0 END), 0) AS skill_card_excl_38, "
         "COALESCE(SUM(r.monthly_wage), 0) AS wage_sum, "
         "COALESCE(SUM(r.non_continuous_bonus), 0) AS non_continuous_sum, "
         "COALESCE(SUM(r.employer_insurance), 0) AS employer_insurance_sum, "
         "COUNT(*) AS cnt FROM records r WHERE 1=1" + clause)
    p = list(sc_params)
    if period:
        q += " AND r.period_month = ?"; p.append(period)
    if deputy_filter and deputy_filter != "همه":
        q += " AND r.deputy = ?"; p.append(deputy_filter)
    if center_filter and center_filter != "همه":
        q += " AND r.cost_center = ?"; p.append(center_filter)
    if supply_filter and supply_filter != "همه":
        q += " AND r.contract_subject LIKE ?"; p.append(f"%{supply_filter}%")
    q += " GROUP BY r.deputy, r.cost_center ORDER BY r.deputy, r.cost_center"
    rows = conn.execute(q, p).fetchall()

    centers_ok = scope.visible_centers(conn)
    se_sql, se_params = "", []
    if centers_ok is not None:
        if not centers_ok:
            se_sql = " AND 1=0"
        else:
            se_sql = " AND center_name IN (" + ",".join("?" * len(centers_ok)) + ")"
            se_params = sorted(centers_ok)

    if period:
        se_rows = conn.execute(
            "SELECT center_name, supply_type, specialists, equipment, bonus "
            "FROM specialists_equipment_bonus WHERE period_month = ?" + se_sql,
            [period] + se_params,
        ).fetchall()
    else:
        se_rows = conn.execute(
            "SELECT center_name, supply_type, SUM(specialists) AS specialists, "
            "SUM(equipment) AS equipment, SUM(bonus) AS bonus "
            "FROM specialists_equipment_bonus WHERE 1=1" + se_sql +
            " GROUP BY center_name, supply_type", se_params,
        ).fetchall()

    se_map = defaultdict(lambda: {"specialists": 0.0, "equipment": 0.0, "bonus": 0.0})
    for r in se_rows:
        se_map[r["center_name"]]["specialists"] += float(r["specialists"] or 0)
        se_map[r["center_name"]]["equipment"] += float(r["equipment"] or 0)
        se_map[r["center_name"]]["bonus"] += float(r["bonus"] or 0)

    result = []
    for r in rows:
        deputy, center = r["deputy"] or "", r["cost_center"] or ""
        se = se_map.get(center, {"specialists": 0, "equipment": 0, "bonus": 0})
        skill_all = float(r["skill_card_all"] or 0)
        skill_excl_38 = float(r["skill_card_excl_38"] or 0)
        wage_sum = float(r["wage_sum"] or 0)
        non_cont_sum = float(r["non_continuous_sum"] or 0)
        emp_ins = float(r["employer_insurance_sum"] or 0)
        professional = (skill_all + skill_excl_38 * 0.23) * 1.04
        allocation_base = (wage_sum + non_cont_sum + se["specialists"] + se["equipment"]
                           + se["bonus"] + (emp_ins - skill_excl_38 * 0.23))
        allocation = allocation_base * 1.04
        result.append({
            "deputy": deputy, "center": center, "count": r["cnt"],
            "skill_card_all": skill_all, "skill_card_excl_38": skill_excl_38,
            "wage_sum": wage_sum, "non_continuous_sum": non_cont_sum,
            "employer_insurance_sum": emp_ins,
            "specialists": se["specialists"], "equipment": se["equipment"],
            "bonus": se["bonus"], "professional": professional,
            "allocation": allocation, "total": professional + allocation,
        })
    return result

@app.route("/api/summary-table")
@perms.perm_required('tab_report')
def api_summary_table():
    period = request.args.get("period") or None
    if period in ("همه", "", "all"): period = None
    deputy_filter, center_filter, supply_filter = request.args.get("deputy", "همه"), request.args.get("center", "همه"), request.args.get("supply_type", "همه")
    conn = get_connection(DB_PATH)
    rows = _build_summary_rows(conn, period, deputy_filter, center_filter, supply_filter)
    conn.close()
    return jsonify({"period": period or "همه", "rows": rows, "total_professional": sum(r["professional"] for r in rows), "total_allocation": sum(r["allocation"] for r in rows), "total_sum": sum(r["total"] for r in rows)})

@app.route("/api/summary-table/export")
@perms.perm_required('tab_report')
def api_summary_table_export():
    period = request.args.get("period") or None
    if period in ("همه", "", "all"): period = None
    deputy_filter, center_filter, supply_filter = request.args.get("deputy", "همه"), request.args.get("center", "همه"), request.args.get("supply_type", "همه")
    conn = get_connection(DB_PATH)
    rows = _build_summary_rows(conn, period, deputy_filter, center_filter, supply_filter)
    conn.close()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "خلاصه تفکیکی"
    ws.sheet_view.rightToLeft = True
    headers = ["معاونت", "شبکه / مرکز", "صلاحیت حرفه‌ای (ریال)", "تخصیص ماه (ریال)", "مجموع (ریال)"]
    header_font = Font(bold=True, color="FFFFFF", name="Tahoma")
    header_fill = PatternFill("solid", start_color="1F4A7E")
    header_align = Alignment(horizontal="center", vertical="center")
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=1, column=i, value=h)
        c.font, c.fill, c.alignment = header_font, header_fill, header_align
    for r in rows: ws.append([r["deputy"], r["center"], round(r["professional"]), round(r["allocation"]), round(r["total"])])
    ws.append(["جمع کل", "", round(sum(r["professional"] for r in rows)), round(sum(r["allocation"] for r in rows)), round(sum(r["total"] for r in rows))])
    for i in range(1, len(headers) + 1): ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = 22
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="خلاصه-تفکیکی.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.route("/api/clear-month", methods=["POST"])
@auth.admin_required
def api_clear_month():
    data = request.get_json() or {}
    period = (data.get("period_month") or "").strip()
    if not period: return jsonify({"error": "دوره لازم است."}), 400
    clear_records, clear_employment, clear_payments, clear_bulk, clear_maincenter, category = bool(data.get("clear_records", False)), bool(data.get("clear_employment", False)), bool(data.get("clear_payments", False)), bool(data.get("clear_bulk", False)), bool(data.get("clear_maincenter", False)), (data.get("category") or "").strip()
    if not (clear_records or clear_employment or clear_payments or clear_bulk or clear_maincenter): return jsonify({"error": "حداقل یک گزینه انتخاب کنید."}), 400
    conn = get_connection(DB_PATH)
    result = {}
    if clear_records:
        conn.execute("UPDATE monthly_payments SET record_id = NULL WHERE record_id IN (SELECT id FROM records WHERE period_month = ?)", (period,))
        result["calculated_deleted"] = conn.execute("DELETE FROM calculated_results WHERE record_id IN (SELECT id FROM records WHERE period_month = ?)", (period,)).rowcount
        result["records_deleted"] = conn.execute("DELETE FROM records WHERE period_month = ?", (period,)).rowcount
    if clear_employment: result["employment_deleted"] = conn.execute("DELETE FROM employment_monthly WHERE period_month = ?", (period,)).rowcount
    if clear_payments: result["payments_deleted"] = conn.execute("DELETE FROM monthly_payments WHERE period_month = ?", (period,)).rowcount
    if clear_bulk and category in ("specialists", "equipment", "bonus"):
        try: result["bulk_" + category + "_cleared"] = conn.execute("UPDATE specialists_equipment_bonus SET " + category + " = 0 WHERE period_month = ?", (period,)).rowcount
        except Exception as e: result["bulk_" + category + "_error"] = str(e)
    if clear_maincenter:
        try: result["maincenter_cleared"] = conn.execute("DELETE FROM main_cost_centers WHERE period_month = ?", (period,)).rowcount
        except Exception as e: result["maincenter_error"] = str(e)
    log_action(conn, "کاربر", "پاک کردن داده‌های ماه", f"{period}: {result}")
    conn.commit()
    conn.close()
    try: recalculate_all(DB_PATH)
    except: pass
    return jsonify({"ok": True, "period": period, "deleted": result})

@app.route("/api/approval-status/deputies")
@auth.login_required
def api_approval_status_deputies():
    period = request.args.get("period") or None
    if period in ("همه", "", "all"): period = None
    rows = approval.get_status_by_deputy(period)
    scope = perms.current_scope()
    if scope: rows = [r for r in rows if r.get('deputy') in scope]
    return jsonify(rows)

@app.route("/api/approval-status/centers")
@auth.login_required
def api_approval_status_centers():
    period = request.args.get("period") or None
    if period in ("همه", "", "all"): period = None
    deputy = request.args.get("deputy") or None
    if deputy in ("همه", ""): deputy = None
    scope = perms.current_scope()
    if scope and deputy and deputy not in scope: return jsonify([])
    rows = approval.get_status_by_center(period, deputy)
    if scope: rows = [r for r in rows if r.get('deputy') in scope]
    return jsonify(rows)

@app.route("/api/approval-log")
@auth.login_required
def api_approval_log():
    """تاریخچهٔ تاییدها، محدود به دامنهٔ دسترسی کاربر."""
    try: limit = int(request.args.get("limit", 100))
    except: limit = 100
    rows = approval.get_recent_approvals(max(1, min(limit, 500)))
    out = [r for r in rows
           if scope.can_see(r.get("deputy") or "", r.get("cost_center") or "")]
    return jsonify(out)

@app.route("/command-center")
@perms.perm_required('command_center')
def command_center_page():
    return render_template("command_center.html")

@app.route("/api/command-center/snapshot")
@perms.perm_required('command_center')
def api_command_center_snapshot():
    try: last = int(request.args.get("last", 0))
    except: last = 0
    return jsonify(cc.get_snapshot(scope=perms.current_scope(), last_event_id=last))

@app.route("/analytics")
@perms.perm_required('command_center')
def analytics_page():
    return render_template("analytics.html")

@app.route("/api/analytics/all")
@perms.perm_required('command_center')
def api_analytics_all():
    return jsonify(analytics.get_analytics(scope=perms.current_scope()))

@app.route("/api/deadline")
@auth.login_required
def api_deadline():
    return jsonify(deadline_mod.get_deadline_status())

@app.route("/personnel")
@auth.login_required
def personnel_page():
    return render_template("personnel.html")

@app.route("/api/personnel/meta")
@auth.login_required
def api_personnel_meta():
    return jsonify({"job_titles": personnel.JOB_TITLES, "contract_types": personnel.CONTRACT_TYPES, "supply_types": personnel.SUPPLY_TYPES, "sima_deputy": personnel.SIMA_DEPUTY})

@app.route("/api/personnel", methods=["GET"])
@auth.login_required
def api_personnel_list():
    deputy, center, search = request.args.get("deputy") or None, request.args.get("center") or None, request.args.get("search") or None
    try: limit = int(request.args.get("limit", 500))
    except: limit = 500
    try: offset = int(request.args.get("offset", 0))
    except: offset = 0
    sc_sql, sc_par = scope.scope_sql("deputy", "center", "supply_type")
    items, total = personnel.list_personnel(deputy, center, search, limit, offset,
                                            sc_sql, sc_par)
    return jsonify({"items": items, "total": total})

@app.route("/api/personnel/enriched", methods=["GET"])
@auth.login_required
def api_personnel_enriched():
    deputy, center, search = request.args.get("deputy") or None, request.args.get("center") or None, request.args.get("search") or None
    job_title, contract_type = request.args.get("job_title") or None, request.args.get("contract_type") or None
    try: limit = int(request.args.get("limit", 1000))
    except: limit = 1000
    try: offset = int(request.args.get("offset", 0))
    except: offset = 0
    sc_sql, sc_par = scope.scope_sql("p.deputy", "p.center", "p.supply_type")
    items, total = personnel.list_personnel_enriched(deputy, center, search, job_title,
                                                     contract_type, limit, offset,
                                                     sc_sql, sc_par)
    return jsonify({"items": items, "total": total})

@app.route("/api/personnel/<int:pid>", methods=["GET"])
@auth.login_required
def api_personnel_get(pid):
    p = personnel.get_personnel(pid)
    if not p: return jsonify({"error": "پیدا نشد"}), 404
    return jsonify(p)

@app.route("/api/personnel", methods=["POST"])
@perms.perm_required('can_upload')
def api_personnel_create():
    data = request.get_json() or {}
    try:
        pid = personnel.create_personnel(data)
        return jsonify({"ok": True, "id": pid})
    except ValueError as e: return jsonify({"error": str(e)}), 400

@app.route("/api/personnel/<int:pid>", methods=["PUT"])
@perms.perm_required('can_upload')
def api_personnel_update(pid):
    personnel.update_personnel(pid, request.get_json() or {})
    return jsonify({"ok": True})

@app.route("/api/personnel/<int:pid>", methods=["DELETE"])
@perms.perm_required('can_upload')
def api_personnel_delete(pid):
    personnel.delete_personnel(pid)
    return jsonify({"ok": True})

@app.route("/api/personnel/<int:pid>/transfers", methods=["GET"])
@auth.login_required
def api_personnel_transfers(pid):
    return jsonify(personnel.list_transfers(pid))

@app.route("/api/personnel/<int:pid>/transfer", methods=["POST"])
@perms.perm_required('can_upload')
def api_personnel_transfer(pid):
    data = request.get_json() or {}
    try:
        tid = personnel.do_transfer(pid, data)
        log_action(get_connection(DB_PATH), "کاربر", "انتقال نیرو", f"personnel #{pid}")
        return jsonify({"ok": True, "id": tid})
    except ValueError as e: return jsonify({"error": str(e)}), 400

@app.route("/api/personnel/<int:pid>/status-changes", methods=["GET"])
@auth.login_required
def api_personnel_status_changes(pid):
    return jsonify(personnel.list_status_changes(pid))

@app.route("/api/personnel/<int:pid>/status-change", methods=["POST"])
@perms.perm_required('can_upload')
def api_personnel_status_change(pid):
    data = request.get_json() or {}
    try:
        sid = personnel.do_status_change(pid, data)
        log_action(get_connection(DB_PATH), "کاربر", "تبدیل وضعیت", f"personnel #{pid}")
        return jsonify({"ok": True, "id": sid})
    except ValueError as e: return jsonify({"error": str(e)}), 400

@app.route("/api/personnel/import", methods=["POST"])
@perms.perm_required('can_upload')
def api_personnel_import():
    if "file" not in request.files: return jsonify({"error": "فایلی ارسال نشده"}), 400
    f = request.files["file"]
    save_path = os.path.join(UPLOAD_DIR, "personnel_" + f.filename)
    f.save(save_path)
    try: result = personnel.import_personnel_excel(save_path)
    except Exception as e: return jsonify({"error": f"خطا: {e}"}), 500
    return jsonify({"ok": True, "result": result})

@app.route("/api/personnel/export")
@auth.login_required
def api_personnel_export():
    buf = personnel.export_personnel()
    return send_file(buf, as_attachment=True, download_name="bank-personnel.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.route("/api/templates/matrix")
@auth.login_required
def api_templates_matrix():
    return jsonify(personnel_templates.get_full_matrix(request.args.get("deputy", "").strip() or None, request.args.get("center", "").strip() or None, request.args.get("supply_type", "").strip() or None))

@app.route("/api/templates/save-matrix", methods=["POST"])
@perms.perm_required('can_upload')
def api_templates_save_matrix():
    saved = personnel_templates.save_matrix((request.get_json() or {}).get("rows") or [])
    return jsonify({"ok": True, "saved": saved})

@app.route("/api/templates/summary")
@auth.login_required
def api_templates_summary():
    return jsonify(personnel_templates.get_summary())

@app.route("/api/templates/details")
@auth.login_required
def api_templates_details():
    deputy, center, supply = request.args.get("deputy", "").strip(), request.args.get("center", "").strip(), request.args.get("supply_type", "").strip()
    if not deputy or not center: return jsonify({"error": "معاونت و مرکز الزامی است"}), 400
    return jsonify(personnel_templates.get_details(deputy, center, supply))

@app.route("/api/templates/save", methods=["POST"])
@perms.perm_required('can_upload')
def api_templates_save():
    data = request.get_json() or {}
    deputy, center, supply, items = (data.get("deputy") or "").strip(), (data.get("center") or "").strip(), (data.get("supply_type") or "").strip(), data.get("items") or []
    if not deputy or not center: return jsonify({"error": "معاونت و مرکز الزامی است"}), 400
    saved = personnel_templates.save_batch(deputy, center, supply, items)
    return jsonify({"ok": True, "saved": saved})

@app.route("/api/templates/import", methods=["POST"])
@perms.perm_required('can_upload')
def api_templates_import():
    if "file" not in request.files: return jsonify({"error": "فایلی ارسال نشده"}), 400
    f = request.files["file"]
    save_path = os.path.join(UPLOAD_DIR, "template_" + f.filename)
    f.save(save_path)
    try: result = personnel_templates.import_excel(save_path)
    except Exception as e: return jsonify({"error": f"خطا: {e}"}), 500
    return jsonify({"ok": True, "result": result})

@app.route("/api/templates/sample")
@auth.login_required
def api_templates_sample():
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from io import BytesIO
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "الگو مصوب"
    ws.sheet_view.rightToLeft = True
    headers = ["معاونت", "شبکه/مرکز", "تامین/پخش", "عنوان شغلی", "تعداد"]
    hf, hfill, ha = Font(bold=True, color="FFFFFF", name="Tahoma"), PatternFill("solid", start_color="1F4A7E"), Alignment(horizontal="center", vertical="center")
    for i, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=i, value=h)
        c.font, c.fill, c.alignment = hf, hfill, ha
    ws.cell(row=2, column=1, value="معاونت سیما"); ws.cell(row=2, column=2, value="شبکه یک"); ws.cell(row=2, column=3, value="تولید"); ws.cell(row=2, column=4, value="کارگردان تلویزیونی"); ws.cell(row=2, column=5, value=5)
    ws.cell(row=3, column=1, value="معاونت سیما"); ws.cell(row=3, column=2, value="شبکه یک"); ws.cell(row=3, column=3, value="تولید"); ws.cell(row=3, column=4, value="صدابردار"); ws.cell(row=3, column=5, value=3)
    ws.cell(row=4, column=1, value="معاونت صدا"); ws.cell(row=4, column=2, value="شبکه ایرانصدا"); ws.cell(row=4, column=3, value=""); ws.cell(row=4, column=4, value="صدابردار"); ws.cell(row=4, column=5, value=2)
    for i, w in enumerate([18, 20, 12, 24, 10], 1): ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="template-sample.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.route("/api/shifts/matrix")
@auth.login_required
def api_shifts_matrix():
    return jsonify(personnel_templates.get_shifts_matrix(request.args.get("deputy", "").strip() or None, request.args.get("center", "").strip() or None, request.args.get("supply_type", "").strip() or None))

@app.route("/api/shifts/save", methods=["POST"])
@perms.perm_required('can_upload')
def api_shifts_save():
    data = request.get_json() or {}
    deputy, center, supply, emp_type = (data.get("deputy") or "").strip(), (data.get("center") or "").strip(), (data.get("supply_type") or "").strip(), (data.get("employment_type") or "").strip()
    amount, count = data.get("amount", 0), data.get("count", 0)
    if not deputy or not center or not emp_type: return jsonify({"error": "پارامتر ناقص"}), 400
    try: amount, count = float(amount or 0), int(count or 0)
    except: return jsonify({"error": "عدد نامعتبر"}), 400
    job_title = (data.get("job_title") or "").strip()
    if not job_title: return jsonify({"error": "عنوان شغلی ناقص"}), 400
    personnel_templates.save_shift(deputy, center, supply, job_title, emp_type, amount, count)
    return jsonify({"ok": True})

master_routes.register(app)
period_routes.register(app)

@app.route("/api/dashboard-export/<kind>")
@auth.login_required
def api_dashboard_export(kind):
    period = request.args.get("period") or None
    if period in ("همه", "", "all"): period = None
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.sheet_view.rightToLeft = True
    header_font = Font(bold=True, color="FFFFFF", name="Tahoma")
    header_fill = PatternFill("solid", start_color="1F4A7E")
    header_align = Alignment(horizontal="center", vertical="center")
    def _hdr(cols):
        for i, h in enumerate(cols, start=1):
            c = ws.cell(row=1, column=i, value=h)
            c.font, c.fill, c.alignment = header_font, header_fill, header_align
    conn = get_connection(DB_PATH)
    try:
        if kind == "by-month":
            ws.title = "روند پرداختی ماهانه"
            if period: rows = conn.execute("SELECT period_month, COALESCE(SUM(amount),0) s, COUNT(*) c FROM monthly_payments WHERE period_month = ? GROUP BY period_month", (period,)).fetchall()
            else: rows = conn.execute("SELECT period_month, COALESCE(SUM(amount),0) s, COUNT(*) c FROM monthly_payments GROUP BY period_month").fetchall()
            _hdr(["دوره", "تعداد پرداخت", "مجموع مبلغ (ریال)"])
            for r in rows: ws.append([r["period_month"], r["c"], float(r["s"] or 0)])
            ws.column_dimensions['A'].width = 18; ws.column_dimensions['B'].width = 15; ws.column_dimensions['C'].width = 22
        elif kind == "wage-dist":
            ws.title = "توزیع دستمزد ماهانه"
            buckets = [("۰ تا ۵۰ میلیون", 0, 50_000_000), ("۵۰ تا ۱۰۰ میلیون", 50_000_000, 100_000_000), ("۱۰۰ تا ۲۰۰ میلیون", 100_000_000, 200_000_000), ("۲۰۰ تا ۳۰۰ میلیون", 200_000_000, 300_000_000), ("۳۰۰ تا ۵۰۰ میلیون", 300_000_000, 500_000_000), ("بیش از ۵۰۰ میلیون", 500_000_000, 10**18)]
            _hdr(["بازه دستمزد", "تعداد نفرات"])
            for label, lo, hi in buckets:
                if period: cnt = conn.execute("SELECT COUNT(*) c FROM records WHERE monthly_wage >= ? AND monthly_wage < ? AND period_month = ?", (lo, hi, period)).fetchone()["c"]
                else: cnt = conn.execute("SELECT COUNT(*) c FROM records WHERE monthly_wage >= ? AND monthly_wage < ?", (lo, hi)).fetchone()["c"]
                ws.append([label, cnt])
            ws.column_dimensions['A'].width = 25; ws.column_dimensions['B'].width = 15
        elif kind == "emp-dist":
            ws.title = "وضعیت اشتغال"
            if period: rows = conn.execute("SELECT COALESCE(NULLIF(employment_status,''),'نامعلوم') s, COUNT(*) c FROM records WHERE period_month = ? GROUP BY s ORDER BY c DESC", (period,)).fetchall()
            else: rows = conn.execute("SELECT COALESCE(NULLIF(employment_status,''),'نامعلوم') s, COUNT(*) c FROM records GROUP BY s ORDER BY c DESC").fetchall()
            _hdr(["وضعیت اشتغال", "تعداد"])
            for r in rows: ws.append([r["s"], r["c"]])
            ws.column_dimensions['A'].width = 25; ws.column_dimensions['B'].width = 15
        elif kind == "places-dist":
            ws.title = "پراکندگی محل خدمتی"
            if period: rows = conn.execute("SELECT cnt, COUNT(*) c FROM (SELECT p.national_code, r.period_month, COUNT(DISTINCT r.cost_center) AS cnt FROM records r JOIN persons p ON p.id = r.person_id WHERE r.cost_center IS NOT NULL AND r.cost_center != '' AND r.period_month = ? GROUP BY p.national_code, r.period_month) GROUP BY cnt ORDER BY cnt", (period,)).fetchall()
            else: rows = conn.execute("SELECT cnt, COUNT(*) c FROM (SELECT p.national_code, r.period_month, COUNT(DISTINCT r.cost_center) AS cnt FROM records r JOIN persons p ON p.id = r.person_id WHERE r.cost_center IS NOT NULL AND r.cost_center != '' GROUP BY p.national_code, r.period_month) GROUP BY cnt ORDER BY cnt").fetchall()
            _hdr(["تعداد محل خدمتی", "تعداد نفرات"])
            for r in rows: ws.append([r["cnt"], r["c"]])
            ws.column_dimensions['A'].width = 18; ws.column_dimensions['B'].width = 15
        elif kind == "warnings":
            ws.title = "ترکیب وضعیت رکوردها"
            where_month = " WHERE r.period_month = ? " if period else " WHERE 1=1 "
            params = [period] if period else []
            w = conn.execute(f"SELECT SUM(CASE WHEN cr.ceiling_status = 'حذف شود' AND COALESCE(cr.manager_approved,0) = 0 THEN 1 ELSE 0 END) AS employed, SUM(CASE WHEN cr.six_month_ceiling < 0 AND COALESCE(cr.manager_approved,0) = 0 THEN 1 ELSE 0 END) AS orange_cnt, SUM(CASE WHEN cr.six_month_ceiling >= 0 AND cr.ceiling_status NOT IN ('', 'حذف شود') AND COALESCE(cr.manager_approved,0) = 0 AND r.monthly_wage > CAST(cr.ceiling_status AS REAL) THEN 1 ELSE 0 END) AS yellow_cnt, SUM(CASE WHEN COALESCE(cr.manager_approved,0) = 1 THEN 1 ELSE 0 END) AS approved_cnt, SUM(CASE WHEN cr.ceiling_status NOT IN ('', 'حذف شود') AND COALESCE(cr.manager_approved,0) = 0 AND (cr.six_month_ceiling IS NULL OR cr.six_month_ceiling >= 0) AND r.monthly_wage <= CAST(cr.ceiling_status AS REAL) THEN 1 ELSE 0 END) AS ok_cnt FROM records r LEFT JOIN calculated_results cr ON cr.record_id = r.id {where_month}", params).fetchone()
            _hdr(["وضعیت", "تعداد"])
            ws.append(["سالم", w["ok_cnt"] or 0]); ws.append(["تأییدشده", w["approved_cnt"] or 0]); ws.append(["بالاتر از سقف ماهانه (زرد)", w["yellow_cnt"] or 0]); ws.append(["بالاتر از مجموع پرداختی (نارنجی)", w["orange_cnt"] or 0]); ws.append(["شاغل (قرمز)", w["employed"] or 0])
            ws.column_dimensions['A'].width = 38; ws.column_dimensions['B'].width = 15
        elif kind == "financials":
            ws.title = "جزئیات مالی"
            from collections import defaultdict
            if period: rows = conn.execute("SELECT center_name, supply_type, specialists, equipment, bonus FROM specialists_equipment_bonus WHERE period_month = ?", (period,)).fetchall()
            else: rows = conn.execute("SELECT center_name, supply_type, SUM(specialists) specialists, SUM(equipment) equipment, SUM(bonus) bonus FROM specialists_equipment_bonus GROUP BY center_name, supply_type").fetchall()
            agg = defaultdict(lambda: {"specialists": 0.0, "equipment": 0.0, "bonus": 0.0})
            for r in rows:
                agg[r["center_name"]]["specialists"] += float(r["specialists"] or 0)
                agg[r["center_name"]]["equipment"] += float(r["equipment"] or 0)
                agg[r["center_name"]]["bonus"] += float(r["bonus"] or 0)
            _hdr(["مرکز/شبکه", "کارشناسان (ریال)", "تجهیزات (ریال)", "هدایا (ریال)", "مجموع (ریال)"])
            for center, vals in sorted(agg.items()): ws.append([center, vals["specialists"], vals["equipment"], vals["bonus"], vals["specialists"] + vals["equipment"] + vals["bonus"]])
            ws.column_dimensions['A'].width = 30
            for col in "BCDE": ws.column_dimensions[col].width = 20
        elif kind == "submission":
            ws.title = "وضعیت ارسال"
            all_centers = conn.execute("SELECT DISTINCT center_name, deputy, COALESCE(supply_type, '') AS supply_type FROM centers_structure WHERE center_name IS NOT NULL AND center_name != '' ORDER BY deputy, center_name, supply_type").fetchall()
            _t = "تامین"
            _p = "پخش"
            _u = "تولید"
            _sub_sql = ("SELECT DISTINCT cost_center, "
                        "CASE "
                        "  WHEN contract_subject LIKE ? THEN ? "
                        "  WHEN contract_subject LIKE ? THEN ? "
                        "  WHEN contract_subject LIKE ? THEN ? "
                        "  ELSE '' END AS st "
                        "FROM records WHERE cost_center IS NOT NULL AND cost_center != ''")
            _params = ["%" + _t + "%", _t, "%" + _p + "%", _p, "%" + _u + "%", _u]
            if period:
                _sub_sql += " AND period_month = ?"
                _params.append(period)
            submitted_rows = conn.execute(_sub_sql, _params).fetchall()
            def _nc(s):
                if not s: return ""
                return s.replace("\u200c","").replace("\u00a0","").replace(" ","")
            submitted_pairs = set((_nc(r["cost_center"]), r["st"]) for r in submitted_rows if r["st"])
            submitted_centers = set(_nc(r["cost_center"]) for r in submitted_rows)
            _hdr(["معاونت", "مرکز/شبکه", "تامین/پخش", "وضعیت"])
            for r in all_centers:
                _dep = r["deputy"] or ""
                _cen = r["center_name"]
                _sup = r["supply_type"] or ""
                if _dep == "معاونت سیما" and _sup in (_t, _p, _u):
                    _is_sub = (_nc(_cen), _sup) in submitted_pairs
                else:
                    _is_sub = _nc(_cen) in submitted_centers
                ws.append([_dep, _cen, _sup, "ارسال شده ✅" if _is_sub else "ارسال نشده ❌"])
            ws.column_dimensions['A'].width = 20
            ws.column_dimensions['B'].width = 30
            ws.column_dimensions['C'].width = 15
            ws.column_dimensions['D'].width = 18
        elif kind == "approvals":
            ws.title = "وضعیت تأیید"
            if period: rows = conn.execute("SELECT r.deputy, r.cost_center, COUNT(*) total, SUM(CASE WHEN cr.manager_approved=1 THEN 1 ELSE 0 END) approved FROM records r LEFT JOIN calculated_results cr ON cr.record_id = r.id WHERE r.period_month = ? GROUP BY r.deputy, r.cost_center ORDER BY r.deputy, r.cost_center", (period,)).fetchall()
            else: rows = conn.execute("SELECT r.deputy, r.cost_center, COUNT(*) total, SUM(CASE WHEN cr.manager_approved=1 THEN 1 ELSE 0 END) approved FROM records r LEFT JOIN calculated_results cr ON cr.record_id = r.id GROUP BY r.deputy, r.cost_center ORDER BY r.deputy, r.cost_center").fetchall()
            _hdr(["معاونت", "مرکز/شبکه", "کل رکورد", "تأییدشده", "در انتظار", "درصد تأیید"])
            for r in rows:
                tot, appr = r["total"] or 0, r["approved"] or 0
                ws.append([r["deputy"] or "", r["cost_center"] or "", tot, appr, tot - appr, f"{round((appr / tot) * 100) if tot else 0}%"])
            ws.column_dimensions['A'].width = 20; ws.column_dimensions['B'].width = 30
            for col in "CDEF": ws.column_dimensions[col].width = 15
        else:
            conn.close()
            return jsonify({"error": "نوع گزارش نامعتبر است"}), 400
    finally:
        try: conn.close()
        except: pass
    names = {"by-month": "روند-پرداختی-ماهانه.xlsx", "wage-dist": "توزیع-دستمزد.xlsx", "emp-dist": "وضعیت-اشتغال.xlsx", "places-dist": "پراکندگی-محل-خدمتی.xlsx", "warnings": "ترکیب-وضعیت-رکوردها.xlsx", "financials": "جزئیات-مالی.xlsx", "submission": "وضعیت-ارسال-اطلاعات.xlsx", "approvals": "وضعیت-تأیید.xlsx"}
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=names.get(kind, "گزارش.xlsx"), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

def open_browser():
    webbrowser.open("http://stm.iriborg")

if __name__ == "__main__":
    init_db(DB_PATH)
    _init_wal = get_connection(DB_PATH)
    _init_wal.execute('PRAGMA journal_mode=WAL')
    _init_wal.close()
    auth.init_users_table()
    perms.init_permissions()
    scope.ensure_schema()
    periods.init_periods_table()
    personnel.init_personnel_tables()
    personnel_templates.init_templates_table()
    approval.init_approval_log()
    result = recalculate_all(DB_PATH, username="سیستم (استارت‌آپ)")
    threading.Timer(1.2, open_browser).start()
    app.run(host="0.0.0.0", port=80, debug=False, threaded=True)