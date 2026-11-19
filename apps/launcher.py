"""Space secim ekrani — baslat.bat bu dosyayi acar.

Liste ``spaces.json`` dosyasindan okunur. Her kayit bir arayuz modulu belirtir:

    {
      "id": "ltx-2-3-10eros",
      "ad": "LTX-2.3 · Video (10Eros)",
      "tur": "Video üretimi",
      "space": "rdata92/LTX-2.3-10Eros",
      "host": "rdata92-ltx-2-3-10eros.hf.space",
      "modul": "ltx_app",
      "aciklama": "Tek fotoğraftan video üretir."
    }

Yeni bir space eklemek icin: istemci + arayuz modulunu yazip buraya bir kayit
eklemek yeterli; launcher listeyi otomatik gosterir.
"""


from __future__ import annotations

import os as _os, sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
from paths import ROOT_DIR, CONFIG_DIR, DATA_DIR, OUTPUT_DIR, SETTINGS_DIR, PROXY_FILE


import importlib
import json
import os
import sys
import tkinter as tk
from tkinter import messagebox, ttk

APP_DIR = ROOT_DIR
REGISTRY_PATH = os.path.join(CONFIG_DIR, "spaces.json")

BG = "#0f1115"
PANEL = "#151820"
CARD = "#1b1f28"
CARD2 = "#242a36"
BORDER = "#2b3140"
FG = "#e9ecf1"
MUTED = "#8b93a1"
ACCENT = "#7c5cff"
ACCENT2 = "#31c8ff"
FONT = "Segoe UI"
MONO = "Consolas"


def load_spaces() -> list[dict]:
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        raise SystemExit(f"spaces.json okunamadi: {exc}")
    spaces = data.get("spaces") if isinstance(data, dict) else data
    if not isinstance(spaces, list):
        return []
    return [s for s in spaces if isinstance(s, dict) and s.get("modul")]


