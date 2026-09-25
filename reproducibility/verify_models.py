import argparse
import hashlib
import json
from pathlib import Path


CANONICAL_ROOT = Path("/opt/ai-services/models")


def sha256_file(path, chunk_size=8 * 1024 * 1024):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative_path(value):
    path = Path(value)
    if path.is_absolute() or not path.parts or '..' in path.parts or '\\' in str(value):
        raise ValueError(f'unsafe relative model path: {value}')
    return path


def remap_local_path(local_path, root):
    relative = Path(local_path).relative_to(CANONICAL_ROOT)
    return Path(root) / safe_relative_path(relative)


def stt_repo_cache_path(item, root):
    cache_root = remap_local_path(item["local_path"], root)
    return (
        cache_root
        / "hub"
        / ("models--" + item["repository"].replace("/", "--"))
    )


def stt_snapshot_path(item, root):
    return (
        stt_repo_cache_path(item, root)
        / "snapshots"
        / item["revision"]
    )


def verify_file(path, expected):
    path = Path(path)
    if not path.is_file():
        return f"missing: {path}"
    size = path.stat().st_size
    if size != expected["size"]:
        return f"size mismatch: {path}: {size} != {expected['size']}"
    digest = sha256_file(path)
    if digest != expected["sha256"]:
        return (
            f"sha256 mismatch: {path}: "
            f"{digest} != {expected['sha256']}"
        )
    return None
MODEL_ORDER = ("llm", "embeddings", "reranker", "stt", "tts", "ocr")


def selected_model_names(lock, selected=None):
    wanted = set(MODEL_ORDER if selected is None else selected)
    unknown = wanted.difference(MODEL_ORDER)
    if unknown:
        raise ValueError(f"unknown model groups: {sorted(unknown)}")
    missing = wanted.difference(lock["models"])
    if missing:
        raise ValueError(f"model groups missing from lock: {sorted(missing)}")
    return [name for name in MODEL_ORDER if name in wanted]


def validate_model_paths(lock, root, selected=None):
    boundary = Path(root).resolve()
    for name in selected_model_names(lock, selected):
        item = lock['models'][name]
        base = remap_local_path(item['local_path'], root)
        for entry in item['files']:
            relative = safe_relative_path(entry['path'])
            if name == 'llm':
                target = base
            elif name == 'stt':
                target = stt_snapshot_path(item, root) / relative
            elif name == 'ocr':
                target = base / safe_relative_path(entry['local_subdir']) / relative
            else:
                target = base / relative
            if not target.resolve().is_relative_to(boundary):
                raise ValueError(f'model path escapes selected root: {target}')


def verify_locked_models(lock, root, selected=None):
    """Verify only selected groups; the default still verifies the entire lock."""
    validate_model_paths(lock, root, selected)
    failures = []
    for name in selected_model_names(lock, selected):
        item = lock["models"][name]
        base = remap_local_path(item["local_path"], root)
        for entry in item["files"]:
            if name == "llm":
                target = base
            elif name == "stt":
                target = stt_snapshot_path(item, root) / entry["path"]
            elif name == "ocr":
                target = base / entry["local_subdir"] / entry["path"]
            else:
                target = base / entry["path"]
            error = verify_file(target, entry)
            if error:
                failures.append(error)
        if name == "stt":
            ref = stt_repo_cache_path(item, root) / "refs" / "main"
            if not ref.is_file():
                failures.append(f"missing STT main ref: {ref}")
            elif ref.read_text() != item["revision"]:
                failures.append(
                    f"STT main ref mismatch: {ref.read_text()!r} "
                    f"!= {item['revision']}"
                )
    return failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--lock",
        default=str(Path(__file__).with_name("models.lock.json")),
    )
    parser.add_argument(
        "--root",
        default="/models",
    )
    parser.add_argument("--model", action="append", dest="models", choices=MODEL_ORDER)
    args = parser.parse_args()

    lock = json.loads(Path(args.lock).read_text())
    failures = verify_locked_models(lock, args.root, args.models)
    if failures:
        for failure in failures:
            print("FAIL", failure)
        raise SystemExit(1)

    print("PASS selected locked model files match size and SHA-256")


if __name__ == "__main__":
    main()
