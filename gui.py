"""
gui.py — Premium CustomTkinter UI  v4
========================================
New in v4:
  - Screen Center Zoom Magnifier (personalizable size, zoom factor, keybind, toggle/hold mode)
  - Mouse Tracking Variation:
      • Center Screen Lock
      • Mouse Snapshot (Toggle) — locks to cursor position at toggle time
      • Mouse Follow (Hold) — dynamically tracks cursor in real-time
  - Visual Tracking Dot Overlay — customizable dot at sample coordinates
  - Mouse button trigger keys (MB1–MB5) + extended keyboard keys
  - Auto-Strafe Stop with true counter-strafing sequence & delay slider
  - Color Whitelist / Blacklist with RGB color pickers & tolerances
  - Profile Management System & Floating Status Overlay
"""

import customtkinter as ctk
import threading
import time
import json
import os
import webbrowser
import tkinter as tk
from tkinter import colorchooser, simpledialog, messagebox

from magnifier import ScreenMagnifier
from dot_overlay import TrackingDotOverlay

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ── Palette ───────────────────────────────────────────────────────────────────
ACCENT      = "#7C3AED"
ACCENT2     = "#06B6D4"
BG_DARK     = "#0A0A0F"
BG_CARD     = "#12121A"
BG_SURFACE  = "#1A1A2E"
TEXT_MAIN   = "#E2E8F0"
TEXT_DIM    = "#64748B"
GREEN       = "#10B981"
RED         = "#EF4444"
ORANGE      = "#F59E0B"
PURPLE      = "#A855F7"
CYAN        = "#00FFFF"

FONT_TITLE  = ("Segoe UI", 22, "bold")
FONT_HEAD   = ("Segoe UI", 12, "bold")
FONT_BODY   = ("Segoe UI", 11)
FONT_SMALL  = ("Segoe UI", 9)
FONT_MONO   = ("Consolas", 10)

PROFILES_DIR = os.path.join(os.path.dirname(__file__), "profiles")

KEY_CHOICES = [
    "shift", "ctrl", "alt", "caps_lock",
    "x", "c", "v", "f", "g", "h", "t", "z", "e", "q", "r", "space",
    "f1", "f2", "f3", "f4",
    "mb1 (LMB)", "mb2 (RMB)", "mb3 (MMB)", "mb4 (Side-Back)", "mb5 (Side-Fwd)"
]


# ── Overlay window ────────────────────────────────────────────────────────────
class TriggerOverlay(ctk.CTkToplevel):
    """Small always-on-top status badge."""

    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.title("")
        self.geometry("200x60+20+20")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.82)
        self.configure(fg_color="#0D0D14")
        self.overrideredirect(True)   # borderless

        # Drag support
        self._drag_x = self._drag_y = 0
        self.bind("<ButtonPress-1>",   self._drag_start)
        self.bind("<B1-Motion>",       self._drag_move)

        self._lbl = ctk.CTkLabel(
            self, text="● DISABLED", font=("Segoe UI", 13, "bold"),
            text_color=TEXT_DIM,
        )
        self._lbl.pack(expand=True)

        ctk.CTkButton(
            self, text="✕", width=18, height=18, font=("Segoe UI", 9),
            fg_color="transparent", hover_color="#2D2D4E",
            command=self.destroy,
        ).place(relx=1.0, rely=0.0, anchor="ne", x=-2, y=2)

        self._running = True
        self._schedule()

    def _drag_start(self, e):
        self._drag_x, self._drag_y = e.x, e.y

    def _drag_move(self, e):
        dx = e.x - self._drag_x
        dy = e.y - self._drag_y
        x  = self.winfo_x() + dx
        y  = self.winfo_y() + dy
        self.geometry(f"+{x}+{y}")

    def _schedule(self):
        if not self._running:
            return
        try:
            self._refresh()
        except Exception:
            pass
        self.after(70, self._schedule)

    def _refresh(self):
        st = self.engine.diag_status
        if st == "ACTIVE":
            self._lbl.configure(text="🔥 FIRING", text_color=RED)
        elif st == "MONITORING":
            self._lbl.configure(text="● MONITORING", text_color=GREEN)
        else:
            self._lbl.configure(text="● DISABLED", text_color=TEXT_DIM)

    def on_close(self):
        self._running = False


