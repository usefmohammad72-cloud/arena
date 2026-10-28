import re
# -*- coding: utf-8 -*-
"""
ماژول ایمپورت اکسل.
- بارگذاری چندباره برای یک ماه (حذف امن + درج مجدد)
- حل مشکل FOREIGN KEY constraint
- تشخیص هوشمند ستون‌ها (اولین match، نه آخرین)
- محافظت باز بودن دوره (فقط ماه‌های باز توسط مدیر)
"""
import sys
import os
import openpyxl
from openpyxl.utils import column_index_from_string as col_idx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db.database import get_connection, log_action

# ==== STM v2: محافظت باز بودن دوره ====
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from web.periods import is_period_open


INPUT_SHEET_NAME = "ورودی"

COLUMN_MAP = {
    "B":  "first_name",
    "C":  "last_name",
    "D":  "national_code",
    "L":  "has_second_salary",
    "M":  "legal_article",
    "AE": "skill_card_bonus",
    "AG": "monthly_wage",
    "AL": "employer_insurance",
    "AN": "non_continuous_bonus",
    "BA": "program_name_raw",
    "BB": "contract_subject",
    "BD": "cost_center",
}

NUMERIC_FIELDS = {"skill_card_bonus", "monthly_wage", "employer_insurance", "non_continuous_bonus"}

PERSIAN_MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
                  "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]

MONTH_COLUMN_MAP = {
    4: "فروردین", 5: "اردیبهشت", 6: "خرداد", 7: "تیر", 8: "مرداد", 9: "شهریور",
    10: "مهر", 11: "آبان", 12: "آذر", 13: "دی", 14: "بهمن", 15: "اسفند",
}

_DIGIT_MAP = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789"
)

CONTRACT_KEYWORD_MAP = [
    ("تحریریه هفته نامه", "تحریریه هفته نامه"),
    ("هفته نامه", "تحریریه هفته نامه"),
    ("هفته‌نامه", "تحریریه هفته نامه"),
    ("امور مخاطبان سامانه 162", "امور مخاطبان سامانه 162"),
    ("سامانه 162", "امور مخاطبان سامانه 162"),
    ("امور مخاطبان", "امور مخاطبان سامانه 162"),
    ("ستاد معاونت امور استان‌ها", "ستاد معاونت امور استان‌ها"),
    ("ستاد معاونت امور استانها", "ستاد معاونت امور استان‌ها"),
    ("معاونت امور استان", "ستاد معاونت امور استان‌ها"),
    ("نظارت بر محتوای تولیدی اپراتورها", "نظارت بر محتوای تولیدی اپراتورها"),
    ("نظارت بر محتوای تولیدی", "نظارت بر محتوای تولیدی اپراتورها"),
    ("اپراتورها", "نظارت بر محتوای تولیدی اپراتورها"),
    ("ممیزی آثار تولیدی", "ممیزی آثار تولیدی"),
    ("ممیزی آثار", "ممیزی آثار تولیدی"),
    ("ممیزی", "ممیزی آثار تولیدی"),
    ("برنامه های شبکه رادیویی معارف", "برنامه های شبکه رادیویی معارف"),
    ("شبکه رادیویی معارف", "برنامه های شبکه رادیویی معارف"),
    ("رادیویی معارف", "برنامه های شبکه رادیویی معارف"),
    ("پشتیبانی فنی تولید و پخش صدا", "پشتیبانی فنی تولید و پخش صدا"),
    ("پشتیبانی فنی تولید", "پشتیبانی فنی تولید و پخش صدا"),
    ("پشتیبانی فنی", "پشتیبانی فنی تولید و پخش صدا"),
    ("و کانال فراتر", "و کانال فراتر"),
    ("کانال فراتر", "و کانال فراتر"),
    ("شبکه خبر", "شبکه خبر"),
    ("باشگاه خبرنگاران جوان", "باشگاه خبرنگاران جوان"),
    ("باشگاه خبرنگاران", "باشگاه خبرنگاران جوان"),
    ("خبرنگاران جوان", "باشگاه خبرنگاران جوان"),
    ("کارشناسان پاره وقت (تولید و پخش خبر)", "کارشناسان پاره وقت (تولید و پخش خبر)"),
    ("کارشناسان پاره وقت", "کارشناسان پاره وقت (تولید و پخش خبر)"),
    ("پاره وقت", "کارشناسان پاره وقت (تولید و پخش خبر)"),
]
CONTRACT_KEYWORD_MAP.sort(key=lambda x: -len(x[0]))


