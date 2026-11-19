"""proxy_state.db icerigini gosteren kucuk arac."""



import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
from paths import ROOT_DIR, CONFIG_DIR, DATA_DIR, OUTPUT_DIR, SETTINGS_DIR, PROXY_FILE
import sqlite3

c = sqlite3.connect("proxy_state.db")
print("=== proxy_state.db ===")
print("tablolar:", [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")])
print("proxies kolonlari:", [d[1] for d in c.execute("PRAGMA table_info(proxies)")])
print()
print("ilk 6 satir (en eski kullanilan):")
for r in c.execute("SELECT ip, last_used, use_count, bad FROM proxies ORDER BY last_used ASC LIMIT 6"):
    print("  ", r)
print()
print("son kullanilan:", c.execute("SELECT value FROM state WHERE key='last_ip'").fetchone()[0])
print("kotu proxy sayisi:", c.execute("SELECT COUNT(*) FROM proxies WHERE bad=1").fetchone()[0])
print("toplam kullanim:", c.execute("SELECT SUM(use_count) FROM proxies").fetchone()[0])
c.close()
