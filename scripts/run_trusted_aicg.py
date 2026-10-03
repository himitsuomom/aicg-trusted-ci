#!/usr/bin/env python3
"""Run only the AICG package copied from the pinned trusted commit."""

from pathlib import Path
import sys


TRUSTED_SOURCE = Path(__file__).resolve().parents[1] / "aicg" / "src"
sys.path.insert(0, str(TRUSTED_SOURCE))

from aicg.cli import main  # noqa: E402


if __name__ == "__main__":
    main()
