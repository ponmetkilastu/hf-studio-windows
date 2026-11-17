"""Krea 2 Turbo — Windows masaustu arayuzu (gorsel uretme / gorsel duzenleme).

Calistirma:
    python krea_app.py          (veya baslat.bat -> Space listesi)

Gereksinimler:
    pip install requests pillow

Bir gorsel (edit modu / referans) ve prompt ile gorsel uretir. Her uretim tek bir
proxy IP'si uzerinden gonderilir; yeni uretimde listeden farkli bir IP alinir.
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
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from PIL import Image, ImageDraw, ImageTk

import krea_client as api

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(APP_DIR, "settings_krea.json")
OUTPUT_DIR = os.path.join(APP_DIR, "outputs")

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

FONT = "Segoe UI"
MONO = "Consolas"


class KreaApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Krea 2 Turbo · Görsel")
        # Ekrana sigdır: kisa ekranlarda (1366x768 vb.) pencere taskbar'in altina tasmaz.
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        width = min(1260, max(900, screen_w - 40))
        height = max(620, min(860, screen_h - 110))
        self.geometry(f"{width}x{height}+20+10")
        self.minsize(900, 600)
        self.configure(bg=BG)
        self._set_icon()

        self.photo_path: Optional[str] = None
        self.second_path: Optional[str] = None
        self._thumb_ref = None
        self._result_ref = None
        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self.result: Optional[api.ImageResult] = None
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

        self._append_log("info", "Hazır. Görsel seçin (edit modu), prompt yazın ve ÜRET'e basın.")
        if self.proxy_file:
            self._append_log("info", f"Proxy dosyası: {os.path.basename(self.proxy_file)} · {len(self.pool)} IP")
        else:
            self._append_log("warn", "Proxy dosyası bulunamadı; doğrudan bağlantı kullanılacak.")

    # -- kurulum ---------------------------------------------------------- #

    def _set_icon(self) -> None:
        try:
            img = Image.new("RGB", (64, 64), (18, 20, 27))
            draw = ImageDraw.Draw(img)
            for y in range(64):
                t = y / 63
                draw.line([(0, y), (64, y)], fill=(int(124 + (49 - 124) * t),
                          int(92 + (200 - 92) * t), 255))
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
            "mode": self.mode_var.get(),
            "prompt": self.prompt_text.get("1.0", "end").strip(),
            "edit": self.edit_text.get("1.0", "end").strip(),
            "width": self.width_var.get(), "height": self.height_var.get(),
            "megapixels": self.mp_var.get(), "grounding": self.ground_var.get(),
            "strength1": self.str1_var.get(), "strength2": self.str2_var.get(),
            "steps": self.steps_var.get(), "cfg": self.cfg_var.get(),
            "sampler": self.sampler_var.get(), "scheduler": self.scheduler_var.get(),
            "seed": self.seed_var.get(), "randomize": bool(self.randomize_var.get()),
            "checkpoint": self.ckpt_var.get(), "gpu_budget": self.gpu_var.get(),
            "optimize": bool(self.optimize_var.get()),
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
        style.configure("TCombobox", fieldbackground=CARD, background=CARD2,
                        foreground=FG, arrowcolor=MUTED, bordercolor=BORDER,
                        lightcolor=CARD, darkcolor=CARD)
        style.map("TCombobox", fieldbackground=[("readonly", CARD)],
                  foreground=[("readonly", FG)])
        style.configure("TProgressbar", troughcolor=CARD, background=ACCENT,
                        bordercolor=CARD, lightcolor=ACCENT, darkcolor=ACCENT)
        style.configure("TScrollbar", background=CARD2, troughcolor=BG,
                        bordercolor=BG, arrowcolor=MUTED)

    # -- arayuz ----------------------------------------------------------- #

    def _build(self) -> None:
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        header = tk.Frame(self, bg=PANEL, height=74)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.columnconfigure(0, weight=1)
        title = tk.Frame(header, bg=PANEL)
        title.grid(row=0, column=0, sticky="w", padx=22, pady=12)
        tk.Label(title, text="Krea 2", bg=PANEL, fg=ACCENT, font=(FONT, 22, "bold")).pack(side="left")
        tk.Label(title, text=" · Görsel", bg=PANEL, fg=FG, font=(FONT, 22)).pack(side="left")
        tk.Label(title, text="  ·  metinden görsel / görsel düzenleme",
                 bg=PANEL, fg=MUTED, font=(FONT, 10)).pack(side="left", pady=(8, 0))
        right = tk.Frame(header, bg=PANEL)
        right.grid(row=0, column=1, sticky="e", padx=22)
        tk.Label(right, text="Intruzo / Krea-2-Turbo_v2", bg=PANEL, fg=MUTED,
                 font=(FONT, 9)).pack(side="left", padx=(0, 12))
        self._btn(right, "⌂  Space seç", self._back_to_launcher, small=True).pack(side="left")

        bar = tk.Canvas(self, height=3, bg=BG, highlightthickness=0)
        bar.grid(row=0, column=0, sticky="sew")
        self._gradient_bar = bar
        bar.bind("<Configure>", self._draw_gradient)

        body = tk.Frame(self, bg=BG)
        body.grid(row=1, column=0, sticky="nsew", padx=16, pady=(12, 8))
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=0, minsize=450)
        body.columnconfigure(1, weight=1)

        # Sol kolon: ustte kaydirilabilir ayarlar, altta SABIT uretim butonu.
        # Boylece 41 parametre ekrana sigmasa da "GÖRSEL ÜRET" her zaman gorunur.
        left_col = tk.Frame(body, bg=BG, width=450)
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        left_col.grid_propagate(False)
        left_col.rowconfigure(0, weight=1)
        left_col.columnconfigure(0, weight=1)

        left_outer = tk.Frame(left_col, bg=BG)
        left_outer.grid(row=0, column=0, sticky="nsew")
        left_outer.rowconfigure(0, weight=1)
        left_outer.columnconfigure(0, weight=1)

        left_canvas = tk.Canvas(left_outer, bg=BG, highlightthickness=0, bd=0)
        left_canvas.grid(row=0, column=0, sticky="nsew")
        left_scroll = ttk.Scrollbar(left_outer, orient="vertical", command=left_canvas.yview)
        left_scroll.grid(row=0, column=1, sticky="ns")
        left_canvas.configure(yscrollcommand=left_scroll.set)

        left = tk.Frame(left_canvas, bg=BG)
        self._left_window = left_canvas.create_window((0, 0), window=left, anchor="nw")
        left.bind("<Configure>", lambda _e: left_canvas.configure(scrollregion=left_canvas.bbox("all")))
        left_canvas.bind(
            "<Configure>",
            lambda e: left_canvas.itemconfig(self._left_window, width=e.width),
        )
        self._build_left(left)
        self._bind_mousewheel(left, left_canvas)

        # Sabit alt uretim cubugu (kaydirmadan etkilenmez).
        footer = tk.Frame(left_col, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        footer.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.gen_btn = tk.Button(footer, text="▶   GÖRSEL ÜRET", command=self._start_generate,
                                 bg=ACCENT, fg="white", activebackground="#6a4ce0",
                                 activeforeground="white", relief="flat", bd=0,
                                 font=(FONT, 11, "bold"), cursor="hand2", pady=8)
        self.gen_btn.pack(fill="x", padx=8, pady=(8, 4))
        self.progress = ttk.Progressbar(footer, mode="indeterminate")
        self.progress.pack(fill="x", padx=8, pady=(0, 8))

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
        tk.Label(status, textvariable=self.status_var, bg=PANEL, fg=MUTED,
                 font=(FONT, 9), anchor="w").grid(row=0, column=0, sticky="w", padx=18, pady=6)
        proxy_text = f"{len(self.pool)} proxy · her üretimde farklı IP" if self.pool else "proxy kapalı"
        tk.Label(status, text=proxy_text, bg=PANEL, fg=MUTED, font=(FONT, 9)).grid(
            row=0, column=1, sticky="e", padx=18)

    def _draw_gradient(self, _e=None) -> None:
        c = self._gradient_bar
        c.delete("all")
        w = max(c.winfo_width(), 1)
        for x in range(0, w, 3):
            t = x / max(w - 1, 1)
            col = (int(124 + (49 - 124) * t), int(92 + (200 - 92) * t), 255)
            c.create_line(x, 1, x + 3, 1, fill=f"#{col[0]:02x}{col[1]:02x}{col[2]:02x}", width=3)

    def _build_left(self, parent: tk.Frame) -> None:
        # Mod + gorsel
        mode_card = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        mode_card.pack(fill="x")
        head = tk.Frame(mode_card, bg=CARD)
        head.pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(head, text="MOD", bg=CARD, fg=FG, font=(FONT, 8, "bold")).pack(side="left")
        self.mode_var = tk.StringVar(value=self.settings.get("mode", "edit"))
        if self.mode_var.get() not in api.MODES:
            self.mode_var.set("edit")
        for m in api.MODES:
            tk.Radiobutton(mode_card, text=m, variable=self.mode_var, value=m, bg=CARD,
                           fg=FG, selectcolor=CARD2, activebackground=CARD,
                           font=(FONT, 9), anchor="w").pack(fill="x", padx=12)

        img_card = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        img_card.pack(fill="x", pady=(10, 0))
        ih = tk.Frame(img_card, bg=CARD)
        ih.pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(ih, text="GÖRSEL / REFERANS", bg=CARD, fg=FG, font=(FONT, 8, "bold")).pack(side="left")
        self._btn(ih, "Seç", self._pick_photo, small=True).pack(side="right")
        self._btn(ih, "Kaldır", self._clear_photo, small=True).pack(side="right", padx=(0, 6))
        self.thumb = tk.Canvas(img_card, bg="#0a0c10", height=96, highlightthickness=0)
        self.thumb.pack(fill="x", padx=12, pady=(8, 6))
        self.thumb.bind("<Configure>", lambda _e: self._draw_thumb())
        self.photo_label = tk.Label(img_card, text="Henüz görsel yok", bg=CARD, fg=MUTED,
                                    font=(FONT, 9), anchor="w")
        self.photo_label.pack(fill="x", padx=12, pady=(0, 4))
        sr = tk.Frame(img_card, bg=CARD)
        sr.pack(fill="x", padx=12, pady=(0, 10))
        tk.Label(sr, text="2. referans", bg=CARD, fg=MUTED, font=(FONT, 8)).pack(side="left")
        self._btn(sr, "Kaldır", self._clear_second, small=True).pack(side="right")
        self._btn(sr, "Seç", self._pick_second, small=True).pack(side="right", padx=(0, 6))
        self.second_label = tk.Label(sr, text="(opsiyonel · yok)", bg=CARD, fg=MUTED,
                                     font=(FONT, 8), anchor="e")
        self.second_label.pack(side="right", padx=(0, 8), fill="x", expand=True)

        # Prompt + edit instruction
        pc = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        pc.pack(fill="x", pady=(10, 0))
        tk.Label(pc, text="PROMPT", bg=CARD, fg=FG, font=(FONT, 8, "bold")).pack(anchor="w", padx=12, pady=(10, 0))
        self.prompt_text = self._textbox(pc, 2, self.settings.get("prompt", api.DEFAULT_PROMPT))
        self.prompt_text.bind("<Control-Return>", lambda _e: (self._start_generate(), "break")[1])
        tk.Label(pc, text="DÜZENLEME TALİMATI (edit)", bg=CARD, fg=FG, font=(FONT, 8, "bold")).pack(
            anchor="w", padx=12, pady=(4, 0))
        self.edit_text = self._textbox(pc, 2, self.settings.get("edit", ""))

        # Secenekler
        opts = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        opts.pack(fill="x", pady=(10, 0))
        for c in (1, 3):
            opts.columnconfigure(c, weight=1)

        def lbl(text, r, c):
            tk.Label(opts, text=text, bg=CARD, fg=MUTED, font=(FONT, 8)).grid(
                row=r, column=c, sticky="w", padx=(12, 6), pady=2)

        def entry(var, r, c, padx=(0, 10)):
            tk.Entry(opts, textvariable=var, bg=CARD2, fg=FG, insertbackground=FG,
                     relief="flat", highlightthickness=1, highlightbackground=BORDER,
                     font=(FONT, 9)).grid(row=r, column=c, sticky="ew", padx=padx, pady=2, ipady=2)

        def combo(var, values, r, c, padx=(0, 10)):
            ttk.Combobox(opts, textvariable=var, values=values, state="readonly").grid(
                row=r, column=c, sticky="ew", padx=padx, pady=2)

        s = self.settings
        self.width_var = tk.StringVar(value=str(s.get("width", 1024)))
        self.height_var = tk.StringVar(value=str(s.get("height", 1024)))
        self.mp_var = tk.StringVar(value=str(s.get("megapixels", 1.4)))
        self.ground_var = tk.StringVar(value=str(s.get("grounding", 768)))
        self.str1_var = tk.StringVar(value=str(s.get("strength1", 1.0)))
        self.str2_var = tk.StringVar(value=str(s.get("strength2", 1.0)))
        self.steps_var = tk.StringVar(value=str(s.get("steps", 8)))
        self.cfg_var = tk.StringVar(value=str(s.get("cfg", 1.0)))
        self.sampler_var = tk.StringVar(value=s.get("sampler", "euler"))
        self.scheduler_var = tk.StringVar(value=s.get("scheduler", "beta"))
        self.seed_var = tk.StringVar(value=str(s.get("seed", "2")))
        self.randomize_var = tk.BooleanVar(value=bool(s.get("randomize", False)))
        self.ckpt_var = tk.StringVar(value=s.get("checkpoint", api.DEFAULT_CHECKPOINT))
        self.gpu_var = tk.StringVar(value=str(s.get("gpu_budget", 0)))

        lbl("Genişlik", 0, 0); entry(self.width_var, 0, 1)
        lbl("Yükseklik", 0, 2); entry(self.height_var, 0, 3, (0, 12))
        lbl("Megapiksel", 1, 0); entry(self.mp_var, 1, 1)
        lbl("Grounding", 1, 2); entry(self.ground_var, 1, 3, (0, 12))
        lbl("Ref. güç 1", 2, 0); entry(self.str1_var, 2, 1)
        lbl("Ref. güç 2", 2, 2); entry(self.str2_var, 2, 3, (0, 12))
        lbl("Adım", 3, 0); entry(self.steps_var, 3, 1)
        lbl("CFG", 3, 2); entry(self.cfg_var, 3, 3, (0, 12))
        lbl("Sampler", 4, 0); combo(self.sampler_var, api.SAMPLERS, 4, 1)
        lbl("Scheduler", 4, 2); combo(self.scheduler_var, api.SCHEDULERS, 4, 3, (0, 12))
        lbl("Checkpoint", 5, 0)
        combo(self.ckpt_var, [c for c in api.CHECKPOINTS if c != "__custom_huggingface_base_model__"], 5, 1, (0, 10))
        lbl("Seed", 6, 0)
        seed_row = tk.Frame(opts, bg=CARD)
        seed_row.grid(row=6, column=1, sticky="ew", padx=(0, 10), pady=4)
        seed_row.columnconfigure(0, weight=1)
        self.seed_entry = tk.Entry(seed_row, textvariable=self.seed_var, bg=CARD2, fg=FG,
                                   insertbackground=FG, relief="flat", highlightthickness=1,
                                   highlightbackground=BORDER, font=(FONT, 9))
        self.seed_entry.grid(row=0, column=0, sticky="ew", ipady=2)
        self._btn(seed_row, "🎲", self._random_seed, small=True).grid(row=0, column=1, padx=(6, 0))
        tk.Checkbutton(opts, text="rastgele seed", variable=self.randomize_var,
                       command=self._sync_seed_state, bg=CARD, fg=FG, selectcolor=CARD2,
                       activebackground=CARD, font=(FONT, 8)).grid(row=6, column=2, columnspan=2, sticky="w", padx=(0, 12))
        lbl("GPU bütçe", 7, 0); entry(self.gpu_var, 7, 1)

        ch = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        ch.pack(fill="x", pady=(10, 0))
        self.optimize_var = tk.BooleanVar(value=bool(s.get("optimize", True)))
        self.use_proxy_var = tk.BooleanVar(value=bool(s.get("use_proxy", True)) and self.pool is not None)
        tk.Checkbutton(ch, text="görselleri optimize et", variable=self.optimize_var, bg=CARD,
                       fg=FG, selectcolor=CARD2, activebackground=CARD, font=(FONT, 9)).pack(anchor="w", padx=12, pady=(8, 2))
        tk.Checkbutton(ch, text="her üretimde farklı proxy", variable=self.use_proxy_var,
                       bg=CARD, fg=FG, selectcolor=CARD2, activebackground=CARD,
                       font=(FONT, 9)).pack(anchor="w", padx=12, pady=(2, 8))

        # Not: "GÖRSEL ÜRET" butonu _build() icinde sabit alt cubukta olusturulur;
        # burada tekrar olusturulmaz (ayarlar kaydirilabilir alanda kaldigi icin).

    def _build_right(self, parent: tk.Frame) -> None:
        stage = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        stage.pack(fill="both", expand=True)
        sh = tk.Frame(stage, bg=CARD)
        sh.pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(sh, text="SONUÇ", bg=CARD, fg=FG, font=(FONT, 8, "bold")).pack(side="left")
        self.info_var = tk.StringVar(value="Henüz üretim yok")
        tk.Label(sh, textvariable=self.info_var, bg=CARD, fg=MUTED, font=(MONO, 8)).pack(side="right")
        self.stage_canvas = tk.Canvas(stage, bg="#0a0c10", highlightthickness=0)
        self.stage_canvas.pack(fill="both", expand=True, padx=12, pady=(8, 8))
        self.stage_canvas.bind("<Configure>", lambda _e: self._draw_stage())

        btns = tk.Frame(parent, bg=BG)
        btns.pack(fill="x", pady=(10, 0))
        self.save_btn = self._btn(btns, "💾  Kaydet", self._save_result, small=False)
        self.save_btn.pack(side="left", padx=(0, 8))
        self.open_btn = self._btn(btns, "Aç", self._open_result, small=False)
        self.open_btn.pack(side="left", padx=(0, 8))
        self.folder_btn = self._btn(btns, "Klasör", self._open_folder, small=False)
        self.folder_btn.pack(side="left")

        logc = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        logc.pack(fill="x", pady=(10, 0))
        tk.Label(logc, text="GÜNLÜK", bg=CARD, fg=FG, font=(FONT, 8, "bold")).pack(anchor="w", padx=12, pady=(8, 2))
        self.log_text = tk.Text(logc, height=9, wrap="word", bg="#0a0c10", fg=FG,
                                relief="flat", highlightthickness=0, font=(MONO, 8), padx=8, pady=6)
        self.log_text.pack(fill="x", padx=8, pady=(0, 8))
        for tag, color in (("time", MUTED), ("info", FG), ("status", ACCENT2),
                           ("ok", OK), ("warn", WARN), ("error", ERR), ("proxy", "#6fb8ff")):
            self.log_text.tag_configure(tag, foreground=color)

    # -- yardimcilar ------------------------------------------------------ #

    def _textbox(self, parent, height: int, initial: str) -> tk.Text:
        box = tk.Text(parent, height=height, wrap="word", bg="#0a0c10", fg=FG,
                      insertbackground=FG, relief="flat", highlightthickness=1,
                      highlightbackground=BORDER, highlightcolor=ACCENT, font=(FONT, 10), padx=8, pady=6)
        box.pack(fill="x", padx=12, pady=(5, 4))
        box.insert("1.0", initial or "")
        return box

    def _btn(self, parent, text, command, small: bool = False) -> tk.Button:
        return tk.Button(parent, text=text, command=command, bg=CARD2, fg=FG,
                         activebackground=BORDER, activeforeground=FG, relief="flat", bd=0,
                         font=(FONT, 8 if small else 9), cursor="hand2",
                         padx=8 if small else 12, pady=3 if small else 6)

    @staticmethod
    def _bind_mousewheel(widget: tk.Misc, canvas: tk.Canvas) -> None:
        """Sol panelin icindeki tum widget'larda fare tekerlegiyle kaydirma saglar."""

        def scroll(event) -> None:
            if event.delta:
                canvas.yview_scroll(-int(event.delta / 120), "units")
            elif event.num == 4:
                canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                canvas.yview_scroll(1, "units")

        def apply(w: tk.Misc) -> None:
            w.bind("<MouseWheel>", scroll)
            w.bind("<Button-4>", scroll)
            w.bind("<Button-5>", scroll)
            for child in w.winfo_children():
                apply(child)

        apply(widget)

    def _pick_photo(self) -> None:
        p = filedialog.askopenfilename(title="Görsel seç",
                                       filetypes=[("Görseller", "*.png *.jpg *.jpeg *.webp"), ("Tümü", "*.*")])
        if p:
            self.photo_path = p
            self.photo_label.configure(text=os.path.basename(p), fg=FG)
            self._draw_thumb()

    def _clear_photo(self) -> None:
        self.photo_path = None
        self.photo_label.configure(text="Henüz görsel yok", fg=MUTED)
        self._draw_thumb()

    def _pick_second(self) -> None:
        p = filedialog.askopenfilename(title="İkinci referans",
                                       filetypes=[("Görseller", "*.png *.jpg *.jpeg *.webp"), ("Tümü", "*.*")])
        if p:
            self.second_path = p
            self.second_label.configure(text=os.path.basename(p), fg=FG)

    def _clear_second(self) -> None:
        self.second_path = None
        self.second_label.configure(text="(opsiyonel · yok)", fg=MUTED)

    def _fit_photo(self, canvas: tk.Canvas, path: Optional[str]) -> None:
        canvas.delete("all")
        if not path or not os.path.exists(path):
            return
        try:
            with Image.open(path) as im:
                from PIL import ImageOps
                im = ImageOps.exif_transpose(im).convert("RGB")
                cw, ch = canvas.winfo_width(), canvas.winfo_height()
                if cw < 10 or ch < 10:
                    return
                im.thumbnail((cw - 16, ch - 16), Image.LANCZOS)
                photo = ImageTk.PhotoImage(im)
                canvas.create_image(cw // 2, ch // 2, image=photo)
                if canvas is self.thumb:
                    self._thumb_ref = photo
                else:
                    self._result_ref = photo
        except Exception:
            pass

    def _draw_thumb(self) -> None:
        self._fit_photo(self.thumb, self.photo_path)

    def _draw_stage(self) -> None:
        if self.result and self.result_path and os.path.exists(self.result_path):
            self._fit_photo(self.stage_canvas, self.result_path)
        else:
            self.stage_canvas.delete("all")

    def _sync_seed_state(self) -> None:
        if self.randomize_var.get():
            self.seed_entry.configure(state="disabled")
        else:
            self.seed_entry.configure(state="normal")

    def _random_seed(self) -> None:
        self.randomize_var.set(False)
        self.seed_var.set(str(random.randint(0, 2_147_483_647)))
        self._sync_seed_state()
        self._append_log("info", "Seed elle girildi (rastgele kapatıldı)")

    # -- uretim ----------------------------------------------------------- #

    def _set_busy(self, busy: bool) -> None:
        if busy:
            self.gen_btn.configure(state="disabled", text="⏳   ÜRETİLİYOR…", bg="#4a3020")
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.configure(value=0)
            self.gen_btn.configure(state="normal", text="▶   GÖRSEL ÜRET", bg=ACCENT)
        self._sync_seed_state()

    def _num(self, var: tk.StringVar, name: str, lo: float, hi: float, integer: bool = False):
        raw = var.get().strip().replace(",", ".")
        val = float(raw)
        if not lo <= val <= hi:
            raise ValueError(f"{name} {lo}-{hi} aralığında olmalı")
        return int(val) if integer else val

    def _start_generate(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        mode = self.mode_var.get()
        prompt = self.prompt_text.get("1.0", "end").strip()
        edit = self.edit_text.get("1.0", "end").strip()
        if not prompt and not edit:
            messagebox.showwarning("Prompt", "Prompt veya düzenleme talimatı yazın.")
            return
        if mode == "edit" and not self.photo_path:
            messagebox.showwarning("Görsel", "Edit modu için bir görsel seçin.")
            return
        try:
            width = self._num(self.width_var, "Genişlik", 512, 2048, True)
            height = self._num(self.height_var, "Yükseklik", 512, 2048, True)
            mp = self._num(self.mp_var, "Megapiksel", 0.25, 4.0)
            ground = self._num(self.ground_var, "Grounding", 384, 1536, True)
            str1 = self._num(self.str1_var, "Ref. güç 1", 0.0, 12.0)
            str2 = self._num(self.str2_var, "Ref. güç 2", 0.0, 12.0)
            steps = self._num(self.steps_var, "Adım", 4, 40, True)
            cfg = self._num(self.cfg_var, "CFG", 1.0, 5.0)
            gpu = self._num(self.gpu_var, "GPU bütçe", 0, 300, True)
            if self.randomize_var.get():
                seed = random.randint(0, 2_147_483_647)
            else:
                seed = self._num(self.seed_var, "Seed", 0, 2_147_483_647, True)
        except ValueError as exc:
            messagebox.showwarning("Ayar", str(exc))
            return

        use_proxy = bool(self.use_proxy_var.get()) and self.pool is not None
        self._save_settings()
        self._set_busy(True)
        self.status_var.set("İstek hazırlanıyor…")
        self.save_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self._append_log("info", f"Üretim başlatıldı · mod={mode} · {width}x{height} · "
                                 f"adım={steps} · seed={'rastgele' if self.randomize_var.get() else seed}")

        self.worker = threading.Thread(
            target=self._thread_entry,
            args=(dict(
                image_path=self.photo_path, second_image_path=self.second_path,
                prompt=prompt, mode=mode, edit_instruction=edit,
                width=width, height=height, megapixels=mp, grounding=ground,
                strength1=str1, strength2=str2, steps=steps, cfg=cfg,
                sampler=self.sampler_var.get(), scheduler=self.scheduler_var.get(),
                seed=seed, randomize=bool(self.randomize_var.get()),
                gpu_budget=gpu, checkpoint=self.ckpt_var.get(),
                optimize_image=bool(self.optimize_var.get()),
                use_proxy=use_proxy,
            ),),   # NOT: virgül zorunlu — yoksa dict, Thread args'ina iterative edilir
            daemon=True,
        )
        self.worker.start()

    def _thread_entry(self, kw: dict) -> None:
        """Thread girisindeki bir hata bile arayuze event olarak ulassın; sessiz kilitlenme olmasın."""
        try:
            self._run_job(kw)
        except Exception as exc:  # _run_job'a girmeden once patlayan hatalar icin
            self.events.put(("error", str(exc)))
            self.events.put(("done", None))

    def _run_job(self, kw: dict) -> None:
        def log(level: str, msg: str) -> None:
            self.events.put(("log", level, msg))
        try:
            use_proxy = kw.pop("use_proxy")
            client = api.KreaClient(proxy_pool=self.pool if use_proxy else None, on_log=log)
            result = client.generate(**kw)
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

    def _on_result(self, result: api.ImageResult) -> None:
        self.result = result
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(OUTPUT_DIR, f"krea_{stamp}.png")
        try:
            with open(path, "wb") as fh:
                fh.write(result.image_bytes)
            self.result_path = path
        except OSError as exc:
            self._append_log("warn", f"Sonuç otomatik kaydedilemedi: {exc}")
            self.result_path = None
        self._draw_stage()
        self.save_btn.configure(state="normal")
        self.open_btn.configure(state="normal" if self.result_path else "disabled")
        seed_text = result.seed if result.seed is not None else "?"
        info = f"{result.size_kb:.0f} KB · seed {seed_text} · {result.elapsed:.0f} sn"
        if result.status:
            info = f"{result.status[:60]} · " + info
        self.info_var.set(info)
        self.status_var.set("Tamamlandı ✓")
        if result.status:
            self._append_log("info", result.status)
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

    # -- kaydetme / gezinme ----------------------------------------------- #

    def _save_result(self) -> None:
        if not self.result:
            return
        path = filedialog.asksaveasfilename(title="PNG kaydet", defaultextension=".png",
                                            initialfile=os.path.basename(self.result_path or "krea.png"),
                                            initialdir=OUTPUT_DIR,
                                            filetypes=[("PNG görsel", "*.png")])
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
                subprocess.Popen([sys.executable, os.path.join(APP_DIR, "launcher.py")])
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
    KreaApp().mainloop()


if __name__ == "__main__":
    main()
