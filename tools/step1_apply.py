#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
گام ۱ — اصلاح دسترسی «تأییدکننده» در سامانهٔ STM
=================================================

این اسکریپت چهار ایراد را در فایل web/app.py اصلاح می‌کند:

  الف) خطای ۵۰۰ در تأیید رکورد برای کاربران غیرادمین
       (نام ماژول «perms_mod» وجود ندارد؛ ماژول با نام «perms» ایمپورت شده است)

  ب) منطق دامنهٔ دسترسی در تأیید، «و» بود به‌جای «یا»؛
       نتیجه: کسی که فقط «معاونت» گرفته بود، هیچ رکوردی نمی‌توانست تأیید کند.
       منطق جدید: رکورد مجاز است اگر «یا» معاونتش در دامنه باشد «یا» مرکزش.
       برای رکوردی که معاونت/مرکز ندارد و کاربر محدود است: رد می‌شود (بسته به‌طور پیش‌فرض).

  ج) در «لغو تأیید گروهی»، ستون‌های deputy و cost_center خوانده نمی‌شدند؛
       بنابراین برای هر کاربر غیرادمین خطا می‌خورد و بی‌صدا نادیده گرفته می‌شد
       (لغو تأیید عملاً کار نمی‌کرد و هیچ پیامی هم نمی‌داد).

  د) بر اساس تصمیم شما: «پاک کردن دادهٔ ماه» فقط برای ادمین مجاز است.

نکات ایمنی:
  • قبل از هر تغییر، از فایل بکاپ گرفته می‌شود:  web/app.py.bak_<تاریخ>
  • فایل «step1_rollback.py» ساخته می‌شود که با یک اجرا همه‌چیز را برمی‌گرداند.
  • diff کامل در فایل «step1_diff.txt» ذخیره و خلاصهٔ آن چاپ می‌شود.
  • این اسکریپت هیچ‌جا فایل دیگری را لمس نمی‌کند و هیچ اتصالی به دیتابیس ندارد.

اجرا:
    python step1_apply.py                 (از پوشهٔ سامانه)
    python step1_apply.py D:\\moghatee\\samane\\app
