"""FLUX.3 Image Klein (Black Forest Labs) HF Space istemcisi.

Kaynak: ``huggingface.co.flux3.klein.har``
Space: https://huggingface.co/spaces/black-forest-labs/flux-3-image-klein
Host : https://black-forest-labs-flux-3-image-klein.hf.space  (Gradio 6.30.0)

HAR uretim zinciri (bkz. docs/REVERSE.md):
  1. POST /gradio_api/queue/join?__theme=dark — fn_index=33 (/generate),
     trigger_id=31 (Generate butonu), 10 elemanli data -> {"event_id": "..."}:
     [prompt, gallery, mode, seed, randomize_seed, width, height,
      num_inference_steps, guidance_scale, prompt_upsampling]
  2. GET /gradio_api/queue/data?session_hash=... (SSE) -> process_completed
     output.data = [Image(FileData), seed, prompt_the_model_saw]
  3. GET /gradio_api/file=/tmp/gradio/<hash>/image.png -> PNG

Reference image varsa (space "up to 10" destekler):
  POST /gradio_api/upload?upload_id=<id> (multipart, alan "files")
  -> ["/tmp/gradio/<hash>/<ad>"] -> gallery ogeleri
  [{"image": FileData, "caption": null}, ...]

Atlanan UI-only join'ler: fn 34 (/describe_result), fn 32 (/boxes_toggle),
fn 30 (/use_as_reference), fn 25 (/sync_references), fn 27/28 (/set_aspect),
fn 29 (/update_steps_from_mode), /component_server (/get_app_version).

10 parametrenin sirasi canli /gradio_api/info (/generate) ve /config
inputs [23,27,28,35,36,39,40,43,44,33] ile dogrulandi.

REVERSE.md: x-zerogpu-* / x-gradio-user / x-mfn-sid / cookie / Authorization
GONDERILMEZ.
"""

from __future__ import annotations

import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
from paths import ROOT_DIR, CONFIG_DIR, DATA_DIR, OUTPUT_DIR, SETTINGS_DIR, PROXY_FILE

import json
import os
import random
import string
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import requests

from clients.hf_image_client import ClientError, DEFAULT_UA, ProxyPool, RotatingTransport

BASE_URL = "https://black-forest-labs-flux-3-image-klein.hf.space"
SPACE_ID = "black-forest-labs/flux-3-image-klein"

UPLOAD_URL = BASE_URL + "/gradio_api/upload"
QUEUE_JOIN = BASE_URL + "/gradio_api/queue/join?__theme=dark"
QUEUE_DATA = BASE_URL + "/gradio_api/queue/data"

FN_GENERATE = 33
TRIGGER_GENERATE = 31

MODE_DISTILLED = "Distilled (16 steps)"
MODE_BASE = "Base (50 steps)"
MODES = [MODE_DISTILLED, MODE_BASE]

ASPECTS = ["1:1", "4:3", "3:4", "3:2", "2:3", "16:9", "9:16"]
RESOLUTIONS = ["1K", "2K", "4K"]
RESOLUTION_BASE = {"1K": 1024, "2K": 2048, "4K": 4096}

MIN_SIZE, MAX_SIZE, SIZE_STEP = 256, 4096, 16
MIN_STEPS, MAX_STEPS = 1, 50
SEED_MAX = 2147483647


@dataclass
class ImageResult:
    image_bytes: bytes
    image_url: str
    prompt: str = ""
    used_prompt: str = ""
    seed: Optional[int] = None
    elapsed: float = 0.0
    proxy_log: list[str] = field(default_factory=list)

    @property
    def size_kb(self) -> float:
        return len(self.image_bytes) / 1024


@dataclass
class PreparedUpload:
    path: str
    filename: str
    raw: bytes
    mime: str


def _random_id(length: int) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def prepare_upload(path: str) -> PreparedUpload:
    with open(path, "rb") as fh:
        raw = fh.read()
    base = os.path.basename(path)
    mime = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(os.path.splitext(base)[1].lower(), "image/png")
    return PreparedUpload(path, base, raw, mime)


def size_from(aspect: str, resolution: str) -> tuple[int, int]:
    """Aspect/Resolution seciminden /generate width/height uretir (space UI mantigi)."""
    base = RESOLUTION_BASE.get(str(resolution).upper(), 2048)
    try:
        w, h = (int(v) for v in str(aspect).split(":"))
    except (ValueError, TypeError):
        w, h = 1, 1
    width = base if w >= h else max(SIZE_STEP, round(base * w / h / SIZE_STEP) * SIZE_STEP)
    height = base if h >= w else max(SIZE_STEP, round(base * h / w / SIZE_STEP) * SIZE_STEP)
    return width, height


