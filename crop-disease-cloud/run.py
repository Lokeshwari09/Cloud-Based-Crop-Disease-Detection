"""Convenience launcher: open this file in VS Code and press the Run button (or F5)."""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).parent / "app" / "app.py"), run_name="__main__")
