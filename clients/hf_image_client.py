"""MiniMax H3 Image (Hugging Face Space) icin tersine muhendislik istemcisi.

Tersine muhendislik kaynagi: ``huggingface.co.m3max.har``
Space: https://huggingface.co/spaces/MiniMaxAI/minimax-h3-image

HAR'dan cikarilan akis (tarayicidaki "Generate" zinciri):

  1. POST /gradio_api/queue/join  {fn_index: 1, data: [state, seed, randomize, effort]}
     -> {"event_id": "..."}          (studio: prompt kodlama + plan)
  2. GET  /gradio_api/queue/data?session_hash=...   (SSE, process_completed beklenir)
  3. POST /gradio_api/queue/join  {fn_index: 2, data: [null]}
     -> {"event_id": "..."}          (render: plan sunucu state'inden okunur)
  4. GET  /gradio_api/queue/data?session_hash=...   (SSE, process_completed beklenir)
  5. GET  <sonuc url>                (/gradio_api/file=/tmp/gradio/....png)

``state`` sozlugu tarayicidan gelen bicimdedir::

    {"prompt": "...", "aspect": "auto", "resolution": "4 MP",
     "enhance": false, "images": ["data:image/jpeg;base64,...."]}

Notlar:
  * HAR'daki isteklerde hicbir Authorization / cookie / HF tokeni yoktur.
    Bu istemci de kimlik dogrulama bilgisi gondermez (proxy kullanici/parola
    haric; onlar sadece proxy'e aittir).
  * Tarayicidaki ilk ``fn_index: 0`` istegi sadece arayuzu temizleyen bir
    lambdadir, sonucu etkilemez; bu yuzden atlanir.
  * ``fn_index: 2`` isteginde plan ``null`` gonderilir; plan sunucuda
    ``session_hash`` anahtarli state'te tutulur.
"""


from __future__ import annotations

import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
from paths import ROOT_DIR, CONFIG_DIR, DATA_DIR, OUTPUT_DIR, SETTINGS_DIR, PROXY_FILE


import base64
import glob
import io
import ipaddress
import json
import os
import random
import re
import string
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Iterable, Optional
from urllib.parse import quote

import requests

from core.proxy_db import ProxyDB

BASE_URL = "https://minimaxai-minimax-h3-image.hf.space"
QUEUE_JOIN = BASE_URL + "/gradio_api/queue/join?__theme=system"
QUEUE_DATA = BASE_URL + "/gradio_api/queue/data"

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36"
)

ASPECTS = ["auto", "1:1", "5:4", "4:3", "3:2", "16:9", "21:9", "4:5", "3:4", "2:3", "9:16"]
RESOLUTIONS = ["4 MP", "8 MP", "16 MP"]
EFFORTS = ["low", "medium", "xhigh"]
MAX_IMAGES = 8
FALLBACK_PROXY_GLOB = "ips-datacenter_proxy*.txt"

RETRY_STATUS = {403, 407, 429, 502, 503, 504}


class ClientError(RuntimeError):
    """Kullaniciya gosterilebilir istemci hatasi."""


class HttpStatusError(ClientError):
    """HTTP >= 400 yaniti; govdeyi de tasir.

    Space'in ``/gradio_api/file=`` rotasi, dosya o surecte tanimli degilse
    ``403 {"detail": "File not allowed: ..."}`` dondurur (bkz. download_result).
    """

    def __init__(self, label: str, status: int, body: str = "") -> None:
        self.status = status
        self.body = body
        text = f"{label} · HTTP {status}"
        if body:
            text += f": {body}"
        super().__init__(text)

    @property
    def file_not_allowed(self) -> bool:
        return self.status == 403 and "file not allowed" in self.body.lower()

    @property
    def retryable(self) -> bool:
        return self.status in RETRY_STATUS


# --------------------------------------------------------------------------- #
#  Proxy havuzu
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Proxy:
    """``host:port:kullanici:parola`` satirinin ayristirilmis hali."""

    host: str
    port: int
    username: str
    password: str

    @property
    def ip(self) -> str:
        # Bright Data kullanici adi sonunda "-ip-178.171.117.112" tasir.
        m = re.search(r"-ip-([0-9a-fA-F:.]+)$", self.username)
        return m.group(1) if m else self.username

    @property
    def url(self) -> str:
        user = quote(self.username, safe="")
        pwd = quote(self.password, safe="")
        return f"http://{user}:{pwd}@{self.host}:{self.port}"

    def as_dict(self) -> dict[str, str]:
        u = self.url
        return {"http": u, "https": u}

    @property
    def label(self) -> str:
        return self.ip


