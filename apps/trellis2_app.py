"""Microsoft TRELLIS.2 — Windows arayuzu (gorselden 3D model / GLB).

Calistirma: python apps/trellis2_app.py  (veya baslat.bat -> Space listesi)
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

import clients.trellis2_client as api

APP_DIR = ROOT_DIR
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "settings_trellis2.json")
OUT_DIR = os.path.join(APP_DIR, "outputs")

BG, PANEL, CARD, CARD2, BORDER = "#0f1115", "#151820", "#1b1f28", "#242a36", "#2b3140"
FG, MUTED, ACCENT, ACCENT2 = "#e9ecf1", "#8b93a1", "#7c5cff", "#31c8ff"
OK, WARN, ERR = "#38d39f", "#ffb020", "#ff5d6c"
FONT, MONO = "Segoe UI", "Consolas"

STAGE_LABELS = (
    ("ss_", "Aşama 1 · Sparse structure"),
    ("shape_slat_", "Aşama 2 · Shape"),
    ("tex_slat_", "Aşama 3 · Material"),
)
STAGE_FIELDS = (
    ("guidance_strength", "Guidance strength"),
    ("guidance_rescale", "Guidance rescale"),
    ("sampling_steps", "Sampling steps"),
    ("rescale_t", "Rescale T"),
)


class Trellis2App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("TRELLIS.2 · Görselden 3D")
        width = min(1180, max(900, self.winfo_screenwidth() - 40))
        height = max(660, min(860, self.winfo_screenheight() - 110))
        self.geometry(f"{width}x{height}+20+10")
        self.minsize(900, 640)
        self.configure(bg=BG)
        self._set_icon()

        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self.result: Optional[api.ModelResult] = None
        self.result_path: Optional[str] = None
        self.pool: Optional[api.ProxyPool] = None
        self.proxy_file: Optional[str] = None
        self.image_path: Optional[str] = None
        self.stage_vars: dict[str, tk.StringVar] = {}
        self._stage_mode = "idle"
        self._stage_text = ""

        os.makedirs(OUT_DIR, exist_ok=True)
        self.settings = self._load_settings()
        self._init_proxy()
        self._init_style()
        self._build()
        self._set_busy(False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._pump_job = self.after(100, self._pump)

        self._append_log("info", "Hazır. Görsel seçin ve 3D ÜRET'e basın (çıktı: GLB).")
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
            d.polygon([(32, 12), (50, 22), (50, 42), (32, 52), (14, 42), (14, 22)],
                      outline=(255, 255, 255))
            d.line([(14, 22), (32, 32), (50, 22)], fill=(255, 255, 255))
            d.line([(32, 32), (32, 52)], fill=(255, 255, 255))
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
            "resolution": self.resolution_var.get(),
            "seed": self.seed_var.get(),
            "randomize": bool(self.randomize_var.get()),
            "decimation": self.decimation_var.get(),
            "texture": self.texture_var.get(),
            "stage": {k: v.get() for k, v in self.stage_vars.items()},
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
        style.configure("TNotebook", background=CARD, borderwidth=0)
        style.configure("TNotebook.Tab", background=CARD2, foreground=FG,
                        padding=(12, 5), font=(FONT, 8))
        style.map("TNotebook.Tab", background=[("selected", ACCENT)],
                  foreground=[("selected", "white")])
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
        tk.Label(title, text="TRELLIS", bg=PANEL, fg=ACCENT, font=(FONT, 22, "bold")).pack(side="left")
        tk.Label(title, text=" · 2", bg=PANEL, fg=FG, font=(FONT, 22)).pack(side="left")
        tk.Label(title, text="  ·  görselden 3D model", bg=PANEL, fg=MUTED,
                 font=(FONT, 10)).pack(side="left", pady=(8, 0))
        right = tk.Frame(header, bg=PANEL)
        right.grid(row=0, column=1, sticky="e", padx=22)
        tk.Label(right, text="microsoft / TRELLIS.2", bg=PANEL, fg=MUTED,
                 font=(FONT, 9)).pack(side="left", padx=(0, 12))
        self._btn(right, "⌂  Space seç", self._back_to_launcher, small=True).pack(side="left")

        body = tk.Frame(self, bg=BG)
        body.grid(row=1, column=0, sticky="nsew", padx=16, pady=(12, 8))
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=0, minsize=440)
        body.columnconfigure(1, weight=1)

        left = tk.Frame(body, bg=BG, width=440)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        left.grid_propagate(False)
        left.columnconfigure(0, weight=1)

        ic = tk.Frame(left, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        ic.grid(row=0, column=0, sticky="ew")
        ih = tk.Frame(ic, bg=CARD)
        ih.pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(ih, text="KAYNAK GÖRSEL", bg=CARD, fg=FG, font=(FONT, 8, "bold")).pack(side="left")
        self._btn(ih, "Seç", self._choose_image, small=True).pack(side="right")
        self._btn(ih, "Kaldır", self._clear_image, small=True).pack(side="right", padx=(0, 6))
        self.thumb = tk.Canvas(ic, bg="#0a0c10", height=150, highlightthickness=0)
        self.thumb.pack(fill="x", padx=12, pady=8)
        self.thumb.bind("<Configure>", lambda _e: self._draw_thumb())
        self.image_label = tk.Label(ic, text="Görsel seçilmedi", bg=CARD, fg=MUTED,
                                    font=(FONT, 8), anchor="w")
        self.image_label.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(ic, text="İpucu: ön planı maskelemesi (alpha) olan görseller daha iyi sonuç verir.",
                 bg=CARD, fg=MUTED, font=(FONT, 7), anchor="w", wraplength=400,
                 justify="left").pack(fill="x", padx=12, pady=(0, 10))

        opts = tk.Frame(left, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        opts.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        for c in (1, 3):
            opts.columnconfigure(c, weight=1)
        s = self.settings
        stage = s.get("stage") or {}
        for key, default in api.STAGE_DEFAULTS.items():
            self.stage_vars[key] = tk.StringVar(value=str(stage.get(key, default)))
        self.resolution_var = tk.StringVar(value=str(s.get("resolution", api.DEFAULT_RESOLUTION)))
        self.seed_var = tk.StringVar(value=str(s.get("seed", 0)))
        self.decimation_var = tk.StringVar(value=str(s.get("decimation", api.DECIMATION_DEFAULT)))
        self.texture_var = tk.StringVar(value=str(s.get("texture", api.TEXTURE_DEFAULT)))
        self.randomize_var = tk.BooleanVar(value=bool(s.get("randomize", True)))
        self.use_proxy_var = tk.BooleanVar(value=bool(s.get("use_proxy", True)) and self.pool is not None)

        def lbl(t, r, c):
            tk.Label(opts, text=t, bg=CARD, fg=MUTED, font=(FONT, 8)).grid(
                row=r, column=c, sticky="w", padx=(12, 6), pady=3)

        def ent(v, r, c):
            tk.Entry(opts, textvariable=v, bg=CARD2, fg=FG, insertbackground=FG,
                     relief="flat", highlightthickness=1, highlightbackground=BORDER,
                     font=(FONT, 9)).grid(row=r, column=c, sticky="ew", padx=(0, 10), pady=3, ipady=2)

        lbl("Resolution", 0, 0)
        ttk.Combobox(opts, textvariable=self.resolution_var, values=list(api.RESOLUTIONS),
                     state="readonly", font=(FONT, 9)).grid(
            row=0, column=1, sticky="ew", padx=(0, 10), ipady=1)
        lbl("Seed", 0, 2); ent(self.seed_var, 0, 3)
        tk.Checkbutton(opts, text="rastgele seed", variable=self.randomize_var,
                       bg=CARD, fg=FG, selectcolor=CARD2, activebackground=CARD,
                       font=(FONT, 8)).grid(row=1, column=0, columnspan=2, sticky="w", padx=12, pady=2)
        lbl("Decimation (100k-500k)", 1, 2); ent(self.decimation_var, 1, 3)
        lbl("Texture (1024-4096)", 2, 0); ent(self.texture_var, 2, 1)
        self._btn(opts, "⚙  Gelişmiş…", self._open_advanced, small=True).grid(
            row=2, column=2, columnspan=2, sticky="w", pady=2)
        tk.Checkbutton(opts, text="her üretimde farklı proxy", variable=self.use_proxy_var,
                       bg=CARD, fg=FG, selectcolor=CARD2, activebackground=CARD,
                       font=(FONT, 8)).grid(row=3, column=0, columnspan=4, sticky="w", padx=12, pady=(4, 8))

        footer = tk.Frame(left, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        footer.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.gen_btn = tk.Button(footer, text="▶   3D ÜRET", command=self._start,
                                 bg=ACCENT, fg="white", activebackground="#6a4ce0",
                                 activeforeground="white", relief="flat", bd=0,
                                 font=(FONT, 11, "bold"), cursor="hand2", pady=8)
        self.gen_btn.pack(fill="x", padx=8, pady=(8, 4))
        self.progress = ttk.Progressbar(footer, mode="indeterminate")
        self.progress.pack(fill="x", padx=8, pady=(0, 8))

        stagec = tk.Frame(body, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        stagec.grid(row=0, column=1, sticky="nsew")
        stagec.rowconfigure(1, weight=1)
        stagec.columnconfigure(0, weight=1)
        sh = tk.Frame(stagec, bg=CARD)
        sh.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 0))
        tk.Label(sh, text="3D MODEL (GLB)", bg=CARD, fg=FG, font=(FONT, 8, "bold")).pack(side="left")
        self.info_var = tk.StringVar(value="Henüz üretim yok")
        tk.Label(sh, textvariable=self.info_var, bg=CARD, fg=MUTED,
                 font=(MONO, 8)).pack(side="right")
        self.stage = tk.Canvas(stagec, bg="#0a0c10", highlightthickness=0)
        self.stage.grid(row=1, column=0, sticky="nsew", padx=12, pady=8)
        self.stage.bind("<Configure>", lambda _e: self._draw_stage())

        btns = tk.Frame(body, bg=BG)
        btns.grid(row=1, column=1, sticky="ew", pady=(10, 0))
        self.open_btn = self._btn(btns, "▶ Aç", self._open_result)
        self.open_btn.pack(side="left", padx=(0, 8))
        self.save_btn = self._btn(btns, "💾  Kaydet", self._save_result)
        self.save_btn.pack(side="left", padx=(0, 8))
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

    def _btn(self, parent, text, command, small: bool = False) -> tk.Button:
        return tk.Button(parent, text=text, command=command, bg=CARD2, fg=FG,
                         activebackground=BORDER, activeforeground=FG, relief="flat", bd=0,
                         font=(FONT, 8 if small else 9), cursor="hand2",
                         padx=8 if small else 12, pady=3 if small else 6)

    def _open_advanced(self) -> None:
        win = tk.Toplevel(self)
        win.title("Gelişmiş ayarlar · 3 aşama")
        win.configure(bg=BG)
        win.transient(self)
        win.geometry("560x300+120+120")
        win.minsize(520, 280)

        notebook = ttk.Notebook(win)
        notebook.pack(fill="both", expand=True, padx=12, pady=(12, 8))

        def field(parent, key, label, row, col):
            tk.Label(parent, text=label, bg=CARD, fg=MUTED, font=(FONT, 8)).grid(
                row=row, column=col, sticky="w", padx=(14, 8), pady=7)
            tk.Entry(parent, textvariable=self.stage_vars[key], bg=CARD2, fg=FG,
                     insertbackground=FG, relief="flat", highlightthickness=1,
                     highlightbackground=BORDER, font=(FONT, 9)).grid(
                row=row, column=col + 1, sticky="ew", padx=(0, 14), pady=7, ipady=2)

        for prefix, label in STAGE_LABELS:
            tab = tk.Frame(notebook, bg=CARD)
            tab.columnconfigure(1, weight=1)
            tab.columnconfigure(3, weight=1)
            notebook.add(tab, text=label)
            for idx, (suffix, text) in enumerate(STAGE_FIELDS):
                field(tab, prefix + suffix, text, idx // 2, (idx % 2) * 2)
            tk.Label(tab, text="Guidance 1-10 · Rescale 0-1 · Steps 1-50 · Rescale T 1-6",
                     bg=CARD, fg=MUTED, font=(FONT, 7)).grid(
                row=2, column=0, columnspan=4, sticky="w", padx=14, pady=(4, 0))

        tk.Label(win, text="Bu değerler yalnızca bir sonraki üretimde kullanılır.",
                 bg=BG, fg=MUTED, font=(FONT, 8)).pack(anchor="w", padx=14)
        self._btn(win, "Kapat", win.destroy).pack(anchor="e", padx=12, pady=(0, 10))

    def _choose_image(self) -> None:
        path = filedialog.askopenfilename(
            title="Kaynak görsel",
            filetypes=[("Görseller", "*.png *.jpg *.jpeg *.webp"), ("Tümü", "*.*")])
        if path:
            self.image_path = path
            self.image_label.configure(text=os.path.basename(path), fg=FG)
            self._draw_thumb()

    def _clear_image(self) -> None:
        self.image_path = None
        self.thumb.delete("all")
        self.image_label.configure(text="Görsel seçilmedi", fg=MUTED)

    def _draw_thumb(self) -> None:
        self.thumb.delete("all")
        if not self.image_path or not os.path.exists(self.image_path):
            return
        try:
            with Image.open(self.image_path) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                cw, ch = self.thumb.winfo_width(), self.thumb.winfo_height()
                if cw < 10 or ch < 10:
                    return
                im.thumbnail((cw - 16, ch - 16), Image.LANCZOS)
                photo = ImageTk.PhotoImage(im)
                self.thumb.create_image(cw // 2, ch // 2, image=photo)
                self._thumb_ref = photo
        except Exception:
            pass

    def _draw_stage(self) -> None:
        self.stage.delete("all")
        w, h = self.stage.winfo_width(), self.stage.winfo_height()
        if w < 20 or h < 20:
            return
        cx, cy = w // 2, h // 2
        if self._stage_mode != "result":
            self.stage.create_text(cx, cy - 14, text="3D model (GLB) burada hazırlanacak",
                                   fill=MUTED, font=(FONT, 11), justify="center")
            self.stage.create_text(cx, cy + 16, text="Görsel seç → 3D ÜRET",
                                   fill=BORDER, font=(FONT, 9))
            return
        size = min(w, h) * 0.17
        top = (cx, cy - size * 1.35)
        left = (cx - size * 1.1, cy - size * 0.6)
        right = (cx + size * 1.1, cy - size * 0.6)
        mid = (cx, cy)
        bl = (cx - size * 1.1, cy + size * 0.6)
        br = (cx + size * 1.1, cy + size * 0.6)
        bot = (cx, cy + size * 1.35)
        edges = ((top, left), (top, right), (left, mid), (right, mid),
                 (left, bl), (mid, bot), (right, br), (bl, bot), (br, bot),
                 (mid, left), (mid, right))
        for a, b in edges:
            self.stage.create_line(a, b, fill=ACCENT2, width=2)
        for pt in (top, left, right, mid, bl, br, bot):
            self.stage.create_oval(pt[0] - 2, pt[1] - 2, pt[0] + 2, pt[1] + 2,
                                   fill=ACCENT2, outline="")
        self.stage.create_text(cx, h - 46, text="GLB hazır", fill=FG,
                               font=(FONT, 12, "bold"))
        self.stage.create_text(cx, h - 24, text=self._stage_text, fill=MUTED,
                               font=(MONO, 9), justify="center")

    def _set_busy(self, busy: bool) -> None:
        if busy:
            self.gen_btn.configure(state="disabled", text="⏳   ÜRETİLİYOR…", bg="#4a3020")
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.configure(value=0)
            self.gen_btn.configure(state="normal", text="▶   3D ÜRET", bg=ACCENT)

    def _params(self) -> dict:
        stage = {}
        for key, value in self.stage_vars.items():
            lo, hi = api.STAGE_RANGES[key]
            is_int = key.endswith("_sampling_steps")
            num = int(float(value.get())) if is_int else float(value.get())
            if not (lo <= num <= hi):
                raise ValueError(f"{key}: {lo}–{hi} aralığında olmalı.")
            stage[key] = num
        return dict(
            resolution=self.resolution_var.get(),
            seed=int(self.seed_var.get()),
            randomize_seed=bool(self.randomize_var.get()),
            decimation_target=int(self.decimation_var.get()),
            texture_size=int(self.texture_var.get()),
            **stage,
        )

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.image_path or not os.path.exists(self.image_path):
            messagebox.showwarning("Görsel", "Kaynak görsel seçin.")
            return
        try:
            kw = self._params()
        except ValueError as exc:
            messagebox.showwarning("Parametre", f"Sayısal alanları kontrol edin.\n{exc}")
            return
        if kw["resolution"] not in api.RESOLUTIONS:
            messagebox.showwarning("Resolution", "512, 1024 veya 1536 seçin.")
            return
        if not (api.DECIMATION_MIN <= kw["decimation_target"] <= api.DECIMATION_MAX):
            messagebox.showwarning("Decimation", "100000–500000 aralığında olmalı.")
            return
        if not (api.TEXTURE_MIN <= kw["texture_size"] <= api.TEXTURE_MAX):
            messagebox.showwarning("Texture", "1024–4096 aralığında olmalı.")
            return
        use_proxy = bool(self.use_proxy_var.get()) and self.pool is not None
        self._save_settings()
        self._set_busy(True)
        self.open_btn.configure(state="disabled")
        self.save_btn.configure(state="disabled")
        self.info_var.set("Üretiliyor…")
        self._append_log("info", f"Üretim başlatıldı · {os.path.basename(self.image_path)} · "
                                 f"res {kw['resolution']} · seed="
                                 f"{'rastgele' if kw['randomize_seed'] else kw['seed']} · "
                                 f"decimation {kw['decimation_target']} · texture {kw['texture_size']}")
        self.worker = threading.Thread(
            target=self._thread_entry,
            args=(self.image_path, dict(kw, use_proxy=use_proxy)), daemon=True)
        self.worker.start()

    def _thread_entry(self, image_path: str, kw: dict) -> None:
        try:
            use_proxy = kw.pop("use_proxy")
            client = api.Trellis2Client(proxy_pool=self.pool if use_proxy else None,
                                        on_log=lambda lv, m: self.events.put(("log", lv, m)))
            self.events.put(("result", client.generate(image_path, **kw)))
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

    def _on_result(self, result: api.ModelResult) -> None:
        self.result = result
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(OUT_DIR, f"trellis2_{stamp}.glb")
        try:
            with open(path, "wb") as fh:
                fh.write(result.glb_bytes)
            self.result_path = path
        except OSError as exc:
            self._append_log("warn", f"GLB otomatik kaydedilemedi: {exc}")
            self.result_path = None
        self.open_btn.configure(state="normal" if self.result_path else "disabled")
        self.save_btn.configure(state="normal")
        self.info_var.set(f"{result.size_kb / 1024:.1f} MB · seed {result.seed} · {result.elapsed:.0f} sn")
        self._stage_mode = "result"
        self._stage_text = os.path.basename(path) if path else "bellekte"
        self._draw_stage()
        self._append_log("ok", f"Sonuç hazır: {os.path.basename(path) if path else 'bellekte'}")
        try:
            self.bell()
            self.lift()
        except Exception:
            pass

    def _on_error(self, message: str) -> None:
        self.info_var.set("Hata")
        self._append_log("error", message)
        messagebox.showerror("Üretim hatası", message)

    def _save_result(self) -> None:
        if not self.result:
            return
        path = filedialog.asksaveasfilename(
            title="GLB kaydet", defaultextension=".glb",
            initialfile=os.path.basename(self.result_path or "model.glb"),
            initialdir=OUT_DIR, filetypes=[("GLB model", "*.glb")])
        if not path:
            return
        try:
            with open(path, "wb") as fh:
                fh.write(self.result.glb_bytes)
            self._append_log("ok", f"Kaydedildi: {path}")
        except OSError as exc:
            messagebox.showerror("Kaydetme", str(exc))

    def _open_result(self) -> None:
        if self.result_path and os.path.exists(self.result_path):
            try:
                os.startfile(self.result_path)  # type: ignore[attr-defined]
            except OSError as exc:
                messagebox.showerror(
                    "Aç", f"GLB için varsayılan uygulama bulunamadı.\n{exc}\n\n"
                          "Dosyayı Blender veya Windows 3D Viewer ile açabilirsiniz.")

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
    Trellis2App().mainloop()


if __name__ == "__main__":
    main()
