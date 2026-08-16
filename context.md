# TriggerBot Pro — Complete Architecture & Context Guide

## 1. Overview
**TriggerBot Pro** is a high-performance, real-time pixel color-delta trigger automation application built for Windows. It monitors pixel color changes at a targeted screen location (center crosshair or mouse position) and automatically sends configurable action outputs (such as mouse clicks or keyboard inputs) with sub-millisecond precision.

It incorporates competitive gaming mechanics including:
* **Multi-Mode Counter-Strafing** (Flexible Null-Cancel, Fast Reverse Snap with Hardware Sync, and Full Stop).
* **Ultra-Low Latency Win32 GDI Magnifier** (120+ FPS hardware `StretchBlt` circular zoom lens down to 20px diameter).
* **Target Reticle Dot Overlay** (Customizable pixel-perfect crosshair dot).
* **Anti-Recoil Mouse Compensation** (Relative downward cursor compensation).
* **Movement Compensation (WASD Prediction)** (Dynamic crosshair offset tracking).
* **Color Whitelist & Blacklist Filters** (Target highlight matching and team/flashbang exclusion).
* **Keyboard & Mouse Freezing** (Selective hardware input suppression).
* **Profile Management** (Instant JSON preset switching).

---

## 2. Architecture & Concurrency Model

The application operates across 5 coordinated threads to ensure zero lag, non-blocking UI, and high-frequency sampling without dropping inputs:

```
                  ┌─────────────────────────────────────┐
                  │          GUI Thread (Tk)            │
                  │   CustomTkinter UI (60 FPS diag)    │
                  └──────────────┬──────────────────────┘
                                 │ config updates & telemetry
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            TriggerEngine                                    │
│                                                                             │
│  ┌─────────────────────────────┐        ┌────────────────────────────────┐  │
│  │   Hook Thread (Zero I/O)    │        │      Main Loop Thread          │  │
│  │  Low-level WH_KEYBOARD_LL   │        │     200 Hz Sampling Loop       │  │
│  │  - Physical key tracking    │◄──────►│  - Screen capture (MSS)        │  │
│  │  - Hardware key suppression │        │  - Color Δ calculation         │  │
│  │  - Passes LLKHF_INJECTED    │        │  - Whitelist/Blacklist filter  │  │
│  └─────────────────────────────┘        │  - Trigger evaluation          │  │
│                                         └───────────────┬────────────────┘  │
│                                                         │                   │
│                                                         ▼                   │
│  ┌─────────────────────────────┐        ┌────────────────────────────────┐  │
│  │    GdiMagnifier Thread      │        │      Burst Worker Thread       │  │
│  │  - Win32 Direct StretchBlt  │        │  - Counter-strafe execution    │  │
│  │  - 120-144 FPS Zoom Lens    │        │  - Action dispatch (SendInput) │  │
│  │  - Circular clipping region │        │  - Anti-recoil mouse nudging   │  │
│  └─────────────────────────────┘        └────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Thread Descriptions
1. **Main UI Thread (`TriggerBotGUI` in [gui.py](file:///c:/Users/UserDoes/Desktop/New%20folder/gui.py))**:
   - Renders CustomTkinter UI widgets.
   - Polls engine diagnostics every 70ms (`diag_status`, `diag_delta`, `diag_current_color`, `diag_baseline_color`).
   - Manages profile JSON loading/saving.
   - Houses floating, borderless always-on-top status overlay (`TriggerOverlay`).

2. **Hook Thread (`_run_hook` in [engine.py](file:///c:/Users/UserDoes/Desktop/New%20folder/engine.py))**:
   - Runs a Windows low-level keyboard hook (`WH_KEYBOARD_LL`).
   - Never performs blocking I/O or sleep calls inside the hook procedure.
   - Distinguishes between physical keypresses and synthetic inputs via `(lParam.contents.flags & 0x10) == 0`.
   - Populates `self._held_wasd` with 100% genuine physical finger states.
   - Intercepts and suppresses blacklisted keys (`self._suppressed_vks`) to prevent hardware auto-repeat during Fast Reverse Snap.

3. **Main Engine Loop (`_main_loop` in [engine.py](file:///c:/Users/UserDoes/Desktop/New%20folder/engine.py))**:
   - Runs at 200 Hz (5ms sleep per iteration when active, 20ms when idle).
   - Polls mouse trigger buttons (`MB1` through `MB5`) via Win32 `GetAsyncKeyState`.
   - Freezes the mouse cursor if `freeze_mouse` is enabled.
   - Captures bounding box pixels using `mss`.
   - Computes Euclidean color distance $\Delta = \sqrt{\Delta R^2 + \Delta G^2 + \Delta B^2}$.
   - Evaluates Whitelist / Blacklist criteria and fires asynchronous bursts.

4. **Burst Worker Thread (`_run_burst` in [engine.py](file:///c:/Users/UserDoes/Desktop/New%20folder/engine.py))**:
   - Spawned asynchronously upon valid detection to prevent blocking the 200 Hz sampling loop.
   - Performs counter-strafe, delay, key/click injection via Win32 `SendInput` (using hardware scancodes `KEYEVENTF_SCANCODE` with dual `wVk`+`wScan`), anti-recoil offsets, and clean state recovery.

5. **GDI Magnifier Thread (`ScreenMagnifier` in [magnifier.py](file:///c:/Users/UserDoes/Desktop/New%20folder/magnifier.py))**:
   - Standalone Win32 native window running direct `StretchBlt` blits from desktop HDC to window HDC at 120–144 Hz.
   - Hardware circular region clipping (`CreateEllipticRgn` + `SetWindowRgn`).
   - Suppresses Windows cursor rendering (`WM_SETCURSOR` -> `SetCursor(None)`) with full click passthrough (`WS_EX_TRANSPARENT | WS_EX_NOACTIVATE`).

---

## 3. Core Engine Mechanics

### A. Color Detection & Sampling
- **Bounding Box Calculation**:
  Given sample point $(X, Y)$ and box size $S$, a box of dimensions $(2S + 1) \times (2S + 1)$ is grabbed via `mss`.
- **Fast Slice-Sum Averaging**:
  The raw BGRA buffer is sampled in one pass:
  $$R_{avg} = \frac{\sum \text{raw}[2::4]}{N}, \quad G_{avg} = \frac{\sum \text{raw}[1::4]}{N}, \quad B_{avg} = \frac{\sum \text{raw}[0::4]}{N}$$
- **Baseline Capture**:
  When the trigger is first engaged, the engine captures a baseline color on the first tick and begins monitoring on subsequent frames.
- **Delta Threshold**:
  Triggers when $\Delta(C_{\text{current}}, C_{\text{baseline}}) \ge \text{color\_threshold}$.

---

### B. Multi-Mode Counter-Strafe System

The engine features three counter-strafe behaviors selectable in the GUI:

#### 1. Flexible (Null-Cancel) — `flexible`
* **Concept:** Holding opposing keys ($A + D$) cancels momentum in Source 2 / CS2 physics, forcing velocity to $0.0\text{ u/s}$.
* **Mechanism:**
  1. Detects moving keys (e.g. `D`).
  2. Injects opposing key `A` **without releasing `D`**.
  3. Holds `A` for the slider duration (`strafe_stop_delay_ms`, 20ms–50ms).
  4. Releases `A`.
  5. **Adaptive Direction Handoff:** If the player touches any new key or opposite direction mid-pulse, it cuts the hold early within **<1ms** and preserves the player's new input with zero stutter.

#### 2. Fast Reverse Snap (Hardware Sync) — `snap_tap`
* **Concept:** True mechanical counter-strafe (Cuts original key, applies active reverse torque, then cleanly resumes).
* **Mechanism:**
  1. **Release & Suppress:** Sends `KeyUp` on `D` and adds `VK_D` to `self._suppressed_vks` (blocking all physical USB auto-repeat pulses from reaching the game).
  2. **Micro-Gap:** 1ms separation to guarantee the game engine registers `KeyUp D`.
  3. **Active Reverse Brake:** Sends `KeyDown` on `A` alone (applying pure reverse deceleration).
  4. **Adaptive Hold:** Holds `A` for `fast_brake_ms` (1ms polling loop cuts early if user changes direction).
  5. **Clean Release:** Sends `KeyUp` on `A` unconditionally.
  6. **Physical Resume:** Un-suppresses `D` and immediately re-asserts `KeyDown` on whatever physical keys are currently in `self._held_wasd`.

#### 3. Full Stop (Hard Release) — `full_stop`
* **Mechanism:** Releases held key `D`, taps counter-key `A` for the slider duration, releases `A`, and leaves the character standing completely stopped.

---

### C. DirectInput Scan-Code Keyboard Simulation
DirectInput games ignore virtual key codes (`wVk`) unless hardware scan codes (`wScan`) are populated.
* The engine uses `MapVirtualKeyW(vk, 0)` to obtain the keyboard scan code.
* Pre-allocated Win32 `INPUT` structures are used with `KEYEVENTF_SCANCODE` to eliminate garbage collection delays:
  ```python
  scan = MapVirtualKeyW(vk, 0)
  flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if key_up else 0)
  self._single_key_arr[0]._input.ki.wVk = vk
  self._single_key_arr[0]._input.ki.wScan = scan
  self._single_key_arr[0]._input.ki.dwFlags = flags
  SendInput(1, self._single_key_arr, self._inp_size)
  ```

---

### D. Ultra-Fast Win32 GDI Magnifier
* **Direct Hardware Blitting:** Bypasses PIL/Tkinter software pipelines by executing Win32 GDI `StretchBlt` directly from desktop HDC (`GetDC(0)`) to the window HDC at 120–144 FPS (<0.2ms latency).
* **Dual Display Modes:**
  - **Center Circle (`"center"`):** Circular lens centered at crosshair (`CreateEllipticRgn`).
  - **Top-Left Square (`"top_left"`):** Tactical picture-in-picture (PIP) viewfinder square on the top left of the screen with neon border and reticle crosshair marking center screen.
* **Capture Exclusion:** `SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)` prevents the triggerbot from sampling the magnified lens itself.
* **Cursor Suppression:** `WM_SETCURSOR` handler sets `SetCursor(None)` to prevent Windows loading wheels or arrow pointers from showing over the lens.
* **Configurable Viewport:** Supports lens/square size from **`20px` to `500px`** and zoom ratios from **`1.5x` to `4.0x`**.

---

### E. Target Reticle Dot Overlay
* High-FPS standalone transparent window rendering a centered dot.
* Configurable dot size (1px to 10px) and custom RGB hex color.
* Pass-through input styling (`WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOPMOST`).

---

## 4. Key Configuration Parameters ([config.json](file:///c:/Users/UserDoes/Desktop/New%20folder/config.json))

| Parameter | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `trigger_key` | string | Key or mouse button to engage trigger bot (`shift`, `alt`, `mb1`–`mb5`, `f1`–`f4`, etc.) | `"alt"` |
| `action_key` | string | Output action to send on trigger (`"left"`, `"right"`, `"space"`, `"e"`, `"r"`, `"f"`, `"q"`) | `"left"` |
| `detection_box_size` | int | Radius $S$ of detection region (0 = 1x1 px, 1 = 3x3 px, 2 = 5x5 px) | `2` |
| `color_threshold` | int | Color Euclidean distance delta required to fire | `63` |
| `cooldown_ms` | int | Cooldown period between bursts in ms (0ms to 1000ms) | `50` |
| `lock_to_center` | bool | Lock sample point to screen center $(W/2, H/2)$ | `true` |
| `freeze_keyboard` | bool | Suppress physical keyboard inputs while holding trigger | `false` |
| `freeze_mouse` | bool | Lock mouse cursor position during activation | `false` |
| `shots_per_detection` | int | Number of shots to fire per trigger burst | `1` |
| `shot_delay_ms` | int | Delay between shots during multi-shot burst | `0` |
| `one_shot_mode` | bool | Disengage after single burst until key is re-pressed | `true` |
| `anti_recoil` | bool | Enable vertical downward pull after firing | `true` |
| `recoil_strength` | int | Downward pixel nudge amount per shot | `3` |
| `wasd_compensation` | bool | Dynamic crosshair offset compensation during movement | `false` |
| `auto_strafe_stop` | bool | Automated counter-strafing before firing | `true` |
| `strafe_source` | string | Counter-strafe trigger source (`"both"`, `"detection"`, `"manual"`) | `"both"` |
| `strafe_key` | string | Dedicated key/click to trigger manual counter-strafe | `"mb1"` |
| `strafe_mode` | string | Counter-strafe behavior (`"flexible"`, `"snap_tap"`, `"full_stop"`) | `"flexible"` |
| `strafe_stop_delay_ms`| int | Counter-key hold duration in ms (5ms – 250ms) | `45` |
| `zoom_enabled` | bool | Enable screen magnifying zoom lens | `false` |
| `zoom_key` | string | Key to activate magnifier (`"shift"`, `"alt"`, `"c"`, etc.) | `"shift"` |
| `zoom_mode` | string | Magnifier activation mode (`"toggle"` or `"hold"`) | `"toggle"` |
| `zoom_position` | string | Display layout & shape (`"center"` circle or `"top_left"` square PIP) | `"center"` |
| `zoom_factor` | float | Magnification ratio (1.5x to 4.0x) | `1.5` |
| `zoom_size` | int | Magnifier lens / square size in pixels (20px to 500px) | `40` |
| `show_tracking_dot` | bool | Enable center target reticle dot overlay | `false` |
| `dot_size` | int | Center dot diameter in pixels (1px to 10px) | `2` |
| `dot_color` | string | Center dot hex color string | `"#00FFFF"` |
| `color_whitelist` | [R,G,B] \| null | Required target color filter | `null` |
| `whitelist_threshold` | int | Tolerance delta for whitelist match | `150` |
| `color_blacklist` | [R,G,B] \| null | Excluded color filter | `null` |
| `blacklist_threshold` | int | Tolerance delta for blacklist exclusion | `76` |
| `wasd_speed` | dict | Per-key compensation speed multiplier | `{"w":2.5, "s":2.5, "a":2.5, "d":2.5}` |

---

## 5. File & Module Structure

```
trigger/
├── main.py          # Application entry point; initializes engine & launches GUI
├── engine.py        # Core triggerbot engine, Win32 hooks, SendInput API, detection loop, counter-strafe
├── gui.py           # CustomTkinter GUI, live diagnostics, profile manager, floating overlay
├── magnifier.py     # Native Win32 GDI hardware StretchBlt circular magnifier (120+ FPS)
├── dot_overlay.py   # Minimalist transparent center reticle dot overlay
├── config.json      # Active JSON configuration
├── context.md       # Comprehensive system architecture and reference guide
└── profiles/        # User-saved named configuration presets (.json)
```