class ProxyPool:
    """Her cagride "en eski kullanilan" proxy'i dondurur; veriler SQLite'da tutulur.

    Calisma mantigi (FIFO / LRU):

      * Kullanim verisi ``proxy_state.db`` (SQLite) icinde saklanir.
      * Her uretimde EN ESKI kullanilan proxy secilir (last_used en kucuk).
      * Isaretleme proxy secildigi ANDA yapilir; uretimin bitmesi beklenmez.
      * Ayni proxy iki kez arka arkaya kullanilmaz (son kullanilan atlanir).
      * "kotu" (olu) proxy'ler atlanir.
      * Secim + isaretleme tek transaction icinde oldugu icin ayni anda
        calisan birden fazla sekme ayni proxy'yi ALAMAZ.
    """

    def __init__(self, path: str, state_path: Optional[str] = None) -> None:
        self.path = path
        self.state_path = state_path or os.path.join(
            os.path.dirname(os.path.abspath(path)) or ".", "proxy_state.json"
        )
        self.proxies = self._load(path)
        if not self.proxies:
            raise ClientError(f"Proxy dosyasi bos veya gecersiz: {path}")

        self._by_ip: dict[str, Proxy] = {p.ip: p for p in self.proxies}
        self._last_position: int = 0
        self._last_used_at: float = 0.0

        self.db = ProxyDB(self._db_path())
        self._seed_db()

    # -- yukleme ---------------------------------------------------------- #

    @staticmethod
    def _load(path: str) -> list[Proxy]:
        out: list[Proxy] = []
        seen: set[str] = set()
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or line.count(":") < 3:
                    continue
                host, port_s, user, pwd = line.split(":", 3)
                try:
                    port = int(port_s)
                except ValueError:
                    continue
                user = user.strip()
                match = re.search(r"-ip-(.+)$", user)
                if match:
                    # "-ip-undefined" gibi bozuk satirlari atla.
                    try:
                        ipaddress.ip_address(match.group(1))
                    except ValueError:
                        continue
                proxy = Proxy(host.strip(), port, user, pwd.strip())
                # Ayni IP'yi iki kez kullanmayalim (dosyada tekrarlar olabilir).
                if proxy.ip in seen:
                    continue
                seen.add(proxy.ip)
                out.append(proxy)
        return out

    @staticmethod
    def find_default(directory: str) -> Optional[str]:
        exact = os.path.join(directory, "ips-datacenter_proxy12026-11-16T01_15_06.647Z.txt")
        if os.path.exists(exact):
            return exact
        for base in (directory, os.path.join(directory, "data")):
            for pattern in (FALLBACK_PROXY_GLOB, "*proxy*.txt"):
                hits = sorted(glob.glob(os.path.join(base, pattern)), key=os.path.getmtime, reverse=True)
                if hits:
                    return hits[0]
        return None

    # -- durum (SQLite) ---------------------------------------------------- #

    def _db_path(self) -> str:
        """JSON state yerine kullanilacak SQLite dosyasi."""
        return os.path.splitext(self.state_path)[0] + ".db"

    def _seed_db(self) -> None:
        """Proxy listesini tabloya yazar; eski JSON state varsa aktarir."""
        fresh = self.db.count() == 0
        self.db.seed(self._by_ip.keys())
        if fresh:
            self._migrate_legacy_json()

    def _migrate_legacy_json(self) -> None:
        """Eski ``proxy_state.json`` icindeki verileri tabloya aktarir."""
        try:
            with open(self.state_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                return
        except (OSError, ValueError, TypeError):
            return

        bad = [ip for ip in (data.get("bad") or []) if ip in self._by_ip]
        used: dict[str, float] = {}

        raw = data.get("used")
        if isinstance(raw, dict) and raw:
            for ip, ts in raw.items():
                if ip in self._by_ip:
                    try:
                        used[ip] = float(ts)
                    except (TypeError, ValueError):
                        continue
        else:
            order = data.get("queue")
            if isinstance(order, list) and order:
                # Ara format: kuyruk en eski -> en yeni.
                for i, ip in enumerate(order):
                    if ip in self._by_ip:
                        used[ip] = float(i + 1)
            else:
                # En eski format: "index" kaldigimiz yeri gosterir.
                try:
                    idx = int(data.get("index", -1))
                except (TypeError, ValueError):
                    idx = -1
                if 0 <= idx < len(self.proxies):
                    seq = self.proxies[idx + 1:] + self.proxies[:idx + 1]
                    for i, proxy in enumerate(seq):
                        used[proxy.ip] = float(i + 1)

        self.db.import_state(bad=bad, used=used, last_ip=data.get("last_ip"))

    # -- secim ------------------------------------------------------------ #

    def next(self) -> Proxy:
        """En eski kullanilan proxy'yi sec ve KULLANILDI OLARAK ISARETLE.

        Isaretleme ve yazma, istegin bitmesini BEKLEMEZ: proxy secildigi anda
        olur. Secim + isaretleme tek SQLite transaction'i icinde yapildigi icin
        ayni anda calisan iki sekme ayni proxy'yi ALAMAZ.
        """
        now = time.time()
        last_ip = self.db.get_state("last_ip")
        ip = self.db.pick(last_ip, now)
        if ip is None:
            raise ClientError("Kullanilabilir proxy kalmadi.")
        proxy = self._by_ip.get(ip)
        if proxy is None:
            raise ClientError(f"Proxy listede bulunamadi: {ip}")
        self._last_used_at = now
        self._last_position = self.db.position_of(ip)
        return proxy

    def mark_bad(self, proxy: Proxy) -> None:
        self.db.mark_bad(proxy.ip)

    def stats(self) -> dict:
        """Kullanim istatistikleri (log/panel icin)."""
        return self.db.stats()

    @property
    def position(self) -> int:
        """Kuyrukta secilen proxy'nin 1 tabanli konumu (loglarda gosterilir)."""
        return self._last_position

    @property
    def remaining(self) -> int:
        """Henuz hic kullanilmamis proxy sayisi."""
        return self.db.never_used_count()

    @property
    def last_used_at(self) -> float:
        """Secilen proxy'nin isaretlendigi an (epoch)."""
        return self._last_used_at

    def __len__(self) -> int:
        return len(self.proxies)


# --------------------------------------------------------------------------- #
#  Uretim basina tek proxy kullanan HTTP katmani
# --------------------------------------------------------------------------- #


class StreamHandle:
    def __init__(self, session: requests.Session, response: requests.Response, proxy: Proxy) -> None:
        self.session = session
        self.response = response
        self.proxy = proxy

    def __iter__(self):
        return self.response.iter_lines(decode_unicode=True)

    def close(self) -> None:
        try:
            self.response.close()
        finally:
            self.session.close()


class RotatingTransport:
    """Bir uretim boyunca tek proxy kullanir; yeni uretimde havuzdan sonraki proxy'i alir.

    Proxy seviyesinde bir hata olursa (olu IP vb.) sadece o uretim icin bir sonraki
    proxy'e gecer, boylece islem yarida kalmaz.
    """

    def __init__(
        self,
        pool: Optional[ProxyPool],
        on_log: Optional[Callable[[str, str], None]] = None,
        max_attempts: int = 6,
    ) -> None:
        self.pool = pool
        self.on_log = on_log or (lambda level, msg: None)
        self.max_attempts = max_attempts
        self.used: list[Proxy] = []
        self._leased: Optional[Proxy] = None

    def begin_run(self) -> None:
        """Yeni uretim icin tek bir proxy kirala (tum istekler bunun uzerinden gider)."""
        self.used = []
        self._leased = None
        if self.pool is None:
            self.on_log("proxy", "uretim · dogrudan baglanti")
            return
        self._leased = self.pool.next()
        self.used.append(self._leased)
        stamp = datetime.fromtimestamp(self.pool.last_used_at).strftime("%H:%M:%S")
        self.on_log(
            "proxy",
            f"uretim proxy'si · {self._leased.label}  "
            f"[en eski kullanilan · {stamp} · sira {self.pool.position}/{len(self.pool)}]",
        )

    def _pick(self) -> Optional[Proxy]:
        if self.pool is None:
            return None
        if self._leased is None:
            self._leased = self.pool.next()
            if self._leased not in self.used:
                self.used.append(self._leased)
        return self._leased

    def _rotate(self, failed: Optional[Proxy]) -> None:
        """Proxy seviyesinde hata olduysa bu uretim icin yeni proxy kirala."""
        if self.pool is None or failed is None:
            return
        if self._leased is not None and failed.ip == self._leased.ip:
            self._leased = None

    def _log(self, level: str, msg: str) -> None:
        self.on_log(level, msg)

    def _proxy_note(self, label: str, proxy: Optional[Proxy], attempt: int) -> None:
        if proxy is None:
            self._log("info", f"{label} · dogrudan baglanti" + (f" (deneme {attempt})" if attempt > 1 else ""))
        else:
            self._log(
                "info",
                f"{label} · proxy {proxy.label}" + (f" · deneme {attempt}" if attempt > 1 else ""),
            )

    def post_json(
        self,
        url: str,
        payload: dict,
        headers: dict,
        timeout: tuple[int, int] = (30, 180),
        label: str = "istek",
    ) -> requests.Response:
        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_attempts + 1):
            proxy = self._pick()
            self._proxy_note(label, proxy, attempt)
            session = requests.Session()
            session.trust_env = False
            try:
                try:
                    resp = session.post(
                        url,
                        json=payload,
                        headers=headers,
                        proxies=proxy.as_dict() if proxy else None,
                        timeout=timeout,
                    )
                except (requests.exceptions.ProxyError, requests.exceptions.ConnectTimeout) as exc:
                    last_error = exc
                    if proxy is not None and self.pool is not None:
                        self.pool.mark_bad(proxy)
                        self._rotate(proxy)
                    self._log("warn", f"{label} · proxy hatasi ({type(exc).__name__}), baska proxy deneniyor")
                    time.sleep(0.4)
                    continue
                except requests.exceptions.RequestException as exc:
                    last_error = exc
                    self._log("warn", f"{label} · baglanti hatasi ({type(exc).__name__}), baska proxy deneniyor")
                    time.sleep(0.4)
                    continue

                if resp.status_code in RETRY_STATUS and attempt < self.max_attempts:
                    last_error = ClientError(f"HTTP {resp.status_code}")
                    self._log("warn", f"{label} · HTTP {resp.status_code}, baska proxy deneniyor")
                    time.sleep(0.4)
                    continue
                if resp.status_code >= 400:
                    body = (resp.text or "").strip().replace("\n", " ")[:400]
                    raise ClientError(f"{label} · HTTP {resp.status_code}: {body}")
                return resp
            finally:
                session.close()
        raise ClientError(f"{label} basarisiz: {last_error}")

    def post_multipart(
        self,
        url: str,
        files: dict,
        data: Optional[dict] = None,
        headers: Optional[dict] = None,
        timeout: tuple[int, int] = (30, 900),
        label: str = "yukleme",
    ) -> requests.Response:
        """multipart/form-data POST (Gradio ``/upload``). Proxy hatasinda IP degistirir."""
        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_attempts + 1):
            proxy = self._pick()
            self._proxy_note(label, proxy, attempt)
            session = requests.Session()
            session.trust_env = False
            try:
                try:
                    resp = session.post(
                        url,
                        files=files,
                        data=data or {},
                        headers=headers or {},
                        proxies=proxy.as_dict() if proxy else None,
                        timeout=timeout,
                    )
                except (requests.exceptions.ProxyError, requests.exceptions.ConnectTimeout) as exc:
                    last_error = exc
                    if proxy is not None and self.pool is not None:
                        self.pool.mark_bad(proxy)
                        self._rotate(proxy)
                    self._log("warn", f"{label} · proxy hatasi ({type(exc).__name__}), baska proxy deneniyor")
                    time.sleep(0.4)
                    continue
                except requests.exceptions.RequestException as exc:
                    last_error = exc
                    self._log("warn", f"{label} · baglanti hatasi ({type(exc).__name__})")
                    time.sleep(0.4)
                    continue

                if resp.status_code in RETRY_STATUS and attempt < self.max_attempts:
                    last_error = ClientError(f"HTTP {resp.status_code}")
                    self._log("warn", f"{label} · HTTP {resp.status_code}, baska proxy deneniyor")
                    time.sleep(0.4)
                    continue
                if resp.status_code >= 400:
                    body = (resp.text or "").strip().replace("\n", " ")[:400]
                    raise HttpStatusError(label, resp.status_code, body)
                return resp
            finally:
                session.close()
        raise ClientError(f"{label} basarisiz: {last_error}")

    def open_sse(
        self,
        url: str,
        headers: dict,
        timeout: tuple[int, int] = (30, 1800),
        label: str = "sse",
    ) -> StreamHandle:
        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_attempts + 1):
            proxy = self._pick()
            self._proxy_note(label, proxy, attempt)
            session = requests.Session()
            session.trust_env = False
            try:
                try:
                    resp = session.get(
                        url,
                        headers=headers,
                        proxies=proxy.as_dict() if proxy else None,
                        stream=True,
                        timeout=timeout,
                    )
                except (requests.exceptions.ProxyError, requests.exceptions.ConnectTimeout) as exc:
                    last_error = exc
                    session.close()
                    if proxy is not None and self.pool is not None:
                        self.pool.mark_bad(proxy)
                        self._rotate(proxy)
                    self._log("warn", f"{label} · proxy hatasi ({type(exc).__name__})")
                    time.sleep(0.4)
                    continue
                except requests.exceptions.RequestException as exc:
                    last_error = exc
                    session.close()
                    self._log("warn", f"{label} · baglanti hatasi ({type(exc).__name__})")
                    time.sleep(0.4)
                    continue

                if resp.status_code != 200:
                    status, body = resp.status_code, (resp.text or "").strip().replace("\n", " ")[:400]
                    resp.close()
                    session.close()
                    if status in RETRY_STATUS and attempt < self.max_attempts:
                        last_error = ClientError(f"HTTP {status}")
                        self._log("warn", f"{label} · HTTP {status}, baska proxy deneniyor")
                        time.sleep(0.4)
                        continue
                    raise ClientError(f"{label} · HTTP {status}: {body}")
                return StreamHandle(session, resp, proxy or Proxy("", 0, "", ""))
            except ClientError:
                raise
        raise ClientError(f"{label} baglantisi kurulamadi: {last_error}")

    def _fetch(
        self,
        url: str,
        headers: dict,
        proxy: Optional[Proxy],
        label: str,
        attempt: int,
        timeout: tuple[int, int],
    ) -> bytes:
        """Tek bir GET denemesi. Hata durumunda govdesiyle birlikte firlatir."""
        self._proxy_note(label, proxy, attempt)
        session = requests.Session()
        session.trust_env = False
        try:
            resp = session.get(
                url,
                headers=headers,
                proxies=proxy.as_dict() if proxy else None,
                timeout=timeout,
            )
            if resp.status_code >= 400:
                body = (resp.text or "").strip().replace("\n", " ")[:300]
                raise HttpStatusError(label, resp.status_code, body)
            return resp.content
        finally:
            session.close()

    def get_bytes(
        self,
        url: str,
        headers: dict,
        timeout: tuple[int, int] = (30, 300),
        label: str = "indirme",
        use_proxy: bool = True,
    ) -> bytes:
        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_attempts + 1):
            proxy = self._pick() if use_proxy else None
            try:
                return self._fetch(url, headers, proxy, label, attempt, timeout)
            except HttpStatusError as exc:
                last_error = exc
                if exc.status in RETRY_STATUS and attempt < self.max_attempts:
                    self._log("warn", f"{label} · HTTP {exc.status}, tekrar deneniyor")
                    time.sleep(0.4)
                    continue
                raise
            except (requests.exceptions.ProxyError, requests.exceptions.ConnectTimeout) as exc:
                last_error = exc
                if proxy is not None and self.pool is not None:
                    self.pool.mark_bad(proxy)
                    self._rotate(proxy)
                self._log("warn", f"{label} · proxy hatasi ({type(exc).__name__})")
                time.sleep(0.4)
            except requests.exceptions.RequestException as exc:
                last_error = exc
                self._log("warn", f"{label} · baglanti hatasi ({type(exc).__name__})")
                time.sleep(0.4)
        raise ClientError(f"{label} basarisiz: {last_error}")

    def download_result(
        self,
        url: str,
        headers: dict,
        label: str = "sonuc/indir",
        direct_attempts: int = 2,
        proxy_attempts: int = 2,
        timeout: tuple[int, int] = (30, 300),
    ) -> bytes:
        """Sonuc dosyasini indirir: once dogrudan, gerekirse proxy uzerinden.

        Space bazen birden fazla replica calistirir (ornegin 1 istenmis, 3 aktif).
        Dosya sadece onu ureten replica'nin /tmp + bellek kaydinda bulunur; bu
        yuzden ``/gradio_api/file=`` istegi baska bir replica'ya duserse
        ``403 File not allowed`` doner. Ayni IP'den tekrar denemek cogu zaman
        ayni replica'ya gittigi icin, kisa bir dogrudan denemeden sonra cikis
        IP'sini degistirmek (proxy) gerekir.
        """
        last: Optional[Exception] = None

        # 1) Dogrudan: proxy kotasi harcanmaz.
        for attempt in range(1, direct_attempts + 1):
            try:
                return self._fetch(url, headers, None, label, attempt, timeout)
            except HttpStatusError as exc:
                last = exc
                if not exc.retryable:
                    raise
                extra = " · dosya baska replica'da" if exc.file_not_allowed else ""
                self._log("warn", f"{label} · HTTP {exc.status}{extra}")
                if attempt < direct_attempts:
                    time.sleep(1.5)
            except requests.exceptions.RequestException as exc:
                last = exc
                self._log("warn", f"{label} · baglanti hatasi ({type(exc).__name__})")
                if attempt < direct_attempts:
                    time.sleep(0.5)

        # 2) Uretim proxy'si: farkli cikis IP'si = farkli replica.
        if self.pool is not None:
            self._log("warn", f"{label} · dogrudan alinamadi, proxy ile deneniyor")
            for attempt in range(1, proxy_attempts + 1):
                proxy = self._pick()
                if proxy is None:
                    break
                try:
                    return self._fetch(url, headers, proxy, label, attempt, timeout)
                except HttpStatusError as exc:
                    last = exc
                    if not exc.retryable:
                        raise
                    self._log("warn", f"{label} · proxy {proxy.label} · HTTP {exc.status}")
                    self._rotate(proxy)
                    time.sleep(1.5)
                except (requests.exceptions.ProxyError, requests.exceptions.ConnectTimeout) as exc:
                    last = exc
                    self.pool.mark_bad(proxy)
                    self._rotate(proxy)
                    self._log("warn", f"{label} · proxy hatasi ({type(exc).__name__})")
                    time.sleep(0.5)
                except requests.exceptions.RequestException as exc:
                    last = exc
                    self._log("warn", f"{label} · baglanti hatasi ({type(exc).__name__})")
                    time.sleep(0.5)

        if isinstance(last, HttpStatusError) and last.file_not_allowed:
            raise ClientError(
                f"{label} · dosya sunucudaki baska bir kopyada kaldi (HTTP 403 File not allowed). "
                "Sunucu birkac kopya halinde calisiyor; ayni gorseli yeniden uretin."
            )
        raise ClientError(f"{label} basarisiz: {last}")