def build_generate_data(prompt: str, gallery: list, mode: str, seed: int,
                        randomize_seed: bool, width: int, height: int,
                        steps: int, guidance: float, prompt_upsampling: bool) -> list:
    """/generate (fn 33) icin 10 elemanli data; sira HAR ile ayni."""
    return [
        str(prompt), gallery, str(mode), int(seed), bool(randomize_seed),
        int(width), int(height), int(steps), float(guidance), bool(prompt_upsampling),
    ]


class Flux3Client:
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
        # x-zerogpu-* / x-gradio-user / x-mfn-sid / cookie / auth eklenmez.
        return headers

    def _join(self, data: list, label: str) -> str:
        # HAR'daki fn 33 join govdesinde event_data alani yok, trigger_id var.
        payload = {
            "data": data, "fn_index": FN_GENERATE,
            "trigger_id": TRIGGER_GENERATE, "session_hash": self.session_hash,
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
            self._headers(sse=True), timeout=(30, 3600), label="queue/sse",
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
                return Flux3Client._find_image(node["value"], depth + 1)
            url = str(node.get("url") or "")
            path = str(node.get("path") or "")
            mime = str(node.get("mime_type") or node.get("mime") or "")
            if (any(k in f"{url} {path}".lower() for k in (".png", ".jpg", ".jpeg", ".webp"))
                    or mime.startswith("image/")):
                return node
            for value in node.values():
                found = Flux3Client._find_image(value, depth + 1)
                if found:
                    return found
        elif isinstance(node, (list, tuple)):
            for item in node:
                found = Flux3Client._find_image(item, depth + 1)
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

    def upload(self, prepared: PreparedUpload) -> dict:
        upload_id = _random_id(10)
        resp = self.transport.post_multipart(
            f"{UPLOAD_URL}?upload_id={upload_id}",
            {"files": (prepared.filename, prepared.raw, prepared.mime)},
            headers={"accept": "*/*", "origin": BASE_URL,
                     "referer": BASE_URL + "/?__theme=dark", "user-agent": DEFAULT_UA},
            label="referans/yukleme",
        )
        try:
            paths = resp.json()
        except ValueError:
            raise ClientError(f"Yukleme yaniti okunamadi: {resp.text[:300]}")
        if not isinstance(paths, list) or not paths:
            raise ClientError(f"Yukleme yolu donmedi: {str(paths)[:300]}")
        path = str(paths[0])
        self._log("ok", f"Referans yuklendi · {prepared.filename}")
        return {
            "image": {
                "path": path,
                "url": BASE_URL + "/gradio_api/file=" + path,
                "orig_name": prepared.filename,
                "size": len(prepared.raw),
                "mime_type": prepared.mime,
                "is_stream": False,
                "meta": {"_type": "gradio.FileData"},
            },
            "caption": None,
        }

    def _run_generate(self, data: list, attempts: int = 3) -> list:
        """ZeroGPU kotasi dolarsa proxy degistirip tekrar dener (istek durumsuz)."""
        for attempt in range(1, attempts + 1):
            try:
                event_id = self._join(data, "generate/join")
                stream = self._open_stream()
                try:
                    message = self._wait(stream, event_id)
                finally:
                    stream.close()
                return (message.get("output") or {}).get("data") or []
            except ClientError as exc:
                text = str(exc).lower()
                if attempt >= attempts or not ("quota" in text and "gpu" in text):
                    raise
                self._log("warn", f"ZeroGPU kotasi doldu · yeni proxy ile tekrar deneniyor "
                                  f"({attempt + 1}/{attempts})")
                self.transport._rotate(getattr(self.transport, "_leased", None))

    def generate(self, prompt: str, image_paths: Optional[list[str]] = None,
                 mode: str = MODE_DISTILLED, seed: int = 0, randomize_seed: bool = True,
                 width: int = 2048, height: int = 2048,
                 steps: int = 16, guidance_scale: float = 1.0,
                 prompt_upsampling: bool = True) -> ImageResult:
        """Metinden / referansli gorsel uretimi: /generate (fn 33) -> PNG."""
        started = time.time()
        if not (prompt or "").strip():
            raise ClientError("Prompt bos olamaz.")
        if str(mode) not in MODES:
            raise ClientError(f"Model secenekleri: {', '.join(MODES)}.")
        for name, value, lo, hi in (("width", width, MIN_SIZE, MAX_SIZE),
                                     ("height", height, MIN_SIZE, MAX_SIZE),
                                     ("steps", steps, MIN_STEPS, MAX_STEPS)):
            if not (lo <= int(value) <= hi):
                raise ClientError(f"{name} {lo}-{hi} araliginda olmali.")
        if not (0 <= float(guidance_scale) <= 10):
            raise ClientError("Guidance 0-10 araliginda olmali.")
        if not (0 <= int(seed) <= SEED_MAX):
            raise ClientError(f"Seed 0-{SEED_MAX} araliginda olmali.")

        self.session_hash = _random_id(10)
        self.transport.begin_run()
        self._log("info", f"Oturum {self.session_hash} · {SPACE_ID} · "
                          f"{int(width)}x{int(height)} · {mode} · {int(steps)} step")

        gallery: list[dict] = []
        paths = [p for p in (image_paths or []) if p]
        if len(paths) > 10:
            raise ClientError("En fazla 10 referans gorsel eklenebilir.")
        for p in paths:
            if not os.path.exists(p):
                raise ClientError(f"Referans gorsel bulunamadi: {p}")
            gallery.append(self.upload(prepare_upload(p)))

        data = build_generate_data(
            prompt.strip(), gallery, mode, seed, randomize_seed,
            width, height, steps, guidance_scale, prompt_upsampling,
        )
        self._log("info", f"join · fn_index={FN_GENERATE} · {len(data)} parametre")
        self._log("status", "Görsel üretiliyor… (30-120 sn)")
        output = self._run_generate(data)

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
        used_prompt = ""
        for value in output:
            if isinstance(value, dict) and value.get("__type__") == "update" and isinstance(value.get("value"), str):
                used_prompt = value["value"]
                break
            if isinstance(value, str) and value.strip():
                used_prompt = value
                break
        elapsed = time.time() - started
        self._log("ok", f"Tamamlandı · {len(image_bytes) / 1024:.0f} KB · {elapsed:.1f} sn"
                        + (f" · seed {used_seed}" if used_seed is not None else ""))
        return ImageResult(image_bytes=image_bytes, image_url=url, prompt=prompt.strip(),
                           used_prompt=used_prompt, seed=used_seed, elapsed=elapsed,
                           proxy_log=[p.label for p in self.transport.used])


def _cli() -> int:
    import argparse
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="FLUX.3 Image Klein istemcisi (HAR'dan reverse edildi)")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--image", action="append", default=[], help="referans gorsel (en fazla 10)")
    parser.add_argument("--mode", default=MODE_DISTILLED, choices=MODES)
    parser.add_argument("--aspect", default="1:1", choices=ASPECTS)
    parser.add_argument("--resolution", default="2K", choices=RESOLUTIONS)
    parser.add_argument("--width", type=int, default=None)
    parser.add_argument("--height", type=int, default=None)
    parser.add_argument("--steps", type=int, default=16)
    parser.add_argument("--guidance", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--no-randomize", action="store_true")
    parser.add_argument("--no-upsampling", action="store_true")
    parser.add_argument("--no-proxy", action="store_true")
    parser.add_argument("--proxy-file", default=None)
    parser.add_argument("--out", default="outputs")
    args = parser.parse_args()

    pool = None
    if not args.no_proxy:
        pf = args.proxy_file or ProxyPool.find_default(os.getcwd())
        if pf:
            pool = ProxyPool(pf)
    client = Flux3Client(proxy_pool=pool, on_log=lambda lv, m: print(f"{lv:6} {m}"))
    width, height = args.width, args.height
    if width is None or height is None:
        width, height = size_from(args.aspect, args.resolution)
    result = client.generate(
        args.prompt, image_paths=args.image, mode=args.mode,
        seed=args.seed, randomize_seed=not args.no_randomize,
        width=width, height=height, steps=args.steps, guidance_scale=args.guidance,
        prompt_upsampling=not args.no_upsampling,
    )
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"flux3_{time.strftime('%Y%m%d_%H%M%S')}.png")
    with open(path, "wb") as fh:
        fh.write(result.image_bytes)
    print(f"Kaydedildi: {path} · {result.size_kb:.0f} KB · seed {result.seed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
