#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
طبیب سامانهٔ STM — تشخیص مشکل «سامانه در حال اجرا پیدا نشد»
===========================================================

این اسکریپت بدون تغییر دادن هیچ چیزی، وضعیت را بررسی می‌کند:

  ۱) پایتون و پوشهٔ پروژه
  ۲) اعمال شدن گام ۱ روی web/app.py
  ۳) میزبان و پورتی که برنامه با آن اجرا می‌شود (از روی کد خودت)
  ۴) آیا آن پورت گوش می‌دهد؟
  ۵) آیا HTTP پاسخ می‌دهد؟ (با و بدون پراکسی سیستم)
  ۶) مسیر دیتابیس و تعداد کاربران/رکوردها
  ۷) پراکسی‌های تنظیم‌شده در محیط ویندوز

اجرا:
    python step1_doctor.py
"""

import os
import re
import sys
import socket
import sqlite3
import pathlib
import urllib.request
import urllib.error

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

OK = "✔"
NO = "✘"
WARN = "⚠"
FOUND = []


def _find_root():
    """ریشهٔ سامانه: نزدیک‌ترین پوشهٔ والد که web/app.py در آن باشد."""
    here = pathlib.Path(__file__).resolve().parent
    for base in (here, here.parent, here.parent.parent):
        if (base / "web" / "app.py").is_file():
            return base
    return here



def say(mark, title, detail=""):
    print(f"  {mark} {title}" + (f"  →  {detail}" if detail else ""))
    if mark == OK:
        FOUND.append(title)


def section(title):
    print("\n" + "─" * 70)
    print(title)
    print("─" * 70)


def main():
    root = _find_root()
    port_from_src = None

    # ---------------------------------------------------------------- ۱
    section("۱) محیط اجرا")
    say(OK if sys.version_info >= (3, 8) else NO, "نسخهٔ پایتون", sys.version.split()[0])
    say(OK, "پوشهٔ پروژه", str(root))
    app_py = root / "web" / "app.py"
    say(OK if app_py.is_file() else NO, "فایل web/app.py",
        "موجود" if app_py.is_file() else "پیدا نشد — آیا در پوشهٔ درست هستید؟")
    if not app_py.is_file():
        return finish()
    src = app_py.read_text(encoding="utf-8", errors="ignore")

    # ---------------------------------------------------------------- ۲
    section("۲) وضعیت گام ۱ (اصلاح دسترسی تأییدکننده)")
    say(NO if "perms_mod." in src else OK, "ارجاع‌های شکستهٔ perms_mod",
        "هنوز وجود دارد" if "perms_mod." in src else "اصلاح شده")
    say(OK if "«یا» معاونتش در دامنه" in src else WARN, "منطق دامنهٔ تأیید",
        "نسخهٔ جدید" if "«یا» معاونتش در دامنه" in src else "نسخهٔ قدیمی («و»)")
    say(OK if "@auth.admin_required\ndef api_clear_month" in src else WARN,
        "قفل ادمین روی «پاک کردن ماه»",
        "فعال" if "@auth.admin_required\ndef api_clear_month" in src else "غیرفعال")
    baks = sorted(root.glob("web/app.py.bak_*"))
    say(OK if baks else WARN, "بکاپ‌های موجود", f"{len(baks)} فایل" if baks else "هیچ")

    # ---------------------------------------------------------------- ۳
    section("۳) میزبان و پورت برنامه")
    m = re.search(r"app\.run\(([^)]*)\)", src)
    host = "(نامشخص)"
    port = 80
    raw_args = ""
    if m:
        raw_args = m.group(1).strip()
        pm = re.search(r"port\s*=\s*(\d+)", raw_args)
        hm = re.search(r"host\s*=\s*['\"]([^'\"]+)", raw_args)
        if pm:
            port = int(pm.group(1))
            port_from_src = port
        if hm:
            host = hm.group(1)
        say(OK, "خط اجرای برنامه", f"app.run({raw_args})")
    else:
        say(NO, "خط app.run پیدا نشد", "برنامه ممکن است پورت پیش‌فرض را استفاده کند")
    say(OK, "میزبان", host)
    say(OK, "پورت", str(port))
    if host == "0.0.0.0":
        print(f"     {WARN} میزبان 0.0.0.0 است؛ یعنی همهٔ شبکهٔ محلی هم می‌توانند وصل شوند.")
    if port == 80:
        print(f"     {WARN} پورت ۸۰ روی ویندوز معمولاً نیاز به دسترسی مدیر دارد؛")
        print("        اگر پنجرهٔ سرور خطای Permission denied داد، همین علت است.")

    # ---------------------------------------------------------------- ۴
    section("۴) آیا پورت گوش می‌دهد؟")
    ports = []
    if port_from_src:
        ports.append(port_from_src)
    ports += [p for p in (80, 5000, 5001, 5050, 8000, 8080, 8081, 8888, 3000)
              if p not in ports]
    listening = []
    for p in ports:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0)
        try:
            s.connect(("127.0.0.1", p))
            listening.append(p)
            say(OK, f"پورت {p} باز است", "سرور روی این پورت اجرا شده")
        except Exception:
            print(f"  ·  پورت {p} بسته است")
        finally:
            s.close()
    if not listening:
        say(NO, "هیچ پورتی از سامانه باز نیست", "سرور اجرا نشده یا هنوز بالا نیامده")

    # ---------------------------------------------------------------- ۵
    section("۵) پاسخ HTTP")
    for p in (listening or [port]):
        url = "http://127.0.0.1" if p == 80 else f"http://127.0.0.1:{p}"
        for label, opener in (
            ("بدون پراکسی", urllib.request.build_opener(urllib.request.ProxyHandler({}))),
            ("با تنظیمات پیش‌فرض", urllib.request.build_opener()),
        ):
            try:
                with opener.open(url + "/login", timeout=5) as resp:
                    ok = resp.status == 200
                    say(OK if ok else NO, f"{url}/login ({label})",
                        f"HTTP {resp.status}")
            except urllib.error.HTTPError as exc:
                say(WARN, f"{url}/login ({label})", f"HTTP {exc.code}")
            except Exception as exc:
                say(NO, f"{url}/login ({label})", str(exc)[:70])

    # ---------------------------------------------------------------- ۶
    section("۶) دیتابیس و داده")
    try:
        sys.path.insert(0, str(root))
        from app_paths import get_db_path  # noqa: E402
        db = pathlib.Path(get_db_path())
        say(OK if db.is_file() else NO, "مسیر دیتابیس", str(db))
        if db.is_file():
            con = sqlite3.connect(str(db))
            con.row_factory = sqlite3.Row
            for table in ("records", "persons", "auth_users", "monthly_payments"):
                try:
                    n = con.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
                    say(OK, f"تعداد {table}", str(n))
                except Exception:
                    say(WARN, f"جدول {table}", "وجود ندارد")
            try:
                rows = con.execute(
                    "SELECT username, role, is_active FROM auth_users ORDER BY id LIMIT 5"
                ).fetchall()
                for r in rows:
                    print(f"       کاربر: {r['username']} | نقش: {r['role']} | "
                          f"فعال: {'بله' if r['is_active'] else 'خیر'}")
            except Exception:
                pass
            con.close()
    except Exception as exc:
        say(WARN, "خواندن مسیر دیتابیس", str(exc)[:70])

    # ---------------------------------------------------------------- ۷
    section("۷) پراکسی‌های محیطی")
    proxy_vars = {k: v for k, v in os.environ.items()
                  if "proxy" in k.lower() and v}
    if proxy_vars:
        for k, v in proxy_vars.items():
            say(WARN, k, v)
        print("     ℹ اگر درخواست‌های محلی از پراکسی رد شوند، آزمون شکست می‌خورد؛")
        print("       step1_verify.py از نسخهٔ جدید پراکسی را نادیده می‌گیرد.")
    else:
        say(OK, "پراکسی محیطی", "تنظیم نشده")

    return finish(port_from_src, listening)


def finish(port=None, listening=None):
    section("نتیجه و قدم بعدی")
    if listening:
        p = listening[0]
        base = "http://127.0.0.1" if p == 80 else f"http://127.0.0.1:{p}"
        print(f"  {OK} سامانه در حال اجراست. آزمون را با این آدرس بزنید:\n")
        print(f"        python step1_verify.py --url {base} --write-test\n")
        return 0
    if port:
        print(f"  {NO} سرور روی پورت {port} پاسخ نمی‌دهد. کارها به ترتیب:")
    else:
        print(f"  {NO} سرور در حال اجرا نیست. کارها به ترتیب:")
    print("""
        ۱) یک پنجرهٔ CMD تازه باز کنید و اجرا کنید:

               cd /d D:\\moghatee\\samane\\app
               run.bat

        ۲) در همان پنجره منتظر این خط بمانید:

               * Running on http://127.0.0.1:...

           اگر این خط نیامد یا خطای Permission denied دیدید، پورت ۸۰ است
           و ویندوز اجازه نمی‌دهد؛ خروجی پنجره را برای من بفرستید.

        ۳) پنجره را باز نگه دارید و در پنجرهٔ دوم آزمون را بزنید.

        ۴) اگر باز هم پیدا نشد، همین خروجی «طبیب» را برای من بفرستید.
    """)
    return 1


if __name__ == "__main__":
    sys.exit(main())
