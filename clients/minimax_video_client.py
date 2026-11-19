"""MiniMax H3 (fotograftan video) Hugging Face Space'i icin tersine muhendislik istemcisi.

Tersine muhendislik kaynagi: ``huggingface.co.minimax.img2vid.har``
Space: https://huggingface.co/spaces/wank3r/minimax-h3
Host : https://wank3r-minimax-h3.hf.space

HAR'dan cikarilan akis:

  1. POST /gradio_api/upload?upload_id=<id>      (multipart, alan adi "files")
     -> ["/tmp/gradio/<hash>/<dosya>.png"]
  2. POST /gradio_api/queue/join?__theme=dark    fn_index 0 = /_fit_keyframe
     {"data": [<FileData>, "<canvas preset>"], "trigger_id": 24, "session_hash": ...}
     -> {"event_id": ...}
  3. GET  /gradio_api/queue/data?session_hash=...   (SSE)
     output.data[0] -> canvas'a sigdirilmis ilk kare (FileData)
  4. POST /gradio_api/queue/join  fn_index 1 = /generate
     {"data": [prompt, <FileData ilk kare>, <FileData son kare|null>, "<canvas>",
               duration, steps, seed, upsample, turbo, [], null, 1.0, null],
      "trigger_id": 26, "session_hash": ...}
  5. GET  /gradio_api/queue/data?session_hash=...   (SSE, process_completed beklenir)
     output.data[0] -> video FileData (…/gradio_api/file=/tmp/gradio/<hash>/h3-*.mp4)
  6. GET  <video url>                               (proxy'siz, 403'te proxy yedegi)

Notlar:
  * HAR'daki hicbir istekte Authorization / cookie / HF tokeni yoktur; bu istemci
    de kimlik dogrulama bilgisi gondermez (proxy kullanici/parola haric).
  * ZeroGPU oturum basliklari (``x-zerogpu-uuid`` / ``x-zerogpu-token``) GOnderilmez;
    tarayicinin oturum kimligidir, API icin gerekli degildir (bkz. REVERSE.md).
  * ``/_fit_keyframe`` adimi opsiyoneldir: basarisiz olursa yuklenen fotograf
    oldugu gibi /generate cagrisina verilir.
"""


from __future__ import annotations

import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
from paths import ROOT_DIR, CONFIG_DIR, DATA_DIR, OUTPUT_DIR, SETTINGS_DIR, PROXY_FILE


import io
import json
import math
import os
import random
import re
import string
import sys
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

BASE_URL = "https://wank3r-minimax-h3.hf.space"
SPACE_ID = "wank3r/minimax-h3"

QUEUE_JOIN = BASE_URL + "/gradio_api/queue/join?__theme=dark"
QUEUE_DATA = BASE_URL + "/gradio_api/queue/data"
UPLOAD_URL = BASE_URL + "/gradio_api/upload"

# /gradio_api/info -> /_fit_keyframe ve /generate parametrelerindeki Literal.
CANVAS_PRESETS: list[str] = [
    "960x544 · 16:9 fast",
    "1024x576 · 16:9 fast",
    "1152x640 · 16:9",
    "1280x704 · 16:9",
    "1344x768 · 16:9 full",
    "544x960 · 9:16 fast",
    "640x1152 · 9:16",
    "768x1344 · 9:16 full",
    "544x544 · 1:1 fast",
    "768x768 · 1:1 full",
    "768x576 · 4:3 fast",
    "1024x768 · 4:3 full",
    "576x768 · 3:4 fast",
    "768x1024 · 3:4 full",
    "1152x512 · 21:9 fast",
    "1536x672 · 21:9 full",
]
DEFAULT_CANVAS = "960x544 · 16:9 fast"
AUTO_CANVAS = "Otomatik (fotoğraftan)"

# Hizli secim icin kisaltmalar (arayuzde combobox'ta tam metin gosterilir).
DURATION_RANGE = (1.0, 10.0)
STEPS_RANGE = (10, 50)

DEFAULT_PROMPT = (
    "The subject moves naturally, the camera slowly pushes in, cinematic lighting, "
    "smooth motion, high detail"
)


@dataclass
class PreparedUpload:
    path: str
    filename: str
    raw: bytes
    mime: str
    note: str = ""


