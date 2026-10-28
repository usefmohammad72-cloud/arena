# -*- coding: utf-8 -*-
"""پاک کردن کامل سابقه پرداختی — برای بارگذاری از اول"""
import sqlite3
import os

db_path = os.path.expandvars(r"%LOCALAPPDATA%\STM\data\app.db")

if not os.path.exists(db_path):
    print(f"[!!] دیتابیس پیدا نشد: {db_path}")
    raise SystemExit(1)

print("=" * 60)
print("  دیتابیس:", db_path)
print("=" * 60)

# اتصال با timeout
conn = sqlite3.connect(db_path, timeout=30)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# ============================================================
# ۱. نمایش آمار فعلی
# ============================================================
print("\n[۱] آمار فعلی:")
print("-" * 60)

tables = ["monthly_payments", "approval_log", "calculated_results", "records", "persons"]
for t in tables:
    try:
        cnt = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {cnt} رکورد")
    except sqlite3.OperationalError:
        print(f"  {t}: (جدول وجود نداره)")

# ============================================================
# ۲. تاییدیه
# ============================================================
print()
print("=" * 60)
print("  عملیات:")
print("=" * 60)
print("  • حذف کامل جدول monthly_payments")
print("  • حذف approval_log (سابقه تأیید/رد)")
print("  • صفر کردن manager_approved در calculated_results")
print()
print("  ❌ persons، records، employment_monthly پاک نمی‌شن")
print()

answer = input("آیا مطمئن هستید؟ (بله / no): ").strip().lower()

if answer != "بله" and answer != "yes" and answer != "y":
    print("لغو شد.")
    conn.close()
    raise SystemExit(0)

# ============================================================
# ۳. پاک کردن
# ============================================================
print()
print("[۲] پاک کردن...")
print("-" * 60)

# monthly_payments
try:
    cur.execute("DELETE FROM monthly_payments")
    deleted_payments = cur.rowcount
    print(f"  ✅ monthly_payments: {deleted_payments} رکورد حذف شد")
except sqlite3.OperationalError as e:
    print(f"  ⚠️ monthly_payments: {e}")

# approval_log
try:
    cur.execute("DELETE FROM approval_log")
    deleted_log = cur.rowcount
    print(f"  ✅ approval_log: {deleted_log} رکورد حذف شد")
except sqlite3.OperationalError:
    print(f"  ⏭ approval_log: (جدول وجود نداره)")

# manager_approved = 0
try:
    cur.execute("UPDATE calculated_results SET manager_approved = 0")
    reset_approved = cur.rowcount
    print(f"  ✅ calculated_results: {reset_approved} رکورد manager_approved=0 شد")
except sqlite3.OperationalError as e:
    print(f"  ⚠️ calculated_results: {e}")

# WAL checkpoint برای ذخیره در دیسک
try:
    cur.execute("PRAGMA wal_checkpoint(TRUNCATE)")
except Exception:
    pass

conn.commit()
conn.close()

# ============================================================
# ۴. تأیید نهایی
# ============================================================
print()
print("=" * 60)
print("  ✅ تمام شد")
print("=" * 60)
print()
print("  حالا سرور رو ری‌استارت کن:")
print("    taskkill /F /IM python.exe")
print("    python web\\app.py")
print()
print("  بعد برو /master-control و ماه‌های موردنظر رو باز کن.")
print("  بعد از اطلاعات ورودی، پرداختی ماهانه رو دوباره آپلود کن.")