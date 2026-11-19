"""Kokoro TTS (hexgrad) — Windows masaustu arayuzu (metinden ses).

Calistirma: python apps/kokoro_app.py  (veya baslat.bat -> Space listesi)
Gereksinim: pip install requests
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

import clients.kokoro_client as api

APP_DIR = ROOT_DIR
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "settings_kokoro.json")
OUT_DIR = os.path.join(APP_DIR, "outputs")

BG, PANEL, CARD, CARD2, BORDER = "#0f1115", "#151820", "#1b1f28", "#242a36", "#2b3140"
FG, MUTED, ACCENT, ACCENT2 = "#e9ecf1", "#8b93a1", "#7c5cff", "#31c8ff"
OK, WARN, ERR = "#38d39f", "#ffb020", "#ff5d6c"
FONT, MONO = "Segoe UI", "Consolas"


class KokoroApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Kokoro TTS · Metinden ses")
        width = min(1000, max(760, self.winfo_screenwidth() - 40))
        height = max(620, min(780, self.winfo_screenheight() - 110))
        self.geometry(f"{width}x{height}+20+10")
        self.minsize(760, 600)
        self.configure(bg=BG)

        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self.result: Optional[api.AudioResult] = None
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
        self._append_log("info", "Hazır. Metin yazın ve ÜRET'e basın.")
        if self.proxy_file:
            self._append_log("info", f"Proxy dosyası: {os.path.basename(self.proxy_file)} · {len(self.pool)} IP")
        else:
            self._append_log("warn", "Proxy dosyası bulunamadı; doğrudan bağlantı kullanılacak.")

    def _load_settings(self) -> dict:
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    def _save_settings(self) -> None:
        data = {
            "text": self.text_box.get("1.0", "end").strip(),
            "voice": self.voice_var.get(), "speed": self.speed_var.get(),
            "gpu": bool(self.gpu_var.get()),
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
        style.configure("TScale", background=CARD, troughcolor=CARD2)

    def _build(self) -> None:
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        header = tk.Frame(self, bg=PANEL, height=74)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.columnconfigure(0, weight=1)
        title = tk.Frame(header, bg=PANEL)
        title.grid(row=0, column=0, sticky="w", padx=22, pady=12)
        tk.Label(title, text="Kokoro", bg=PANEL, fg=ACCENT, font=(FONT, 22, "bold")).pack(side="left")
        tk.Label(title, text=" · TTS", bg=PANEL, fg=FG, font=(FONT, 22)).pack(side="left")
        tk.Label(title, text="  ·  metinden ses", bg=PANEL, fg=MUTED,
                 font=(FONT, 10)).pack(side="left", pady=(8, 0))
        right = tk.Frame(header, bg=PANEL)
        right.grid(row=0, column=1, sticky="e", padx=22)
        tk.Label(right, text="hexgrad / Kokoro-TTS", bg=PANEL, fg=MUTED,
                 font=(FONT, 9)).pack(side="left", padx=(0, 12))
        self._btn(right, "⌂  Space seç", self._back_to_launcher, small=True).pack(side="left")

        body = tk.Frame(self, bg=BG)
        body.grid(row=1, column=0, sticky="nsew", padx=16, pady=(12, 8))
        body.rowconfigure(1, weight=1)
        body.columnconfigure(0, weight=1)

        tc = tk.Frame(body, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        tc.grid(row=0, column=0, sticky="ew")
        tk.Label(tc, text="METİN (~500 karakter)", bg=CARD, fg=FG,
                 font=(FONT, 8, "bold")).pack(anchor="w", padx=12, pady=(10, 0))
        self.text_box = tk.Text(tc, height=6, wrap="word", bg="#0a0c10", fg=FG,
                                insertbackground=FG, relief="flat", highlightthickness=1,
                                highlightbackground=BORDER, font=(FONT, 10), padx=8, pady=6)
        self.text_box.pack(fill="x", padx=12, pady=(5, 10))
        self.text_box.insert("1.0", self.settings.get("text", "Hello, this is Kokoro text to speech."))
        self.text_box.bind("<Control-Return>", lambda _e: (self._start(), "break")[1])

        opts = tk.Frame(body, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        opts.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        for c in (1, 3):
            opts.columnconfigure(c, weight=1)
        s = self.settings
        self.voice_var = tk.StringVar(value=s.get("voice", api.DEFAULT_VOICE))
        self.speed_var = tk.StringVar(value=str(s.get("speed", 1.0)))
        self.gpu_var = tk.BooleanVar(value=bool(s.get("gpu", True)))
        self.use_proxy_var = tk.BooleanVar(value=bool(s.get("use_proxy", True)) and self.pool is not None)

        def lbl(t, r, c):
            tk.Label(opts, text=t, bg=CARD, fg=MUTED, font=(FONT, 8)).grid(
                row=r, column=c, sticky="w", padx=(12, 6), pady=4)

        lbl("Ses", 0, 0)
        voice_combo = ttk.Combobox(
            opts, textvariable=self.voice_var,
            values=[f"{lab}  [{val}]" for lab, val in api.VOICES], state="readonly")
        voice_combo.grid(row=0, column=1, columnspan=3, sticky="ew", padx=(0, 12), pady=4)
        #Combobox görünen değerden value çıkar
        current = self.voice_var.get()
        if current in api.VOICE_VALUES:
            for lab, val in api.VOICES:
                if val == current:
                    self.voice_var.set(f"{lab}  [{val}]")
                    break
        lbl("Hız (0.5 - 2.0)", 1, 0)
        tk.Entry(opts, textvariable=self.speed_var, bg=CARD2, fg=FG,
                 insertbackground=FG, relief="flat", highlightthickness=1,
                 highlightbackground=BORDER, font=(FONT, 9)).grid(
            row=1, column=1, sticky="ew", padx=(0, 10), pady=4, ipady=2)
        tk.Checkbutton(opts, text="ZeroGPU (kapatırsan CPU)", variable=self.gpu_var,
                       bg=CARD, fg=FG, selectcolor=CARD2, activebackground=CARD,
                       font=(FONT, 8)).grid(row=1, column=2, columnspan=2, sticky="w", pady=4)
        tk.Checkbutton(opts, text="her üretimde farklı proxy", variable=self.use_proxy_var,
                       bg=CARD, fg=FG, selectcolor=CARD2, activebackground=CARD,
                       font=(FONT, 8)).grid(row=2, column=0, columnspan=4, sticky="w", padx=12, pady=(2, 8))

        footer = tk.Frame(body, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        footer.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.gen_btn = tk.Button(footer, text="▶   SES ÜRET", command=self._start,
                                 bg=ACCENT, fg="white", activebackground="#6a4ce0",
                                 activeforeground="white", relief="flat", bd=0,
                                 font=(FONT, 11, "bold"), cursor="hand2", pady=8)
        self.gen_btn.pack(fill="x", padx=8, pady=(8, 4))
        self.progress = ttk.Progressbar(footer, mode="indeterminate")
        self.progress.pack(fill="x", padx=8, pady=(0, 8))

        rc = tk.Frame(body, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        rc.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        tk.Label(rc, text="SONUÇ", bg=CARD, fg=FG, font=(FONT, 8, "bold")).pack(
            anchor="w", padx=12, pady=(8, 2))
        self.info_var = tk.StringVar(value="Henüz üretim yok")
        tk.Label(rc, textvariable=self.info_var, bg=CARD, fg=MUTED,
                 font=(MONO, 9)).pack(anchor="w", padx=12, pady=(0, 4))
        btns = tk.Frame(rc, bg=CARD)
        btns.pack(fill="x", padx=12, pady=(0, 10))
        self.play_btn = self._btn(btns, "▶ Oynat", self._open_result)
        self.play_btn.pack(side="left", padx=(0, 8))
        self.save_btn = self._btn(btns, "💾  Kaydet", self._save_result)
        self.save_btn.pack(side="left", padx=(0, 8))
        self._btn(btns, "Klasör", self._open_folder).pack(side="left")

        logc = tk.Frame(body, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        logc.grid(row=4, column=0, sticky="nsew", pady=(10, 0))
        tk.Label(logc, text="GÜNLÜK", bg=CARD, fg=FG, font=(FONT, 8, "bold")).pack(
            anchor="w", padx=12, pady=(8, 2))
        self.log_text = tk.Text(logc, height=7, wrap="word", bg="#0a0c10", fg=FG,
                                relief="flat", highlightthickness=0, font=(MONO, 8), padx=8, pady=6)
        self.log_text.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        for tag, color in (("time", MUTED), ("info", FG), ("status", ACCENT2),
                           ("ok", OK), ("warn", WARN), ("error", ERR)):
            self.log_text.tag_configure(tag, foreground=color)

    def _btn(self, parent, text, command, small: bool = False) -> tk.Button:
        return tk.Button(parent, text=text, command=command, bg=CARD2, fg=FG,
                         activebackground=BORDER, activeforeground=FG, relief="flat", bd=0,
                         font=(FONT, 8 if small else 9), cursor="hand2",
                         padx=8 if small else 12, pady=3 if small else 6)

    def _voice_value(self) -> str:
        val = self.voice_var.get()
        if val in api.VOICE_VALUES:
            return val
        if "[" in val and val.endswith("]"):
            inner = val.rsplit("[", 1)[1][:-1].strip()
            if inner in api.VOICE_VALUES:
                return inner
        return api.DEFAULT_VOICE

    def _set_busy(self, busy: bool) -> None:
        if busy:
            self.gen_btn.configure(state="disabled", text="⏳   ÜRETİLİYOR…", bg="#4a3020")
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.configure(value=0)
            self.gen_btn.configure(state="normal", text="▶   SES ÜRET", bg=ACCENT)

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        text = self.text_box.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("Metin", "Metin yazın.")
            return
        try:
            speed = float(self.speed_var.get())
        except ValueError:
            messagebox.showwarning("Hız", "Hız sayı olmalı (0.5 - 2.0).")
            return
        use_proxy = bool(self.use_proxy_var.get()) and self.pool is not None
        self._save_settings()
        self._set_busy(True)
        self.play_btn.configure(state="disabled")
        self.save_btn.configure(state="disabled")
        self._append_log("info", f"Üretim başlatıldı · ses {self._voice_value()} · "
                                 f"hız {speed} · {'GPU' if self.gpu_var.get() else 'CPU'}")
        self.worker = threading.Thread(
            target=self._thread_entry,
            args=(dict(text=text, voice=self._voice_value(), speed=speed,
                       hardware=bool(self.gpu_var.get()), use_proxy=use_proxy),),
            daemon=True)
        self.worker.start()

    def _thread_entry(self, kw: dict) -> None:
        try:
            use_proxy = kw.pop("use_proxy")
            client = api.KokoroClient(proxy_pool=self.pool if use_proxy else None,
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

    def _on_result(self, result: api.AudioResult) -> None:
        self.result = result
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(OUT_DIR, f"kokoro_{stamp}.wav")
        try:
            with open(path, "wb") as fh:
                fh.write(result.audio_bytes)
            self.result_path = path
        except OSError as exc:
            self._append_log("warn", f"Ses otomatik kaydedilemedi: {exc}")
            self.result_path = None
        self.play_btn.configure(state="normal" if self.result_path else "disabled")
        self.save_btn.configure(state="normal")
        toks = f" · {len(result.tokens)} token" if result.tokens else ""
        self.info_var.set(f"{result.size_kb:.0f} KB · {result.elapsed:.1f} sn{toks}")
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
            title="WAV kaydet", defaultextension=".wav",
            initialfile=os.path.basename(self.result_path or "kokoro.wav"),
            initialdir=OUT_DIR, filetypes=[("WAV ses", "*.wav")])
        if not path:
            return
        try:
            with open(path, "wb") as fh:
                fh.write(self.result.audio_bytes)
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
    KokoroApp().mainloop()


if __name__ == "__main__":
    main()