def canvas_size(preset: str) -> tuple[int, int]:
    """``"960x544 · 16:9 fast"`` -> ``(960, 544)``."""
    try:
        part = preset.split("·")[0].strip().lower()
        width, height = (int(v) for v in part.split("x"))
        return width, height
    except (ValueError, AttributeError):
        return 960, 544


def image_dimensions(path: str) -> tuple[int, int]:
    """Fotografin (EXIF yonu duzeltilmis) piksel boyutunu dondurur."""
    from PIL import Image

    with Image.open(path) as im:
        width, height = im.size
        try:
            orientation = int(im.getexif().get(274) or 1)
        except Exception:
            orientation = 1
    if orientation in (5, 6, 7, 8):
        width, height = height, width
    return width, height


_ASPECT_GROUPS: Optional[dict[float, list[str]]] = None


def _aspect_groups() -> dict[float, list[str]]:
    global _ASPECT_GROUPS
    if _ASPECT_GROUPS is None:
        groups: dict[float, list[str]] = {}
        for preset in CANVAS_PRESETS:
            width, height = canvas_size(preset)
            groups.setdefault(round(width / height, 4), []).append(preset)
        _ASPECT_GROUPS = groups
    return _ASPECT_GROUPS


def best_canvas_for_image(width: int, height: int) -> str:
    """Fotoğrafın oranına en yakın canvas'ı, çözünürlüğüne en yakın boyutta seçer.

    Örn. 1536x2720 dikey fotoğraf -> ``768x1344 · 9:16 full``;
    640x480 yatay fotoğraf -> ``768x576 · 4:3 fast``.
    """
    if width <= 0 or height <= 0:
        return DEFAULT_CANVAS
    src_ratio = width / height
    groups = _aspect_groups()
    ratio = min(groups, key=lambda value: abs(math.log(src_ratio / value)))
    presets = groups[ratio]
    src_area = width * height
    fitting = [p for p in presets if canvas_size(p)[0] * canvas_size(p)[1] <= src_area]
    if fitting:
        return max(fitting, key=lambda p: canvas_size(p)[0] * canvas_size(p)[1])
    return min(presets, key=lambda p: canvas_size(p)[0] * canvas_size(p)[1])


def best_canvas_for_path(path: str) -> str:
    try:
        return best_canvas_for_image(*image_dimensions(path))
    except Exception:
        return DEFAULT_CANVAS


def prepare_upload(path: str, optimize: bool = True, max_side: int = 1536, quality: int = 92) -> PreparedUpload:
    """Yuklenecek gorseli hazirlar; optimize acikken buyuk dosyalari JPEG'e cevirir."""
    from PIL import Image

    with open(path, "rb") as fh:
        raw = fh.read()

    base = os.path.basename(path)
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(os.path.splitext(base)[1].lower(), "image/png")

    if not optimize:
        return PreparedUpload(path, base, raw, mime)

    try:
        with Image.open(io.BytesIO(raw)) as im:
            im.load()
            from PIL import ImageOps

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
            note = f"{work.width}x{work.height} JPEG"
            return PreparedUpload(path, os.path.splitext(base)[0] + ".jpg", buf.getvalue(), "image/jpeg", note)
    except Exception:
        return PreparedUpload(path, base, raw, mime)


@dataclass
class VideoResult:
    video_bytes: bytes
    video_url: str
    status: str = ""
    prompt_used: str = ""
    seed: Optional[int] = None
    elapsed: float = 0.0
    canvas: str = DEFAULT_CANVAS
    duration: float = 5.0
    proxy_log: list[str] = field(default_factory=list)

    @property
    def size_mb(self) -> float:
        return len(self.video_bytes) / 1024 / 1024


