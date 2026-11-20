"""Microsoft TRELLIS.2 (gorselden 3D model / GLB) HF Space istemcisi.

Kaynak: ``huggingface.co.trellis2.har``
Space: https://huggingface.co/spaces/microsoft/TRELLIS.2
Host : https://microsoft-trellis-2.hf.space  (Gradio 6.1.0)

HAR uretim zinciri (bkz. docs/REVERSE.md):
  0. POST /gradio_api/queue/join  fn_index=2 (/start_session), data=[]  -> SSE
  1. POST /gradio_api/upload?upload_id=<id>  (multipart, alan "files")
     -> ["/tmp/gradio/<hash>/qwen_....png"]
  2. POST /queue/join  fn_index=4 (/preprocess_image), trigger_id=4,
     data=[FileData] -> SSE image.png (on islenmis FileData)
  3. POST /queue/join  fn_index=5 (/get_seed), trigger_id=10,
     data=[randomize_seed, seed] -> SSE [kullanilan_seed]
  4. POST /queue/join  fn_index=7 (/image_to_3d), trigger_id=10,
     15 elemanli data -> SSE [state, html_onizleme]
  5. POST /queue/join  fn_index=9 (/extract_glb), trigger_id=38,
     data=[null, decimation_target, texture_size] -> SSE [Model3D, DownloadButton]
     (ilk null, gr.State input 45 icin yer tutucudur; state sunucuda kalir)
  6. GET /gradio_api/file=/tmp/gradio/<hash>/*.glb -> GLB

Atlana: GET /gradio_api/upload_progress (SSE, yalnizca yukleme ilerlemesi) ve
``fn 6 / lambda`` (walkthrough adimi; uretime etkisi yok).

15 parametrenin sirasi /gradio_api/info + /config inputs
[4,6,5,14,15,16,17,21,22,23,24,28,29,30,31] ile dogrulandi:
  image, seed, resolution, ss_* (4), shape_slat_* (4), tex_slat_* (4)

``trigger_id`` = olayi baslatan bilesenin id'si (Gradio 6.1):
  Image 4 (upload), Generate 10 (buton), Extract GLB 38 (buton).
State bileseni (45) istemciden gonderilmez; sunucu session_hash ile tutar.

REVERSE.md: x-zerogpu-* / cookie / Authorization GONDERILMEZ.
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
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import requests

from clients.hf_image_client import ClientError, DEFAULT_UA, ProxyPool, RotatingTransport

BASE_URL = "https://microsoft-trellis-2.hf.space"
SPACE_ID = "microsoft/TRELLIS.2"

UPLOAD_URL = BASE_URL + "/gradio_api/upload"
QUEUE_JOIN = BASE_URL + "/gradio_api/queue/join?__theme=system"
QUEUE_DATA = BASE_URL + "/gradio_api/queue/data"

FN_START = 2
FN_PREPROCESS = 4
FN_SEED = 5
FN_3D = 7
FN_EXTRACT = 9

TRIGGER_PREPROCESS = 4
TRIGGER_GENERATE = 10
TRIGGER_EXTRACT = 38

RESOLUTIONS = ("512", "1024", "1536")
DEFAULT_RESOLUTION = "1024"
DECIMATION_MIN, DECIMATION_MAX = 100000, 500000
DECIMATION_DEFAULT = 300000
TEXTURE_MIN, TEXTURE_MAX = 1024, 4096
TEXTURE_DEFAULT = 2048
SEED_MAX = 2147483647

# Asama varsayilanlari (/config ve /info)
STAGE_DEFAULTS = {
    "ss_guidance_strength": 7.5,
    "ss_guidance_rescale": 0.7,
    "ss_sampling_steps": 12,
    "ss_rescale_t": 5.0,
    "shape_slat_guidance_strength": 7.5,
    "shape_slat_guidance_rescale": 0.5,
    "shape_slat_sampling_steps": 12,
    "shape_slat_rescale_t": 3.0,
    "tex_slat_guidance_strength": 1.0,
    "tex_slat_guidance_rescale": 0.0,
    "tex_slat_sampling_steps": 12,
    "tex_slat_rescale_t": 3.0,
}

STAGE_RANGES = {
    "ss_guidance_strength": (1.0, 10.0),
    "ss_guidance_rescale": (0.0, 1.0),
    "ss_sampling_steps": (1, 50),
    "ss_rescale_t": (1.0, 6.0),
    "shape_slat_guidance_strength": (1.0, 10.0),
    "shape_slat_guidance_rescale": (0.0, 1.0),
    "shape_slat_sampling_steps": (1, 50),
    "shape_slat_rescale_t": (1.0, 6.0),
    "tex_slat_guidance_strength": (1.0, 10.0),
    "tex_slat_guidance_rescale": (0.0, 1.0),
    "tex_slat_sampling_steps": (1, 50),
    "tex_slat_rescale_t": (1.0, 6.0),
}


@dataclass
class ModelResult:
    glb_bytes: bytes
    glb_url: str
    seed: Optional[int] = None
    preview_html: str = ""
    elapsed: float = 0.0
    proxy_log: list[str] = field(default_factory=list)

    @property
    def size_kb(self) -> float:
        return len(self.glb_bytes) / 1024


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


def build_preprocess_data(image: dict) -> list:
    """/preprocess_image (fn 4) icin 1 elemanli data."""
    return [image]


def build_seed_data(randomize_seed: bool, seed: int) -> list:
    """/get_seed (fn 5): [randomize_seed, seed]."""
    return [bool(randomize_seed), int(seed)]


def build_3d_data(image: dict, seed: int, resolution: str, **stage) -> list:
    """/image_to_3d (fn 7) icin 15 elemanli data. Sira /info ile dogrulandi."""
    values = dict(STAGE_DEFAULTS)
    values.update({k: v for k, v in stage.items() if k in values})
    res = str(resolution or DEFAULT_RESOLUTION)
    if res not in RESOLUTIONS:
        res = DEFAULT_RESOLUTION
    return [
        image, int(seed), res,
        float(values["ss_guidance_strength"]),
        float(values["ss_guidance_rescale"]),
        int(values["ss_sampling_steps"]),
        float(values["ss_rescale_t"]),
        float(values["shape_slat_guidance_strength"]),
        float(values["shape_slat_guidance_rescale"]),
        int(values["shape_slat_sampling_steps"]),
        float(values["shape_slat_rescale_t"]),
        float(values["tex_slat_guidance_strength"]),
        float(values["tex_slat_guidance_rescale"]),
        int(values["tex_slat_sampling_steps"]),
        float(values["tex_slat_rescale_t"]),
    ]


def build_extract_data(decimation_target: int, texture_size: int) -> list:
    """/extract_glb (fn 9) icin 3 elemanli data.

    Ilk eleman ``gr.State`` (input 45) icin **null** yer tutucudur; gercek state
    (latent sozlugu) istemciye gonderilmez, Gradio sunucuda session_hash ile
    saklar ve null gorunce kendi degerini koyar.
    """
    return [None, int(decimation_target), int(texture_size)]


class Trellis2Client:
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
            "referer": BASE_URL + "/?__theme=system",
            "user-agent": DEFAULT_UA,
        }
        if not sse:
            headers["content-type"] = "application/json"
        # x-zerogpu-* / cookie / auth bilincli olarak eklenmez (REVERSE.md).
        return headers

    def _join(self, fn_index: int, trigger_id: Optional[int], data: list,
              label: str) -> str:
        # HAR: data + event_data + fn_index + trigger_id + session_hash.
        payload = {
            "data": data, "event_data": None, "fn_index": fn_index,
            "trigger_id": trigger_id, "session_hash": self.session_hash,
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
    def _unwrap(node, depth: int = 0):
        if depth > 8:
            return node
        if isinstance(node, dict):
            if node.get("__type__") == "update" and "value" in node:
                return Trellis2Client._unwrap(node["value"], depth + 1)
        return node

    @staticmethod
    def _file_data(node) -> Optional[dict]:
        """Bir cikti degerini FileData sozlugune cevir (path/url)."""
        if isinstance(node, str) and node.startswith("/"):
            return {
                "path": node,
                "url": BASE_URL + "/gradio_api/file=" + node,
                "orig_name": os.path.basename(node),
                "meta": {"_type": "gradio.FileData"},
            }
        if isinstance(node, dict) and node.get("path"):
            node = dict(node)
            if not node.get("url"):
                path = str(node["path"])
                node["url"] = BASE_URL + "/gradio_api/file=" + (
                    path if path.startswith("/") else "/" + path)
            return node
        return None

    @staticmethod
    def _find_file(node, exts: tuple[str, ...], depth: int = 0) -> Optional[dict]:
        if depth > 10:
            return None
        if isinstance(node, dict):
            path = str(node.get("path") or "")
            url = str(node.get("url") or "")
            for value in (path, url):
                if value and any(value.lower().endswith(e) for e in exts):
                    return node
            for value in node.values():
                found = Trellis2Client._find_file(value, exts, depth + 1)
                if found:
                    return found
        elif isinstance(node, (list, tuple)):
            for item in node:
                found = Trellis2Client._find_file(item, exts, depth + 1)
                if found:
                    return found
        elif isinstance(node, str):
            if any(node.lower().endswith(e) for e in exts):
                return {"path": node}
            # Buyuk base64/HTML govdelerinde katastrofik geri izlemeyi onlemek icin
            # once bosluksuz parcalara bol, sonra uzantiya bak.
            for token in re.findall(r"[^\s\"'<>]+", node):
                low = token.lower()
                if any(low.endswith(e) for e in exts):
                    if low.startswith(("http://", "https://")):
                        return {"url": token}
                    return {"path": token}
        return None

    def _run_event(self, fn_index: int, trigger_id: Optional[int], data: list,
                   label: str, step: str = "") -> list:
        if step:
            self._log("status", step)
        event_id = self._join(fn_index, trigger_id, data, label)
        stream = self._open_stream()
        try:
            message = self._wait(stream, event_id)
        finally:
            stream.close()
        output = (message.get("output") or {}).get("data") or []
        return [self._unwrap(v) for v in output]

    @staticmethod
    def _is_quota_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return "quota" in text and "gpu" in text

    def _run_gpu_event(self, fn_index: int, trigger_id: Optional[int], data: list,
                       label: str, step: str = "", attempts: int = 3) -> list:
        """ZeroGPU kotasi dolarsa proxy degistirip tekrar dener.

        Kota IP basina oldugu icin yeni proxy genelde temiz kota getirir.
        State ``session_hash`` ile sunucuda tutuldugundan extract retry'si
        guvenlidir (proxy degisse bile state bulunur).
        """
        for attempt in range(1, attempts + 1):
            try:
                return self._run_event(fn_index, trigger_id, data, label,
                                       step if attempt == 1 else "")
            except ClientError as exc:
                if attempt >= attempts or not self._is_quota_error(exc):
                    raise
                self._log("warn", f"ZeroGPU kotası doldu · yeni proxy ile tekrar deneniyor "
                                  f"({attempt + 1}/{attempts})")
                self.transport._rotate(getattr(self.transport, "_leased", None))

    def upload(self, prepared: PreparedUpload) -> dict:
        upload_id = _random_id(10)
        resp = self.transport.post_multipart(
            f"{UPLOAD_URL}?upload_id={upload_id}",
            {"files": (prepared.filename, prepared.raw, prepared.mime)},
            headers={"accept": "*/*", "origin": BASE_URL,
                     "referer": BASE_URL + "/?__theme=system", "user-agent": DEFAULT_UA},
            label="yukleme",
        )
        try:
            paths = resp.json()
        except ValueError:
            raise ClientError(f"Yukleme yaniti okunamadi: {resp.text[:300]}")
        if not isinstance(paths, list) or not paths:
            raise ClientError(f"Yukleme yolu donmedi: {str(paths)[:300]}")
        path = str(paths[0])
        self._log("ok", f"Yukleme tamam · {prepared.filename} · {len(prepared.raw) / 1024:.0f} KB")
        return {
            "path": path,
            "url": BASE_URL + "/gradio_api/file=" + path,
            "orig_name": prepared.filename,
            "size": len(prepared.raw),
            "mime_type": prepared.mime,
            "meta": {"_type": "gradio.FileData"},
        }

    def generate(self, image_path: str, resolution: str = DEFAULT_RESOLUTION,
                 seed: int = 0, randomize_seed: bool = True,
                 decimation_target: int = DECIMATION_DEFAULT,
                 texture_size: int = TEXTURE_DEFAULT,
                 **stage) -> ModelResult:
        """Gorselden 3D: oturum -> upload -> preprocess -> seed -> image_to_3d -> extract_glb."""
        started = time.time()
        if not image_path or not os.path.exists(image_path):
            raise ClientError("Gorsel dosyasi bulunamadi.")
        if str(resolution) not in RESOLUTIONS:
            raise ClientError("Resolution 512, 1024 veya 1536 olmali.")
        if not (DECIMATION_MIN <= int(decimation_target) <= DECIMATION_MAX):
            raise ClientError(f"Decimation target {DECIMATION_MIN}-{DECIMATION_MAX} araliginda olmali.")
        if not (TEXTURE_MIN <= int(texture_size) <= TEXTURE_MAX):
            raise ClientError(f"Texture size {TEXTURE_MIN}-{TEXTURE_MAX} araliginda olmali.")

        self.session_hash = _random_id(10)
        self.transport.begin_run()
        self._log("info", f"Oturum {self.session_hash} · {SPACE_ID} · image-to-3D")

        # 0) oturum baslat (state 45 bu oturumda tutulur)
        self._run_event(FN_START, None, [], "session/join", "1/6 · Oturum başlatılıyor…")

        # 1) gorsel yukle + on isle
        image = self.upload(prepare_upload(image_path))
        pre = self._run_event(FN_PREPROCESS, TRIGGER_PREPROCESS,
                              build_preprocess_data(image), "preprocess/join",
                              "2/6 · Görsel ön işleniyor…")
        prepared = None
        for value in pre:
            prepared = self._file_data(value)
            if prepared:
                break
        if not prepared:
            raise ClientError(f"Ön işlenmiş görsel bulunamadı: {str(pre)[:300]}")
        self._log("info", f"Ön işlenmiş görsel · {prepared.get('path', '')[:70]}")

        # 2) seed
        seed_out = self._run_event(FN_SEED, TRIGGER_GENERATE,
                                   build_seed_data(randomize_seed, seed), "seed/join",
                                   "3/6 · Seed belirleniyor…")
        used_seed = None
        for value in seed_out:
            if isinstance(value, (int, float)):
                used_seed = int(value)
                break
        if used_seed is None:
            used_seed = int(seed)
        self._log("info", f"Kullanılan seed · {used_seed}")

        # 3) 3D uretimi (HAR fn 7, 15 parametre)
        data = build_3d_data(prepared, used_seed, resolution, **stage)
        self._log("info", f"join · fn_index={FN_3D} · {len(data)} parametre")
        out = self._run_gpu_event(FN_3D, TRIGGER_GENERATE, data, "3d/join",
                                  "4/6 · 3D model üretiliyor… (1-3 dakika sürebilir)")
        preview_html = ""
        for value in out:
            if isinstance(value, str) and "<" in value:
                preview_html = value
                break

        # 4) GLB cikar
        extract = self._run_gpu_event(FN_EXTRACT, TRIGGER_EXTRACT,
                                      build_extract_data(decimation_target, texture_size),
                                      "extract/join",
                                      "5/6 · GLB çıkarılıyor… (30 sn veya daha fazla)")
        glb = self._find_file(extract, (".glb",))
        if not glb:
            raise ClientError(f"GLB çıktısı bulunamadı: {str(extract)[:400]}")
        url = str(glb.get("url") or "")
        if not url:
            path = str(glb.get("path") or "")
            if not path:
                raise ClientError("GLB için URL/path yok.")
            url = BASE_URL + "/gradio_api/file=" + (path if path.startswith("/") else "/" + path)

        self._log("status", "6/6 · GLB indiriliyor…")
        glb_bytes = self.transport.download_result(
            url,
            {"accept": "model/gltf-binary,model/gltf+json,application/octet-stream,*/*;q=0.8",
             "referer": BASE_URL + "/?__theme=system", "user-agent": DEFAULT_UA},
            label="glb/indir",
        )
        elapsed = time.time() - started
        self._log("ok", f"Tamamlandı · {len(glb_bytes) / 1024 / 1024:.1f} MB · {elapsed:.1f} sn")
        return ModelResult(glb_bytes=glb_bytes, glb_url=url, seed=used_seed,
                           preview_html=preview_html, elapsed=elapsed,
                           proxy_log=[p.label for p in self.transport.used])


def _cli() -> int:
    import argparse
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="TRELLIS.2 gorselden 3D istemcisi (HAR'dan reverse edildi)")
    parser.add_argument("--image", required=True)
    parser.add_argument("--resolution", choices=RESOLUTIONS, default=DEFAULT_RESOLUTION)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--no-randomize", action="store_true")
    parser.add_argument("--decimation", type=int, default=DECIMATION_DEFAULT)
    parser.add_argument("--texture", type=int, default=TEXTURE_DEFAULT)
    parser.add_argument("--no-proxy", action="store_true")
    parser.add_argument("--proxy-file", default=None)
    parser.add_argument("--out", default="outputs")
    args = parser.parse_args()

    pool = None
    if not args.no_proxy:
        pf = args.proxy_file or ProxyPool.find_default(os.getcwd())
        if pf:
            pool = ProxyPool(pf)
    client = Trellis2Client(proxy_pool=pool, on_log=lambda lv, m: print(f"{lv:6} {m}"))
    result = client.generate(
        args.image, resolution=args.resolution, seed=args.seed,
        randomize_seed=not args.no_randomize,
        decimation_target=args.decimation, texture_size=args.texture,
    )
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"trellis2_{time.strftime('%Y%m%d_%H%M%S')}.glb")
    with open(path, "wb") as fh:
        fh.write(result.glb_bytes)
    print(f"Kaydedildi: {path} · {result.size_kb:.0f} KB · seed {result.seed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
