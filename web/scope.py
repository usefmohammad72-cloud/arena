# -*- coding: utf-8 -*-
"""
web/scope.py — تنها مرجع تصمیم‌گیری «چه کسی چه داده‌ای را می‌بیند»
=================================================================

مدل داده: جدول user_scopes
    هر ردیف یک «مجوز دسترسی» است با سه سطح:
        deputy       معاونت      ('*' = همهٔ معاونت‌ها)
        center       مرکز/شبکه   ('*' = همهٔ مراکز آن معاونت)
        supply_type  نوع تأمین   ('*' = همه | 'تامین' | 'پخش' | 'تولید')

قاعدهٔ تصمیم:
    • ادمین → همه‌چیز.
    • بدون هیچ مجوز → هیچ‌چیز (fail-closed).
    • بین مجوزها «یا» است، داخل هر مجوز «و».

نمونه‌ها:
    ('*', '*', '*')                    → کل سازمان
    ('معاونت برون مرزی', '*', '*')      → کل آن معاونت
    ('معاونت سیما', 'شبکه فیلم', '*')   → فقط شبکه فیلم
    ('معاونت سیما', 'شبکه تهران', 'پخش') → شبکه تهران، فقط پخش
"""

import json
import sqlite3
import sys
from pathlib import Path

from flask import g, session

sys.path.insert(0, str(Path(__file__).parent.parent))
from app_paths import get_db_path  # noqa: E402

WILDCARD = "*"
SUPPLY_TYPES = ["تامین", "پخش", "تولید"]

# کلید تنظیمات برای اینکه مهاجرت فقط یک بار اجرا شود
MIGRATION_KEY = "user_scopes_migrated_v1"


# ------------------------------------------------------------------ اتصال
def _conn():
    con = sqlite3.connect(str(get_db_path()))
    con.row_factory = sqlite3.Row
    return con


