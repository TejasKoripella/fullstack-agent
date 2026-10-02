"""Test-only safety isolation; never reads or changes the live stop latch."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import safety as safety_runtime


class IsolatedSafetyTestCase(unittest.TestCase):
    def run(self, result=None):
        with tempfile.TemporaryDirectory(prefix="jarvis-test-safety-") as folder:
            manager = safety_runtime.SafetyState(Path(folder) / "safety.json")
            with patch.object(safety_runtime, "safety", manager):
                try:
                    return super().run(result)
                finally:
                    manager.stop("test cleanup")
