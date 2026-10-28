#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
آزمون خودکار گام ۱ — بررسی دسترسی «تأییدکننده»
===============================================

این اسکریپت سامانهٔ در حال اجرا را صدا می‌زند و با ساختن چند کاربر آزمایشی،
درستی مجوزها و دامنهٔ دسترسی را می‌سنجد. در پایان کاربران آزمایشی پاک می‌شوند.

نکتهٔ مهم دربارهٔ ایمنی داده:
  • آزمون‌ها با «لغو تأیید» (approved=false) اجرا می‌شوند، نه تأیید.
    روی رکوردی که تأییدنشده است، این کار هیچ تغییری در داده ایجاد نمی‌کند.
  • اگر بخواهید جریان کامل «تأیید → نشستن در پرداختی» هم آزموده شود،
    با سوئیچ --write-test اجرا کنید؛ در این حالت خودِ اسکریپت در پایان
    همان تأیید را برمی‌گرداند.

اجرا (سرور باید بالا باشد):
    python step1_verify.py
    python step1_verify.py --url http://127.0.0.1:5000
    python step1_verify.py --user 4044588 --pass 4180261936
    python step1_verify.py --write-test
"""

import os
import sys
import re
import json
import shutil
import argparse
import pathlib
import urllib.request
import urllib.parse
import urllib.error
import http.cookiejar

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TEST_USERS = ["_step1_approver", "_step1_reader"]
OK, BAD, SKIP = "✔", "✘", "…"
results = []


# ------------------------------------------------------------------ HTTP
class Client:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        # پراکسی سیستم نادیده گرفته می‌شود؛ وگرنه درخواست به 127.0.0.1
        # ممکن است به پراکسی سازمان فرستاده شود و شکست بخورد.
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(self.jar),
        )

    def _req(self, path, data=None, method=None, form=False):
        url = self.base + path
        body = None
        headers = {}
        if data is not None:
            if form:
                body = urllib.parse.urlencode(data).encode()
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            else:
                body = json.dumps(data).encode()
                headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            url, data=body, headers=headers, method=method or ("POST" if body else "GET")
        )
        try:
            with self.opener.open(req, timeout=40) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except urllib.error.URLError as exc:
            raise SystemExit(f"[خطا] اتصال به {url} برقرار نشد: {exc.reason}")

    def json(self, path, data=None, method=None):
        code, raw = self._req(path, data=data, method=method)
        try:
            return code, json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            return code, None

    def login(self, username, password):
        code, _ = self._req(
            "/login", {"username": username, "password": password}, form=True
        )
        return code


# ------------------------------------------------------------------ گزارش
def record(name, passed, detail=""):
    results.append((name, passed, detail))
    mark = OK if passed else BAD
    print(f"  {mark} {name}" + (f" — {detail}" if detail else ""))


def skip(name, why):
    results.append((name, None, why))
    print(f"  {SKIP} {name} — رد شد: {why}")


def ensure_user(admin, username, password, perms, deputies, centers):
    """کاربر آزمایشی را می‌سازد (اگر از قبل باشد، اول پاکش می‌کند)."""
    code, users = admin.json("/api/users")
    if code == 200 and isinstance(users, list):
        for u in users:
            if u.get("username") == username:
                admin.json(f"/api/users/{u['id']}", method="DELETE")
    code, body = admin.json(
        "/api/users",
        {
            "username": username,
            "password": password,
            "full_name": "کاربر آزمایشی گام ۱",
            "role": "user",
            "permissions": perms,
            "allowed_deputies": deputies,
            "allowed_centers": centers,
        },
    )
    return code == 200


def cleanup_users(admin):
    code, users = admin.json("/api/users")
    if code != 200 or not isinstance(users, list):
        return
    for u in users:
        if u.get("username") in TEST_USERS:
            admin.json(f"/api/users/{u['id']}", method="DELETE")



# ------------------------------------------------------------------ تشخیص آدرس
PORTS = [80, 5000, 5001, 5050, 8000, 8080, 8081, 8888, 3000]


def _port_from_source():
    """پورت و میزبان را از web/app.py خودِ پروژه می‌خواند."""
    try:
        here = pathlib.Path(__file__).resolve().parent
        src = (here / "web" / "app.py").read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"app\.run\(([^)]*)\)", src)
        if not m:
            return None, None
        args = m.group(1)
        port = re.search(r"port\s*=\s*(\d+)", args)
        host = re.search(r"host\s*=\s*['\"]([^'\"]+)", args)
        return (int(port.group(1)) if port else 80,
                host.group(1) if host else None)
    except Exception:
        return None, None


def _probe(url):
    """آیا سامانه روی این آدرس پاسخ می‌دهد؟ (بدون پراکسی)"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url + "/login", timeout=3) as resp:
            return resp.status == 200, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        return exc.code in (200, 302, 401), f"HTTP {exc.code}"
    except Exception as exc:
        return False, str(exc)[:80]


