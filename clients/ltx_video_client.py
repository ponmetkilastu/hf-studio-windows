"""LTX-2.3 10Eros (Hugging Face Space) icin tersine muhendislik istemcisi.

Tersine muhendislik kaynagi: ``huggingface.co.ltx23.har``
Space: https://huggingface.co/spaces/rdata92/LTX-2.3-10Eros
Host : https://rdata92-ltx-2-3-10eros.hf.space

HAR'dan cikarilan akis:

  1. POST /gradio_api/upload?upload_id=<id>      (multipart, alan adi "files")
     -> ["/tmp/gradio/<hash>/<dosya>.png"]
  2. POST /gradio_api/queue/join?__theme=system
     {"data": [<88 parametre>], "fn_index": 0, "trigger_id": 145,
      "session_hash": "<10 karakter>"}
     -> {"event_id": "..."}
  3. GET  /gradio_api/queue/data?session_hash=...   (SSE, process_completed beklenir)
     output.data[0] -> video FileData (…/gradio_api/file=/tmp/gradio/<hash>/output.mp4)
  4. GET  <video url>                                (proxy'siz, 403'te proxy yedegi)

Notlar:
  * HAR'daki hicbir istekte Authorization / cookie / HF tokeni yoktur; bu istemci
    de kimlik dogrulama bilgisi gondermez (proxy kullanici/parola haric).
  * ZeroGPU oturum basliklari (``x-zerogpu-uuid`` / ``x-zerogpu-token``) GOnderilmez;
    tarayicinin oturum kimligidir, API icin gerekli degildir (bkz. REVERSE.md).
  * ``snap_multiple`` ve ``msr_frame_count`` semada string literal gorunse de
    tarayici sayisal deger gonderir; ayni sekilde sayisal gonderilir.
"""


from __future__ import annotations

import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
from paths import ROOT_DIR, CONFIG_DIR, DATA_DIR, OUTPUT_DIR, SETTINGS_DIR, PROXY_FILE


import io
import json
import os
import random
import string
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

import requests

from clients.hf_image_client import (
    ClientError,
    DEFAULT_UA,
    ProxyPool,
    RotatingTransport,
)

BASE_URL = "https://rdata92-ltx-2-3-10eros.hf.space"
SPACE_ID = "rdata92/LTX-2.3-10Eros"

QUEUE_JOIN = BASE_URL + "/gradio_api/queue/join?__theme=system"
QUEUE_DATA = BASE_URL + "/gradio_api/queue/data"
UPLOAD_URL = BASE_URL + "/gradio_api/upload"

PRESETS = ["tuned", "original", "tuned #2", "experimental #1"]
MODES = ["anchor only", "auto face", "manual bbox"]
INPUT_MODES = ["single image (i2v)", "multi-reference (MSR)", "multi-reference (original)"]

DEFAULT_NEGATIVE = (
    "captions, music, transition, VR, bad quality, subtitles, text, watermark, "
    "overlay effects, cartoon, childish, ugly, text, blur, logo, static, low quality, "
    "noise, mutant, horror, film grain"
)

