"""Ortak yol tanimlari — tum moduller bunu kullanir."""
import os

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(ROOT_DIR, "config")
DATA_DIR = os.path.join(ROOT_DIR, "data")
OUTPUT_DIR = os.path.join(ROOT_DIR, "outputs")
SETTINGS_DIR = CONFIG_DIR
PROXY_FILE = os.path.join(DATA_DIR, "ips-datacenter_proxy12026-11-16T01_15_06.647Z.txt")

for _d in (CONFIG_DIR, DATA_DIR, OUTPUT_DIR):
    os.makedirs(_d, exist_ok=True)
