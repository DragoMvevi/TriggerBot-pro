"""
engine.py — Optimized Core Engine v3
=====================================
Key fix vs v2:
  - Hook callback is now ZERO-I/O — only flips boolean flags.
    Screen capture was previously happening inside the hook callback,
    which caused Windows to freeze keyboard input while waiting.
  - Baseline capture moved entirely into the main loop (uses _needs_baseline flag).
  - mss instance is never touched from the hook thread.
  - Hook proc wrapped in try/except — any bug can't hang the keyboard.
"""

import threading
import time
import ctypes
import ctypes.wintypes
import mss

# ULONG_PTR is 8 bytes on 64-bit Windows — critical for correct INPUT struct sizing
ULONG_PTR = ctypes.c_size_t

# ─── Windows API ──────────────────────────────────────────────────────────────
user32   = ctypes.WinDLL("user32",   use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

SendInput           = user32.SendInput
GetCursorPos        = user32.GetCursorPos
GetAsyncKeyState    = user32.GetAsyncKeyState
GetSystemMetrics    = user32.GetSystemMetrics
CallNextHookEx      = user32.CallNextHookEx
SetWindowsHookExW   = user32.SetWindowsHookExW
UnhookWindowsHookEx = user32.UnhookWindowsHookEx
PeekMessageW        = user32.PeekMessageW
TranslateMessage    = user32.TranslateMessage
DispatchMessageW    = user32.DispatchMessageW
GetModuleHandleW    = kernel32.GetModuleHandleW
PostThreadMessageW  = user32.PostThreadMessageW

# MapVirtualKeyW: translates Virtual Key codes → hardware scan codes (needed for DirectInput games)
MapVirtualKeyW              = user32.MapVirtualKeyW
MapVirtualKeyW.argtypes     = [ctypes.c_uint, ctypes.c_uint]
MapVirtualKeyW.restype      = ctypes.c_uint

# ─── ctypes input structs ─────────────────────────────────────────────────────
INPUT_MOUSE    = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE        = 0x0001
MOUSEEVENTF_LEFTDOWN    = 0x0002
MOUSEEVENTF_LEFTUP      = 0x0004
MOUSEEVENTF_RIGHTDOWN   = 0x0008
MOUSEEVENTF_RIGHTUP     = 0x0010
MOUSEEVENTF_ABSOLUTE    = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
KEYEVENTF_KEYUP         = 0x0002
KEYEVENTF_SCANCODE      = 0x0008   # use hardware scan code instead of virtual key

WH_KEYBOARD_LL = 13
WM_KEYDOWN     = 0x0100
WM_KEYUP       = 0x0101
WM_SYSKEYDOWN  = 0x0104
WM_SYSKEYUP    = 0x0105
WM_QUIT        = 0x0012
PM_REMOVE      = 0x0001


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx",          ctypes.c_long),
        ("dy",          ctypes.c_long),
        ("mouseData",   ctypes.c_ulong),
        ("dwFlags",     ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),   # FIX: was c_ulong (4B), must be ULONG_PTR (8B on x64)
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk",         ctypes.c_ushort),
        ("wScan",       ctypes.c_ushort),
        ("dwFlags",     ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),   # FIX: was c_ulong (4B), must be ULONG_PTR (8B on x64)
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("_input", _INPUT_UNION)]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode",      ctypes.c_ulong),
        ("scanCode",    ctypes.c_ulong),
        ("flags",       ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_ulong),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_long, ctypes.c_int, ctypes.c_uint,
    ctypes.POINTER(KBDLLHOOKSTRUCT),
)

# ─── Key mappings ─────────────────────────────────────────────────────────────
VK_TRIGGER_SETS: dict = {
    # Modifier keys
    "shift":    frozenset({0x10, 0xA0, 0xA1}),   # VK_SHIFT / L / R
    "ctrl":     frozenset({0x11, 0xA2, 0xA3}),
    "alt":      frozenset({0x12, 0xA4, 0xA5}),
    "caps_lock":frozenset({0x14}),
    # Letters & actions
    "x":        frozenset({0x58}),
    "c":        frozenset({0x43}),
    "v":        frozenset({0x56}),
    "f":        frozenset({0x46}),
    "g":        frozenset({0x47}),
    "h":        frozenset({0x48}),
    "t":        frozenset({0x54}),
    "z":        frozenset({0x5A}),
    "e":        frozenset({0x45}),
    "q":        frozenset({0x51}),
    "r":        frozenset({0x52}),
    "space":    frozenset({0x20}),
    # Function keys
    "f1":       frozenset({0x70}),
    "f2":       frozenset({0x71}),
    "f3":       frozenset({0x72}),
    "f4":       frozenset({0x73}),
    # Mouse buttons (polled via GetAsyncKeyState, not the keyboard hook)
    "mb1":      frozenset({0x01}),   # Left mouse button
    "mb2":      frozenset({0x02}),   # Right mouse button
    "mb3":      frozenset({0x04}),   # Middle mouse button
    "mb4":      frozenset({0x05}),   # X1 / Back side button
    "mb5":      frozenset({0x06}),   # X2 / Forward side button
}