# /generate isteginin 88 parametresi: (ad, varsayilan). Degerler HAR'daki
# tarayici isteginden bire bir alinmistir.
PARAMS: list[tuple[str, object]] = [
    ("image_path", None),
    ("prompt", None),
    ("negative_prompt", DEFAULT_NEGATIVE),
    ("preset", "tuned"),
    ("seconds", 4),
    ("max_width", 1120),
    ("max_height", 1344),
    ("mode", "anchor only"),
    ("face_bbox", None),
    ("likeness_strength", 0.9),
    ("likeness_anchor_strength", 0.15),
    ("latent_anchor_strength", 0.08),
    ("first_frame_strength", 0.82),
    ("seed", -1),
    ("randomize_seed", True),
    ("gen_budget", 0),
    ("target_mp", 1.15),
    ("snap_multiple", 64),
    ("custom_res_enabled", False),
    ("sulphur_lora_strength", 0.15),
    ("sulphur_v1_lora_strength", 0.15),
    ("vbvr_lora_strength", 0.5),
    ("dreamly_lora_strength", 0.6),
    ("synth_lora_strength", 0.0),
    ("plora_lora_strength", 0.0),
    ("singularity_lora_strength", 0.3),
    ("omninft_lora_strength", 0.8),
    ("omninft_bf16_lora_strength", 0.0),
    ("better_motion_lora_strength", 0.0),
    ("physics_v2_lora_strength", 0.0),
    ("hardcut_lora_strength", 0.0),
    ("transition_lora_strength", 0.0),
    ("sulphur_audio_strength", 0.15),
    ("sulphur_v1_audio_strength", 0.15),
    ("vbvr_audio_strength", 0.5),
    ("dreamly_audio_strength", 0.6),
    ("synth_audio_strength", 0.0),
    ("plora_audio_strength", 0.0),
    ("singularity_audio_strength", 0.3),
    ("omninft_audio_strength", 0.8),
    ("omninft_bf16_audio_strength", 0.0),
    ("better_motion_audio_strength", 0.0),
    ("physics_v2_audio_strength", 0.0),
    ("hardcut_audio_strength", 0.0),
    ("transition_audio_strength", 0.0),
    ("cache_at_step", 0),
    ("cache_warmup", 400),
    ("energy_threshold", 0.3),
    ("anchor_similarity_threshold", 0.3),
    ("sigma_string", "0.4824, 0.2412, 0.0"),
    ("input_mode", "single image (i2v)"),
    ("msr_ref2", None),
    ("msr_ref3", None),
    ("msr_ref4", None),
    ("msr_background", None),
    ("msr_frame_count", 41),
    ("msr_guide_strength", 1.0),
    ("msr_lora_strength", 0.7),
    ("prompt_relay_enabled", False),
    ("prompt_segments", None),
    ("scene_chain_enabled", False),
    ("scene_chain_prompt", None),
    ("scene_chain_max_scenes", 2),
    ("scene_chain_frame_overlap", 8),
    ("scene_chain_mid_guide", True),
    ("scene_chain_mid_guide_strength", 0.25),
    ("kv_enabled", False),
    ("kv_strength", 1.0),
    ("audio_ref_enabled", False),
    ("audio_ref_file", None),
    ("audio_ref_guidance_scale", 3.0),
    ("audio_ref_stem_sep", False),
    ("audio_ref_normalize", True),
    ("kf_last_image", None),
    ("kf_strength", 0.82),
    ("kf_mid_enabled", False),
    ("kf_mid_1_image", None),
    ("kf_mid_1_pos", 50),
    ("kf_mid_2_image", None),
    ("kf_mid_2_pos", 50),
    ("kf_mid_3_image", None),
    ("kf_mid_3_pos", 50),
    ("kf_mid_4_image", None),
    ("kf_mid_4_pos", 50),
    ("kf_mid_5_image", None),
    ("kf_mid_5_pos", 50),
    ("profile_name", None),
    ("skip_refine", False),
]

INDEX = {name: i for i, (name, _) in enumerate(PARAMS)}


@dataclass
class PreparedUpload:
    path: str
    filename: str
    raw: bytes
    mime: str
    note: str = ""


def prepare_upload(path: str, optimize: bool = True, max_side: int = 2048, quality: int = 92) -> PreparedUpload:
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
            big = max(im.size) > max_side
            heavy = len(raw) > 4 * 1024 * 1024
            if not big and not heavy and mime != "image/png":
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
    proxy_log: list[str] = field(default_factory=list)

    @property
    def size_mb(self) -> float:
        return len(self.video_bytes) / 1024 / 1024


