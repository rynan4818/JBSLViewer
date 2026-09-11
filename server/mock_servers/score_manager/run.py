"""Portable Windows entry point; no files outside this folder are required."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from score_manager.__main__ import main
if __name__ == "__main__":
    main()
