"""Yerel HF Image/Video API — FastAPI.

Agent'larin kullandigi sabit URL: http://127.0.0.1:8787
Butun uretimler mevcut Python istemcileri uzerinden gider; proxy rotasyonu
(ProxyPool / FIFO / SQLite) ve "x-zerogpu yok, HF token yok" kurallari korunur.

Baslatma:
    python core/local_api.py   (veya api_baslat.bat)
"""


from __future__ import annotations

import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
from paths import ROOT_DIR, CONFIG_DIR, DATA_DIR, OUTPUT_DIR, SETTINGS_DIR, PROXY_FILE


import os
import shutil
import sys
import tempfile
from typing import Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware

import clients.hf_image_client as hf_mod
import clients.krea_client as krea_mod
import clients.ltx_video_client as ltx_mod
import clients.minimax_video_client as mmv_mod
import clients.ph3_client as ph3_mod
import clients.qwen_client as qwen_mod
import clients.zimage_client as zimage_mod
import clients.ltx09_client as ltx09_mod
import clients.kokoro_client as kokoro_mod

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

APP_DIR = ROOT_DIR
HOST = "127.0.0.1"
PORT = 8787

app = FastAPI(title="HF Image/Video API", version="1.0")

# Tarayici / web tabanli ajanlardan cross-origin isteklere izin ver.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Tek proxy havuzu — tum client'lar aynisini kullanir (FIFO sirasi bozulmaz).
_proxy_pool = hf_mod.ProxyPool.find_default(APP_DIR)
POOL = hf_mod.ProxyPool(_proxy_pool) if _proxy_pool else None
print(f"[api] proxy havuzu: {len(POOL) if POOL else 0} IP")


def _log(level: str, msg: str) -> None:
    print(f"[{level}] {msg}", flush=True)


def _save_uploads(files: list[UploadFile]) -> list[str]:
    """UploadFile'lari gecici dosyalara yazar ve yollarini dondurur."""
    paths = []
    for f in files:
        # FastAPI, gonderilmeyen Optional[UploadFile] alanlarini None verir.
        if f is None or not f.filename:
            continue
        suffix = os.path.splitext(f.filename)[1] or ".png"
        fd, path = tempfile.mkstemp(suffix=suffix, dir=tempfile.gettempdir())
        os.close(fd)
        with open(path, "wb") as out:
            shutil.copyfileobj(f.file, out)
        paths.append(path)
    return paths


def _cleanup(paths: list[str]) -> None:
    for p in paths:
        try:
            if os.path.exists(p):
                os.remove(p)
        except OSError:
            pass


def _binary(data: bytes, media: str, name: str) -> Response:
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": f'inline; filename="{name}"'})


@app.get("/")
def root():
    return {
        "ok": True,
        "name": "hf-local-api",
        "base_url": f"http://{HOST}:{PORT}",
        "endpoints": [
            "/ph3/text2image", "/ph3/img2img",
            "/krea/text2image", "/krea/img2img",
            "/qwen/text2image", "/qwen/img2img",
            "/minimax-video/i2v", "/ltx/i2v",
            "/minimax-image/text2image", "/zimage/text2image",
            "/ltx09/i2v", "/kokoro/tts",
        ],
    }


# ---------------------------------------------------------------------------
# ph3
# ---------------------------------------------------------------------------

@app.post("/ph3/text2image")
async def ph3_text2image(
    prompt: str = Form(...),
    aspect: str = Form("4:3"),
    resolution: str = Form("8 MP"),
    upsample: bool = Form(True),
    seed: int = Form(42),
    randomize: bool = Form(True),
):
    tmp: list[str] = []
    try:
        c = ph3_mod.PH3Client(proxy_pool=POOL, on_log=_log)
        r = c.generate(prompt, aspect=aspect, resolution=resolution,
                       upsample=upsample, seed=seed, randomize=randomize)
        return _binary(r.image_bytes, "image/jpeg", "ph3.jpg")
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    finally:
        _cleanup(tmp)


@app.post("/ph3/img2img")
async def ph3_img2img(
    image: UploadFile = File(...),
    instruction: str = Form(...),
    resolution: str = Form("8 MP"),
    upsample: bool = Form(True),
    seed: int = Form(42),
    randomize: bool = Form(True),
    ref2: Optional[UploadFile] = File(None),
    ref3: Optional[UploadFile] = File(None),
    ref4: Optional[UploadFile] = File(None),
    ref5: Optional[UploadFile] = File(None),
    ref6: Optional[UploadFile] = File(None),
    ref7: Optional[UploadFile] = File(None),
    ref8: Optional[UploadFile] = File(None),
):
    tmp: list[str] = []
    try:
        tmps = _save_uploads([image, ref2, ref3, ref4, ref5, ref6, ref7, ref8])
        tmp = tmps
        c = ph3_mod.PH3Client(proxy_pool=POOL, on_log=_log)
        r = c.edit(tmps[0], instruction, ref_paths=tmps[1:],
                   resolution=resolution, upsample=upsample,
                   seed=seed, randomize=randomize)
        return _binary(r.image_bytes, "image/jpeg", "ph3.jpg")
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    finally:
        _cleanup(tmp)