# --------------------------------------------------------------------------- #
#  Goruntu hazirlama
# --------------------------------------------------------------------------- #


@dataclass
class PreparedImage:
    path: str
    data_url: str
    note: str = ""


def prepare_image(path: str, optimize: bool = True, max_side: int = 2048, quality: int = 92) -> PreparedImage:
    """Dosyayi tarayicinin FileReader ciktisi gibi ``data:image/...;base64,...`` yapar."""
    from PIL import Image

    with open(path, "rb") as fh:
        raw = fh.read()

    with Image.open(io.BytesIO(raw)) as im:
        im.load()
        fmt = (im.format or "").upper()
        mime = {
            "JPEG": "image/jpeg",
            "PNG": "image/png",
            "WEBP": "image/webp",
            "GIF": "image/gif",
        }.get(fmt)

        if not optimize and mime is not None:
            return PreparedImage(path, f"data:{mime};base64," + base64.b64encode(raw).decode("ascii"))

        big = max(im.size) > max_side
        heavy = len(raw) > 4 * 1024 * 1024
        if not optimize and not big and mime is None:
            # Sunucunun tanimadigi format (bmp/tiff/...): PNG'ye cevir.
            buf = io.BytesIO()
            im.save(buf, "PNG")
            return PreparedImage(path, "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii"), "PNG'ye cevrildi")

        if optimize and (big or heavy or mime is None):
            work = im
            if work.mode in ("RGBA", "LA") or (work.mode == "P" and "transparency" in work.info):
                work = work.convert("RGBA")
                bg = Image.new("RGB", work.size, (255, 255, 255))
                bg.paste(work, mask=work.split()[-1])
                work = bg
            elif work.mode != "RGB":
                work = work.convert("RGB")
            if big:
                work.thumbnail((max_side, max_side), Image.LANCZOS)
            buf = io.BytesIO()
            work.save(buf, "JPEG", quality=quality, optimize=True)
            note = f"{work.width}x{work.height} JPEG"
            return PreparedImage(path, "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii"), note)

    # Optimize kapali ve format zaten destekli.
    return PreparedImage(path, f"data:{mime};base64," + base64.b64encode(raw).decode("ascii"))


