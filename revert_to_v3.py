# -*- coding: utf-8 -*-
import shutil, time, sys, os

ts = str(int(time.time()))

REVERTS = [
    (r"D:\moghatee\samane\app\web\app.py",
     r"D:\moghatee\samane\app\web\app.py.bak_1792406583",
     "app.py (قبل از fix_export2)"),
    (r"D:\moghatee\samane\app\engine\report_engine.py",
     r"D:\moghatee\samane\app\engine\report_engine.py.bak_1792406822",
     "report_engine.py (قبل از fix_engine)"),
]

print("=" * 70)
print("مرحله ۱: چک وجود بکاپ‌ها و فایل‌های اصلی")
print("=" * 70)
for target, backup, label in REVERTS:
    ok_t = os.path.exists(target)
    ok_b = os.path.exists(backup)
    print(f"  {label}")
    print(f"    target: {target}  {'OK' if ok_t else 'MISSING'}")
    print(f"    backup: {backup}  {'OK' if ok_b else 'MISSING'}")
    if not ok_t or not ok_b:
        print("ERROR — یکی از فایل‌ها نیست. دست نمی‌زنم.")
        sys.exit(1)

print("\n" + "=" * 70)
print("مرحله ۲: بکاپ از وضعیت فعلی (برای امنیت)")
print("=" * 70)
for target, _, label in REVERTS:
    dst = target + ".before_revert_" + ts
    shutil.copyfile(target, dst)
    print(f"  saved: {dst}")

print("\n" + "=" * 70)
print("مرحله ۳: بازگردانی به نسخه‌های قدیمی")
print("=" * 70)
for target, backup, label in REVERTS:
    shutil.copyfile(backup, target)
    print(f"  reverted: {target}")
    print(f"    ← {backup}")

print("\n" + "=" * 70)
print("مرحله ۴: چک سینتکس")
print("=" * 70)
for target, _, label in REVERTS:
    with open(target, encoding="utf-8") as f:
        src = f.read()
    try:
        compile(src, target, "exec")
        print(f"  OK: {label}")
    except SyntaxError as e:
        print(f"  SYNTAX ERROR in {label}: {e}")
        sys.exit(1)

print("\n" + "=" * 70)
print("مرحله ۵: چک وضعیت پس از بازگردانی")
print("=" * 70)

ENGINE = r"D:\moghatee\samane\app\engine\report_engine.py"
APP = r"D:\moghatee\samane\app\web\app.py"
with open(ENGINE, encoding="utf-8") as f: eng = f.read()
with open(APP, encoding="utf-8") as f: app = f.read()

print(f"  report_engine.py:")
print(f"    _period_for_records موجود است: {'_period_for_records' in eng} (باید False باشد)")
print(f"    build_report اولین خط دارد:")
import re
m = re.search(r'^def build_report\([^)]*\):', eng, re.MULTILINE)
if m:
    nxt = eng.find("\n", m.end())
    print(f"      {eng[m.start():nxt+1].splitlines()[-1] if nxt > 0 else ''}")

print(f"\n  app.py:")
print(f"    _period_for_records موجود است: {'_period_for_records' in app} (باید False باشد)")
print(f"    تعداد decoratorهای api_import_employment: {app.count('def api_import_employment')} (باید ۱ باشد)")

print("\n" + "=" * 70)
print("✅ تمام. حالا restart کن:")
print("=" * 70)
print("  taskkill /F /IM python.exe")
print("  python web\\app.py")