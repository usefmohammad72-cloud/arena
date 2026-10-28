import sqlite3
import os
import sys
import re

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
try:
    from db.database import DEFAULT_DB_PATH
except ImportError:
    print("Could not import database. Make sure to run this in the 'app' folder.")
    sys.exit(1)

FA_DIGITS = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789"
)

def to_en_digits(value):
    if value is None:
        return ""
    return str(value).translate(FA_DIGITS)

def smart_nc(value):
    """کد ملی را از هر فرمتی به ۱۰ رقم انگلیسی تبدیل می‌کند."""
    if value is None:
        return ""

    s = to_en_digits(value).strip()
    if s.lower() in ("nan", "none", ""):
        return ""

    s = s.replace("٫", ".").replace(",", "")

    # اگر اکسل کد ملی را نمایی ذخیره کرده باشد
    if re.search(r'[eE][+-]?\d+', s):
        try:
            s = str(int(float(s)))
        except Exception:
            pass

    # حذف اعشار
    if "." in s:
        s = s.split(".")[0]

    # فقط ارقام
    s = "".join(ch for ch in s if ch.isdigit())

    if not s:
        return ""

    # کد ملی ۱۰ رقمی است
    if len(s) < 10:
        s = s.zfill(10)
    elif len(s) > 10:
        s = s[-10:]

    return s

def norm_period(value):
    """دوره ماه را یکدست می‌کند: 1403/7 و 1403-07 و ۱۴۰۳/۰۷ => 1403/07"""
    if value is None:
        return ""

    s = to_en_digits(value).strip()
    s = s.replace("\\", "/").replace("-", "/").replace(".", "/")
    s = re.sub(r"\s+", "", s)

    m = re.match(r'^(\d{4})/(\d{1,2})(?:/.*)?$', s)
    if m:
        s = f"{m.group(1)}/{int(m.group(2)):02d}"

    return s

print(f"Connecting to database: {DEFAULT_DB_PATH}")
conn = sqlite3.connect(DEFAULT_DB_PATH)
conn.row_factory = sqlite3.Row

# ۱) اصلاح کدهای ملی در جدول اشخاص
persons = conn.execute("SELECT id, national_code FROM persons").fetchall()
fixed_persons = 0
for p in persons:
    c = smart_nc(p["national_code"])
    if c and c != str(p["national_code"]).strip():
        try:
            conn.execute(
                "UPDATE persons SET national_code = ? WHERE id = ?",
                (c, p["id"])
            )
            fixed_persons += 1
        except sqlite3.IntegrityError:
            pass

# ۲) اصلاح کدهای ملی در جدول وضعیت اشتغال
emps = conn.execute("SELECT id, national_code FROM employment_monthly").fetchall()
fixed_emps = 0
for e in emps:
    c = smart_nc(e["national_code"])
    if c and c != str(e["national_code"]).strip():
        try:
            conn.execute(
                "UPDATE employment_monthly SET national_code = ? WHERE id = ?",
                (c, e["id"])
            )
            fixed_emps += 1
        except sqlite3.IntegrityError:
            pass

# ۳) ساخت نقشه کد ملی + دوره => وضعیت اشتغال
em_rows = conn.execute(
    "SELECT national_code, period_month, employment_status FROM employment_monthly"
).fetchall()

em_map = {}
for r in em_rows:
    nc = smart_nc(r["national_code"])
    pm = norm_period(r["period_month"])
    if nc and pm:
        em_map[(nc, pm)] = r["employment_status"]

# ۴) نوشتن وضعیت اشتغال مستقیماً روی رکوردهای جدول اصلی records
rec_rows = conn.execute("""
    SELECT r.id, p.national_code, r.period_month
    FROM records r
    JOIN persons p ON p.id = r.person_id
""").fetchall()

updated = 0
for r in rec_rows:
    nc = smart_nc(r["national_code"])
    pm = norm_period(r["period_month"])
    key = (nc, pm)

    if key in em_map:
        conn.execute(
            "UPDATE records SET employment_status = ? WHERE id = ?",
            (em_map[key], r["id"])
        )
        updated += 1

conn.commit()
conn.close()

print(f"✅ کد ملی اشخاص اصلاح‌شده: {fixed_persons}")
print(f"✅ کد ملی وضعیت اشتغال اصلاح‌شده: {fixed_emps}")
print(f"✅ رکوردهای records به‌روزرسانی‌شده: {updated}")
print("حالا سرور را ری‌استارت کن و صفحه را Ctrl+F5 کن.")