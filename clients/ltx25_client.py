"""Lightricks LTX-2.5 (metinden / fotograftan video) HF Space istemcisi.

Kaynak: ``huggingface.co.ltx2.5.har``
Space: https://huggingface.co/spaces/Lightricks/LTX-2.5
Host : https://lightricks-ltx-2-5.hf.space  (Gradio 6.13.0)

HAR uretim zinciri (bkz. docs/REVERSE.md):
  1. (opsiyonel gorsel) POST /gradio_api/upload?upload_id=<id>  (multipart, "files")
     -> ["/tmp/gradio/<hash>/krea_....png"]
  2. POST /gradio_api/queue/join?__theme=system  fn_index=0
     (/set_dims_from_image), trigger_id=4, data=[FileData] -> SSE
     -> output.data = [height, width]  (gorsel oranina gore ayarlanan olculer)
  3. POST /gradio_api/queue/join?__theme=system  fn_index=2 (/run), trigger_id=22,
     10 elemanli data -> SSE -> output.data =
       [video FileData, prompt_sent, seed_used, length_generated]
  4. GET /gradio_api/file=/tmp/gradio/<hash>/tmp*.mp4 -> MP4

Atlana: GET /gradio_api/upload_progress (SSE, yalnizca yukleme ilerlemesi).

10 parametrenin sirasi /gradio_api/info + /config inputs
[5,4,9,8,11,16,14,12,17,19] ile dogrulandi:
  prompt, image_path, height, width, duration_s, seed, decoder,
  auto_len, randomize_seed, do_enhance

Gorsel opsiyoneldir: verilmezse metinden videoya (t2v) calisir ve fn 0 atlanir.

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
import string
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import requests

from clients.hf_image_client import ClientError, DEFAULT_UA, ProxyPool, RotatingTransport

BASE_URL = "https://lightricks-ltx-2-5.hf.space"
SPACE_ID = "Lightricks/LTX-2.5"

UPLOAD_URL = BASE_URL + "/gradio_api/upload"
QUEUE_JOIN = BASE_URL + "/gradio_api/queue/join?__theme=system"
QUEUE_DATA = BASE_URL + "/gradio_api/queue/data"

FN_DIMS = 0
FN_RUN = 2
TRIGGER_DIMS = 4
TRIGGER_RUN = 22

DEFAULT_PROMPT = "A kingfisher perched on a branch, morning light, gentle camera push-in"
DIM_MIN, DIM_MAX = 512, 1536
DURATION_MIN, DURATION_MAX = 1.0, 5.0
SEED_MAX = 2147483647
DECODERS = ("conv", "diffusion")
DEFAULT_DECODER = "conv"
DEFAULT_HEIGHT = 1472
DEFAULT_WIDTH = 832
DEFAULT_DURATION = 2.0
DEFAULT_SEED = 42


@dataclass
class VideoResult:
    video_bytes: bytes
    video_url: str
    seed: Optional[int] = None
    prompt: str = ""
    length: str = ""
    height: int = 0
    width: int = 0
    elapsed: float = 0.0
    proxy_log: list[str] = field(default_factory=list)

    @property
    def size_kb(self) -> float:
        return len(self.video_bytes) / 1024


@dataclass
class PreparedUpload:
    path: str
    filename: str
    raw: bytes
    mime: str


def _random_id(length: int) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def prepare_upload(path: str) -> PreparedUpload:
    raw = open(path, "rb").read()
    base = os.path.basename(path)
    mime = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(os.path.splitext(base)[1].lower(), "image/png")
    return PreparedUpload(path, base, raw, mime)


def build_dims_data(image: dict) -> list:
    """/set_dims_from_image (fn 0) icin 1 elemanli data: yalnizca gorsel."""
    return [image]


def build_run_data(prompt: str, image: Optional[dict], height: int, width: int,
                   duration: float, seed: int, decoder: str, auto_len: bool,
                   randomize_seed: bool, do_enhance: bool) -> list:
    """/run (fn 2) icin 10 elemanli data dizisi. Sira /info ile dogrulandi."""
    decoder = (decoder or DEFAULT_DECODER).strip().lower()
    if decoder not in DECODERS:
        decoder = DEFAULT_DECODER
    return [
        (prompt or "").strip(), image, int(height), int(width),
        float(duration), int(seed), decoder, bool(auto_len),
        bool(randomize_seed), bool(do_enhance),
    ]


class LTX25Client:
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

    def _join(self, fn_index: int, trigger_id: int, data: list, label: str) -> str:
        # Gradio 6.13: HAR govdesinde event_data yok; data/fn_index/trigger_id yeterli.
        payload = {
            "data": data, "fn_index": fn_index,
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
                return LTX25Client._unwrap(node["value"], depth + 1)
        return node

    @staticmethod
    def _find_video(node, depth: int = 0) -> Optional[dict]:
        if depth > 8:
            return None
        if isinstance(node, dict):
            url = str(node.get("url") or "")
            path = str(node.get("path") or "")
            mime = str(node.get("mime_type") or node.get("mime") or "")
            if (any(k in f"{url} {path}".lower() for k in (".mp4", ".webm"))
                    or mime.startswith("video/")):
                return node
            for value in node.values():
                found = LTX25Client._find_video(value, depth + 1)
                if found:
                    return found
        elif isinstance(node, (list, tuple)):
            for item in node:
                found = LTX25Client._find_video(item, depth + 1)
                if found:
                    return found
        return None

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

    def generate(self, image_path: Optional[str] = None,
                 prompt: str = DEFAULT_PROMPT,
                 height: int = DEFAULT_HEIGHT, width: int = DEFAULT_WIDTH,
                 duration: float = DEFAULT_DURATION, seed: int = DEFAULT_SEED,
                 decoder: str = DEFAULT_DECODER, auto_len: bool = False,
                 randomize_seed: bool = True,
                 do_enhance: bool = True) -> VideoResult:
        """Video uret: (gorsel varsa upload + /set_dims_from_image) -> /run."""
        started = time.time()
        if not (prompt or "").strip():
            raise ClientError("Prompt bos olamaz.")
        if image_path and not os.path.exists(image_path):
            raise ClientError("Gorsel dosyasi bulunamadi.")

        self.session_hash = _random_id(10)
        self.transport.begin_run()
        mode = "image-to-video" if image_path else "text-to-video"
        self._log("info", f"Oturum {self.session_hash} · {SPACE_ID} · {mode}")

        image: Optional[dict] = None
        used_h, used_w = int(height), int(width)
        step = 0
        total = 4 if image_path else 3

        if image_path:
            step += 1
            self._log("status", f"{step}/{total} · Gorsel yukleniyor…")
            image = self.upload(prepare_upload(image_path))

            # 1) gorsel oranina gore gercek olculer (fn 0: outputs [height, width])
            step += 1
            self._log("status", f"{step}/{total} · Olculer ayarlaniyor…")
            dims_id = self._join(FN_DIMS, TRIGGER_DIMS, build_dims_data(image), "dims/join")
            stream = self._open_stream()
            try:
                dims_msg = self._wait(stream, dims_id)
            finally:
                stream.close()
            dims_data = (dims_msg.get("output") or {}).get("data") or []
            dims_data = [self._unwrap(v) for v in dims_data]
            used_h = dims_data[0] if len(dims_data) > 0 and isinstance(dims_data[0], (int, float)) else height
            used_w = dims_data[1] if len(dims_data) > 1 and isinstance(dims_data[1], (int, float)) else width
            used_h, used_w = int(used_h), int(used_w)
            self._log("info", f"Ayarlanan olculer · {used_w}x{used_h}")

        # 2) video uretimi (HAR fn 2, 10 parametre)
        step += 1
        self._log("status", f"{step}/{total} · Video uretiliyor… (1-5 dakika surebilir)")
        data = build_run_data(prompt, image, used_h, used_w, duration, seed,
                              decoder, auto_len, randomize_seed, do_enhance)
        self._log("info", f"join · fn_index={FN_RUN} · {len(data)} parametre")
        run_id = self._join(FN_RUN, TRIGGER_RUN, data, "run/join")
        stream = self._open_stream()
        try:
            completed = self._wait(stream, run_id)
        finally:
            stream.close()

        output = (completed.get("output") or {}).get("data") or []
        output = [self._unwrap(v) for v in output]
        video = self._find_video(output)
        if not video:
            raise ClientError(f"Video ciktisi bulunamadi: {str(output)[:400]}")
        url = str(video.get("url") or "")
        if not url:
            path = video.get("path")
            if not path:
                raise ClientError("Video icin URL/path yok.")
            url = BASE_URL + "/gradio_api/file=" + (str(path) if str(path).startswith("/") else "/" + str(path))
        step += 1
        self._log("status", f"{step}/{total} · Video indiriliyor…")
        video_bytes = self.transport.download_result(
            url,
            {"accept": "video/mp4,video/*;q=0.9,*/*;q=0.8",
             "referer": BASE_URL + "/?__theme=system", "user-agent": DEFAULT_UA},
            label="video/indir",
        )
        used_seed = None
        if len(output) > 2 and isinstance(output[2], (int, float)):
            used_seed = int(output[2])
        prompt_sent = str(output[1]) if len(output) > 1 and output[1] is not None else ""
        length = str(output[3]) if len(output) > 3 and output[3] is not None else ""
        elapsed = time.time() - started
        self._log("ok", f"Tamamlandı · {len(video_bytes) / 1024 / 1024:.1f} MB · {elapsed:.1f} sn")
        return VideoResult(video_bytes=video_bytes, video_url=url, seed=used_seed,
                           prompt=prompt_sent, length=length,
                           height=used_h, width=used_w, elapsed=elapsed,
                           proxy_log=[p.label for p in self.transport.used])


def _cli() -> int:
    import argparse
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="LTX-2.5 video istemcisi (HAR'dan reverse edildi)")
    parser.add_argument("--image", default=None, help="Opsiyonel kaynak gorsel (i2v)")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--decoder", choices=DECODERS, default=DEFAULT_DECODER)
    parser.add_argument("--auto-len", action="store_true")
    parser.add_argument("--no-enhance", action="store_true")
    parser.add_argument("--no-proxy", action="store_true")
    parser.add_argument("--proxy-file", default=None)
    parser.add_argument("--out", default="outputs")
    args = parser.parse_args()

    pool = None
    if not args.no_proxy:
        pf = args.proxy_file or ProxyPool.find_default(os.getcwd())
        if pf:
            pool = ProxyPool(pf)
    client = LTX25Client(proxy_pool=pool, on_log=lambda lv, m: print(f"{lv:6} {m}"))
    result = client.generate(
        args.image, args.prompt, height=args.height, width=args.width,
        duration=args.duration, seed=args.seed, decoder=args.decoder,
        auto_len=args.auto_len, do_enhance=not args.no_enhance,
    )
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"ltx25_{time.strftime('%Y%m%d_%H%M%S')}.mp4")
    with open(path, "wb") as fh:
        fh.write(result.video_bytes)
    print(f"Kaydedildi: {path} · {result.size_kb:.0f} KB · {result.width}x{result.height} · seed {result.seed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
