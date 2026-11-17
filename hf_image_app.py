"""MiniMax H3 Image — Windows masaustu arayuzu.

Calistirma:
    python hf_image_app.py

Gereksinimler:
    pip install requests pillow

Fotograf yukleyip duzenleyebilir veya bos birakip metinden gorsel uretebilirsiniz.
Her uretim tek bir proxy IP'si uzerinden gonderilir; yeni uretimde listeden farkli bir IP alinir.
"""

from __future__ import annotations

import io
import json
import os
import queue
import random
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from PIL import Image, ImageDraw, ImageTk

import hf_image_client as api

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(APP_DIR, "settings.json")
OUTPUT_DIR = os.path.join(APP_DIR, "outputs")

# -- renkler --------------------------------------------------------------- #
BG = "#0f1115"
PANEL = "#151820"
CARD = "#1b1f28"
CARD2 = "#242a36"
BORDER = "#2b3140"
FG = "#e9ecf1"
MUTED = "#8b93a1"
ACCENT = "#e8197e"
ACCENT2 = "#ff6a3d"
OK = "#38d39f"
WARN = "#ffb020"
ERR = "#ff5d6c"
PROXY = "#6fb8ff"

FONT = "Segoe UI"
MONO = "Consolas"

ASPECTS = api.ASPECTS
RESOLUTIONS = api.RESOLUTIONS
EFFORTS = api.EFFORTS
MAX_IMAGES = api.MAX_IMAGES

