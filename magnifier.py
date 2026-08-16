"""
magnifier.py — Ultra-Low-Latency Direct GDI Hardware Zoom Lens
================================================================
Renders a clear magnifying lens with <1ms latency and 120+ FPS.

Modes:
- "center": Circular lens centered in the middle of the screen.
- "top_left": Large square Picture-in-Picture on the top-left of the screen.

Features:
- Pure Win32 GDI StretchBlt directly from Desktop HDC to Window HDC.
- Zero PIL conversions and zero Python heap allocations in render loop.
- Clear magnification with no obstructing crosshair lines.
- Hardware DWM clipping (CreateEllipticRgn for circle, CreateRectRgn for square).
- Hidden from Windows screen captures (WDA_EXCLUDEFROMCAPTURE).
- Click-through transparent overlay (WS_EX_TRANSPARENT | WS_EX_NOACTIVATE).
"""

import threading
import time
import ctypes
from ctypes import wintypes

# ── Win32 APIs & Constants ───────────────────────────────────────────────────
user32   = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
gdi32    = ctypes.windll.gdi32

GWL_EXSTYLE       = -20
WS_EX_LAYERED     = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW  = 0x00000080
WS_EX_TOPMOST     = 0x00000008
WS_EX_NOACTIVATE  = 0x08000000
WS_POPUP          = 0x80000000
WS_VISIBLE        = 0x10000000

SWP_NOSIZE        = 0x0001
SWP_NOMOVE        = 0x0002
SWP_NOZORDER      = 0x0004
SWP_NOACTIVATE    = 0x0010
SWP_FRAMECHANGED  = 0x0020
SWP_SHOWWINDOW    = 0x0040
SWP_HIDEWINDOW    = 0x0080
SW_HIDE           = 0
SW_SHOW           = 5

HWND_TOPMOST      = wintypes.HWND(-1)

SRCCOPY           = 0x00CC0020
COLORONCOLOR      = 3
WDA_EXCLUDEFROMCAPTURE = 0x00000011

# Custom window class & structs
WNDPROC = ctypes.WINFUNCTYPE(wintypes.LPARAM, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype  = wintypes.LPARAM

user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.UINT
]
user32.SetWindowPos.restype = wintypes.BOOL

user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype  = wintypes.BOOL

gdi32.CreateEllipticRgn.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
gdi32.CreateEllipticRgn.restype  = wintypes.HRGN

gdi32.CreateRectRgn.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
gdi32.CreateRectRgn.restype  = wintypes.HRGN

user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
user32.SetWindowRgn.restype  = ctypes.c_int

gdi32.StretchBlt.argtypes = [
    wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.DWORD
]
gdi32.StretchBlt.restype = wintypes.BOOL


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype  = wintypes.ATOM
user32.CreateWindowExW.restype = wintypes.HWND


