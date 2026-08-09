"""Zero-dep test entry: `python3 tests/run.py` discovers and runs tests/.
Inserts the repo root on sys.path so `from lib.state_engine import …` resolves."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

if __name__ == "__main__":
    suite = unittest.TestLoader().discover(os.path.join(ROOT, "tests"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
