# web/master_control.py — کنترل مطلق مالک سامانه
"""
لایه‌های امنیتی:
۱. فایل master.key روی دسکتاپ مالک (اثر انگشت سخت‌افزاری)
۲. حالت read-only بدون فایل کلید
۳. قفل اضطراری (Lockdown)
"""
import os, sys, json, hashlib
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from app_paths import get_data_dir

# ==== کلید امضای مخفی (فقط توی این فایل و ذهن مالک) ====
MASTER_SIGNATURE = "STM_MASTER_2026_xK9mP3qR"
# ==== رمز فعال‌سازی مالک ====
MASTER_PASSWORD = "Stm_Master_2026!"


def _hardware_id():
    """شناسه یکتای سیستم — UUID مادربورد"""
    if os.name == 'nt':
        try:
            import subprocess
            out = subprocess.check_output(
                'wmic csproduct get uuid',
                shell=True, stderr=subprocess.DEVNULL
            ).decode(errors='ignore')
            lines = [l.strip() for l in out.split('\n') if l.strip()]
            if len(lines) >= 2:
                return hashlib.sha256(lines[1].encode()).hexdigest()[:32]
        except Exception:
            pass
    try:
        import uuid
        return hashlib.sha256(str(uuid.getnode()).encode()).hexdigest()[:32]
    except Exception:
        return "unknown_hw"


def get_master_key_path():
    """مسیر فایل کلید روی دسکتاپ مالک"""
    home = Path.home()
    desktop = home / 'Desktop'
    if not desktop.exists():
        desktop = home
    return desktop / '.stm_master.key'


def create_master_key():
    """ساخت فایل کلید برای اولین بار"""
    hw = _hardware_id()
    sig = hashlib.sha256((hw + MASTER_SIGNATURE).encode()).hexdigest()
    key_data = {
        "version": "1.0",
        "owner": "system_owner",
        "hardware_id": hw,
        "signature": sig,
        "created_at": datetime.now().isoformat(),
    }
    path = get_master_key_path()
    path.write_text(json.dumps(key_data, ensure_ascii=False, indent=2), encoding='utf-8')
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass
    return path


def verify_master_key():
    """چک اعتبار فایل کلید"""
    path = get_master_key_path()
    if not path.exists():
        return False, "فایل کلید مالک پیدا نشد"
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return False, "فایل کلید نامعتبر است"
    hw = _hardware_id()
    if data.get("hardware_id") != hw:
        return False, "کلید مربوط به این سیستم نیست"
    expected = hashlib.sha256((hw + MASTER_SIGNATURE).encode()).hexdigest()
    if data.get("signature") != expected:
        return False, "امضای کلید نامعتبر است"
    return True, "تأیید شد"


def _lock_file():
    return get_data_dir() / '.lockdown'


def is_locked():
    return _lock_file().exists()


def set_lockdown(state):
    f = _lock_file()
    if state:
        f.write_text(datetime.now().isoformat(), encoding='utf-8')
    else:
        if f.exists():
            f.unlink()


def get_status():
    ok, msg = verify_master_key()
    return {
        "master_key_exists": get_master_key_path().exists(),
        "master_key_path": str(get_master_key_path()),
        "master_key_valid": ok,
        "master_key_message": msg,
        "hardware_id": _hardware_id()[:8] + "...",
        "lockdown": is_locked(),
    }