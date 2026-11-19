"""SQLite tabanli proxy havuzu testleri.

Kontrol edilenler:
  1. FIFO: en eski kullanilan secilir, ayni IP arka arkaya gelmez.
  2. Iki ayri SUREC ayni anda secim yapinca farkli IP alir.
  3. Isaretleme secim aninda yapilir (uretim bitmeden).
  4. Kotu proxy atlanir.
  5. Eski JSON state DB'ye aktarilir.
"""


from __future__ import annotations

import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
from paths import ROOT_DIR, CONFIG_DIR, DATA_DIR, OUTPUT_DIR, SETTINGS_DIR, PROXY_FILE

import json
import os
import shutil
import subprocess
import sys
import tempfile

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(APP_DIR, "ips-datacenter_proxy12026-11-16T01_15_06.647Z.txt")
sys.path.insert(0, APP_DIR)

from clients.hf_image_client import ProxyPool  # noqa: E402

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'OK  ' if cond else 'FAIL'}] {name}{(' · ' + detail) if detail else ''}")
    if not cond:
        failures.append(name)


CHILD = r'''
import os, sys, time, json
sys.path.insert(0, {app!r})
from clients.hf_image_client import ProxyPool
state, count = sys.argv[1], int(sys.argv[2])
pool = ProxyPool({src!r}, state_path=state)
out = []
for _ in range(count):
    p = pool.next()
    out.append({{"ip": p.ip, "at": pool.last_used_at}})
    time.sleep(0.05)
print(json.dumps(out))
'''


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="proxy_db_test_")
    try:
        state = os.path.join(tmp, "proxy_state.json")
        db = os.path.splitext(state)[0] + ".db"

        # --- 1) FIFO --- #
        pool = ProxyPool(SRC, state_path=state)
        total = len(pool)
        check("havuz yuklendi", total == 503, f"{total} IP")
        check("SQLite dosyasi olustu", os.path.exists(db), db)

        picked = [pool.next().ip for _ in range(total)]
        check("her IP tam bir kez kullanildi", len(set(picked)) == total, f"{len(set(picked))}/{total}")
        check("arka arkaya ayni IP yok", all(picked[i] != picked[i + 1] for i in range(total - 1)))

        second = [pool.next().ip for _ in range(10)]
        check("2. tur en eski kullanilanlardan baslar", second[0] == picked[0], second[0])
        check("2. turda tekrarli IP yok", len(set(second)) == len(second))

        # --- 2) kotu proxy --- #
        pool2 = ProxyPool(SRC, state_path=state)
        bad = pool2.next()
        pool2.mark_bad(bad)
        nxt = pool2.next()
        check("kotu proxy atlandi", nxt.ip != bad.ip, f"{bad.ip} -> {nxt.ip}")

        # --- 3) DB icerigi --- #
        import sqlite3

        conn = sqlite3.connect(db)
        rows = conn.execute("SELECT COUNT(*) FROM proxies").fetchone()[0]
        badn = conn.execute("SELECT COUNT(*) FROM proxies WHERE bad=1").fetchone()[0]
        usedn = conn.execute("SELECT COUNT(*) FROM proxies WHERE last_used > 0").fetchone()[0]
        last = conn.execute("SELECT value FROM state WHERE key='last_ip'").fetchone()
        conn.close()
        check("DB'de tum proxy'ler var", rows == total, f"{rows}/{total}")
        check("DB'de kotu isareti var", badn >= 1, f"{badn}")
        check("DB'de kullanim zamanlari var", usedn > 0, f"{usedn} IP")
        check("DB'de last_ip var", bool(last and last[0]), last[0] if last else "-")

        # --- 4) iki surec ayni anda --- #
        tmp2 = tempfile.mkdtemp(prefix="proxy_db_multi_")
        try:
            state2 = os.path.join(tmp2, "proxy_state.json")
            script = os.path.join(tmp2, "child.py")
            with open(script, "w", encoding="utf-8") as fh:
                fh.write(CHILD.format(app=APP_DIR, src=SRC))
            procs = [
                subprocess.Popen(
                    [sys.executable, script, state2, "6"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for _ in range(2)
            ]
            res = []
            for p in procs:
                out, err = p.communicate(timeout=120)
                if p.returncode != 0:
                    print("SUREC HATASI:", err[-500:])
                res.append(json.loads(out.strip().splitlines()[-1]))

            a = [r["ip"] for r in res[0]]
            b = [r["ip"] for r in res[1]]
            allips = a + b
            check("iki sekme ayni IP almadi", not (set(a) & set(b)), f"A[0]={a[0]} B[0]={b[0]}")
            check("tum secimler farkli", len(set(allips)) == len(allips), f"{len(set(allips))}/{len(allips)}")
            for nm, seq in (("A", a), ("B", b)):
                check(f"sekme {nm} arka arkaya ayni IP yok",
                      all(seq[i] != seq[i + 1] for i in range(len(seq) - 1)))
            check("isaretleme secim aninda diskte",
                  all(r["ip"] in {x[0] for x in sqlite3.connect(os.path.splitext(state2)[0] + ".db")
                                  .execute("SELECT ip FROM proxies WHERE last_used > 0")} for r in res[0]))
        finally:
            shutil.rmtree(tmp2, ignore_errors=True)

        # --- 5) legacy JSON migration --- #
        tmp3 = tempfile.mkdtemp(prefix="proxy_db_legacy_")
        try:
            state3 = os.path.join(tmp3, "proxy_state.json")
            db3 = os.path.splitext(state3)[0] + ".db"
            with open(state3, "w", encoding="utf-8") as fh:
                json.dump({"index": 100, "last_ip": None, "bad": []}, fh)
            p3 = ProxyPool(SRC, state_path=state3)
            got = p3.next().ip
            conn3 = sqlite3.connect(db3)
            n_used = conn3.execute("SELECT COUNT(*) FROM proxies WHERE last_used > 0").fetchone()[0]
            conn3.close()
            check("legacy JSON aktarildi", n_used >= 1, f"{n_used} IP zamanladi")
            check("legacy migration sonraki IP dogru", got == p3.proxies[101].ip, got)
        finally:
            shutil.rmtree(tmp3, ignore_errors=True)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        print(f"{len(failures)} test BASARISIZ: {', '.join(failures)}")
        return 1
    print("Tum SQLite testleri gecti.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
