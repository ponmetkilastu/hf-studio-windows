

import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
from paths import ROOT_DIR, CONFIG_DIR, DATA_DIR, OUTPUT_DIR, SETTINGS_DIR, PROXY_FILE
from clients.hf_image_client import ProxyPool
p = ProxyPool('ips-datacenter_proxy12026-11-16T01_15_06.647Z.txt')
print(f'Loaded {len(p)} proxies')
print(f'First 3: {[px.ip for px in p.proxies[:3]]}')
print(f'Last 3: {[px.ip for px in p.proxies[-3:]]}')