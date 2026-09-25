import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class STTLockRuntimeRequirements(unittest.TestCase):
    def test_speaches_required_readme_is_locked(self):
        lock = json.loads((ROOT / "reproducibility/models.lock.json").read_text())
        paths = {entry["path"] for entry in lock["models"]["stt"]["files"]}
        self.assertIn("README.md", paths)

if __name__ == "__main__":
    unittest.main()
