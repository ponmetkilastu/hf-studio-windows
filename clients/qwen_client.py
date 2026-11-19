"""Qwen Image 2.1 Realtime (gorsel uretme / gorsel duzenleme) HF Space istemcisi.

Tersine muhendislik kaynagi: ``huggingface.co.qwen21.imgedit.har``
Space: https://huggingface.co/spaces/linoyts/qwen-image-2-1-realtime
Host : https://linoyts-qwen-image-2-1-realtime.hf.space
Gradio: 6.30.0 (SvelteKit arayuzu, klasik ``gradio_api`` akisi)

HAR'dan cikarilan uretim zinciri:

  1. POST /gradio_api/upload?upload_id=<id>       (multipart, alan adi "files")
     -> ["/tmp/gradio/<hash>/<dosya>"]  (her gorsel icin bir upload)
  2. POST /gradio_api/queue/join                 fn_index 10 = /prepare
     {"data":[prompt, gallery, enhance, seed, randomize_seed, aspect_ratio],
      "fn_index":10, "trigger_id":12, "session_hash":"..."}  -> event_id
     GET queue/data -> output.data = [prompt, rewritten, seed, aspect_ratio]
  3. POST /gradio_api/queue/join                 fn_index 11 = /generate
     {"data":[prompt, gallery, seed, resolution, aspect_ratio],
      "fn_index":11, "trigger_id":12, "session_hash":"..."}  -> event_id
     GET queue/data -> output.data[0] = sonuc gorseli (FileData)
  4. GET /gradio_api/file=/tmp/gradio/<hash>/image.png  -> PNG

Parametrelerin gonderilme bicimi (onemli):

  * ``gallery`` duz bir FileData DEGIL; Gradio Gallery ogeleridir:
    ``[{"image": {path, url, orig_name, size, mime_type, meta}, "caption": null}, ...]``
    (en fazla 10 gorsel). Bu yuzden her gorsel ayri upload edilir ve Gallery
    sarmalayicisi icine konur.
  * ``/prepare`` ciktisindaki seed ve aspect_ratio, ``/generate`` cagrisinda
    KULLANILIR (tarayici boyle yapar). ``randomize_seed: true`` iken sunucu
    seed'i uretir ve dondurur; istemci o seed'i alip generate'e verir.
  * ``/prepare`` ciktisindaki prompt (enhance aciksa yeniden yazilmis olabilir)
    yine generate'e gonderilir.
  * HAR'da prompt harf harf yazildigi icin ``fn_index 5`` (/push_live vb.)
    20+ kez cagrilmis; bunlar yalnizca 512px "realtime" onizleme icindir,
    ``outputs: []`` veya onizleme görseli dondurur. Uretimi etkilemedigi icin
    istemcide ATLANIR (bkz. REVERSE.md).
  * ``trigger_id: 12`` her iki join icin de aynidir (prepare click -> generate then).
  * ``session_hash`` 10 karakterli rastgele degerdir.

Not: HAR'daki join isteklerinde ``x-zerogpu-*`` basliklari gorunur; bu istemci
bunlari bilincli olarak GONDERMEZ (bkz. REVERSE.md "Zorunlu kurallar").
Authorization / cookie / HF tokeni de yoktur ve gonderilmez.
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

BASE_URL = "https://linoyts-qwen-image-2-1-realtime.hf.space"
SPACE_ID = "linoyts/qwen-image-2-1-realtime"

QUEUE_JOIN = BASE_URL + "/gradio_api/queue/join?__theme=dark"
QUEUE_DATA = BASE_URL + "/gradio_api/queue/data"
UPLOAD_URL = BASE_URL + "/gradio_api/upload"

FN_PREPARE = 10
FN_GENERATE = 11
TRIGGER_ID = 12

ASPECT_RATIOS = ["Auto", "1:1", "4:3", "3:4", "3:2", "2:3", "16:9", "9:16"]
RESOLUTIONS = [512, 1024, 1536]
DEFAULT_PROMPT = "A cinematic portrait in soft natural light"
MAX_IMAGES = 10


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
    prompt: str = ""
    seed: Optional[int] = None
    aspect_ratio: str = "Auto"
    resolution: int = 1024
    elapsed: float = 0.0
    proxy_log: list[str] = field(default_factory=list)

    @property
    def size_kb(self) -> float:
        return len(self.image_bytes) / 1024


def prepare_upload(path: str, optimize: bool = True, max_side: int = 1536,
                   quality: int = 92) -> PreparedUpload:
    """Gorseli yuklemeye hazirlar; optimize acikken buyuk dosyalari JPEG'e cevirir."""
    from PIL import Image, ImageOps
    import io

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
        with Image.open(io.BytesIO(raw)) as im:
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
            buf = io.BytesIO()
            work.save(buf, "JPEG", quality=quality, optimize=True)
            return PreparedUpload(path, os.path.splitext(base)[0] + ".jpg",
                                  buf.getvalue(), "image/jpeg",
                                  f"{work.width}x{work.height} JPEG")
    except Exception:
        return PreparedUpload(path, base, raw, mime)