# ============================================================
# توابع کمکی عمومی
# ============================================================
def _normalize_text(value):
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    v = value.strip()
    v = v.replace("ي", "ی").replace("ك", "ک")
    v = v.replace("\u200c", " ")
    v = " ".join(v.split())
    return v if v else None


def _to_number(value):
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return 0.0
    s = s.translate(_DIGIT_MAP).replace(",", "").replace("،", "").replace(" ", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _to_national_code(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return str(int(value)).zfill(10)
        except Exception:
            return str(value).strip()
    s = str(value).strip().translate(_DIGIT_MAP)
    s = s.replace(".0", "").replace(" ", "")
    if s.isdigit():
        return s.zfill(10)
    return s


# ============================================================
# تشخیص هوشمند ستون‌های فایل وضعیت اشتغال
# ============================================================
def _detect_employment_columns(headers):
    cols = {}
    for i, h in enumerate(headers):
        if h is None:
            continue
        h_str = str(h).strip()
        if not h_str:
            continue
        h_norm = h_str.replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")
        h_low = h_norm.lower()

        # نام خانوادگی: قبل از «نام» چک شود
        if "last_name" not in cols and (
            "نام خانوادگ" in h_norm
            or "نام‌خانوادگ" in h_norm
            or "خانوادگي" in h_norm
            or "خانوادگی" in h_norm
            or "family" in h_low
            or "last" in h_low
        ):
            cols["last_name"] = i
            continue

        # کد ملی (فقط اولین match)
        if "nc" not in cols and (
            "کد ملی" in h_norm
            or "کدملی" in h_norm
            or "کد ملي" in h_norm
            or "national" in h_low
        ):
            cols["nc"] = i
            continue

        # وضعیت اشتغال
        if "status" not in cols and (
            "وضعیت" in h_norm
            or "شاغل" in h_norm
            or "بازنشسته" in h_norm
            or "اشتغال" in h_norm
            or "status" in h_low
        ):
            cols["status"] = i
            continue

        # معاونت / مرکز / محل خدمت
        if "center" not in cols and (
            "معاونت" in h_norm
            or "مرکز" in h_norm
            or "محل خدمت" in h_norm
        ):
            cols["center"] = i
            continue

        # نام (فقط اگه قبلاً «نام خانوادگی» پیدا نشده)
        if "first_name" not in cols and "نام" in h_norm:
            cols["first_name"] = i
            continue

    return cols


def _norm_header_cell(v):
    if v is None: return ""
    s = str(v)
    s = s.replace("ي", "ی").replace("ك", "ک").replace("‌", " ")
    s = " ".join(s.split())
    return s


def _detect_employment_columns_from_cells(cells):
    result = {}
    nc_list = []
    for i, c in enumerate(cells):
        low = c.lower()
        if ("کد" in c and "ملی" in c) or "national" in low:
            nc_list.append(i)
        elif "استخدام" in c or "وضعیت" in c or "اشتغال" in c or "status" in low:
            result.setdefault("status", i)
        elif "خانوادگ" in c or "family" in low or "last" in low:
            result.setdefault("last_name", i)
        elif ("مرکز" in c or "مراکز" in c or "هزینه" in c or "هزينه" in c
              or "cost" in low or "center" in low):
            result.setdefault("center", i)
    for i, c in enumerate(cells):
        if "نام" in c and "خانوادگ" not in c and "استخدام" not in c and "کد" not in c:
            result.setdefault("first_name", i)
            break
    if nc_list:
        exact = [i for i in nc_list if cells[i].strip() == "کد ملی"]
        result["nc"] = exact[0] if exact else nc_list[0]
    return result


def _read_employment_file(ws, max_scan_rows=8):
    for ri in range(1, max_scan_rows + 1):
        try:
            row = next(ws.iter_rows(min_row=ri, max_row=ri, values_only=True))
        except StopIteration:
            break
        cells = [_norm_header_cell(v) for v in row]
        joined = " ".join(cells)
        if "کد" in joined and "ملی" in joined:
            detected = _detect_employment_columns_from_cells(cells)
            if "nc" in detected and "status" in detected:
                return ri + 1, detected
    return 1, {"nc": 2, "status": 3, "first_name": 0, "last_name": 1, "center": 4}

def _load_centers_data(conn):
    rows = conn.execute("""
        SELECT DISTINCT center_name, canonical_name, deputy, supply_type
        FROM centers_structure
    """).fetchall()

    by_name = {}
    by_canonical = {}
    for r in rows:
        cname = _normalize_text(r["center_name"])
        canon = _normalize_text(r["canonical_name"])
        dep = r["deputy"]
        if cname:
            by_name[cname] = dep
        if canon:
            by_canonical.setdefault(canon, []).append((cname, dep))

    sorted_names = sorted(by_name.keys(), key=lambda x: -len(x))
    sorted_canonical = sorted(by_canonical.keys(), key=lambda x: -len(x))

    return {
        "by_name": by_name,
        "by_canonical": by_canonical,
        "sorted_names": sorted_names,
        "sorted_canonical": sorted_canonical,
    }


def _pick_from_candidates(candidates, contract_subject):
    cs = _normalize_text(contract_subject) or ""
    cands_sorted = sorted(candidates, key=lambda x: -len(x[0] or ""))
    for cname, dep in cands_sorted:
        if cname and cname in cs:
            return cname, dep
    return None, None


def _resolve_display_channels(contract_subject, cost_center):
    combined = f"{cost_center or ''} {contract_subject or ''}"
    if "تماشا" in combined:
        return "شبکه تماشا"
    if "شبکه نمایش" in combined or "شبکه های نمایش" in combined:
        return "شبکه نمایش"
    return None


def _find_center_by_contract_keywords(combined):
    for keyword, center_name in CONTRACT_KEYWORD_MAP:
        if keyword in combined:
            return center_name
    return None


def _resolve_center_and_deputy(centers_data, cost_center, contract_subject):
    cc_raw = cost_center
    cc = _normalize_text(cost_center) or ""
    cs = _normalize_text(contract_subject) or ""

    by_name = centers_data["by_name"]
    by_canonical = centers_data["by_canonical"]
    sorted_names = centers_data["sorted_names"]
    sorted_canonical = centers_data["sorted_canonical"]

    # ۱) تطابق دقیق در cost_center
    if cc and cc in by_name:
        if cc in ("شبکه های نمایش", "شبکههای نمایش"):
            resolved = _resolve_display_channels(cs, cc)
            if resolved and resolved in by_name:
                return resolved, by_name[resolved]
        return cc, by_name[cc]

    # ۲) تطابق در canonical_name
    if cc and cc in by_canonical:
        cands = by_canonical[cc]
        if len(cands) == 1:
            return cands[0]
        cname, dep = _pick_from_candidates(cands, cs)
        if cname:
            return cname, dep

    # ۳) CONTRACT_KEYWORD_MAP
    combined = f"{cc} {cs}"
    contract_center = _find_center_by_contract_keywords(combined)
    if contract_center and contract_center in by_name:
        return contract_center, by_name[contract_center]

    # ۴) substring در cost_center
    if cc:
        for name in sorted_names:
            if name in cc:
                return name, by_name[name]
        for name in sorted_names:
            if cc in name:
                return name, by_name[name]

    # ۵) شبکه نمایش/تماشا
    resolved = _resolve_display_channels(cs, cc)
    if resolved and resolved in by_name:
        return resolved, by_name[resolved]

    # ۶) substring در canonical
    if cc:
        for k in sorted_canonical:
            if k in cc or cc in k:
                cands = by_canonical[k]
                if len(cands) == 1:
                    return cands[0]
                cname, dep = _pick_from_candidates(cands, cs)
                if cname:
                    return cname, dep

    # ۷) جستجوی center_name در contract_subject
    if cs:
        for name in sorted_names:
            if name in cs:
                return name, by_name[name]

    # ۸) جستجوی canonical_name در contract_subject
    if cs:
        for k in sorted_canonical:
            if k in cs:
                cands = by_canonical[k]
                if len(cands) == 1:
                    return cands[0]
                cname, dep = _pick_from_candidates(cands, cs)
                if cname:
                    return cname, dep

    return (cc_raw, None)


# ============================================================
# اشتغال ماهانه
# ============================================================
_MONTHS_FA = {
    "فروردین": "01", "اردیبهشت": "02", "خرداد": "03",
    "تیر": "04", "مرداد": "05", "شهریور": "06",
    "مهر": "07", "آبان": "08", "آذر": "09",
    "دی": "10", "بهمن": "11", "اسفند": "12",
}

_FA2EN = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
                        "01234567890123456789")


def _pk_norm(p):
    if p is None:
        return ""
    s = str(p).strip().translate(_FA2EN)
    for name, num in _MONTHS_FA.items():
        s = s.replace(name, num)
    s = s.replace("\\", "/").replace("-", "/").replace(".", "/")
    s = re.sub(r"\s+", "", s)
    m = re.match(r"^(\d{4})/(\d{1,2})(?:/.*)?$", s)
    if m:
        return f"{m.group(1)}/{int(m.group(2)):02d}"
    return s


def _apply_employment_for_month(conn, period_month):
    target = _pk_norm(period_month)

    em_rows = conn.execute("""
        SELECT national_code, period_month, employment_status, main_cost_center
        FROM employment_monthly
    """).fetchall()
    em_map = {}
    for r in em_rows:
        if _pk_norm(r[1]) != target:
            continue
        nc = _to_national_code(r[0])
        if nc:
            em_map[nc] = {"status": r[2], "center": r[3]}

    rec_rows = conn.execute("""
        SELECT r.id, p.national_code, r.period_month
        FROM records r JOIN persons p ON p.id = r.person_id
    """).fetchall()

    updated = 0
    for rec in rec_rows:
        if _pk_norm(rec[2]) != target:
            continue
        nc = _to_national_code(rec[1])
        if not nc or nc not in em_map:
            continue
        m = em_map[nc]
        sets, params = [], []
        if m["status"]:
            sets.append("employment_status = ?")
            params.append(m["status"])
        if m["center"]:
            sets.append("main_cost_center = ?")
            params.append(m["center"])
        if sets:
            params.append(rec[0])
            conn.execute(f"UPDATE records SET {', '.join(sets)} WHERE id = ?", params)
            updated += 1
    return updated

def _safe_delete_records_for_month(conn, period_month):
    old_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM records WHERE period_month = ?", (period_month,)
    )]

    if not old_ids:
        return 0, 0

    qmarks = ",".join("?" * len(old_ids))

    # قطع FK های ماهانه
    try:
        conn.execute(
            f"UPDATE monthly_payments SET record_id = NULL WHERE record_id IN ({qmarks})",
            old_ids
        )
    except Exception:
        pass

    n_calc = conn.execute(
        f"DELETE FROM calculated_results WHERE record_id IN ({qmarks})",
        old_ids
    ).rowcount

    n_rec = conn.execute(
        "DELETE FROM records WHERE period_month = ?", (period_month,)
    ).rowcount

    return n_rec, n_calc