def detect_url(explicit=None):
    if explicit:
        return explicit.rstrip("/")

    tried = []
    src_port, _src_host = _port_from_source()
    ports = []
    if src_port:
        ports.append(src_port)
    ports += [p for p in PORTS if p not in ports]

    for port in ports:
        url = "http://127.0.0.1" if port == 80 else f"http://127.0.0.1:{port}"
        ok, why = _probe(url)
        tried.append((url, ok, why))
        if ok:
            src_note = "  (بر اساس web/app.py)" if (src_port and port == src_port) else ""
            print(f"سامانه پیدا شد: {url}{src_note}")
            return url

    print("\n✘ سامانه روی هیچ‌کدام از این آدرس‌ها پاسخ نداد:")
    for url, ok, why in tried:
        print(f"    {url:32s} {'✔' if ok else '✘'} {why}")
    raise SystemExit(
        "\n[خطا] سرور در حال اجرا نیست.\n"
        "       ۱) پنجرهٔ سرور را باز کنید و اجرا کنید:  run.bat\n"
        "       ۲) منتظر بمانید تا خط «Running on ...» را ببینید، بعد این آزمون را بزنید.\n"
        "       ۳) اگر پورت دیگری استفاده می‌کنید:  python step1_verify.py --url http://127.0.0.1:PORT\n"
        "       ۴) برای تشخیص کامل:  python step1_doctor.py"
    )



def _db_candidates():
    """مسیرهای ممکن فایل دیتابیس، به ترتیب اولویت."""
    out = []
    env_db = os.environ.get("STM_DB")
    if env_db:
        out.append(pathlib.Path(env_db))

    # همان منطقی که app_paths استفاده می‌کند
    try:
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        from app_paths import get_db_path  # noqa: E402
        out.append(pathlib.Path(get_db_path()))
    except Exception:
        pass

    home = pathlib.Path.home()
    for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("APPDATA"),
                 os.environ.get("XDG_DATA_HOME"), str(home / ".local" / "share"),
                 str(home)):
        if base:
            out.append(pathlib.Path(base) / "STM" / "data" / "app.db")

    seen, uniq = set(), []
    for p in out:
        if str(p) not in seen:
            seen.add(str(p))
            uniq.append(p)
    return uniq


def _backup_db():
    """پیش از آزمونِ نوشتن، از فایل دیتابیس یک نسخهٔ پشتیبان می‌گیرد."""
    try:
        tried = _db_candidates()
        db = next((p for p in tried if p.is_file()), None)
        if not db:
            print("  ℹ فایل دیتابیس پیدا نشد؛ بکاپ گرفته نشد. مسیرهای بررسی‌شده:")
            for p in tried[:4]:
                print("      ", p)
            return
        stamp = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = db.with_name(db.name + ".bak_step1verify_" + stamp)
        shutil.copy2(db, dst)
        print(f"  ⛨ بکاپ دیتابیس: {dst}")
    except Exception as exc:
        print(f"  ℹ بکاپ دیتابیس ممکن نشد: {exc}")


