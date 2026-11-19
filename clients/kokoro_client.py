"""Kokoro TTS (hexgrad) HF Space istemcisi.

Kaynak: ``huggingface.co.kokoro.tts.fast.har``
Space: https://huggingface.co/spaces/hexgrad/Kokoro-TTS
Host : https://hexgrad-kokoro-tts.hf.space  (Gradio 5.24.0)

HAR uretim zinciri (bkz. docs/REVERSE.md):
  1. POST /gradio_api/queue/join?__theme=dark
     fn_index=4 (Generate), trigger_id=2,
     data=[text, voice, speed, hardware] -> {"event_id": "..."}
  2. GET /gradio_api/queue/data?session_hash=... (SSE) -> process_completed
     output.data[0] = ses FileData (audio.wav), data[1] = kullanilan token'lar
  3. GET /gradio_api/file=/tmp/gradio/<hash>/audio.wav -> WAV

Parametreler /config component'lerinden dogrulandi:
  [22(text), 24(voice), 27(speed), 25(hardware)]
  voice varsayilan "af_heart" (28 secenek), speed 0.5-2.0 (adim 0.1),
  hardware true = ZeroGPU, false = CPU.

REVERSE.md: x-zerogpu-* / cookie / Authorization GONDERILMEZ.
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

BASE_URL = "https://hexgrad-kokoro-tts.hf.space"
SPACE_ID = "hexgrad/Kokoro-TTS"

QUEUE_JOIN = BASE_URL + "/gradio_api/queue/join?__theme=dark"
QUEUE_DATA = BASE_URL + "/gradio_api/queue/data"

FN_GENERATE = 4
TRIGGER_ID = 2

# /config component 24 choices
VOICES: list[tuple[str, str]] = [
    ("🇺🇸 🚺 Heart ❤️", "af_heart"),
    ("🇺🇸 🚺 Bella 🔥", "af_bella"),
    ("🇺🇸 🚺 Nicole 🎧", "af_nicole"),
    ("🇺🇸 🚺 Aoede", "af_aoede"),
    ("🇺🇸 🚺 Kore", "af_kore"),
    ("🇺🇸 🚺 Sarah", "af_sarah"),
    ("🇺🇸 🚺 Nova", "af_nova"),
    ("🇺🇸 🚺 Sky", "af_sky"),
    ("🇺🇸 🚺 Alloy", "af_alloy"),
    ("🇺🇸 🚺 Jessica", "af_jessica"),
    ("🇺🇸 🚺 River", "af_river"),
    ("🇺🇸 🚹 Michael", "am_michael"),
    ("🇺🇸 🚹 Fenrir", "am_fenrir"),
    ("🇺🇸 🚹 Puck", "am_puck"),
    ("🇺🇸 🚹 Echo", "am_echo"),
    ("🇺🇸 🚹 Eric", "am_eric"),
    ("🇺🇸 🚹 Liam", "am_liam"),
    ("🇺🇸 🚹 Onyx", "am_onyx"),
    ("🇺🇸 🚹 Santa", "am_santa"),
    ("🇺🇸 🚹 Adam", "am_adam"),
    ("🇬🇧 🚺 Emma", "bf_emma"),
    ("🇬🇧 🚺 Isabella", "bf_isabella"),
    ("🇬🇧 🚺 Alice", "bf_alice"),
    ("🇬🇧 🚺 Lily", "bf_lily"),
    ("🇬🇧 🚹 George", "bm_george"),
    ("🇬🇧 🚹 Fable", "bm_fable"),
    ("🇬🇧 🚹 Lewis", "bm_lewis"),
    ("🇬🇧 🚹 Daniel", "bm_daniel"),
]
VOICE_VALUES = [v for _, v in VOICES]
DEFAULT_VOICE = "af_heart"
SPEED_MIN, SPEED_MAX = 0.5, 2.0
MAX_CHARS = 500  # /config Input Text: "Up to ~500 characters per Generate"


@dataclass
class AudioResult:
    audio_bytes: bytes
    audio_url: str
    text: str = ""
    tokens: str = ""
    elapsed: float = 0.0
    proxy_log: list[str] = field(default_factory=list)

    @property
    def size_kb(self) -> float:
        return len(self.audio_bytes) / 1024


def _random_id(length: int) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def build_generate_data(text: str, voice: str, speed: float, hardware: bool) -> list:
    """/Generate icin 4 elemanli data dizisi (fn_index 4)."""
    return [text, voice, float(speed), bool(hardware)]


class KokoroClient:
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

    def _join(self, data: list, label: str) -> str:
        payload = {
            "data": data, "event_data": None,
            "fn_index": FN_GENERATE, "trigger_id": TRIGGER_ID,
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
            self._headers(sse=True), timeout=(30, 600), label="queue/sse",
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
                    rank = message.get("rank")
                    eta = message.get("rank_eta")
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
                return KokoroClient._unwrap(node["value"], depth + 1)
        return node

    @staticmethod
    def _find_audio(node, depth: int = 0) -> Optional[dict]:
        if depth > 8:
            return None
        if isinstance(node, dict):
            url = str(node.get("url") or "")
            path = str(node.get("path") or "")
            mime = str(node.get("mime_type") or node.get("mime") or "")
            if (any(k in f"{url} {path}".lower() for k in (".wav", ".mp3", ".flac", ".ogg"))
                    or mime.startswith("audio/")):
                return node
            for value in node.values():
                found = KokoroClient._find_audio(value, depth + 1)
                if found:
                    return found
        elif isinstance(node, (list, tuple)):
            for item in node:
                found = KokoroClient._find_audio(item, depth + 1)
                if found:
                    return found
        return None

    def generate(self, text: str, voice: str = DEFAULT_VOICE,
                 speed: float = 1.0, hardware: bool = True) -> AudioResult:
        """Metinden ses: /Generate (fn_index 4)."""
        started = time.time()
        text = (text or "").strip()
        if not text:
            raise ClientError("Metin bos olamaz.")
        if len(text) > MAX_CHARS:
            self._log("warn", f"Metin {len(text)} karakter; space üst sınırı ~{MAX_CHARS}.")
        if voice not in VOICE_VALUES:
            voice = DEFAULT_VOICE
        speed = max(SPEED_MIN, min(SPEED_MAX, float(speed)))

        self.session_hash = _random_id(10)
        self.transport.begin_run()
        self._log("info", f"Oturum {self.session_hash} · {SPACE_ID} · "
                          f"ses {voice} · hız {speed} · {'GPU' if hardware else 'CPU'}")

        data = build_generate_data(text, voice, speed, hardware)
        self._log("info", f"join · fn_index={FN_GENERATE} · {len(data)} parametre")
        self._log("status", "Ses üretiliyor…")
        event_id = self._join(data, "generate/join")
        stream = self._open_stream()
        try:
            completed = self._wait(stream, event_id)
        finally:
            stream.close()

        output = (completed.get("output") or {}).get("data") or []
        output = [self._unwrap(v) for v in output]
        audio = self._find_audio(output)
        if not audio:
            raise ClientError(f"Ses ciktisi bulunamadi: {str(output)[:400]}")
        url = str(audio.get("url") or "")
        if not url:
            path = audio.get("path")
            if not path:
                raise ClientError("Ses icin URL/path yok.")
            url = BASE_URL + "/gradio_api/file=" + (str(path) if str(path).startswith("/") else "/" + str(path))
        self._log("status", "Ses dosyasi indiriliyor…")
        audio_bytes = self.transport.download_result(
            url,
            {"accept": "audio/*,*/*;q=0.8",
             "referer": BASE_URL + "/?__theme=dark", "user-agent": DEFAULT_UA},
            label="ses/indir",
        )
        tokens = output[1] if len(output) > 1 and isinstance(output[1], str) else ""
        elapsed = time.time() - started
        self._log("ok", f"Tamamlandı · {len(audio_bytes) / 1024:.0f} KB · {elapsed:.1f} sn")
        return AudioResult(audio_bytes=audio_bytes, audio_url=url, text=text,
                           tokens=tokens, elapsed=elapsed,
                           proxy_log=[p.label for p in self.transport.used])


def _cli() -> int:
    import argparse
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Kokoro TTS istemcisi (HAR'dan reverse edildi)")
    parser.add_argument("--text", required=True)
    parser.add_argument("--voice", default=DEFAULT_VOICE, choices=VOICE_VALUES)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--cpu", action="store_true", help="ZeroGPU yerine CPU kullan")
    parser.add_argument("--proxy-file", default=None)
    parser.add_argument("--no-proxy", action="store_true")
    parser.add_argument("--out", default="outputs")
    args = parser.parse_args()

    pool = None
    if not args.no_proxy:
        pf = args.proxy_file or ProxyPool.find_default(os.getcwd())
        if pf:
            pool = ProxyPool(pf)
    client = KokoroClient(proxy_pool=pool, on_log=lambda lv, m: print(f"{lv:6} {m}"))
    result = client.generate(args.text, voice=args.voice, speed=args.speed,
                             hardware=not args.cpu)
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"kokoro_{time.strftime('%Y%m%d_%H%M%S')}.wav")
    with open(path, "wb") as fh:
        fh.write(result.audio_bytes)
    print(f"Kaydedildi: {path} · {result.size_kb:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