# ── Main GUI ──────────────────────────────────────────────────────────────────
class TriggerBotGUI(ctk.CTk):

    CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

    def __init__(self, engine):
        super().__init__()
        self.engine   = engine
        self._config  = self._load_config()
        self._overlay = None
        self.engine.reload_config(self._config)

        self.title("TriggerBot Pro — Precision Suite")
        self.geometry("1000x960")
        self.resizable(True, True)
        self.configure(fg_color=BG_DARK)

        os.makedirs(PROFILES_DIR, exist_ok=True)

        self._build_ui()
        self._apply_config_to_ui()

        # Initialize sub-overlays
        self._magnifier = ScreenMagnifier(self.engine)
        self._magnifier.start()

        self._dot_overlay = TrackingDotOverlay(self.engine)
        self._dot_overlay.start()

        self._diag_running = True
        self._schedule_diag()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Config ────────────────────────────────────────────────────────────────
    def _load_config(self) -> dict:
        try:
            with open(self.CONFIG_PATH, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_config(self):
        with open(self.CONFIG_PATH, "w") as f:
            json.dump(self._config, f, indent=4)

    # ── UI build ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        # Header
        header = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=0, height=64)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        tf = ctk.CTkFrame(header, fg_color="transparent")
        tf.pack(side="left", padx=20, pady=10)
        ctk.CTkLabel(tf, text="⚡ TRIGGERBOT", font=("Segoe UI", 20, "bold"),
                     text_color=ACCENT).pack(side="left")
        ctk.CTkLabel(tf, text="  PRO v4", font=("Segoe UI", 20, "bold"),
                     text_color=ACCENT2).pack(side="left")

        self._status_badge = ctk.CTkLabel(
            header, text="● DISABLED", font=("Segoe UI", 11, "bold"),
            text_color=TEXT_DIM, fg_color="#1E1E2E", corner_radius=12,
            padx=14, pady=6,
        )
        self._status_badge.pack(side="right", padx=20, pady=16)

        self._master_var = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(
            header, text="ENABLED", variable=self._master_var,
            command=self._on_master_toggle,
            font=("Segoe UI", 11, "bold"), text_color=TEXT_MAIN,
            progress_color=ACCENT, button_color=TEXT_MAIN,
            fg_color="#2D2D4E",
        ).pack(side="right", padx=(0, 10), pady=16)

        ctk.CTkButton(
            header, text="🖥 Status Overlay", font=FONT_SMALL,
            fg_color=BG_SURFACE, hover_color="#2D2D4E", corner_radius=8,
            command=self._toggle_overlay, width=110, height=30,
        ).pack(side="right", padx=(0, 6), pady=16)

        # Bottom bar (profiles + actions)
        bottom = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=0, height=52)
        bottom.pack(fill="x", side="bottom")
        bottom.pack_propagate(False)

        ctk.CTkButton(
            bottom, text="💾  Save Config", font=FONT_BODY,
            fg_color=ACCENT, hover_color="#6D28D9", corner_radius=8,
            command=self._on_save, width=130, height=32,
        ).pack(side="right", padx=16, pady=10)

        ctk.CTkButton(
            bottom, text="↺  Reset", font=FONT_BODY,
            fg_color=BG_SURFACE, hover_color="#2D2D4E", corner_radius=8,
            command=self._on_reset, width=90, height=32,
        ).pack(side="right", padx=(0, 6), pady=10)

        ctk.CTkButton(
            bottom, text="Support me on Ko-fi  ☕", font=FONT_BODY,
            fg_color="#FF5E5B", hover_color="#E04B48", text_color="#FFFFFF", corner_radius=8,
            command=self._open_kofi, width=165, height=32,
        ).pack(side="right", padx=(0, 10), pady=10)

        # Profile controls
        self._profile_var = ctk.StringVar(value="Default")
        self._profile_menu = ctk.CTkOptionMenu(
            bottom, variable=self._profile_var,
            values=self._get_profiles(),
            fg_color=BG_SURFACE, button_color=ACCENT2, dropdown_fg_color=BG_CARD,
            font=FONT_BODY, text_color=TEXT_MAIN, width=130,
        )
        self._profile_menu.pack(side="left", padx=(16, 4), pady=10)

        ctk.CTkButton(
            bottom, text="Load", font=FONT_SMALL,
            fg_color=BG_SURFACE, hover_color="#2D2D4E", corner_radius=8,
            command=self._on_profile_load, width=54, height=32,
        ).pack(side="left", padx=2, pady=10)

        ctk.CTkButton(
            bottom, text="Save As", font=FONT_SMALL,
            fg_color=BG_SURFACE, hover_color="#2D2D4E", corner_radius=8,
            command=self._on_profile_save_as, width=68, height=32,
        ).pack(side="left", padx=2, pady=10)

        ctk.CTkButton(
            bottom, text="Delete", font=FONT_SMALL,
            fg_color="#3D1515", hover_color="#5C1F1F", corner_radius=8,
            command=self._on_profile_delete, width=56, height=32,
        ).pack(side="left", padx=2, pady=10)

        self._footer_label = ctk.CTkLabel(
            bottom, text="TriggerBot Pro  •  Precision Edition",
            font=FONT_SMALL, text_color=TEXT_DIM,
        )
        self._footer_label.pack(side="left", padx=12)

        # Scrollable Content container to ensure all cards fit effortlessly on any resolution
        scroll_content = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll_content.pack(fill="both", expand=True, padx=12, pady=(8, 4))

        left = ctk.CTkFrame(scroll_content, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))

        right = ctk.CTkFrame(scroll_content, fg_color="transparent")
        right.pack(side="right", fill="both", expand=True, padx=(6, 0))

        self._build_trigger_card(left)
        self._build_tracking_mode_card(left)
        self._build_detection_card(left)

        self._build_magnifier_card(right)
        self._build_wasd_card(right)
        self._build_diagnostics_card(right)

    # ── Card helpers ──────────────────────────────────────────────────────────
    def _card(self, parent, title: str, icon: str = "") -> ctk.CTkFrame:
        outer = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=12)
        outer.pack(fill="x", pady=(0, 10))
        hdr = ctk.CTkFrame(outer, fg_color="transparent")
        hdr.pack(fill="x", padx=12, pady=(10, 2))
        ctk.CTkLabel(hdr, text=f"{icon}  {title}" if icon else title,
                     font=FONT_HEAD, text_color=ACCENT2).pack(side="left")
        ctk.CTkFrame(outer, fg_color=BG_SURFACE, height=1).pack(fill="x", padx=12, pady=(2, 6))
        body = ctk.CTkFrame(outer, fg_color="transparent")
        body.pack(fill="x", padx=14, pady=(0, 10))
        return body

    def _row(self, parent, label: str, label_width: int = 180):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=3)
        ctk.CTkLabel(row, text=label, font=FONT_BODY, text_color=TEXT_DIM,
                     width=label_width, anchor="w").pack(side="left")
        return row

    def _slider_row(self, parent, label, from_, to, default,
                    fmt="{:.0f}", steps=None, color=ACCENT):
        row = self._row(parent, label)
        var = ctk.DoubleVar(value=default)
        lbl = ctk.CTkLabel(row, text=fmt.format(default),
                           font=FONT_MONO, text_color=ACCENT2, width=46)
        lbl.pack(side="right")

        def _update(v, _lbl=lbl, _fmt=fmt):
            _lbl.configure(text=_fmt.format(float(v)))
            self._on_cfg_change()

        kw = dict(from_=from_, to=to, variable=var,
                  progress_color=color, button_color=ACCENT2,
                  fg_color=BG_SURFACE, width=105, command=_update)
        if steps is not None:
            kw["number_of_steps"] = steps
        ctk.CTkSlider(row, **kw).pack(side="right", padx=4)
        return var, lbl

    # ── Trigger card ──────────────────────────────────────────────────────────
    def _build_trigger_card(self, parent):
        body = self._card(parent, "Trigger Settings", "🎯")

        # Activation key
        row = self._row(body, "Activation Key")
        self._trigger_key_var = ctk.StringVar(value="shift")
        ctk.CTkOptionMenu(
            row, variable=self._trigger_key_var,
            values=KEY_CHOICES,
            fg_color=BG_SURFACE, button_color=ACCENT, dropdown_fg_color=BG_CARD,
            font=FONT_BODY, text_color=TEXT_MAIN, width=160,
            command=self._on_cfg_change,
        ).pack(side="right")

        # Action key
        row2 = self._row(body, "Action (Output)")
        self._action_key_var = ctk.StringVar(value="left")
        ctk.CTkOptionMenu(
            row2, variable=self._action_key_var,
            values=["left", "right", "space", "e", "r", "f", "q"],
            fg_color=BG_SURFACE, button_color=ACCENT, dropdown_fg_color=BG_CARD,
            font=FONT_BODY, text_color=TEXT_MAIN, width=160,
            command=self._on_cfg_change,
        ).pack(side="right")

        # Freeze Keyboard
        row4 = self._row(body, "Freeze Keyboard on Hold")
        self._freeze_kb_var = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(row4, text="", variable=self._freeze_kb_var,
                      progress_color=RED, button_color=TEXT_MAIN,
                      fg_color="#2D2D4E", command=self._on_cfg_change).pack(side="right")

        # Freeze Mouse
        row_fm = self._row(body, "Freeze Mouse on Hold")
        self._freeze_mouse_var = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(row_fm, text="", variable=self._freeze_mouse_var,
                      progress_color=RED, button_color=TEXT_MAIN,
                      fg_color="#2D2D4E", command=self._on_cfg_change).pack(side="right")

        # Cooldown
        self._cooldown_var, self._cooldown_lbl = self._slider_row(
            body, "Cooldown (ms)", 0, 1000, 50)

        # Shots per detection
        self._shots_var, self._shots_lbl = self._slider_row(
            body, "Shots per Detection", 1, 10, 1,
            fmt="{:.0f}", steps=9, color=PURPLE)

        # Shot delay
        self._shot_delay_var, self._shot_delay_lbl = self._slider_row(
            body, "Delay Between Shots (ms)", 0, 500, 0,
            fmt="{:.0f}", color=PURPLE)

        # One-Shot Mode
        row5 = self._row(body, "One-Shot Mode")
        self._one_shot_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(row5, text="", variable=self._one_shot_var,
                      progress_color=ORANGE, button_color=TEXT_MAIN,
                      fg_color="#2D2D4E", command=self._on_cfg_change).pack(side="right")

        # Anti-Recoil
        row6 = self._row(body, "Anti-Recoil (Downward Nudge)")
        self._anti_recoil_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(row6, text="", variable=self._anti_recoil_var,
                      progress_color=ACCENT2, button_color=TEXT_MAIN,
                      fg_color="#2D2D4E", command=self._on_cfg_change).pack(side="right")

        self._recoil_str_var, self._recoil_str_lbl = self._slider_row(
            body, "  Recoil Strength (px)", 1, 15, 3,
            fmt="{:.0f}", steps=14, color=ACCENT2)

    # ── Tracking Mode Card (NEW) ──────────────────────────────────────────────
    def _build_tracking_mode_card(self, parent):
        body = self._card(parent, "Target Tracking & Reticle Dot", "📍")

        row = self._row(body, "Tracking Behavior")
        self._trk_mode_var = ctk.StringVar(value="Center Screen")
        self._trk_menu = ctk.CTkOptionMenu(
            row, variable=self._trk_mode_var,
            values=["Center Screen", "Mouse Snapshot (Toggle)", "Mouse Follow (Hold)"],
            fg_color=BG_SURFACE, button_color=ACCENT2, dropdown_fg_color=BG_CARD,
            font=FONT_BODY, text_color=TEXT_MAIN, width=175,
            command=self._on_cfg_change,
        )
        self._trk_menu.pack(side="right")

        # Visual Dot Toggle
        row_dot = self._row(body, "Visual Sample Dot")
        self._show_dot_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(row_dot, text="", variable=self._show_dot_var,
                      progress_color=CYAN, button_color=TEXT_MAIN,
                      fg_color="#2D2D4E", command=self._on_cfg_change).pack(side="right")

        # Dot Size
        self._dot_size_var, self._dot_size_lbl = self._slider_row(
            body, "  Dot Size", 1, 6, 2, fmt="{:.0f}px", steps=5, color=CYAN)

        # Dot Color
        dot_c_row = ctk.CTkFrame(body, fg_color="transparent")
        dot_c_row.pack(fill="x", pady=3)
        ctk.CTkLabel(dot_c_row, text="  Dot Color", font=FONT_BODY,
                     text_color=TEXT_DIM, width=180, anchor="w").pack(side="left")
        self._dot_swatch = tk.Canvas(dot_c_row, width=20, height=20, bg=CYAN,
                                     highlightthickness=1, highlightbackground=TEXT_DIM)
        self._dot_swatch.pack(side="right", padx=(0, 4))
        ctk.CTkButton(dot_c_row, text="Pick Color", width=75, height=24, font=FONT_SMALL,
                      fg_color=BG_SURFACE, hover_color=ACCENT,
                      command=self._pick_dot_color).pack(side="right", padx=2)

    # ── Detection card ────────────────────────────────────────────────────────
    def _build_detection_card(self, parent):
        body = self._card(parent, "Color Detection & Filters", "🔬")

        self._box_var, self._box_lbl = self._slider_row(
            body, "Detection Box Radius", 0, 11, 2, fmt="{:.0f}", steps=11)

        self._threshold_var, self._threshold_lbl = self._slider_row(
            body, "Color Threshold (Δ)", 5, 200, 63)

        # ── Color whitelist ───────────────────────────────────────────────────
        wl_row = ctk.CTkFrame(body, fg_color="transparent")
        wl_row.pack(fill="x", pady=(6, 2))
        ctk.CTkLabel(wl_row, text="Whitelist Color", font=FONT_BODY,
                     text_color=TEXT_DIM, width=180, anchor="w").pack(side="left")
        self._wl_swatch = tk.Canvas(wl_row, width=20, height=20, bg="#1A1A2E",
                                    highlightthickness=1, highlightbackground=TEXT_DIM)
        self._wl_swatch.pack(side="right", padx=(0, 4))
        ctk.CTkButton(wl_row, text="Pick", width=44, height=24, font=FONT_SMALL,
                      fg_color=BG_SURFACE, hover_color=ACCENT,
                      command=self._pick_whitelist).pack(side="right", padx=2)
        ctk.CTkButton(wl_row, text="✕", width=24, height=24, font=FONT_SMALL,
                      fg_color=BG_SURFACE, hover_color=RED,
                      command=self._clear_whitelist).pack(side="right", padx=2)

        self._wl_thresh_var, self._wl_thresh_lbl = self._slider_row(
            body, "  Whitelist Tolerance (Δ)", 5, 200, 150, color=GREEN)

        # ── Color blacklist ───────────────────────────────────────────────────
        bl_row = ctk.CTkFrame(body, fg_color="transparent")
        bl_row.pack(fill="x", pady=(6, 2))
        ctk.CTkLabel(bl_row, text="Blacklist Color", font=FONT_BODY,
                     text_color=TEXT_DIM, width=180, anchor="w").pack(side="left")
        self._bl_swatch = tk.Canvas(bl_row, width=20, height=20, bg="#1A1A2E",
                                    highlightthickness=1, highlightbackground=TEXT_DIM)
        self._bl_swatch.pack(side="right", padx=(0, 4))
        ctk.CTkButton(bl_row, text="Pick", width=44, height=24, font=FONT_SMALL,
                      fg_color=BG_SURFACE, hover_color=ACCENT,
                      command=self._pick_blacklist).pack(side="right", padx=2)
        ctk.CTkButton(bl_row, text="✕", width=24, height=24, font=FONT_SMALL,
                      fg_color=BG_SURFACE, hover_color=RED,
                      command=self._clear_blacklist).pack(side="right", padx=2)

        self._bl_thresh_var, self._bl_thresh_lbl = self._slider_row(
            body, "  Blacklist Tolerance (Δ)", 5, 200, 76, color=RED)

    # ── Zoom Magnifier Card (NEW) ─────────────────────────────────────────────
    def _build_magnifier_card(self, parent):
        body = self._card(parent, "Screen Center Zoom Magnifier", "🔍")

        row = self._row(body, "Enable Magnifier")
        self._zoom_enabled_var = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(row, text="", variable=self._zoom_enabled_var,
                      progress_color=ACCENT2, button_color=TEXT_MAIN,
                      fg_color="#2D2D4E", command=self._on_cfg_change).pack(side="right")

        row_k = self._row(body, "Magnifier Key")
        self._zoom_key_var = ctk.StringVar(value="c")
        ctk.CTkOptionMenu(
            row_k, variable=self._zoom_key_var,
            values=KEY_CHOICES,
            fg_color=BG_SURFACE, button_color=ACCENT2, dropdown_fg_color=BG_CARD,
            font=FONT_BODY, text_color=TEXT_MAIN, width=155,
            command=self._on_cfg_change,
        ).pack(side="right")

        row_m = self._row(body, "Magnifier Mode")
        self._zoom_mode_var = ctk.StringVar(value="Hold")
        ctk.CTkOptionMenu(
            row_m, variable=self._zoom_mode_var,
            values=["Hold", "Toggle"],
            fg_color=BG_SURFACE, button_color=ACCENT2, dropdown_fg_color=BG_CARD,
            font=FONT_BODY, text_color=TEXT_MAIN, width=155,
            command=self._on_cfg_change,
        ).pack(side="right")

        row_pos = self._row(body, "Display Position & Shape")
        self._zoom_pos_var = ctk.StringVar(value="Center Circle")
        ctk.CTkOptionMenu(
            row_pos, variable=self._zoom_pos_var,
            values=["Center Circle", "Top-Left Square"],
            fg_color=BG_SURFACE, button_color=ACCENT2, dropdown_fg_color=BG_CARD,
            font=FONT_BODY, text_color=TEXT_MAIN, width=155,
            command=self._on_cfg_change,
        ).pack(side="right")

        self._zoom_factor_var, self._zoom_factor_lbl = self._slider_row(
            body, "Zoom Ratio", 1.5, 4.0, 2.0, fmt="{:.1f}x", steps=25, color=ACCENT2)

        self._zoom_size_var, self._zoom_size_lbl = self._slider_row(
            body, "Lens / Square Size (px)", 20, 500, 180, fmt="{:.0f}px", steps=48, color=ACCENT2)

    # ── WASD card ─────────────────────────────────────────────────────────────
    def _build_wasd_card(self, parent):
        body = self._card(parent, "Counter-Strafe & Movement", "🕹️")

        # Auto-Strafe Stop
        row_ss = self._row(body, "Auto-Strafe Stop (CS2 Counter)")
        self._strafe_stop_var = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(row_ss, text="", variable=self._strafe_stop_var,
                      progress_color=ORANGE, button_color=TEXT_MAIN,
                      fg_color="#2D2D4E", command=self._on_cfg_change).pack(side="right")

        # Strafe Source (Both vs Detection vs Manual Key/Click)
        row_src = self._row(body, "  Activation Trigger")
        self._strafe_src_var = ctk.StringVar(value="Both (Detection + Key/Click)")
        ctk.CTkOptionMenu(
            row_src, variable=self._strafe_src_var,
            values=["Both (Detection + Key/Click)", "TriggerBot Detection Only", "Dedicated Key / Click Only"],
            fg_color=BG_SURFACE, button_color=ORANGE, dropdown_fg_color=BG_CARD,
            font=FONT_BODY, text_color=TEXT_MAIN, width=175,
            command=self._on_cfg_change,
        ).pack(side="right")

        # Dedicated Strafe Key / Click
        row_sk = self._row(body, "  Dedicated Strafe Key/Click")
        self._strafe_key_var = ctk.StringVar(value="mb1 (LMB)")
        ctk.CTkOptionMenu(
            row_sk, variable=self._strafe_key_var,
            values=KEY_CHOICES,
            fg_color=BG_SURFACE, button_color=ORANGE, dropdown_fg_color=BG_CARD,
            font=FONT_BODY, text_color=TEXT_MAIN, width=175,
            command=self._on_cfg_change,
        ).pack(side="right")

        # Strafe Mode (Snap-Tap vs Flexible vs Full Stop)
        row_sm = self._row(body, "  Counter-Strafe Behavior")
        self._strafe_mode_var = ctk.StringVar(value="Fast Reverse Snap (Hardware Sync)")
        ctk.CTkOptionMenu(
            row_sm, variable=self._strafe_mode_var,
            values=["Fast Reverse Snap (Hardware Sync)", "Flexible (Null-Cancel)", "Full Stop (Hard Release)"],
            fg_color=BG_SURFACE, button_color=ORANGE, dropdown_fg_color=BG_CARD,
            font=FONT_BODY, text_color=TEXT_MAIN, width=220,
            command=self._on_cfg_change,
        ).pack(side="right")

        # Strafe stop delay / hold duration
        self._strafe_delay_var, self._strafe_delay_lbl = self._slider_row(
            body, "  Counter Key Hold Duration (ms)", 5, 250, 45,
            fmt="{:.0f} ms", color=ORANGE)

        row = self._row(body, "WASD Velocity Compensation")
        self._wasd_var = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(row, text="", variable=self._wasd_var,
                      progress_color=GREEN, button_color=TEXT_MAIN,
                      fg_color="#2D2D4E", command=self._on_cfg_change).pack(side="right")

        self._wasd_vars = {}
        for k, label in [("w", "Forward (W)"), ("s", "Back (S)"),
                          ("a", "Left (A)"),   ("d", "Right (D)")]:
            var, _ = self._slider_row(body, f"  {label} Offset",
                                      0.5, 15.0, 2.5, fmt="{:.1f}", color=GREEN)
            self._wasd_vars[k] = var

    # ── Diagnostics card ──────────────────────────────────────────────────────
    def _build_diagnostics_card(self, parent):
        body = self._card(parent, "Live Diagnostics", "📊")

        sf = ctk.CTkFrame(body, fg_color="transparent")
        sf.pack(fill="x", pady=(0, 6))

        for attr, label in [("_baseline", "BASELINE"), ("_current", "CURRENT")]:
            fr = ctk.CTkFrame(sf, fg_color="transparent")
            fr.pack(side="left" if attr == "_baseline" else "right", expand=True)
            ctk.CTkLabel(fr, text=label, font=FONT_SMALL, text_color=TEXT_DIM).pack()
            c = tk.Canvas(fr, width=68, height=36, bg="#000000",
                          highlightthickness=1, highlightbackground=BG_SURFACE)
            c.pack(pady=2)
            lbl = ctk.CTkLabel(fr, text="(—, —, —)", font=FONT_MONO, text_color=TEXT_DIM)
            lbl.pack()
            setattr(self, f"{attr}_swatch", c)
            setattr(self, f"{attr}_rgb_lbl", lbl)

        dr = ctk.CTkFrame(body, fg_color="transparent")
        dr.pack(fill="x", pady=(2, 0))
        ctk.CTkLabel(dr, text="Δ Color Delta", font=FONT_SMALL,
                     text_color=TEXT_DIM).pack(side="left")
        self._delta_lbl = ctk.CTkLabel(dr, text="0.0", font=FONT_MONO,
                                       text_color=ACCENT2)
        self._delta_lbl.pack(side="right")

        self._delta_bar = ctk.CTkProgressBar(body, progress_color=ACCENT,
                                             fg_color=BG_SURFACE, height=8, corner_radius=4)
        self._delta_bar.set(0)
        self._delta_bar.pack(fill="x", pady=(3, 2))

        self._thresh_hint = ctk.CTkLabel(body, text="Threshold: —",
                                         font=FONT_SMALL, text_color=TEXT_DIM)
        self._thresh_hint.pack(anchor="e")

        br = ctk.CTkFrame(body, fg_color="transparent")
        br.pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(br, text="Sample Target", font=FONT_SMALL, text_color=TEXT_DIM).pack(side="left")
        self._pos_lbl = ctk.CTkLabel(br, text="X: —  Y: —",
                                     font=FONT_MONO, text_color=ACCENT2)
        self._pos_lbl.pack(side="right")

    # ── Color picker helpers ──────────────────────────────────────────────────
    def _pick_color(self):
        res = colorchooser.askcolor(title="Pick Color", parent=self)
        if res and res[0]:
            r, g, b = (int(x) for x in res[0])
            return (r, g, b)
        return None

    def _pick_dot_color(self):
        rgb = self._pick_color()
        if rgb:
            hex_c = "#{:02X}{:02X}{:02X}".format(*rgb)
            self._config["dot_color"] = hex_c
            self._dot_swatch.configure(bg=hex_c)
            self.engine.reload_config(self._config)

    def _pick_whitelist(self):
        rgb = self._pick_color()
        if rgb:
            self._config["color_whitelist"] = list(rgb)
            hex_c = "#{:02X}{:02X}{:02X}".format(*rgb)
            self._wl_swatch.configure(bg=hex_c)
            self.engine.reload_config(self._config)

    def _clear_whitelist(self):
        self._config["color_whitelist"] = None
        self._wl_swatch.configure(bg="#1A1A2E")
        self.engine.reload_config(self._config)

    def _pick_blacklist(self):
        rgb = self._pick_color()
        if rgb:
            self._config["color_blacklist"] = list(rgb)
            hex_c = "#{:02X}{:02X}{:02X}".format(*rgb)
            self._bl_swatch.configure(bg=hex_c)
            self.engine.reload_config(self._config)

    def _clear_blacklist(self):
        self._config["color_blacklist"] = None
        self._bl_swatch.configure(bg="#1A1A2E")
        self.engine.reload_config(self._config)

    # ── Config sync ───────────────────────────────────────────────────────────
    def _clean_key(self, raw_str: str) -> str:
        return raw_str.split(" ")[0]

    def _on_cfg_change(self, _=None):
        bs = int(self._box_var.get())
        self._box_lbl.configure(text=f"{bs*2+1}×{bs*2+1}")
        self._cooldown_lbl.configure(text=str(int(self._cooldown_var.get())))
        self._shots_lbl.configure(text=str(int(self._shots_var.get())))
        self._shot_delay_lbl.configure(text=str(int(self._shot_delay_var.get())))
        self._recoil_str_lbl.configure(text=str(int(self._recoil_str_var.get())))
        self._strafe_delay_lbl.configure(text=f"{int(self._strafe_delay_var.get())} ms")
        self._wl_thresh_lbl.configure(text=str(int(self._wl_thresh_var.get())))
        self._bl_thresh_lbl.configure(text=str(int(self._bl_thresh_var.get())))
        self._zoom_factor_lbl.configure(text=f"{float(self._zoom_factor_var.get()):.1f}x")
        self._zoom_size_lbl.configure(text=f"{int(self._zoom_size_var.get())}px")
        self._dot_size_lbl.configure(text=str(int(self._dot_size_var.get())))

        trk_map = {
            "Center Screen": "center",
            "Mouse Snapshot (Toggle)": "mouse_toggle",
            "Mouse Follow (Hold)": "mouse_hold",
        }
        trk_val = trk_map.get(self._trk_mode_var.get(), "center")

        sm_map = {
            "Fast Reverse Snap (Hardware Sync)": "snap_tap",
            "Flexible (Null-Cancel)": "flexible",
            "Full Stop (Hard Release)": "full_stop",
        }
        sm_val = sm_map.get(self._strafe_mode_var.get(), "snap_tap")

        src_map = {
            "Both (Detection + Key/Click)": "both",
            "TriggerBot Detection Only": "detection",
            "Dedicated Key / Click Only": "manual",
        }
        src_val = src_map.get(self._strafe_src_var.get(), "both")

        pos_map = {
            "Center Circle": "center",
            "Top-Left Square": "top_left",
        }
        zoom_pos_val = pos_map.get(self._zoom_pos_var.get(), "center")

        self._config.update({
            "trigger_key":          self._clean_key(self._trigger_key_var.get()),
            "action_key":           self._action_key_var.get(),
            "tracking_mode":        trk_val,
            "lock_to_center":       (trk_val == "center"),
            "show_tracking_dot":    self._show_dot_var.get(),
            "dot_size":             int(self._dot_size_var.get()),
            "dot_color":            self._config.get("dot_color", CYAN),
            "zoom_enabled":         self._zoom_enabled_var.get(),
            "zoom_key":             self._clean_key(self._zoom_key_var.get()),
            "zoom_mode":            self._zoom_mode_var.get().lower(),
            "zoom_position":        zoom_pos_val,
            "zoom_factor":          round(float(self._zoom_factor_var.get()), 2),
            "zoom_size":            int(self._zoom_size_var.get()),
            "freeze_keyboard":      self._freeze_kb_var.get(),
            "freeze_mouse":         self._freeze_mouse_var.get(),
            "cooldown_ms":          int(self._cooldown_var.get()),
            "detection_box_size":   bs,
            "color_threshold":      int(self._threshold_var.get()),
            "shots_per_detection":  int(self._shots_var.get()),
            "shot_delay_ms":        int(self._shot_delay_var.get()),
            "one_shot_mode":        self._one_shot_var.get(),
            "anti_recoil":          self._anti_recoil_var.get(),
            "recoil_strength":      int(self._recoil_str_var.get()),
            "wasd_compensation":    self._wasd_var.get(),
            "auto_strafe_stop":     self._strafe_stop_var.get(),
            "strafe_source":        src_val,
            "strafe_key":           self._clean_key(self._strafe_key_var.get()),
            "strafe_mode":          sm_val,
            "strafe_stop_delay_ms": int(self._strafe_delay_var.get()),
            "whitelist_threshold":  int(self._wl_thresh_var.get()),
            "blacklist_threshold":  int(self._bl_thresh_var.get()),
            "wasd_speed": {k: round(v.get(), 2) for k, v in self._wasd_vars.items()},
        })
        self.engine.reload_config(self._config)

    def _apply_config_to_ui(self):
        c = self._config
        _MB_LABELS = {
            "mb1": "mb1 (LMB)", "mb2": "mb2 (RMB)", "mb3": "mb3 (MMB)",
            "mb4": "mb4 (Side-Back)", "mb5": "mb5 (Side-Fwd)",
        }

        # Trigger key
        raw_tk = c.get("trigger_key", "alt")
        self._trigger_key_var.set(_MB_LABELS.get(raw_tk, raw_tk))

        # Action key
        self._action_key_var.set(c.get("action_key", "left"))

        # Tracking Mode
        trk_val = c.get("tracking_mode", "center" if c.get("lock_to_center", True) else "mouse_hold")
        trk_rev = {
            "center": "Center Screen",
            "mouse_toggle": "Mouse Snapshot (Toggle)",
            "mouse_hold": "Mouse Follow (Hold)",
        }
        self._trk_mode_var.set(trk_rev.get(trk_val, "Center Screen"))

        # Dot
        self._show_dot_var.set(c.get("show_tracking_dot", True))
        self._dot_size_var.set(c.get("dot_size", 2))
        dot_c = c.get("dot_color", CYAN)
        self._dot_swatch.configure(bg=dot_c)

        # Zoom
        self._zoom_enabled_var.set(c.get("zoom_enabled", False))
        raw_zk = c.get("zoom_key", "c")
        self._zoom_key_var.set(_MB_LABELS.get(raw_zk, raw_zk))
        self._zoom_mode_var.set(c.get("zoom_mode", "hold").capitalize())
        zoom_pos = c.get("zoom_position", "center")
        pos_rev = {
            "center": "Center Circle",
            "top_left": "Top-Left Square",
        }
        self._zoom_pos_var.set(pos_rev.get(zoom_pos, "Center Circle"))
        self._zoom_factor_var.set(c.get("zoom_factor", 2.0))
        self._zoom_size_var.set(c.get("zoom_size", 180))

        # Trigger settings
        self._freeze_kb_var.set(c.get("freeze_keyboard", False))
        self._freeze_mouse_var.set(c.get("freeze_mouse", False))
        self._cooldown_var.set(c.get("cooldown_ms", 50))
        self._box_var.set(c.get("detection_box_size", 2))
        self._threshold_var.set(c.get("color_threshold", 63))
        self._shots_var.set(c.get("shots_per_detection", 1))
        self._shot_delay_var.set(c.get("shot_delay_ms", 0))
        self._one_shot_var.set(c.get("one_shot_mode", true := True))
        self._anti_recoil_var.set(c.get("anti_recoil", True))
        self._recoil_str_var.set(c.get("recoil_strength", 3))

        # Movement
        self._strafe_stop_var.set(c.get("auto_strafe_stop", False))
        
        src_saved = c.get("strafe_source", "both")
        src_rev = {
            "both": "Both (Detection + Key/Click)",
            "detection": "TriggerBot Detection Only",
            "manual": "Dedicated Key / Click Only",
        }
        self._strafe_src_var.set(src_rev.get(src_saved, "Both (Detection + Key/Click)"))

        raw_sk = c.get("strafe_key", "mb1")
        self._strafe_key_var.set(_MB_LABELS.get(raw_sk, raw_sk))

        sm_saved = c.get("strafe_mode", "snap_tap")
        sm_rev = {
            "snap_tap": "Fast Reverse Snap (Hardware Sync)",
            "flexible": "Flexible (Null-Cancel)",
            "full_stop": "Full Stop (Hard Release)",
        }
        self._strafe_mode_var.set(sm_rev.get(sm_saved, "Fast Reverse Snap (Hardware Sync)"))
        self._strafe_delay_var.set(c.get("strafe_stop_delay_ms", 25))
        self._wasd_var.set(c.get("wasd_compensation", False))

        # Tolerances
        self._wl_thresh_var.set(c.get("whitelist_threshold", 150))
        self._bl_thresh_var.set(c.get("blacklist_threshold", 76))

        sp = c.get("wasd_speed", {"w": 2.5, "a": 2.5, "s": 2.5, "d": 2.5})
        for k, var in self._wasd_vars.items():
            var.set(sp.get(k, 2.5))

        # Swatches
        wl = c.get("color_whitelist")
        if wl:
            self._wl_swatch.configure(bg="#{:02X}{:02X}{:02X}".format(*wl))
        else:
            self._wl_swatch.configure(bg="#1A1A2E")

        bl = c.get("color_blacklist")
        if bl:
            self._bl_swatch.configure(bg="#{:02X}{:02X}{:02X}".format(*bl))
        else:
            self._bl_swatch.configure(bg="#1A1A2E")

        self._on_cfg_change()

    # ── Master toggle ─────────────────────────────────────────────────────────
    def _on_master_toggle(self):
        enabled = self._master_var.get()
        self.engine.enabled = enabled
        if not enabled:
            self._status_badge.configure(text="● DISABLED", text_color=TEXT_DIM)

    # ── Diagnostics loop ──────────────────────────────────────────────────────
    def _schedule_diag(self):
        if not self._diag_running:
            return
        try:
            self._refresh_diag()
        except Exception:
            pass
        self.after(70, self._schedule_diag)

    def _refresh_diag(self):
        status = self.engine.diag_status
        if status == "ACTIVE":
            self._status_badge.configure(text="🔥 FIRING", text_color=RED)
        elif status == "MONITORING":
            self._status_badge.configure(text="● MONITORING", text_color=GREEN)
        elif self._master_var.get():
            self._status_badge.configure(text="● MONITORING", text_color=GREEN)
        else:
            self._status_badge.configure(text="● DISABLED", text_color=TEXT_DIM)

        cur = self.engine.diag_current_color
        bas = self.engine.diag_baseline_color
        self._current_swatch.configure(bg="#{:02X}{:02X}{:02X}".format(*cur))
        self._baseline_swatch.configure(bg="#{:02X}{:02X}{:02X}".format(*bas))
        self._current_rgb_lbl.configure(text=f"({cur[0]}, {cur[1]}, {cur[2]})")
        self._baseline_rgb_lbl.configure(text=f"({bas[0]}, {bas[1]}, {bas[2]})")

        delta  = self.engine.diag_delta
        thresh = float(self._config.get("color_threshold", 30))
        self._delta_lbl.configure(text=f"{delta:.1f}")
        self._delta_bar.set(min(1.0, delta / max(thresh * 2, 1)))
        self._thresh_hint.configure(text=f"Threshold: {int(thresh)}")

        bar_color = GREEN if delta < thresh * 0.6 else (ORANGE if delta < thresh else RED)
        self._delta_bar.configure(progress_color=bar_color)

        pos = getattr(self.engine, "diag_sample_pos", (0, 0))
        self._pos_lbl.configure(text=f"X: {pos[0]}  Y: {pos[1]}")

    # ── Overlay toggle ────────────────────────────────────────────────────────
    def _toggle_overlay(self):
        if self._overlay and self._overlay.winfo_exists():
            self._overlay.on_close()
            self._overlay.destroy()
            self._overlay = None
        else:
            self._overlay = TriggerOverlay(self.engine)

    # ── Profile system ────────────────────────────────────────────────────────
    def _get_profiles(self):
        try:
            files = [f[:-5] for f in os.listdir(PROFILES_DIR) if f.endswith(".json")]
            return sorted(files) if files else ["(none)"]
        except Exception:
            return ["(none)"]

    def _refresh_profile_menu(self):
        profiles = self._get_profiles()
        self._profile_menu.configure(values=profiles)
        if profiles:
            self._profile_var.set(profiles[0])

    def _on_profile_load(self):
        name = self._profile_var.get()
        if not name or name == "(none)":
            return
        path = os.path.join(PROFILES_DIR, f"{name}.json")
        try:
            with open(path) as f:
                self._config = json.load(f)
            self._apply_config_to_ui()
            self.engine.reload_config(self._config)
            self._footer_label.configure(text=f"✓ Loaded profile: {name}", text_color=GREEN)
            self.after(2000, lambda: self._footer_label.configure(
                text="TriggerBot Pro  •  Precision Edition", text_color=TEXT_DIM))
        except Exception as e:
            messagebox.showerror("Load Error", str(e))

    def _on_profile_save_as(self):
        name = simpledialog.askstring("Save Profile", "Enter profile name:", parent=self)
        if not name:
            return
        name = "".join(c for c in name if c.isalnum() or c in "_- ")
        path = os.path.join(PROFILES_DIR, f"{name}.json")
        self._on_cfg_change()
        with open(path, "w") as f:
            json.dump(self._config, f, indent=4)
        self._refresh_profile_menu()
        self._profile_var.set(name)
        self._footer_label.configure(text=f"✓ Saved profile: {name}", text_color=GREEN)
        self.after(2000, lambda: self._footer_label.configure(
            text="TriggerBot Pro  •  Precision Edition", text_color=TEXT_DIM))

    def _on_profile_delete(self):
        name = self._profile_var.get()
        if not name or name == "(none)":
            return
        if not messagebox.askyesno("Delete Profile", f"Delete profile '{name}'?"):
            return
        path = os.path.join(PROFILES_DIR, f"{name}.json")
        try:
            os.remove(path)
            self._refresh_profile_menu()
            self._footer_label.configure(text=f"✓ Deleted: {name}", text_color=RED)
        except Exception as e:
            messagebox.showerror("Delete Error", str(e))

    # ── Button handlers ───────────────────────────────────────────────────────
    def _open_kofi(self):
        try:
            webbrowser.open_new_tab("https://ko-fi.com/dragomvevi")
        except Exception:
            pass

    def _on_save(self):
        self._on_cfg_change()
        self._save_config()
        self._footer_label.configure(text="✓ Configuration saved to disk!", text_color=GREEN)
        self.after(2000, lambda: self._footer_label.configure(
            text="TriggerBot Pro  •  Precision Edition", text_color=TEXT_DIM))

    def _on_reset(self):
        self._config = {
            "trigger_key": "alt", "action_key": "left",
            "tracking_mode": "center", "lock_to_center": True,
            "show_tracking_dot": True, "dot_size": 6, "dot_color": CYAN,
            "zoom_enabled": False, "zoom_key": "c", "zoom_mode": "hold",
            "zoom_position": "center",
            "zoom_factor": 2.0, "zoom_size": 180,
            "detection_box_size": 2, "color_threshold": 63,
            "cooldown_ms": 50, "freeze_keyboard": False, "freeze_mouse": False,
            "shots_per_detection": 1, "shot_delay_ms": 0,
            "one_shot_mode": True,
            "anti_recoil": True, "recoil_strength": 3,
            "wasd_compensation": False,
            "auto_strafe_stop": False, "strafe_stop_delay_ms": 30,
            "color_whitelist": None, "whitelist_threshold": 150,
            "color_blacklist": None, "blacklist_threshold": 76,
            "wasd_speed": {"w": 2.5, "a": 2.5, "s": 2.5, "d": 2.5},
        }
        self._apply_config_to_ui()
        self.engine.reload_config(self._config)

    def _on_close(self):
        self._diag_running = False
        if self._overlay and self._overlay.winfo_exists():
            self._overlay.on_close()
        if self._magnifier:
            self._magnifier.destroy()
        if self._dot_overlay:
            self._dot_overlay.destroy()
        self.engine.stop()
        self.destroy()
