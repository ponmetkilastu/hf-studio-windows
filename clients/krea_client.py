"""Krea 2 Turbo (gorsel uretme / gorsel duzenleme) HF Space icin istemci.

Tersine muhendislik kaynagi: ``huggingface.co.krea.imgedit.har``
Space: https://huggingface.co/spaces/Intruzo/Krea-2-Turbo_v2
Host : https://intruzo-krea-2-turbo-v2.hf.space
Gradio: 5.44.1 (SvelteKit arayuzu, klasik ``gradio_api`` akisi)

HAR'dan cikarilan akis:

  1. POST /gradio_api/upload?upload_id=<id>       (multipart, alan adi "files")
     -> ["/tmp/gradio/<hash>/<dosya>"]
  2. POST /gradio_api/queue/join?__theme=dark     fn_index 4 = /_generate_wrapper
     {"data":[41 eleman], "event_data":null, "fn_index":4,
      "trigger_id":79, "session_hash":"..."}  ->  {"event_id":"..."}
  3. GET  /gradio_api/queue/data?session_hash=... (SSE, process_completed beklenir)
     output.data = [gallery, status, used_seed]
  4. GET  /gradio_api/file=/tmp/gradio/<hash>/output_0.png   (sonuc gorseli)

Parametrelerin gonderilme bicimi (onemli):

  * Gradio ``data`` dizisi SABIT 41 elemandir; hicbir parametre atlanmaz.
    Tarayici varsayilan degerleri de (1024, 1.4, 768, 0.0 ...) acikca gonderir.
    Bu yuzden istemci tum 41 slot'u doldurur; bos birakilan lar null/0.0 olur.
  * Slot sirasi ``/gradio_api/info`` -> ``/_generate_wrapper`` ve ``/config``
    dosyasindaki ``inputs`` listesinden dogrulanmistir (bkz. PARAM_LABELS).
  * ``primary image`` slot'u, yukleme yanitindan uretilen bir FileData sozlugudur:
    path + url (BASE_URL + "/gradio_api/file=" + path) + orig_name + size +
    mime_type + meta. Tarayici URL'deki boslugu kodlamadan gonderir; requests
    bunu otomatik kodlar.
  * ``trigger_id: 79`` ve ``fn_index: 4`` space'in ``/config`` dosyasindan gelir
    (generate dugmesinin click event'i). ``session_hash`` 10 karakterli rastgele
    bir degerdir.
  * HAR'daki ilk join (``fn_index: 0``, ``data: ["edit"]`` = /on_mode_change)
    yalnizca arayuz gorunurlugunu degistirir; uretimi etkilemez ve atlanir.

Not: HAR'da Authorization / cookie / HF tokeni yoktur; istemci de gondermez.
ZeroGPU oturum basliklari (``x-zerogpu-uuid`` / ``x-zerogpu-token``) bilincli
olarak GONDERILMEZ: bunlar tarayicinin kendi oturum kimligidir, kimlik dogrulama
icin gerekli degildir ve bu istemci icin bir anlami yoktur (bkz. REVERSE.md).
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
import re
import string
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import requests

from clients.hf_image_client import (
    ClientError,
    DEFAULT_UA,
    ProxyPool,
    RotatingTransport,
)

BASE_URL = "https://intruzo-krea-2-turbo-v2.hf.space"
SPACE_ID = "Intruzo/Krea-2-Turbo_v2"

QUEUE_JOIN = BASE_URL + "/gradio_api/queue/join?__theme=dark"
QUEUE_DATA = BASE_URL + "/gradio_api/queue/data"
UPLOAD_URL = BASE_URL + "/gradio_api/upload"

FN_INDEX_GENERATE = 4
TRIGGER_ID_GENERATE = 79

MODES = ["text2image", "edit"]
SAMPLERS = ["euler", "euler_ancestral", "euler_a", "dpmpp_2m", "dpmpp_2m_sde",
            "dpmpp_sde", "heun", "lms"]
SCHEDULERS = ["beta", "normal", "karras", "exponential", "sgm_uniform", "simple"]
CHECKPOINTS = [
    "gonzalomoKrea2_v40.safetensors",
    "museByStableYogi_v25EXTENDEDTURBO.safetensors",
    "pornmasterKrea2_v2TurboInt8.safetensors",
    "__custom_huggingface_base_model__",
]
DEFAULT_CHECKPOINT = "pornmasterKrea2_v2TurboInt8.safetensors"

# Slider sinirlari (/gradio_api/info + /config)
WIDTH_RANGE = (512, 2048, 64)
HEIGHT_RANGE = (512, 2048, 64)
MEGAPIXELS_RANGE = (0.25, 4.0, 0.05)
GROUNDING_RANGE = (384, 1536, 32)
STRENGTH_RANGE = (0.0, 12.0, 0.1)
STEPS_RANGE = (4, 40, 1)
CFG_RANGE = (1.0, 5.0, 0.1)
GPU_BUDGET_RANGE = (0, 300, 10)

# /_generate_wrapper parametre adlari (41 slot) — dogrulama/dokumantasyon icin.
PARAM_LABELS = [
    "mode", "prompt", "edit instruction", "primary image / scene",
    "optional second reference", "width", "height", "target megapixels",
    "grounding resolution", "primary reference strength", "second reference strength",
    "steps", "CFG", "sampler", "scheduler", "seed", "randomize seed",
    "GPU budget (0 = automatic)", "base Krea checkpoint",
    "custom base-model Hugging Face repository", "custom base-model filename",
    "custom base-model revision (optional)", "custom Hugging Face LoRAs",
] + [f"catalog LoRA slider {i + 1}" for i in range(18)]

DEFAULT_PROMPT = "A cinematic portrait in soft natural light"
EMPTY_DATAFRAME = {"headers": ["repo_id", "filename", "revision", "weight"],
                   "data": [], "metadata": None}


@dataclass
class PreparedUpload:
    path: str
    filename: str
    raw: bytes
    mime: str
    note: str = ""


@dataclass
class ImageResult:
    image_bytes: bytes
    image_url: str
    status: str = ""
    seed: Optional[int] = None
    elapsed: float = 0.0
    prompt: str = ""
    proxy_log: list[str] = field(default_factory=list)

    @property
    def size_kb(self) -> float:
        return len(self.image_bytes) / 1024


def prepare_upload(path: str, optimize: bool = True, max_side: int = 1536,
                   quality: int = 92) -> PreparedUpload:
    """Gorseli yuklemeye hazirlar; optimize acikken buyuk dosyalari JPEG'e cevirir."""
    from PIL import Image, ImageOps

    with open(path, "rb") as fh:
        raw = fh.read()
    base = os.path.basename(path)
    mime = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(os.path.splitext(base)[1].lower(), "image/png")
    if not optimize:
        return PreparedUpload(path, base, raw, mime)
    try:
        with Image.open(__import__("io").BytesIO(raw)) as im:
            im.load()
            im = ImageOps.exif_transpose(im)
            big = max(im.size) > max_side
            heavy = len(raw) > 5 * 1024 * 1024
            if not big and not heavy and mime in ("image/png", "image/jpeg"):
                return PreparedUpload(path, base, raw, mime)
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
            buf = __import__("io").BytesIO()
            work.save(buf, "JPEG", quality=quality, optimize=True)
            return PreparedUpload(path, os.path.splitext(base)[0] + ".jpg",
                                  buf.getvalue(), "image/jpeg",
                                  f"{work.width}x{work.height} JPEG")
    except Exception:
        return PreparedUpload(path, base, raw, mime)


