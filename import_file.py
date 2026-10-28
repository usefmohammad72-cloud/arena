"""
ایمپورت مستقیم یک فایل اکسل ورودی از هر مسیری.
Usage:
    python import_file.py <path-to-xlsx> [period]
مثال:
    python import_file.py "C:\\Users\\home\\Desktop\\myfile.xlsx" شهریور
"""
import sys
import os

sys.path.insert(0, '.')
from db.database import init_db
from importer.excel_importer import import_input_sheet
from engine.pricing_engine import recalculate_all

if len(sys.argv) < 2:
    print("Usage: python import_file.py <path-to-xlsx> [period]")
    sys.exit(1)

path = sys.argv[1].strip('"').strip("'")
period = sys.argv[2] if len(sys.argv) > 2 else 'شهریور'

if not os.path.exists(path):
    print(f"!!! فایل پیدا نشد: {path}")
    sys.exit(1)

print(f"در حال ایمپورت از: {path}")
print(f"دوره: {period}")

init_db('data/app.db')
result = import_input_sheet(path, period, 'data/app.db')
print("نتیجهٔ ایمپورت:", result)

calc = recalculate_all('data/app.db')
print("محاسبه:", calc)

# آمار شبکه نمایش و تماشا
import sqlite3
c = sqlite3.connect('data/app.db')
c.row_factory = sqlite3.Row
print("\n--- رکوردهای شبکه نمایش / تماشا بعد از ایمپورت ---")
for r in c.execute("""
    SELECT cost_center, deputy, COUNT(*) AS n
    FROM records
    WHERE period_month = ?
      AND (cost_center LIKE '%شبکه نمایش%' OR cost_center LIKE '%شبکه تماشا%')
    GROUP BY cost_center, deputy
""", (period,)):
    print(f"  {r['n']:4d} | {r['cost_center']!r} | {r['deputy']!r}")
c.close()
print("\n=== پایان ===")