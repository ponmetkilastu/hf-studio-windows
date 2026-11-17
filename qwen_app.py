"""Qwen Image 2.1 Realtime — Windows masaustu arayuzu (gorsel uretme / duzenleme).

Calistirma:
    python qwen_app.py          (veya baslat.bat -> Space listesi)

Gereksinimler:
    pip install requests pillow

Bir veya daha fazla referans gorsel (opsiyonel, en fazla 10) ve prompt ile
gorsel uretir. Once /prepare (seed + oran), sonra /generate cagrilir.
Her uretim tek proxy IP'si uzerinden gonderilir.
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

from PIL import Image, ImageDraw, ImageOps, ImageTk

import qwen_client as api

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(APP_DIR, "settings_qwen.json")
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


class QwenApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Qwen Image 2.1 · Görsel")
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        width = min(1260, max(900, screen_w - 40))
        height = max(620, min(860, screen_h - 110))
        self.geometry(f"{width}x{height}+20+10")
        self.minsize(900, 600)
        self.configure(bg=BG)
        self._set_icon()

        self.image_paths: list[str] = []
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

        self._append_log("info", "Hazır. İsterseniz referans görsel(ler) ekleyin, prompt yazın ve ÜRET'e basın.")
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
            "prompt": self.prompt_text.get("1.0", "end").strip(),
            "seed": self.seed_var.get(),
            "randomize": bool(self.randomize_var.get()),
            "enhance": bool(self.enhance_var.get()),
            "aspect": self.aspect_var.get(),
            "resolution": self.resolution_var.get(),
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
        tk.Label(title, text="Qwen 2.1", bg=PANEL, fg=ACCENT, font=(FONT, 22, "bold")).pack(side="left")
        tk.Label(title, text=" · Görsel", bg=PANEL, fg=FG, font=(FONT, 22)).pack(side="left")
        tk.Label(title, text="  ·  metinden görsel / görsel düzenleme",
                 bg=PANEL, fg=MUTED, font=(FONT, 10)).pack(side="left", pady=(8, 0))
        right = tk.Frame(header, bg=PANEL)
        right.grid(row=0, column=1, sticky="e", padx=22)
        tk.Label(right, text="linoyts / qwen-image-2-1-realtime", bg=PANEL, fg=MUTED,
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

        # Sol kolon: kaydirilabilir ayarlar + sabit uretim butonu.
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
        left_canvas.bind("<Configure>", lambda e: left_canvas.itemconfig(self._left_window, width=e.width))
        self._build_left(left)
        self._bind_mousewheel(left, left_canvas)

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
        # Referans gorseller
        img_card = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        img_card.pack(fill="x")
        ih = tk.Frame(img_card, bg=CARD)
        ih.pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(ih, text="REFERANS GÖRSELLER (isteğe bağlı)", bg=CARD, fg=FG,
                 font=(FONT, 8, "bold")).pack(side="left")
        self._btn(ih, "Ekle", self._add_image, small=True).pack(side="right")
        self._btn(ih, "Temizle", self._clear_images, small=True).pack(side="right", padx=(0, 6))
        self.thumb = tk.Canvas(img_card, bg="#0a0c10", height=96, highlightthickness=0)
        self.thumb.pack(fill="x", padx=12, pady=(8, 6))
        self.thumb.bind("<Configure>", lambda _e: self._draw_thumb())
        self.image_label = tk.Label(img_card, text="Görsel yok (metinden üretim)",
                                    bg=CARD, fg=MUTED, font=(FONT, 9), anchor="w")
        self.image_label.pack(fill="x", padx=12, pady=(0, 4))
        self.image_list = tk.Listbox(img_card, height=3, bg="#0a0c10", fg=FG,
                                     selectbackground=ACCENT, relief="flat",
                                     highlightthickness=1, highlightbackground=BORDER,
                                     font=(FONT, 8))
        self.image_list.pack(fill="x", padx=12, pady=(0, 4))
        self._btn(img_card, "Seçiliyi kaldır", self._remove_image, small=True).pack(
            anchor="e", padx=12, pady=(0, 10))

        # Prompt
        pc = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        pc.pack(fill="x", pady=(10, 0))
        tk.Label(pc, text="PROMPT", bg=CARD, fg=FG, font=(FONT, 8, "bold")).pack(anchor="w", padx=12, pady=(10, 0))
        self.prompt_text = self._textbox(pc, 3, self.settings.get("prompt", api.DEFAULT_PROMPT))
        self.prompt_text.bind("<Control-Return>", lambda _e: (self._start_generate(), "break")[1])

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
        self.seed_var = tk.StringVar(value=str(s.get("seed", "0")))
        self.randomize_var = tk.BooleanVar(value=bool(s.get("randomize", True)))
        self.enhance_var = tk.BooleanVar(value=bool(s.get("enhance", False)))
        self.aspect_var = tk.StringVar(value=s.get("aspect", "Auto"))
        if self.aspect_var.get() not in api.ASPECT_RATIOS:
            self.aspect_var.set("Auto")
        self.resolution_var = tk.StringVar(value=str(s.get("resolution", 1024)))

        lbl("Oran", 0, 0); combo(self.aspect_var, api.ASPECT_RATIOS, 0, 1)
        lbl("Çözünürlük", 0, 2)
        combo(self.resolution_var, [str(r) for r in api.RESOLUTIONS], 0, 3, (0, 12))
        lbl("Seed", 1, 0)
        seed_row = tk.Frame(opts, bg=CARD)
        seed_row.grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=2)
        seed_row.columnconfigure(0, weight=1)
        self.seed_entry = tk.Entry(seed_row, textvariable=self.seed_var, bg=CARD2, fg=FG,
                                   insertbackground=FG, relief="flat", highlightthickness=1,
                                   highlightbackground=BORDER, font=(FONT, 9))
        self.seed_entry.grid(row=0, column=0, sticky="ew", ipady=2)
        self._btn(seed_row, "🎲", self._random_seed, small=True).grid(row=0, column=1, padx=(6, 0))
        tk.Checkbutton(opts, text="rastgele seed", variable=self.randomize_var,
                       command=self._sync_seed_state, bg=CARD, fg=FG, selectcolor=CARD2,
                       activebackground=CARD, font=(FONT, 8)).grid(row=1, column=2, columnspan=2, sticky="w", padx=(0, 12))
        tk.Checkbutton(opts, text="prompt'u zenginleştir (yavaş)", variable=self.enhance_var,
                       bg=CARD, fg=FG, selectcolor=CARD2, activebackground=CARD,
                       font=(FONT, 8)).grid(row=2, column=0, columnspan=4, sticky="w", padx=(12, 0), pady=2)

        ch = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        ch.pack(fill="x", pady=(10, 0))
        self.optimize_var = tk.BooleanVar(value=bool(s.get("optimize", True)))
        self.use_proxy_var = tk.BooleanVar(value=bool(s.get("use_proxy", True)) and self.pool is not None)
        tk.Checkbutton(ch, text="görselleri optimize et", variable=self.optimize_var, bg=CARD,
                       fg=FG, selectcolor=CARD2, activebackground=CARD, font=(FONT, 9)).pack(anchor="w", padx=12, pady=(8, 2))
        tk.Checkbutton(ch, text="her üretimde farklı proxy", variable=self.use_proxy_var,
                       bg=CARD, fg=FG, selectcolor=CARD2, activebackground=CARD,
                       font=(FONT, 9)).pack(anchor="w", padx=12, pady=(2, 8))

        # Not: uretim butonu _build() icinde sabit alt cubukta olusturulur.

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
        self.save_btn = self._btn(btns, "💾  Kaydet", self._save_result)
        self.save_btn.pack(side="left", padx=(0, 8))
        self.open_btn = self._btn(btns, "Aç", self._open_result)
        self.open_btn.pack(side="left", padx=(0, 8))
        self.folder_btn = self._btn(btns, "Klasör", self._open_folder)
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

    def _add_image(self) -> None:
        files = filedialog.askopenfilenames(
            title="Referans görseller (en fazla 10)",
            filetypes=[("Görseller", "*.png *.jpg *.jpeg *.webp"), ("Tümü", "*.*")],
        )
        for p in files:
            if len(self.image_paths) >= api.MAX_IMAGES:
                self._append_log("warn", f"En fazla {api.MAX_IMAGES} görsel eklenebilir.")
                break
            if p not in self.image_paths:
                self.image_paths.append(p)
                self.image_list.insert("end", os.path.basename(p))
        self._refresh_image_label()

    def _remove_image(self) -> None:
        sel = list(self.image_list.curselection())
        for idx in reversed(sel):
            self.image_list.delete(idx)
            if idx < len(self.image_paths):
                self.image_paths.pop(idx)
        self._refresh_image_label()

    def _clear_images(self) -> None:
        self.image_paths.clear()
        self.image_list.delete(0, "end")
        self._refresh_image_label()

    def _refresh_image_label(self) -> None:
        n = len(self.image_paths)
        self.image_label.configure(text=f"{n} görsel" if n else "Görsel yok (metinden üretim)",
                                   fg=FG if n else MUTED)
        self._draw_thumb()

    def _fit_photo(self, canvas: tk.Canvas, path: Optional[str]) -> None:
        canvas.delete("all")
        if not path or not os.path.exists(path):
            return
        try:
            with Image.open(path) as im:
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
        self._fit_photo(self.thumb, self.image_paths[0] if self.image_paths else None)

    def _draw_stage(self) -> None:
        if self.result and self.result_path and os.path.exists(self.result_path):
            self._fit_photo(self.stage_canvas, self.result_path)
        else:
            self.stage_canvas.delete("all")

    def _sync_seed_state(self) -> None:
        self.seed_entry.configure(state="disabled" if self.randomize_var.get() else "normal")

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

    def _start_generate(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        prompt = self.prompt_text.get("1.0", "end").strip()
        if not prompt:
            messagebox.showwarning("Prompt", "Ne üretmek istediğinizi yazın.")
            return
        try:
            seed = random.randint(0, 2_147_483_647) if self.randomize_var.get() \
                else int(self.seed_var.get().strip() or "0")
            resolution = int(self.resolution_var.get())
            if resolution not in api.RESOLUTIONS:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Ayar", "Seed tam sayı, çözünürlük 512/1024/1536 olmalı.")
            return

        use_proxy = bool(self.use_proxy_var.get()) and self.pool is not None
        self._save_settings()
        self._set_busy(True)
        self.status_var.set("İstek hazırlanıyor…")
        self.save_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self._append_log("info", f"Üretim başlatıldı · {resolution}px · {self.aspect_var.get()} · "
                                 f"{len(self.image_paths)} görsel · seed="
                                 f"{'rastgele' if self.randomize_var.get() else seed}")

        # NOT: args gerçek bir tuple olmalı — sondaki virgül zorunlu (krea hatası tekrarlanmasın).
        self.worker = threading.Thread(
            target=self._thread_entry,
            args=(dict(
                prompt=prompt,
                image_paths=list(self.image_paths),
                seed=seed,
                randomize_seed=bool(self.randomize_var.get()),
                enhance=bool(self.enhance_var.get()),
                aspect_ratio=self.aspect_var.get(),
                resolution=resolution,
                optimize_images=bool(self.optimize_var.get()),
                use_proxy=use_proxy,
            ),),
            daemon=True,
        )
        self.worker.start()

    def _thread_entry(self, kw: dict) -> None:
        """Thread girisindeki hata bile arayuze event olarak ulassın; sessiz kilitlenme olmasın."""
        try:
            self._run_job(kw)
        except Exception as exc:
            self.events.put(("error", str(exc)))
            self.events.put(("done", None))

    def _run_job(self, kw: dict) -> None:
        def log(level: str, msg: str) -> None:
            self.events.put(("log", level, msg))
        try:
            use_proxy = kw.pop("use_proxy")
            client = api.QwenClient(proxy_pool=self.pool if use_proxy else None, on_log=log)
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
        path = os.path.join(OUTPUT_DIR, f"qwen_{stamp}.png")
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
        info = f"{result.size_kb:.0f} KB · seed {result.seed} · {result.resolution}px · {result.aspect_ratio} · {result.elapsed:.0f} sn"
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

    # -- kaydetme / gezinme ----------------------------------------------- #

    def _save_result(self) -> None:
        if not self.result:
            return
        path = filedialog.asksaveasfilename(title="PNG kaydet", defaultextension=".png",
                                            initialfile=os.path.basename(self.result_path or "qwen.png"),
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
    QwenApp().mainloop()


if __name__ == "__main__":
    main()
