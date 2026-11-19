"""Z-Image-Turbo (mrfakename) HF Space istemcisi.

Kaynak: ``huggingface.co.z.image.har``
Space: https://huggingface.co/spaces/mrfakename/Z-Image-Turbo
Host : https://mrfakename-z-image-turbo.hf.space  (Gradio 6.20.0)

HAR uretim zinciri (bkz. docs/REVERSE.md):
  1. POST /gradio_api/queue/join?__theme=dark
     fn_index=3 (/generate_image), trigger_id=16,
     data=[prompt, height, width, num_inference_steps, seed, randomize_seed]
     -> {"event_id": "..."}
  2. GET /gradio_api/queue/data?session_hash=... (SSE) -> process_completed
  3. GET /gradio_api/file=/tmp/gradio/<hash>/image.png -> PNG

Atlanan istekler (UI-only): fn_index=2 (_start_timer, data=[]) ve
fn_index=4 (_show_took, data=[null]). Bunlar yalnizca sure gostergesini
gunceller, uretimi etkilemez.

REVERSE.md kurallari: x-zerogpu-* / x-gradio-user / x-mfn-sid / cookie /
Authorization GONDERILMEZ. Yalnizca accept, accept-language, origin,
referer, user-agent, content-type.
"""

from __future__ import annotations

import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
from paths import ROOT_DIR, CONFIG_DIR, DATA_DIR, OUTPUT_DIR, SETTINGS_DIR, PROXY_FILE

import json
import random
import string
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import requests

from clients.hf_image_client import ClientError, DEFAULT_UA, ProxyPool, RotatingTransport

BASE_URL = "https://mrfakename-z-image-turbo.hf.space"
SPACE_ID = "mrfakename/Z-Image-Turbo"

QUEUE_JOIN = BASE_URL + "/gradio_api/queue/join?__theme=dark"
QUEUE_DATA = BASE_URL + "/gradio_api/queue/data"

FN_GENERATE = 3
TRIGGER_ID = 16

MIN_SIZE, MAX_SIZE, SIZE_STEP = 512, 2048, 64
MIN_STEPS, MAX_STEPS = 1, 20


@dataclass
class ImageResult:
    image_bytes: bytes
    image_url: str
    prompt: str = ""
    seed: Optional[int] = None
    elapsed: float = 0.0
    proxy_log: list[str] = field(default_factory=list)

    @property
    def size_kb(self) -> float:
        return len(self.image_bytes) / 1024


def _random_id(length: int) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def build_generate_data(prompt: str, height: int, width: int,
                        steps: int, seed: int, randomize_seed: bool) -> list:
    """/generate_image icin 6 elemanli data dizisi (fn_index 3).

    Sira /gradio_api/info parametre sirasi ve /config inputs listesi
    [4(prompt), 7(height), 8(width), 10(steps), 13(seed), 12(randomize)]
    ile dogrulandi. HAR'daki gercek dizi: ["sample prompt",1024,1024,9,42,true].
    """
    return [prompt, int(height), int(width), int(steps), int(seed), bool(randomize_seed)]


