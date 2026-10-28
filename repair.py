import re
import time

path = r"D:\moghatee\samane\app\web\app.py"

with open(path, "r", encoding="utf-8") as f:
    content = f.read()

backup = path + ".bak_" + str(int(time.time()))
with open(backup, "w", encoding="utf-8") as f:
    f.write(content)
print(f"Backup saved: {backup}")

# پیدا کردن خط خراب: @app.route("/api/import-employment") که اول خط نیست
pattern = r'^([^\n]+?)(@app\.route\("/api/import-employment")'
matches = [m for m in re.finditer(pattern, content, re.MULTILINE) if m.group(1).strip()]

if not matches:
    print("No corruption pattern found.")
    print("File may already be fixed or corruption is different.")
else:
    m = matches[0]
    prefix = m.group(1)
    at_route_start = m.start(2)
    mangled_line_start = m.start()

    print("Corrupted line found at position:", mangled_line_start)
    print("Prefix to remove:", repr(prefix))

    # پیدا کردن decorator تمیزِ قدیمی که قبل از این خط خراب است
    before = content[:mangled_line_start]
    old_decos = list(re.finditer(
        r'^@app\.route\("/api/import-employment"', before, re.MULTILINE
    ))

    if not old_decos:
        print("Could not find OLD decorator above the mangled line.")
        print("Manual repair needed.")
    else:
        delete_start = old_decos[-1].start()
        print("Old decorator at position:", delete_start)

        # حذف از decorator قدیمی تا شروع @app.route در خط خراب + درج نسخه تمیز
        new_content = content[:delete_start] + "\n" + content[at_route_start:]

        try:
            compile(new_content, path, "exec")
            print("Syntax check: PASSED")
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
            print("File repaired and saved.")
        except SyntaxError as e:
            print("Syntax error after repair:", e)
            print("Line", e.lineno, ":", e.text)
            print("Backup saved. Manual repair needed.")