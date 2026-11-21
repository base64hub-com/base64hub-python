"""Tests run against src/ unless base64hub is importable from elsewhere (an installed wheel)."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")

if os.environ.get("BASE64HUB_TEST_INSTALLED") != "1" and SRC not in sys.path:
    sys.path.insert(0, SRC)
