# -*- coding: utf-8 -*-
"""ساخت نسخهٔ آزمایشی جدا: پوشهٔ stm-test

چه کاری می‌کند؟
  ۱) کدِ نسخهٔ تازه (گام ۲: دامنهٔ دسترسی) را از شاخهٔ گیت می‌خواند — بدون تغییر در نسخهٔ اصلی
  ۲) یک کپی کامل از برنامه در پوشهٔ «stm-test» کنار پوشهٔ برنامه می‌سازد
  ۳) یک کپی از پایگاه‌دادهٔ واقعی را داخل همان پوشه می‌گذارد (داده‌های اصلی دست‌نخورده می‌مانند)
  ۴) فایل اجرا با پورت ۸۰۸۱ + سه کاربر آزمایشی آماده می‌سازد

اجرا (از داخل پوشهٔ برنامه):
    python tools\\make_test_install.py

هیچ چیزی در نسخهٔ اصلی و پایگاه‌دادهٔ اصلی تغییر نمی‌کند.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

BRANCH = "arena/2c734307-arena"
# فایل‌هایی که نسخهٔ تازهٔ آن‌ها باید در پوشهٔ آزمایشی نوشته شود
LATEST_FILES = [
    "web/app.py",
    "web/scope.py",
    "web/permissions.py",
    "web/personnel.py",
    "web/analytics.py",
    "web/command_center.py",
    "web/templates/index.html",
    "engine/report_engine.py",
]
IGNORE_NAMES = {
    "data", "__pycache__", ".git", ".venv", "venv", "env", "build", "dist",
    "stm-test", "_data", ".pytest_cache", ".idea", ".vscode", "node_modules",
}
IGNORE_PATTERNS = (".bak", ".pyc", ".pyo", ".log", ".db-wal", ".db-shm")


def say(text=""):
    print(text, flush=True)


def root_dir() -> Path:
    """پوشهٔ برنامه = پوشهٔ والدِ tools"""
    return Path(__file__).resolve().parent.parent


def run_git(root: Path, *args):
    """اجرای گیت بدون شل (فقط subprocess)"""
    try:
        res = subprocess.run(["git", "-C", str(root)] + list(args),
                             capture_output=True)
        return res.returncode, res.stdout, res.stderr
    except FileNotFoundError:
        return 127, b"", b"git not found"


def get_latest_ref(root: Path):
    """آخرین نسخهٔ شاخه را از مخزن گیت می‌گیرد (فقط fetch، بدون تغییر فایل‌ها)"""
    say("→ دریافت آخرین نسخهٔ کد از گیت (بدون تغییر در فایل‌های شما)...")
    code, out, err = run_git(root, "fetch", "origin", BRANCH)
    if code != 0:
        say("  ! gfetch انجام نشد: " + err.decode("utf-8", "ignore")[:300])
    for ref in (f"origin/{BRANCH}", "FETCH_HEAD", "HEAD"):
        code, out, _ = run_git(root, "rev-parse", "--verify", ref + "^{commit}")
        if code == 0:
            sha = out.decode().strip()[:8]
            say(f"  ✔ نسخهٔ {ref} ({sha})")
            return ref
    return None


def git_file(root: Path, ref: str, rel_path: str):
    code, out, err = run_git(root, "show", f"{ref}:{rel_path}")
    if code != 0:
        raise RuntimeError(f"خواندن {rel_path} از {ref} نشد: " + err.decode("utf-8", "ignore"))
    return out


def ignore_func(directory, names):
    out = []
    for n in names:
        if n in IGNORE_NAMES or n.endswith(IGNORE_PATTERNS):
            out.append(n)
    return out


def find_source_db(root: Path):
    candidates = []
    if os.environ.get("LOCALAPPDATA"):
        candidates.append(Path(os.environ["LOCALAPPDATA"]) / "STM" / "data" / "app.db")
    candidates.append(Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")) / "STM" / "data" / "app.db")
    candidates.append(root / "data" / "app.db")
    for c in candidates:
        if c.exists() and c.stat().st_size > 0:
            return c
    return None


RUN_TEST = r'''# -*- coding: utf-8 -*-
"""اجرای نسخهٔ آزمایشی STM — پورت ۸۰۸۱ با پایگاه‌دادهٔ جداگانه