# ============================================================
# ایمپورت ورودی ماهانه
# ============================================================
def import_input_sheet(xlsx_path: str, period_month: str, db_path: str,
                        username: str = "سیستم", max_rows: int = None) -> dict:
    # ==== STM v2: محافظت باز بودن دوره ====
    if not is_period_open(period_month):
        raise ValueError(
            f"دورهٔ «{period_month}» توسط مدیر باز نشده است. "
            f"با مدیر سامانه تماس بگیرید."
        )

    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    # حذف شرط نام شیت — از اولین شیت استفاده می‌شود
    ws = wb[wb.sheetnames[0]]

    col_indexes = {col_idx(c): field for c, field in COLUMN_MAP.items()}
    max_col_needed = max(col_indexes.keys())

    conn = get_connection(db_path)
    centers_data = _load_centers_data(conn)

    old_rec, old_calc = _safe_delete_records_for_month(conn, period_month)

    ok = skipped = unresolved = 0
    errors = []
    unresolved_samples = []

    row_iter = ws.iter_rows(min_row=2, max_row=max_rows,
                            max_col=max_col_needed, values_only=True)
    for row_num, row in enumerate(row_iter, start=2):
        data = {}
        for i, value in enumerate(row, start=1):
            field = col_indexes.get(i)
            if field:
                data[field] = value

        for k in list(data.keys()):
            if k in NUMERIC_FIELDS:
                data[k] = _to_number(data[k])
            elif k == "national_code":
                data[k] = _to_national_code(data[k])
            else:
                data[k] = _normalize_text(data[k])

        nc = data.get("national_code")
        if not nc:
            continue

        original_cost_center = data.get("cost_center")
        contract_subject = data.get("contract_subject")

        resolved_center, deputy = _resolve_center_and_deputy(
            centers_data, original_cost_center, contract_subject
        )
        if not deputy:
            unresolved += 1
            if len(unresolved_samples) < 30:
                unresolved_samples.append(
                    f"ردیف {row_num}: مرکز='{original_cost_center}' | موضوع='{contract_subject}'"
                )

        try:
            existing = conn.execute(
                "SELECT id FROM persons WHERE national_code = ?", (nc,)
            ).fetchone()
            if existing:
                person_id = existing["id"]
                conn.execute(
                    "UPDATE persons SET first_name=COALESCE(?,first_name), last_name=COALESCE(?,last_name) WHERE id=?",
                    (data.get("first_name"), data.get("last_name"), person_id),
                )
            else:
                cur = conn.execute(
                    "INSERT INTO persons (national_code, first_name, last_name) VALUES (?,?,?)",
                    (nc, data.get("first_name"), data.get("last_name")),
                )
                person_id = cur.lastrowid

            conn.execute("""
                INSERT INTO records (
                    person_id, period_month, deputy, cost_center, main_cost_center,
                    legal_article, has_second_salary, employment_status, contract_subject,
                    program_name_raw, program_name_resolved,
                    skill_card_bonus, employer_insurance, non_continuous_bonus,
                    monthly_wage, yearly_paid_total
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                person_id, period_month,
                deputy, resolved_center, None,
                data.get("legal_article"), data.get("has_second_salary"),
                None, contract_subject,
                data.get("program_name_raw"), data.get("program_name_raw"),
                data.get("skill_card_bonus") or 0,
                data.get("employer_insurance") or 0,
                data.get("non_continuous_bonus") or 0,
                data.get("monthly_wage") or 0,
                0,
            ))
            ok += 1
        except Exception as e:
            skipped += 1
            errors.append(f"ردیف {row_num}: {e}")

    emp_applied = _apply_employment_for_month(conn, period_month)

    conn.commit()
    log_action(conn, username, "ایمپورت اکسل",
               f"دورهٔ {period_month}: {ok} رکورد، {unresolved} بدون معاونت، "
               f"{emp_applied} وضعیت اشتغال اعمال شد، "
               f"حذف قبلی: {old_rec} رکورد + {old_calc} محاسبه")
    conn.close()

    return {
        "ok": ok, "skipped": skipped,
        "unresolved_deputy": unresolved,
        "employment_applied": emp_applied,
        "deleted_previous_records": old_rec,
        "deleted_previous_calculations": old_calc,
        "unresolved_samples": unresolved_samples,
        "errors": errors[:50],
    }


# ============================================================
# ایمپورت وضعیت اشتغال
# ============================================================
def import_employment_status(xlsx_path: str, period_month: str, db_path: str,
                              username: str = "سیستم") -> dict:
    # ==== STM v2: محافظت باز بودن دوره ====
    if not is_period_open(period_month):
        raise ValueError(
            f"دورهٔ «{period_month}» توسط مدیر باز نشده است. "
            f"با مدیر سامانه تماس بگیرید."
        )

    if not period_month:
        raise ValueError('دوره معتبر نیست.')

    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]

    start_row, col_map = _read_employment_file(ws)

    print(f"[EMPLOYMENT] start_row={start_row}  col_map={col_map}")

    conn = get_connection(db_path)
    conn.execute("DELETE FROM employment_monthly WHERE period_month = ?", (period_month,))

    ok = 0
    skipped = 0
    errors = []
    sample_skipped = []

    for row_num, row in enumerate(
        ws.iter_rows(min_row=start_row, values_only=True), start=start_row
    ):
        if not row:
            continue

        def get(idx):
            if idx is None or idx >= len(row):
                return None
            return row[idx]

        nc_raw     = get(col_map.get("nc"))
        status     = get(col_map.get("status"))
        first_name = get(col_map.get("first_name"))
        last_name  = get(col_map.get("last_name"))
        center     = get(col_map.get("center"))

        nc = _to_national_code(nc_raw)
        if not nc:
            skipped += 1
            if len(sample_skipped) < 5:
                sample_skipped.append(
                    f"ردیف {row_num}: nc_raw={nc_raw!r} | status={status!r}"
                )
            continue

        try:
            conn.execute("""
                INSERT OR REPLACE INTO employment_monthly
                    (national_code, period_month, first_name, last_name,
                     employment_status, main_cost_center)
                VALUES (?,?,?,?,?,?)
            """, (nc, period_month,
                  _normalize_text(first_name), _normalize_text(last_name),
                  _normalize_text(status), _normalize_text(center)))
            ok += 1
        except Exception as e:
            errors.append(f"ردیف {row_num}: {e}")

    records_updated = _apply_employment_for_month(conn, period_month)

    conn.commit()
    log_action(conn, username, "ایمپورت وضعیت اشتغال",
               f"دورهٔ {period_month}: {ok} ردیف، {records_updated} رکورد به‌روز شد")
    conn.close()

    print(f"[EMPLOYMENT] ذخیره شد: {ok} | skip: {skipped} | records به‌روز: {records_updated}")

    return {
        "ok": ok,
        "skipped": skipped,
        "period": period_month,
        "records_updated": records_updated,
        "detected_columns": col_map,
        "start_row": start_row,
        "sample_skipped": sample_skipped,
        "errors": errors[:20],
    }


# ============================================================
# ایمپورت پرداختی‌های ماهانه
# ============================================================
PERSIAN_MONTHS_NAMES = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
                        "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]


def _detect_payments_columns(headers):
    """تشخیص ستون‌های کد ملی، نام، نام خانوادگی و ماه‌ها از هدر."""
    result = {"nc": None, "first_name": None, "last_name": None, "months": {}}

    for i, h in enumerate(headers):
        if h is None:
            continue
        h_str = str(h).strip()
        if not h_str:
            continue
        h_norm = h_str.replace("ي", "ی").replace("ك", "ک")

        if result["nc"] is None and ("کد ملی" in h_norm or "کدملی" in h_norm or "کد ملي" in h_norm):
            result["nc"] = i
            continue

        if result["last_name"] is None and ("نام خانوادگ" in h_norm or "خانوادگی" in h_norm or "خانوادگي" in h_norm):
            result["last_name"] = i
            continue

        if result["first_name"] is None and h_norm.strip() == "نام":
            result["first_name"] = i
            continue

        for month in PERSIAN_MONTHS_NAMES:
            if month in h_norm:
                result["months"][i] = month
                break

    return result


def import_monthly_payments(xlsx_path, db_path,
                             username="سیستم",
                             overwrite=False,
                             year=None):
    """
    فایل «پرداختی نفرات» را می‌خواند.
    ستون‌ها هوشمند از هدر تشخیص داده می‌شوند.
    فقط ماه‌هایی که توسط مدیر باز شده‌اند پردازش می‌شوند.
    """
    from db.database import current_jalali_year
    if year is None:
        year = current_jalali_year()

    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]

    header_row_idx = 1
    header_row = None
    for ri in range(1, 6):
        try:
            candidate = next(ws.iter_rows(min_row=ri, max_row=ri, values_only=True))
        except StopIteration:
            break
        if not candidate:
            continue
        row_text = " ".join(str(v) for v in candidate if v is not None)
        if "کد ملی" in row_text or "کدملی" in row_text:
            header_row_idx = ri
            header_row = candidate
            break

    if header_row is None:
        header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True))

    col_map = _detect_payments_columns(header_row)

    print(f"[PAYMENTS] هدر در ردیف {header_row_idx}")
    print(f"[PAYMENTS] ستون کد ملی: {col_map['nc']}")
    print(f"[PAYMENTS] ستون نام: {col_map['first_name']}")
    print(f"[PAYMENTS] ستون نام خانوادگی: {col_map['last_name']}")
    print(f"[PAYMENTS] ستون‌های ماه: {col_map['months']}")

    if col_map["nc"] is None:
        col_map["nc"] = 0
    if col_map["first_name"] is None:
        col_map["first_name"] = 1
    if col_map["last_name"] is None:
        col_map["last_name"] = 2

    if not col_map["months"]:
        print("[PAYMENTS] ⚠️ هیچ ستون ماهی پیدا نشد — fallback به D-O")
        for col_num, month in MONTH_COLUMN_MAP.items():
            col_map["months"][col_num - 1] = month

    conn = get_connection(db_path)

    deleted = 0
    if overwrite:
        deleted = conn.execute(
            "DELETE FROM monthly_payments WHERE source='manual' AND period_month LIKE ?",
            (f"{year}-%",)
        ).rowcount

    opened_months = set()
    for col_idx, month in col_map["months"].items():
        pm = f"{year}-{month}"
        if is_period_open(pm):
            opened_months.add(month)

    print(f"[PAYMENTS] ماه‌های باز: {sorted(opened_months)}")

    if not opened_months:
        conn.close()
        wb.close()
        raise ValueError(f"هیچ ماهی از سال {year} توسط مدیر باز نشده است.")

    ok = 0
    skipped = 0
    skipped_closed = 0
    created_persons = 0
    updated_existing = 0
    errors = []

    data_start = header_row_idx + 1

    for row_num, row in enumerate(ws.iter_rows(min_row=data_start, values_only=True), start=data_start):
        if not row:
            continue

        def get(idx):
            if idx is None or idx >= len(row):
                return None
            return row[idx]

        nc = _to_national_code(get(col_map["nc"]))
        if not nc:
            skipped += 1
            continue

        first_name = _normalize_text(get(col_map["first_name"]))
        last_name = _normalize_text(get(col_map["last_name"]))

        existing = conn.execute(
            "SELECT id FROM persons WHERE national_code = ?", (nc,)
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO persons (national_code, first_name, last_name) VALUES (?,?,?)",
                (nc, first_name, last_name),
            )
            created_persons += 1
        else:
            if first_name or last_name:
                conn.execute("""
                    UPDATE persons
                    SET first_name = COALESCE(NULLIF(first_name, ''), ?),
                        last_name  = COALESCE(NULLIF(last_name,  ''), ?)
                    WHERE national_code = ?
                """, (first_name, last_name, nc))

        for col_idx, month in col_map["months"].items():
            if col_idx >= len(row):
                continue

            period_month = f"{year}-{month}"

            if not is_period_open(period_month):
                skipped_closed += 1
                continue

            val = row[col_idx]
            if val is None or val == "":
                continue

            amount = _to_number(val)
            if amount <= 0:
                continue

            prev = conn.execute("""
                SELECT id, amount, source FROM monthly_payments
                WHERE national_code = ? AND period_month = ?
            """, (nc, period_month)).fetchone()

            if prev and prev["source"] == "approved":
                continue

            if prev:
                updated_existing += 1

            try:
                conn.execute("""
                    INSERT INTO monthly_payments
                        (national_code, period_month, amount, source)
                    VALUES (?, ?, ?, 'manual')
                    ON CONFLICT(national_code, period_month) DO UPDATE SET
                        amount = excluded.amount,
                        source = 'manual'
                """, (nc, period_month, amount))
                ok += 1
            except Exception as e:
                errors.append(f"ردیف {row_num} / ماه {month}: {e}")

    conn.commit()
    log_action(conn, username, "ایمپورت پرداختی‌های ماهانه",
               f"سال {year}: {ok} پرداخت، {updated_existing} به‌روز، "
               f"{created_persons} شخص جدید")
    conn.close()
    wb.close()

    return {
        "ok": ok,
        "skipped": skipped,
        "skipped_closed_months": skipped_closed,
        "opened_months_processed": sorted(opened_months),
        "created_persons": created_persons,
        "updated_existing": updated_existing,
        "deleted_before": deleted,
        "year": year,
        "detected_columns": {
            "nc": col_map["nc"],
            "first_name": col_map["first_name"],
            "last_name": col_map["last_name"],
            "months": {str(k): v for k, v in col_map["months"].items()},
        },
        "errors": errors[:30],
    }




# ==== STM v2.3: ایمپورت مرکز هزینه اصلی ====
def import_main_cost_centers(xlsx_path, db_path, username="سیستم", period_month=None):
    if not period_month:
        raise ValueError("period_month الزامی است")
    """
    فایل مرکز هزینه اصلی.
    ساختار: کد ملی | نام | نام خانوادگی | مرکز هزینه اصلی
    """
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]

    header_row_idx = 1
    header_row = None
    for ri in range(1, 6):
        try:
            candidate = next(ws.iter_rows(min_row=ri, max_row=ri, values_only=True))
        except StopIteration:
            break
        if not candidate:
            continue
        row_text = " ".join(str(v) for v in candidate if v is not None)
        if "کد ملی" in row_text or "کدملی" in row_text:
            header_row_idx = ri
            header_row = candidate
            break

    if header_row is None:
        header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True))

    col_nc = None
    col_first = None
    col_last = None
    col_center = None

    for i, h in enumerate(header_row):
        if h is None:
            continue
        h_norm = str(h).strip().replace("ي", "ی").replace("ك", "ک")

        if col_nc is None and ("کد ملی" in h_norm or "کدملی" in h_norm):
            col_nc = i
            continue
        if col_last is None and ("نام خانوادگ" in h_norm or "خانوادگی" in h_norm or "خانوادگي" in h_norm):
            col_last = i
            continue
        if col_first is None and h_norm.strip() == "نام":
            col_first = i
            continue
        if col_center is None and ("مرکز هزینه اصلی" in h_norm or ("مرکز" in h_norm and "هزینه" in h_norm)):
            col_center = i
            continue

    if col_nc is None: col_nc = 0
    if col_first is None: col_first = 1
    if col_last is None: col_last = 2
    if col_center is None: col_center = 3

    print(f"[MAIN-CENTER] هدر ردیف {header_row_idx}, ستون‌ها: nc={col_nc}, first={col_first}, last={col_last}, center={col_center}")

    conn = get_connection(db_path)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS main_cost_centers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            national_code TEXT NOT NULL,
            period_month TEXT NOT NULL,
            main_cost_center TEXT NOT NULL,
            first_name TEXT,
            last_name TEXT,
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(national_code, period_month)
        )
    """)

    ok = 0
    skipped = 0
    errors = []
    data_start = header_row_idx + 1

    for row_num, row in enumerate(ws.iter_rows(min_row=data_start, values_only=True), start=data_start):
        if not row:
            continue
        def get(idx):
            if idx is None or idx >= len(row):
                return None
            return row[idx]

        nc = _to_national_code(get(col_nc))
        center = _normalize_text(get(col_center))
        first_name = _normalize_text(get(col_first))
        last_name = _normalize_text(get(col_last))

        if not nc or not center:
            skipped += 1
            continue

        try:
            conn.execute("""
                INSERT INTO main_cost_centers (national_code, period_month, main_cost_center, first_name, last_name, updated_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(national_code, period_month) DO UPDATE SET
                    main_cost_center = excluded.main_cost_center,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    updated_at = datetime('now')
            """, (nc, period_month, center, first_name, last_name))
            ok += 1
        except Exception as e:
            errors.append(f"ردیف {row_num}: {e}")

    updated_records = conn.execute("""
        UPDATE records SET main_cost_center = (
            SELECT mcc.main_cost_center FROM main_cost_centers mcc
            WHERE mcc.national_code = (
                SELECT p.national_code FROM persons p WHERE p.id = records.person_id
            ) AND mcc.period_month = ?
        )
        WHERE period_month = ? AND EXISTS (
            SELECT 1 FROM main_cost_centers mcc
            JOIN persons p ON p.national_code = mcc.national_code
            WHERE p.id = records.person_id AND mcc.period_month = ?
        )
    """, (period_month, period_month, period_month)).rowcount

    conn.commit()
    log_action(conn, username, "ایمپورت مرکز هزینه اصلی",
               f"{ok} ردیف، {skipped} رد، {updated_records} رکورد به‌روز")
    conn.close()
    wb.close()

    return {
        "ok": ok,
        "skipped": skipped,
        "records_updated": updated_records,
        "detected_columns": {
            "nc": col_nc,
            "first_name": col_first,
            "last_name": col_last,
            "center": col_center,
        },
        "errors": errors[:20],
    }

