"""
main.py — Entry Point
======================
Boots the TriggerEngine background thread, then launches the GUI.
Run this file:  python main.py
"""

import sys
import os
import json
import threading

# ── Ensure the project root is in path ───────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))

from engine import TriggerEngine
from gui    import TriggerBotGUI

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {
            "trigger_key": "shift",
            "action_key": "left",
            "detection_box_size": 3,
            "color_threshold": 30,
            "cooldown_ms": 150,
            "lock_to_center": True,
            "wasd_compensation": True,
            "wasd_speed": {"w": 2.5, "a": 2.5, "s": 2.5, "d": 2.5},
        }


def main():
    config = load_config()

    # Start the engine
    engine = TriggerEngine(config)
    engine.start()

    # Launch the GUI (blocks until window is closed)
    app = TriggerBotGUI(engine)
    app.mainloop()

    # Cleanup on exit
    engine.stop()


if __name__ == "__main__":
    main()