class KreaClient:
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

    # -- yardimcilar ------------------------------------------------------ #

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
        # ZeroGPU oturum basliklari (x-zerogpu-uuid / x-zerogpu-token) bilincli
        # olarak EKLENMEZ — bkz. REVERSE.md "Zorunlu kurallar".
        return headers

    def _join(self, fn_index: int, trigger_id: int, data: list, label: str) -> str:
        payload = {
            "data": data,
            "event_data": None,
            "fn_index": fn_index,
            "trigger_id": trigger_id,
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
                if kind == "heartbeat":
                    continue
                if kind == "close_stream":
                    raise ClientError("Sunucu akisi beklenmeden kapatti.")
                if kind == "queue_full":
                    raise ClientError("Kuyruk dolu, biraz sonra tekrar deneyin.")
                if message.get("event_id") != event_id:
                    continue
                if kind == "estimation":
                    rank = message.get("rank")
                    eta = message.get("rank_eta")
                    if rank is not None:
                        extra = f" · tahmini {eta:.0f} sn" if isinstance(eta, (int, float)) else ""
                        self._log("status", f"Kuyrukta {rank}. sıra{extra}")
                elif kind == "process_generating":
                    text = _progress_text(message)
                    if text:
                        self._log("status", text)
                elif kind == "process_completed":
                    if not message.get("success", True):
                        detail = message.get("output")
                        if isinstance(detail, dict):
                            text = str(detail.get("error") or detail.get("title") or detail)
                        else:
                            text = str(detail or message.get("title") or "bilinmeyen hata")
                        raise ClientError(f"Sunucu islemi basarisiz: {text[:800]}")
                    return message
        except requests.exceptions.RequestException as exc:
            raise ClientError(f"SSE baglantisi koptu: {exc}") from exc
        raise ClientError("SSE akisi beklenmeden sona erdi.")

    # -- cikti ------------------------------------------------------------ #

    @staticmethod
    def _unwrap(node, depth: int = 0):
        if depth > 6:
            return node
        if isinstance(node, dict):
            if node.get("__type__") == "update" and "value" in node:
                return KreaClient._unwrap(node["value"], depth + 1)
            if set(node) == {"value"} and isinstance(node["value"], (dict, list)):
                return KreaClient._unwrap(node["value"], depth + 1)
        return node

    @staticmethod
    def _first_image(node, depth: int = 0) -> Optional[dict]:
        """Sonuc agacinda ilk gorsel FileData/ImageData sozlugunu bulur."""
        if depth > 8:
            return None
        if isinstance(node, dict):
            url = str(node.get("url") or "")
            path = str(node.get("path") or "")
            mime = str(node.get("mime_type") or node.get("mime") or "")
            image = node.get("image")
            if image is not None:
                found = KreaClient._first_image(image, depth + 1)
                if found:
                    return found
            haystack = f"{url} {path}".lower()
            if (any(k in haystack for k in (".png", ".jpg", ".jpeg", ".webp"))
                    or mime.startswith("image/")):
                return node
            for key in ("value", "image", "data"):
                if key in node:
                    found = KreaClient._first_image(node[key], depth + 1)
                    if found:
                        return found
        elif isinstance(node, (list, tuple)):
            for item in node:
                found = KreaClient._first_image(item, depth + 1)
                if found:
                    return found
        return None

    @staticmethod
    def _file_url(file_data: dict) -> str:
        url = file_data.get("url")
        if url:
            return str(url)
        path = file_data.get("path")
        if not path:
            raise ClientError("Gorsel icin URL/path yok.")
        return BASE_URL + "/gradio_api/file=" + (path if str(path).startswith("/") else "/" + str(path))

    # -- ana akis --------------------------------------------------------- #

    def upload(self, upload: PreparedUpload) -> dict:
        upload_id = _random_id(10)
        url = f"{UPLOAD_URL}?upload_id={upload_id}"
        resp = self.transport.post_multipart(
            url, {"files": (upload.filename, upload.raw, upload.mime)},
            headers={"accept": "*/*", "origin": BASE_URL,
                     "referer": BASE_URL + "/?__theme=dark", "user-agent": DEFAULT_UA},
            label="yukleme",
        )
        try:
            paths = resp.json()
        except ValueError:
            raise ClientError(f"Yukleme yaniti okunamadi: {resp.text[:300]}")
        if not isinstance(paths, list) or not paths:
            raise ClientError(f"Yukleme yolu donmedi: {str(paths)[:300]}")
        path = str(paths[0])
        self._log("ok", f"Yukleme tamam · {upload.filename} · {len(upload.raw) / 1024:.0f} KB")
        return {
            "path": path,
            "url": BASE_URL + "/gradio_api/file=" + path,
            "orig_name": upload.filename,
            "size": len(upload.raw),
            "mime_type": upload.mime,
            "meta": {"_type": "gradio.FileData"},
        }

    @staticmethod
    def build_data(
        mode: str = "edit",
        prompt: str = DEFAULT_PROMPT,
        edit_instruction: str = "",
        primary_image: Optional[dict] = None,
        second_image: Optional[dict] = None,
        width: int = 1024,
        height: int = 1024,
        megapixels: float = 1.4,
        grounding: int = 768,
        strength1: float = 1.0,
        strength2: float = 1.0,
        steps: int = 8,
        cfg: float = 1.0,
        sampler: str = "euler",
        scheduler: str = "beta",
        seed: int = 2,
        randomize: bool = False,
        gpu_budget: int = 0,
        checkpoint: str = DEFAULT_CHECKPOINT,
        custom_repo: Optional[str] = None,
        custom_filename: Optional[str] = None,
        custom_revision: Optional[str] = None,
        lora_dataframe: Optional[dict] = None,
        lora_sliders: Optional[list[float]] = None,
    ) -> list:
        """Gradio'nun bekledigi 41 elemanli ``data`` dizisini olusturur."""
        if mode not in MODES:
            mode = "edit"
        if sampler not in SAMPLERS:
            sampler = "euler"
        if scheduler not in SCHEDULERS:
            scheduler = "beta"
        if checkpoint not in CHECKPOINTS:
            checkpoint = DEFAULT_CHECKPOINT
        sliders = list(lora_sliders or [0.0] * 18)
        sliders = (sliders + [0.0] * 18)[:18]
        return [
            mode,                       # 0  mode
            prompt,                     # 1  prompt
            edit_instruction,           # 2  edit instruction
            primary_image,              # 3  primary image / scene
            second_image,               # 4  optional second reference
            int(width),                 # 5  width
            int(height),                # 6  height
            float(megapixels),          # 7  target megapixels
            int(grounding),             # 8  grounding resolution
            float(strength1),           # 9  primary reference strength
            float(strength2),           # 10 second reference strength
            int(steps),                 # 11 steps
            float(cfg),                 # 12 CFG
            sampler,                    # 13 sampler
            scheduler,                  # 14 scheduler
            int(seed),                  # 15 seed
            bool(randomize),            # 16 randomize seed
            int(gpu_budget),            # 17 GPU budget
            checkpoint,                 # 18 base Krea checkpoint
            custom_repo,                # 19 custom base-model repo
            custom_filename,            # 20 custom base-model filename
            custom_revision,            # 21 custom base-model revision
            lora_dataframe or dict(EMPTY_DATAFRAME),  # 22 custom HF LoRAs
            *[float(v) for v in sliders],             # 23..40 katalog LoRA sliderlari
        ]

    def generate(
        self,
        image_path: Optional[str],
        prompt: str = DEFAULT_PROMPT,
        mode: str = "edit",
        edit_instruction: str = "",
        second_image_path: Optional[str] = None,
        width: int = 1024, height: int = 1024, megapixels: float = 1.4,
        grounding: int = 768, strength1: float = 1.0, strength2: float = 1.0,
        steps: int = 8, cfg: float = 1.0, sampler: str = "euler",
        scheduler: str = "beta", seed: int = 2, randomize: bool = False,
        gpu_budget: int = 0, checkpoint: str = DEFAULT_CHECKPOINT,
        custom_repo: Optional[str] = None, custom_filename: Optional[str] = None,
        custom_revision: Optional[str] = None,
        lora_dataframe: Optional[dict] = None, lora_sliders: Optional[list[float]] = None,
        optimize_image: bool = True,
    ) -> ImageResult:
        started = time.time()
        prompt = (prompt or "").strip()
        if not prompt and not edit_instruction:
            raise ClientError("Prompt veya duzenleme talimati gerekli.")
        if mode == "edit" and (not image_path or not os.path.exists(image_path)):
            raise ClientError("Duzenleme modu icin bir gorsel gerekli.")
        if mode not in MODES:
            mode = "edit"

        self.session_hash = _random_id(10)
        self._log("info", f"Oturum {self.session_hash} · {SPACE_ID} · {mode} · {width}x{height}")

        self.transport.begin_run()

        primary = None
        if image_path and os.path.exists(image_path):
            self._log("status", "1/4 · Gorsel yukleniyor…")
            prepared = prepare_upload(image_path, optimize=optimize_image)
            note = f" ({prepared.note})" if prepared.note else ""
            self._log("info", f"Gorsel hazır: {os.path.basename(image_path)} · "
                              f"~{len(prepared.raw) / 1024:.0f} KB{note}")
            primary = self.upload(prepared)

        secondary = None
        if second_image_path and os.path.exists(second_image_path):
            self._log("status", "2/4 · Ikinci referans yukleniyor…")
            prepared2 = prepare_upload(second_image_path, optimize=optimize_image)
            secondary = self.upload(prepared2)

        data = self.build_data(
            mode=mode, prompt=prompt, edit_instruction=edit_instruction,
            primary_image=primary, second_image=secondary,
            width=width, height=height, megapixels=megapixels, grounding=grounding,
            strength1=strength1, strength2=strength2, steps=steps, cfg=cfg,
            sampler=sampler, scheduler=scheduler, seed=seed, randomize=randomize,
            gpu_budget=gpu_budget, checkpoint=checkpoint,
            custom_repo=custom_repo, custom_filename=custom_filename,
            custom_revision=custom_revision, lora_dataframe=lora_dataframe,
            lora_sliders=lora_sliders,
        )
        self._log("info", f"join · fn_index={FN_INDEX_GENERATE} · trigger_id={TRIGGER_ID_GENERATE} · {len(data)} parametre")

        self._log("status", "3/4 · Gorsel uretiliyor… (bu adim 1-5 dk surebilir)")
        event_id = self._join(FN_INDEX_GENERATE, TRIGGER_ID_GENERATE, data, "gorsel/join")
        stream = self._open_stream()
        try:
            completed = self._wait(stream, event_id)
        finally:
            stream.close()

        output = (completed.get("output") or {}).get("data") or []
        gallery = output[0] if output else None
        status = ""
        used_seed: Optional[int] = None
        if len(output) > 1 and isinstance(output[1], str):
            status = output[1].strip()
        if len(output) > 2 and isinstance(output[2], (int, float)):
            used_seed = int(output[2])

        image = self._first_image(gallery)
        if not image:
            raise ClientError(f"Gorsel ciktisi bulunamadi: {str(output)[:400]}")
        url = self._file_url(image)

        self._log("status", "4/4 · Gorsel indiriliyor…")
        image_bytes = self.transport.download_result(
            url,
            {"accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
             "referer": BASE_URL + "/?__theme=dark", "user-agent": DEFAULT_UA},
            label="gorsel/indir",
        )
        elapsed = time.time() - started
        self._log("ok", f"Tamamlandı · {len(image_bytes) / 1024:.0f} KB · {elapsed:.1f} sn"
                        + (f" · seed {used_seed}" if used_seed is not None else ""))
        return ImageResult(
            image_bytes=image_bytes, image_url=url, status=status, seed=used_seed,
            elapsed=elapsed, prompt=prompt, proxy_log=[p.label for p in self.transport.used],
        )


def _random_id(length: int) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def _progress_text(message: dict) -> str:
    for item in message.get("progress_data") or []:
        if isinstance(item, dict):
            progress = item.get("progress")
            desc = str(item.get("desc") or "").strip()
            if desc and isinstance(progress, (int, float)) and 0 <= progress <= 1:
                return f"{desc} · %{progress * 100:.0f}"
    return ""


# --------------------------------------------------------------------------- #
#  CLI (arayuz olmadan hizli test)
# --------------------------------------------------------------------------- #


def _cli() -> int:
    import argparse

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Krea 2 Turbo gorsel istemcisi (HAR'dan reverse edildi)")
    parser.add_argument("--image", default=None, help="Duzenleme modu icin gorsel / referans")
    parser.add_argument("--second-image", default=None, help="Opsiyonel ikinci referans")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--edit", default="", help="Duzenleme talimati")
    parser.add_argument("--mode", choices=MODES, default="edit")
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--megapixels", type=float, default=1.4)
    parser.add_argument("--grounding", type=int, default=768)
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--cfg", type=float, default=1.0)
    parser.add_argument("--sampler", choices=SAMPLERS, default="euler")
    parser.add_argument("--scheduler", choices=SCHEDULERS, default="beta")
    parser.add_argument("--seed", type=int, default=2)
    parser.add_argument("--randomize", action="store_true")
    parser.add_argument("--checkpoint", choices=CHECKPOINTS, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--gpu-budget", type=int, default=0)
    parser.add_argument("--out", default="outputs")
    parser.add_argument("--proxy-file", default=None)
    parser.add_argument("--no-proxy", action="store_true")
    args = parser.parse_args()

    pool = None
    if not args.no_proxy:
        proxy_file = args.proxy_file or ProxyPool.find_default(os.getcwd())
        if proxy_file:
            pool = ProxyPool(proxy_file)
    client = KreaClient(proxy_pool=pool, on_log=lambda lv, m: print(f"{lv:6} {m}"))
    result = client.generate(
        args.image, prompt=args.prompt, mode=args.mode, edit_instruction=args.edit,
        second_image_path=args.second_image, width=args.width, height=args.height,
        megapixels=args.megapixels, grounding=args.grounding, steps=args.steps,
        cfg=args.cfg, sampler=args.sampler, scheduler=args.scheduler,
        seed=args.seed, randomize=args.randomize, checkpoint=args.checkpoint,
        gpu_budget=args.gpu_budget,
    )
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"krea_{time.strftime('%Y%m%d_%H%M%S')}.png")
    with open(path, "wb") as fh:
        fh.write(result.image_bytes)
    print(f"Kaydedildi: {path} · {result.size_kb:.0f} KB · seed {result.seed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