# --------------------------------------------------------------------------- #
#  Gradio akisi
# --------------------------------------------------------------------------- #


@dataclass
class GenerationResult:
    image_bytes: bytes
    image_url: str
    stats: str = ""
    prompt_used: str = ""
    thinking: str = ""
    seed: Optional[int] = None
    elapsed: float = 0.0
    proxy_log: list[str] = field(default_factory=list)


class MiniMaxH3Client:
    def __init__(
        self,
        proxy_pool: Optional[ProxyPool] = None,
        proxy_file: Optional[str] = None,
        on_log: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self.on_log = on_log or (lambda level, msg: None)
        self.pool = proxy_pool
        if self.pool is None and proxy_file:
            self.pool = ProxyPool(proxy_file)
        self.on_log("info", f"Proxy havuzu: {len(self.pool)} adet" if self.pool else "Proxy KAPALI (dogrudan baglanti)")
        self.transport = RotatingTransport(self.pool, on_log=self.on_log)
        self.session_hash = ""
        self.trace: list[str] = []

    # -- yardimcilar ------------------------------------------------------ #

    def _log(self, level: str, msg: str) -> None:
        self.on_log(level, msg)

    def _headers(self, sse: bool = False) -> dict[str, str]:
        headers = {
            "accept": "text/event-stream" if sse else "*/*",
            "accept-language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            "content-type": "application/json",
            "origin": BASE_URL,
            "referer": BASE_URL + "/?__theme=system",
            "user-agent": DEFAULT_UA,
            "x-gradio-server": BASE_URL + "/",
            "x-gradio-user": "app",
        }
        return headers

    def _join(self, fn_index: int, data: list, event_data, label: str) -> str:
        payload = {
            "data": data,
            "event_data": event_data,
            "fn_index": fn_index,
            "trigger_id": 6,
            "session_hash": self.session_hash,
        }
        resp = self.transport.post_json(QUEUE_JOIN, payload, self._headers(), label=label)
        event_id = resp.json().get("event_id")
        if not event_id:
            raise ClientError(f"Sunucu event_id dondurmedi: {resp.text[:300]}")
        self._log("info", f"{label} · event {event_id[:12]}… kuyruga alindi")
        return event_id

    @staticmethod
    def _flatten_strings(value, depth: int = 0) -> list[str]:
        if depth > 6:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, (list, tuple)):
            out: list[str] = []
            for item in value:
                out.extend(MiniMaxH3Client._flatten_strings(item, depth + 1))
            return out
        return []

    def _progress_text(self, message: dict, exclude: str) -> Optional[str]:
        data = (message.get("output") or {}).get("data") or []
        if not data:
            return None
        strings = [
            s.strip()
            for s in self._flatten_strings(data[0])
            if s and s.strip() and len(s) <= 160 and s.strip() != exclude
        ]
        return strings[-1] if strings else None

    def _open_stream(self) -> StreamHandle:
        return self.transport.open_sse(
            QUEUE_DATA + "?session_hash=" + self.session_hash,
            {**self._headers(), "accept": "text/event-stream"},
            timeout=(30, 1800),
            label="queue/sse",
        )

    def _wait(self, stream: StreamHandle, event_id: str, exclude_prompt: str) -> dict:
        try:
            return self._wait_inner(stream, event_id, exclude_prompt)
        except requests.exceptions.RequestException as exc:
            raise ClientError(f"SSE baglantisi koptu: {exc}") from exc

    def _wait_inner(self, stream: StreamHandle, event_id: str, exclude_prompt: str) -> dict:
        for raw in stream:
            if not raw:
                continue
            line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload:
                continue
            try:
                message = json.loads(payload)
            except json.JSONDecodeError:
                continue

            kind = message.get("msg")
            if kind == "heartbeat":
                continue
            if kind == "queue_full":
                raise ClientError("Kuyruk dolu, biraz sonra tekrar deneyin.")
            if kind == "close_stream":
                raise ClientError("Sunucu akisi beklenmeden kapatti.")
            if message.get("event_id") != event_id:
                continue

            if kind == "process_generating":
                text = self._progress_text(message, exclude_prompt)
                if text:
                    self._log("status", text)
            elif kind == "process_completed":
                if not message.get("success", True):
                    detail = message.get("output")
                    text = ""
                    if isinstance(detail, dict):
                        text = str(detail.get("error") or detail.get("title") or detail)
                    else:
                        text = str(detail or message.get("title") or "bilinmeyen hata")
                    raise ClientError(f"Sunucu islemi basarisiz: {text[:800]}")
                return message
        raise ClientError("SSE akisi beklenmeden sona erdi.")

    # -- ana akis --------------------------------------------------------- #

    def generate(
        self,
        image_paths: Iterable[str],
        prompt: str,
        aspect: str = "auto",
        resolution: str = "4 MP",
        enhance: bool = False,
        randomize: bool = True,
        seed: int = 0,
        reasoning_effort: str = "low",
        optimize_images: bool = True,
    ) -> GenerationResult:
        started = time.time()
        prompt = (prompt or "").strip()
        if not prompt:
            raise ClientError("Prompt bos olamaz.")
        if aspect not in ASPECTS:
            aspect = "auto"
        if resolution not in RESOLUTIONS:
            resolution = "4 MP"
        if reasoning_effort not in EFFORTS:
            reasoning_effort = "low"

        paths = [p for p in image_paths if p][:MAX_IMAGES]
        self.session_hash = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
        self._log("info", f"Oturum {self.session_hash} · {len(paths)} fotograf · {resolution} · {aspect}")

        prepared: list[PreparedImage] = []
        for path in paths:
            item = prepare_image(path, optimize=optimize_images)
            prepared.append(item)
            size_kb = len(item.data_url) * 3 // 4 // 1024
            note = f" ({item.note})" if item.note else ""
            self._log("info", f"Fotograf hazir: {os.path.basename(path)} · ~{size_kb} KB{note}")

        state = {
            "prompt": prompt,
            "aspect": aspect,
            "resolution": resolution,
            "enhance": bool(enhance),
            "images": [p.data_url for p in prepared],
        }

        # Bu uretim boyunca tek proxy kullanilir; yeni uretimde havuzdan sonraki alinir.
        self.transport.begin_run()

        # 1) studio: prompt kodlama + plan (fn_index 1)
        self._log("status", "1/3 · Prompt kodlaniyor ve plan hazirlaniyor…")
        event_id = self._join(1, [state, int(seed), bool(randomize), reasoning_effort], None, "studio/join")

        # Each join needs its own SSE connection (HAR: entries 7 and 12 are separate
        # /queue/data requests; the server closes the stream after the event).
        stream = self._open_stream()
        try:
            studio = self._wait(stream, event_id, prompt)
        finally:
            stream.close()

        studio_data = (studio.get("output") or {}).get("data") or []
        prompt_used = studio_data[1] if len(studio_data) > 1 and isinstance(studio_data[1], str) else prompt
        thinking = studio_data[2] if len(studio_data) > 2 and isinstance(studio_data[2], str) else ""
        used_seed = studio_data[3] if len(studio_data) > 3 else seed
        self._log("ok", f"Studio tamam · seed {used_seed}")

        # 2) render: plan sunucu state'inden okunur, bu yuzden [null] gonderilir.
        self._log("status", "2/3 · Gorsel uretiliyor… (bu adim 10-120 sn surebilir)")
        render_id = self._join(2, [None], None, "render/join")
        stream = self._open_stream()
        try:
            render = self._wait(stream, render_id, prompt)
        finally:
            stream.close()

        render_data = (render.get("output") or {}).get("data") or []
        if not render_data:
            raise ClientError("Render sonucu bos dondu.")
        image = render_data[0]
        if not isinstance(image, dict):
            raise ClientError(f"Beklenmeyen sonuc bicimi: {str(image)[:300]}")
        url = image.get("url")
        path = image.get("path")
        if not url:
            if not path:
                raise ClientError("Sonuc gorseli icin URL/path yok.")
            url = BASE_URL + "/gradio_api/file=" + (path if str(path).startswith("/") else "/" + str(path))

        # 4) sonucu indir: once dogrudan (proxy kotasi harcanmaz), 403 olursa
        #    uretim proxy'si ile yedek deneme (baska replica'ya dusurmek icin)
        self._log("status", "3/3 · Sonuc indiriliyor…")
        data = self.transport.download_result(
            url,
            {
                "accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "referer": BASE_URL + "/?__theme=system",
                "user-agent": DEFAULT_UA,
            },
            label="sonuc/indir",
        )

        stats = render_data[1] if len(render_data) > 1 and isinstance(render_data[1], str) else ""
        elapsed = time.time() - started
        self._log("ok", f"Tamamlandi · {len(data) / 1024 / 1024:.1f} MB · {elapsed:.1f} sn")

        return GenerationResult(
            image_bytes=data,
            image_url=url,
            stats=stats,
            prompt_used=prompt_used,
            thinking=thinking,
            seed=int(used_seed) if isinstance(used_seed, (int, float)) else None,
            elapsed=elapsed,
            proxy_log=[f"{p.label}" for p in self.transport.used],
        )