# ------------------------------------------------------------------ ساخت جدول
def ensure_schema(conn=None):
    """ساخت جدول user_scopes و مهاجرت یک‌بارهٔ مجوزهای قدیمی."""
    own = conn is None
    con = conn or _conn()
    try:
        con.execute("""
            CREATE TABLE IF NOT EXISTS user_scopes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                deputy      TEXT NOT NULL DEFAULT '*',
                center      TEXT NOT NULL DEFAULT '*',
                supply_type TEXT NOT NULL DEFAULT '*',
                note        TEXT DEFAULT '',
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, deputy, center, supply_type)
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_user_scopes_uid ON user_scopes(user_id)")
        con.commit()

        # آیا مهاجرت قبلاً انجام شده؟
        try:
            row = con.execute(
                "SELECT value FROM settings WHERE key = ?", (MIGRATION_KEY,)
            ).fetchone()
        except sqlite3.OperationalError:
            con.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
            row = None

        if row and str(row["value"]) in ("1", "true", "True"):
            return

        _migrate_legacy(con)
        con.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, '1')",
            (MIGRATION_KEY,),
        )
        con.commit()
    finally:
        if own:
            con.close()


def _migrate_legacy(con):
    """تبدیل allowed_deputies / allowed_centers قدیمی به ردیف‌های user_scopes.

    نکتهٔ مهم برای اینکه چیزی از کار نیفتد:
    کاربری که هیچ محدودیتی برایش ثبت نشده بود (و تا امروز عملاً همه‌چیز را
    می‌دید)، یک مجوز «کل سازمان» می‌گیرد و با یادداشت «مهاجرت» علامت می‌خورد،
    تا مدیر در پنل کاربران ببیند و درستش کند.
    """
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(auth_users)").fetchall()]
    except sqlite3.OperationalError:
        return
    if "permissions" not in cols:
        return

    rows = con.execute(
        "SELECT id, role, permissions, allowed_deputies, allowed_centers FROM auth_users"
    ).fetchall()

    for u in rows:
        uid = u["id"]

        # اگر از قبل مجوزی دارد، دست نزن
        has = con.execute(
            "SELECT COUNT(*) c FROM user_scopes WHERE user_id = ?", (uid,)
        ).fetchone()["c"]
        if has:
            continue

        if u["role"] == "admin":
            con.execute(
                "INSERT OR IGNORE INTO user_scopes (user_id, deputy, center, supply_type, note) "
                "VALUES (?, '*', '*', '*', 'admin')",
                (uid,),
            )
            continue

        try:
            perms = json.loads(u["permissions"] or "{}")
        except Exception:
            perms = {}
        try:
            deputies = json.loads(u["allowed_deputies"] or "[]")
        except Exception:
            deputies = []
        try:
            centers = json.loads(u["allowed_centers"] or "[]")
        except Exception:
            centers = []

        all_dep = bool(perms.get("scope_all_deputies"))
        all_cen = bool(perms.get("scope_all_centers"))

        if all_dep and all_cen:
            con.execute(
                "INSERT OR IGNORE INTO user_scopes (user_id, deputy, center, supply_type, note) "
                "VALUES (?, '*', '*', '*', 'legacy:all')",
                (uid,),
            )
            continue

        added = 0
        for d in deputies or []:
            d = str(d).strip()
            if d:
                con.execute(
                    "INSERT OR IGNORE INTO user_scopes (user_id, deputy, center, supply_type, note) "
                    "VALUES (?, ?, '*', '*', 'legacy:deputy')",
                    (uid, d),
                )
                added += 1

        for c in centers or []:
            c = str(c).strip()
            if not c:
                continue
            dep = ""
            try:
                r = con.execute(
                    "SELECT deputy FROM centers_structure WHERE center_name = ? LIMIT 1",
                    (c,),
                ).fetchone()
                if r:
                    dep = r["deputy"] or ""
            except Exception:
                pass
            con.execute(
                "INSERT OR IGNORE INTO user_scopes (user_id, deputy, center, supply_type, note) "
                "VALUES (?, ?, ?, '*', 'legacy:center')",
                (uid, dep or WILDCARD, c),
            )
            added += 1

        if added == 0:
            # هیچ محدودیتی ثبت نشده بود → برای جلوگیری از قطع دسترسی ناگهانی
            # مجوز «کل سازمان» با یادداشت می‌گیرد تا مدیر بازبینی کند.
            con.execute(
                "INSERT OR IGNORE INTO user_scopes (user_id, deputy, center, supply_type, note) "
                "VALUES (?, '*', '*', '*', 'legacy:unrestricted')",
                (uid,),
            )


# ------------------------------------------------------------------ خواندن مجوزها
def _load_grants(uid):
    con = _conn()
    try:
        return [
            dict(r)
            for r in con.execute(
                "SELECT deputy, center, supply_type, note FROM user_scopes WHERE user_id = ?",
                (uid,),
            ).fetchall()
        ]
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()


def get_grants(uid=None):
    """لیست مجوزهای کاربر.

    None  → کاربر ادمین است (همه‌چیز)
    []    → هیچ مجوزی ندارد (هیچ‌چیز)
    """
    uid = uid if uid is not None else session.get("user_id")
    if not uid:
        return []

    if g is not None and getattr(g, "_scope_cache_uid", None) == uid:
        return g._scope_cache

    if session.get("role") == "admin":
        result = None
    else:
        result = _load_grants(uid)

    try:
        g._scope_cache_uid = uid
        g._scope_cache = result
    except RuntimeError:
        pass
    return result


def invalidate(uid=None):
    """بعد از تغییر مجوزها، کش همین درخواست را پاک می‌کند."""
    try:
        if getattr(g, "_scope_cache_uid", None) == uid or uid is None:
            g._scope_cache_uid = None
            g._scope_cache = None
    except RuntimeError:
        pass


# ------------------------------------------------------------------ سازندهٔ شرط SQL
def scope_sql(deputy_expr="r.deputy", center_expr="r.cost_center",
              supply_expr="r.contract_subject", uid=None):
    """قطعهٔ SQL آمادهٔ چسباندن به WHERE + پارامترها.

    مثال:
        clause, params = scope_sql()
        sql = "SELECT ... FROM records r WHERE 1=1" + clause
    """
    grants = get_grants(uid)
    if grants is None:
        return "", []
    if not grants:
        return " AND 1=0", []

    parts, params = [], []
    for gr in grants:
        conds = []
        if gr["deputy"] != WILDCARD:
            conds.append(f"COALESCE({deputy_expr}, '') = ?")
            params.append(gr["deputy"])
        if gr["center"] != WILDCARD:
            conds.append(f"COALESCE({center_expr}, '') = ?")
            params.append(gr["center"])
        if gr["supply_type"] != WILDCARD:
            conds.append(f"COALESCE({supply_expr}, '') LIKE ?")
            params.append(f"%{gr['supply_type']}%")
        parts.append("(" + " AND ".join(conds) + ")" if conds else "(1 = 1)")

    return " AND (" + " OR ".join(parts) + ")", params


# ------------------------------------------------------------------ مراکز و معاونت‌های مجاز
def visible_deputies(conn=None, uid=None):
    """None = همه | set() = هیچ | مجموعهٔ نام معاونت‌ها"""
    grants = get_grants(uid)
    if grants is None:
        return None
    if not grants:
        return set()
    out = set()
    for gr in grants:
        if gr["deputy"] == WILDCARD:
            own = conn is None
            con = conn or _conn()
            try:
                return {
                    r["deputy"]
                    for r in con.execute(
                        "SELECT deputy FROM deputies_structure WHERE deputy IS NOT NULL"
                    ).fetchall()
                }
            except Exception:
                return None
            finally:
                if own:
                    con.close()
        out.add(gr["deputy"])
    return out


def visible_centers(conn=None, uid=None):
    """None = همه | set() = هیچ | مجموعهٔ نام مراکز مجاز"""
    grants = get_grants(uid)
    if grants is None:
        return None
    if not grants:
        return set()

    own = conn is None
    con = conn or _conn()
    try:
        out = set()
        for gr in grants:
            if gr["center"] != WILDCARD:
                out.add(gr["center"])
                continue
            if gr["deputy"] == WILDCARD:
                return None
            try:
                for r in con.execute(
                    "SELECT center_name FROM centers_structure WHERE deputy = ?",
                    (gr["deputy"],),
                ).fetchall():
                    if r["center_name"]:
                        out.add(r["center_name"])
            except Exception:
                pass
        return out
    finally:
        if own:
            con.close()


def can_see(deputy=None, center=None, supply_type=None, uid=None, empty_center_is_any=False):
    """آیا کاربر این ردیف را می‌بیند؟

    empty_center_is_any=True → ردیفی که مرکز مشخصی ندارد (مثل جدول قیمت در سطح معاونت)
    برای دارندهٔ دسترسی «یک مرکز» هم دیده می‌شود.
    """
    grants = get_grants(uid)
    if grants is None:
        return True
    if not grants:
        return False

    deputy = (deputy or "").strip()
    center = (center or "").strip()
    supply = (supply_type or "").strip()

    for gr in grants:
        if gr["deputy"] != WILDCARD and gr["deputy"] != deputy:
            continue
        if gr["center"] != WILDCARD:
            if gr["center"] != center:
                if not (empty_center_is_any and not center):
                    continue
        if gr["supply_type"] != WILDCARD and gr["supply_type"] not in supply:
            continue
        return True
    return False


def is_restricted(uid=None):
    """آیا کاربر محدود است؟ (برای نمایش هشدار در پنل)"""
    return get_grants(uid) is not None


# ------------------------------------------------------------------ نوشتن مجوزها
def replace_grants(uid, grants, note="panel"):
    """جایگزینی کامل مجوزهای یک کاربر.

    grants: [{"deputy":..., "center":..., "supply_type":...}, ...]
    """
    con = _conn()
    try:
        con.execute("DELETE FROM user_scopes WHERE user_id = ?", (uid,))
        seen = set()
        for gr in grants or []:
            dep = (gr.get("deputy") or WILDCARD).strip() or WILDCARD
            cen = (gr.get("center") or WILDCARD).strip() or WILDCARD
            sup = (gr.get("supply_type") or WILDCARD).strip() or WILDCARD
            key = (dep, cen, sup)
            if key in seen:
                continue
            seen.add(key)
            con.execute(
                "INSERT OR IGNORE INTO user_scopes "
                "(user_id, deputy, center, supply_type, note) VALUES (?,?,?,?,?)",
                (uid, dep, cen, sup, note),
            )
        con.commit()
    finally:
        con.close()


def grants_from_legacy(deputies=None, centers=None, permissions=None):
    """تبدیل انتخاب‌های پنل فعلی (allowed_deputies / allowed_centers) به grant."""
    perms = permissions or {}
    if perms.get("scope_all_deputies") and perms.get("scope_all_centers"):
        return [{"deputy": WILDCARD, "center": WILDCARD, "supply_type": WILDCARD}]

    out = []
    for dep in deputies or []:
        dep = str(dep).strip()
        if dep and dep != "همه":
            out.append({"deputy": dep, "center": WILDCARD, "supply_type": WILDCARD})

    con = _conn()
    try:
        for cen in centers or []:
            cen = str(cen).strip()
            if not cen or cen == "همه":
                continue
            dep = ""
            try:
                row = con.execute(
                    "SELECT deputy FROM centers_structure WHERE center_name = ? LIMIT 1",
                    (cen,),
                ).fetchone()
                if row:
                    dep = row["deputy"] or ""
            except Exception:
                pass
            out.append({"deputy": dep or WILDCARD, "center": cen, "supply_type": WILDCARD})
    finally:
        con.close()
    return out


def list_grants(uid):
    con = _conn()
    try:
        return [
            dict(r)
            for r in con.execute(
                "SELECT deputy, center, supply_type, note FROM user_scopes "
                "WHERE user_id = ? ORDER BY deputy, center, supply_type",
                (uid,),
            ).fetchall()
        ]
    finally:
        con.close()


# ------------------------------------------------------------------ پیش‌نمایش
def preview(uid, conn=None):
    """چند مرکز/رکورد/نفر را می‌بیند؟ برای نمایش در پنل مدیریت."""
    grants = get_grants(uid)
    own = conn is None
    con = conn or _conn()
    try:
        centers = visible_centers(con, uid)
        clause, params = scope_sql("r.deputy", "r.cost_center", "r.contract_subject", uid)

        def one(sql, p):
            try:
                return con.execute(sql, p).fetchone()[0] or 0
            except Exception:
                return 0

        records = one(f"SELECT COUNT(*) FROM records r WHERE 1=1 {clause}", params)
        persons = one(
            f"SELECT COUNT(DISTINCT r.person_id) FROM records r WHERE 1=1 {clause}", params
        )
        periods = [
            r[0]
            for r in con.execute(
                f"SELECT DISTINCT r.period_month FROM records r WHERE 1=1 {clause} "
                "ORDER BY r.period_month DESC LIMIT 3",
                params,
            ).fetchall()
        ]
        return {
            "is_admin": grants is None,
            "centers_count": len(centers) if centers is not None else "همه",
            "records": records,
            "persons": persons,
            "periods": periods,
            "grants": list_grants(uid),
        }
    finally:
        if own:
            con.close()


# ------------------------------------------------------------------ کمک‌های امنیتی
def row_visible(row):
    """برای ردیف‌های dict/Row با کلیدهای deputy/cost_center/centers"""
    if row is None:
        return False
    keys = row.keys() if hasattr(row, "keys") else []
    deputy = row["deputy"] if "deputy" in keys else None
    center = row["cost_center"] if "cost_center" in keys else None
    if center is None and "center" in keys:
        center = row["center"]
    if center is None and "center_name" in keys:
        center = row["center_name"]
    supply = row["supply_type"] if "supply_type" in keys else ""
    return can_see(deputy, center, supply)


def filter_rows(rows, center_key="center", deputy_key=None, supply_key="supply_type"):
    """فیلتر لیستی از dictها بر اساس دامنهٔ کاربر (برای مسیرهای ساده)."""
    grants = get_grants()
    if grants is None:
        return list(rows)
    if not grants:
        return []
    out = []
    for row in rows or []:
        deputy = row.get(deputy_key) if deputy_key else None
        center = row.get(center_key)
        supply = row.get(supply_key) if supply_key else None
        if can_see(deputy, center, supply):
            out.append(row)
    return out
