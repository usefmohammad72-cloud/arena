# چطور کد سامانه را به من برسانی

## چرا نمی‌توانم مستقیم به `D:\moghatee\samane\app` وصل شوم؟

من در یک محیط لینوکسیِ ابری اجرا می‌شوم. هیچ ابزاری (bash، فایل، ایجنت) در اختیار من نیست که به درایو `D:` کامپیوتر تو دسترسی پیدا کند — نه از طریق شبکه، نه از طریق VPN، نه با هیچ ترفندی. آن مسیر فقط از داخل ویندوز خودت قابل خواندن است.

پس یک پل لازم است. سه راه داری؛ **راه ۲ بهترین است** چون بعد از آن، خودم کد را می‌خوانم و بقیهٔ کارها (بازبینی دقیق، پاک‌سازی، اصلاح باگ) را انجام می‌دهم.

---

## راه ۰ — بدون اینترنت، بدون دانلود (توصیه‌شده)

دو خطای رایج:

| خطا | علت | راه‌حل |
|---|---|---|
| `D:\moghatee\samane\app : The term ... is not recognized` | مسیر یک **پوشه** است، نه یک دستور. PowerShell نمی‌تواند پوشه را «اجرا» کند | `cd "D:\moghatee\samane\app"` یا `Test-Path` |
| `The argument '.\attach_app.ps1' ... does not exist` | اسکریپت دانلود نشده بود | راه ۰ را استفاده کن، یا اول دانلودش کن |

**گام ۱ — مطمئن شو پوشه وجود دارد** (این خروجی را برای من بفرست):

```powershell
Test-Path "D:\moghatee\samane\app"
Get-ChildItem "D:\moghatee\samane\app" -Name
```

**گام ۲ — این بلوک را کامل کپی و در PowerShell پیست کن** (نیازی به اینترنت و دانلود ندارد):

```powershell
$src   = "D:\moghatee\samane\app"
$dest  = Join-Path ([Environment]::GetFolderPath('Desktop')) "stm-code.zip"
$stage = Join-Path $env:TEMP "stm_stage"
if (-not (Test-Path $src)) { "MISSING: $src" } else {
  Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
  robocopy $src $stage /E /XD venv __pycache__ data logs backups build dist dist_installer .git node_modules /XF *.pyc *.db *.exe *.zip *.key *.log *.bak /NFL /NDL /NP /NJH /NJS | Out-Null
  Compress-Archive -Path "$stage\*" -DestinationPath $dest -Force
  (Get-ChildItem $stage -Recurse -File | Measure-Object Length -Sum) | ForEach-Object { "files=$($_.Count)  size=$([math]::Round($_.Sum/1MB,2)) MB" }
  "ZIP -> $dest"
}
```

**گام ۳ — فایل `stm-code.zip` را از دسکتاپ در چت ضمیمه کن.**

---

## راه ۱ — بسته‌بندی و آپلود ZIP در چت (ساده‌ترین)

PowerShell را باز کن و این ۶ خط را یک‌جا پیست کن:

```powershell
$src = "D:\moghatee\samane\app"
$stage = "$env:TEMP\stm_stage"
$out = "$env:USERPROFILE\Desktop\stm-code.zip"
Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
robocopy $src $stage /E /XD venv __pycache__ data logs build dist dist_installer .git node_modules /XF *.pyc *.db *.exe *.zip *.key *.log /NFL /NDL /NP | Out-Null
Compress-Archive -Path "$stage\*" -DestinationPath $out -Force
Write-Host "ZIP ready: $out"
```

بعد فایل `stm-code.zip` را از دسکتاپ در همین گفتگو ضمیمه کن.

**آنچه عمداً کپی نمی‌شود:** `venv/`، `data/` (شامل `app.db` و آپلودها)، لاگ‌ها، بکاپ‌ها، `__pycache__/`، خروجی‌های build و `*.key`. یعنی کد ملی و حقوق کسی جابه‌جا نمی‌شود.

---

## راه ۲ — خودت push کن، من از GitHub برمی‌دارم (بهترین)

اسکریپت آمادهٔ این کار در همین مخزن است:

**<https://github.com/usefmohammad72-cloud/arena/raw/arena/2c734307-arena/tools/attach_app.ps1>**

روی دسکتاپ ذخیره کن، بعد در PowerShell:

```powershell
cd "$env:USERPROFILE\Desktop"
powershell -ExecutionPolicy Bypass -File .\attach_app.ps1
```

این فقط ZIP می‌سازد. اگر بخواهی هم‌زمان به GitHub بفرستد:

```powershell
powershell -ExecutionPolicy Bypass -File .\attach_app.ps1 -Push
```

اسکریپت:
1. وجود `web\app.py`، `engine`، `importer`، `db` را چک می‌کند و می‌گوید کدام‌ها نیستند؛
2. فقط سورس‌ها را کپی می‌کند (لیست حذف‌شده‌ها بالا)؛
3. یک `MANIFEST.txt` می‌سازد تا بفهمیم دقیقاً چه چیزی فرستاده شده؛
4. ZIP را روی دسکتاپ می‌گذارد؛
5. با `-Push`، مخزن را clone می‌کند، فایل‌ها را روی شاخهٔ `arena/2c734307-arena` می‌گذارد، commit و push می‌کند.

موقع push، ویندوز پنجرهٔ ورود GitHub را باز می‌کند؛ همان حساب `usefmohammad72-cloud` را تأیید کن. **رمز یا توکن را هیچ‌وقت در چت ننویس** — لازم نیست.

فایل‌های `README.md`، `.gitignore` و `REVIEW.md` مخزن دست‌نخورده می‌مانند تا بازبینی و تنظیمات فعلی از بین نروند.

بعد از push فقط بنویس «push کردم» — من `git fetch` می‌زنم و کد را می‌بینم.

---

## راه ۳ — مسیر دستی، بدون اسکریپت

```powershell
cd $env:TEMP
git clone --branch arena/2c734307-arena https://github.com/usefmohammad72-cloud/arena.git stm-upload
cd stm-upload
robocopy "D:\moghatee\samane\app\web"      ".\web"      /E /XD venv __pycache__ data /XF *.db *.pyc
robocopy "D:\moghatee\samane\app\engine"   ".\engine"   /E /XD __pycache__ /XF *.pyc
robocopy "D:\moghatee\samane\app\importer" ".\importer" /E /XD __pycache__ /XF *.pyc
robocopy "D:\moghatee\samane\app\db"       ".\db"       /E /XD __pycache__ /XF *.db *.pyc
git add -A
git commit -m "sources: import STM application code"
git push origin arena/2c734307-arena
```

---

## دو نکتهٔ مهم

1. **`data/app.db` را نفرست.** داخلش کد ملی و حقوق واقعی است و این مخزن عمومی (public) است. اگر برای تست به دادهٔ نمونه نیاز دارم، فقط ۵ تا ۱۰ ردیف با کد ملی و مبلغ ساختگی بفرست.
2. **چیزی را پاک نکن.** فایل‌های زائد (`python`، `cd`، `Set-Content`، نسخه‌های `.txt`) را خودم در شاخهٔ کاری حذف می‌کنم تا در مخزن اصلیِ تو تغییری ندهد، مگر اینکه بگویی مستقیم روی `main` کار کنم.