# ---------------------------------------------------------------------------
# krea
# ---------------------------------------------------------------------------

@app.post("/krea/text2image")
async def krea_text2image(
    prompt: str = Form(...),
    width: int = Form(1024), height: int = Form(1024),
    megapixels: float = Form(1.4), grounding: int = Form(768),
    steps: int = Form(8), cfg: float = Form(1.0),
    sampler: str = Form("euler"), scheduler: str = Form("beta"),
    seed: int = Form(2), randomize: bool = Form(False),
):
    try:
        c = krea_mod.KreaClient(proxy_pool=POOL, on_log=_log)
        r = c.generate(None, prompt=prompt, mode="text2image",
                       width=width, height=height, megapixels=megapixels,
                       grounding=grounding, steps=steps, cfg=cfg,
                       sampler=sampler, scheduler=scheduler,
                       seed=seed, randomize=randomize)
        return _binary(r.image_bytes, "image/png", "krea.png")
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/krea/img2img")
async def krea_img2img(
    image: UploadFile = File(...),
    prompt: str = Form(...),
    edit_instruction: str = Form(""),
    width: int = Form(1024), height: int = Form(1024),
    steps: int = Form(8), cfg: float = Form(1.0),
    seed: int = Form(2), randomize: bool = Form(False),
):
    tmp: list[str] = []
    try:
        tmps = _save_uploads([image])
        tmp = tmps
        c = krea_mod.KreaClient(proxy_pool=POOL, on_log=_log)
        r = c.generate(tmps[0], prompt=prompt, mode="edit",
                       edit_instruction=edit_instruction,
                       width=width, height=height, steps=steps, cfg=cfg,
                       seed=seed, randomize=randomize)
        return _binary(r.image_bytes, "image/png", "krea.png")
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    finally:
        _cleanup(tmp)


# ---------------------------------------------------------------------------
# qwen
# ---------------------------------------------------------------------------

@app.post("/qwen/text2image")
async def qwen_text2image(
    prompt: str = Form(...),
    aspect: str = Form("Auto"), resolution: int = Form(1024),
    enhance: bool = Form(False), seed: int = Form(0),
    randomize: bool = Form(True),
):
    try:
        c = qwen_mod.QwenClient(proxy_pool=POOL, on_log=_log)
        r = c.generate(prompt, aspect_ratio=aspect, resolution=resolution,
                       enhance=enhance, seed=seed, randomize_seed=randomize)
        return _binary(r.image_bytes, "image/png", "qwen.png")
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/qwen/img2img")
async def qwen_img2img(
    prompt: str = Form(...),
    image: Optional[UploadFile] = File(None),
    ref1: Optional[UploadFile] = File(None),
    ref2: Optional[UploadFile] = File(None),
    ref3: Optional[UploadFile] = File(None),
    ref4: Optional[UploadFile] = File(None),
    ref5: Optional[UploadFile] = File(None),
    ref6: Optional[UploadFile] = File(None),
    ref7: Optional[UploadFile] = File(None),
    ref8: Optional[UploadFile] = File(None),
    ref9: Optional[UploadFile] = File(None),
    ref10: Optional[UploadFile] = File(None),
    aspect: str = Form("Auto"), resolution: int = Form(1024),
    enhance: bool = Form(False), seed: int = Form(0),
    randomize: bool = Form(True),
):
    tmp: list[str] = []
    try:
        tmps = _save_uploads([image, ref1, ref2, ref3, ref4, ref5,
                              ref6, ref7, ref8, ref9, ref10])
        tmp = tmps
        if not tmps:
            return JSONResponse({"ok": False, "error": "En az bir görsel gerekli."}, status_code=400)
        c = qwen_mod.QwenClient(proxy_pool=POOL, on_log=_log)
        r = c.generate(prompt, image_paths=tmps, aspect_ratio=aspect,
                       resolution=resolution, enhance=enhance,
                       seed=seed, randomize_seed=randomize)
        return _binary(r.image_bytes, "image/png", "qwen.png")
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    finally:
        _cleanup(tmp)


# ---------------------------------------------------------------------------
# minimax-video
# ---------------------------------------------------------------------------

