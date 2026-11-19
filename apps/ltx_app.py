"""LTX-2.3 10Eros — Windows masaustu arayuzu (fotograftan video).

Calistirma:
    python ltx_app.py          (veya baslat.bat -> Space listesi)

Gereksinimler:
    pip install requests pillow

Tek bir fotograf + prompt ile video uretir. Her uretim tek bir proxy IP'si
uzerinden gonderilir; yeni uretimde listeden farkli bir IP alinir.
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
import random
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from PIL import Image, ImageDraw, ImageTk

import clients.ltx_video_client as api

APP_DIR = ROOT_DIR
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "settings_ltx.json")
OUTPUT_DIR = os.path.join(APP_DIR, "outputs")

# -- renkler (hf_image_app ile ayni palet) --------------------------------- #
BG = "#0f1115"
PANEL = "#151820"
CARD = "#1b1f28"
CARD2 = "#242a36"
BORDER = "#2b3140"
FG = "#e9ecf1"
MUTED = "#8b93a1"
ACCENT = "#7c5cff"
ACCENT2 = "#31c8ff"
OK = "#38d39f"
WARN = "#ffb020"
ERR = "#ff5d6c"
PROXY = "#6fb8ff"

FONT = "Segoe UI"
MONO = "Consolas"

SIZES = ["768x768", "896x1152", "1120x1344", "1280x960", "1344x1120", "1152x896"]


class LtXApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("LTX-2.3 10Eros · Video Studio")
        self.geometry("1240x820+24+12")
        self.minsize(1080, 740)
        self.configure(bg=BG)
        self._set_icon()

        self.photo_path: Optional[str] = None
        self._thumb_ref = None
        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self.result: Optional[api.VideoResult] = None
        self.result_path: Optional[str] = None
        self.pool: Optional[api.ProxyPool] = None
        self.proxy_file: Optional[str] = None

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        self.settings = self._load_settings()
        self._init_proxy()
        self._init_style()
        self._build()
        self._set_busy(False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._pump_job = self.after(100, self._pump)

        self._append_log("info", "Hazır. Bir fotoğraf seçin, prompt yazın ve ÜRET'e basın.")
        if self.proxy_file:
            self._append_log("info", f"Proxy dosyası: {os.path.basename(self.proxy_file)} · {len(self.pool)} IP")
        else:
            self._append_log("warn", "Proxy dosyası bulunamadı; doğrudan bağlantı kullanılacak.")

    # ------------------------------------------------------------------ #
    #  Kurulum
    # ------------------------------------------------------------------ #

    def _set_icon(self) -> None:
        try:
            img = Image.new("RGB", (64, 64), (18, 20, 27))
            draw = ImageDraw.Draw(img)
            for y in range(64):
                t = y / 63
                color = (
                    int(124 * (1 - t) + 49 * t),
                    int(92 * (1 - t) + 200 * t),
                    int(255 * (1 - t) + 255 * t),
                )
                draw.line([(0, y), (64, y)], fill=color)
            draw.polygon([(24, 18), (46, 32), (24, 46)], fill=(255, 255, 255))
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
            "preset": self.preset_var.get(),
            "mode": self.mode_var.get(),
            "seconds": self.seconds_var.get(),
            "size": self.size_var.get(),
            "seed": self.seed_var.get(),
            "randomize": bool(self.randomize_var.get()),
            "optimize": bool(self.optimize_var.get()),
            "use_proxy": bool(self.use_proxy_var.get()),
            "negative": self.negative_text.get("1.0", "end").strip(),
            "proxy_file": self.proxy_file,
        }
        try:
            with open(SETTINGS_PATH, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
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
        style.configure(
            "TCombobox",
            fieldbackground=CARD,
            background=CARD2,
            foreground=FG,
            arrowcolor=MUTED,
            bordercolor=BORDER,
            lightcolor=CARD,
            darkcolor=CARD,
        )
        style.map("TCombobox", fieldbackground=[("readonly", CARD)], foreground=[("readonly", FG)])
        style.configure(
            "TProgressbar",
            troughcolor=CARD,
            background=ACCENT,
            bordercolor=CARD,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
        )
        style.configure("TScrollbar", background=CARD2, troughcolor=BG, bordercolor=BG, arrowcolor=MUTED)

    # ------------------------------------------------------------------ #
    #  Arayuz
    # ------------------------------------------------------------------ #

    def _build(self) -> None:
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        header = tk.Frame(self, bg=PANEL, height=74)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.columnconfigure(0, weight=1)

        title = tk.Frame(header, bg=PANEL)
        title.grid(row=0, column=0, sticky="w", padx=22, pady=12)
        tk.Label(title, text="LTX", bg=PANEL, fg=ACCENT2, font=(FONT, 22, "bold")).pack(side="left")
        tk.Label(title, text=" 2.3", bg=PANEL, fg=FG, font=(FONT, 22)).pack(side="left")
        tk.Label(
            title,
            text="  ·  fotoğraftan video (10Eros)",
            bg=PANEL,
            fg=MUTED,
            font=(FONT, 10),
        ).pack(side="left", pady=(8, 0))

        right = tk.Frame(header, bg=PANEL)
        right.grid(row=0, column=1, sticky="e", padx=22)
        tk.Label(right, text="rdata92 / LTX-2.3-10Eros", bg=PANEL, fg=MUTED, font=(FONT, 9)).pack(
            side="left", padx=(0, 12)
        )
        self._btn(right, "⌂  Space seç", self._back_to_launcher, small=True).pack(side="left")

        bar = tk.Canvas(self, height=3, bg=BG, highlightthickness=0)
        bar.grid(row=0, column=0, sticky="sew")
        self._gradient_bar = bar
        bar.bind("<Configure>", self._draw_gradient)

        body = tk.Frame(self, bg=BG)
        body.grid(row=1, column=0, sticky="nsew", padx=16, pady=(12, 8))
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=0, minsize=452)
        body.columnconfigure(1, weight=1)

        left = tk.Frame(body, bg=BG, width=452)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        left.grid_propagate(False)
        self._build_left(left)

        right_panel = tk.Frame(body, bg=BG)
        right_panel.grid(row=0, column=1, sticky="nsew")
        right_panel.rowconfigure(0, weight=1)
        right_panel.columnconfigure(0, weight=1)
        self._build_right(right_panel)

        status = tk.Frame(self, bg=PANEL, height=30)
        status.grid(row=2, column=0, sticky="ew")
        status.grid_propagate(False)
        status.columnconfigure(0, weight=1)
        self.status_var = tk.StringVar(value="Hazır")
        tk.Label(status, textvariable=self.status_var, bg=PANEL, fg=MUTED, font=(FONT, 9), anchor="w").grid(
            row=0, column=0, sticky="w", padx=18, pady=6
        )
        proxy_text = f"{len(self.pool)} proxy · her üretimde farklı IP" if self.pool else "proxy kapalı"
        tk.Label(status, text=proxy_text, bg=PANEL, fg=MUTED, font=(FONT, 9)).grid(
            row=0, column=1, sticky="e", padx=18
        )

    def _draw_gradient(self, _event=None) -> None:
        canvas = self._gradient_bar
        canvas.delete("all")
        width = max(canvas.winfo_width(), 1)
        for x in range(0, width, 3):
            t = x / max(width - 1, 1)
            color = (
                int(124 + (49 - 124) * t),
                int(92 + (200 - 92) * t),
                255,
            )
            canvas.create_line(
                x, 1, x + 3, 1, fill=f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}", width=3
            )

    # -- sol panel -------------------------------------------------------- #

    def _build_left(self, parent: tk.Frame) -> None:
        photo_card = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        photo_card.pack(fill="x")
        head = tk.Frame(photo_card, bg=CARD)
        head.pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(head, text="FOTOĞRAF", bg=CARD, fg=FG, font=(FONT, 8, "bold")).pack(side="left")
        self._btn(head, "Seç", self._pick_photo, small=True).pack(side="right")
        self.clear_btn = self._btn(head, "Kaldır", self._clear_photo, small=True)
        self.clear_btn.pack(side="right", padx=(0, 6))

        self.thumb = tk.Canvas(photo_card, bg="#0a0c10", height=150, highlightthickness=0)
        self.thumb.pack(fill="x", padx=12, pady=(8, 10))
        self.thumb.bind("<Configure>", lambda _e: self._draw_thumb())
        self.photo_label = tk.Label(
            photo_card, text="Henüz fotoğraf yok", bg=CARD, fg=MUTED, font=(FONT, 9)
        )
        self.photo_label.pack(anchor="w", padx=12, pady=(0, 10))

        prompt_card = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        prompt_card.pack(fill="x", pady=(10, 0))
        tk.Label(prompt_card, text="PROMPT", bg=CARD, fg=FG, font=(FONT, 8, "bold")).pack(
            anchor="w", padx=12, pady=(10, 0)
        )
        self.prompt_text = tk.Text(
            prompt_card,
            height=3,
            wrap="word",
            bg="#0a0c10",
            fg=FG,
            insertbackground=FG,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            font=(FONT, 10),
            padx=8,
            pady=6,
        )
        self.prompt_text.pack(fill="x", padx=12, pady=(5, 0))
        self.prompt_text.insert("1.0", self.settings.get("prompt", "animate this photo"))
        self.prompt_text.bind("<Control-Return>", lambda _e: (self._start_generate(), "break")[1])

        tk.Label(prompt_card, text="NEGATİF PROMPT", bg=CARD, fg=MUTED, font=(FONT, 8, "bold")).pack(
            anchor="w", padx=12, pady=(8, 0)
        )
        self.negative_text = tk.Text(
            prompt_card,
            height=2,
            wrap="word",
            bg="#0a0c10",
            fg=MUTED,
            insertbackground=FG,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            font=(FONT, 8),
            padx=8,
            pady=5,
        )
        self.negative_text.pack(fill="x", padx=12, pady=(5, 12))
        self.negative_text.insert("1.0", self.settings.get("negative", api.DEFAULT_NEGATIVE))

        opts = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        opts.pack(fill="x", pady=(10, 0))
        opts.columnconfigure(1, weight=1)
        opts.columnconfigure(3, weight=1)

        def row_label(text, r, c):
            tk.Label(opts, text=text, bg=CARD, fg=MUTED, font=(FONT, 8)).grid(
                row=r, column=c, sticky="w", padx=(12, 6), pady=5
            )

        self.preset_var = tk.StringVar(value=self.settings.get("preset", "tuned"))
        self.mode_var = tk.StringVar(value=self.settings.get("mode", "anchor only"))
        self.seconds_var = tk.StringVar(value=str(self.settings.get("seconds", "4")))
        self.size_var = tk.StringVar(value=self.settings.get("size", "1120x1344"))
        self.randomize_var = tk.BooleanVar(value=bool(self.settings.get("randomize", True)))
        self.optimize_var = tk.BooleanVar(value=bool(self.settings.get("optimize", True)))
        self.use_proxy_var = tk.BooleanVar(
            value=bool(self.settings.get("use_proxy", True)) and self.pool is not None
        )

        row_label("Preset", 0, 0)
        ttk.Combobox(opts, textvariable=self.preset_var, values=api.PRESETS, state="readonly").grid(
            row=0, column=1, sticky="ew", padx=(0, 10), pady=5
        )
        row_label("Mod", 0, 2)
        ttk.Combobox(opts, textvariable=self.mode_var, values=api.MODES, state="readonly").grid(
            row=0, column=3, sticky="ew", padx=(0, 12), pady=5
        )

        row_label("Süre (sn)", 1, 0)
        tk.Entry(
            opts,
            textvariable=self.seconds_var,
            bg=CARD2,
            fg=FG,
            insertbackground=FG,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            font=(FONT, 9),
        ).grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=5, ipady=2)
        row_label("Çözünürlük", 1, 2)
        ttk.Combobox(opts, textvariable=self.size_var, values=SIZES, state="readonly").grid(
            row=1, column=3, sticky="ew", padx=(0, 12), pady=5
        )

        row_label("Seed", 2, 0)
        seed_row = tk.Frame(opts, bg=CARD)
        seed_row.grid(row=2, column=1, sticky="ew", padx=(0, 10), pady=5)
        seed_row.columnconfigure(0, weight=1)
        self.seed_var = tk.StringVar(value=str(self.settings.get("seed", "0")))
        self.seed_entry = tk.Entry(
            seed_row,
            textvariable=self.seed_var,
            bg=CARD2,
            fg=FG,
            insertbackground=FG,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            font=(FONT, 9),
        )
        self.seed_entry.grid(row=0, column=0, sticky="ew", ipady=2)
        self._btn(seed_row, "🎲", self._random_seed, small=True).grid(row=0, column=1, padx=(6, 0))
        checks = tk.Frame(opts, bg=CARD)
        checks.grid(row=2, column=2, columnspan=2, sticky="w", padx=(0, 12))
        self.randomize_box = tk.Checkbutton(
            checks,
            text="rastgele seed (elle yazınca kapanır)",
            variable=self.randomize_var,
            command=self._sync_seed_state,
            bg=CARD,
            fg=MUTED,
            selectcolor=CARD,
            activebackground=CARD,
            activeforeground=FG,
            font=(FONT, 8),
            bd=0,
            highlightthickness=0,
        )
        self.randomize_box.pack(side="left")
        self.seed_var.trace_add("write", self._on_seed_typed)
        tk.Checkbutton(
            checks,
            text="yüklemede küçült",
            variable=self.optimize_var,
            bg=CARD,
            fg=MUTED,
            selectcolor=CARD,
            activebackground=CARD,
            activeforeground=FG,
            font=(FONT, 8),
            bd=0,
            highlightthickness=0,
        ).pack(side="left", padx=(10, 0))

        foot = tk.Frame(parent, bg=BG)
        foot.pack(fill="x", pady=(10, 0))
        self.gen_btn = tk.Button(
            foot,
            text="▶   VİDEO ÜRET",
            command=self._start_generate,
            bg=ACCENT,
            fg="white",
            activebackground="#6a4ce0",
            activeforeground="white",
            relief="flat",
            bd=0,
            font=(FONT, 11, "bold"),
            cursor="hand2",
            height=2,
        )
        self.gen_btn.pack(fill="x")
        self.progress = ttk.Progressbar(foot, mode="indeterminate")
        self.progress.pack(fill="x", pady=(6, 0))
        tk.Checkbutton(
            foot,
            text="Her üretimde farklı proxy",
            variable=self.use_proxy_var,
            bg=BG,
            fg=MUTED,
            selectcolor=CARD,
            activebackground=BG,
            activeforeground=FG,
            font=(FONT, 8),
            bd=0,
            highlightthickness=0,
        ).pack(anchor="w", pady=(6, 0))

    # -- sag panel -------------------------------------------------------- #

    def _build_right(self, parent: tk.Frame) -> None:
        card = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        card.grid(row=0, column=0, sticky="nsew")
        tk.Label(card, text="SONUÇ VİDEO", bg=CARD, fg=FG, font=(FONT, 8, "bold")).pack(
            anchor="w", padx=12, pady=(10, 0)
        )
        self.stage = tk.Canvas(card, bg="#0a0c10", highlightthickness=0)
        self.stage.pack(fill="both", expand=True, padx=12, pady=10)
        self.stage.bind("<Configure>", lambda _e: self._draw_stage())

        info = tk.Frame(parent, bg=BG)
        info.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        info.columnconfigure(0, weight=1)
        self.info_var = tk.StringVar(value="Sonuç yok")
        tk.Label(info, textvariable=self.info_var, bg=BG, fg=MUTED, font=(FONT, 9), anchor="w").grid(
            row=0, column=0, sticky="w"
        )
        self.play_btn = self._btn(info, "Oynat", self._open_result, small=True)
        self.play_btn.grid(row=0, column=1, padx=(6, 0))
        self.save_btn = self._btn(info, "MP4 kaydet", self._save_result, small=True)
        self.save_btn.grid(row=0, column=2, padx=(6, 0))
        self._btn(info, "Klasör", self._open_folder, small=True).grid(row=0, column=3, padx=(6, 0))

        log_card = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        log_card.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        tk.Label(log_card, text="GÜNLÜK", bg=CARD, fg=FG, font=(FONT, 8, "bold")).pack(
            anchor="w", padx=12, pady=(7, 0)
        )
        wrap = tk.Frame(log_card, bg=CARD)
        wrap.pack(fill="both", expand=True, padx=6, pady=(2, 6))
        self.log_text = tk.Text(
            wrap,
            height=9,
            wrap="word",
            bg="#0a0c10",
            fg=MUTED,
            relief="flat",
            highlightthickness=0,
            font=(MONO, 8),
            padx=8,
            pady=6,
            state="disabled",
        )
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(wrap, orient="vertical", command=self.log_text.yview)
        scroll.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scroll.set)
        for tag, color in (
            ("info", MUTED),
            ("ok", OK),
            ("warn", WARN),
            ("error", ERR),
            ("proxy", PROXY),
            ("status", "#cbd2e0"),
            ("time", "#5e6674"),
        ):
            self.log_text.tag_configure(tag, foreground=color)

    def _btn(self, parent, text, command, small: bool = False) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=CARD2,
            fg=FG,
            activebackground=BORDER,
            activeforeground=FG,
            relief="flat",
            bd=0,
            font=(FONT, 8 if small else 9),
            cursor="hand2",
            padx=10 if small else 16,
            pady=4 if small else 8,
        )

    # ------------------------------------------------------------------ #
    #  Fotograf
    # ------------------------------------------------------------------ #

    def _pick_photo(self) -> None:
        path = filedialog.askopenfilename(
            title="Referans fotoğraf",
            filetypes=[("Görseller", "*.png *.jpg *.jpeg *.webp *.bmp"), ("Tüm dosyalar", "*.*")],
        )
        if not path:
            return
        self.photo_path = path
        self.photo_label.configure(text=os.path.basename(path))
        self._draw_thumb()
        self._append_log("info", f"Fotoğraf seçildi: {os.path.basename(path)}")

    def _clear_photo(self) -> None:
        self.photo_path = None
        self.photo_label.configure(text="Henüz fotoğraf yok")
        self._draw_thumb()

    def _draw_thumb(self) -> None:
        canvas = self.thumb
        canvas.delete("all")
        w, h = max(canvas.winfo_width(), 2), max(canvas.winfo_height(), 2)
        if not self.photo_path:
            canvas.create_text(w // 2, h // 2, text="fotoğraf yok", fill="#3d4453", font=(FONT, 9))
            return
        try:
            with Image.open(self.photo_path) as im:
                im.thumbnail((w - 8, h - 8))
                self._thumb_ref = ImageTk.PhotoImage(im.convert("RGB"))
            canvas.create_image(w // 2, h // 2, image=self._thumb_ref)
        except Exception as exc:
            canvas.create_text(w // 2, h // 2, text=f"önizleme yok: {exc}", fill=ERR, font=(FONT, 8))

    def _draw_stage(self) -> None:
        canvas = self.stage
        canvas.delete("all")
        w, h = max(canvas.winfo_width(), 2), max(canvas.winfo_height(), 2)
        if self.result_path:
            canvas.create_text(w // 2, h // 2 - 14, text="▶  video hazır", fill=OK, font=(FONT, 14, "bold"))
            canvas.create_text(
                w // 2,
                h // 2 + 12,
                text=os.path.basename(self.result_path),
                fill=MUTED,
                font=(MONO, 9),
            )
        else:
            canvas.create_text(w // 2, h // 2, text="üretim bekleniyor", fill="#3d4453", font=(FONT, 10))

    # ------------------------------------------------------------------ #
    #  Uretim
    # ------------------------------------------------------------------ #

    def _sync_seed_state(self) -> None:
        """Girdi her zaman yazilabilir; kutu yalnizca sunucunun rastgele secmesini belirler."""
        self.seed_entry.configure(fg="#646c7b" if self.randomize_var.get() else FG)

    def _on_seed_typed(self, *_args) -> None:
        # Elle deger yazilinca "rastgele seed" kapanir; yazilan deger kullanilir.
        if not self.randomize_var.get():
            return
        value = self.seed_var.get().strip()
        if not value or not value.isdigit():
            return
        self.randomize_var.set(False)
        self._sync_seed_state()
        self._append_log("info", f"Seed elle girildi ({value}); rastgele seed kapatıldı.")

    def _random_seed(self) -> None:
        self.randomize_var.set(False)
        self.seed_var.set(str(random.randint(0, 2**31 - 1)))
        self._sync_seed_state()

    def _set_busy(self, busy: bool) -> None:
        if busy:
            self.gen_btn.configure(state="disabled", text="⏳   ÜRETİLİYOR…", bg="#3a3357")
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.configure(value=0)
            self.gen_btn.configure(state="normal", text="▶   VİDEO ÜRET", bg=ACCENT)
        self._sync_seed_state()

    def _start_generate(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.photo_path:
            messagebox.showwarning("Fotoğraf", "LTX tek bir referans fotoğrafla çalışır. Önce fotoğraf seçin.")
            return
        prompt = self.prompt_text.get("1.0", "end").strip()
        if not prompt:
            messagebox.showwarning("Prompt", "Ne üretmek istediğinizi yazın.")
            self.prompt_text.focus_set()
            return

        try:
            seconds = float(self.seconds_var.get().replace(",", "."))
            if not 1 <= seconds <= 10:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Süre", "Süre 1-10 saniye arasında olmalı.")
            return
        seed = 0
        if not self.randomize_var.get():
            try:
                seed = int(float(self.seed_var.get().strip() or "0"))
                if seed < 0:
                    raise ValueError
            except ValueError:
                messagebox.showwarning("Seed", "Seed 0 veya daha büyük bir tam sayı olmalı.")
                return
        try:
            width, height = (int(v) for v in self.size_var.get().split("x"))
        except ValueError:
            width, height = 1120, 1344

        use_proxy = bool(self.use_proxy_var.get()) and self.pool is not None
        # DEBUG: Proxy durumu logla
        self._append_log("info", f"DEBUG: use_proxy_var={self.use_proxy_var.get()}, pool={'var' if self.pool else 'yok'}, use_proxy={use_proxy}")
        if self.use_proxy_var.get() and self.pool is None:
            self._append_log("warn", "Proxy dosyası yok, doğrudan bağlantı kullanılıyor.")
        # Proxy havuzu varsa zorla kullan (checkbox bazen resetleniyor olabilir)
        if self.pool is not None and not use_proxy:
            self._append_log("warn", "Proxy havuzu var ama use_proxy=False, zorla aktif ediliyor")
            use_proxy = True

        self._save_settings()
        self._set_busy(True)
        self.status_var.set("İstek hazırlanıyor…")
        self.play_btn.configure(state="disabled")
        self.save_btn.configure(state="disabled")

        self.worker = threading.Thread(
            target=self._run_job,
            args=(
                self.photo_path,
                prompt,
                self.negative_text.get("1.0", "end").strip(),
                self.preset_var.get(),
                seconds,
                width,
                height,
                self.mode_var.get(),
                seed,
                bool(self.randomize_var.get()),
                bool(self.optimize_var.get()),
                use_proxy,
            ),
            daemon=True,
        )
        self.worker.start()

    def _run_job(
        self,
        image_path: str,
        prompt: str,
        negative: str,
        preset: str,
        seconds: float,
        width: int,
        height: int,
        mode: str,
        seed: int,
        randomize: bool,
        optimize: bool,
        use_proxy: bool,
    ) -> None:
        def log(level: str, msg: str) -> None:
            self.events.put(("log", level, msg))

        try:
            client = api.LTXVideoClient(proxy_pool=self.pool if use_proxy else None, on_log=log)
            result = client.generate(
                image_path,
                prompt,
                negative_prompt=negative or None,
                preset=preset,
                seconds=seconds,
                max_width=width,
                max_height=height,
                mode=mode,
                seed=seed if not randomize else -1,
                randomize=randomize,
                optimize_image=optimize,
            )
            self.events.put(("result", result))
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
                    level, msg = event[1], event[2]
                    self._append_log(level, msg)
                    if level == "status":
                        self.status_var.set(msg)
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

    def _on_result(self, result: api.VideoResult) -> None:
        self.result = result
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(OUTPUT_DIR, f"ltx_{stamp}.mp4")
        try:
            with open(path, "wb") as fh:
                fh.write(result.video_bytes)
            self.result_path = path
        except OSError as exc:
            self._append_log("warn", f"Sonuç otomatik kaydedilemedi: {exc}")
            self.result_path = None

        self._draw_stage()
        self.play_btn.configure(state="normal" if self.result_path else "disabled")
        self.save_btn.configure(state="normal")
        info = f"{result.size_mb:.1f} MB · seed {result.seed if result.seed is not None else '?'} · {result.elapsed:.0f} sn"
        if result.status:
            info = f"{result.status[:90]} · " + info
        self.info_var.set(info)
        self.status_var.set("Tamamlandı ✓")
        self._append_log("ok", f"Sonuç hazır: {os.path.basename(path) if path else 'bellekte'}")
        try:
            self.bell()
            self.lift()
        except Exception:
            pass

    def _on_error(self, message: str) -> None:
        self.status_var.set("Hata")
        self._append_log("error", message)
        messagebox.showerror("Üretim hatası", message)

    # ------------------------------------------------------------------ #
    #  Kaydetme / acma
    # ------------------------------------------------------------------ #

    def _save_result(self) -> None:
        if not self.result:
            return
        path = filedialog.asksaveasfilename(
            title="MP4 kaydet",
            defaultextension=".mp4",
            initialfile=os.path.basename(self.result_path or "ltx.mp4"),
            initialdir=OUTPUT_DIR,
            filetypes=[("MP4 video", "*.mp4")],
        )
        if not path:
            return
        try:
            with open(path, "wb") as fh:
                fh.write(self.result.video_bytes)
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
            os.startfile(OUTPUT_DIR)  # type: ignore[attr-defined]
        except OSError:
            pass

    def _back_to_launcher(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno("Space seç", "Üretim sürüyor. Yine de menüye dönmek istiyor musunuz?"):
                return
        self._save_settings()
        # Launcher uzerinden acildiyk sadece kapanir; launcher geri gelecek.
        # Dogrudan acildiyk yeni launcher baslat.
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

    # ------------------------------------------------------------------ #

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
    app = LtXApp()
    app.mainloop()


if __name__ == "__main__":
    main()
