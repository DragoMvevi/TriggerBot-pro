"""
dot_overlay.py — Minimalist Precision Target Dot Overlay
=========================================================
Renders a small, customizable dot (e.g. 2x2 to 8x8 px) at the exact
sample location being tracked by TriggerBot.

Features:
- Pure clean dot with optional micro-outline for visibility.
- Configurable size (down to 1–2 px) and color.
- Click-through (WS_EX_TRANSPARENT) so games receive all inputs.
- Excluded from Windows screen captures (WDA_EXCLUDEFROMCAPTURE)
  so it NEVER interferes with TriggerBot color delta sampling!
- Easily enabled / disabled via GUI switch.
"""

import tkinter as tk
import ctypes
from ctypes import wintypes

# ── Win32 Constants ───────────────────────────────────────────────────────────
GWL_EXSTYLE       = -20
WS_EX_LAYERED     = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW  = 0x00000080
WS_EX_TOPMOST     = 0x00000008
WDA_EXCLUDEFROMCAPTURE = 0x00000011

user32 = ctypes.windll.user32
TRANS_COLOR = "#010101"


class TrackingDotOverlay:
    def __init__(self, engine):
        self.engine = engine
        self._running = False
        self._root = None
        self._canvas = None
        self._dot_item = None
        self._hwnd = None
        self._visible = False

    def start(self):
        if self._root is not None:
            return

        self._root = tk.Toplevel() if tk._default_root else tk.Tk()
        self._root.title("TriggerTargetDot")
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)

        # Transparent background
        self._root.configure(bg=TRANS_COLOR)
        self._root.wm_attributes("-transparentcolor", TRANS_COLOR)

        self._canvas = tk.Canvas(
            self._root,
            width=24,
            height=24,
            bg=TRANS_COLOR,
            highlightthickness=0,
        )
        self._canvas.pack(fill="both", expand=True)

        # Minimalist dot
        self._dot_item = self._canvas.create_rectangle(11, 11, 13, 13, fill="#00FFFF", outline="#000000", width=1)

        self._root.update_idletasks()
        self._hwnd = user32.GetParent(self._root.winfo_id()) or self._root.winfo_id()

        # Set click-through & topmost style
        ex_style = user32.GetWindowLongW(self._hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(
            self._hwnd,
            GWL_EXSTYLE,
            ex_style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_TOPMOST
        )

        # WDA_EXCLUDEFROMCAPTURE: Guarantee TriggerBot/MSS never captures this dot
        try:
            user32.SetWindowDisplayAffinity(self._hwnd, WDA_EXCLUDEFROMCAPTURE)
        except Exception:
            pass

        self._running = True
        self._root.withdraw()
        self._visible = False
        self._update_loop()

    def _hide(self):
        if self._visible and self._root:
            self._root.withdraw()
            self._visible = False

    def _show(self):
        if not self._visible and self._root:
            self._root.deiconify()
            self._visible = True

    def _update_loop(self):
        if not self._running or not self._root or not self._root.winfo_exists():
            return

        try:
            cfg = self.engine.config
            show_dot = cfg.get("show_tracking_dot", False)
            trk_mode = cfg.get("tracking_mode", "center" if cfg.get("lock_to_center", True) else "mouse_hold")

            # Snapshot / Mouse modes: Only appear when trigger is actively engaged
            if trk_mode in ("mouse_toggle", "mouse_hold"):
                should_show = show_dot and self.engine.enabled and self.engine.active
            else:
                should_show = show_dot and self.engine.enabled

            if should_show:
                pos = getattr(self.engine, "diag_sample_pos", None)
                if pos:
                    x, y = int(pos[0]), int(pos[1])
                    # Center the 24x24 overlay window at (x, y)
                    self._root.geometry(f"24x24+{x - 12}+{y - 12}")

                    # Color feedback: Red when firing, otherwise user color
                    st = getattr(self.engine, "diag_status", "DISABLED")
                    if st == "ACTIVE":
                        color = "#EF4444"
                    else:
                        color = cfg.get("dot_color", "#00FFFF")

                    # Radius / half-size (e.g. 1 = 2x2 px, 2 = 4x4 px, 3 = 6x6 px)
                    half_sz = max(1, min(6, int(cfg.get("dot_size", 2))))
                    cx, cy = 12, 12

                    self._canvas.coords(
                        self._dot_item,
                        cx - half_sz,
                        cy - half_sz,
                        cx + half_sz,
                        cy + half_sz,
                    )
                    self._canvas.itemconfig(self._dot_item, fill=color)

                    self._show()
                else:
                    self._hide()
            else:
                self._hide()

        except Exception:
            pass

        if self._root and self._root.winfo_exists():
            self._root.after(16, self._update_loop)

    def destroy(self):
        self._running = False
        if self._root and self._root.winfo_exists():
            try:
                self._root.destroy()
            except Exception:
                pass
        self._root = None
