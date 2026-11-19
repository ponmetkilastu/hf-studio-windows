"""P-H3-Image (PrunaAI) HF Space icin istemci.

Tersine muhendislik kaynagi: ``huggingface.co.ph3.imgedit.har``
Space: https://huggingface.co/spaces/PrunaAI/P-H3-Image
Host : https://prunaai-p-h3-image.hf.space
Gradio: 6.30.0

HAR'dan cikarilan uretim zinciri:

  1. POST /gradio_api/upload?upload_id=<id>       (multipart, alan adi "files")
     -> ["/tmp/gradio/<hash>/<dosya>"]
  2. POST /gradio_api/queue/join?__theme=dark     fn_index 1 = /edit
     {"data":[source, instruction, ref2..ref8, resolution, upsample, seed, randomize],
      "event_data":null, "fn_index":1, "trigger_id":null, "session_hash":"..."}
     -> {"event_id":"..."}
  3. GET /gradio_api/queue/data?session_hash=... (SSE, process_completed)
     output.data[0] = {"image_data": "data:image/jpeg;base64,..."}  (gorsel GOMULU)
     -> ek indirme istegi YOKTUR; base64 cozulur. (FileData/path yolu da desteklenir.)

  /generate icin fn_index 0, 6 elemanli data:
     [prompt, aspect, resolution, upsample, seed, randomize]

Parametrelerin gonderilme bicimi (onemli):

  * Bu space'te gorseller FileData SARMALAYICISI ICINDE DEGIL, dogrudan
    ``/tmp/gradio/...`` PATH STRING'i olarak gonderilir (component tipi "Api"/string).
    HAR'daki gercek data: ``["/tmp/gradio/.../d.jpg", "angry", null, null, null,
    null, null, null, null, "8 MP", true, 42, true]``.
  * ``trigger_id: null`` gonderilir (diger space'lerde sayiydi).
  * ``/edit`` 13 eleman: source, instruction, ref2..ref8 (7 adet, bos null),
    resolution, upsample, seed, randomize.参照 gorseller de path string'dir.
  * ``/generate`` 6 eleman: prompt, aspect, resolution, upsample, seed, randomize.
  * HAR'da 12 ``/workflow/gradio_api/component_server`` istegi (curated_modalities,
    list_bound_fns, get_token vb.) ve 1 workflow canvas join'i (fn 0, data=[])
    vardir; hepsi UI/meta icindir, uretimi etkilemez ve ATLANIR (REVERSE.md).
  * Join isteklerinde ``x-zerogpu-*`` ve ``x-gradio-user`` gorunur; istemci
    bunlari bilincli olarak GONDERMEZ (bkz. REVERSE.md "Zorunlu kurallar").

Not: Authorization / cookie / HF tokeni yoktur ve gonderilmez.
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

BASE_URL = "https://prunaai-p-h3-image.hf.space"
SPACE_ID = "PrunaAI/P-H3-Image"

QUEUE_JOIN = BASE_URL + "/gradio_api/queue/join?__theme=dark"
QUEUE_DATA = BASE_URL + "/gradio_api/queue/data"
UPLOAD_URL = BASE_URL + "/gradio_api/upload"

FN_GENERATE = 0
FN_EDIT = 1

ASPECTS = ["4:3", "1:1", "3:4", "16:9", "9:16", "3:2", "2:3", "21:9"]
RESOLUTIONS = ["8 MP", "4 MP", "16 MP", "2 MP", "1 MP"]
DEFAULT_ASPECT = "4:3"
DEFAULT_RESOLUTION = "8 MP"
MAX_REFS = 7  # ref2..ref8


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
    project: str = ""
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


class PH3Client:
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
        # ZeroGPU / gradio-user oturum basliklari bilincli olarak EKLENMEZ (REVERSE.md).
        return headers

    def _join(self, fn_index: int, data: list, label: str) -> str:
        payload = {
            "data": data,
            "event_data": None,
            "fn_index": fn_index,
            "trigger_id": None,   # HAR'da null
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
        if depth > 8:
            return node
        if isinstance(node, dict):
            if node.get("__type__") == "update" and "value" in node:
                return PH3Client._unwrap(node["value"], depth + 1)
            if set(node) == {"value"} and isinstance(node["value"], (dict, list)):
                return PH3Client._unwrap(node["value"], depth + 1)
        return node

    @staticmethod
    def _first_image(node, depth: int = 0) -> Optional[dict]:
        if depth > 10:
            return None
        if isinstance(node, dict):
            # dogrudan path/url iceren sozluk
            url = str(node.get("url") or "")
            path = str(node.get("path") or "")
            mime = str(node.get("mime_type") or node.get("mime") or "")
            if (any(k in f"{url} {path}".lower() for k in (".png", ".jpg", ".jpeg", ".webp"))
                    or mime.startswith("image/")):
                return node
            # anahtarli sozluk: {"image": FileData, "seed": ..., ...}
            for value in node.values():
                found = PH3Client._first_image(value, depth + 1)
                if found:
                    return found
        elif isinstance(node, (list, tuple)):
            for item in node:
                found = PH3Client._first_image(item, depth + 1)
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

    def upload(self, upload: PreparedUpload) -> str:
        """Gorseli yukler ve /tmp/gradio/... PATH STRING'i dondurur (FileData degil)."""
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
        return path

    @staticmethod
    def build_edit_data(source: str, instruction: str, refs: Optional[list[str]],
                        resolution: str, upsample: bool, seed: int, randomize: bool) -> list:
        """``/edit`` icin 13 elemanli ``data`` dizisi (fn_index 1)."""
        refs = (refs or [])[:MAX_REFS]
        refs += [None] * (MAX_REFS - len(refs))
        return [source, instruction, *refs, resolution, bool(upsample), int(seed), bool(randomize)]

    @staticmethod
    def build_generate_data(prompt: str, aspect: str, resolution: str,
                            upsample: bool, seed: int, randomize: bool) -> list:
        """``/generate`` icin 6 elemanli ``data`` dizisi (fn_index 0)."""
        return [prompt, aspect, resolution, bool(upsample), int(seed), bool(randomize)]

    @staticmethod
    def _find_image_data(node, depth: int = 0) -> Optional[str]:
        """Cikti agacinda ``image_data`` (data URI / base64) alanini bulur.

        Bu space sonucu FileData/path yerine ``{"image_data": "data:image/jpeg;base64,..."}``
        seklinde dondurur. Harici bir GET indirmeye gerek yoktur.
        """
        if depth > 10:
            return None
        if isinstance(node, dict):
            # "image_data" anahtari tek basina yeterli gosterge
            value = node.get("image_data")
            if isinstance(value, str) and value:
                return value
            for key in ("image", "data"):
                value = node.get(key)
                if isinstance(value, str) and (
                    value.startswith("data:image/") or len(value) > 1000
                ):
                    return value
            for value in node.values():
                found = PH3Client._find_image_data(value, depth + 1)
                if found:
                    return found
        elif isinstance(node, (list, tuple)):
            for item in node:
                found = PH3Client._find_image_data(item, depth + 1)
                if found:
                    return found
        return None

    @staticmethod
    def _decode_image_data(value: str) -> bytes:
        """``data:image/jpeg;base64,XXX`` veya ham base64 -> bytes."""
        import base64
        raw = value
        if raw.startswith("data:"):
            # "data:image/jpeg;base64,...." -> virgulden sonrasi
            if "," not in raw:
                raise ClientError("Bozuk data URI (virgul yok).")
            raw = raw.split(",", 1)[1]
        try:
            return base64.b64decode(raw)
        except Exception as exc:
            raise ClientError(f"Gorsel base64 cozulemedi: {exc}") from exc

    def _finish(self, completed: dict, started: float, label: str) -> ImageResult:
        output = (completed.get("output") or {}).get("data") or []
        result_node = self._unwrap(output[0]) if output else None

        # 1) Tercih edilen yol: image_data (data URI / base64)
        data_uri = self._find_image_data(result_node)
        url = ""
        if data_uri:
            self._log("info", "Sonuc data URI olarak alindi (indirme gerekmedi)")
            image_bytes = self._decode_image_data(data_uri)
        else:
            # 2) Geri dönüş: FileData / path / url
            image = self._first_image(output[:1] if output else [])
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

        # cikti sozlugunden seed/proje bilgisi
        seed = None
        project = ""
        if isinstance(result_node, dict):
            for key in ("seed", "used_seed"):
                if isinstance(result_node.get(key), (int, float)):
                    seed = int(result_node[key]); break
            project = str(result_node.get("project") or "")
        elapsed = time.time() - started
        self._log("ok", f"Tamamlandı · {len(image_bytes) / 1024:.0f} KB · {elapsed:.1f} sn"
                        + (f" · seed {seed}" if seed is not None else ""))
        return ImageResult(image_bytes=image_bytes, image_url=url, seed=seed,
                           project=project, elapsed=elapsed,
                           proxy_log=[p.label for p in self.transport.used])

    def generate(self, prompt: str, aspect: str = DEFAULT_ASPECT,
                 resolution: str = DEFAULT_RESOLUTION, upsample: bool = True,
                 seed: int = 42, randomize: bool = True) -> ImageResult:
        """Metinden gorsel: /generate (fn_index 0)."""
        started = time.time()
        if not (prompt or "").strip():
            raise ClientError("Prompt bos olamaz.")
        self.session_hash = _random_id(10)
        self.transport.begin_run()
        self._log("info", f"Oturum {self.session_hash} · {SPACE_ID} · /generate · {aspect} · {resolution}")
        data = self.build_generate_data(prompt.strip(), aspect, resolution, upsample, seed, randomize)
        self._log("info", f"join · fn_index={FN_GENERATE} · {len(data)} parametre")
        self._log("status", "Görsel üretiliyor…")
        event_id = self._join(FN_GENERATE, data, "generate/join")
        stream = self._open_stream()
        try:
            completed = self._wait(stream, event_id)
        finally:
            stream.close()
        result = self._finish(completed, started, "generate")
        result.prompt = prompt.strip()
        return result

    def edit(self, source_path: str, instruction: str, ref_paths: Optional[list[str]] = None,
             resolution: str = DEFAULT_RESOLUTION, upsample: bool = True,
             seed: int = 42, randomize: bool = True, optimize_images: bool = True) -> ImageResult:
        """Gorsel duzenleme: /edit (fn_index 1), en fazla 7 ek referans."""
        started = time.time()
        if not (instruction or "").strip():
            raise ClientError("Duzenleme talimati bos olamaz.")
        if not source_path or not os.path.exists(source_path):
            raise ClientError("Kaynak gorsel gerekli.")
        self.session_hash = _random_id(10)
        self.transport.begin_run()
        self._log("info", f"Oturum {self.session_hash} · {SPACE_ID} · /edit · {resolution}")

        prep = prepare_upload(source_path, optimize=optimize_images)
        self._log("status", "1/3 · Kaynak gorsel yukleniyor…")
        source = self.upload(prep)
        refs: list[str] = []
        valid_refs = [p for p in (ref_paths or []) if p and os.path.exists(p)][:MAX_REFS]
        for i, rp in enumerate(valid_refs, 1):
            self._log("status", f"2/3 · Referans {i}/{len(valid_refs)} yukleniyor…")
            rprep = prepare_upload(rp, optimize=optimize_images)
            refs.append(self.upload(rprep))

        data = self.build_edit_data(source, instruction.strip(), refs,
                                    resolution, upsample, seed, randomize)
        self._log("info", f"join · fn_index={FN_EDIT} · {len(data)} parametre · {len(refs)} referans")
        self._log("status", "3/3 · Gorsel uretiliyor…")
        event_id = self._join(FN_EDIT, data, "edit/join")
        stream = self._open_stream()
        try:
            completed = self._wait(stream, event_id)
        finally:
            stream.close()
        result = self._finish(completed, started, "edit")
        result.prompt = instruction.strip()
        return result


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
    parser = argparse.ArgumentParser(description="P-H3-Image istemcisi (HAR'dan reverse edildi)")
    parser.add_argument("--mode", choices=("generate", "edit"), default="generate")
    parser.add_argument("--prompt", default="A cinematic portrait in soft natural light")
    parser.add_argument("--instruction", default=None, help="edit modunda talimat")
    parser.add_argument("--source", default=None, help="edit modunda kaynak gorsel")
    parser.add_argument("--ref", action="append", default=[], help="ek referans (en fazla 7)")
    parser.add_argument("--aspect", default=DEFAULT_ASPECT)
    parser.add_argument("--resolution", default=DEFAULT_RESOLUTION)
    parser.add_argument("--no-upsample", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--fixed-seed", action="store_true")
    parser.add_argument("--out", default="outputs")
    parser.add_argument("--proxy-file", default=None)
    parser.add_argument("--no-proxy", action="store_true")
    args = parser.parse_args()

    pool = None
    if not args.no_proxy:
        proxy_file = args.proxy_file or ProxyPool.find_default(os.getcwd())
        if proxy_file:
            pool = ProxyPool(proxy_file)
    client = PH3Client(proxy_pool=pool, on_log=lambda lv, m: print(f"{lv:6} {m}"))
    if args.mode == "edit":
        result = client.edit(
            args.source or "", args.instruction or args.prompt, ref_paths=args.ref,
            resolution=args.resolution, upsample=not args.no_upsample,
            seed=args.seed, randomize=not args.fixed_seed,
        )
    else:
        result = client.generate(
            args.prompt, aspect=args.aspect, resolution=args.resolution,
            upsample=not args.no_upsample, seed=args.seed, randomize=not args.fixed_seed,
        )
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"ph3_{time.strftime('%Y%m%d_%H%M%S')}.png")
    with open(path, "wb") as fh:
        fh.write(result.image_bytes)
    print(f"Kaydedildi: {path} · {result.size_kb:.0f} KB · seed {result.seed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
