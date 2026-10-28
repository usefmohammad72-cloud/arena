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

import sys
import json
import argparse
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
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
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
CANDIDATES = [
    "http://127.0.0.1",
    "http://127.0.0.1:80",
    "http://127.0.0.1:5000",
    "http://127.0.0.1:8080",
    "http://127.0.0.1:8000",
]


def detect_url():
    """آدرس سامانهٔ در حال اجرا را خودکار پیدا می‌کند."""
    for url in CANDIDATES:
        try:
            with urllib.request.urlopen(url + "/login", timeout=3) as resp:
                if resp.status == 200:
                    return url
        except Exception:
            continue
    raise SystemExit(
        "[خطا] سامانه در حال اجرا پیدا نشد.\n"
        "       اول سرور را اجرا کنید (python web\\app.py) یا آدرس را بدهید:\n"
        "       python step1_verify.py --url http://127.0.0.1"
    )

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

    base = args.url or detect_url()

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
        # ترجیح می‌دهیم روی رکوردی آزمون کنیم که از قبل تأیید نشده باشد،
        # تا آزمون هیچ تغییری در دادهٔ واقعی ایجاد نکند.
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
