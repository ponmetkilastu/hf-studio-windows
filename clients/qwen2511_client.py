"""Qwen Image Edit 2511 Rapid AIO LoRAs HF Space istemcisi.

Kaynak: ``huggingface.co.qwen.2511.edit.har``
Space: https://huggingface.co/spaces/aet256/Qwen-Image-Edit-Rapid-AIO-Loras-Experimental
Host : https://aet256-qwen-image-edit-rapid-aio-loras-experimental.hf.space
       (Gradio 6.28.0)

HAR uretim zinciri (bkz. docs/REVERSE.md):
  1. POST /gradio_api/upload?upload_id=<id> — multipart, alan "files"
     -> ["/tmp/gradio/<hash>/<ad>"]
  2. POST /gradio_api/queue/join?__theme=dark — fn_index=1 (/infer),
     trigger_id=11 (Edit Image butonu), 19 elemanli data -> {"event_id": "..."}
  3. GET /gradio_api/queue/data?session_hash=... (SSE) -> process_completed
     output.data = [Image(FileData), kullanilan_seed]
  4. GET /gradio_api/file=/tmp/gradio/<hash>/image.png -> PNG

Atlanan UI-only join'ler: fn 0 (/on_lora_change_ui), fn 2/3/4 (ciktiyi
Image1/Image2/Extra'a tasima), fn 5 (/add_derived_ref) ve
GET /gradio_api/upload_progress (SSE, yalnizca yukleme ilerlemesi).

19 parametrenin sirasi HAR icindeki HTML'den cikarilan /config dependencies[1]
inputs [7,8,9,10,22,30,31,32,33,34,41,42,43,35,36,37,38,39,40] ve canli
/gradio_api/info (/infer) ile dogrulandi.

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

BASE_URL = "https://aet256-qwen-image-edit-rapid-aio-loras-experimental.hf.space"
SPACE_ID = "aet256/Qwen-Image-Edit-Rapid-AIO-Loras-Experimental"

UPLOAD_URL = BASE_URL + "/gradio_api/upload"
QUEUE_JOIN = BASE_URL + "/gradio_api/queue/join?__theme=dark"
QUEUE_DATA = BASE_URL + "/gradio_api/queue/data"

FN_INFER = 1
TRIGGER_INFER = 11

LORAS = [
    "None", "Consistance", "Semirealistic-photo-detailer", "AnyPose",
    "Any2Real_2601", "Hyperrealistic-Portrait", "Ultrarealistic-Portrait",
    "BFS-Best-FaceSwap", "BFS-Best-FaceSwap-merge", "F2P", "Multiple-Angles",
    "Light-Restoration", "Relight", "Multi-Angle-Lighting", "Edit-Skin",
    "Next-Scene", "Flat-Log", "Upscale-Image", "Upscale2K",
]
DECODERS = ["qwen", "wan2x"]
RESOLUTION_MULTIPLES = [32, 56, 112]
SEED_MAX = 2147483647


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


def build_infer_data(image1: dict, image2: Optional[dict], extras: list, prompt: str,
                     lora: str, seed: int, randomize_seed: bool, guidance: float,
                     steps: int, target_mp: float, extras_condition_only: bool,
                     pad_to_canvas: bool, vae_tiling: bool, resolution_multiple: int,
                     vae_ref_mp: float, decoder: str, keep_2x: bool,
                     highlight_protection: bool, highlight_strength: float) -> list:
    """/infer (fn 1) icin 19 elemanli data; sira HAR/config inputs ile ayni."""
    return [
        image1, image2, extras, str(prompt), str(lora),
        int(seed), bool(randomize_seed), float(guidance), int(steps),
        float(target_mp), bool(extras_condition_only), bool(pad_to_canvas),
        bool(vae_tiling), int(resolution_multiple), float(vae_ref_mp),
        str(decoder), bool(keep_2x), bool(highlight_protection),
        float(highlight_strength),
    ]


class Qwen2511Client:
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

    def _upload(self, prepared: PreparedUpload) -> dict:
        upload_id = _random_id(10)
        resp = self.transport.post_multipart(
            f"{UPLOAD_URL}?upload_id={upload_id}",
            {"files": (prepared.filename, prepared.raw, prepared.mime)},
            headers={"accept": "*/*", "origin": BASE_URL,
                     "referer": BASE_URL + "/?__theme=dark", "user-agent": DEFAULT_UA},
            label="gorsel/yukleme",
        )
        try:
            paths = resp.json()
        except ValueError:
            raise ClientError(f"Yukleme yaniti okunamadi: {resp.text[:300]}")
        if not isinstance(paths, list) or not paths:
            raise ClientError(f"Yukleme yolu donmedi: {str(paths)[:300]}")
        path = str(paths[0])
        self._log("ok", f"Yuklendi · {prepared.filename}")
        return {
            "path": path,
            "url": BASE_URL + "/gradio_api/file=" + path,
            "orig_name": prepared.filename,
            "size": len(prepared.raw),
            "mime_type": prepared.mime,
            "meta": {"_type": "gradio.FileData"},
        }

    @staticmethod
    def _gallery_item(image: dict) -> dict:
        return {"image": image, "caption": None}

    def _join(self, data: list, label: str) -> str:
        # HAR'daki fn 1 join govdesinde event_data alani yok, trigger_id var.
        payload = {
            "data": data, "fn_index": FN_INFER,
            "trigger_id": TRIGGER_INFER, "session_hash": self.session_hash,
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
                return Qwen2511Client._find_image(node["value"], depth + 1)
            url = str(node.get("url") or "")
            path = str(node.get("path") or "")
            mime = str(node.get("mime_type") or node.get("mime") or "")
            if (any(k in f"{url} {path}".lower() for k in (".png", ".jpg", ".jpeg", ".webp"))
                    or mime.startswith("image/")):
                return node
            for value in node.values():
                found = Qwen2511Client._find_image(value, depth + 1)
                if found:
                    return found
        elif isinstance(node, (list, tuple)):
            for item in node:
                found = Qwen2511Client._find_image(item, depth + 1)
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

    def _run_infer(self, data: list, attempts: int = 3) -> list:
        """ZeroGPU kotasi dolarsa proxy degistirip tekrar dener (istek durumsuz)."""
        for attempt in range(1, attempts + 1):
            try:
                event_id = self._join(data, "infer/join")
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

    def generate(self, image_path: str, prompt: str, image2_path: Optional[str] = None,
                 extra_paths: Optional[list[str]] = None, lora: str = "None",
                 seed: int = 0, randomize_seed: bool = True, guidance_scale: float = 1.0,
                 steps: int = 4, target_megapixels: float = 1.0,
                 extras_condition_only: bool = True, pad_to_canvas: bool = True,
                 vae_tiling: bool = False, resolution_multiple: int = 32,
                 vae_ref_megapixels: float = 0.0, decoder_vae: str = "qwen",
                 keep_decoder_2x: bool = False, highlight_protection: bool = True,
                 highlight_protection_strength: float = 0.35) -> ImageResult:
        """Fotograf duzenleme: yukleme -> /infer (fn 1) -> PNG indirme."""
        started = time.time()
        if not image_path or not os.path.exists(image_path):
            raise ClientError("Base gorsel (Image 1) bulunamadi.")
        if not (prompt or "").strip():
            raise ClientError("Prompt bos olamaz.")
        if str(lora) not in LORAS:
            raise ClientError("Gecersiz LoRA secimi.")
        if str(decoder_vae) not in DECODERS:
            raise ClientError("Decoder VAE qwen veya wan2x olmali.")
        if int(resolution_multiple) not in RESOLUTION_MULTIPLES:
            raise ClientError("Resolution multiple 32/56/112 olmali.")
        if not (1 <= int(steps) <= 50):
            raise ClientError("Steps 1-50 araliginda olmali.")
        if not (1 <= float(guidance_scale) <= 10):
            raise ClientError("Guidance 1-10 araliginda olmali.")
        if not (0 <= int(seed) <= SEED_MAX):
            raise ClientError(f"Seed 0-{SEED_MAX} araliginda olmali.")

        self.session_hash = _random_id(10)
        self.transport.begin_run()
        self._log("info", f"Oturum {self.session_hash} · {SPACE_ID} · /infer")
        self._log("status", "1/3 · Gorseller yükleniyor…")

        image1 = self._upload(prepare_upload(image_path))
        image2 = None
        if image2_path and os.path.exists(image2_path):
            image2 = self._upload(prepare_upload(image2_path))
        extras = []
        for p in (extra_paths or []):
            if not p:
                continue
            if not os.path.exists(p):
                raise ClientError(f"Ek gorsel bulunamadi: {p}")
            extras.append(self._gallery_item(self._upload(prepare_upload(p))))

        data = build_infer_data(
            image1, image2, extras, prompt.strip(), lora,
            seed, randomize_seed, guidance_scale, steps, target_megapixels,
            extras_condition_only, pad_to_canvas, vae_tiling, resolution_multiple,
            vae_ref_megapixels, decoder_vae, keep_decoder_2x,
            highlight_protection, highlight_protection_strength,
        )
        self._log("info", f"join · fn_index={FN_INFER} · {len(data)} parametre")
        self._log("status", "2/3 · Görsel düzenleniyor… (30-120 sn)")
        output = self._run_infer(data)

        image = self._find_image(output)
        if not image:
            raise ClientError(f"Gorsel ciktisi bulunamadi: {str(output)[:400]}")
        url = self._file_url(image)
        self._log("status", "3/3 · Sonuç indiriliyor…")
        image_bytes = self.transport.download_result(
            url,
            {"accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
             "referer": BASE_URL + "/?__theme=dark", "user-agent": DEFAULT_UA},
            label="gorsel/indir",
        )
        used_seed = None
        if len(output) > 1 and isinstance(output[1], (int, float)) and not isinstance(output[1], bool):
            used_seed = int(output[1])
        elapsed = time.time() - started
        self._log("ok", f"Tamamlandı · {len(image_bytes) / 1024:.0f} KB · {elapsed:.1f} sn")
        return ImageResult(image_bytes=image_bytes, image_url=url, prompt=prompt.strip(),
                           seed=used_seed, elapsed=elapsed,
                           proxy_log=[p.label for p in self.transport.used])


def _cli() -> int:
    import argparse
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Qwen Image Edit 2511 istemcisi (HAR'dan reverse edildi)")
    parser.add_argument("--image", required=True, help="Image 1 (base/target)")
    parser.add_argument("--image2", default=None, help="Image 2 (reference, opsiyonel)")
    parser.add_argument("--extra", action="append", default=[], help="ek referans (birden cok)")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--lora", default="None", choices=LORAS)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--no-randomize", action="store_true")
    parser.add_argument("--guidance", type=float, default=1.0)
    parser.add_argument("--steps", type=int, default=4)
    parser.add_argument("--megapixels", type=float, default=1.0)
    parser.add_argument("--resolution-multiple", type=int, default=32, choices=RESOLUTION_MULTIPLES)
    parser.add_argument("--decoder", default="qwen", choices=DECODERS)
    parser.add_argument("--no-proxy", action="store_true")
    parser.add_argument("--proxy-file", default=None)
    parser.add_argument("--out", default="outputs")
    args = parser.parse_args()

    pool = None
    if not args.no_proxy:
        pf = args.proxy_file or ProxyPool.find_default(os.getcwd())
        if pf:
            pool = ProxyPool(pf)
    client = Qwen2511Client(proxy_pool=pool, on_log=lambda lv, m: print(f"{lv:6} {m}"))
    result = client.generate(
        args.image, args.prompt, image2_path=args.image2, extra_paths=args.extra,
        lora=args.lora, seed=args.seed, randomize_seed=not args.no_randomize,
        guidance_scale=args.guidance, steps=args.steps,
        target_megapixels=args.megapixels, resolution_multiple=args.resolution_multiple,
        decoder_vae=args.decoder,
    )
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"qwen2511_{time.strftime('%Y%m%d_%H%M%S')}.png")
    with open(path, "wb") as fh:
        fh.write(result.image_bytes)
    print(f"Kaydedildi: {path} · {result.size_kb:.0f} KB · seed {result.seed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