این فایل فقط داخل پوشهٔ stm-test کار می‌کند. داده‌ها در پوشهٔ «_data» همین‌جاست،
پس هیچ ارتباطی با برنامهٔ اصلی و پایگاه‌دادهٔ اصلی ندارد.
"""
import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "_data"
DATA.mkdir(parents=True, exist_ok=True)
# داده‌ها و رمز نشست را داخل همین پوشه نگه می‌داریم
os.environ["LOCALAPPDATA"] = str(DATA)
os.environ["XDG_DATA_HOME"] = str(DATA)
sys.path.insert(0, str(HERE))

# ---------------- انتخاب پورت آزاد ----------------
def free_port(start=8081):
    for p in range(start, start + 15):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return start


PORT = free_port(8081)

from db.database import init_db, get_connection, DEFAULT_DB_PATH
import web.auth as auth
import web.permissions as perms
import web.scope as scope
import web.periods as periods
import web.personnel as personnel
import web.personnel_templates as pt
import web.approval as approval

init_db(DEFAULT_DB_PATH)
_w = get_connection(DEFAULT_DB_PATH)
_w.execute("PRAGMA journal_mode=WAL")
_w.close()
auth.init_users_table()
perms.init_permissions()
scope.ensure_schema()
periods.init_periods_table()
personnel.init_personnel_tables()
pt.init_templates_table()
approval.init_approval_log()

# ---------------- سه کاربر آزمایشی ----------------
PERMS_DEMO = {
    "tab_dashboard": True, "tab_report": True, "dash_charts": True,
    "dash_summary": True, "box_approval": True, "can_approve": True,
    "view_payments": True, "search_person": True, "tab_personnel": True,
    "view_personnel": True, "export_excel": True,
}
PASSWORD = "Test!2345"


def _pick_scope():
    """یک معاونت و یک مرکزِ واقعی که داده دارد انتخاب می‌کند"""
    con = get_connection(DEFAULT_DB_PATH)
    try:
        deputies = [r[0] for r in con.execute(
            "SELECT deputy, COUNT(*) c FROM records WHERE COALESCE(deputy,'')<>'' "
            "GROUP BY deputy ORDER BY c DESC")]
        dep = None
        for want in ("برون‌مرزی", "برون مرزی"):
            for d in deputies:
                if want in d:
                    dep = d
                    break
            if dep:
                break
        if dep is None and deputies:
            dep = deputies[0]
        center = None
        if dep:
            centers = [r[0] for r in con.execute(
                "SELECT cost_center, COUNT(*) c FROM records WHERE deputy=? AND COALESCE(cost_center,'')<>'' "
                "GROUP BY cost_center ORDER BY c DESC", (dep,))]
            for cn in centers:
                if "شبکه" in cn and "فیلم" in cn:
                    center = cn
                    break
            if center is None and centers:
                center = centers[0]
        return dep, center
    finally:
        con.close()


def seed_users():
    dep, center = _pick_scope()
    plans = [
        ("test_deputy", "آزمون ۱ — یک معاونت" + (f" ({dep})" if dep else ""),
         [{"deputy": dep or "*", "center": "*", "supply_type": "*"}] if dep else []),
        ("test_center", "آزمون ۲ — یک مرکز" + (f" ({center})" if center else ""),
         [{"deputy": dep or "*", "center": center or "*", "supply_type": "*"}] if (dep and center) else []),
        ("test_none", "آزمون ۳ — بدون دامنه (باید هیچ‌چیز نبیند)", []),
    ]
    for username, full_name, grants in plans:
        try:
            already = [u for u in auth.list_users() if u["username"] == username]
            if already:
                uid = already[0]["id"]
            else:
                uid = auth.create_user(username, PASSWORD, full_name=full_name,
                                       role="user", permissions=PERMS_DEMO)
            scope.replace_grants(uid, grants, note="test-install")
        except Exception as e:  # noqa: BLE001
            print(f"  ! ساخت کاربر {username} ناموفق: {e}")
    return dep, center


DEP, CENTER = seed_users()

print("=" * 66)
print("  نسخهٔ آزمایشی STM — دامنهٔ دسترسی")
print("=" * 66)
print(f"  آدرس:      http://127.0.0.1:{PORT}")
print(f"  پایگاه‌داده: {DEFAULT_DB_PATH}")
print(f"  معاونت نمونه: {DEP or '-'}   |   مرکز نمونه: {CENTER or '-'}")
print("-" * 66)
print("  کاربر آزمایشی                         رمز")
print(f"  test_deputy  (یک معاونت)              {PASSWORD}")
print(f"  test_center  (یک مرکز)                {PASSWORD}")
print(f"  test_none    (بدون دامنه)             {PASSWORD}")
print("-" * 66)
print("  کاربر اصلی خودتان (admin) هم مثل قبل کار می‌کند.")
print("  برای بستن: همین پنجره را ببندید یا Ctrl+C")
print("=" * 66, flush=True)

threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()

from web.app import app  # noqa: E402  (بعد از تنظیم مسیرها ایمپورت می‌شود)

app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
'''

BAT = """@echo off\r
chcp 65001 >nul\r
title STM - نسخه آزمایشی (پورت 8081)\r
cd /d "%~dp0"\r
python run_test.py\r
if errorlevel 1 pause\r
pause\r
"""

README_TEST = """نسخهٔ آزمایشی STM — دامنهٔ دسترسی
=================================