class LTXVideoClient:
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

    def _headers(self, sse: bool = False, json_body: bool = True) -> dict[str, str]:
        headers = {
            "accept": "text/event-stream" if sse else "*/*",
            "accept-language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            "origin": BASE_URL,
            "referer": BASE_URL + "/?__theme=system",
            "user-agent": DEFAULT_UA,
            "x-gradio-server": BASE_URL + "/",
        }
        if json_body:
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
                out.extend(LTXVideoClient._flatten_strings(item, depth + 1))
            return out
        return []

    def _progress_text(self, message: dict, exclude: str) -> Optional[str]:
        data = (message.get("output") or {}).get("data") or []
        strings = [
            s.strip()
            for s in self._flatten_strings(data)
            if s and s.strip() and len(s) <= 160 and s.strip() != exclude
        ]
        return strings[-1] if strings else None

    def _join(self, fn_index: int, data: list, label: str) -> str:
        payload = {
            "data": data,
            "fn_index": fn_index,
            "trigger_id": 145,
            "session_hash": self.session_hash,
        }
        resp = self.transport.post_json(QUEUE_JOIN, payload, self._headers(), label=label)
        event_id = resp.json().get("event_id")
        if not event_id:
            raise ClientError(f"Sunucu event_id dondurmedi: {resp.text[:300]}")
        self._log("info", f"{label} · event {event_id[:12]}… kuyruga alindi")
        return event_id

    def _open_stream(self):
        return self.transport.open_sse(
            QUEUE_DATA + "?session_hash=" + self.session_hash,
            {**self._headers(sse=True, json_body=False), "content-type": "application/json"},
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

    # -- video cikarimi --------------------------------------------------- #

    @staticmethod
    def _find_video(node, depth: int = 0) -> Optional[dict]:
        """Sonuc agacinda video FileData'sini bulur (Video bileşeni sarmalayicisi dahil)."""
        if depth > 8:
            return None
        if isinstance(node, dict):
            url = node.get("url") or ""
            mime = str(node.get("mime_type") or "")
            if isinstance(url, str) and "/gradio_api/file=" in url and (".mp4" in url or mime.startswith("video")):
                return node
            for key in ("video", "path", "value", "_data"):
                if key in node:
                    found = LTXVideoClient._find_video(node[key], depth + 1)
                    if found:
                        return found
            for value in node.values():
                found = LTXVideoClient._find_video(value, depth + 1)
                if found:
                    return found
        elif isinstance(node, (list, tuple)):
            for item in node:
                found = LTXVideoClient._find_video(item, depth + 1)
                if found:
                    return found
        elif isinstance(node, str) and node.startswith("/tmp/gradio/"):
            return {"path": node}
        return None

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
                "referer": BASE_URL + "/?__theme=system",
                "user-agent": DEFAULT_UA,
                "x-gradio-server": BASE_URL + "/",
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

    def generate(
        self,
        image_path: str,
        prompt: str,
        negative_prompt: Optional[str] = None,
        preset: str = "tuned",
        seconds: float = 4,
        max_width: int = 1120,
        max_height: int = 1344,
        mode: str = "anchor only",
        seed: int = -1,
        randomize: bool = True,
        input_mode: str = "single image (i2v)",
        optimize_image: bool = True,
        extra: Optional[dict] = None,
    ) -> VideoResult:
        started = time.time()
        prompt = (prompt or "").strip()
        if not prompt:
            raise ClientError("Prompt bos olamaz.")
        if not image_path or not os.path.exists(image_path):
            raise ClientError("Referans fotograf gerekli (LTX tek goruntu ile calisir).")

        self.session_hash = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
        self._log(
            "info",
            f"Oturum {self.session_hash} · {SPACE_ID} · {seconds:g} sn · {max_width}x{max_height}",
        )

        upload = prepare_upload(image_path, optimize=optimize_image)
        size_kb = len(upload.raw) / 1024
        note = f" ({upload.note})" if upload.note else ""
        self._log("info", f"Fotograf hazir: {os.path.basename(image_path)} · ~{size_kb:.0f} KB{note}")

        # Bu uretim boyunca tek proxy kullanilir; yeni uretimde havuzdan sonraki alinir.
        self.transport.begin_run()

        self._log("status", "1/3 · Fotograf yukleniyor…")
        file_data = self.upload(upload)

        # 88 parametreli /generate cagrisi
        values = {name: default for name, default in PARAMS}
        values.update(
            {
                "image_path": file_data,
                "prompt": prompt,
                "negative_prompt": DEFAULT_NEGATIVE if negative_prompt is None else negative_prompt,
                "preset": preset if preset in PRESETS else "tuned",
                "seconds": float(seconds),
                "max_width": float(max_width),
                "max_height": float(max_height),
                "mode": mode if mode in MODES else "anchor only",
                "seed": int(seed),
                "randomize_seed": bool(randomize),
                "input_mode": input_mode if input_mode in INPUT_MODES else INPUT_MODES[0],
            }
        )
        for key, value in (extra or {}).items():
            if key in INDEX:
                values[key] = value
        data = [values[name] for name, _ in PARAMS]

        self._log("status", "2/3 · Video uretiliyor… (bu adim 1-5 dk surebilir)")
        event_id = self._join(0, data, "video/join")
        stream = self._open_stream()
        try:
            completed = self._wait(stream, event_id, prompt)
        finally:
            stream.close()

        output = (completed.get("output") or {}).get("data") or []
        video = self._find_video(output)
        if not video:
            raise ClientError(f"Video ciktisi bulunamadi: {str(output)[:400]}")
        url = video.get("url")
        path = video.get("path")
        if not url:
            if not path:
                raise ClientError("Video icin URL/path yok.")
            url = BASE_URL + "/gradio_api/file=" + (path if str(path).startswith("/") else "/" + str(path))

        status = output[1] if len(output) > 1 and isinstance(output[1], str) else ""
        used_seed = output[2] if len(output) > 2 else None

        self._log("status", "3/3 · Video indiriliyor…")
        video_bytes = self.transport.download_result(
            url,
            {
                "accept": "*/*",
                "referer": BASE_URL + "/?__theme=system",
                "user-agent": DEFAULT_UA,
            },
            label="video/indir",
        )

        elapsed = time.time() - started
        self._log("ok", f"Tamamlandi · {len(video_bytes) / 1024 / 1024:.1f} MB · {elapsed:.1f} sn")
        return VideoResult(
            video_bytes=video_bytes,
            video_url=url,
            status=status,
            prompt_used=prompt,
            seed=int(used_seed) if isinstance(used_seed, (int, float)) else None,
            elapsed=elapsed,
            proxy_log=[p.label for p in self.transport.used],
        )

    def enhance_prompt(self, prompt: str, image_path: Optional[str] = None) -> str:
        """``/enhance_prompt`` (fn_index 1): prompt'u detaylandirir."""
        self.session_hash = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
        self.transport.begin_run()
        file_data = None
        if image_path and os.path.exists(image_path):
            file_data = self.upload(prepare_upload(image_path))
        data = [file_data, prompt, 80, None, None, None, None]
        event_id = self._join(1, data, "prompt/join")
        stream = self._open_stream()
        try:
            completed = self._wait(stream, event_id, prompt)
        finally:
            stream.close()
        output = (completed.get("output") or {}).get("data") or []
        text = output[0] if output and isinstance(output[0], str) else ""
        if not text:
            raise ClientError("Prompt guclendirme bos dondu.")
        return text


# --------------------------------------------------------------------------- #
#  CLI (arayuz olmadan hizli test)
# --------------------------------------------------------------------------- #


def _cli() -> int:
    import argparse

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="LTX-2.3 10Eros video istemcisi (HAR'dan reverse edildi)")
    parser.add_argument("--image", required=True, help="Referans fotograf")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--negative", default=None)
    parser.add_argument("--seconds", type=float, default=4)
    parser.add_argument("--width", type=int, default=1120)
    parser.add_argument("--height", type=int, default=1344)
    parser.add_argument("--preset", default="tuned", choices=PRESETS)
    parser.add_argument("--mode", default="anchor only", choices=MODES)
    parser.add_argument("--seed", type=int, default=-1)
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

    client = LTXVideoClient(proxy_pool=pool, on_log=lambda lv, m: print(f"{lv:6} {m}"))
    result = client.generate(
        args.image,
        args.prompt,
        negative_prompt=args.negative,
        preset=args.preset,
        seconds=args.seconds,
        max_width=args.width,
        max_height=args.height,
        mode=args.mode,
        seed=args.seed,
    )
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"ltx_{time.strftime('%Y%m%d_%H%M%S')}.mp4")
    with open(path, "wb") as fh:
        fh.write(result.video_bytes)
    print(f"Kaydedildi: {path} · {result.size_mb:.1f} MB · seed {result.seed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