class MiniMaxVideoClient:
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
        self.on_log(
            "info",
            f"Proxy havuzu: {len(self.pool)} adet" if self.pool else "Proxy KAPALI (dogrudan baglanti)",
        )
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
        headers["content-type"] = "application/json"
        # ZeroGPU oturum basliklari bilincli olarak EKLENMEZ (bkz. REVERSE.md).
        return headers

    @staticmethod
    def _flatten_strings(value, depth: int = 0) -> list[str]:
        if depth > 6:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, (list, tuple)):
            out: list[str] = []
            for item in value:
                out.extend(MiniMaxVideoClient._flatten_strings(item, depth + 1))
            return out
        return []

    def _progress_text(self, message: dict, exclude: str) -> Optional[str]:
        for item in message.get("progress_data") or []:
            if not isinstance(item, dict):
                continue
            progress = item.get("progress")
            desc = str(item.get("desc") or "").strip()
            if desc and isinstance(progress, (int, float)) and 0 <= progress <= 1:
                return f"{desc} · %{progress * 100:.0f}"
        data = (message.get("output") or {}).get("data") or []
        strings = [
            s.strip()
            for s in self._flatten_strings(data)
            if s and s.strip() and len(s) <= 160 and s.strip() != exclude
        ]
        return strings[-1] if strings else None

    def _join(self, fn_index: int, data: list, trigger_id: int, label: str) -> str:
        payload = {
            "data": data,
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
            self._headers(sse=True),
            timeout=(30, 3600),
            label="queue/sse",
        )

    def _wait(self, stream, event_id: str, exclude_prompt: str) -> dict:
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
                if kind == "queue_full":
                    raise ClientError("Kuyruk dolu, biraz sonra tekrar deneyin.")
                if kind == "close_stream":
                    raise ClientError("Sunucu akisi beklenmeden kapatti.")
                if message.get("event_id") != event_id:
                    continue

                if kind == "estimation":
                    rank = message.get("rank")
                    eta = message.get("rank_eta")
                    if rank is not None:
                        extra = f" · tahmini {eta:.0f} sn" if isinstance(eta, (int, float)) else ""
                        self._log("status", f"Kuyrukta {rank}. sıra{extra}")
                elif kind == "process_generating":
                    text = self._progress_text(message, exclude_prompt)
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

    # -- cikti cikarimi --------------------------------------------------- #

    @staticmethod
    def _unwrap(node, depth: int = 0):
        """Gradio ``{"__type__": "update", "value": ...}`` sarmalayicisini acar."""
        if depth > 6:
            return node
        if isinstance(node, dict):
            if node.get("__type__") == "update" and "value" in node:
                return MiniMaxVideoClient._unwrap(node["value"], depth + 1)
            if set(node) == {"value"} and isinstance(node["value"], (dict, list)):
                return MiniMaxVideoClient._unwrap(node["value"], depth + 1)
        return node

    @staticmethod
    def _first_file(node, kinds: tuple[str, ...], depth: int = 0) -> Optional[dict]:
        """Sonuc agacinda ilk dosya FileData'sini bulur (video veya goruntu)."""
        if depth > 8:
            return None
        if isinstance(node, dict):
            url = node.get("url") or ""
            path = node.get("path") or ""
            mime = str(node.get("mime_type") or "")
            haystack = f"{url} {path}".lower()
            if any(k in haystack or mime.startswith(k) for k in kinds):
                return node
            if node.get("__type__") == "update" and "value" in node:
                found = MiniMaxVideoClient._first_file(node["value"], kinds, depth + 1)
                if found:
                    return found
            for value in node.values():
                found = MiniMaxVideoClient._first_file(value, kinds, depth + 1)
                if found:
                    return found
        elif isinstance(node, (list, tuple)):
            for item in node:
                found = MiniMaxVideoClient._first_file(item, kinds, depth + 1)
                if found:
                    return found
        return None

    @staticmethod
    def _file_url(file_data: dict) -> str:
        url = file_data.get("url")
        if url:
            return url
        path = file_data.get("path")
        if not path:
            raise ClientError("Dosya icin URL/path yok.")
        return BASE_URL + "/gradio_api/file=" + (path if str(path).startswith("/") else "/" + str(path))

    # -- ana akis --------------------------------------------------------- #

    def upload(self, upload: PreparedUpload) -> dict:
        """Dosyayi space'in /gradio_api/upload ucuna yukler ve FileData sozlugu dondurur."""
        upload_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
        url = f"{UPLOAD_URL}?upload_id={upload_id}"
        files = {"files": (upload.filename, upload.raw, upload.mime)}
        resp = self.transport.post_multipart(
            url,
            files,
            headers={
                "accept": "*/*",
                "origin": BASE_URL,
                "referer": BASE_URL + "/?__theme=dark",
                "user-agent": DEFAULT_UA,
            },
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

    def fit_keyframe(self, file_data: dict, canvas: str) -> tuple[Optional[dict], str]:
        """``/_fit_keyframe`` (fn_index 0): fotografi secilen canvas'a sigdirir.

        Sunucu, fotografin oranina gore canvas'i degistirebilir (orn. 16:9 secilse de
        dikey fotograf icin 9:16 dondurebilir). Bu durumda cagiran taraf karar verir.
        """
        try:
            event_id = self._join(0, [file_data, canvas], 24, "kare/hazirla")
            stream = self._open_stream()
            try:
                completed = self._wait(stream, event_id, "")
            finally:
                stream.close()
            output = (completed.get("output") or {}).get("data") or []
            fitted = self._first_file(output[:1], (".png", ".jpg", ".jpeg", ".webp", "image/"))
            new_canvas = self._unwrap(output[1]) if len(output) > 1 else canvas
            if not isinstance(new_canvas, str):
                new_canvas = canvas
            if fitted and fitted.get("path"):
                self._log("ok", f"Kare hazırlandı · canvas {new_canvas}")
                return fitted, new_canvas
            self._log("warn", "Kare hazırlama çıktısı boş; yüklenen fotoğraf kullanılacak")
        except Exception as exc:  # opsiyonel adim: uretimi asla engellemesin
            self._log("warn", f"Kare hazırlama atlandı ({exc}); yüklenen fotoğraf kullanılacak")
        return None, canvas

    def generate(
        self,
        image_path: str,
        prompt: str,
        last_image_path: Optional[str] = None,
        canvas: Optional[str] = None,
        auto_canvas: bool = True,
        fit_frame: bool = False,
        duration: float = 5,
        steps: int = 25,
        seed: int = -1,
        randomize: bool = True,
        upsample: bool = False,
        turbo: bool = False,
        optimize_image: bool = True,
        extra: Optional[dict] = None,
    ) -> VideoResult:
        started = time.time()
        prompt = (prompt or "").strip()
        if not prompt:
            raise ClientError("Prompt bos olamaz.")
        if not image_path or not os.path.exists(image_path):
            raise ClientError("Baslangic fotografi gerekli (image-to-video).")

        if auto_canvas or not canvas or canvas == AUTO_CANVAS:
            try:
                src_w, src_h = image_dimensions(image_path)
            except Exception:
                src_w, src_h = 0, 0
            canvas = best_canvas_for_image(src_w, src_h)
            if src_w and src_h:
                self._log("info", f"Canvas otomatik: {canvas} · fotoğraf {src_w}x{src_h}")
        if canvas not in CANVAS_PRESETS:
            canvas = DEFAULT_CANVAS

        self.session_hash = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
        self._log(
            "info",
            f"Oturum {self.session_hash} · {SPACE_ID} · {canvas} · {duration:g} sn · {steps} adım",
        )

        # Bu uretim boyunca tek proxy kullanilir; yeni uretimde havuzdan sonraki alinir.
        self.transport.begin_run()

        self._log("status", "1/4 · Fotoğraf yükleniyor…")
        prepared = prepare_upload(image_path, optimize=optimize_image)
        size_kb = len(prepared.raw) / 1024
        note = f" ({prepared.note})" if prepared.note else ""
        self._log("info", f"Fotoğraf hazır: {os.path.basename(image_path)} · ~{size_kb:.0f} KB{note}")
        first_file = self.upload(prepared)

        last_file = None
        if last_image_path:
            if os.path.exists(last_image_path):
                self._log("status", "2/4 · Son kare yükleniyor…")
                last_prepared = prepare_upload(last_image_path, optimize=optimize_image)
                self._log(
                    "info",
                    f"Son kare hazır: {os.path.basename(last_image_path)} · ~{len(last_prepared.raw) / 1024:.0f} KB",
                )
                last_file = self.upload(last_prepared)
            else:
                self._log("warn", f"Son kare bulunamadı: {last_image_path}")

        self._log("status", "2/4 · Kare hazırlanıyor…")
        start_file = first_file
        if fit_frame:
            fitted, fitted_canvas = self.fit_keyframe(first_file, canvas)
            if fitted:
                start_file = fitted
                if fitted_canvas != canvas:
                    self._log(
                        "info",
                        f"Sunucu {fitted_canvas} önerdi; seçilen {canvas} kullanılıyor.",
                    )

        data = [
            prompt,
            start_file,
            last_file,
            canvas,
            float(duration),
            float(steps),
            int(seed),
            bool(upsample),
            bool(turbo),
            [],          # nsfw_lora_keys
            None,        # custom_lora_url
            1.0,         # custom_lora_scale
            None,        # custom_lora_trigger
        ]
        for key, value in (extra or {}).items():
            if key == "nsfw_lora_keys":
                data[9] = value
            elif key == "custom_lora_url":
                data[10] = value
            elif key == "custom_lora_scale":
                data[11] = value
            elif key == "custom_lora_trigger":
                data[12] = value

        self._log("status", "3/4 · Video üretiliyor… (bu adım 1-5 dk sürebilir)")
        event_id = self._join(1, data, 26, "video/join")
        stream = self._open_stream()
        try:
            completed = self._wait(stream, event_id, prompt)
        finally:
            stream.close()

        output = (completed.get("output") or {}).get("data") or []
        video = self._first_file(output, (".mp4", "video/"))
        if not video:
            raise ClientError(f"Video ciktisi bulunamadi: {str(output)[:400]}")
        url = self._file_url(video)

        status = ""
        used_seed: Optional[int] = None
        texts: list[str] = []
        for item in output:
            value = self._unwrap(item)
            if isinstance(value, str) and value.strip():
                texts.append(value.strip())
            elif isinstance(value, dict):
                inner = value.get("value")
                if isinstance(inner, str) and inner.strip():
                    texts.append(inner.strip())
        for text in texts:
            match = re.search(r"seed\s+(-?\d+)", text, re.IGNORECASE)
            if match:
                try:
                    used_seed = int(match.group(1))
                except ValueError:
                    used_seed = None
                break
        if used_seed is None:
            for text in texts:
                if text.isdigit() and len(text) <= 12:
                    used_seed = int(text)
                    break
        for text in texts:
            if not text.isdigit():
                status = text
                break

        self._log("status", "4/4 · Video indiriliyor…")
        video_bytes = self.transport.download_result(
            url,
            {
                "accept": "*/*",
                "referer": BASE_URL + "/?__theme=dark",
                "user-agent": DEFAULT_UA,
            },
            label="video/indir",
        )

        elapsed = time.time() - started
        self._log("ok", f"Tamamlandı · {len(video_bytes) / 1024 / 1024:.1f} MB · {elapsed:.1f} sn")
        return VideoResult(
            video_bytes=video_bytes,
            video_url=url,
            status=status,
            prompt_used=prompt,
            seed=used_seed,
            elapsed=elapsed,
            canvas=canvas,
            duration=float(duration),
            proxy_log=[p.label for p in self.transport.used],
        )


# --------------------------------------------------------------------------- #
#  CLI (arayuz olmadan hizli test)
# --------------------------------------------------------------------------- #


def _cli() -> int:
    import argparse

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="MiniMax H3 image-to-video istemcisi (HAR'dan reverse edildi)")
    parser.add_argument("--image", required=True, help="Baslangic fotografi")
    parser.add_argument("--last-image", default=None, help="Opsiyonel son kare")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--canvas", default=None, choices=CANVAS_PRESETS,
                        help="Bos birakilirsa fotografin oranina/cozunurlugune gore otomatik secilir")
    parser.add_argument("--fit", action="store_true", help="Opsiyonel /_fit_keyframe adimini da calistir")
    parser.add_argument("--duration", type=float, default=5)
    parser.add_argument("--steps", type=int, default=25)
    parser.add_argument("--seed", type=int, default=-1)
    parser.add_argument("--upsample", action="store_true")
    parser.add_argument("--turbo", action="store_true")
    parser.add_argument("--out", default="outputs")
    parser.add_argument("--proxy-file", default=None)
    parser.add_argument("--no-proxy", action="store_true")
    args = parser.parse_args()

    pool = None
    if not args.no_proxy:
        proxy_file = args.proxy_file or ProxyPool.find_default(os.getcwd())
        if proxy_file:
            pool = ProxyPool(proxy_file)
    else:
        print("Proxy KAPALI")

    client = MiniMaxVideoClient(proxy_pool=pool, on_log=lambda lv, m: print(f"{lv:6} {m}"))
    result = client.generate(
        args.image,
        args.prompt,
        last_image_path=args.last_image,
        canvas=args.canvas,
        auto_canvas=args.canvas is None,
        fit_frame=args.fit,
        duration=args.duration,
        steps=args.steps,
        seed=args.seed,
        randomize=args.seed < 0,
        upsample=args.upsample,
        turbo=args.turbo,
    )
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"minimax_video_{time.strftime('%Y%m%d_%H%M%S')}.mp4")
    with open(path, "wb") as fh:
        fh.write(result.video_bytes)
    print(f"Kaydedildi: {path} · {result.size_mb:.1f} MB · seed {result.seed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