"""

import os
import sys
import shutil
import difflib
from pathlib import Path
from datetime import datetime

# ------------------------------------------------------------------ خروجی UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ================================================================== یافتن ریشه
def find_app_root(start: Path) -> Path:
    """ریشهٔ سامانه جایی است که web/app.py در آن باشد."""
    for base in (start, start.parent, start.parent.parent):
        if (base / "web" / "app.py").is_file():
            return base
    return start


# ================================================================== متن‌های جدید
NEW_SCOPE_FUNC = '''def _approval_scope_check(row):
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


'''

NEW_BULK_UNAPPROVE = '''@app.route("/api/bulk-unapprove", methods=["POST"])
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


'''


# ================================================================== ابزارها
def backup_file(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = path.with_name(path.name + ".bak_" + stamp)
    shutil.copy2(path, bak)
    return bak


def write_rollback(app_root: Path, bak: Path, target: Path) -> Path:
    rb = app_root / "step1_rollback.py"
    rb.write_text(
        "# -*- coding: utf-8 -*-\n"
        '"""برگرداندن تغییرات گام ۱ — ساختهٔ step1_apply.py"""\n'
        "import shutil, sys\n"
        "from pathlib import Path\n\n"
        f"BAK    = Path(r'{bak}')\n"
        f"TARGET = Path(r'{target}')\n\n"
        "if not BAK.exists():\n"
        "    print('فایل بکاپ پیدا نشد:', BAK)\n"
        "    sys.exit(1)\n\n"
        "shutil.copy2(BAK, TARGET)\n"
        "print('بازگردانی شد:', TARGET)\n"
        "print('سرور را ری‌استارت کنید.')\n",
        encoding="utf-8",
    )
    return rb


def show_diff(old: str, new: str, target_name: str, app_root: Path) -> int:
    diff = list(
        difflib.unified_diff(
            old.splitlines(),
            new.splitlines(),
            fromfile=target_name + " (قبل)",
            tofile=target_name + " (بعد)",
            lineterm="",
            n=2,
        )
    )
    (app_root / "step1_diff.txt").write_text("\n".join(diff), encoding="utf-8")
    print("--- تفاوت‌ها (ذخیره در step1_diff.txt) " + "-" * 30)
    for line in diff[:120]:
        print(line)
    if len(diff) > 120:
        print(f"... و {len(diff) - 120} خط دیگر")
    print("-" * 78)
    return len(diff)


# ================================================================== اصلی
def main() -> int:
    start = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else Path.cwd().resolve()
    if start.is_file():
        start = start.parent
    app_root = find_app_root(start)

    app_py = app_root / "web" / "app.py"
    if not app_py.is_file():
        print("[خطا] فایل web/app.py پیدا نشد.")
        print("       اسکریپت را داخل پوشهٔ سامانه اجرا کنید یا مسیر را بدهید:")
        print(r"       python step1_apply.py D:\moghatee\samane\app")
        return 1

    print("پوشهٔ سامانه:", app_root)
    print("فایل هدف  :", app_py)

    original = app_py.read_text(encoding="utf-8")
    text = original
    applied = []

    # ---------- پیش‌بررسی: آیا از قبل اعمال شده؟ ----------
    if "perms_mod." not in text and "«یا» معاونتش در دامنه" in text:
        print("\n[اطلاع] به نظر می‌رسد گام ۱ از قبل اعمال شده است. کاری انجام نشد.")
        return 0

    # ---------- الف) perms_mod → perms ----------
    n_mod = text.count("perms_mod.")
    if n_mod:
        text = text.replace("perms_mod.", "perms.")
        applied.append(f"الف) {n_mod} ارجاع به «perms_mod» به «perms» اصلاح شد")

    # ---------- ب) منطق دامنه در تأیید ----------
    start_idx = text.find("def _approval_scope_check(row):")
    end_marker = '\n@app.route("/api/bulk-approve"'
    if start_idx == -1:
        print("\n[خطا] تابع _approval_scope_check پیدا نشد. نسخهٔ فایل با انتظار فرق دارد.")
        return 2
    end_idx = text.find(end_marker, start_idx)
    if end_idx == -1:
        print("\n[خطا] انتهای تابع _approval_scope_check پیدا نشد.")
        return 2
    text = text[:start_idx] + NEW_SCOPE_FUNC + text[end_idx + 1:]
    applied.append("ب) منطق دامنهٔ تأیید بازنویسی شد («یا» به‌جای «و»، بسته به‌طور پیش‌فرض)")

    # ---------- ج) لغو تأیید گروهی ----------
    j_start = text.find('@app.route("/api/bulk-unapprove", methods=["POST"])')
    j_marker = '\n@app.route("/api/toggle-approval", methods=["POST"])'
    j_end = text.find(j_marker, j_start) if j_start != -1 else -1
    if j_start == -1 or j_end == -1:
        print("\n[هشدار] تابع api_bulk_unapprove پیدا نشد؛ این بخش رد شد.")
    else:
        text = text[:j_start] + NEW_BULK_UNAPPROVE + text[j_end + 1:]
        applied.append("ج) «لغو تأیید گروهی» اصلاح شد (ستون‌های دامنه + گزارش خطا + لاگ)")

    # ---------- د) پاک کردن ماه فقط ادمین ----------
    if "@perms.perm_required('can_clear_month')\ndef api_clear_month():" in text:
        text = text.replace(
            "@perms.perm_required('can_clear_month')\ndef api_clear_month():",
            "@auth.admin_required\ndef api_clear_month():",
            1,
        )
        applied.append("د) «پاک کردن دادهٔ ماه» فقط برای ادمین شد (تصمیم تأییدشدهٔ شما)")

    if text == original:
        print("\n[اطلاع] هیچ تغییری لازم نبود.")
        return 0

    # ---------- اعتبارسنجی نحوی پیش از نوشتن ----------
    try:
        compile(text, str(app_py), "exec")
    except SyntaxError as exc:
        print("\n[خطا] کد جدید خطای نحوی دارد؛ فایلی نوشته نشد.")
        print("       خط", exc.lineno, ":", exc.msg)
        return 3

    # ---------- بکاپ، نوشتن، diff ----------
    bak = backup_file(app_py)
    print("بکاپ      :", bak.name)

    app_py.write_text(text, encoding="utf-8", newline="")
    print("نوشته شد  :", app_py.name)

    n_diff = show_diff(original, text, "web/app.py", app_root)

    rb = write_rollback(app_root, bak, app_py)

    print("\n" + "=" * 78)
    print("گام ۱ با موفقیت اعمال شد. تغییرات:")
    for line in applied:
        print("  ✔", line)
    print(f"  · {n_diff} خط diff (کامل در step1_diff.txt)")
    print("\nکارهای بعدی:")
    print("  ۱) سرور را ببندید (Ctrl+C) و دوباره اجرا کنید:  python web\\app.py")
    print("  ۲) آزمون خودکار را بزنید:  python step1_verify.py")
    print(f"  ۳) اگر نخواستید، برگرداندن:  python {rb.name}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
