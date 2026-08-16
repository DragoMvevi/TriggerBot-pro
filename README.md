# ⚡ TriggerBot Pro — Precision Automation Suite

[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Platform Windows](https://img.shields.io/badge/Platform-Windows-0078D6?style=for-the-badge&logo=windows&logoColor=white)](https://microsoft.com/windows)
[![Ko-fi Support](https://img.shields.io/badge/Support_on-Ko--fi-FF5E5B?style=for-the-badge&logo=kofi&logoColor=white)](https://ko-fi.com/dragomvevi)

**TriggerBot Pro** is a high-performance, real-time pixel color-delta trigger automation application designed for Windows. It provides competitive gaming enhancements with sub-millisecond precision, featuring advanced counter-strafing mechanics, ultra-low-latency direct GDI hardware screen magnification, target reticle overlays, anti-recoil compensation, and fine-grained color filtering.

---

## 🌟 Key Features

### 🎯 1. High-Frequency Pixel Sampling Engine
* **200 Hz Sampling Loop:** Employs optimized `mss` screen captures with zero-allocation slice-sum color averaging.
* **Euclidean Color Delta Detection:** Computes instantaneous pixel distance ($\Delta = \sqrt{\Delta R^2 + \Delta G^2 + \Delta B^2}$) against a baseline frame.
* **DirectInput Hardware Scancode Injection:** Bypasses basic virtual keys using low-level Win32 `SendInput` with physical scan codes (`KEYEVENTF_SCANCODE`) for seamless game compatibility.
* **Full Mouse Trigger Support:** Supports mouse buttons (`MB1` through `MB5`) and full keyboard keybinds.

---

### 🕹️ 2. Advanced Multi-Mode Counter-Strafing
Execute flawless, instant counter-strafes before firing:
* **Fast Reverse Snap (Hardware Sync):** True mechanical counter-strafe. Releases active movement key, blocks hardware USB auto-repeat via a low-level hook (`WH_KEYBOARD_LL`), injects counter-key with active braking deceleration, and seamlessly resumes held keys. Features sub-millisecond adaptive handoff.
* **Flexible (Null-Cancel):** Injects counter-key without releasing the original key to cancel momentum in Source 2 / CS2 physics engines.
* **Full Stop (Hard Release):** Releases moving keys and taps the opposite direction, bringing the character to an immediate, clean standstill.

---

### 🔍 3. Ultra-Fast Win32 GDI Magnifier (120+ FPS)
* **Direct Hardware Blitting:** Bypasses software image processing by executing Win32 GDI `StretchBlt` directly from the Desktop HDC to the Window HDC at 120–144 FPS (<0.2ms latency).
* **Dual Display Modes:**
  * **Center Circle (`"center"`):** Circular lens centered directly over the screen crosshair.
  * **Top-Left Square (`"top_left"`):** Large tactical Picture-in-Picture (PIP) viewfinder positioned at the top-left of your monitor ($X=24, Y=24$) magnifying the screen center.
* **Crystal Clear Viewport:** 100% unobstructed, crisp magnification without interfering crosshairs.
* **Capture Exclusion:** Leverages `WDA_EXCLUDEFROMCAPTURE` so the triggerbot never captures or interferes with the magnified lens itself.

---

### 🔴 4. Visual Reticle Dot Overlay
* High-FPS transparent topmost window rendering a clean center target dot.
* Fully customizable dot diameter (1px to 10px) and custom RGB hex color.
* Pass-through input styling (`WS_EX_TRANSPARENT | WS_EX_NOACTIVATE`) so games receive all mouse inputs without interruption.

---

### 🛡️ 5. Color Whitelist & Blacklist Filtering
* **Target Whitelist:** Restricts trigger firing to specific enemy outline colors (e.g. glowing yellow, red, or purple).
* **Environment Blacklist:** Prevents accidental trigger activations from flashes, team models, or specific HUD elements.
* **Built-in RGB Palette Pickers:** Easy color selection and customizable tolerance sliders directly in the GUI.

---

### 🎯 6. Anti-Recoil & Movement Compensation
* **Dynamic Recoil Pull:** Automatically injects relative downward cursor nudges per shot to counteract weapon recoil.
* **WASD Movement Compensation:** Adjusts crosshair sampling coordinates dynamically according to player movement speed and direction.
* **Hardware Freezing:** Optional suppression of physical keyboard or mouse inputs while holding the trigger.

---

### 💾 7. Profile Management & Floating HUD
* Save, load, and switch between named configuration presets (`.json`) instantly.
* Movable, borderless floating status badge overlay displaying live `MONITORING` and `FIRING` states.

---

## 🚀 Quick Start & Installation

### Prerequisites
* Windows 10 or Windows 11 (64-bit)
* Python 3.10 or higher installed with `pip`

### 1. Clone or Extract the Repository
```bash
git clone https://github.com/DragoMvevi/TriggerBot-pro.git
cd TriggerBot-pro
```

### 2. Install Dependencies
```bash
pip install customtkinter mss pillow
```

### 3. Launch the Application
Double-click `start.bat` or run:
```bash
python main.py
```

---

## ⚙️ Configuration Reference

| Parameter | Description | Default |
| :--- | :--- | :--- |
| `trigger_key` | Key or mouse button to engage triggerbot (`alt`, `shift`, `mb1`–`mb5`, etc.) | `"alt"` |
| `action_key` | Output action dispatched upon detection (`left`, `right`, `space`, `e`, etc.) | `"left"` |
| `tracking_mode` | Tracking mode: `center`, `mouse_toggle`, or `mouse_hold` | `"center"` |
| `detection_box_size` | Sampling box radius (0 = 1x1 px, 1 = 3x3 px, 2 = 5x5 px) | `2` |
| `color_threshold` | Euclidean color distance delta required to fire | `63` |
| `cooldown_ms` | Cooldown period between bursts in ms | `50` |
| `shots_per_detection` | Number of shots fired per trigger burst | `1` |
| `anti_recoil` | Enable vertical recoil compensation | `true` |
| `recoil_strength` | Downward pixel nudge amount per shot | `3` |
| `auto_strafe_stop` | Automated counter-strafing before firing | `true` |
| `strafe_mode` | Counter-strafe mode: `snap_tap`, `flexible`, or `full_stop` | `"snap_tap"` |
| `strafe_stop_delay_ms` | Counter-key brake hold duration in ms (5ms – 250ms) | `35` |
| `zoom_enabled` | Enable screen magnifying zoom lens | `false` |
| `zoom_position` | Magnifier layout: `center` (circular lens) or `top_left` (square PIP) | `"center"` |
| `zoom_factor` | Zoom magnification ratio (1.5x to 4.0x) | `1.5` |
| `zoom_size` | Lens diameter or square viewport size in pixels (20px to 500px) | `180` |
| `show_tracking_dot` | Enable center target reticle dot overlay | `true` |

---

## ☕ Support & Donations

If you enjoy using **TriggerBot Pro** and want to support its ongoing development:

[![Support me on Ko-fi](https://img.shields.io/badge/Support_me_on_Ko--fi-FF5E5B?style=for-the-badge&logo=kofi&logoColor=white)](https://ko-fi.com/dragomvevi)

👉 **[https://ko-fi.com/dragomvevi](https://ko-fi.com/dragomvevi)**

---

## ⚠️ Disclaimer
* This application is provided for educational, research, and single-player/offline testing purposes only.
* Ensure you comply with all terms of service and anti-cheat policies of the games you play.
