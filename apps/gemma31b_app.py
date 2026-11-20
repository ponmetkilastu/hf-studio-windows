"""Gemma 4 31B (mxderncultxre) — Windows sohbet arayuzu.

Calistirma: python apps/gemma31b_app.py  (veya baslat.bat -> Space listesi)
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

import clients.gemma31b_client as api

APP_DIR = ROOT_DIR
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "settings_gemma31b.json")

BG, PANEL, CARD, CARD2, BORDER = "#0f1115", "#151820", "#1b1f28", "#242a36", "#2b3140"
FG, MUTED, ACCENT, ACCENT2 = "#e9ecf1", "#8b93a1", "#7c5cff", "#31c8ff"
OK, WARN, ERR = "#38d39f", "#ffb020", "#ff5d6c"
FONT, MONO = "Segoe UI", "Consolas"


class Gemma31BApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Gemma 4 31B · Sohbet")
        width = min(1200, max(900, self.winfo_screenwidth() - 40))
        height = max(660, min(880, self.winfo_screenheight() - 110))
        self.geometry(f"{width}x{height}+20+10")
        self.minsize(900, 640)
        self.configure(bg=BG)

        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self.pool: Optional[api.ProxyPool] = None
        self.proxy_file: Optional[str] = None

        self.settings = self._load_settings()
        self._init_proxy()
        self._init_style()
        self._build()
        self._set_busy(False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._pump_job = self.after(100, self._pump)
        self._append_log("info", "Hazır. Mesaj yazın ve Gönder'e basın.")
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
            "system": self.system_text.get("1.0", "end").strip(),
            "max_tokens": self.max_var.get(), "temp": self.temp_var.get(),
            "top_p": self.topp_var.get(), "top_k": self.topk_var.get(),
            "rep": self.rep_var.get(), "thinking": bool(self.thinking_var.get()),
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
        tk.Label(title, text="Gemma", bg=PANEL, fg=ACCENT, font=(FONT, 22, "bold")).pack(side="left")
        tk.Label(title, text=" · 4 31B", bg=PANEL, fg=FG, font=(FONT, 22)).pack(side="left")
        tk.Label(title, text="  ·  sohbet", bg=PANEL, fg=MUTED, font=(FONT, 10)).pack(side="left", pady=(8, 0))
        right = tk.Frame(header, bg=PANEL)
        right.grid(row=0, column=1, sticky="e", padx=22)
        tk.Label(right, text="mxderncultxre / Gemma4-31b", bg=PANEL, fg=MUTED,
                 font=(FONT, 9)).pack(side="left", padx=(0, 12))
        self._btn(right, "⌂  Space seç", self._back_to_launcher, small=True).pack(side="left")

        body = tk.Frame(self, bg=BG)
        body.grid(row=1, column=0, sticky="nsew", padx=16, pady=(12, 8))
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=0, minsize=300)
        body.columnconfigure(1, weight=1)

        # Sol: ayarlar
        left = tk.Frame(body, bg=BG, width=300)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        left.grid_propagate(False)
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        sc = tk.Frame(left, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        sc.grid(row=0, column=0, sticky="nsew")
        sc.rowconfigure(1, weight=1)
        sc.columnconfigure(0, weight=1)
        tk.Label(sc, text="SİSTEM PROMPTU", bg=CARD, fg=FG,
                 font=(FONT, 8, "bold")).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 0))
        self.system_text = tk.Text(sc, height=8, wrap="word", bg="#0a0c10", fg=FG,
                                   insertbackground=FG, relief="flat", highlightthickness=1,
                                   highlightbackground=BORDER, font=(FONT, 9), padx=8, pady=6)
        self.system_text.grid(row=1, column=0, sticky="nsew", padx=12, pady=(5, 8))
        self.system_text.insert("1.0", self.settings.get("system", api.DEFAULT_SYSTEM))

        opts = tk.Frame(sc, bg=CARD)
        opts.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 10))
        for c in (1, 3):
            opts.columnconfigure(c, weight=1)
        s = self.settings
        self.max_var = tk.StringVar(value=str(s.get("max_tokens", api.DEFAULT_MAX_TOKENS)))
        self.temp_var = tk.StringVar(value=str(s.get("temp", api.DEFAULT_TEMPERATURE)))
        self.topp_var = tk.StringVar(value=str(s.get("top_p", api.DEFAULT_TOP_P)))
        self.topk_var = tk.StringVar(value=str(s.get("top_k", api.DEFAULT_TOP_K)))
        self.rep_var = tk.StringVar(value=str(s.get("rep", api.DEFAULT_REPETITION)))
        self.thinking_var = tk.BooleanVar(value=bool(s.get("thinking", False)))
        self.use_proxy_var = tk.BooleanVar(value=bool(s.get("use_proxy", True)) and self.pool is not None)

        def lbl(t, r, c):
            tk.Label(opts, text=t, bg=CARD, fg=MUTED, font=(FONT, 8)).grid(
                row=r, column=c, sticky="w", pady=3)

        def ent(v, r, c):
            tk.Entry(opts, textvariable=v, bg=CARD2, fg=FG, insertbackground=FG,
                     relief="flat", highlightthickness=1, highlightbackground=BORDER,
                     font=(FONT, 9)).grid(row=r, column=c, sticky="ew", padx=(0, 8), pady=3, ipady=2)

        lbl("Max token", 0, 0); ent(self.max_var, 0, 1)
        lbl("Temperature", 0, 2); ent(self.temp_var, 0, 3)
        lbl("Top-p", 1, 0); ent(self.topp_var, 1, 1)
        lbl("Top-k", 1, 2); ent(self.topk_var, 1, 3)
        lbl("Repetition", 2, 0); ent(self.rep_var, 2, 1)
        tk.Checkbutton(opts, text="thinking", variable=self.thinking_var,
                       bg=CARD, fg=FG, selectcolor=CARD2, activebackground=CARD,
                       font=(FONT, 8)).grid(row=2, column=2, columnspan=2, sticky="w")
        tk.Checkbutton(opts, text="her üretimde farklı proxy", variable=self.use_proxy_var,
                       bg=CARD, fg=FG, selectcolor=CARD2, activebackground=CARD,
                       font=(FONT, 8)).grid(row=3, column=0, columnspan=4, sticky="w", pady=(4, 0))

        act = tk.Frame(left, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        act.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self._btn(act, "🔄  Yeni konuşma", self._reset_chat, small=True).pack(
            fill="x", padx=8, pady=(8, 4))
        self._btn(act, "💾  Konuşmayı kaydet", self._save_chat, small=True).pack(
            fill="x", padx=8, pady=(0, 8))

        # Sag: sohbet
        cc = tk.Frame(body, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        cc.grid(row=0, column=1, sticky="nsew")
        cc.rowconfigure(1, weight=1)
        cc.columnconfigure(0, weight=1)
        ch = tk.Frame(cc, bg=CARD)
        ch.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 0))
        tk.Label(ch, text="KONUŞMA", bg=CARD, fg=FG, font=(FONT, 8, "bold")).pack(side="left")
        self.status_var = tk.StringVar(value="Hazır")
        tk.Label(ch, textvariable=self.status_var, bg=CARD, fg=MUTED,
                 font=(MONO, 8)).pack(side="right")

        self.chat_text = tk.Text(cc, wrap="word", bg="#0a0c10", fg=FG,
                                 relief="flat", highlightthickness=0, font=(FONT, 10),
                                 padx=10, pady=8, state="disabled")
        self.chat_text.grid(row=1, column=0, sticky="nsew", padx=12, pady=8)
        for tag, color in (("user", ACCENT2), ("assistant", FG), ("meta", MUTED), ("error", ERR)):
            self.chat_text.tag_configure(tag, foreground=color, spacing1=8, spacing3=4)

        inp = tk.Frame(cc, bg=CARD)
        inp.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 10))
        inp.columnconfigure(0, weight=1)
        self.msg_var = tk.StringVar()
        self.msg_entry = tk.Entry(inp, textvariable=self.msg_var, bg=CARD2, fg=FG,
                                  insertbackground=FG, relief="flat", highlightthickness=1,
                                  highlightbackground=BORDER, font=(FONT, 10))
        self.msg_entry.grid(row=0, column=0, sticky="ew", ipady=5)
        self.msg_entry.bind("<Return>", lambda _e: self._send())
        self.send_btn = tk.Button(inp, text="Gönder  →", command=self._send,
                                  bg=ACCENT, fg="white", activebackground="#6a4ce0",
                                  relief="flat", bd=0, font=(FONT, 10, "bold"),
                                  cursor="hand2", padx=16, pady=5)
        self.send_btn.grid(row=0, column=1, padx=(8, 0))

        logc = tk.Frame(body, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        logc.grid(row=1, column=1, sticky="ew", pady=(10, 0))
        tk.Label(logc, text="GÜNLÜK", bg=CARD, fg=FG, font=(FONT, 8, "bold")).pack(
            anchor="w", padx=12, pady=(8, 2))
        self.log_text = tk.Text(logc, height=5, wrap="word", bg="#0a0c10", fg=FG,
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

    def _client(self) -> api.Gemma31BClient:
        use_proxy = bool(self.use_proxy_var.get()) and self.pool is not None
        return api.Gemma31BClient(
            proxy_pool=self.pool if use_proxy else None,
            on_log=lambda lv, m: self.events.put(("log", lv, m)),
        )

    def _params(self) -> dict:
        try:
            return dict(
                max_new_tokens=int(self.max_var.get()),
                temperature=float(self.temp_var.get()),
                top_p=float(self.topp_var.get()),
                top_k=int(self.topk_var.get()),
                repetition_penalty=float(self.rep_var.get()),
                thinking=bool(self.thinking_var.get()),
                system_prompt=self.system_text.get("1.0", "end").strip(),
            )
        except ValueError:
            raise ValueError("Sayısal parametreleri kontrol edin.")

    def _set_busy(self, busy: bool) -> None:
        if busy:
            self.send_btn.configure(state="disabled", text="⏳")
            self.progress_start()
        else:
            self.send_btn.configure(state="normal", text="Gönder  →")

    def progress_start(self) -> None:
        self.status_var.set("Üretiliyor…")

    def _write(self, role: str, text: str) -> None:
        self.chat_text.configure(state="normal")
        self.chat_text.insert("end", f"{'Sen' if role == 'user' else 'Gemma'}: ", "meta")
        self.chat_text.insert("end", text + "\n\n", role)
        self.chat_text.configure(state="disabled")
        self.chat_text.see("end")

    def _send(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        text = self.msg_var.get().strip()
        if not text:
            return
        try:
            params = self._params()
        except ValueError as exc:
            messagebox.showwarning("Parametre", str(exc))
            return
        self._save_settings()
        self._write("user", text)
        self.msg_var.set("")
        self._set_busy(True)
        if not hasattr(self, "_client_instance") or self._client_instance is None:
            self._client_instance = self._client()
        client = self._client_instance
        history = list(client.history)
        self.worker = threading.Thread(
            target=self._thread_entry,
            args=(client, text, history, params), daemon=True)
        self.worker.start()

    def _thread_entry(self, client, text, history, params) -> None:
        try:
            result = client.chat(text, history=history, **params)
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
                    result = event[1]
                    if result.error:
                        self._write("error", f"HATA: {result.error}")
                        self.status_var.set("Hata")
                    else:
                        self._write("assistant", result.content)
                        self.status_var.set(f"Tamamlandı ✓ {result.elapsed:.1f} sn")
                elif kind == "error":
                    self._write("error", f"HATA: {event[1]}")
                    self._append_log("error", event[1])
                    self.status_var.set("Hata")
                elif kind == "done":
                    self._set_busy(False)
        except queue.Empty:
            pass
        try:
            self._pump_job = self.after(100, self._pump)
        except tk.TclError:
            pass

    def _reset_chat(self) -> None:
        self._client_instance = None
        self.chat_text.configure(state="normal")
        self.chat_text.delete("1.0", "end")
        self.chat_text.configure(state="disabled")
        self.status_var.set("Yeni konuşma")
        self._append_log("info", "Konuşma geçmişi ve oturum sıfırlandı.")

    def _save_chat(self) -> None:
        client = getattr(self, "_client_instance", None)
        if not client:
            messagebox.showinfo("Kaydet", "Kaydedilecek konuşma yok.")
            return
        path = filedialog.asksaveasfilename(
            title="Konuşmayı kaydet", defaultextension=".json",
            initialfile=f"gemma_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            json.dump(client.history, open(path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
            self._append_log("ok", f"Kaydedildi: {path}")
        except OSError as exc:
            messagebox.showerror("Kaydetme", str(exc))

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
        if int(self.log_text.index("end-1c").split(".")[0]) > 400:
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
    Gemma31BApp().mainloop()


if __name__ == "__main__":
    main()
