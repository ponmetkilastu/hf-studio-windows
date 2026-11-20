"""Wan 2.2 Fast I2V (14B + Lightning LoRA) HF Space istemcisi.

Kaynak: ``huggingface.co.wan22.aoti.fast..har``
Space: https://huggingface.co/spaces/zerogpu-aoti/wan2-2-fp8da-aoti-faster
Host : https://zerogpu-aoti-wan2-2-fp8da-aoti-faster.hf.space  (Gradio 6.1.0)

HAR uretim zinciri (bkz. docs/REVERSE.md):
  1. POST /gradio_api/upload?upload_id=<id>  (multipart, alan "files")
     -> ["/tmp/gradio/<hash>/qwen_....png"]
  2. POST /gradio_api/queue/join  fn_index=0 (/generate_video), trigger_id=16,
     9 elemanli data -> SSE -> output.data = [video FileData, kullanilan_seed]
  3. GET /gradio_api/file=/tmp/gradio/<hash>/tmp*.mp4 -> MP4

Atlana: GET /gradio_api/upload_progress (SSE, yalnizca yukleme ilerlemesi).

9 parametrenin sirasi /gradio_api/config inputs
[5, 6, 12, 9, 7, 13, 14, 10, 11] ve /gradio_api/info ile dogrulandi:
  image, prompt, steps, negative_prompt, duration_seconds,
  guidance_scale, guidance_scale_2, seed, randomize_seed

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
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import requests

from clients.hf_image_client import ClientError, DEFAULT_UA, ProxyPool, RotatingTransport

BASE_URL = "https://zerogpu-aoti-wan2-2-fp8da-aoti-faster.hf.space"
SPACE_ID = "zerogpu-aoti/wan2-2-fp8da-aoti-faster"

UPLOAD_URL = BASE_URL + "/gradio_api/upload"
QUEUE_JOIN = BASE_URL + "/gradio_api/queue/join?__theme=dark"
QUEUE_DATA = BASE_URL + "/gradio_api/queue/data"

FN_GENERATE = 0
TRIGGER_GENERATE = 16

DEFAULT_PROMPT = "make this image come alive, cinematic motion, smooth animation"
DEFAULT_NEGATIVE = (
    "色调艳丽, 过曝, 静态, 细节模糊不清, 字幕, 风格, 作品, 画作, 画面, 静止, 整体发灰, "
    "最差质量, 低质量, JPEG压缩残留, 丑陋的, 残缺的, 多余的手指, 画得不好的手部, "
    "画得不好的脸部, 畸形的, 毁容的, 形态畸形的肢体, 手指融合, 静止不动的画面, "
    "杂乱的背景, 三条腿, 背景人很多, 倒着走"
)

STEPS_MIN, STEPS_MAX, STEPS_DEFAULT = 1, 30, 6
DURATION_MIN, DURATION_MAX, DURATION_DEFAULT = 0.5, 5.0, 3.5
GUIDANCE_MIN, GUIDANCE_MAX, GUIDANCE_DEFAULT = 0.0, 10.0, 1.0
SEED_MIN, SEED_MAX, SEED_DEFAULT = 0, 2147483647, 42


@dataclass
class VideoResult:
    video_bytes: bytes
    video_url: str
    seed: Optional[int] = None
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
    with open(path, "rb") as fh:
        raw = fh.read()
    base = os.path.basename(path)
    mime = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(os.path.splitext(base)[1].lower(), "image/png")
    return PreparedUpload(path, base, raw, mime)


def build_generate_data(image: dict, prompt: str, steps: int, negative: str,
                        duration: float, guidance: float, guidance_2: float,
                        seed: int, randomize_seed: bool) -> list:
    """/generate_video (fn 0) icin 9 elemanli data; sira HAR ile ayni."""
    return [
        image, str(prompt), int(steps), str(negative),
        float(duration), float(guidance), float(guidance_2),
        int(seed), bool(randomize_seed),
    ]


class Wan22Client:
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
        # x-zerogpu-* / cookie / auth bilincli olarak eklenmez (REVERSE.md).
        return headers

    def _join(self, fn_index: int, trigger_id: int, data: list, label: str) -> str:
        # HAR'da event_data alani yok.
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
                return Wan22Client._unwrap(node["value"], depth + 1)
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
                found = Wan22Client._find_video(value, depth + 1)
                if found:
                    return found
        elif isinstance(node, (list, tuple)):
            for item in node:
                found = Wan22Client._find_video(item, depth + 1)
                if found:
                    return found
        elif isinstance(node, str):
            if node.lower().endswith((".mp4", ".webm")):
                return {"path": node}
        return None

    def _run_generate(self, data: list, attempts: int = 3) -> list:
        """ZeroGPU kotasi dolarsa proxy degistirip tekrar dener (istek durumsuz)."""
        for attempt in range(1, attempts + 1):
            try:
                self._log("status", "2/3 · Video üretiliyor… (30-120 sn)")
                event_id = self._join(FN_GENERATE, TRIGGER_GENERATE, data, "generate/join")
                stream = self._open_stream()
                try:
                    message = self._wait(stream, event_id)
                finally:
                    stream.close()
                output = (message.get("output") or {}).get("data") or []
                return [self._unwrap(v) for v in output]
            except ClientError as exc:
                text = str(exc).lower()
                if attempt >= attempts or not ("quota" in text and "gpu" in text):
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
        self._log("ok", f"Yukleme tamam · {prepared.filename} · {len(prepared.raw) / 1024:.0f} KB")
        return {
            "path": path,
            "url": BASE_URL + "/gradio_api/file=" + path,
            "orig_name": prepared.filename,
            "size": len(prepared.raw),
            "mime_type": prepared.mime,
            "meta": {"_type": "gradio.FileData"},
        }

    def generate(self, image_path: str, prompt: str = DEFAULT_PROMPT,
                 negative_prompt: str = DEFAULT_NEGATIVE, steps: int = STEPS_DEFAULT,
                 duration: float = DURATION_DEFAULT,
                 guidance_scale: float = GUIDANCE_DEFAULT,
                 guidance_scale_2: float = GUIDANCE_DEFAULT,
                 seed: int = SEED_DEFAULT, randomize_seed: bool = True) -> VideoResult:
        """Fotograftan video: upload -> /generate_video -> MP4 indir."""
        started = time.time()
        if not image_path or not os.path.exists(image_path):
            raise ClientError("Gorsel dosyasi bulunamadi.")
        if not (prompt or "").strip():
            raise ClientError("Prompt bos olamaz.")
        if not (STEPS_MIN <= int(steps) <= STEPS_MAX):
            raise ClientError(f"Steps {STEPS_MIN}-{STEPS_MAX} araliginda olmali.")
        if not (DURATION_MIN <= float(duration) <= DURATION_MAX):
            raise ClientError(f"Sure {DURATION_MIN}-{DURATION_MAX} sn araliginda olmali.")
        if not (GUIDANCE_MIN <= float(guidance_scale) <= GUIDANCE_MAX):
            raise ClientError(f"Guidance {GUIDANCE_MIN}-{GUIDANCE_MAX} araliginda olmali.")
        if not (GUIDANCE_MIN <= float(guidance_scale_2) <= GUIDANCE_MAX):
            raise ClientError(f"Guidance 2 {GUIDANCE_MIN}-{GUIDANCE_MAX} araliginda olmali.")
        if not (SEED_MIN <= int(seed) <= SEED_MAX):
            raise ClientError(f"Seed {SEED_MIN}-{SEED_MAX} araliginda olmali.")

        self.session_hash = _random_id(10)
        self.transport.begin_run()
        self._log("info", f"Oturum {self.session_hash} · {SPACE_ID} · image-to-video")
        self._log("info", f"steps={int(steps)} · {float(duration):.1f} sn · "
                          f"guidance={float(guidance_scale):g}/{float(guidance_scale_2):g} · "
                          f"seed={'rastgele' if randomize_seed else int(seed)}")

        self._log("status", "1/3 · Görsel yükleniyor…")
        image = self.upload(prepare_upload(image_path))

        data = build_generate_data(
            image, prompt.strip(), steps, negative_prompt or "",
            duration, guidance_scale, guidance_scale_2, seed, randomize_seed,
        )
        self._log("info", f"join · fn_index={FN_GENERATE} · {len(data)} parametre")
        output = self._run_generate(data)

        video = self._find_video(output)
        if not video:
            raise ClientError(f"Video ciktisi bulunamadi: {str(output)[:400]}")
        url = str(video.get("url") or "")
        if not url:
            path = video.get("path")
            if not path:
                raise ClientError("Video icin URL/path yok.")
            url = BASE_URL + "/gradio_api/file=" + (str(path) if str(path).startswith("/") else "/" + str(path))
        self._log("status", "3/3 · Video indiriliyor…")
        video_bytes = self.transport.download_result(
            url,
            {"accept": "video/mp4,video/*;q=0.9,*/*;q=0.8",
             "referer": BASE_URL + "/?__theme=dark", "user-agent": DEFAULT_UA},
            label="video/indir",
        )
        used_seed = None
        if len(output) > 1 and isinstance(output[1], (int, float)):
            used_seed = int(output[1])
        elapsed = time.time() - started
        self._log("ok", f"Tamamlandı · {len(video_bytes) / 1024 / 1024:.1f} MB · {elapsed:.1f} sn")
        return VideoResult(video_bytes=video_bytes, video_url=url, seed=used_seed,
                           elapsed=elapsed, proxy_log=[p.label for p in self.transport.used])


def _cli() -> int:
    import argparse
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Wan 2.2 Fast I2V istemcisi (HAR'dan reverse edildi)")
    parser.add_argument("--image", required=True)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--negative", default=DEFAULT_NEGATIVE)
    parser.add_argument("--steps", type=int, default=STEPS_DEFAULT)
    parser.add_argument("--duration", type=float, default=DURATION_DEFAULT)
    parser.add_argument("--guidance", type=float, default=GUIDANCE_DEFAULT)
    parser.add_argument("--guidance2", type=float, default=GUIDANCE_DEFAULT)
    parser.add_argument("--seed", type=int, default=SEED_DEFAULT)
    parser.add_argument("--no-randomize", action="store_true")
    parser.add_argument("--no-proxy", action="store_true")
    parser.add_argument("--proxy-file", default=None)
    parser.add_argument("--out", default="outputs")
    args = parser.parse_args()

    pool = None
    if not args.no_proxy:
        pf = args.proxy_file or ProxyPool.find_default(os.getcwd())
        if pf:
            pool = ProxyPool(pf)
    client = Wan22Client(proxy_pool=pool, on_log=lambda lv, m: print(f"{lv:6} {m}"))
    result = client.generate(
        args.image, prompt=args.prompt, negative_prompt=args.negative,
        steps=args.steps, duration=args.duration,
        guidance_scale=args.guidance, guidance_scale_2=args.guidance2,
        seed=args.seed, randomize_seed=not args.no_randomize,
    )
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"wan22_{time.strftime('%Y%m%d_%H%M%S')}.mp4")
    with open(path, "wb") as fh:
        fh.write(result.video_bytes)
    print(f"Kaydedildi: {path} · {result.size_kb:.0f} KB · seed {result.seed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