@app.post("/minimax-video/i2v")
async def minimax_video_i2v(
    image: UploadFile = File(...),
    prompt: str = Form(...),
    canvas: Optional[str] = Form(None),
    duration: float = Form(5), steps: int = Form(25),
    seed: int = Form(2), randomize: bool = Form(False),
    upsample: bool = Form(False), turbo: bool = Form(False),
    fit_frame: bool = Form(False),
):
    tmp: list[str] = []
    try:
        tmps = _save_uploads([image])
        tmp = tmps
        c = mmv_mod.MiniMaxVideoClient(proxy_pool=POOL, on_log=_log)
        r = c.generate(tmps[0], prompt, canvas=canvas,
                       auto_canvas=canvas is None, fit_frame=fit_frame,
                       duration=duration, steps=steps, seed=seed,
                       randomize=randomize, upsample=upsample, turbo=turbo)
        return _binary(r.video_bytes, "video/mp4", "video.mp4")
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    finally:
        _cleanup(tmp)


# ---------------------------------------------------------------------------
# ltx
# ---------------------------------------------------------------------------

@app.post("/ltx/i2v")
async def ltx_i2v(
    image: UploadFile = File(...),
    prompt: str = Form(...),
    negative_prompt: Optional[str] = Form(None),
    preset: str = Form("tuned"), seconds: float = Form(4),
    max_width: int = Form(1120), max_height: int = Form(1344),
    mode: str = Form("anchor only"), seed: int = Form(-1),
    randomize: bool = Form(True),
):
    tmp: list[str] = []
    try:
        tmps = _save_uploads([image])
        tmp = tmps
        c = ltx_mod.LTXVideoClient(proxy_pool=POOL, on_log=_log)
        r = c.generate(tmps[0], prompt, negative_prompt=negative_prompt,
                       preset=preset, seconds=seconds,
                       max_width=max_width, max_height=max_height,
                       mode=mode, seed=seed, randomize=randomize)
        return _binary(r.video_bytes, "video/mp4", "ltx.mp4")
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    finally:
        _cleanup(tmp)


# ---------------------------------------------------------------------------
# minimax-image
# ---------------------------------------------------------------------------

@app.post("/minimax-image/text2image")
async def minimax_image_text2image(
    prompt: str = Form(...),
    aspect: str = Form("auto"), resolution: str = Form("4 MP"),
    enhance: bool = Form(False), seed: int = Form(0),
    randomize: bool = Form(True),
):
    try:
        c = hf_mod.MiniMaxH3Client(proxy_pool=POOL, on_log=_log)
        r = c.generate([], prompt, aspect=aspect, resolution=resolution,
                       enhance=enhance, seed=seed, randomize=randomize)
        return _binary(r.image_bytes, "image/png", "minimax.png")
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# zimage
# ---------------------------------------------------------------------------

@app.post("/zimage/text2image")
async def zimage_text2image(
    prompt: str = Form(...),
    width: int = Form(1024), height: int = Form(1024),
    steps: int = Form(9), seed: int = Form(42),
    randomize: bool = Form(True),
):
    try:
        c = zimage_mod.ZImageClient(proxy_pool=POOL, on_log=_log)
        r = c.generate(prompt, width=width, height=height,
                       steps=steps, seed=seed, randomize_seed=randomize)
        return _binary(r.image_bytes, "image/png", "zimage.png")
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/ltx09/i2v")
async def ltx09_i2v(
    image: UploadFile = File(...),
    prompt: str = Form("The creature from the image starts to move"),
    negative_prompt: str = Form("worst quality, inconsistent motion, blurry, jittery, distorted"),
    width: int = Form(704), height: int = Form(512),
    duration: float = Form(2), frames: int = Form(9),
    seed: int = Form(42), randomize: bool = Form(True),
    guidance: float = Form(1), improve_texture: bool = Form(True),
):
    tmp: list[str] = []
    try:
        tmp = _save_uploads([image])
        c = ltx09_mod.LTX09Client(proxy_pool=POOL, on_log=_log)
        r = c.generate(tmp[0], prompt, negative_prompt,
                       width=width, height=height, duration=duration,
                       frames=frames, seed=seed, randomize_seed=randomize,
                       guidance=guidance, improve_texture=improve_texture)
        return _binary(r.video_bytes, "video/mp4", "ltx09.mp4")
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    finally:
        _cleanup(tmp)


@app.post("/kokoro/tts")
async def kokoro_tts(
    text: str = Form(...),
    voice: str = Form(kokoro_mod.DEFAULT_VOICE),
    speed: float = Form(1.0),
    hardware: bool = Form(True),
):
    try:
        c = kokoro_mod.KokoroClient(proxy_pool=POOL, on_log=_log)
        r = c.generate(text, voice=voice, speed=speed, hardware=hardware)
        return _binary(r.audio_bytes, "audio/wav", "kokoro.wav")
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
