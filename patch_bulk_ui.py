# -*- coding: utf-8 -*-
"""پچ: endpoint تخصیص مرکز ناشناخته + ویرایش دستی + نمایش در UI"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / "web" / "app.py"
MKE = ROOT / "make_index.py"

changed_app = False
changed_mke = False

# ============================================================
# ۱. endpoint برای تخصیص مرکز ناشناخته
# ============================================================
src = APP.read_text(encoding="utf-8")

if "/api/bulk-import/remap" in src:
    print("[skip] endpoint remap از قبل هست")
else:
    anchor = '@app.route("/api/specialists/<int:row_id>", methods=["PUT"])'
    if anchor not in src:
        print("[!!] anchor specialists PUT پیدا نشد")
    else:
        new_ep = '''@app.route("/api/bulk-import/remap", methods=["POST"])
@perms.perm_required('can_edit_specialists')
def api_bulk_import_remap():
    """انتقال مقدار از یک مرکز ناشناخته به یک مرکز واقعی"""
    data = request.get_json() or {}
    source = (data.get("source") or "").strip()
    target = (data.get("target") or "").strip()
    category = (data.get("category") or "").strip()
    amount = data.get("amount", 0)

    if not source or not target or category not in ("specialists", "equipment", "bonus"):
        return jsonify({"error": "پارامترها نامعتبر"}), 400

    try:
        amount = float(amount or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "مبلغ نامعتبر"}), 400

    col_name = {
        "specialists": "specialists",
        "equipment": "equipment",
        "bonus": "bonus",
    }[category]

    conn = get_connection(DB_PATH)

    # حذف رکورد مرکز ناشناخته
    conn.execute("""
        DELETE FROM specialists_equipment_bonus
        WHERE center_name = ? AND (supply_type = '' OR supply_type IS NULL)
    """, (source,))

    # پیدا کردن supply_type مرکز واقعی
    row = conn.execute("""
        SELECT supply_type FROM centers_structure
        WHERE center_name = ? LIMIT 1
    """, (target,)).fetchone()
    supply_type = (row["supply_type"] or "") if row else ""

    # درج یا به‌روز مقدار برای مرکز واقعی
    existing = conn.execute("""
        SELECT id FROM specialists_equipment_bonus
        WHERE center_name = ? AND COALESCE(supply_type,'') = ?
    """, (target, supply_type)).fetchone()

    if existing:
        conn.execute(
            f"UPDATE specialists_equipment_bonus SET {col_name} = ? WHERE id = ?",
            (amount, existing["id"])
        )
    else:
        defaults = {"specialists": 0.0, "equipment": 0.0, "bonus": 0.0}
        defaults[col_name] = amount
        conn.execute("""
            INSERT INTO specialists_equipment_bonus
                (center_name, supply_type, specialists, equipment, bonus)
            VALUES (?, ?, ?, ?, ?)
        """, (target, supply_type,
              defaults["specialists"],
              defaults["equipment"],
              defaults["bonus"]))

    log_action(conn, "کاربر", "تخصیص دستی مرکز",
               f"{source} → {target} ({category})")
    conn.commit()
    conn.close()

    return jsonify({"ok": True})


'''
        src = src.replace(anchor, new_ep + anchor, 1)
        APP.write_text(src, encoding="utf-8", newline="")
        changed_app = True
        print("[ok] endpoint remap اضافه شد")

# ============================================================
# ۲. UI در make_index.py
# ============================================================
mke = MKE.read_text(encoding="utf-8")

# ---- ۲-الف: بلاک HTML برای unmatched ----
if 'id="unmatched-box"' in mke:
    print("[skip] HTML unmatched از قبل هست")
else:
    anchor = '<div class="row">\n            <label>فیلتر معاونت:</label>\n            <select id="sp-deputy-filter" onchange="loadSpecialists()"></select>\n          </div>'
    if anchor not in mke:
        # شاید anchor فرق کنه
        anchor = '<select id="sp-deputy-filter" onchange="loadSpecialists()"></select>'

    if anchor not in mke:
        print("[!!] anchor sp-deputy-filter پیدا نشد")
    else:
        unmatched_html = anchor + '''

          <div id="unmatched-box" style="display:none;margin-top:18px;padding:16px;background:rgba(245,158,11,.06);border:1px solid rgba(245,158,11,.3);border-radius:12px">
            <div style="font-weight:700;font-size:13px;color:#fbbf24;margin-bottom:12px;padding-bottom:10px;border-bottom:1px dashed rgba(245,158,11,.3)">
              ⚠️ مراکز ناشناخته — تخصیص دستی
            </div>
            <p style="margin:0 0 12px;font-size:12px;color:#a1a1aa;line-height:1.7">
              این مراکز در فایل شما هستند ولی در سیستم شناسایی نشدند. برای هر کدام، مرکز صحیح را انتخاب کنید.
            </p>
            <div class="table-wrap" style="max-height:400px">
              <table id="unmatched-table">
                <thead><tr>
                  <th>نام در فایل</th>
                  <th class="num">مبلغ (ریال)</th>
                  <th>مرکز صحیح</th>
                  <th>عملیات</th>
                </tr></thead>
                <tbody></tbody>
              </table>
            </div>
          </div>'''
        mke = mke.replace(anchor, unmatched_html, 1)
        changed_mke = True
        print("[ok] HTML unmatched اضافه شد")

# ---- ۲-ب: اصلاح تابع doBulkImport ----
if 'showUnmatched' not in mke:
    old_func = re.compile(
        r"async function doBulkImport\(category\)\{[\s\S]*?\n\}\n",
        re.MULTILINE
    )
    new_func = '''async function doBulkImport(category){
  var fileInput = document.getElementById('bulk-' + category + '-file');
  var msg = document.getElementById('bulk-' + category + '-msg');

  if (!fileInput.files.length){
    msg.innerHTML = '<span style="color:#fca5a5">فایل را انتخاب کنید.</span>';
    return;
  }

  var fd = new FormData();
  fd.append('file', fileInput.files[0]);

  msg.innerHTML = '<span style="color:#a1a1aa">در حال ایمپورت...</span>';

  try {
    var res = await fetch('/api/bulk-import/' + category, {method: 'POST', body: fd});
    var data = await res.json();

    if (!res.ok){
      msg.innerHTML = '<span style="color:#fca5a5">' + (data.error || 'خطا') + '</span>';
      return;
    }

    var r = data.result;
    var txt = r.centers_count + ' مرکز — درج: ' + r.inserted + '، به‌روز: ' + r.updated;

    if (r.remapped_count > 0){
      txt += ' — تطبیق هوشمند: ' + r.remapped_count;
    }
    if (r.unmatched_count > 0){
      txt += ' — ⚠️ ناشناخته: ' + r.unmatched_count;
    }

    msg.innerHTML = '<span style="color:#6ee7b7">' + txt + '</span>';

    fileInput.value = '';

    loadSpecialists();

    // نمایش مراکز ناشناخته
    if (r.unmatched && r.unmatched.length){
      showUnmatched(r.unmatched, category);
    } else {
      document.getElementById('unmatched-box').style.display = 'none';
    }
  } catch(e){
    msg.innerHTML = '<span style="color:#fca5a5">خطا: ' + e + '</span>';
  }
}

function showUnmatched(items, category){
  var box = document.getElementById('unmatched-box');
  var tbody = document.querySelector('#unmatched-table tbody');
  box.style.display = 'block';

  // پر کردن dropdown مراکز (بعداً با لیست مراکز پر می‌شه)
  tbody.innerHTML = items.map(function(it, idx){
    return '<tr data-idx="' + idx + '">' +
      '<td>' + (it.raw_name || '') + '</td>' +
      '<td class="num">' + fmt(it.amount || 0) + '</td>' +
      '<td><select class="unmatched-target" data-idx="' + idx + '" style="width:100%">' +
        '<option value="">— انتخاب کنید —</option>' +
      '</select></td>' +
      '<td><button class="action" data-apply-idx="' + idx + '">ثبت</button></td>' +
    '</tr>';
  }).join('');

  // پر کردن dropdown‌ها
  loadCenterOptions().then(function(centers){
    document.querySelectorAll('.unmatched-target').forEach(function(sel){
      sel.innerHTML = '<option value="">— انتخاب کنید —</option>' +
        centers.map(function(c){ return '<option value="' + c + '">' + c + '</option>'; }).join('');
    });
  });

  // دکمه‌ها
  document.querySelectorAll('#unmatched-table button[data-apply-idx]').forEach(function(btn){
    btn.addEventListener('click', function(){
      var idx = Number(btn.dataset.applyIdx);
      applyRemap(idx, items, category);
    });
  });
}

var _centerOptionsCache = null;
async function loadCenterOptions(){
  if (_centerOptionsCache) return _centerOptionsCache;
  try {
    var r = await fetch('/api/all-centers');
    var d = await r.json();
    _centerOptionsCache = d.map(function(x){ return x.name; }).sort();
    return _centerOptionsCache;
  } catch(e){
    return [];
  }
}

async function applyRemap(idx, items, category){
  var sel = document.querySelector('.unmatched-target[data-idx="' + idx + '"]');
  var target = sel ? sel.value : '';
  if (!target){
    alert('مرکز صحیح را انتخاب کنید');
    return;
  }
  var it = items[idx];
  var res = await fetch('/api/bulk-import/remap', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      source: it.raw_name,
      target: target,
      amount: it.amount,
      category: category
    })
  });
  var d = await res.json();
  if (res.ok){
    showToast('تخصیص انجام شد', it.raw_name + ' → ' + target, 'ok');
    // حذف سطر
    var tr = document.querySelector('#unmatched-table tr[data-idx="' + idx + '"]');
    if (tr) tr.remove();
    // اگه خالی شد، مخفی کن
    var tbody = document.querySelector('#unmatched-table tbody');
    if (tbody && !tbody.querySelector('tr')){
      document.getElementById('unmatched-box').style.display = 'none';
    }
    loadSpecialists();
  } else {
    alert(d.error || 'خطا');
  }
}
'''
    if old_func.search(mke):
        mke = old_func.sub(new_func + "\n", mke, count=1)
        changed_mke = True
        print("[ok] doBulkImport آپدیت شد + توابع unmatched اضافه شد")
    else:
        print("[!!] تابع doBulkImport پیدا نشد")

# ---- ۲-ج: برگرداندن ویرایش دستی جدول specialists ----
old_row = re.compile(
    r"'<td class=\"num\">'\+fmt\(r\.specialists\|\|0\)\+'</td>' \+[\s\S]{0,200}?'<td class=\"num\">'\+fmt\(r\.bonus\|\|0\)\+'</td>' \+",
    re.MULTILINE
)

new_row = (
    "'<td><input type=\"text\" inputmode=\"numeric\" class=\"thousand-input\" "
    "value=\"'+(r.specialists||0)+'\" data-edit-id=\"'+r.id+'\" data-edit-field=\"specialists\"></td>' +"
    "'<td><input type=\"text\" inputmode=\"numeric\" class=\"thousand-input\" "
    "value=\"'+(r.equipment||0)+'\" data-edit-id=\"'+r.id+'\" data-edit-field=\"equipment\"></td>' +"
    "'<td><input type=\"text\" inputmode=\"numeric\" class=\"thousand-input\" "
    "value=\"'+(r.bonus||0)+'\" data-edit-id=\"'+r.id+'\" data-edit-field=\"bonus\"></td>' +"
)

if 'data-edit-field="specialists"' in mke:
    print("[skip] ویرایش دستی از قبل هست")
elif old_row.search(mke):
    mke = old_row.sub(new_row, mke, count=1)
    changed_mke = True
    print("[ok] ویرایش دستی جدول برگشت")

# ---- ۲-د: event listener برای ذخیره خودکار ----
if "attachSpecialistsEditHandlers" not in mke:
    # در پایان تابع loadSpecialists، بلافاصله بعد از innerHTML
    anchor_load = "  document.querySelectorAll('#specialists-table button[data-save-id]').forEach(function(btn){\n    btn.addEventListener('click', function(){\n      saveSpec(Number(btn.dataset.saveId), btn.dataset.saveField);\n    });\n  });\n}"

    # anchor ساده‌تر: پایان تابع loadSpecialists
    # چک می‌کنیم anchor قدیمی (که حذف شده) یا anchor جدید
    if anchor_load in mke:
        # نگه‌داریم — این anchor قدیمی با تابع saveSpec کار می‌کنه ولی ما تغییر دادیم
        pass

    # جایگزینی کامل تابع loadSpecialists
    old_load = re.compile(
        r"async function loadSpecialists\(\)\{[\s\S]*?\n\}\n",
        re.MULTILINE
    )
    new_load = '''async function loadSpecialists(){
  var filter = document.getElementById('sp-deputy-filter').value;
  var all = await (await fetch('/api/specialists')).json();
  var rows = (filter && filter !== 'همه') ? all.filter(function(r){return r.deputy === filter;}) : all;
  document.querySelector('#specialists-table tbody').innerHTML = rows.map(function(r){
    return '<tr>' +
      '<td>'+(r.deputy||'')+'</td>' +
      '<td>'+r.center_name+'</td>' +
      '<td>'+(r.supply_type||'-')+'</td>' +
      '<td><input type="text" inputmode="numeric" class="thousand-input" value="'+(r.specialists||0)+'" data-edit-id="'+r.id+'" data-edit-field="specialists"></td>' +
      '<td><input type="text" inputmode="numeric" class="thousand-input" value="'+(r.equipment||0)+'" data-edit-id="'+r.id+'" data-edit-field="equipment"></td>' +
      '<td><input type="text" inputmode="numeric" class="thousand-input" value="'+(r.bonus||0)+'" data-edit-id="'+r.id+'" data-edit-field="bonus"></td>' +
    '</tr>';
  }).join('');

  document.querySelectorAll('#specialists-table input[data-edit-id]').forEach(function(inp){
    inp.addEventListener('change', function(){
      var id = Number(inp.dataset.editId);
      var field = inp.dataset.editField;
      var value = unformatNumber(inp.value);
      fetch('/api/specialists/' + id, {
        method: 'PUT',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ field: field, value: value })
      }).then(function(r){
        if (r.ok){
          inp.style.background = 'rgba(16,185,129,.15)';
          setTimeout(function(){ inp.style.background = ''; }, 800);
        } else {
          inp.style.background = 'rgba(239,68,68,.15)';
        }
      });
    });
  });
}
'''
    if old_load.search(mke):
        mke = old_load.sub(new_load, mke, count=1)
        changed_mke = True
        print("[ok] loadSpecialists آپدیت شد + ویرایش دستی")

if changed_mke:
    MKE.write_text(mke, encoding="utf-8", newline="")

print()
print("=" * 50)
print("حالا اینا رو بزن:")
print("  python make_index.py")