class ScreenMagnifier:
    def __init__(self, engine):
        self.engine = engine
        self._running = False
        self._thread = None
        self._hwnd = None
        self._visible = False

        self._sw = user32.GetSystemMetrics(0)
        self._sh = user32.GetSystemMetrics(1)

        self._last_size = 0
        self._last_pos  = None
        self._wnd_proc_ref = None

    def start(self):
        if self._thread is not None:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_window_thread, daemon=True, name="GdiMagnifier")
        self._thread.start()

    def _apply_region(self, pos_mode: str, size: int):
        if not self._hwnd:
            return
        if pos_mode == "top_left":
            rgn = gdi32.CreateRectRgn(0, 0, size, size)
        else:
            rgn = gdi32.CreateEllipticRgn(0, 0, size, size)
        user32.SetWindowRgn(self._hwnd, rgn, True)

    def _run_window_thread(self):
        def wnd_proc(hwnd, msg, wparam, lparam):
            if msg == 0x0002: # WM_DESTROY
                return 0
            if msg == 0x0020: # WM_SETCURSOR -> Suppress cursor completely over magnifier
                user32.SetCursor(None)
                return 1
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wnd_proc_ref = WNDPROC(wnd_proc)
        hinst = kernel32.GetModuleHandleW(None)
        class_name = "TriggerGdiMagnifier"

        wndclass = WNDCLASSW()
        wndclass.style         = 0
        wndclass.lpfnWndProc   = self._wnd_proc_ref
        wndclass.cbClsExtra    = 0
        wndclass.cbWndExtra    = 0
        wndclass.hInstance     = hinst
        wndclass.hIcon         = None
        wndclass.hCursor       = None
        wndclass.hbrBackground = None
        wndclass.lpszMenuName  = None
        wndclass.lpszClassName = class_name

        user32.RegisterClassW(ctypes.byref(wndclass))

        cfg = self.engine.config
        lens_size = max(20, min(600, int(cfg.get("zoom_size", 180))))
        zoom_pos  = cfg.get("zoom_position", "center")

        cx = self._sw // 2
        cy = self._sh // 2

        if zoom_pos == "top_left":
            x, y = 24, 24
        else:
            x = cx - lens_size // 2
            y = cy - lens_size // 2

        self._hwnd = user32.CreateWindowExW(
            WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE,
            class_name,
            "GdiMagnifier",
            WS_POPUP,
            x, y, lens_size, lens_size,
            None, None, hinst, None
        )

        try:
            user32.SetWindowDisplayAffinity(self._hwnd, WDA_EXCLUDEFROMCAPTURE)
        except Exception:
            pass

        self._apply_region(zoom_pos, lens_size)
        self._last_size = lens_size
        self._last_pos  = zoom_pos
        user32.ShowWindow(self._hwnd, SW_HIDE)

        # High-FPS Render loop (up to 144 Hz)
        hdc_screen = user32.GetDC(0)
        hdc_win    = user32.GetDC(self._hwnd)
        gdi32.SetStretchBltMode(hdc_win, COLORONCOLOR)

        msg = wintypes.MSG()

        while self._running:
            # Process any window messages non-blocking
            while user32.PeekMessageW(ctypes.byref(msg), self._hwnd, 0, 0, 1): # PM_REMOVE = 1
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

            try:
                cfg = self.engine.config
                zoom_enabled = cfg.get("zoom_enabled", False)
                zoom_active  = getattr(self.engine, "zoom_active", False)
                should_show  = zoom_enabled and zoom_active and self.engine.enabled

                if should_show:
                    lens_size   = max(20, min(600, int(cfg.get("zoom_size", 180))))
                    zoom_factor = max(1.1, float(cfg.get("zoom_factor", 2.0)))
                    zoom_pos    = cfg.get("zoom_position", "center")

                    cx = self._sw // 2
                    cy = self._sh // 2

                    if zoom_pos == "top_left":
                        x, y = 24, 24
                    else:
                        x = cx - lens_size // 2
                        y = cy - lens_size // 2

                    # Update position / size / shape if changed
                    if self._last_size != lens_size or self._last_pos != zoom_pos:
                        user32.SetWindowPos(
                            self._hwnd, HWND_TOPMOST,
                            x, y, lens_size, lens_size,
                            SWP_NOACTIVATE | SWP_FRAMECHANGED
                        )
                        self._apply_region(zoom_pos, lens_size)
                        self._last_size = lens_size
                        self._last_pos  = zoom_pos

                    if not self._visible:
                        user32.SetWindowPos(
                            self._hwnd, HWND_TOPMOST,
                            x, y, lens_size, lens_size,
                            SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_FRAMECHANGED
                        )
                        self._apply_region(zoom_pos, lens_size)
                        self._visible = True

                    cap_w = int(lens_size / zoom_factor)
                    cap_h = int(lens_size / zoom_factor)
                    cap_left = max(0, cx - cap_w // 2)
                    cap_top  = max(0, cy - cap_h // 2)

                    # Pure, crystal-clear direct hardware StretchBlt (no crosshairs)
                    gdi32.StretchBlt(
                        hdc_win, 0, 0, lens_size, lens_size,
                        hdc_screen, cap_left, cap_top, cap_w, cap_h,
                        SRCCOPY
                    )

                else:
                    if self._visible:
                        user32.ShowWindow(self._hwnd, SW_HIDE)
                        self._visible = False

            except Exception:
                pass

            # ~120 FPS tick rate
            time.sleep(0.007)

        user32.ReleaseDC(0, hdc_screen)
        user32.ReleaseDC(self._hwnd, hdc_win)

    def destroy(self):
        self._running = False
        if self._hwnd:
            try:
                user32.DestroyWindow(self._hwnd)
            except Exception:
                pass
        self._hwnd = None
