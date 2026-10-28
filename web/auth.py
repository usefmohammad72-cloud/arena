# web/auth.py — احراز هویت چندکاربره + سطح دسترسی — STM v2
import sqlite3, json, sys
from pathlib import Path
from functools import wraps
from flask import session, redirect, url_for, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

sys.path.insert(0, str(Path(__file__).parent.parent))
from app_paths import get_db_path
import web.permissions as perms


DEFAULT_ADMIN_USERNAME = "4044588"
DEFAULT_ADMIN_PASSWORD = "4180261936"
DEFAULT_ADMIN_FULLNAME = "مدیر سامانه"


def _conn():
    c = sqlite3.connect(str(get_db_path()))
    c.row_factory = sqlite3.Row
    return c


def init_users_table():
    con = _conn()
    con.execute("""
        CREATE TABLE IF NOT EXISTS auth_users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name     TEXT DEFAULT '',
            role          TEXT NOT NULL DEFAULT 'user'
                          CHECK(role IN ('admin','user')),
            is_active     INTEGER NOT NULL DEFAULT 1,
            permissions   TEXT DEFAULT '{}',
            allowed_deputies TEXT DEFAULT '[]',
            allowed_centers  TEXT DEFAULT '[]',
            created_at    TEXT DEFAULT (datetime('now')),
            last_login    TEXT
        )
    """)
    row = con.execute("SELECT COUNT(*) c FROM auth_users").fetchone()
    if row["c"] == 0:
        con.execute(
            "INSERT INTO auth_users (username, password_hash, full_name, role) VALUES (?,?,?,?)",
            (DEFAULT_ADMIN_USERNAME,
             generate_password_hash(DEFAULT_ADMIN_PASSWORD),
             DEFAULT_ADMIN_FULLNAME, 'admin')
        )
    con.commit()
    con.close()
    perms.init_permissions()


def authenticate(username, password):
    con = _conn()
    row = con.execute(
        "SELECT * FROM auth_users WHERE username=? AND is_active=1", (username,)
    ).fetchone()
    con.close()
    if row and check_password_hash(row["password_hash"], password):
        return dict(row)
    return None


def touch_last_login(user_id):
    con = _conn()
    con.execute("UPDATE auth_users SET last_login=datetime('now') WHERE id=?", (user_id,))
    con.commit()
    con.close()


def get_user(user_id):
    con = _conn()
    row = con.execute("SELECT * FROM auth_users WHERE id=?", (user_id,)).fetchone()
    con.close()
    return dict(row) if row else None


def list_users():
    con = _conn()
    rows = con.execute("""
        SELECT id, username, full_name, role, is_active,
               permissions, allowed_deputies, allowed_centers,
               created_at, last_login
        FROM auth_users ORDER BY id
    """).fetchall()
    con.close()
    return [dict(r) for r in rows]


def create_user(username, password, full_name="", role="user",
                permissions=None, allowed_deputies=None, allowed_centers=None):
    username = (username or "").strip()
    if not username or not password:
        raise ValueError("نام کاربری و رمز الزامی است")
    if role not in ("admin", "user"):
        role = "user"
    perms_json = json.dumps(permissions or {}, ensure_ascii=False)
    deputies_json = json.dumps(allowed_deputies or [], ensure_ascii=False)
    centers_json = json.dumps(allowed_centers or [], ensure_ascii=False)
    con = _conn()
    try:
        cur = con.execute(
            "INSERT INTO auth_users "
            "(username, password_hash, full_name, role, permissions, allowed_deputies, allowed_centers) "
            "VALUES (?,?,?,?,?,?,?)",
            (username, generate_password_hash(password), full_name or "",
             role, perms_json, deputies_json, centers_json)
        )
        con.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        raise ValueError("این نام کاربری قبلاً وجود دارد")
    finally:
        con.close()


def update_user(user_id, full_name=None, role=None, is_active=None,
                new_password=None, permissions=None,
                allowed_deputies=None, allowed_centers=None):
    fields, params = [], []
    if full_name is not None:
        fields.append("full_name=?"); params.append(full_name)
    if role is not None and role in ("admin", "user"):
        fields.append("role=?"); params.append(role)
    if is_active is not None:
        fields.append("is_active=?"); params.append(1 if is_active else 0)
    if new_password:
        fields.append("password_hash=?"); params.append(generate_password_hash(new_password))
    if permissions is not None:
        fields.append("permissions=?")
        params.append(json.dumps(permissions, ensure_ascii=False))
    if allowed_deputies is not None:
        fields.append("allowed_deputies=?")
        params.append(json.dumps(allowed_deputies, ensure_ascii=False))
    if allowed_centers is not None:
        fields.append("allowed_centers=?")
        params.append(json.dumps(allowed_centers, ensure_ascii=False))
    if not fields:
        return
    params.append(user_id)
    con = _conn()
    con.execute(f"UPDATE auth_users SET {', '.join(fields)} WHERE id=?", params)
    con.commit()
    con.close()


def delete_user(user_id):
    con = _conn()
    row = con.execute("SELECT role FROM auth_users WHERE id=?", (user_id,)).fetchone()
    if not row:
        con.close()
        return
    if row["role"] == "admin":
        n = con.execute(
            "SELECT COUNT(*) c FROM auth_users WHERE role='admin' AND is_active=1"
        ).fetchone()["c"]
        if n <= 1:
            con.close()
            raise ValueError("نمی‌توان آخرین ادمین را حذف کرد")
    con.execute("DELETE FROM auth_users WHERE id=?", (user_id,))
    con.commit()
    con.close()


def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if 'user_id' not in session:
            if request.path.startswith('/api/'):
                return jsonify({'error': 'unauthorized'}), 401
            return redirect(url_for('login', next=request.path))
        return f(*a, **k)
    return w


def admin_required(f):
    @wraps(f)
    def w(*a, **k):
        if 'user_id' not in session:
            if request.path.startswith('/api/'):
                return jsonify({'error': 'unauthorized'}), 401
            return redirect(url_for('login', next=request.path))
        if session.get('role') != 'admin':
            if request.path.startswith('/api/'):
                return jsonify({'error': 'forbidden'}), 403
            return 'دسترسی فقط برای مدیر', 403
        return f(*a, **k)
    return w