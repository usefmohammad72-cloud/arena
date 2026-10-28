# app_paths.py
import os, sys, secrets
from pathlib import Path

APP_NAME = "STM"

def _is_frozen():
    return getattr(sys, 'frozen', False)

def get_resource_dir() -> Path:
    """منابع read-only داخل exe/پوشهٔ نصب."""
    if _is_frozen():
        return Path(sys._MEIPASS)
    return Path(__file__).parent

def get_data_dir() -> Path:
    """داده‌های قابل نوشتن — در AppData، نه کنار exe."""
    if os.name == 'nt':
        base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    else:
        base = os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share')
    d = Path(base) / APP_NAME
    (d / 'data' / 'uploads').mkdir(parents=True, exist_ok=True)
    (d / 'logs').mkdir(exist_ok=True)
    (d / 'backups').mkdir(exist_ok=True)
    return d

def get_db_path() -> Path:
    return get_data_dir() / 'data' / 'app.db'

def get_uploads_dir() -> Path:
    return get_data_dir() / 'data' / 'uploads'

def get_secret_key() -> str:
    p = get_data_dir() / 'secret.key'
    if not p.exists():
        p.write_text(secrets.token_hex(32))
        try: os.chmod(p, 0o600)
        except Exception: pass
    return p.read_text().strip()