PROMPT_HINT = "Fotoğraflara <Picture 1>, <Picture 2> … diye atıf yapın.  Ctrl+Enter ile üret."


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("MiniMax H3 Image · Studio")
        self.geometry("1260x810+20+10")
        self.minsize(1080, 720)
        self.configure(bg=BG)
        self._set_icon()

        self.photos: list[dict] = []
        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self.result = None
        self.result_path: Optional[str] = None
        self.result_pil: Optional[Image.Image] = None
        self._photo_ref = None
        self._render_job = None
        self._thumb_refs: list = []
        self._tags: list = []
        self.pool: Optional[api.ProxyPool] = None
        self.proxy_file: Optional[str] = None

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        self.settings = self._load_settings()
        self._init_proxy()
        self._init_style()
        self._build()
        self._refresh_photos()
        self._set_busy(False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._pump_job = self.after(100, self._pump)

        self._append_log("info", "Hazır. Fotoğraf ekleyin veya doğrudan prompt yazın.")
        if self.proxy_file:
            self._append_log("info", f"Proxy dosyası: {os.path.basename(self.proxy_file)} · {len(self.pool)} IP")
        else:
            self._append_log("warn", "Proxy dosyası bulunamadı; doğrudan bağlantı kullanılacak.")

    # ------------------------------------------------------------------ #
    #  Kurulum
    # ------------------------------------------------------------------ #

    def _set_icon(self) -> None:
        try:
            img = Image.new("RGB", (64, 64), (20, 22, 30))
            draw = ImageDraw.Draw(img)
            for y in range(64):
                t = y / 63
                color = (
                    int(232 * (1 - t) + 255 * t),
                    int(25 * (1 - t) + 106 * t),
                    int(126 * (1 - t) + 61 * t),
                )
                draw.line([(0, y), (64, y)], fill=color)
            draw.rounded_rectangle([8, 14, 56, 50], radius=8, fill=(18, 20, 27))
            draw.text((20, 20), "H3", fill=(255, 255, 255))
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
            "aspect": self.aspect_var.get(),
            "resolution": self.resolution,
            "enhance": bool(self.enhance_var.get()),
            "effort": self.effort_var.get(),
            "randomize": bool(self.randomize_var.get()),
            "seed": self.seed_var.get(),
            "use_proxy": bool(self.use_proxy_var.get()),
            "optimize": bool(self.optimize_var.get()),
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
            except Exception as exc:  # bozuk dosya vb.
                self.pool = None
                messagebox.showwarning("Proxy", f"Proxy dosyası okunamadı:\n{exc}")

    def _init_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        self.option_add("*TCombobox*Listbox.background", CARD)
        self.option_add("*TCombobox*Listbox.foreground", FG)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.option_add("*TCombobox*Listbox.font", (FONT, 10))

        style.configure(".", background=BG, foreground=FG, fieldbackground=CARD, bordercolor=BORDER)
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=(FONT, 9))
        style.configure("TSeparator", background=BORDER)
        style.configure(
            "TCombobox",
            fieldbackground=CARD,
            background=CARD,
            foreground=FG,
            arrowcolor=FG,
            bordercolor=BORDER,
            lightcolor=CARD,
            darkcolor=CARD,
            padding=5,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", CARD)],
            foreground=[("readonly", FG)],
            background=[("active", CARD2)],
            bordercolor=[("focus", ACCENT)],
        )
        style.configure(
            "TCheckbutton",
            background=BG,
            foreground=FG,
            font=(FONT, 9),
            focuscolor=BG,
        )
        style.map("TCheckbutton", background=[("active", BG)], foreground=[("disabled", MUTED)])
        style.configure("TEntry", fieldbackground=CARD, foreground=FG, insertcolor=FG, bordercolor=BORDER, padding=5)
        style.map("TEntry", bordercolor=[("focus", ACCENT)], fieldbackground=[("disabled", CARD2)])
        style.configure("SeedOn.TEntry", fieldbackground=CARD, foreground=FG, insertcolor=FG, bordercolor=BORDER, padding=5)
        style.configure("SeedOff.TEntry", fieldbackground=CARD, foreground="#646c7b", insertcolor=FG, bordercolor=BORDER, padding=5)
        style.map("SeedOff.TEntry", bordercolor=[("focus", ACCENT)])
        style.configure(
            "Accent.Horizontal.TProgressbar",
            troughcolor=CARD,
            background=ACCENT,
            bordercolor=CARD,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
            thickness=4,
        )
        style.configure(
            "Vertical.TScrollbar",
            background=CARD2,
            troughcolor=CARD,
            bordercolor=CARD,
            arrowcolor=MUTED,
            lightcolor=CARD2,
            darkcolor=CARD2,
            relief="flat",
        )
        style.map(
            "Vertical.TScrollbar",
            background=[("active", "#313849")],
            arrowcolor=[("active", FG)],
        )
        style.configure("TScrollbar", background=CARD2, troughcolor=CARD, bordercolor=CARD, arrowcolor=MUTED)

    # ------------------------------------------------------------------ #
    #  Arayuz
    # ------------------------------------------------------------------ #

    def _build(self) -> None:
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        # Ust baslik
        header = tk.Frame(self, bg=PANEL, height=74)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.columnconfigure(0, weight=1)

        title = tk.Frame(header, bg=PANEL)
        title.grid(row=0, column=0, sticky="w", padx=22, pady=12)
        tk.Label(title, text="H3", bg=PANEL, fg=ACCENT, font=(FONT, 22, "bold")).pack(side="left")
        tk.Label(title, text=" Image", bg=PANEL, fg=FG, font=(FONT, 22)).pack(side="left")
        tk.Label(
            title,
            text="  ·  fotoğraf düzenleme & metinden üretim",
            bg=PANEL,
            fg=MUTED,
            font=(FONT, 10),
        ).pack(side="left", pady=(8, 0))

        tk.Label(
            header,
            text="MiniMaxAI / minimax-h3-image",
            bg=PANEL,
            fg=MUTED,
            font=(FONT, 9),
        ).grid(row=0, column=1, sticky="e", padx=(0, 12))

        tk.Button(
            header,
            text="⌂  Space seç",
            command=self._back_to_launcher,
            bg=CARD2,
            fg=FG,
            activebackground=BORDER,
            activeforeground=FG,
            relief="flat",
            bd=0,
            font=(FONT, 8),
            cursor="hand2",
            padx=10,
            pady=4,
        ).grid(row=0, column=2, sticky="e", padx=(0, 22))

        bar = tk.Canvas(self, height=3, bg=BG, highlightthickness=0)
        bar.grid(row=0, column=0, sticky="sew")
        self._gradient_bar = bar
        bar.bind("<Configure>", self._draw_gradient)

        body = tk.Frame(self, bg=BG)
        body.grid(row=1, column=0, sticky="nsew", padx=16, pady=(12, 8))
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=0, minsize=472)
        body.columnconfigure(1, weight=1)

        left = tk.Frame(body, bg=BG, width=472)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        left.grid_propagate(False)
        left.pack_propagate(False)
        self._build_left(left)

        right = tk.Frame(body, bg=BG)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)
        self._build_right(right)

        # Durum cubugu
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
                int(232 + (255 - 232) * t),
                int(25 + (106 - 25) * t),
                int(126 + (61 - 126) * t),
            )
            canvas.create_line(
                x,
                1,
                x + 3,
                1,
                fill=f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}",
                width=3,
            )

    def _build_left(self, parent: tk.Frame) -> None:
        pad = {"padx": 2}

        # --- fotograflar ---
        head = tk.Frame(parent, bg=BG)
        head.pack(fill="x", pady=(0, 6))
        self.photo_count = tk.StringVar(value="FOTOĞRAFLAR  0/8")
        tk.Label(head, textvariable=self.photo_count, bg=BG, fg=FG, font=(FONT, 9, "bold")).pack(side="left")
        self._btn(head, "+ Fotoğraf", self._add_photos, small=True).pack(side="right")

        box = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        box.pack(fill="x")

        self.photos_canvas = tk.Canvas(box, bg=CARD, highlightthickness=0, height=132)
        self.photos_canvas.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.photos_canvas.yview)
        scroll.pack(side="right", fill="y")
        self.photos_canvas.configure(yscrollcommand=scroll.set)

        self.photos_inner = tk.Frame(self.photos_canvas, bg=CARD)
        self._photos_window = self.photos_canvas.create_window((0, 0), window=self.photos_inner, anchor="nw")
        self.photos_inner.bind(
            "<Configure>",
            lambda e: self.photos_canvas.configure(scrollregion=self.photos_canvas.bbox("all")),
        )
        self.photos_canvas.bind(
            "<Configure>",
            lambda e: self.photos_canvas.itemconfigure(self._photos_window, width=e.width),
        )
        self.photos_canvas.bind("<Enter>", self._wheel_enter)
        self.photos_canvas.bind("<Leave>", self._wheel_leave)

        # --- fotograf etiketleri ---
        self.tags_frame = tk.Frame(parent, bg=BG)
        self.tags_frame.pack(fill="x", pady=(6, 0))

        # --- prompt ---
        tk.Label(parent, text="PROMPT", bg=BG, fg=FG, font=(FONT, 9, "bold")).pack(anchor="w", pady=(14, 4))
        self.prompt_text = tk.Text(
            parent,
            height=4,
            wrap="word",
            bg=CARD,
            fg=FG,
            insertbackground=FG,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            font=(FONT, 10),
            padx=10,
            pady=8,
        )
        self.prompt_text.pack(fill="x")
        self.prompt_text.bind("<Control-Return>", self._ctrl_enter)
        tk.Label(parent, text=PROMPT_HINT, bg=BG, fg=MUTED, font=(FONT, 8), justify="left", wraplength=450).pack(
            anchor="w", pady=(4, 0)
        )

        # --- ayarlar ---
        opts = tk.Frame(parent, bg=BG)
        opts.pack(fill="x", pady=(10, 0))
        opts.columnconfigure(1, weight=1)
        opts.columnconfigure(3, weight=1)

        tk.Label(opts, text="Oran", bg=BG, fg=MUTED, font=(FONT, 9)).grid(row=0, column=0, sticky="w", padx=(2, 8))
        self.aspect_var = tk.StringVar(value=self.settings.get("aspect", "auto"))
        self.aspect_box = ttk.Combobox(
            opts, textvariable=self.aspect_var, values=ASPECTS, state="readonly", width=10
        )
        self.aspect_box.grid(row=0, column=1, sticky="ew")

        tk.Label(opts, text="Seed", bg=BG, fg=MUTED, font=(FONT, 9)).grid(
            row=0, column=2, sticky="e", padx=(16, 8)
        )
        seed_row = tk.Frame(opts, bg=BG)
        seed_row.grid(row=0, column=3, sticky="ew")
        seed_row.columnconfigure(0, weight=1)
        self.seed_var = tk.StringVar(value=str(self.settings.get("seed", 0)))
        self.seed_entry = ttk.Entry(seed_row, textvariable=self.seed_var)
        self.seed_entry.grid(row=0, column=0, sticky="ew")
        self._btn(seed_row, "🎲", self._random_seed, small=True).grid(row=0, column=1, padx=(6, 0))

        self.randomize_var = tk.BooleanVar(value=bool(self.settings.get("randomize", True)))
        ttk.Checkbutton(
            opts,
            text="Rastgele seed (elle yazınca kapanır)",
            variable=self.randomize_var,
            command=self._sync_seed_state,
        ).grid(row=1, column=1, columnspan=3, sticky="w", pady=(6, 0))
        self.seed_var.trace_add("write", self._on_seed_typed)
        self._sync_seed_state()

        # cozumurluk segmentleri
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(8, 0))
        tk.Label(row, text="Çözünürlük", bg=BG, fg=MUTED, font=(FONT, 9)).pack(side="left", padx=(2, 8))
        self.resolution = self.settings.get("resolution", "4 MP")
        if self.resolution not in RESOLUTIONS:
            self.resolution = "4 MP"
        self.res_buttons: dict[str, tk.Button] = {}
        for res in RESOLUTIONS:
            btn = tk.Button(
                row,
                text=res,
                command=lambda r=res: self._set_resolution(r),
                bg=CARD,
                fg=MUTED,
                activebackground=CARD2,
                activeforeground=FG,
                relief="flat",
                bd=0,
                font=(FONT, 9, "bold"),
                padx=12,
                pady=4,
                cursor="hand2",
            )
            btn.pack(side="left", padx=(0, 4))
            self.res_buttons[res] = btn
        self._set_resolution(self.resolution)

        row2 = tk.Frame(parent, bg=BG)
        row2.pack(fill="x", pady=(8, 0))
        self.enhance_var = tk.BooleanVar(value=bool(self.settings.get("enhance", False)))
        ttk.Checkbutton(
            row2, text="✨ Prompt güçlendir", variable=self.enhance_var, command=self._sync_effort_state
        ).pack(side="left")
        tk.Label(row2, text="efor", bg=BG, fg=MUTED, font=(FONT, 9)).pack(side="left", padx=(14, 6))
        self.effort_var = tk.StringVar(value=self.settings.get("effort", "low"))
        if self.effort_var.get() not in EFFORTS:
            self.effort_var.set("low")
        self.effort_box = ttk.Combobox(
            row2, textvariable=self.effort_var, values=EFFORTS, state="readonly", width=8
        )
        self.effort_box.pack(side="left")
        self._sync_effort_state()

        tk.Label(
            parent,
            text="Güçlendirme yalnızca metinden üretimde çalışır.",
            bg=BG,
            fg=MUTED,
            font=(FONT, 8),
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        # --- uret ---
        self.gen_btn = tk.Button(
            parent,
            text="✦   ÜRET",
            command=self._start_generate,
            bg=ACCENT,
            fg="white",
            activebackground=ACCENT2,
            activeforeground="white",
            disabledforeground="#d9b9c8",
            relief="flat",
            bd=0,
            font=(FONT, 11, "bold"),
            pady=9,
            cursor="hand2",
        )
        self.gen_btn.pack(fill="x", pady=(12, 0))
        self.gen_btn.bind("<Enter>", lambda e: self._hover(self.gen_btn, ACCENT2))
        self.gen_btn.bind("<Leave>", lambda e: self._hover(self.gen_btn, ACCENT))

        self.progress = ttk.Progressbar(parent, mode="indeterminate", style="Accent.Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(5, 0))

        # --- alt secenekler ---
        foot = tk.Frame(parent, bg=BG)
        foot.pack(fill="x", pady=(8, 0))
        self.use_proxy_var = tk.BooleanVar(value=bool(self.settings.get("use_proxy", True)) and self.pool is not None)
        ttk.Checkbutton(foot, text="Her üretimde farklı proxy", variable=self.use_proxy_var).pack(side="left")
        self.optimize_var = tk.BooleanVar(value=bool(self.settings.get("optimize", True)))
        ttk.Checkbutton(foot, text="Fotoğraf optimize", variable=self.optimize_var).pack(
            side="left", padx=(10, 0)
        )
        self._btn(foot, "Temizle", self._clear_all, small=True).pack(side="right")

    def _build_right(self, parent: tk.Frame) -> None:
        card = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        card.grid(row=0, column=0, sticky="nsew")
        card.rowconfigure(0, weight=1)
        card.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(card, bg="#0a0c10", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.canvas.bind("<Configure>", self._schedule_result_render)

        info = tk.Frame(parent, bg=BG)
        info.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        info.columnconfigure(0, weight=1)
        self.info_var = tk.StringVar(value="Sonuç yok")
        tk.Label(info, textvariable=self.info_var, bg=BG, fg=MUTED, font=(FONT, 9), anchor="w").grid(
            row=0, column=0, sticky="w"
        )
        self.save_btn = self._btn(info, "PNG kaydet", self._save_result, small=True)
        self.save_btn.grid(row=0, column=1, padx=(6, 0))
        self.open_btn = self._btn(info, "Aç", self._open_result, small=True)
        self.open_btn.grid(row=0, column=2, padx=(6, 0))
        self._btn(info, "Klasör", self._open_folder, small=True).grid(row=0, column=3, padx=(6, 0))

        used = tk.Frame(parent, bg=BG)
        used.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        tk.Label(used, text="KULLANILAN PROMPT", bg=BG, fg=FG, font=(FONT, 8, "bold")).pack(anchor="w")
        self.used_prompt = tk.Text(
            used,
            height=2,
            wrap="word",
            bg=CARD,
            fg=MUTED,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            font=(FONT, 9),
            padx=8,
            pady=5,
        )
        self.used_prompt.pack(fill="x", pady=(3, 0))
        self.used_prompt.configure(state="disabled")

        log_card = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        log_card.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        tk.Label(log_card, text="GÜNLÜK", bg=CARD, fg=FG, font=(FONT, 8, "bold")).pack(anchor="w", padx=10, pady=(7, 0))

        log_wrap = tk.Frame(log_card, bg=CARD)
        log_wrap.pack(fill="both", expand=True, padx=6, pady=(2, 6))
        self.log_text = tk.Text(
            log_wrap,
            height=8,
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
        log_scroll = ttk.Scrollbar(log_wrap, orient="vertical", command=self.log_text.yview)
        log_scroll.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=log_scroll.set)

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

        self.save_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")

    # ------------------------------------------------------------------ #
    #  Kucuk yardimcilar
    # ------------------------------------------------------------------ #

    def _btn(self, parent, text, command, small: bool = False) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=CARD2,
            fg=FG,
            activebackground="#313849",
            activeforeground=FG,
            disabledforeground="#5e6674",
            relief="flat",
            bd=0,
            font=(FONT, 8 if small else 9),
            padx=9 if small else 14,
            pady=3 if small else 7,
            cursor="hand2",
        )

    @staticmethod
    def _hover(widget: tk.Button, color: str) -> None:
        if str(widget["state"]) == "normal":
            widget.configure(bg=color)

    def _wheel_enter(self, _event=None) -> None:
        self.bind_all("<MouseWheel>", self._on_wheel)

    def _wheel_leave(self, _event=None) -> None:
        self.unbind_all("<MouseWheel>")

    def _on_wheel(self, event) -> None:
        self.photos_canvas.yview_scroll(int(-event.delta / 120), "units")

    def _ctrl_enter(self, _event=None):
        self._start_generate()
        return "break"

    # ------------------------------------------------------------------ #
    #  Fotograflar
    # ------------------------------------------------------------------ #

    def _add_photos(self) -> None:
        remaining = MAX_IMAGES - len(self.photos)
        if remaining <= 0:
            messagebox.showinfo("Sınır", f"En fazla {MAX_IMAGES} fotoğraf ekleyebilirsiniz.")
            return
        paths = filedialog.askopenfilenames(
            title="Düzenlenecek fotoğrafları seçin",
            filetypes=[
                ("Görseller", "*.jpg *.jpeg *.png *.webp *.gif *.bmp"),
                ("Tüm dosyalar", "*.*"),
            ],
        )
        added = 0
        for path in paths:
            if len(self.photos) >= MAX_IMAGES:
                break
            self.photos.append({"path": path})
            added += 1
        if added:
            self._refresh_photos()
            self._append_log("info", f"{added} fotoğraf eklendi.")

    def _remove_photo(self, index: int) -> None:
        if 0 <= index < len(self.photos):
            self.photos.pop(index)
            self._refresh_photos()

    def _insert_tag(self, number: int) -> None:
        self.prompt_text.insert("insert", f"<Picture {number}>")
        self.prompt_text.focus_set()

    def _refresh_photos(self) -> None:
        for child in self.photos_inner.winfo_children():
            child.destroy()
        self._thumb_refs.clear()

        self.photo_count.set(f"FOTOĞRAFLAR  {len(self.photos)}/{MAX_IMAGES}")

        if not self.photos:
            tk.Label(
                self.photos_inner,
                text="Henüz fotoğraf yok.\nMetinden görsel üretmek için boş bırakabilirsiniz.",
                bg=CARD,
                fg=MUTED,
                font=(FONT, 9),
                justify="left",
            ).pack(anchor="w", padx=12, pady=16)
        else:
            for i, item in enumerate(self.photos):
                row = tk.Frame(self.photos_inner, bg=CARD)
                row.pack(fill="x", padx=6, pady=3)

                try:
                    thumb = Image.open(item["path"])
                    thumb.thumbnail((52, 52), Image.LANCZOS)
                    photo = ImageTk.PhotoImage(thumb)
                    self._thumb_refs.append(photo)
                    img_label = tk.Label(row, image=photo, bg=CARD, cursor="hand2")
                    img_label.image = photo
                    img_label.pack(side="left", padx=(2, 8))
                    img_label.bind("<Button-1>", lambda e, n=i + 1: self._insert_tag(n))
                except Exception:
                    tk.Label(row, text="?", bg=CARD, fg=ERR, font=(FONT, 14)).pack(side="left", padx=(10, 14))

                text = tk.Frame(row, bg=CARD)
                text.pack(side="left", fill="x", expand=True)
                tk.Label(
                    text,
                    text=os.path.basename(item["path"])[:38],
                    bg=CARD,
                    fg=FG,
                    font=(FONT, 9),
                    anchor="w",
                ).pack(anchor="w")
                tk.Label(
                    text,
                    text=f"<Picture {i + 1}>  ·  tıkla ve prompt'a ekle",
                    bg=CARD,
                    fg=ACCENT,
                    font=(FONT, 8),
                    cursor="hand2",
                ).pack(anchor="w")

                close = tk.Label(row, text="✕", bg=CARD, fg=MUTED, font=(FONT, 10), cursor="hand2")
                close.pack(side="right", padx=6)
                close.bind("<Button-1>", lambda e, n=i: self._remove_photo(n))

        # etiket butonlari
        for child in self.tags_frame.winfo_children():
            child.destroy()
        if self.photos:
            tk.Label(self.tags_frame, text="Ekle:", bg=BG, fg=MUTED, font=(FONT, 8)).pack(side="left", padx=(2, 4))
            for i in range(len(self.photos)):
                tag = tk.Button(
                    self.tags_frame,
                    text=f"<Picture {i + 1}>",
                    command=lambda n=i + 1: self._insert_tag(n),
                    bg=CARD,
                    fg=ACCENT,
                    activebackground=CARD2,
                    activeforeground=ACCENT2,
                    relief="flat",
                    bd=0,
                    font=(MONO, 8),
                    padx=6,
                    pady=2,
                    cursor="hand2",
                )
                tag.pack(side="left", padx=(0, 4))

    # ------------------------------------------------------------------ #
    #  Ayar etkilesimleri
    # ------------------------------------------------------------------ #

    def _set_resolution(self, res: str) -> None:
        self.resolution = res
        for name, btn in self.res_buttons.items():
            selected = name == res
            btn.configure(
                bg=ACCENT if selected else CARD,
                fg="white" if selected else MUTED,
                activebackground=ACCENT2 if selected else CARD2,
                activeforeground="white",
            )

    def _sync_seed_state(self) -> None:
        """Girdi her zaman yazilabilir kalir; kutu sadece seed'in kullanilip kullanilmayacagini belirler."""
        random_mode = bool(self.randomize_var.get())
        try:
            self.seed_entry.configure(style="SeedOff.TEntry" if random_mode else "SeedOn.TEntry")
        except tk.TclError:
            pass

    def _on_seed_typed(self, *_args) -> None:
        # Elle deger yazilinca "rastgele seed" kapanir; yazilan deger kullanilir.
        if not self.randomize_var.get():
            return
        value = self.seed_var.get().strip()
        if not value or not value.lstrip("-").isdigit():
            return
        self.randomize_var.set(False)
        self._sync_seed_state()
        self._append_log("info", f"Seed elle girildi ({value}); rastgele seed kapatıldı.")

    def _random_seed(self) -> None:
        self.randomize_var.set(False)
        self.seed_var.set(str(random.randint(0, 2**31 - 1)))
        self._sync_seed_state()

    def _sync_effort_state(self) -> None:
        state = "readonly" if self.enhance_var.get() else "disabled"
        self.effort_box.configure(state=state)

    def _clear_all(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.photos.clear()
        self.prompt_text.delete("1.0", "end")
        self._refresh_photos()

    # ------------------------------------------------------------------ #
    #  Uretim
    # ------------------------------------------------------------------ #

    def _set_busy(self, busy: bool) -> None:
        if busy:
            self.gen_btn.configure(state="disabled", text="⏳   ÜRETİLİYOR…", bg="#4a2536")
            self.progress.start(12)
            self.use_proxy_var.set(self.use_proxy_var.get())
        else:
            self.progress.stop()
            self.progress.configure(value=0)
            self.gen_btn.configure(state="normal", text="✦   ÜRET", bg=ACCENT)

    def _start_generate(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        prompt = self.prompt_text.get("1.0", "end").strip()
        if not prompt:
            messagebox.showwarning("Prompt", "Önce ne üretmek istediğinizi yazın.")
            self.prompt_text.focus_set()
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

        use_proxy = bool(self.use_proxy_var.get()) and self.pool is not None
        # DEBUG: Proxy durumu logla
        self._append_log("info", f"DEBUG: use_proxy_var={self.use_proxy_var.get()}, pool={'var' if self.pool else 'yok'}, use_proxy={use_proxy}")
        if self.use_proxy_var.get() and self.pool is None:
            self._append_log("warn", "Proxy dosyası yok, doğrudan bağlantı kullanılıyor.")
        # Proxy havuzu varsa zorla kullan (checkbox bazen resetleniyor olabilir)
        if self.pool is not None and not use_proxy:
            self._append_log("warn", "Proxy havuzu var ama use_proxy=False, zorla aktif ediliyor")
            use_proxy = True

        self._set_busy(True)
        self.status_var.set("İstek hazırlanıyor…")
        self.save_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")

        self.worker = threading.Thread(
            target=self._run_job,
            args=(
                [p["path"] for p in self.photos],
                prompt,
                self.aspect_var.get(),
                self.resolution,
                bool(self.enhance_var.get()),
                bool(self.randomize_var.get()),
                seed,
                self.effort_var.get(),
                bool(self.optimize_var.get()),
                use_proxy,
            ),
            daemon=True,
        )
        self.worker.start()

    def _run_job(
        self,
        paths: list[str],
        prompt: str,
        aspect: str,
        resolution: str,
        enhance: bool,
        randomize: bool,
        seed: int,
        effort: str,
        optimize: bool,
        use_proxy: bool,
    ) -> None:
        def log(level: str, msg: str) -> None:
            self.events.put(("log", level, msg))

        try:
            client = api.MiniMaxH3Client(
                proxy_pool=self.pool if use_proxy else None,
                on_log=log,
            )
            result = client.generate(
                paths,
                prompt,
                aspect=aspect,
                resolution=resolution,
                enhance=enhance,
                randomize=randomize,
                seed=seed,
                reasoning_effort=effort,
                optimize_images=optimize,
            )
            self.events.put(("result", result))
        except Exception as exc:  # ag/http/sunucu hatalari
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

    def _on_result(self, result) -> None:
        self.result = result
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(OUTPUT_DIR, f"minimax_{stamp}.png")
        try:
            with open(path, "wb") as fh:
                fh.write(result.image_bytes)
            self.result_path = path
        except OSError as exc:
            self._append_log("warn", f"Sonuç otomatik kaydedilemedi: {exc}")
            self.result_path = None

        try:
            image = Image.open(io.BytesIO(result.image_bytes))
            image.load()
            self.result_pil = image
        except Exception as exc:
            self.result_pil = None
            self._append_log("error", f"Sonuç görseli açılamadı: {exc}")

        self._render_result()
        self.save_btn.configure(state="normal")
        self.open_btn.configure(state="normal")

        self._set_text(self.used_prompt, result.prompt_used)
        info = f"{result.stats or 'tamamlandı'}  ·  toplam {result.elapsed:.1f} sn"
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
    #  Sonuc goruntusu / kaydetme
    # ------------------------------------------------------------------ #

    def _schedule_result_render(self, _event=None) -> None:
        if self._render_job:
            try:
                self.after_cancel(self._render_job)
            except Exception:
                pass
        self._render_job = self.after(120, self._render_result)

    def _render_result(self) -> None:
        self._render_job = None
        self.canvas.delete("all")
        width = max(self.canvas.winfo_width(), 200)
        height = max(self.canvas.winfo_height(), 200)

        if self.result_pil is None:
            self.canvas.create_text(
                width // 2,
                height // 2,
                text="Sonuç burada görünecek",
                fill="#3d4453",
                font=(FONT, 12),
            )
            return

        image = self.result_pil.copy()
        image.thumbnail((max(width - 32, 100), max(height - 32, 100)), Image.LANCZOS)
        photo = ImageTk.PhotoImage(image)
        self._photo_ref = photo
        self.canvas.create_image(width // 2, height // 2, image=photo, anchor="center")

    def _save_result(self) -> None:
        if not self.result:
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = filedialog.asksaveasfilename(
            title="Görseli kaydet",
            defaultextension=".png",
            initialdir=OUTPUT_DIR,
            initialfile=f"minimax_{stamp}.png",
            filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg")],
        )
        if not path:
            return
        try:
            if path.lower().endswith((".jpg", ".jpeg")):
                image = Image.open(io.BytesIO(self.result.image_bytes)).convert("RGB")
                image.save(path, "JPEG", quality=95)
            else:
                with open(path, "wb") as fh:
                    fh.write(self.result.image_bytes)
            self._append_log("ok", f"Kaydedildi: {path}")
        except Exception as exc:
            messagebox.showerror("Kaydetme hatası", str(exc))

    def _open_result(self) -> None:
        if self.result_path and os.path.exists(self.result_path):
            os.startfile(self.result_path)  # type: ignore[attr-defined]

    def _open_folder(self) -> None:
        os.startfile(OUTPUT_DIR)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ #
    #  Gunluk
    # ------------------------------------------------------------------ #

    def _append_log(self, level: str, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{stamp} ", "time")
        self.log_text.insert("end", f"{message}\n", level)
        # Cok uzamasin
        if int(self.log_text.index("end-1c").split(".")[0]) > 600:
            self.log_text.delete("1.0", "120.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    @staticmethod
    def _set_text(widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value or "")
        widget.configure(state="disabled")

    # ------------------------------------------------------------------ #

    def _back_to_launcher(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno("Space seç", "Üretim sürüyor. Yine de menüye dönmek istiyor musunuz?"):
                return
        self._save_settings()
        # Launcher uzerinden acildiyk sadece kapanir; launcher geri gelecek.
        # Dogrudan acildiyk yeni launcher baslat.
        if not os.environ.get("HF_STUDIO_LAUNCHER_ACTIVE"):
            try:
                subprocess.Popen([sys.executable, os.path.join(APP_DIR, "launcher.py")])
            except OSError:
                pass
        self.destroy()

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
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
