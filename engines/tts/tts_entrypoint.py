#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

TTS_SERVER = "/opt/venv/bin/tts-server"
RUNTIME_CONFIG = Path("/tmp/tts-runtime-config.json")


def write_runtime_config(source, speaker_ids, language_ids, output):
    source = Path(source)
    speaker_ids = Path(speaker_ids)
    language_ids = Path(language_ids)
    output = Path(output)
    for path in (source, speaker_ids, language_ids):
        if not path.is_file():
            raise FileNotFoundError(path)
    config = json.loads(source.read_text())
    model_args = config.setdefault("model_args", {})
    model_args["speakers_file"] = str(speaker_ids)
    config["language_ids_file"] = str(language_ids)
    output.write_text(json.dumps(config, ensure_ascii=False))
    return output


def replace_arg(args, name, value):
    try:
        idx = args.index(name)
    except ValueError as exc:
        raise RuntimeError(f"{name} is required") from exc
    if idx + 1 >= len(args):
        raise RuntimeError(f"{name} requires a value")
    args[idx + 1] = str(value)


def main():
    args = sys.argv[1:]
    try:
        idx = args.index("--config_path")
        source = Path(args[idx + 1])
    except (ValueError, IndexError) as exc:
        raise SystemExit("--config_path is required") from exc
    model_dir = source.parent
    write_runtime_config(
        source,
        model_dir / "speaker_ids.json",
        model_dir / "language_ids.json",
        RUNTIME_CONFIG,
    )
    replace_arg(args, "--config_path", RUNTIME_CONFIG)
    os.execv(TTS_SERVER, [TTS_SERVER, *args])


if __name__ == "__main__":
    main()