class Launcher(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Space seçin")
        self.geometry("840x600+40+40")
        self.minsize(720, 480)
        self.configure(bg=BG)

        self.spaces = load_spaces()
        self.cards: list[dict] = []
        self.selected: int | None = 0 if self.spaces else None

        self._build()
        self._refresh()

    # -- arayuz ----------------------------------------------------------- #

    def _build(self) -> None:
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        header = tk.Frame(self, bg=PANEL, height=76)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.columnconfigure(0, weight=1)

        title = tk.Frame(header, bg=PANEL)
        title.grid(row=0, column=0, sticky="w", padx=22, pady=12)
        tk.Label(title, text="HF", bg=PANEL, fg=ACCENT2, font=(FONT, 22, "bold")).pack(side="left")
        tk.Label(title, text=" Studio", bg=PANEL, fg=FG, font=(FONT, 22)).pack(side="left")
        tk.Label(
            title,
            text="  ·  hangi space ile çalışmak istersiniz?",
            bg=PANEL,
            fg=MUTED,
            font=(FONT, 10),
        ).pack(side="left", pady=(8, 0))

        bar = tk.Canvas(self, height=3, bg=BG, highlightthickness=0)
        bar.grid(row=0, column=0, sticky="sew")
        bar.bind("<Configure>", lambda _e: self._gradient(bar))

        wrap = tk.Frame(self, bg=BG)
        wrap.grid(row=1, column=0, sticky="nsew", padx=18, pady=14)
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        # Kart listesi dikey kaydirilabilir bir canvas icinde.
        self.list_canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0, bd=0)
        self.list_canvas.grid(row=0, column=0, sticky="nsew")
        self.list_scroll = ttk.Scrollbar(
            wrap, orient="vertical", command=self.list_canvas.yview
        )
        self.list_scroll.grid(row=0, column=1, sticky="ns")
        self.list_canvas.configure(yscrollcommand=self._on_scroll)

        self.list_frame = tk.Frame(self.list_canvas, bg=BG)
        self._list_window = self.list_canvas.create_window(
            (0, 0), window=self.list_frame, anchor="nw"
        )
        self.list_frame.bind(
            "<Configure>",
            lambda _e: self.list_canvas.configure(
                scrollregion=self.list_canvas.bbox("all")
            ),
        )
        self.list_canvas.bind(
            "<Configure>",
            lambda e: self.list_canvas.itemconfig(self._list_window, width=e.width),
        )
        self._bind_mousewheel(self.list_canvas)
        self._bind_mousewheel(self.list_frame)

        foot = tk.Frame(self, bg=PANEL, height=54)
        foot.grid(row=2, column=0, sticky="ew")
        foot.grid_propagate(False)
        foot.columnconfigure(0, weight=1)
        self.hint = tk.StringVar(value="Bir karta tıklayın · Enter ile aç · fare tekeri / ↑↓ ile kaydır · Esc ile çık")
        tk.Label(foot, textvariable=self.hint, bg=PANEL, fg=MUTED, font=(FONT, 9)).grid(
            row=0, column=0, sticky="w", padx=18, pady=15
        )
        self.open_btn = tk.Button(
            foot,
            text="Aç  →",
            command=self.open_selected,
            bg=ACCENT,
            fg="white",
            activebackground="#6a4ce0",
            activeforeground="white",
            relief="flat",
            bd=0,
            font=(FONT, 10, "bold"),
            cursor="hand2",
            padx=22,
            pady=6,
            state="disabled",
        )
        self.open_btn.grid(row=0, column=1, sticky="e", padx=18, pady=10)

        self.bind("<Return>", lambda _e: self.open_selected())
        self.bind("<Down>", lambda _e: self._move(1))
        self.bind("<Up>", lambda _e: self._move(-1))
        self.bind("<Escape>", lambda _e: self.destroy())

        if not self.spaces:
            tk.Label(
                self.list_frame,
                text="spaces.json içinde geçerli kayıt yok.",
                bg=BG,
                fg=MUTED,
                font=(FONT, 10),
            ).pack(anchor="w")

    def _on_scroll(self, first: float, last: float) -> None:
        """Icerik sigarsa kaydirma cubugunu gizle."""
        self.list_scroll.set(first, last)
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.list_scroll.grid_remove()
        else:
            self.list_scroll.grid()

    def _bind_mousewheel(self, widget: tk.Misc) -> None:
        def scroll(event) -> None:
            if event.delta:
                self.list_canvas.yview_scroll(-int(event.delta / 120), "units")
            elif event.num == 4:
                self.list_canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                self.list_canvas.yview_scroll(1, "units")

        widget.bind("<MouseWheel>", scroll)
        widget.bind("<Button-4>", scroll)
        widget.bind("<Button-5>", scroll)

    def _bind_mousewheel_tree(self, widget: tk.Misc) -> None:
        self._bind_mousewheel(widget)
        for child in widget.winfo_children():
            self._bind_mousewheel_tree(child)

    def _scroll_into_view(self, index: int) -> None:
        """Klavye ile secilen kart gorunmezse listeyi kaydir."""
        frame = self.cards[index]["frame"]
        self.update_idletasks()
        content_h = max(self.list_frame.winfo_height(), 1)
        view_h = self.list_canvas.winfo_height()
        top = frame.winfo_y()
        bottom = top + frame.winfo_height()
        cur_top = self.list_canvas.yview()[0] * content_h
        cur_bottom = cur_top + view_h
        if top < cur_top:
            self.list_canvas.yview_moveto(max(0, top - 10) / content_h)
        elif bottom > cur_bottom:
            self.list_canvas.yview_moveto(max(0, bottom - view_h + 10) / content_h)

    def _gradient(self, canvas: tk.Canvas) -> None:
        canvas.delete("all")
        width = max(canvas.winfo_width(), 1)
        for x in range(0, width, 3):
            t = x / max(width - 1, 1)
            color = (int(124 + (49 - 124) * t), int(92 + (200 - 92) * t), 255)
            canvas.create_line(
                x, 1, x + 3, 1, fill=f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}", width=3
            )

    def _refresh(self) -> None:
        for child in self.list_frame.winfo_children():
            child.destroy()
        self.cards.clear()

        cols = self.cols = 3
        for c in range(cols):
            self.list_frame.columnconfigure(c, weight=1, uniform="card")

        for index, space in enumerate(self.spaces):
            row, col = divmod(index, cols)
            card = tk.Frame(
                self.list_frame,
                bg=CARD,
                highlightbackground=BORDER,
                highlightthickness=1,
                cursor="hand2",
                width=232,
                height=172,
            )
            card.grid(row=row, column=col, sticky="nsew", padx=(0, 10), pady=(0, 10))
            card.grid_propagate(False)

            body = tk.Frame(card, bg=CARD, cursor="hand2")
            body.place(x=0, y=0, relwidth=1, relheight=1)

            # ustteki ince renk seridi (kartlari birbirinden ayirir)
            stripe = tk.Frame(body, bg=ACCENT2, height=3)
            stripe.pack(fill="x")

            name = tk.Label(
                body,
                text=space.get("ad", space["modul"]),
                bg=CARD, fg=FG, font=(FONT, 11, "bold"),
                wraplength=204, justify="left", anchor="w",
            )
            name.pack(fill="x", padx=12, pady=(9, 0))

            tur = space.get("tur")
            if tur:
                tk.Label(body, text=tur, bg=CARD, fg=MUTED, font=(FONT, 8),
                         anchor="w").pack(fill="x", padx=12, pady=(2, 0))

            tk.Label(
                body,
                text=space.get("space", "") + "\n" + space.get("host", ""),
                bg=CARD, fg=ACCENT2, font=(MONO, 7),
                justify="left", anchor="w", wraplength=204,
            ).pack(fill="x", padx=12, pady=(5, 0))

            tk.Label(
                body,
                text=space.get("aciklama", ""),
                bg=CARD, fg=MUTED, font=(FONT, 8),
                justify="left", anchor="w", wraplength=204,
            ).pack(fill="x", padx=12, pady=(5, 0))

            # Tek tiklama yeterli: tum kart tek bir acma hedefi.
            widgets = [card, body, stripe, name]
            for widget in widgets:
                widget.bind("<Button-1>", lambda _e, i=index: self._open(i))

            self.cards.append({"frame": card, "widgets": widgets})

        self.update_idletasks()
        self.list_canvas.configure(scrollregion=self.list_canvas.bbox("all"))
        self._bind_mousewheel_tree(self.list_frame)
        self._select(self.selected if self.selected is not None else 0)

    def _select(self, index: int | None) -> None:
        if not self.cards:
            return
        index = 0 if index is None else max(0, min(index, len(self.cards) - 1))
        self.selected = index
        for i, card in enumerate(self.cards):
            active = i == index
            bg = "#232a3a" if active else CARD
            border = ACCENT if active else BORDER
            card["frame"].configure(bg=bg, highlightbackground=border)
            for widget in card["widgets"]:
                widget.configure(bg=bg)
            for child in card["frame"].winfo_children():
                for sub in (child, *child.winfo_children()):
                    try:
                        sub.configure(bg=bg)
                    except tk.TclError:
                        pass
                for sub in child.winfo_children():
                    for leaf in sub.winfo_children():
                        try:
                            leaf.configure(bg=bg)
                        except tk.TclError:
                            pass
        self.open_btn.configure(state="normal")
        self._scroll_into_view(index)
        space = self.spaces[index]
        self.hint.set(f"Seçili: {space.get('ad', space['modul'])} · Enter ile aç")

    def _move(self, delta: int) -> None:
        if self.selected is None:
            self._select(0)
        else:
            self._select(self.selected + delta)

    def open_selected(self) -> None:
        if self.selected is None:
            return
        self._open(self.selected)

    def _open(self, index: int) -> None:
        space = self.spaces[index]
        module_name = str(space.get("modul"))
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            messagebox.showerror("Açılamadı", f"{module_name} yüklenemedi:\n{exc}")
            return
        if not callable(getattr(module, "main", None)):
            messagebox.showerror("Açılamadı", f"{module_name} içinde main() bulunamadı.")
            return

        # Ana sayfa (launcher) KAPANMAZ ve GORUNUR KALIR.
        # Space'i ayri bir process'te baslatiriz: boylece launcher'in mainloop'u
        # ve space'in mainloop'u ic ice girmez (ikinci Tk root sorunu olusmaz).
        # Env degiskeni child'a kalitilir; space icindeki "Space sec" butonu
        # bunu gorup YENI launcher baslatmaz, sadece kendi penceresini kapatir.
        os.environ["HF_STUDIO_LAUNCHER_ACTIVE"] = "1"
        try:
            import subprocess
            subprocess.Popen([sys.executable, os.path.join(APP_DIR, module_name.replace(".", os.sep) + ".py")])
            self.hint.set(f"{space.get('ad', module_name)} açıldı · ana sayfa açık kaldı")
        except OSError as exc:
            messagebox.showerror("Açılamadı", f"Space başlatılamadı:\n{exc}")


def main() -> None:
    Launcher().mainloop()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
