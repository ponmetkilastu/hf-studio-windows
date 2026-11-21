"""Qwen Image Edit 2511 Rapid AIO LoRAs — Windows arayuzu (gorsel duzenleme).

Calistirma: python apps/qwen2511_app.py  (veya baslat.bat -> Space listesi)
Gereksinim: pip install requests pillow
"""

from __future__ import annotations

import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
from paths import ROOT_DIR, CONFIG_DIR, DATA_DIR, OUTPUT_DIR, SETTINGS_DIR, PROXY_FILE

import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from PIL import Image, ImageDraw, ImageOps, ImageTk

import clients.qwen2511_client as api

APP_DIR = ROOT_DIR
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "settings_qwen2511.json")
OUT_DIR = os.path.join(APP_DIR, "outputs")

BG, PANEL, CARD, CARD2, BORDER = "#0f1115", "#151820", "#1b1f28", "#242a36", "#2b3140"
FG, MUTED, ACCENT, ACCENT2 = "#e9ecf1", "#8b93a1", "#7c5cff", "#31c8ff"
OK, WARN, ERR = "#38d39f", "#ffb020", "#ff5d6c"
FONT, MONO = "Segoe UI", "Consolas"


class Qwen2511App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Qwen Image Edit 2511 · Görsel düzenleme")
        width = min(1180, max(880, self.winfo_screenwidth() - 40))
        height = max(600, min(880, self.winfo_screenheight() - 30))
        self.geometry(f"{width}x{height}+20+10")
        self.minsize(880, 580)
        self.configure(bg=BG)
        self._set_icon()

        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self.result: Optional[api.ImageResult] = None
        self.result_path: Optional[str] = None
        self.pool: Optional[api.ProxyPool] = None
        self.proxy_file: Optional[str] = None
        self.image1: Optional[str] = None
        self.image2: Optional[str] = None
        self.extras: list[str] = []

        os.makedirs(OUT_DIR, exist_ok=True)
        self.settings = self._load_settings()
        self.image1 = self.settings.get("image1") if os.path.exists(self.settings.get("image1") or "") else None
        self.image2 = self.settings.get("image2") if os.path.exists(self.settings.get("image2") or "") else None
        self.extras = [p for p in self.settings.get("extras", []) if os.path.exists(p)]
        self._init_proxy()
        self._init_style()
        self._build()
        self._set_busy(False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._pump_job = self.after(100, self._pump)

        self._append_log("info", "Hazır. Image 1 seçin, prompt yazın ve DÜZENLE'ye basın.")
        if self.proxy_file:
            self._append_log("info", f"Proxy dosyası: {os.path.basename(self.proxy_file)} · {len(self.pool)} IP")
        else:
            self._append_log("warn", "Proxy dosyası bulunamadı; doğrudan bağlantı kullanılacak.")

    def _set_icon(self) -> None:
        try:
            img = Image.new("RGB", (64, 64), (18, 20, 27))
            d = ImageDraw.Draw(img)
            for y in range(64):
                t = y / 63
                d.line([(0, y), (64, y)], fill=(int(124 + (49 - 124) * t),
                                                int(92 + (200 - 92) * t), 255))
            d.polygon([(18, 32), (30, 44), (48, 20)], fill=(255, 255, 255))
            self._icon = ImageTk.PhotoImage(img)
            self.iconphoto(True, self._icon)
        except Exception:
            pass

    def _load_settings(self) -> dict:
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    def _save_settings(self) -> None:
        data = {
            "prompt": self.prompt_text.get("1.0", "end").strip(),
            "image1": self.image1, "image2": self.image2, "extras": self.extras,
            "lora": self.lora_var.get(),
            "seed": self.seed_var.get(), "randomize": bool(self.randomize_var.get()),
            "guidance": self.guidance_var.get(), "steps": self.steps_var.get(),
            "megapixels": self.mp_var.get(), "resmultiple": self.res_var.get(),
            "refmp": self.refmp_var.get(), "decoder": self.decoder_var.get(),
            "keep2x": bool(self.keep2x_var.get()),
            "extras_cond": bool(self.extras_cond_var.get()),
            "pad": bool(self.pad_var.get()), "tiling": bool(self.tiling_var.get()),
            "protect": bool(self.protect_var.get()),
            "protect_strength": self.protect_str_var.get(),
            "use_proxy": bool(self.use_proxy_var.get()),
            "proxy_file": self.proxy_file,
        }
        try:
            with open(SETTINGS_PATH, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
        except OSError:
            pass

    def _init_proxy(self) -> None:
        self.proxy_file = self.settings.get("proxy_file") or api.ProxyPool.find_default(APP_DIR)
        if self.proxy_file and not os.path.exists(self.proxy_file):
            self.proxy_file = api.ProxyPool.find_default(APP_DIR)
        if self.proxy_file:
            try:
                self.pool = api.ProxyPool(self.proxy_file)
            except Exception as exc:
                self.pool = None
                messagebox.showwarning("Proxy", f"Proxy dosyası okunamadı:\n{exc}")

    def _init_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        self.option_add("*TCombobox*Listbox.background", CARD)
        self.option_add("*TCombobox*Listbox.foreground", FG)

    def _build(self) -> None:
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        header = tk.Frame(self, bg=PANEL, height=74)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.columnconfigure(0, weight=1)
        title = tk.Frame(header, bg=PANEL)
        title.grid(row=0, column=0, sticky="w", padx=22, pady=12)
        tk.Label(title, text="Qwen Image Edit", bg=PANEL, fg=ACCENT, font=(FONT, 21, "bold")).pack(side="left")
        tk.Label(title, text=" · 2511", bg=PANEL, fg=FG, font=(FONT, 21)).pack(side="left")
        tk.Label(title, text="  ·  referanslı düzenleme", bg=PANEL, fg=MUTED,
                 font=(FONT, 10)).pack(side="left", pady=(8, 0))
        right = tk.Frame(header, bg=PANEL)
        right.grid(row=0, column=1, sticky="e", padx=22)
        tk.Label(right, text="aet256/Qwen-Image-Edit-Rapid-AIO-Loras", bg=PANEL,
                 fg=MUTED, font=(FONT, 9)).pack(side="left", padx=(0, 12))
        self._btn(right, "⌂  Space seç", self._back_to_launcher, small=True).pack(side="left")

        body = tk.Frame(self, bg=BG)
        body.grid(row=1, column=0, sticky="nsew", padx=16, pady=(12, 8))
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=0, minsize=410)
        body.columnconfigure(1, weight=1)

        # --- Sol: kaydirilabilir ayarlar + sabit buton ---
        left_outer = tk.Frame(body, bg=BG, width=410)
        left_outer.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        left_outer.grid_propagate(False)
        self.left_canvas = tk.Canvas(left_outer, bg=BG, highlightthickness=0)
        left_scroll = ttk.Scrollbar(left_outer, orient="vertical", command=self.left_canvas.yview)
        self.left_canvas.configure(yscrollcommand=left_scroll.set)
        footer = tk.Frame(left_outer, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        footer.pack(side="bottom", fill="x", pady=(8, 0))
        left_scroll.pack(side="right", fill="y")
        self.left_canvas.pack(side="left", fill="both", expand=True)
        left = tk.Frame(self.left_canvas, bg=BG)
        self.left_canvas.create_window((0, 0), window=left, anchor="nw", width=392)
        left.bind("<Configure>", lambda _e: self.left_canvas.configure(
            scrollregion=self.left_canvas.bbox("all")))
        self.left_canvas.bind("<MouseWheel>", lambda e: self.left_canvas.yview_scroll(
            -1 if e.delta > 0 else 1, "units"))
        left.columnconfigure(0, weight=1)

        s = self.settings
        # Goreller
        ic = tk.Frame(left, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        ic.grid(row=0, column=0, sticky="ew")
        ih = tk.Frame(ic, bg=CARD)
        ih.pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(ih, text="GÖRSELLER", bg=CARD, fg=FG, font=(FONT, 8, "bold")).pack(side="left")
        self._btn(ih, "Image 2", self._choose_image2, small=True).pack(side="right", padx=(4, 0))
        self._btn(ih, "Image 1", self._choose_image1, small=True).pack(side="right")
        self.thumb = tk.Canvas(ic, bg="#0a0c10", height=64, highlightthickness=0)
        self.thumb.pack(fill="x", padx=12, pady=6)
        self.thumb.bind("<Configure>", lambda _e: self._draw_thumb())
        self.image_label = tk.Label(ic, text="Image 1 seçilmedi", bg=CARD, fg=MUTED,
                                    font=(FONT, 8), anchor="w")
        self.image_label.pack(fill="x", padx=12, pady=(0, 4))
        eh = tk.Frame(ic, bg=CARD)
        eh.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(eh, text="Ek referanslar:", bg=CARD, fg=MUTED, font=(FONT, 8)).pack(side="left")
        self._btn(eh, "+", self._add_extras, small=True).pack(side="left", padx=(4, 2))
        self._btn(eh, "−", self._remove_extra, small=True).pack(side="left")
        self.extra_label = tk.Label(ic, text="yok", bg=CARD, fg=MUTED, font=(FONT, 8), anchor="w")
        self.extra_label.pack(fill="x", padx=12, pady=(0, 8))

        # Prompt
        pc = tk.Frame(left, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        pc.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        tk.Label(pc, text="DÜZENLEME PROMPTU", bg=CARD, fg=FG, font=(FONT, 8, "bold")).pack(
            anchor="w", padx=12, pady=(10, 0))
        self.prompt_text = tk.Text(pc, height=2, wrap="word", bg="#0a0c10", fg=FG,
                                   insertbackground=FG, relief="flat", highlightthickness=1,
                                   highlightbackground=BORDER, font=(FONT, 9), padx=8, pady=6)
        self.prompt_text.pack(fill="x", padx=12, pady=(5, 10))
        self.prompt_text.insert("1.0", s.get("prompt", ""))
        self.prompt_text.bind("<Control-Return>", lambda _e: (self._start(), "break")[1])

        # Ana ayarlar
        opts = tk.Frame(left, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        opts.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        for c in (1, 3):
            opts.columnconfigure(c, weight=1)
        self.lora_var = tk.StringVar(value=s.get("lora", "None"))
        self.seed_var = tk.StringVar(value=str(s.get("seed", 0)))
        self.randomize_var = tk.BooleanVar(value=bool(s.get("randomize", True)))
        self.guidance_var = tk.StringVar(value=str(s.get("guidance", 1.0)))
        self.steps_var = tk.StringVar(value=str(s.get("steps", 4)))
        self.mp_var = tk.StringVar(value=str(s.get("megapixels", 1.0)))
        self.res_var = tk.StringVar(value=str(s.get("resmultiple", 32)))
        self.refmp_var = tk.StringVar(value=str(s.get("refmp", 0.0)))
        self.decoder_var = tk.StringVar(value=s.get("decoder", "qwen"))
        self.keep2x_var = tk.BooleanVar(value=bool(s.get("keep2x", False)))
        self.extras_cond_var = tk.BooleanVar(value=bool(s.get("extras_cond", True)))
        self.pad_var = tk.BooleanVar(value=bool(s.get("pad", True)))
        self.tiling_var = tk.BooleanVar(value=bool(s.get("tiling", False)))
        self.protect_var = tk.BooleanVar(value=bool(s.get("protect", True)))
        self.protect_str_var = tk.StringVar(value=str(s.get("protect_strength", 0.35)))
        self.use_proxy_var = tk.BooleanVar(value=bool(s.get("use_proxy", True)) and self.pool is not None)

        def lbl(t, r, c):
            tk.Label(opts, text=t, bg=CARD, fg=MUTED, font=(FONT, 8)).grid(
                row=r, column=c, sticky="w", padx=(12, 6), pady=3)

        def ent(v, r, c):
            tk.Entry(opts, textvariable=v, bg=CARD2, fg=FG, insertbackground=FG,
                     relief="flat", highlightthickness=1, highlightbackground=BORDER,
                     font=(FONT, 9)).grid(row=r, column=c, sticky="ew", padx=(0, 10), pady=3, ipady=2)

        def combo(var, r, c, values):
            ttk.Combobox(opts, textvariable=var, values=list(values), state="readonly",
                         height=14, font=(FONT, 8)).grid(row=r, column=c, sticky="ew",
                                                         padx=(0, 10), pady=3)

        lbl("Stil / LoRA", 0, 0); combo(self.lora_var, 0, 1, api.LORAS)
        lbl("Seed", 1, 0); ent(self.seed_var, 1, 1)
        tk.Checkbutton(opts, text="rastgele seed", variable=self.randomize_var,
                       bg=CARD, fg=FG, selectcolor=CARD2, activebackground=CARD,
                       font=(FONT, 8)).grid(row=1, column=2, columnspan=2, sticky="w", pady=2)
        lbl("Guidance (1-10)", 2, 0); ent(self.guidance_var, 2, 1)
        lbl("Steps (1-50)", 2, 2); ent(self.steps_var, 2, 3)
        lbl("Hedef MP (0=input)", 3, 0); ent(self.mp_var, 3, 1)
        lbl("Çözünürlük katı", 3, 2); combo(self.res_var, 3, 3, api.RESOLUTION_MULTIPLES)

        tk.Label(opts, text="GELİŞMİŞ", bg=CARD, fg=ACCENT2, font=(FONT, 8, "bold")).grid(
            row=4, column=0, columnspan=4, sticky="w", padx=12, pady=(8, 0))
        lbl("Ref VAE MP (0=canvas)", 5, 0); ent(self.refmp_var, 5, 1)
        lbl("Decoder VAE", 5, 2); combo(self.decoder_var, 5, 3, api.DECODERS)
        for i, (text, var) in enumerate([
            ("ek referanslar conditioning-only", self.extras_cond_var),
            ("görselleri canvas oranına pad'le", self.pad_var),
            ("VAE tiling (düşük VRAM)", self.tiling_var),
            ("wan2x 2× çıktıyı koru", self.keep2x_var),
        ]):
            tk.Checkbutton(opts, text=text, variable=var, bg=CARD, fg=FG,
                           selectcolor=CARD2, activebackground=CARD,
                           font=(FONT, 8)).grid(row=6 + i, column=0, columnspan=4,
                                                sticky="w", padx=12, pady=1)
        tk.Checkbutton(opts, text="parlaklık koruması", variable=self.protect_var,
                       bg=CARD, fg=FG, selectcolor=CARD2, activebackground=CARD,
                       font=(FONT, 8)).grid(row=10, column=0, columnspan=2, sticky="w", padx=12, pady=2)
        lbl("Koruma gücü (0-1)", 10, 2); ent(self.protect_str_var, 10, 3)
        tk.Checkbutton(opts, text="her üretimde farklı proxy", variable=self.use_proxy_var,
                       bg=CARD, fg=FG, selectcolor=CARD2, activebackground=CARD,
                       font=(FONT, 8)).grid(row=11, column=0, columnspan=4, sticky="w",
                                            padx=12, pady=(2, 8))

        self.gen_btn = tk.Button(footer, text="▶   DÜZENLE", command=self._start,
                                 bg=ACCENT, fg="white", activebackground="#6a4ce0",
                                 activeforeground="white", relief="flat", bd=0,
                                 font=(FONT, 11, "bold"), cursor="hand2", pady=8)
        self.gen_btn.pack(fill="x", padx=8, pady=(8, 4))
        self.progress = ttk.Progressbar(footer, mode="indeterminate")
        self.progress.pack(fill="x", padx=8, pady=(0, 8))

        # --- Sag: sonuc ---
        stage = tk.Frame(body, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        stage.grid(row=0, column=1, sticky="nsew")
        stage.rowconfigure(1, weight=1)
        stage.columnconfigure(0, weight=1)
        sh = tk.Frame(stage, bg=CARD)
        sh.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 0))
        tk.Label(sh, text="SONUÇ", bg=CARD, fg=FG, font=(FONT, 8, "bold")).pack(side="left")
        self.info_var = tk.StringVar(value="Henüz üretim yok")
        tk.Label(sh, textvariable=self.info_var, bg=CARD, fg=MUTED, font=(MONO, 8)).pack(side="right")
        self.stage = tk.Label(stage, text="Sonuç görseli burada görünecek",
                              bg="#0a0c10", fg=MUTED, font=(FONT, 10), justify="center")
        self.stage.grid(row=1, column=0, sticky="nsew", padx=12, pady=8)
        btns = tk.Frame(body, bg=BG)
        btns.grid(row=1, column=1, sticky="ew", pady=(10, 0))
        self.save_btn = self._btn(btns, "💾  Kaydet", self._save_result)
        self.save_btn.pack(side="left", padx=(0, 8))
        self.open_btn = self._btn(btns, "Aç", self._open_result)
        self.open_btn.pack(side="left", padx=(0, 8))
        self._btn(btns, "Klasör", self._open_folder).pack(side="left")

        logc = tk.Frame(body, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        logc.grid(row=2, column=1, sticky="ew", pady=(10, 0))
        tk.Label(logc, text="GÜNLÜK", bg=CARD, fg=FG, font=(FONT, 8, "bold")).pack(
            anchor="w", padx=12, pady=(8, 2))
        self.log_text = tk.Text(logc, height=7, wrap="word", bg="#0a0c10", fg=FG,
                                relief="flat", highlightthickness=0, font=(MONO, 8), padx=8, pady=6)
        self.log_text.pack(fill="x", padx=8, pady=(0, 8))
        for tag, color in (("time", MUTED), ("info", FG), ("status", ACCENT2),
                           ("ok", OK), ("warn", WARN), ("error", ERR)):
            self.log_text.tag_configure(tag, foreground=color)

        self._render_images()
        self._render_result()

    def _btn(self, parent, text, command, small: bool = False) -> tk.Button:
        return tk.Button(parent, text=text, command=command, bg=CARD2, fg=FG,
                         activebackground=BORDER, activeforeground=FG, relief="flat", bd=0,
                         font=(FONT, 8 if small else 9), cursor="hand2",
                         padx=8 if small else 12, pady=3 if small else 6)

    # ---------------- gorseller ----------------
    def _choose_image1(self) -> None:
        p = filedialog.askopenfilename(title="Image 1 (base/target)",
                                       filetypes=[("Görseller", "*.png *.jpg *.jpeg *.webp"), ("Tümü", "*.*")])
        if p:
            self.image1 = p
            self._render_images()

    def _choose_image2(self) -> None:
        p = filedialog.askopenfilename(title="Image 2 (reference)",
                                       filetypes=[("Görseller", "*.png *.jpg *.jpeg *.webp"), ("Tümü", "*.*")])
        if p:
            self.image2 = p
            self._render_images()

    def _add_extras(self) -> None:
        paths = filedialog.askopenfilenames(title="Ek referanslar",
                                            filetypes=[("Görseller", "*.png *.jpg *.jpeg *.webp"), ("Tümü", "*.*")])
        for p in paths:
            if p not in self.extras:
                self.extras.append(p)
        self._render_images()

    def _remove_extra(self) -> None:
        if self.extras:
            self.extras.pop()
            self._render_images()

    def _render_images(self) -> None:
        self.image_label.configure(
            text=os.path.basename(self.image1) if self.image1 else "Image 1 seçilmedi",
            fg=FG if self.image1 else MUTED)
        parts = []
        if self.image2:
            parts.append("Image2:" + os.path.basename(self.image2)[:22])
        if self.extras:
            parts.append(f"Ek:{len(self.extras)}")
        self.extra_label.configure(text=" · ".join(parts) if parts else "yok")
        self._draw_thumb()

    def _draw_thumb(self) -> None:
        self.thumb.delete("all")
        if not self.image1 or not os.path.exists(self.image1):
            return
        try:
            with Image.open(self.image1) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                cw, ch = self.thumb.winfo_width(), self.thumb.winfo_height()
                if cw < 10 or ch < 10:
                    return
                im.thumbnail((cw - 16, ch - 8), Image.LANCZOS)
                photo = ImageTk.PhotoImage(im)
                self.thumb.create_image(cw // 2, ch // 2, image=photo)
                self._thumb_ref = photo
        except Exception:
            pass

    def _render_result(self) -> None:
        self.stage.configure(image="")
        self._result_photo = None
        if not self.result:
            self.stage.configure(text="Sonuç görseli burada görünecek")
            return
        try:
            import io
            with Image.open(io.BytesIO(self.result.image_bytes)) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                cw, ch = self.stage.winfo_width() - 24, self.stage.winfo_height() - 24
                if cw < 40 or ch < 40:
                    cw, ch = 700, 500
                im.thumbnail((cw, ch), Image.LANCZOS)
                self._result_photo = ImageTk.PhotoImage(im)
                self.stage.configure(image=self._result_photo, text="")
        except Exception as exc:
            self.stage.configure(text=f"Önizleme alınamadı: {exc}")

    def _set_busy(self, busy: bool) -> None:
        if busy:
            self.gen_btn.configure(state="disabled", text="⏳   DÜZENLENİYOR…", bg="#4a3020")
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.configure(value=0)
            self.gen_btn.configure(state="normal", text="▶   DÜZENLE", bg=ACCENT)

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.image1 or not os.path.exists(self.image1):
            messagebox.showwarning("Görsel", "Image 1 seçin.")
            return
        if not self.prompt_text.get("1.0", "end").strip():
            messagebox.showwarning("Prompt", "Düzenleme promptu yazın.")
            return
        try:
            kw = dict(
                image_path=self.image1,
                prompt=self.prompt_text.get("1.0", "end").strip(),
                image2_path=self.image2,
                extra_paths=list(self.extras),
                lora=self.lora_var.get(),
                seed=int(self.seed_var.get()),
                randomize_seed=bool(self.randomize_var.get()),
                guidance_scale=float(self.guidance_var.get()),
                steps=int(self.steps_var.get()),
                target_megapixels=float(self.mp_var.get()),
                resolution_multiple=int(self.res_var.get()),
                vae_ref_megapixels=float(self.refmp_var.get()),
                decoder_vae=self.decoder_var.get(),
                keep_decoder_2x=bool(self.keep2x_var.get()),
                extras_condition_only=bool(self.extras_cond_var.get()),
                pad_to_canvas=bool(self.pad_var.get()),
                vae_tiling=bool(self.tiling_var.get()),
                highlight_protection=bool(self.protect_var.get()),
                highlight_protection_strength=float(self.protect_str_var.get()),
            )
        except ValueError:
            messagebox.showwarning("Parametre", "Sayısal alanları kontrol edin.")
            return
        use_proxy = bool(self.use_proxy_var.get()) and self.pool is not None
        self._save_settings()
        self._set_busy(True)
        self.save_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self._append_log("info", f"Üretim başlatıldı · {kw['lora']} · {kw['steps']} step · "
                                 f"seed={'rastgele' if kw['randomize_seed'] else kw['seed']}")
        self.worker = threading.Thread(target=self._thread_entry,
                                       args=(dict(kw, use_proxy=use_proxy),), daemon=True)
        self.worker.start()

    def _thread_entry(self, kw: dict) -> None:
        try:
            use_proxy = kw.pop("use_proxy")
            client = api.Qwen2511Client(proxy_pool=self.pool if use_proxy else None,
                                        on_log=lambda lv, m: self.events.put(("log", lv, m)))
            self.events.put(("result", client.generate(**kw)))
        except Exception as exc:
            self.events.put(("error", str(exc)))
        finally:
            self.events.put(("done", None))

    def _pump(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "log":
                    self._append_log(event[1], event[2])
                elif kind == "result":
                    self._on_result(event[1])
                elif kind == "error":
                    self._on_error(event[1])
                elif kind == "done":
                    self._set_busy(False)
        except queue.Empty:
            pass
        try:
            self._pump_job = self.after(100, self._pump)
        except tk.TclError:
            pass

    def _on_result(self, result: api.ImageResult) -> None:
        self.result = result
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(OUT_DIR, f"qwen2511_{stamp}.png")
        try:
            with open(path, "wb") as fh:
                fh.write(result.image_bytes)
            self.result_path = path
        except OSError as exc:
            self._append_log("warn", f"Görsel otomatik kaydedilemedi: {exc}")
            self.result_path = None
        self.save_btn.configure(state="normal")
        self.open_btn.configure(state="normal" if self.result_path else "disabled")
        self.info_var.set(f"{result.size_kb / 1024:.1f} MB · seed {result.seed} · {result.elapsed:.0f} sn")
        self._render_result()
        self._append_log("ok", f"Sonuç hazır: {os.path.basename(path) if path else 'bellekte'}")
        try:
            self.bell()
            self.lift()
        except Exception:
            pass

    def _on_error(self, message: str) -> None:
        self._append_log("error", message)
        messagebox.showerror("Üretim hatası", message)

    def _save_result(self) -> None:
        if not self.result:
            return
        path = filedialog.asksaveasfilename(
            title="PNG kaydet", defaultextension=".png",
            initialfile=os.path.basename(self.result_path or "image.png"),
            initialdir=OUT_DIR, filetypes=[("PNG görsel", "*.png")])
        if not path:
            return
        try:
            with open(path, "wb") as fh:
                fh.write(self.result.image_bytes)
            self._append_log("ok", f"Kaydedildi: {path}")
        except OSError as exc:
            messagebox.showerror("Kaydetme", str(exc))

    def _open_result(self) -> None:
        if self.result_path and os.path.exists(self.result_path):
            try:
                os.startfile(self.result_path)  # type: ignore[attr-defined]
            except OSError as exc:
                messagebox.showerror("Aç", str(exc))

    def _open_folder(self) -> None:
        try:
            os.startfile(OUT_DIR)  # type: ignore[attr-defined]
        except OSError:
            pass

    def _back_to_launcher(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno("Space seç", "Üretim sürüyor. Yine de menüye dönmek istiyor musunuz?"):
                return
        self._save_settings()
        if not os.environ.get("HF_STUDIO_LAUNCHER_ACTIVE"):
            try:
                subprocess.Popen([sys.executable, os.path.join(APP_DIR, "apps", "launcher.py")])
            except OSError:
                pass
        try:
            self.after_cancel(self._pump_job)
        except (tk.TclError, AttributeError):
            pass
        self.destroy()

    def _append_log(self, level: str, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{stamp} ", "time")
        self.log_text.insert("end", f"{message}\n", level)
        if int(self.log_text.index("end-1c").split(".")[0]) > 600:
            self.log_text.delete("1.0", "120.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno("Çıkış", "Üretim sürüyor. Yine de çıkmak istiyor musunuz?"):
                return
        self._save_settings()
        try:
            self.after_cancel(self._pump_job)
        except (tk.TclError, AttributeError):
            pass
        self.destroy()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    Qwen2511App().mainloop()


if __name__ == "__main__":
    main()