۱) روی فایل «اجرا-آزمایشی.bat» دوبار کلیک کنید.
   (یا در همین پوشه: python run_test.py)
۲) مرورگر خودکار باز می‌شود: http://127.0.0.1:8081
۳) با کاربران آزمایشی وارد شوید (رمز همه: Test!2345):
     test_deputy  → فقط یک معاونت را می‌بیند
     test_center  → فقط یک مرکز از همان معاونت را می‌بیند
     test_none    → هیچ رکوردی نمی‌بیند (تست بسته‌بودن دسترسی)
     کاربر admin خودتان → همه‌چیز مثل قبل
۴) داده‌های این نسخه کپی است؛ هر تغییری بکنید به برنامهٔ اصلی سرایت نمی‌کند.

پورت ۸۰۸۱ اگر مشغول باشد، خودش ۸۰۸۲ و بعدی را انتخاب می‌کند (در پنجرهٔ سیاه نوشته می‌شود).
"""


def main():
    root = root_dir()
    if not (root / "web" / "app.py").exists():
        say("✗ این فایل باید داخل پوشهٔ «tools» برنامه باشد. اجرا: python tools\\make_test_install.py")
        return 2

    target = root.parent / "stm-test"
    say("=" * 66)
    say("  ساخت نسخهٔ آزمایشی (پوشهٔ stm-test)")
    say("=" * 66)
    say(f"  برنامهٔ اصلی: {root}")
    say(f"  نسخهٔ آزمایشی: {target}")
    say("-" * 66)

    ref = get_latest_ref(root)
    if not ref:
        say("✗ شاخهٔ گیت پیدا نشد. اول این را اجرا کنید:  git fetch origin")
        return 3

    # ---------- ساخت پوشهٔ آزمایشی ----------
    if target.exists():
        if (target / "run_test.py").exists() or (target / ".stm-test").exists():
            say("→ پوشهٔ آزمایشی قبلی پاک و از نو ساخته می‌شود...")
            shutil.rmtree(target)
        else:
            say(f"✗ پوشهٔ «{target}» وجود دارد و مال این برنامه نیست. دستی پاکش کنید.")
            return 4

    say("→ کپی برنامه (بدون داده‌ها و فایل‌های موقت)...")
    shutil.copytree(root, target, ignore=ignore_func)
    (target / ".stm-test").write_text("stm test install", encoding="utf-8")

    # ---------- نوشتن فایل‌های تازه از گیت ----------
    say("→ نوشتن نسخهٔ تازهٔ فایل‌ها (گام ۲)...")
    for rel in LATEST_FILES:
        data = git_file(root, ref, rel)
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        say(f"   ✔ {rel}  ({len(data):,} بایت)")

    # ---------- کپی پایگاه‌داده ----------
    src_db = find_source_db(root)
    db_dest = target / "_data" / "STM" / "data" / "app.db"
    db_dest.parent.mkdir(parents=True, exist_ok=True)
    if src_db:
        say(f"→ کپی پایگاه‌داده: {src_db}")
        shutil.copy2(src_db, db_dest)
        for suffix in ("-wal", "-shm"):
            side = Path(str(src_db) + suffix)
            if side.exists():
                shutil.copy2(side, Path(str(db_dest) + suffix))
        say(f"   ✔ {db_dest}  ({db_dest.stat().st_size / 1048576:.1f} مگابایت)")
    else:
        say("! پایگاه‌دادهٔ اصلی پیدا نشد؛ نسخهٔ آزمایشی با پایگاه‌دادهٔ خالی بالا می‌آید.")
        say("  اگر برنامهٔ اصلی در جای دیگری است، فایل app.db را دستی اینجا بگذارید:")
        say(f"  {db_dest}")

    # ---------- فایل‌های اجرا ----------
    (target / "run_test.py").write_text(RUN_TEST, encoding="utf-8-sig")
    (target / "اجرا-آزمایشی.bat").write_text(BAT, encoding="utf-8-sig")
    (target / "راهنما-آزمایشی.txt").write_text(README_TEST, encoding="utf-8-sig")

    say("-" * 66)
    say("✔ نسخهٔ آزمایشی آماده است.")
    say("")
    say("  ۱) وارد پوشهٔ stm-test شوید")
    say("  ۲) روی «اجرا-آزمایشی.bat» دوبار کلیک کنید")
    say(f"  ۳) آدرس: http://127.0.0.1:8081")
    say("")
    say("  کاربران آزمایشی (رمز همه: Test!2345):")
    say("     test_deputy  → فقط یک معاونت")
    say("     test_center  → فقط یک مرکز")
    say("     test_none    → هیچ‌چیز (تست بسته‌بودن)")
    say("")
    say("  برنامهٔ اصلی و app.db اصلی دست نخورده‌اند.")
    say("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
