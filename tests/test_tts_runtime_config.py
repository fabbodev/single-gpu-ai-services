import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "engines/tts/tts_entrypoint.py"

class TTSRuntimeConfigTests(unittest.TestCase):
    def load_module(self):
        spec = importlib.util.spec_from_file_location("tts_entrypoint", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_runtime_copy_rehomes_locked_id_files_without_mutating_source(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "config.json"
            speakers = root / "speaker_ids.json"
            languages = root / "language_ids.json"
            output = root / "runtime.json"
            original = {
                "model": "vits",
                "language_ids_file": None,
                "speakers_file": None,
                "model_args": {
                    "use_speaker_embedding": True,
                    "speakers_file": "/stale/hf/cache/speaker_ids.json",
                    "use_language_embedding": True,
                    "language_ids_file": None,
                },
            }
            source.write_text(json.dumps(original))
            speakers.write_text('{"css10": 0}')
            languages.write_text('{"es": 0}')
            before = source.read_bytes()

            module.write_runtime_config(source, speakers, languages, output)

            self.assertEqual(source.read_bytes(), before)
            runtime = json.loads(output.read_text())
            self.assertEqual(runtime["model_args"]["speakers_file"], str(speakers))
            self.assertEqual(runtime["language_ids_file"], str(languages))
            expected = copy.deepcopy(original)
            expected["model_args"]["speakers_file"] = str(speakers)
            expected["language_ids_file"] = str(languages)
            self.assertEqual(runtime, expected)

    def test_missing_locked_id_file_fails_closed(self):
        module = self.load_module()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "config.json"
            source.write_text(json.dumps({"model_args": {}}))
            with self.assertRaises(FileNotFoundError):
                module.write_runtime_config(source, root / "missing-speakers.json",
                                            root / "missing-languages.json",
                                            root / "runtime.json")

if __name__ == "__main__":
    unittest.main()