# ------------------------------------------------------------------ اصلی
def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--url", default=None,
                    help="آدرس سامانه؛ اگر داده نشود، پورت‌های ۸۰/۵۰۰۰/۸۰۸۰ خودکار بررسی می‌شوند")
    ap.add_argument("--user", default="4044588")
    ap.add_argument("--pass", dest="password", default="4180261936")
    ap.add_argument("--write-test", action="store_true",
                    help="آزمون کامل تأیید و سپس برگرداندن آن")
    args = ap.parse_args()

    base = detect_url(args.url)

    print("=" * 78)
    print("آزمون دسترسی «تأییدکننده» — گام ۱")
    print("سامانه:", base)
    print("=" * 78)

    admin = Client(base)
    if admin.login(args.user, args.password) not in (200, 302):
        print("[خطا] ورود با کاربر ادمین ناموفق بود. نام کاربری/رمز را با --user/--pass بدهید.")
        return 1

    code, me = admin.json("/api/me")
    if code != 200 or not me or me.get("role") != "admin":
        print("[خطا] این حساب ادمین نیست.")
        return 1
    print(f"ورود ادمین موفق: {me.get('full_name')} ({me.get('username')})\n")

    in_scope = None
    was_approved = False

    try:
        # ---------- پیدا کردن یک دوره و یک رکورد ----------
        code, periods = admin.json("/api/period-options")
        period = None
        if code == 200 and isinstance(periods, list) and periods:
            first = periods[0]
            period = first if isinstance(first, str) else (first.get("period") or first.get("value"))
        if not period:
            skip("پیدا کردن دورهٔ داده", "هیچ دوره‌ای ثبت نشده؛ اول یک فایل اکسل ایمپورت کنید")
            return 1

        q = urllib.parse.urlencode({"period": period})
        code, report = admin.json(f"/api/report?{q}")
        rows = (report or {}).get("rows", []) if code == 200 else []
        if not rows:
            skip("پیدا کردن رکورد", f"در دورهٔ {period} رکوردی نیست")
            return 1

        # ردیف‌های گزارش ستون «معاونت» ندارند؛ نگاشت مرکز → معاونت را از ساختار مراکز می‌گیریم.
        code, centers = admin.json("/api/all-centers")
        center_deputy = {}
        if code == 200 and isinstance(centers, list):
            for c in centers:
                center_deputy[(c.get("name") or "").strip()] = (c.get("deputy") or "").strip()

        def row_deputy(r):
            return center_deputy.get((r.get("cost_center") or "").strip(), "")

        # معاونتِ پرتکرار در داده را انتخاب می‌کنیم
        counts = {}
        for r in rows:
            d = row_deputy(r)
            if d:
                counts[d] = counts.get(d, 0) + 1
        if not counts:
            skip("پیدا کردن دامنهٔ آزمون", "هیچ رکوردی به معاونت مشخصی متصل نیست")
            return 1
        deputy = max(counts, key=counts.get)

        candidates = [r for r in rows if row_deputy(r) == deputy]

        # رکوردهایی که از قبل پرداختی ثبت‌شده دارند، برای آزمون «تأیید» مناسب نیستند
        # (ممکن است پرداختی واقعی دست بخورد). فهرست این افراد را می‌گیریم.
        paid_now = set()
        code_pay, pays = admin.json(
            "/api/payments?" + urllib.parse.urlencode({"period": period})
        )
        if code_pay == 200 and isinstance(pays, list):
            paid_now = {str(x.get("national_code")) for x in pays}

        def _safe(r):
            """نه تأییدشده باشد، نه پرداختی ثبت‌شده داشته باشد."""
            return (not r.get("manager_approved")
                    and str(r.get("national_code")) not in paid_now)

        in_scope = next((r for r in candidates if _safe(r)), None)
        if in_scope is None:
            in_scope = next((r for r in candidates if not r.get("manager_approved")), None)
        if in_scope is None and candidates:
            in_scope = candidates[0]
        outside = next((r for r in rows if row_deputy(r) not in ("", deputy)), None)
        if not in_scope:
            skip("پیدا کردن رکورد داخل دامنه", "رکوردی برای این معاونت پیدا نشد")
            return 1

        print(f"دورهٔ آزمون: {period}")
        print(f"دامنهٔ آزمون: معاونت «{deputy}» ({counts[deputy]} رکورد)")
        was_approved = bool(in_scope.get("manager_approved"))
        print(f"رکورد داخل دامنه : id={in_scope['record_id']} | مرکز: {in_scope.get('cost_center')}"
              f" | وضعیت تأیید فعلی: {'تأییدشده' if was_approved else 'تأییدنشده'}")
        if was_approved:
            print("  ⚠ این رکورد از قبل تأیید شده است؛ آزمون در پایان وضعیت قبلی را برمی‌گرداند.")
        if outside:
            print(f"رکورد خارج دامنه: id={outside['record_id']} | معاونت: {row_deputy(outside)}")
        print()

        # ---------- ساخت کاربران آزمایشی ----------
        approver_ok = ensure_user(
            admin, TEST_USERS[0], "Test!2345",
            {"tab_report": True, "can_approve": True}, [deputy], [],
        )
        reader_ok = ensure_user(
            admin, TEST_USERS[1], "Test!2345",
            {"tab_report": True}, [deputy], [],
        )
        if not (approver_ok and reader_ok):
            print("[خطا] ساخت کاربر آزمایشی ممکن نشد.")
            return 1

        approver = Client(base)
        approver.login(TEST_USERS[0], "Test!2345")
        reader = Client(base)
        reader.login(TEST_USERS[1], "Test!2345")

        print("۱) کاربر «تأییدکننده» (فقط معاونت مجاز) — دیگر نباید ۵۰۰ بگیرد")
        code, body = approver.json(
            "/api/toggle-approval",
            {"record_id": in_scope["record_id"], "approved": False},
        )
        record(
            "تأیید رکورد داخل دامنه",
            code == 200,
            f"کد پاسخ {code}" + ("" if code == 200 else f" — {str(body)[:90]}"),
        )

        print("\n۲) همان کاربر روی رکورد معاونت دیگر — باید ۴۰۳ بگیرد")
        if outside:
            code, body = approver.json(
                "/api/toggle-approval",
                {"record_id": outside["record_id"], "approved": False},
            )
            record(
                "رد رکورد خارج از دامنه",
                code == 403,
                f"کد پاسخ {code}" + (f" — {str(body)[:90]}" if code != 403 else ""),
            )
        else:
            skip("رد رکورد خارج از دامنه", "در داده فقط یک معاونت وجود دارد")

        print("\n۳) لغو تأیید گروهی — قبلاً بی‌صدا شکست می‌خورد")
        code, body = approver.json(
            "/api/bulk-unapprove", {"record_ids": [in_scope["record_id"]]}
        )
        positive = code == 200 and isinstance(body, dict) and body.get("unapproved_count", 0) >= 1
        record(
            "لغو تأیید گروهی داخل دامنه",
            positive,
            f"کد پاسخ {code} — {str(body)[:110]}",
        )

        print("\n۴) کاربر بدون مجوز تأیید — باید ۴۰۳ بگیرد")
        code, body = reader.json(
            "/api/toggle-approval",
            {"record_id": in_scope["record_id"], "approved": False},
        )
        record(
            "رد کاربر بدون مجوز can_approve",
            code == 403,
            f"کد پاسخ {code}",
        )

        print("\n۵) پاک کردن دادهٔ ماه توسط کاربر غیرادمین — باید ۴۰۳ بگیرد")
        code, body = approver.json(
            "/api/clear-month", {"period_month": period, "clear_payments": True}
        )
        record(
            "قفل «پاک کردن ماه» برای غیرادمین",
            code == 403,
            f"کد پاسخ {code}",
        )

        # ---------- آزمون کامل (اختیاری) ----------
        if args.write_test:
            _backup_db()
            print("\n۶) آزمون کامل: تأیید → ثبت در پرداختی → برگرداندن")
            code, body = approver.json(
                "/api/toggle-approval",
                {"record_id": in_scope["record_id"], "approved": True},
            )
            approved_ok = code == 200
            code2, pays = admin.json(
                "/api/payments?" + urllib.parse.urlencode({"period": period})
            )
            nc = in_scope.get("national_code")
            found = any(
                str(p.get("national_code")) == str(nc) for p in (pays or [])
            ) if isinstance(pays, list) else False
            record("تأیید رکورد", approved_ok, f"کد پاسخ {code}")
            record("ثبت در پرداختی همان ماه", found, f"کد ملی {nc}")

            code3, _ = approver.json(
                "/api/toggle-approval",
                {"record_id": in_scope["record_id"], "approved": False},
            )
            record("برگرداندن تأیید (پاک‌سازی آزمون)", code3 == 200, f"کد پاسخ {code3}")
        else:
            skip("آزمون کامل تأیید", "با سوئیچ --write-test فعال می‌شود")

    finally:
        # بازگردانی وضعیت تأیید رکورد، اگر از قبل تأییدشده بود
        try:
            if was_approved and in_scope:
                code, _ = admin.json(
                    "/api/toggle-approval",
                    {"record_id": in_scope["record_id"], "approved": True},
                )
                if code == 200:
                    print("\n↺ وضعیت تأیید قبلی رکورد بازگردانده شد.")
        except Exception:
            print("\n[هشدار] بازگردانی وضعیت رکورد ممکن نشد؛ دستی بررسی کنید.")
        cleanup_users(admin)
        print("\nکاربران آزمایشی پاک شدند.")

    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok is True)
    failed = sum(1 for _, ok, _ in results if ok is False)
    skipped = sum(1 for _, ok, _ in results if ok is None)
    print("=" * 78)
    print(f"نتیجه: {passed} موفق، {failed} ناموفق، {skipped} رد‌شده  (از {total})")
    if failed:
        print("❗ دست‌کم یک آزمون شکست خورد. فایل step1_diff.txt را ببینید.")
        return 2
    print("✅ همهٔ آزمون‌های اجراشده موفق بودند.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
