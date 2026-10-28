# -*- coding: utf-8 -*-
"""
افزودن دکمه‌های «مدیریت کاربران» و «خروج» به هدر داشبورد.
این اسکریپت فایل make_index.py را پچ می‌کند.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "make_index.py"

src = TARGET.read_text(encoding="utf-8")

# ---------- 1) CSS ----------
css_anchor = "header .sub{color:var(--muted);font-size:12.5px;margin-top:4px}"

if ".header-actions" in src:
    print("[skip] CSS header-actions already present")
elif css_anchor not in src:
    raise SystemExit("[err] CSS anchor not found - make_index.py changed?")
else:
    css_add = css_anchor + """

  /* === STM PATCH: header actions === */
  .header-actions{
    margin-inline-start:auto;
    display:flex;gap:10px;align-items:center;
  }
  .header-actions .hbtn{
    padding:9px 16px;border-radius:10px;
    border:1px solid var(--border);
    background:rgba(255,255,255,.04);
    color:var(--text-soft);
    font-family:inherit;font-size:13px;font-weight:700;
    cursor:pointer;text-decoration:none;
    display:inline-flex;align-items:center;gap:7px;
    transition:all .2s cubic-bezier(.4,0,.2,1);
    white-space:nowrap;
  }
  .header-actions .hbtn:hover{
    background:rgba(47,111,219,.12);
    border-color:var(--blue);
    color:var(--text);
    transform:translateY(-1px);
    box-shadow:0 6px 16px -8px rgba(47,111,219,.6);
  }
  .header-actions .hbtn.gold{
    background:linear-gradient(135deg,#d4b062,#a8863d);
    color:#070d1a;border-color:transparent;
    box-shadow:0 4px 14px -6px rgba(212,176,98,.5);
  }
  .header-actions .hbtn.gold:hover{
    background:linear-gradient(135deg,#e8c877,#d4b062);
    box-shadow:0 8px 20px -6px rgba(212,176,98,.7);
  }
  .header-actions .hbtn.danger{
    color:#fca5a5;
    border-color:rgba(239,68,68,.35);
  }
  .header-actions .hbtn.danger:hover{
    background:rgba(239,68,68,.12);
    border-color:var(--danger);
    color:#fff;
    box-shadow:0 6px 16px -8px rgba(239,68,68,.6);
  }
  .header-actions .user-chip{
    font-size:12px;font-weight:700;
    color:var(--blue-b);
    padding:6px 12px;border-radius:8px;
    background:rgba(47,111,219,.12);
    border:1px solid rgba(47,111,219,.3);
    letter-spacing:.3px;
  }"""
    src = src.replace(css_anchor, css_add, 1)
    print("[ok] CSS added")

# ---------- 2) HTML header ----------
if 'class="header-actions"' in src:
    print("[skip] HTML header-actions already present")
else:
    header_block = (
        '  <div class="header-actions">\n'
        '    <span class="user-chip">{{ session.username }}</span>\n'
        "    {% if session.role == 'admin' %}\n"
        '      <a href="/users" class="hbtn gold">\U0001F465 \u0645\u062F\u06CC\u0631\u06CC\u062A \u06A9\u0627\u0631\u0628\u0631\u0627\u0646</a>\n'
        "    {% endif %}\n"
        '    <a href="/logout" class="hbtn danger">\U0001F6AA \u062E\u0631\u0648\u062C</a>\n'
        "  </div>\n"
        "</header>"
    )
    if "</header>" not in src:
        raise SystemExit("[err] </header> not found")
    src = src.replace("</header>", header_block, 1)
    print("[ok] HTML header added")

TARGET.write_text(src, encoding="utf-8", newline="")
print(f"[done] patched: {TARGET}")