# --------------------------------------------------------------------------- #
#  CLI (UI olmadan hizli test)
# --------------------------------------------------------------------------- #


def _cli() -> int:
    import argparse

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="MiniMax H3 Image istemcisi (HAR'dan reverse edildi)")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--image", action="append", default=[], help="Referans fotograf (en fazla 8)")
    parser.add_argument("--aspect", default="auto", choices=ASPECTS)
    parser.add_argument("--resolution", default="4 MP", choices=RESOLUTIONS)
    parser.add_argument("--enhance", action="store_true")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--no-randomize", action="store_true")
    parser.add_argument("--effort", default="low", choices=EFFORTS)
    parser.add_argument("--no-proxy", action="store_true")
    parser.add_argument("--proxy-file", default=None)
    parser.add_argument("--optimize", action="store_true", default=True)
    parser.add_argument("--no-optimize", dest="optimize", action="store_false")
    parser.add_argument("--out", default="output.png")
    args = parser.parse_args()

    proxy_file = args.proxy_file or ProxyPool.find_default(os.getcwd())
    pool = None
    if not args.no_proxy:
        if not proxy_file:
            print("UYARI: proxy dosyasi bulunamadi, dogrudan baglanti kullanilacak.", flush=True)
        else:
            pool = ProxyPool(proxy_file)

    def log(level: str, msg: str) -> None:
        print(f"[{level:6}] {msg}", flush=True)

    client = MiniMaxH3Client(proxy_pool=pool, on_log=log)
    result = client.generate(
        args.image,
        args.prompt,
        aspect=args.aspect,
        resolution=args.resolution,
        enhance=args.enhance,
        randomize=not args.no_randomize,
        seed=args.seed,
        reasoning_effort=args.effort,
        optimize_images=args.optimize,
    )
    with open(args.out, "wb") as fh:
        fh.write(result.image_bytes)
    print(f"\nKaydedildi: {os.path.abspath(args.out)}")
    print(f"stats: {result.stats} | seed: {result.seed} | sure: {result.elapsed:.1f}s")
    print(f"proxy sirasi: {', '.join(result.proxy_log)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