# Keys that cannot be detected by WH_KEYBOARD_LL — polled in the main loop instead
MOUSE_TRIGGER_KEYS: frozenset = frozenset({"mb1", "mb2", "mb3", "mb4", "mb5"})

WASD_VK: dict = {
    0x57: "w",    0x41: "a",    0x53: "s",    0x44: "d",
    0x26: "up",   0x25: "left", 0x28: "down", 0x27: "right",
}

# Reverse map: name → VK code (for synthetic keyup on deactivation)
WASD_NAME_TO_VK: dict = {v: k for k, v in WASD_VK.items()}

ACTION_VK: dict = {
    "left":  None,
    "right": None,
    "space": 0x20,
    "e":     0x45,
    "r":     0x52,
    "f":     0x46,
    "q":     0x51,
}


# ─── Engine ───────────────────────────────────────────────────────────────────
class TriggerEngine:
    """
    Two daemon threads:
      _hook_thread  → WH_KEYBOARD_LL hook + Windows message pump.
                      ONLY flips boolean flags — no I/O whatsoever.
      _main_thread  → 200 Hz loop: cursor lock, baseline capture, color
                      detection, burst fire.
    """

    def __init__(self, config: dict):
        self.config = dict(config)

        # ── Screen geometry (precomputed) ──────────────────────────────────
        self._sw = GetSystemMetrics(0)
        self._sh = GetSystemMetrics(1)
        self._nx = 65535.0 / max(self._sw - 1, 1)
        self._ny = 65535.0 / max(self._sh - 1, 1)

        # ── Runtime state ──────────────────────────────────────────────────
        self.enabled          = False
        self.active           = False
        self.freeze_keyboard  = bool(config.get("freeze_keyboard", False))
        self.freeze_mouse     = bool(config.get("freeze_mouse",    False))
        self.zoom_active      = False
        self._zoom_held       = False
        self._burst_running   = False
        self._trigger_held    = False
        self._strafe_key_held = False
        self._abort_strafe_event  = threading.Event()
        self._current_counter_vks = set()
        self._strafe_orig_vks     = set()
        self._suppressed_vks      = set()

        # Flag: main loop should capture baseline on next tick
        self._needs_baseline  = False

        self._lock_x: float   = float(self._sw * 0.5)
        self._lock_y: float   = float(self._sh * 0.5)

        self._baseline_color  = None
        self._last_fire_time  = 0.0

        self._held_wasd: set  = set()

        # ── Diagnostics (GUI / Overlays read) ──────────────────────────────
        self.diag_current_color  = (0, 0, 0)
        self.diag_baseline_color = (0, 0, 0)
        self.diag_delta          = 0.0
        self.diag_status         = "DISABLED"
        self.diag_sample_pos     = (self._sw // 2, self._sh // 2)

        # ── Threads ────────────────────────────────────────────────────────
        self._stop_event  = threading.Event()
        self._main_thread = None
        self._hook_thread = None
        self._hook_id     = None
        self._hook_ref    = None   # keep reference — prevents GC of ctypes callback

        # ── Pre-allocated INPUT structs (zero allocation in hot loop) ──────
        self._inp_size = ctypes.sizeof(INPUT)

        # Cursor move
        self._move_arr = (INPUT * 1)()
        self._move_arr[0].type = INPUT_MOUSE
        self._move_arr[0]._input.mi.dwFlags = (
            MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
        )

        # Left click
        self._lclick_arr = (INPUT * 2)()
        self._lclick_arr[0].type = INPUT_MOUSE
        self._lclick_arr[0]._input.mi.dwFlags = MOUSEEVENTF_LEFTDOWN
        self._lclick_arr[1].type = INPUT_MOUSE
        self._lclick_arr[1]._input.mi.dwFlags = MOUSEEVENTF_LEFTUP

        # Right click
        self._rclick_arr = (INPUT * 2)()
        self._rclick_arr[0].type = INPUT_MOUSE
        self._rclick_arr[0]._input.mi.dwFlags = MOUSEEVENTF_RIGHTDOWN
        self._rclick_arr[1].type = INPUT_MOUSE
        self._rclick_arr[1]._input.mi.dwFlags = MOUSEEVENTF_RIGHTUP

        # Key tap (wVk filled at fire time)
        self._key_arr = (INPUT * 2)()
        self._key_arr[0].type = INPUT_KEYBOARD
        self._key_arr[1].type = INPUT_KEYBOARD
        self._key_arr[1]._input.ki.dwFlags = KEYEVENTF_KEYUP

        # Single key event (wVk + wScan with KEYEVENTF_SCANCODE)
        self._single_key_arr = (INPUT * 1)()
        self._single_key_arr[0].type = INPUT_KEYBOARD

        # Relative mouse move (no ABSOLUTE flag) — used for anti-recoil
        self._rel_move_arr = (INPUT * 1)()
        self._rel_move_arr[0].type = INPUT_MOUSE
        self._rel_move_arr[0]._input.mi.dwFlags = MOUSEEVENTF_MOVE

        # Tracks which counter-strafe keys the engine is currently holding
        self._strafe_counter_keys: set = set()

        # mss handle (valid only inside _main_loop)
        self._sct = None

    # ── Public ────────────────────────────────────────────────────────────────
    def start(self):
        self._stop_event.clear()
        self._main_thread = threading.Thread(
            target=self._main_loop, daemon=True, name="TriggerMain"
        )
        self._hook_thread = threading.Thread(
            target=self._run_hook, daemon=True, name="TriggerHook"
        )
        self._main_thread.start()
        self._hook_thread.start()

    def stop(self):
        self._stop_event.set()
        tid = getattr(self._hook_thread, "ident", None)
        if tid:
            PostThreadMessageW(tid, WM_QUIT, 0, 0)

    def reload_config(self, config: dict):
        self.config          = dict(config)
        self.freeze_keyboard = bool(config.get("freeze_keyboard", False))
        self.freeze_mouse    = bool(config.get("freeze_mouse",    False))

    # ── Hook thread (zero I/O — flag flips only) ──────────────────────────────
    def _run_hook(self):

        def hook_proc(nCode, wParam, lParam):
            try:
                if nCode >= 0:
                    vk    = lParam.contents.vkCode
                    is_up = (wParam == WM_KEYUP   or wParam == WM_SYSKEYUP)
                    is_dn = (wParam == WM_KEYDOWN  or wParam == WM_SYSKEYDOWN)

                    # ── Zoom key handling ─────────────────────────────────
                    zoom_enabled = self.config.get("zoom_enabled", False)
                    zoom_key     = self.config.get("zoom_key", "c")
                    if zoom_enabled and zoom_key not in MOUSE_TRIGGER_KEYS:
                        z_vks = VK_TRIGGER_SETS.get(zoom_key, frozenset())
                        if vk in z_vks:
                            z_mode = self.config.get("zoom_mode", "hold")
                            if z_mode == "toggle":
                                if is_dn and not self._zoom_held:
                                    self._zoom_held = True
                                    self.zoom_active = not self.zoom_active
                                elif is_up:
                                    self._zoom_held = False
                            else: # hold mode
                                if is_dn:
                                    self.zoom_active = True
                                elif is_up:
                                    self.zoom_active = False
                            return CallNextHookEx(self._hook_id or 0, nCode, wParam, lParam)

                    # ── Dedicated counter-strafe key handling ─────────────
                    strafe_enabled = self.config.get("auto_strafe_stop", False)
                    strafe_source  = self.config.get("strafe_source", "both")
                    if strafe_enabled and strafe_source in ("manual", "both"):
                        s_key = self.config.get("strafe_key", "mb1")
                        if s_key not in MOUSE_TRIGGER_KEYS:
                            s_vks = VK_TRIGGER_SETS.get(s_key, frozenset())
                            if vk in s_vks:
                                if is_dn and not self._strafe_key_held:
                                    self._strafe_key_held = True
                                    if self.enabled:
                                        self._trigger_manual_strafe_stop()
                                elif is_up:
                                    self._strafe_key_held = False
                                return CallNextHookEx(self._hook_id or 0, nCode, wParam, lParam)

                    # ── Trigger key (keyboard only — mouse buttons handled by polling) ─
                    trigger_key = self.config.get("trigger_key", "shift")
                    if trigger_key not in MOUSE_TRIGGER_KEYS:
                        t_vks = VK_TRIGGER_SETS.get(trigger_key, VK_TRIGGER_SETS["shift"])
                        if vk in t_vks:
                            trk_mode = self.config.get("tracking_mode", "center" if self.config.get("lock_to_center", True) else "mouse_hold")
                            if trk_mode == "mouse_toggle":
                                if is_dn and not self._trigger_held:
                                    self._trigger_held = True
                                    if self.enabled and not self._burst_running:
                                        if self.active:
                                            self._deactivate()
                                        else:
                                            self._activate_fast()
                                elif is_up:
                                    self._trigger_held = False
                            else: # hold modes (center or mouse_hold)
                                if is_dn and not self._trigger_held:
                                    self._trigger_held = True
                                    if self.enabled and not self.active and not self._burst_running:
                                        self._activate_fast()
                                elif is_up:
                                    self._trigger_held = False
                                    if self.active or self._burst_running:
                                        self._deactivate()
                            return CallNextHookEx(self._hook_id or 0, nCode, wParam, lParam)

                    # ── WASD tracking (Physical keys only — ignores bot-injected keys) ──
                    is_injected = (lParam.contents.flags & 0x10) != 0
                    name = WASD_VK.get(vk)
                    if name is not None and not is_injected:
                        if is_dn:
                            self._held_wasd.add(name)
                        elif is_up:
                            self._held_wasd.discard(name)

                    # ── Fast Reverse Snap Key Suppression (Forces true release of original key) ──
                    if not is_injected and vk in self._suppressed_vks:
                        return 1  # Block physical key events/auto-repeat from reaching the game!

                    # ── Keyboard suppress (optional) ──────────────────────
                    if self.freeze_keyboard and self.active:
                        if not is_injected:
                            return 1

            except Exception:
                pass   # never let a bug crash/stall the keyboard hook

            return CallNextHookEx(self._hook_id or 0, nCode, wParam, lParam)

        self._hook_ref = HOOKPROC(hook_proc)
        self._hook_id  = SetWindowsHookExW(
            WH_KEYBOARD_LL, self._hook_ref, None, 0
        )
        if not self._hook_id:
            err = ctypes.get_last_error()
            print(f"[TriggerEngine] WARNING: keyboard hook installation failed! WinError={err}")
        else:
            print(f"[TriggerEngine] Keyboard hook installed (id={self._hook_id})")

        msg = ctypes.wintypes.MSG()
        while not self._stop_event.is_set():
            r = PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE)
            if r > 0:
                if msg.message == WM_QUIT:
                    break
                TranslateMessage(ctypes.byref(msg))
                DispatchMessageW(ctypes.byref(msg))
            else:
                time.sleep(0.001)

        if self._hook_id:
            UnhookWindowsHookEx(self._hook_id)
            self._hook_id = None
            print("[TriggerEngine] Keyboard hook removed.")

    # ── Activation (called from hook thread — MUST be instant, no I/O) ────────
    def _activate_fast(self):
        """Set lock position and raise flag. No screen capture here."""
        trk_mode = self.config.get("tracking_mode", "center" if self.config.get("lock_to_center", True) else "mouse_hold")

        if trk_mode == "center":
            self._lock_x = float(self._sw * 0.5)
            self._lock_y = float(self._sh * 0.5)
        else:
            pt = ctypes.wintypes.POINT()
            GetCursorPos(ctypes.byref(pt))
            self._lock_x = float(pt.x)
            self._lock_y = float(pt.y)

        self.diag_sample_pos = (int(self._lock_x), int(self._lock_y))

        # Send synthetic key-UPs for any keys already held BEFORE freeze starts.
        if self.freeze_keyboard and self._held_wasd:
            for name in list(self._held_wasd):
                vk = WASD_NAME_TO_VK.get(name)
                if vk:
                    self._send_key_event(vk, key_up=True)
            print(f"[TriggerEngine] Sent synthetic keyups for: {self._held_wasd}")

        self._needs_baseline = True   # main loop will grab this
        self._baseline_color = None
        self.diag_status     = "MONITORING"
        self.active          = True
        print(f"[TriggerEngine] Activated [{trk_mode}] — lock=({int(self._lock_x)}, {int(self._lock_y)})")

    def _deactivate(self):
        self.active          = False
        self._needs_baseline = False
        self._baseline_color = None
        self.diag_status     = "DISABLED"

        if self.freeze_keyboard and self._held_wasd:
            for name in list(self._held_wasd):
                vk = WASD_NAME_TO_VK.get(name)
                if vk:
                    self._send_key_event(vk, key_up=False)
            print(f"[TriggerEngine] Sent synthetic keydowns for: {self._held_wasd}")

        print("[TriggerEngine] Deactivated.")

    # ── Cursor move (optimized, pre-allocated struct) ─────────────────────────
    def _move_cursor(self, x: float, y: float):
        mi    = self._move_arr[0]._input.mi
        mi.dx = int(x * self._nx)
        mi.dy = int(y * self._ny)
        SendInput(1, self._move_arr, self._inp_size)

    # ── Screen sampling ───────────────────────────────────────────────────────
    def _sample_color(self, cx: int, cy: int) -> tuple:
        half = max(0, int(self.config.get("detection_box_size", 2)))
        left   = max(0, cx - half)
        top    = max(0, cy - half)
        right  = min(self._sw, cx + half + 1)
        bottom = min(self._sh, cy + half + 1)

        img = self._sct.grab({
            "left": left, "top": top,
            "width": max(1, right - left), "height": max(1, bottom - top),
        })
        raw = img.raw   # BGRA bytes
        n   = len(raw) >> 2
        if n == 0:
            return (0, 0, 0)
        # Slice-sum: no Python-level loop, ~10× faster
        r = sum(raw[2::4]) // n
        g = sum(raw[1::4]) // n
        b = sum(raw[0::4]) // n
        return (r, g, b)

    @staticmethod
    def _color_delta(c1: tuple, c2: tuple) -> float:
        dr = c1[0] - c2[0]
        dg = c1[1] - c2[1]
        db = c1[2] - c2[2]
        return (dr*dr + dg*dg + db*db) ** 0.5

    # ── Cursor relative move (anti-recoil) ────────────────────────────────
    def _move_cursor_relative(self, dx: int, dy: int):
        """Send a relative mouse movement (in raw pixels, no coordinate transform)."""
        mi    = self._rel_move_arr[0]._input.mi
        mi.dx = dx
        mi.dy = dy
        SendInput(1, self._rel_move_arr, self._inp_size)

    # ── Hardware Scan-Code Keyboard Simulation ────────────────────────────
    def _send_key_event(self, vk: int, key_up: bool = False):
        """Sends both virtual key and hardware scan-code so RawInput and DirectInput register the key release."""
        scan = MapVirtualKeyW(vk, 0)
        flags = KEYEVENTF_SCANCODE
        if key_up:
            flags |= KEYEVENTF_KEYUP
        self._single_key_arr[0]._input.ki.wVk    = vk
        self._single_key_arr[0]._input.ki.wScan   = scan
        self._single_key_arr[0]._input.ki.dwFlags = flags
        self._single_key_arr[0]._input.ki.dwExtraInfo = 0
        SendInput(1, self._single_key_arr, self._inp_size)

    # ── Auto-strafe stop helpers ────────────────────────────────────────
    _COUNTER_KEY = {"w": "s", "s": "w", "a": "d", "d": "a"}

    def _trigger_strafe_brake_pulse(self):
        """Executes a clean, isolated counter-strafe pulse.
        - 'flexible': Injects counter key (D) WITHOUT releasing held key (A) (Null-Cancel).
        - 'snap_tap': 4-Step Pro Fast Counter: Cuts D -> Micro-taps A (12ms) -> Releases A -> Re-presses D.
        - 'full_stop': Cuts held key (A), injects counter key (D), leaves character stopped.
        """
        active_keys = set(self._held_wasd)

        if not active_keys:
            print("[STRAFE] Inactive (No movement keys pressed).")
            return

        # If user is already pressing opposing keys (e.g. A+D), skip
        if ("a" in active_keys and "d" in active_keys) or ("w" in active_keys and "s" in active_keys):
            print(f"[STRAFE SKIPPED] Opposing keys already held: {active_keys}")
            return

        mode = self.config.get("strafe_mode", "flexible")
        
        if mode == "snap_tap":
            # ── 4-STEP FAST REVERSE SNAP (Cuts D -> Brakes A -> Releases A -> Resumes D) ──
            # Step 1: Let go of original key(s) and block physical auto-repeats
            orig_vks = []
            opp_vks  = []
            injected_names = []
            for name in list(active_keys):
                opp = self._COUNTER_KEY.get(name)
                if opp and opp not in active_keys:
                    orig_vk = WASD_NAME_TO_VK.get(name)
                    opp_vk  = WASD_NAME_TO_VK.get(opp)
                    if orig_vk:
                        self._suppressed_vks.add(orig_vk)             # 1. Block physical D auto-repeats!
                        self._send_key_event(orig_vk, key_up=True)   # 1. Let go of D completely!
                        orig_vks.append((name, orig_vk))
                    if opp_vk:
                        opp_vks.append((opp, opp_vk))
                        injected_names.append(opp.upper())

            # 1ms gap to ensure game engine processes KeyUp D first
            time.sleep(0.001)

            # Step 2: Press counter key A alone (D remains 100% RELEASED)
            for opp, opp_vk in opp_vks:
                self._send_key_event(opp_vk, key_up=False)           # 2. Press A (Counter Key)

            # Step 3: Hold counter key A for the slider duration (D stays released!)
            fast_brake_ms = max(5, min(300, int(self.config.get("strafe_stop_delay_ms", 15))))
            print(f"[FAST SNAP TRIGGERED] Movement: {list(active_keys)} -> Active Braking: {injected_names} for {fast_brake_ms}ms (Original Released)")
            
            start_time = time.perf_counter()
            target_sec = fast_brake_ms / 1000.0
            early_cut = False

            while (time.perf_counter() - start_time) < target_sec:
                # Instant abort if player presses ANY new movement key (e.g. W, S, A, D) or opposite direction!
                if (self._held_wasd - active_keys) or any(self._COUNTER_KEY.get(k) in self._held_wasd for k in active_keys):
                    early_cut = True
                    break
                time.sleep(0.001)

            # Step 4: Always cleanly release all injected synthetic counter keys
            for opp, opp_vk in opp_vks:
                self._send_key_event(opp_vk, key_up=True)

            # Step 5: Un-suppress and seamlessly re-assert whatever keys the player is physically pressing
            for name, orig_vk in orig_vks:
                self._suppressed_vks.discard(orig_vk)

            for name in list(self._held_wasd):
                vk = WASD_NAME_TO_VK.get(name)
                if vk:
                    self._send_key_event(vk, key_up=False)

            if early_cut:
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                print(f"[FAST SNAP ADAPTIVE] Complex movement override ({list(self._held_wasd)}) -> Cut early to {elapsed_ms:.1f}ms.")
            else:
                print(f"[FAST SNAP FINISHED] Completed {fast_brake_ms}ms pulse -> Maintained active keys {list(self._held_wasd)}.")
            return

        # ── FLEXIBLE & FULL-STOP MODES ─────────────────────────────────────────
        brake_ms = max(5, min(300, int(self.config.get("strafe_stop_delay_ms", 45))))
        counter_vks = []
        injected_names = []

        # Step 1: In full_stop mode, release original keys; otherwise keep held keys untouched
        for name in list(active_keys):
            opp = self._COUNTER_KEY.get(name)
            if opp and opp not in active_keys:
                orig_vk = WASD_NAME_TO_VK.get(name)
                opp_vk  = WASD_NAME_TO_VK.get(opp)
                if mode == "full_stop" and orig_vk:
                    self._send_key_event(orig_vk, key_up=True)
                if opp_vk:
                    self._send_key_event(opp_vk, key_up=False)
                    counter_vks.append(opp_vk)
                    injected_names.append(opp.upper())

        print(f"[STRAFE TRIGGERED] Mode: {mode.upper()} | Movement: {list(active_keys)} -> Injecting Counter: {injected_names} for {brake_ms}ms")

        # Step 2: Adaptive Hold Duration (Holds for full duration unless player physically presses counter key)
        start_time = time.perf_counter()
        target_sec = brake_ms / 1000.0
        early_cut = False

        while (time.perf_counter() - start_time) < target_sec:
            # Check if user physically pressed the counter key or a new direction
            if any(self._COUNTER_KEY.get(k) in self._held_wasd for k in active_keys):
                early_cut = True
                break
            time.sleep(0.002)

        # Step 3: Cleanly release injected counter keys (except keys the player is physically holding!)
        for name in list(active_keys):
            opp = self._COUNTER_KEY.get(name)
            opp_vk = WASD_NAME_TO_VK.get(opp)
            if opp_vk and opp_vk in counter_vks:
                if opp not in self._held_wasd:
                    self._send_key_event(opp_vk, key_up=True)
                else:
                    print(f"[STRAFE HANDOFF] Physical key '{opp.upper()}' is held by player -> Preserved KeyDown with zero interruption!")

        if early_cut:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            print(f"[STRAFE ADAPTIVE] Player initiated direction swap -> Cut hold time early to {elapsed_ms:.1f}ms for instant control!")
        else:
            print(f"[STRAFE FINISHED] Completed {brake_ms}ms counter pulse -> Released {injected_names}.")

    def _trigger_manual_strafe_stop(self):
        """Runs the braking pulse asynchronously on standalone key/click."""
        threading.Thread(target=self._trigger_strafe_brake_pulse, daemon=True, name="StrafePulse").start()

    # ── WASD compensation (corrected directions) ──────────────────────────────
    def _apply_wasd(self):
        if not self.config.get("wasd_compensation", True):
            return
        sp   = self.config.get("wasd_speed", {"w":2.5,"a":2.5,"s":2.5,"d":2.5})
        held = self._held_wasd

        if "w"    in held or "up"    in held: self._lock_y -= sp.get("w", 2.5)
        if "s"    in held or "down"  in held: self._lock_y += sp.get("s", 2.5)
        if "a"    in held or "left"  in held: self._lock_x -= sp.get("a", 2.5)
        if "d"    in held or "right" in held: self._lock_x += sp.get("d", 2.5)

        self._lock_x = max(0.0, min(self._sw - 1.0, self._lock_x))
        self._lock_y = max(0.0, min(self._sh - 1.0, self._lock_y))

    # ── Action fire ───────────────────────────────────────────────────────────
    def _fire_once(self):
        action = self.config.get("action_key", "left").lower()
        if action == "left":
            SendInput(2, self._lclick_arr, self._inp_size)
        elif action == "right":
            SendInput(2, self._rclick_arr, self._inp_size)
        else:
            vk = ACTION_VK.get(action)
            if vk:
                scan = MapVirtualKeyW(vk, 0)
                self._key_arr[0]._input.ki.wVk    = vk
                self._key_arr[0]._input.ki.wScan   = scan
                self._key_arr[0]._input.ki.dwFlags  = KEYEVENTF_SCANCODE
                self._key_arr[1]._input.ki.wVk    = vk
                self._key_arr[1]._input.ki.wScan   = scan
                self._key_arr[1]._input.ki.dwFlags  = KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP
                SendInput(2, self._key_arr, self._inp_size)

    # ── Burst fire (runs in its own thread) ───────────────────────────────────
    def _run_burst(self):
        self._burst_running = True
        self.diag_status    = "ACTIVE"

        shots         = max(1, int(self.config.get("shots_per_detection", 1)))
        delay         = float(self.config.get("shot_delay_ms", 50)) / 1000.0
        one_shot_mode = bool(self.config.get("one_shot_mode", False))
        strafe_stop   = bool(self.config.get("auto_strafe_stop", False))
        strafe_source = self.config.get("strafe_source", "both")
        should_strafe = strafe_stop and (strafe_source in ("detection", "both"))
        anti_recoil   = bool(self.config.get("anti_recoil", False))
        recoil_str    = int(self.config.get("recoil_strength", 3))

        # ── Auto-strafe stop: execute fast isolated braking pulse ────────────
        if should_strafe:
            self._trigger_strafe_brake_pulse()

        for i in range(shots):
            if not self.active:
                break
            self._fire_once()
            self._last_fire_time = time.perf_counter()

            if anti_recoil:
                self._move_cursor_relative(0, recoil_str)

            if i < shots - 1 and delay > 0:
                time.sleep(delay)

        self._burst_running = False

        if self.active:
            if one_shot_mode:
                self._deactivate()
            else:
                self._needs_baseline = True

    # ── Mouse trigger polling (for mb1–mb5 which bypass keyboard hook) ──────────
    def _poll_mouse_trigger(self):
        """Called every main-loop tick when a mouse button is set as trigger, zoom, or strafe key."""
        # Zoom key polling if on mouse button
        zoom_enabled = self.config.get("zoom_enabled", False)
        zoom_key     = self.config.get("zoom_key", "c")
        if zoom_enabled and zoom_key in MOUSE_TRIGGER_KEYS:
            z_vks = VK_TRIGGER_SETS.get(zoom_key)
            if z_vks:
                z_vk = next(iter(z_vks))
                z_held = bool(GetAsyncKeyState(z_vk) & 0x8000)
                z_mode = self.config.get("zoom_mode", "hold")
                if z_mode == "toggle":
                    if z_held and not self._zoom_held:
                        self._zoom_held = True
                        self.zoom_active = not self.zoom_active
                    elif not z_held and self._zoom_held:
                        self._zoom_held = False
                else:
                    self.zoom_active = z_held

        # Standalone counter-strafe mouse button polling
        strafe_enabled = self.config.get("auto_strafe_stop", False)
        strafe_source  = self.config.get("strafe_source", "both")
        if strafe_enabled and strafe_source in ("manual", "both"):
            s_key = self.config.get("strafe_key", "mb1")
            if s_key in MOUSE_TRIGGER_KEYS:
                s_vks = VK_TRIGGER_SETS.get(s_key)
                if s_vks:
                    s_vk = next(iter(s_vks))
                    s_held = bool(GetAsyncKeyState(s_vk) & 0x8000)
                    if s_held and not self._strafe_key_held:
                        self._strafe_key_held = True
                        if self.enabled:
                            self._trigger_manual_strafe_stop()
                    elif not s_held and self._strafe_key_held:
                        self._strafe_key_held = False

        # Trigger key polling
        tk = self.config.get("trigger_key", "mb3")
        if tk in MOUSE_TRIGGER_KEYS:
            vks = VK_TRIGGER_SETS.get(tk)
            if not vks:
                return
            vk      = next(iter(vks))
            is_held = bool(GetAsyncKeyState(vk) & 0x8000)
            trk_mode = self.config.get("tracking_mode", "center" if self.config.get("lock_to_center", True) else "mouse_hold")

            if trk_mode == "mouse_toggle":
                if is_held and not self._trigger_held:
                    self._trigger_held = True
                    if self.enabled and not self._burst_running:
                        if self.active:
                            self._deactivate()
                        else:
                            self._activate_fast()
                elif not is_held and self._trigger_held:
                    self._trigger_held = False
            else: # hold modes
                if is_held and not self._trigger_held:
                    self._trigger_held = True
                    if self.enabled and not self.active and not self._burst_running:
                        self._activate_fast()
                elif not is_held and self._trigger_held:
                    self._trigger_held = False
                    if self.active or self._burst_running:
                        self._deactivate()

    # ── Main loop (200 Hz) ────────────────────────────────────────────────────
    def _main_loop(self):
        ACTIVE_TICK = 0.005   # 200 Hz
        IDLE_TICK   = 0.020   # 50 Hz

        print("[TriggerEngine] Main loop started.")

        with mss.mss() as sct:
            self._sct = sct

            while not self._stop_event.is_set():

                # ── Mouse button polling (trigger / zoom keys) ────────────────
                self._poll_mouse_trigger()

                trk_mode = self.config.get("tracking_mode", "center" if self.config.get("lock_to_center", True) else "mouse_hold")

                if not self.enabled or not self.active:
                    # Update preview dot position when idle in mouse tracking mode
                    if trk_mode == "mouse_hold":
                        pt = ctypes.wintypes.POINT()
                        GetCursorPos(ctypes.byref(pt))
                        self.diag_sample_pos = (pt.x, pt.y)
                    elif trk_mode == "center":
                        self.diag_sample_pos = (self._sw // 2, self._sh // 2)
                    time.sleep(IDLE_TICK)
                    continue

                # ── Dynamic mouse tracking (Hold Mode) ────────────────────────
                if trk_mode == "mouse_hold":
                    pt = ctypes.wintypes.POINT()
                    GetCursorPos(ctypes.byref(pt))
                    self._lock_x = float(pt.x)
                    self._lock_y = float(pt.y)

                # ── Cursor freeze (optional) ─────────────────────────────────
                if self.freeze_mouse:
                    self._move_cursor(self._lock_x, self._lock_y)

                # ── WASD compensation ─────────────────────────────────────
                self._apply_wasd()
                sample_x = int(self._lock_x)
                sample_y = int(self._lock_y)
                self.diag_sample_pos = (sample_x, sample_y)

                # ── Capture baseline (first tick after activation) ─────────
                if self._needs_baseline:
                    self._baseline_color     = self._sample_color(sample_x, sample_y)
                    self.diag_baseline_color = self._baseline_color
                    self._needs_baseline     = False
                    print(f"[TriggerEngine] Baseline captured: {self._baseline_color}")
                    time.sleep(ACTIVE_TICK)
                    continue   # skip detection on the baseline frame

                # ── Sample current colour ─────────────────────────────────
                current = self._sample_color(sample_x, sample_y)
                self.diag_current_color = current

                baseline = self._baseline_color
                if baseline is not None:
                    delta     = self._color_delta(current, baseline)
                    self.diag_delta = delta

                    threshold = float(self.config.get("color_threshold", 30))
                    cooldown  = float(self.config.get("cooldown_ms", 150)) / 1000.0
                    now       = time.perf_counter()

                    # ── Color whitelist: current must be close to a target color ───
                    whitelist = self.config.get("color_whitelist")
                    if whitelist:
                        wl_thresh = float(self.config.get("whitelist_threshold", 60))
                        if self._color_delta(current, tuple(whitelist)) > wl_thresh:
                            time.sleep(ACTIVE_TICK)
                            continue   # color not in whitelist — skip shot

                    # ── Color blacklist: skip if current matches a blocked color ─
                    blacklist = self.config.get("color_blacklist")
                    if blacklist:
                        bl_thresh = float(self.config.get("blacklist_threshold", 30))
                        if self._color_delta(current, tuple(blacklist)) <= bl_thresh:
                            time.sleep(ACTIVE_TICK)
                            continue   # color is blacklisted — skip shot

                    if (delta >= threshold
                            and not self._burst_running
                            and (now - self._last_fire_time) >= cooldown):
                        print(f"[TriggerEngine] Trigger! delta={delta:.1f} >= threshold={threshold:.1f}")
                        threading.Thread(
                            target=self._run_burst, daemon=True, name="Burst"
                        ).start()
                    elif not self._burst_running and self.diag_status == "ACTIVE":
                        self.diag_status = "MONITORING"

                time.sleep(ACTIVE_TICK)

            self._sct = None

        print("[TriggerEngine] Main loop stopped.")
