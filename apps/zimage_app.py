"""Z-Image-Turbo (mrfakename) — Windows masaustu arayuzu (metinden gorsel).

Calistirma: python apps/zimage_app.py  (veya baslat.bat -> Space listesi)
Gereksinimler: pip install requests pillow
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

from PIL import Image, ImageDraw, ImageOps, ImageTk

import clients.zimage_client as api

APP_DIR = ROOT_DIR
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "settings_zimage.json")
OUT_DIR = os.path.join(APP_DIR, "outputs")

BG, PANEL, CARD, CARD2, BORDER = "#0f1115", "#151820", "#1b1f28", "#242a36", "#2b3140"
FG, MUTED, ACCENT, ACCENT2 = "#e9ecf1", "#8b93a1", "#7c5cff", "#31c8ff"
OK, WARN, ERR = "#38d39f", "#ffb020", "#ff5d6c"
FONT, MONO = "Segoe UI", "Consolas"


class ZImageApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Z-Image-Turbo · Görsel")
        width = min(1180, max(880, self.winfo_screenwidth() - 40))
        height = max(600, min(820, self.winfo_screenheight() - 110))
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

        os.makedirs(OUT_DIR, exist_ok=True)
        self.settings = self._load_settings()
        self._init_proxy()
        self._init_style()
        self._build()
        self._set_busy(False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._pump_job = self.after(100, self._pump)

        self._append_log("info", "Hazır. Prompt yazın ve ÜRET'e basın.")
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
            "steps": self.steps_var.get(), "seed": self.seed_var.get(),
            "randomize": bool(self.randomize_var.get()),
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
                        foreground=FG, arrowcolor=MUTED, bordercolor=BORDER)
        style.map("TCombobox", fieldbackground=[("readonly", CARD)],
                  foreground=[("readonly", FG)])

    def _build(self) -> None:
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        header = tk.Frame(self, bg=PANEL, height=74)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.columnconfigure(0, weight=1)
        title = tk.Frame(header, bg=PANEL)
        title.grid(row=0, column=0, sticky="w", padx=22, pady=12)
        tk.Label(title, text="Z-Image", bg=PANEL, fg=ACCENT, font=(FONT, 22, "bold")).pack(side="left")
        tk.Label(title, text=" · Turbo", bg=PANEL, fg=FG, font=(FONT, 22)).pack(side="left")
        tk.Label(title, text="  ·  metinden görsel", bg=PANEL, fg=MUTED,
                 font=(FONT, 10)).pack(side="left", pady=(8, 0))
        right = tk.Frame(header, bg=PANEL)
        right.grid(row=0, column=1, sticky="e", padx=22)
        tk.Label(right, text="mrfakename / Z-Image-Turbo", bg=PANEL, fg=MUTED,
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
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        pc = tk.Frame(left, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        pc.grid(row=0, column=0, sticky="ew")
        tk.Label(pc, text="PROMPT", bg=CARD, fg=FG, font=(FONT, 8, "bold")).pack(
            anchor="w", padx=12, pady=(10, 0))
        self.prompt_text = tk.Text(pc, height=5, wrap="word", bg="#0a0c10", fg=FG,
                                   insertbackground=FG, relief="flat", highlightthickness=1,
                                   highlightbackground=BORDER, font=(FONT, 10), padx=8, pady=6)
        self.prompt_text.pack(fill="x", padx=12, pady=(5, 10))
        self.prompt_text.insert("1.0", self.settings.get("prompt", "a cinematic portrait in soft natural light"))
        self.prompt_text.bind("<Control-Return>", lambda _e: (self._start(), "break")[1])

        opts = tk.Frame(left, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        opts.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        for c in (1, 3):
            opts.columnconfigure(c, weight=1)
        s = self.settings
        self.width_var = tk.StringVar(value=str(s.get("width", 1024)))
        self.height_var = tk.StringVar(value=str(s.get("height", 1024)))
        self.steps_var = tk.StringVar(value=str(s.get("steps", 9)))
        self.seed_var = tk.StringVar(value=str(s.get("seed", 42)))
        self.randomize_var = tk.BooleanVar(value=bool(s.get("randomize", True)))
        self.use_proxy_var = tk.BooleanVar(value=bool(s.get("use_proxy", True)) and self.pool is not None)

        def lbl(t, r, c):
            tk.Label(opts, text=t, bg=CARD, fg=MUTED, font=(FONT, 8)).grid(
                row=r, column=c, sticky="w", padx=(12, 6), pady=3)

        def ent(v, r, c):
            tk.Entry(opts, textvariable=v, bg=CARD2, fg=FG, insertbackground=FG,
                     relief="flat", highlightthickness=1, highlightbackground=BORDER,
                     font=(FONT, 9)).grid(row=r, column=c, sticky="ew", padx=(0, 10), pady=3, ipady=2)

        lbl("Genişlik (512-2048, 64 kat)", 0, 0); ent(self.width_var, 0, 1)
        lbl("Yükseklik (512-2048, 64 kat)", 0, 2); ent(self.height_var, 0, 3)
        lbl("Adım (1-20)", 1, 0); ent(self.steps_var, 1, 1)
        lbl("Seed", 1, 2); ent(self.seed_var, 1, 3)
        tk.Checkbutton(opts, text="rastgele seed", variable=self.randomize_var,
                       bg=CARD, fg=FG, selectcolor=CARD2,
                       activebackground=CARD, font=(FONT, 8)).grid(
            row=2, column=0, columnspan=2, sticky="w", padx=12, pady=(4, 8))
        self._btn(opts, "🎲 Rastgele seed", self._random_seed, small=True).grid(
            row=2, column=2, columnspan=2, sticky="e", padx=(0, 10), pady=(4, 8))
        tk.Checkbutton(opts, text="her üretimde farklı proxy", variable=self.use_proxy_var,
                       bg=CARD, fg=FG, selectcolor=CARD2, activebackground=CARD,
                       font=(FONT, 8)).grid(row=3, column=0, columnspan=4, sticky="w", padx=12, pady=(0, 8))

        footer = tk.Frame(left, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        footer.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.gen_btn = tk.Button(footer, text="▶   GÖRSEL ÜRET", command=self._start,
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
        self.stage_canvas = tk.Canvas(stage, bg="#0a0c10", highlightthickness=0)
        self.stage_canvas.grid(row=1, column=0, sticky="nsew", padx=12, pady=8)
        self.stage_canvas.bind("<Configure>", lambda _e: self._draw_stage())

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
                           ("ok", OK), ("warn", WARN), ("error", ERR), ("proxy", "#6fb8ff")):
            self.log_text.tag_configure(tag, foreground=color)

    def _btn(self, parent, text, command, small: bool = False) -> tk.Button:
        return tk.Button(parent, text=text, command=command, bg=CARD2, fg=FG,
                         activebackground=BORDER, activeforeground=FG, relief="flat", bd=0,
                         font=(FONT, 8 if small else 9), cursor="hand2",
                         padx=8 if small else 12, pady=3 if small else 6)

    def _random_seed(self) -> None:
        self.randomize_var.set(False)
        self.seed_var.set(str(random.randint(0, 2_147_483_647)))
        self._append_log("info", "Seed elle girildi (rastgele kapatıldı)")

    def _fit_photo(self, path: Optional[str]) -> None:
        self.stage_canvas.delete("all")
        if not path or not os.path.exists(path):
            return
        try:
            with Image.open(path) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                cw, ch = self.stage_canvas.winfo_width(), self.stage_canvas.winfo_height()
                if cw < 10 or ch < 10:
                    return
                im.thumbnail((cw - 16, ch - 16), Image.LANCZOS)
                photo = ImageTk.PhotoImage(im)
                self.stage_canvas.create_image(cw // 2, ch // 2, image=photo)
                self._result_ref = photo
        except Exception:
            pass

    def _draw_stage(self) -> None:
        if self.result and self.result_path and os.path.exists(self.result_path):
            self._fit_photo(self.result_path)
        else:
            self.stage_canvas.delete("all")

    def _set_busy(self, busy: bool) -> None:
        if busy:
            self.gen_btn.configure(state="disabled", text="⏳   ÜRETİLİYOR…", bg="#4a3020")
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.configure(value=0)
            self.gen_btn.configure(state="normal", text="▶   GÖRSEL ÜRET", bg=ACCENT)

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        prompt = self.prompt_text.get("1.0", "end").strip()
        if not prompt:
            messagebox.showwarning("Prompt", "Prompt yazın.")
            return
        try:
            width = int(self.width_var.get())
            height = int(self.height_var.get())
            steps = int(self.steps_var.get())
            seed = int(self.seed_var.get())
        except ValueError:
            messagebox.showwarning(" parametre", "Genişlik, yükseklik, adım ve seed tam sayı olmalı.")
            return
        use_proxy = bool(self.use_proxy_var.get()) and self.pool is not None
        self._save_settings()
        self._set_busy(True)
        self.save_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self._append_log("info", f"Üretim başlatıldı · {width}x{height} · {steps} adım · "
                                 f"seed={'rastgele' if self.randomize_var.get() else seed}")
        self.worker = threading.Thread(
            target=self._thread_entry,
            args=(dict(prompt=prompt, width=width, height=height, steps=steps,
                       seed=seed, randomize_seed=bool(self.randomize_var.get()),
                       use_proxy=use_proxy),),
            daemon=True,
        )
        self.worker.start()

    def _thread_entry(self, kw: dict) -> None:
        try:
            use_proxy = kw.pop("use_proxy")
            client = api.ZImageClient(proxy_pool=self.pool if use_proxy else None,
                                      on_log=lambda lv, m: self.events.put(("log", lv, m)))
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
        path = os.path.join(OUT_DIR, f"zimage_{stamp}.png")
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
        self.info_var.set(f"{result.size_kb:.0f} KB · seed {result.seed} · {result.elapsed:.0f} sn")
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
            initialfile=os.path.basename(self.result_path or "zimage.png"),
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
    ZImageApp().mainloop()


if __name__ == "__main__":
    main()
