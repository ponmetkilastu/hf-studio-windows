"""Lightricks LTX-2.5 — Windows arayuzu (metinden / fotograftan video).

Calistirma: python apps/ltx25_app.py  (veya baslat.bat -> Space listesi)
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

import clients.ltx25_client as api

APP_DIR = ROOT_DIR
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "settings_ltx25.json")
OUT_DIR = os.path.join(APP_DIR, "outputs")

BG, PANEL, CARD, CARD2, BORDER = "#0f1115", "#151820", "#1b1f28", "#242a36", "#2b3140"
FG, MUTED, ACCENT, ACCENT2 = "#e9ecf1", "#8b93a1", "#7c5cff", "#31c8ff"
OK, WARN, ERR = "#38d39f", "#ffb020", "#ff5d6c"
FONT, MONO = "Segoe UI", "Consolas"


class LTX25App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("LTX-2.5 · Metinden / fotoğraftan video")
        width = min(1180, max(880, self.winfo_screenwidth() - 40))
        height = max(620, min(840, self.winfo_screenheight() - 110))
        self.geometry(f"{width}x{height}+20+10")
        self.minsize(880, 600)
        self.configure(bg=BG)
        self._set_icon()

        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self.result: Optional[api.VideoResult] = None
        self.result_path: Optional[str] = None
        self.pool: Optional[api.ProxyPool] = None
        self.proxy_file: Optional[str] = None
        self.image_path: Optional[str] = None

        os.makedirs(OUT_DIR, exist_ok=True)
        self.settings = self._load_settings()
        self._init_proxy()
        self._init_style()
        self._build()
        self._set_busy(False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._pump_job = self.after(100, self._pump)

        self._append_log("info", "Hazır. Prompt yazın ve VİDEO ÜRET'e basın (fotoğraf opsiyonel).")
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
            d.polygon([(24, 18), (46, 32), (24, 46)], fill=(255, 255, 255))
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
            "width": self.width_var.get(), "height": self.height_var.get(),
            "duration": self.duration_var.get(), "seed": self.seed_var.get(),
            "decoder": self.decoder_var.get(),
            "auto_len": bool(self.auto_len_var.get()),
            "randomize_seed": bool(self.randomize_var.get()),
            "do_enhance": bool(self.enhance_var.get()),
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
        tk.Label(title, text="LTX", bg=PANEL, fg=ACCENT, font=(FONT, 22, "bold")).pack(side="left")
        tk.Label(title, text=" · 2.5", bg=PANEL, fg=FG, font=(FONT, 22)).pack(side="left")
        tk.Label(title, text="  ·  metinden / fotoğraftan video", bg=PANEL, fg=MUTED,
                 font=(FONT, 10)).pack(side="left", pady=(8, 0))
        right = tk.Frame(header, bg=PANEL)
        right.grid(row=0, column=1, sticky="e", padx=22)
        tk.Label(right, text="Lightricks / LTX-2.5", bg=PANEL, fg=MUTED,
                 font=(FONT, 9)).pack(side="left", padx=(0, 12))
        self._btn(right, "⌂  Space seç", self._back_to_launcher, small=True).pack(side="left")

        body = tk.Frame(self, bg=BG)
        body.grid(row=1, column=0, sticky="nsew", padx=16, pady=(12, 8))
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=0, minsize=420)
        body.columnconfigure(1, weight=1)

        left = tk.Frame(body, bg=BG, width=420)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        left.grid_propagate(False)
        left.rowconfigure(2, weight=1)
        left.columnconfigure(0, weight=1)

        ic = tk.Frame(left, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        ic.grid(row=0, column=0, sticky="ew")
        ih = tk.Frame(ic, bg=CARD)
        ih.pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(ih, text="KAYNAK FOTOĞRAF (OPSİYONEL)", bg=CARD, fg=FG,
                 font=(FONT, 8, "bold")).pack(side="left")
        self._btn(ih, "Seç", self._choose_image, small=True).pack(side="right")
        self._btn(ih, "Kaldır", self._clear_image, small=True).pack(side="right", padx=(0, 6))
        self.thumb = tk.Canvas(ic, bg="#0a0c10", height=96, highlightthickness=0)
        self.thumb.pack(fill="x", padx=12, pady=8)
        self.thumb.bind("<Configure>", lambda _e: self._draw_thumb())
        self.image_label = tk.Label(ic, text="Fotoğraf yok · metinden video üretilecek",
                                    bg=CARD, fg=MUTED, font=(FONT, 8), anchor="w")
        self.image_label.pack(fill="x", padx=12, pady=(0, 8))

        pc = tk.Frame(left, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        pc.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        tk.Label(pc, text="PROMPT", bg=CARD, fg=FG, font=(FONT, 8, "bold")).pack(
            anchor="w", padx=12, pady=(10, 0))
        self.prompt_text = tk.Text(pc, height=3, wrap="word", bg="#0a0c10", fg=FG,
                                   insertbackground=FG, relief="flat", highlightthickness=1,
                                   highlightbackground=BORDER, font=(FONT, 9), padx=8, pady=6)
        self.prompt_text.pack(fill="x", padx=12, pady=(5, 10))
        self.prompt_text.insert("1.0", self.settings.get("prompt", api.DEFAULT_PROMPT))
        self.prompt_text.bind("<Control-Return>", lambda _e: (self._start(), "break")[1])

        opts = tk.Frame(left, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        opts.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        for c in (1, 3):
            opts.columnconfigure(c, weight=1)
        s = self.settings
        self.width_var = tk.StringVar(value=str(s.get("width", api.DEFAULT_WIDTH)))
        self.height_var = tk.StringVar(value=str(s.get("height", api.DEFAULT_HEIGHT)))
        self.duration_var = tk.StringVar(value=str(s.get("duration", api.DEFAULT_DURATION)))
        self.seed_var = tk.StringVar(value=str(s.get("seed", api.DEFAULT_SEED)))
        self.decoder_var = tk.StringVar(value=str(s.get("decoder", api.DEFAULT_DECODER)))
        self.auto_len_var = tk.BooleanVar(value=bool(s.get("auto_len", False)))
        self.randomize_var = tk.BooleanVar(value=bool(s.get("randomize_seed", True)))
        self.enhance_var = tk.BooleanVar(value=bool(s.get("do_enhance", True)))
        self.use_proxy_var = tk.BooleanVar(value=bool(s.get("use_proxy", True)) and self.pool is not None)

        def lbl(t, r, c):
            tk.Label(opts, text=t, bg=CARD, fg=MUTED, font=(FONT, 8)).grid(
                row=r, column=c, sticky="w", padx=(12, 6), pady=3)

        def ent(v, r, c):
            tk.Entry(opts, textvariable=v, bg=CARD2, fg=FG, insertbackground=FG,
                     relief="flat", highlightthickness=1, highlightbackground=BORDER,
                     font=(FONT, 9)).grid(row=r, column=c, sticky="ew", padx=(0, 10), pady=3, ipady=2)

        lbl("Genişlik (512-1536)", 0, 0); ent(self.width_var, 0, 1)
        lbl("Yükseklik (512-1536)", 0, 2); ent(self.height_var, 0, 3)
        lbl("Süre (sn, 1-5)", 1, 0); ent(self.duration_var, 1, 1)
        lbl("Seed", 1, 2); ent(self.seed_var, 1, 3)
        lbl("Decoder", 2, 0)
        combo = ttk.Combobox(opts, textvariable=self.decoder_var, values=list(api.DECODERS),
                             state="readonly", font=(FONT, 9))
        combo.grid(row=2, column=1, sticky="ew", padx=(0, 10), ipady=1)
        tk.Checkbutton(opts, text="auto length (≤15 sn)", variable=self.auto_len_var,
                       bg=CARD, fg=FG, selectcolor=CARD2, activebackground=CARD,
                       font=(FONT, 8)).grid(row=2, column=2, columnspan=2, sticky="w", pady=2)
        tk.Checkbutton(opts, text="rastgele seed", variable=self.randomize_var,
                       bg=CARD, fg=FG, selectcolor=CARD2, activebackground=CARD,
                       font=(FONT, 8)).grid(row=3, column=0, columnspan=2, sticky="w", padx=12, pady=2)
        tk.Checkbutton(opts, text="prompt geliştir (Gemma-4)", variable=self.enhance_var,
                       bg=CARD, fg=FG, selectcolor=CARD2, activebackground=CARD,
                       font=(FONT, 8)).grid(row=3, column=2, columnspan=2, sticky="w", pady=2)
        tk.Checkbutton(opts, text="her üretimde farklı proxy", variable=self.use_proxy_var,
                       bg=CARD, fg=FG, selectcolor=CARD2, activebackground=CARD,
                       font=(FONT, 8)).grid(row=4, column=0, columnspan=4, sticky="w", padx=12, pady=(2, 8))

        footer = tk.Frame(left, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        footer.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.gen_btn = tk.Button(footer, text="▶   VİDEO ÜRET", command=self._start,
                                 bg=ACCENT, fg="white", activebackground="#6a4ce0",
                                 activeforeground="white", relief="flat", bd=0,
                                 font=(FONT, 11, "bold"), cursor="hand2", pady=8)
        self.gen_btn.pack(fill="x", padx=8, pady=(8, 4))
        self.progress = ttk.Progressbar(footer, mode="indeterminate")
        self.progress.pack(fill="x", padx=8, pady=(0, 8))

        stage = tk.Frame(body, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        stage.grid(row=0, column=1, sticky="nsew")
        stage.rowconfigure(1, weight=1)
        stage.columnconfigure(0, weight=1)
        sh = tk.Frame(stage, bg=CARD)
        sh.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 0))
        tk.Label(sh, text="SONUÇ", bg=CARD, fg=FG, font=(FONT, 8, "bold")).pack(side="left")
        self.info_var = tk.StringVar(value="Henüz üretim yok")
        tk.Label(sh, textvariable=self.info_var, bg=CARD, fg=MUTED,
                 font=(MONO, 8)).pack(side="right")
        self.stage = tk.Label(stage, text="Video burada görünecek\n(üretim sonrası Oynat ile açılır)",
                              bg="#0a0c10", fg=MUTED, font=(FONT, 10), justify="center")
        self.stage.grid(row=1, column=0, sticky="nsew", padx=12, pady=8)

        btns = tk.Frame(body, bg=BG)
        btns.grid(row=1, column=1, sticky="ew", pady=(10, 0))
        self.play_btn = self._btn(btns, "▶ Oynat", self._open_result)
        self.play_btn.pack(side="left", padx=(0, 8))
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

    def _choose_image(self) -> None:
        path = filedialog.askopenfilename(
            title="Kaynak fotoğraf (opsiyonel)",
            filetypes=[("Görseller", "*.png *.jpg *.jpeg *.webp"), ("Tümü", "*.*")])
        if path:
            self.image_path = path
            self.image_label.configure(text=os.path.basename(path), fg=FG)
            self._draw_thumb()

    def _clear_image(self) -> None:
        self.image_path = None
        self.thumb.delete("all")
        self.image_label.configure(text="Fotoğraf yok · metinden video üretilecek", fg=MUTED)

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

    def _set_busy(self, busy: bool) -> None:
        if busy:
            self.gen_btn.configure(state="disabled", text="⏳   ÜRETİLİYOR…", bg="#4a3020")
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.configure(value=0)
            self.gen_btn.configure(state="normal", text="▶   VİDEO ÜRET", bg=ACCENT)

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        image = self.image_path if self.image_path and os.path.exists(self.image_path) else None
        try:
            kw = dict(
                image_path=image,
                prompt=self.prompt_text.get("1.0", "end").strip(),
                width=int(self.width_var.get()), height=int(self.height_var.get()),
                duration=float(self.duration_var.get()),
                seed=int(self.seed_var.get()),
                decoder=self.decoder_var.get(),
                auto_len=bool(self.auto_len_var.get()),
                randomize_seed=bool(self.randomize_var.get()),
                do_enhance=bool(self.enhance_var.get()),
            )
        except ValueError:
            messagebox.showwarning("Parametre", "Sayısal alanları kontrol edin.")
            return
        if not kw["prompt"]:
            messagebox.showwarning("Prompt", "Prompt boş olamaz.")
            return
        use_proxy = bool(self.use_proxy_var.get()) and self.pool is not None
        self._save_settings()
        self._set_busy(True)
        self.play_btn.configure(state="disabled")
        self.save_btn.configure(state="disabled")
        mode = "fotoğraftan" if image else "metinden"
        self._append_log("info", f"Üretim başlatıldı ({mode}) · {kw['width']}x{kw['height']} · "
                                 f"{kw['duration']} sn · decoder={kw['decoder']} · "
                                 f"seed={'rastgele' if kw['randomize_seed'] else kw['seed']}")
        self.worker = threading.Thread(
            target=self._thread_entry,
            args=(dict(kw, use_proxy=use_proxy),), daemon=True)
        self.worker.start()

    def _thread_entry(self, kw: dict) -> None:
        try:
            use_proxy = kw.pop("use_proxy")
            client = api.LTX25Client(proxy_pool=self.pool if use_proxy else None,
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

    def _on_result(self, result: api.VideoResult) -> None:
        self.result = result
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(OUT_DIR, f"ltx25_{stamp}.mp4")
        try:
            with open(path, "wb") as fh:
                fh.write(result.video_bytes)
            self.result_path = path
        except OSError as exc:
            self._append_log("warn", f"Video otomatik kaydedilemedi: {exc}")
            self.result_path = None
        self.play_btn.configure(state="normal" if self.result_path else "disabled")
        self.save_btn.configure(state="normal")
        self.info_var.set(f"{result.size_kb / 1024:.1f} MB · {result.width}x{result.height} · "
                          f"seed {result.seed} · {result.elapsed:.0f} sn")
        detail = f"Video hazır\n{os.path.basename(path) if path else 'bellekte'}"
        if result.length:
            detail += f"\nuzunluk: {result.length}"
        self.stage.configure(text=detail)
        self._append_log("ok", f"Sonuç hazır: {os.path.basename(path) if path else 'bellekte'}")
        if result.prompt and result.prompt != self.prompt_text.get("1.0", "end").strip():
            self._append_log("info", f"Geliştirilmiş prompt: {result.prompt[:160]}")
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
            title="MP4 kaydet", defaultextension=".mp4",
            initialfile=os.path.basename(self.result_path or "video.mp4"),
            initialdir=OUT_DIR, filetypes=[("MP4 video", "*.mp4")])
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
                messagebox.showerror("Oynat", str(exc))

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
    LTX25App().mainloop()


if __name__ == "__main__":
    main()