class ZImageClient:
    def __init__(self, proxy_pool: Optional[ProxyPool] = None,
                 proxy_file: Optional[str] = None,
                 on_log: Optional[Callable[[str, str], None]] = None) -> None:
        self.on_log = on_log or (lambda level, msg: None)
        self.pool = proxy_pool
        if self.pool is None and proxy_file:
            self.pool = ProxyPool(proxy_file)
        self.on_log("info", f"Proxy havuzu: {len(self.pool)} adet" if self.pool
                    else "Proxy KAPALI (dogrudan baglanti)")
        self.transport = RotatingTransport(self.pool, on_log=self.on_log)
        self.session_hash = ""

    def _log(self, level: str, msg: str) -> None:
        self.on_log(level, msg)

    def _headers(self, sse: bool = False) -> dict[str, str]:
        headers = {
            "accept": "text/event-stream" if sse else "*/*",
            "accept-language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            "origin": BASE_URL,
            "referer": BASE_URL + "/?__theme=dark",
            "user-agent": DEFAULT_UA,
        }
        if not sse:
            headers["content-type"] = "application/json"
        # x-zerogpu-*, x-gradio-user, x-mfn-sid, cookie, auth bilincli olarak eklenmez.
        return headers

    def _join(self, data: list, label: str) -> str:
        payload = {
            "data": data,
            "event_data": None,
            "fn_index": FN_GENERATE,
            "trigger_id": TRIGGER_ID,
            "session_hash": self.session_hash,
        }
        resp = self.transport.post_json(QUEUE_JOIN, payload, self._headers(), label=label)
        try:
            event_id = resp.json().get("event_id")
        except ValueError:
            raise ClientError(f"Kuyruk yaniti okunamadi: {resp.text[:300]}")
        if not event_id:
            raise ClientError(f"Sunucu event_id dondurmedi: {resp.text[:300]}")
        self._log("info", f"{label} · event {event_id[:12]}… kuyruga alindi")
        return event_id

    def _open_stream(self):
        return self.transport.open_sse(
            QUEUE_DATA + "?session_hash=" + self.session_hash,
            self._headers(sse=True), timeout=(30, 1800), label="queue/sse",
        )

    def _wait(self, stream, event_id: str) -> dict:
        try:
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
                if kind in ("heartbeat", "close_stream"):
                    continue
                if kind == "queue_full":
                    raise ClientError("Kuyruk dolu, biraz sonra tekrar deneyin.")
                if message.get("event_id") != event_id:
                    continue
                if kind == "estimation":
                    eta = message.get("rank_eta")
                    rank = message.get("rank")
                    if rank is not None:
                        extra = f" · tahmini {eta:.0f} sn" if isinstance(eta, (int, float)) else ""
                        self._log("status", f"Kuyrukta {rank}. sıra{extra}")
                elif kind == "process_completed":
                    if not message.get("success", True):
                        detail = message.get("output")
                        text = str(detail.get("error") or detail.get("title") or detail) \
                            if isinstance(detail, dict) else str(detail or "bilinmeyen hata")
                        raise ClientError(f"Sunucu islemi basarisiz: {text[:800]}")
                    return message
        except requests.exceptions.RequestException as exc:
            raise ClientError(f"SSE baglantisi koptu: {exc}") from exc
        raise ClientError("SSE akisi beklenmeden sona erdi.")

    @staticmethod
    def _find_image(node, depth: int = 0) -> Optional[dict]:
        if depth > 8:
            return None
        if isinstance(node, dict):
            if node.get("__type__") == "update" and "value" in node:
                return ZImageClient._find_image(node["value"], depth + 1)
            url = str(node.get("url") or "")
            path = str(node.get("path") or "")
            mime = str(node.get("mime_type") or node.get("mime") or "")
            if (any(k in f"{url} {path}".lower() for k in (".png", ".jpg", ".jpeg", ".webp"))
                    or mime.startswith("image/")):
                return node
            for value in node.values():
                found = ZImageClient._find_image(value, depth + 1)
                if found:
                    return found
        elif isinstance(node, (list, tuple)):
            for item in node:
                found = ZImageClient._find_image(item, depth + 1)
                if found:
                    return found
        return None

    @staticmethod
    def _file_url(image: dict) -> str:
        url = image.get("url")
        if url:
            return str(url)
        path = image.get("path")
        if not path:
            raise ClientError("Sonuc gorseli icin URL/path yok.")
        return BASE_URL + "/gradio_api/file=" + (str(path) if str(path).startswith("/") else "/" + str(path))

    def generate(self, prompt: str, height: int = 1024, width: int = 1024,
                 steps: int = 9, seed: int = 42, randomize_seed: bool = True) -> ImageResult:
        """Metinden gorsel: /generate_image (fn_index 3)."""
        started = time.time()
        if not (prompt or "").strip():
            raise ClientError("Prompt bos olamaz.")

        def clamp(v, lo, hi):
            return max(lo, min(hi, int(v)))

        height = clamp(height, MIN_SIZE, MAX_SIZE)
        width = clamp(width, MIN_SIZE, MAX_SIZE)
        steps = clamp(steps, MIN_STEPS, MAX_STEPS)

        self.session_hash = _random_id(10)
        self.transport.begin_run()
        self._log("info", f"Oturum {self.session_hash} · {SPACE_ID} · "
                          f"{width}x{height} · {steps} step · "
                          f"seed={'rastgele' if randomize_seed else seed}")

        data = build_generate_data(prompt.strip(), height, width, steps, seed, randomize_seed)
        self._log("info", f"join · fn_index={FN_GENERATE} · {len(data)} parametre · {data}")
        self._log("status", "Görsel üretiliyor… (birkaç saniye sürebilir)")
        event_id = self._join(data, "generate/join")
        stream = self._open_stream()
        try:
            completed = self._wait(stream, event_id)
        finally:
            stream.close()

        output = (completed.get("output") or {}).get("data") or []
        image = self._find_image(output)
        if not image:
            raise ClientError(f"Gorsel ciktisi bulunamadi: {str(output)[:400]}")
        url = self._file_url(image)
        self._log("status", "Sonuc indiriliyor…")
        image_bytes = self.transport.download_result(
            url,
            {"accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
             "referer": BASE_URL + "/?__theme=dark", "user-agent": DEFAULT_UA},
            label="gorsel/indir",
        )

        used_seed = None
        for value in output:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                used_seed = int(value)
                break
        elapsed = time.time() - started
        self._log("ok", f"Tamamlandı · {len(image_bytes) / 1024:.0f} KB · {elapsed:.1f} sn"
                        + (f" · seed {used_seed}" if used_seed is not None else ""))
        return ImageResult(image_bytes=image_bytes, image_url=url, prompt=prompt.strip(),
                           seed=used_seed, elapsed=elapsed,
                           proxy_log=[p.label for p in self.transport.used])


def _cli() -> int:
    import argparse

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Z-Image-Turbo istemcisi (HAR'dan reverse edildi)")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--steps", type=int, default=9)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--randomize", action="store_true", default=True)
    parser.add_argument("--no-randomize", dest="randomize", action="store_false")
    parser.add_argument("--proxy-file", default=None)
    parser.add_argument("--no-proxy", action="store_true")
    parser.add_argument("--out", default="outputs")
    args = parser.parse_args()

    pool = None
    if not args.no_proxy:
        pf = args.proxy_file or ProxyPool.find_default(os.getcwd())
        if pf:
            pool = ProxyPool(pf)
    client = ZImageClient(proxy_pool=pool, on_log=lambda lv, m: print(f"{lv:6} {m}"))
    result = client.generate(args.prompt, height=args.height, width=args.width,
                             steps=args.steps, seed=args.seed, randomize_seed=args.randomize)
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"zimage_{time.strftime('%Y%m%d_%H%M%S')}.png")
    with open(path, "wb") as fh:
        fh.write(result.image_bytes)
    print(f"Kaydedildi: {path} · {result.size_kb:.0f} KB · seed {result.seed}")
    return 0


if __name__ == "__main__":
    import sys as _s
    raise SystemExit(_cli())
