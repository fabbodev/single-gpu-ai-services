import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "reproducibility"))
spec = importlib.util.spec_from_file_location("provision_models", ROOT / "reproducibility/provision_models.py")
provision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provision)

class STTRuntimeOwnershipTests(unittest.TestCase):
    def test_lock_declares_runtime_owner(self):
        lock = json.loads((ROOT / "reproducibility/models.lock.json").read_text())
        item = lock["models"]["stt"]
        self.assertEqual(item["runtime_uid"], 1000)
        self.assertEqual(item["runtime_gid"], 1000)

    def test_normalizer_chowns_tree_without_following_symlinks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a").mkdir()
            (root / "a/file").write_text("x")
            (root / "link").symlink_to(root / "a/file")
            calls = []
            def fake_chown(path, uid, gid, *, follow_symlinks=True):
                calls.append((Path(path).relative_to(root), uid, gid, follow_symlinks))
            provision.normalize_tree_ownership(root, 1000, 1000, chown=fake_chown)
            names = {str(c[0]) for c in calls}
            self.assertEqual(names, {".", "a", "a/file", "link"})
            self.assertTrue(all(c[1:3] == (1000, 1000) for c in calls))
            self.assertTrue(all(c[3] is False for c in calls))

if __name__ == "__main__":
    unittest.main()
