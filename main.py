#!/usr/bin/env python3
"""Persona Traffic Generator — main entry point."""
import sys
from pathlib import Path

# Ensure the project root is on sys.path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config_manager import ConfigManager
from app.gui.main_window import TrafficGeneratorGUI


def main() -> None:
    config = ConfigManager(root=ROOT)
    config.load_all()

    gui = TrafficGeneratorGUI(config)
    gui.run()


if __name__ == "__main__":
    main()