class QwenClient:
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
        # ZeroGPU oturum basliklari bilincli olarak EKLENMEZ (bkz. REVERSE.md).
        return headers

    def _join(self, fn_index: int, data: list, label: str) -> str:
        payload = {
            "data": data,
            "event_data": None,
            "fn_index": fn_index,
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
                        text = str(detail.get("error") or detail.get("title") or detail) \
                            if isinstance(detail, dict) else str(detail or "bilinmeyen hata")
                        raise ClientError(f"Sunucu islemi basarisiz: {text[:800]}")
                    return message
        except requests.exceptions.RequestException as exc:
            raise ClientError(f"SSE baglantisi koptu: {exc}") from exc
        raise ClientError("SSE akisi beklenmeden sona erdi.")

    @staticmethod
    def _unwrap(node, depth: int = 0):
        if depth > 6:
            return node
        if isinstance(node, dict):
            if node.get("__type__") == "update" and "value" in node:
                return QwenClient._unwrap(node["value"], depth + 1)
            if set(node) == {"value"} and isinstance(node["value"], (dict, list)):
                return QwenClient._unwrap(node["value"], depth + 1)
        return node

    @staticmethod
    def _first_image(node, depth: int = 0) -> Optional[dict]:
        if depth > 8:
            return None
        if isinstance(node, dict):
            image = node.get("image")
            if image is not None:
                found = QwenClient._first_image(image, depth + 1)
                if found:
                    return found
            url = str(node.get("url") or "")
            path = str(node.get("path") or "")
            mime = str(node.get("mime_type") or node.get("mime") or "")
            if (any(k in f"{url} {path}".lower() for k in (".png", ".jpg", ".jpeg", ".webp"))
                    or mime.startswith("image/")):
                return node
            for key in ("value", "image", "data"):
                if key in node:
                    found = QwenClient._first_image(node[key], depth + 1)
                    if found:
                        return found
        elif isinstance(node, (list, tuple)):
            for item in node:
                found = QwenClient._first_image(item, depth + 1)
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
        """Tek gorseli yukler ve FileData sozlugu dondurur."""
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
    def build_gallery(file_datas: list[dict]) -> list[dict]:
        """FileData listesini Gradio Gallery ogelerine sarar (en fazla 10)."""
        return [{"image": fd, "caption": None} for fd in file_datas[:MAX_IMAGES]]

    @staticmethod
    def build_prepare_data(prompt: str, gallery: list[dict], enhance: bool,
                           seed: int, randomize_seed: bool, aspect_ratio: str) -> list:
        """``/prepare`` icin 6 elemanli ``data`` dizisi (fn_index 10)."""
        return [prompt, gallery, bool(enhance), int(seed), bool(randomize_seed), aspect_ratio]

    @staticmethod
    def build_generate_data(prompt: str, gallery: list[dict], seed: int,
                            resolution: int, aspect_ratio: str) -> list:
        """``/generate`` icin 5 elemanli ``data`` dizisi (fn_index 11)."""
        return [prompt, gallery, int(seed), int(resolution), aspect_ratio]

    def generate(
        self,
        prompt: str,
        image_paths: Optional[list[str]] = None,
        seed: int = 0,
        randomize_seed: bool = True,
        enhance: bool = False,
        aspect_ratio: str = "Auto",
        resolution: int = 1024,
        optimize_images: bool = True,
    ) -> ImageResult:
        started = time.time()
        prompt = (prompt or "").strip()
        if not prompt:
            raise ClientError("Prompt bos olamaz.")
        if aspect_ratio not in ASPECT_RATIOS:
            aspect_ratio = "Auto"
        if resolution not in RESOLUTIONS:
            resolution = 1024

        self.session_hash = _random_id(10)
        self._log("info", f"Oturum {self.session_hash} · {SPACE_ID} · {resolution}px · {aspect_ratio}")

        self.transport.begin_run()

        # 1) Gorselleri yukle ve Gallery ogelerine sar
        gallery: list[dict] = []
        paths = [p for p in (image_paths or []) if p and os.path.exists(p)][:MAX_IMAGES]
        if paths:
            self._log("status", f"1/5 · {len(paths)} gorsel yukleniyor…")
            file_datas = []
            for idx, path in enumerate(paths, 1):
                prepared = prepare_upload(path, optimize=optimize_images)
                note = f" ({prepared.note})" if prepared.note else ""
                self._log("info", f"  {idx}/{len(paths)} · {os.path.basename(path)} · "
                                  f"~{len(prepared.raw) / 1024:.0f} KB{note}")
                file_datas.append(self.upload(prepared))
            gallery = self.build_gallery(file_datas)
        else:
            self._log("info", "Gorsel yok · metinden uretim")

        # 2) /prepare — seed ve aspect_ratio'yu sunucudan al
        self._log("status", "2/5 · Hazırlanıyor…")
        prepare_data = [prompt, gallery, bool(enhance), int(seed),
                        bool(randomize_seed), aspect_ratio]
        self._log("info", f"prepare · fn_index={FN_PREPARE} · trigger_id={TRIGGER_ID} · {len(prepare_data)} parametre")
        event_id = self._join(FN_PREPARE, prepare_data, "prepare/join")
        stream = self._open_stream()
        try:
            completed = self._wait(stream, event_id)
        finally:
            stream.close()
        prep = (completed.get("output") or {}).get("data") or []
        used_prompt = prep[0] if len(prep) > 0 and isinstance(prep[0], str) else prompt
        rewritten = prep[1] if len(prep) > 1 and isinstance(prep[1], str) else ""
        used_seed = prep[2] if len(prep) > 2 and isinstance(prep[2], (int, float)) else seed
        used_aspect = prep[3] if len(prep) > 3 and isinstance(prep[3], str) else aspect_ratio
        self._log("ok", f"Hazırlandı · seed {int(used_seed)} · oran {used_aspect}"
                        + (f" · prompt yeniden yazıldı" if rewritten else ""))

        # 3) /generate — prepare ciktisiyla gercek uretim
        self._log("status", "3/5 · Görsel üretiliyor… (bu adım 1-3 dk sürebilir)")
        generate_data = [used_prompt, gallery, int(used_seed), int(resolution), used_aspect]
        self._log("info", f"generate · fn_index={FN_GENERATE} · trigger_id={TRIGGER_ID} · {len(generate_data)} parametre")
        event_id = self._join(FN_GENERATE, generate_data, "generate/join")
        stream = self._open_stream()
        try:
            completed = self._wait(stream, event_id)
        finally:
            stream.close()

        output = (completed.get("output") or {}).get("data") or []
        image = self._first_image(output[:1] if output else [])
        if not image:
            raise ClientError(f"Gorsel ciktisi bulunamadi: {str(output)[:400]}")
        url = self._file_url(image)

        self._log("status", "4/5 · Görsel indiriliyor…")
        image_bytes = self.transport.download_result(
            url,
            {"accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
             "referer": BASE_URL + "/?__theme=dark", "user-agent": DEFAULT_UA},
            label="gorsel/indir",
        )
        elapsed = time.time() - started
        self._log("ok", f"Tamamlandı · {len(image_bytes) / 1024:.0f} KB · {elapsed:.1f} sn · seed {int(used_seed)}")
        return ImageResult(
            image_bytes=image_bytes, image_url=url, prompt=used_prompt,
            seed=int(used_seed), aspect_ratio=used_aspect, resolution=int(resolution),
            elapsed=elapsed, proxy_log=[p.label for p in self.transport.used],
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
#  CLI
# --------------------------------------------------------------------------- #


def _cli() -> int:
    import argparse

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Qwen Image 2.1 gorsel istemcisi (HAR'dan reverse edildi)")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--image", action="append", default=[], help="Referans gorsel (en fazla 10, tekrarlanabilir)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--randomize", action="store_true", default=True)
    parser.add_argument("--fixed-seed", action="store_true", help="Seed'i rastgelelestirme")
    parser.add_argument("--enhance", action="store_true")
    parser.add_argument("--aspect", choices=ASPECT_RATIOS, default="Auto")
    parser.add_argument("--resolution", type=int, choices=RESOLUTIONS, default=1024)
    parser.add_argument("--out", default="outputs")
    parser.add_argument("--proxy-file", default=None)
    parser.add_argument("--no-proxy", action="store_true")
    args = parser.parse_args()

    pool = None
    if not args.no_proxy:
        proxy_file = args.proxy_file or ProxyPool.find_default(os.getcwd())
        if proxy_file:
            pool = ProxyPool(proxy_file)
    client = QwenClient(proxy_pool=pool, on_log=lambda lv, m: print(f"{lv:6} {m}"))
    result = client.generate(
        args.prompt, image_paths=args.image, seed=args.seed,
        randomize_seed=not args.fixed_seed, enhance=args.enhance,
        aspect_ratio=args.aspect, resolution=args.resolution,
    )
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"qwen_{time.strftime('%Y%m%d_%H%M%S')}.png")
    with open(path, "wb") as fh:
        fh.write(result.image_bytes)
    print(f"Kaydedildi: {path} · {result.size_kb:.0f} KB · seed {result.seed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
