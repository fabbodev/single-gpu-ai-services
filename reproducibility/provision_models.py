import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import urllib.request
import zipfile

from verify_models import (
    CANONICAL_ROOT,
    MODEL_ORDER,
    selected_model_names,
    validate_model_paths,
    remap_local_path,
    sha256_file,
    stt_repo_cache_path,
    stt_snapshot_path,
    verify_locked_models,
)


def human_bytes(value):
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.2f} {unit}"
        size /= 1024


def file_ok(path, entry):
    path = Path(path)
    return (
        path.is_file()
        and path.stat().st_size == entry["size"]
        and sha256_file(path) == entry["sha256"]
    )


def token_from_env():
    token_file = os.getenv("HF_TOKEN_FILE")
    if token_file:
        return Path(token_file).read_text().strip()
    return os.getenv("HF_TOKEN") or None
def preflight_huggingface(lock, token):
    from huggingface_hub import HfApi

    api = HfApi(token=token)
    checked = set()
    for item in lock["models"].values():
        if item["source_type"] != "huggingface":
            continue
        if "repository" in item:
            pairs = [(item["repository"], item["revision"])]
        else:
            pairs = list(item["revisions"].items())

        for repo, revision in pairs:
            if (repo, revision) in checked:
                continue
            info = api.model_info(
                repo_id=repo,
                revision=revision,
                files_metadata=True,
            )
            if info.sha != revision:
                raise RuntimeError(
                    f"{repo}: resolved {info.sha}, expected {revision}"
                )
            print(f"PASS source {repo}@{revision}")
            checked.add((repo, revision))


def preflight(lock, token, offline=False):
    total = 0
    for item in lock["models"].values():
        for entry in item["files"]:
            total += entry["size"]
    print(f"locked payload total: {human_bytes(total)}")
    if offline:
        print("OFFLINE: paths checked; source metadata and authentication not accessed")
        return
    print("HF authentication: configured" if token else "HF authentication: anonymous")
    if os.getenv("HF_HUB_DISABLE_XET", "").lower() in {"1", "true", "yes"}:
        print("HF transfer: Xet disabled by environment (HTTP fallback)")
    else:
        print("HF transfer: transport selected by the installed SDK")
    preflight_huggingface(lock, token)
    if "tts" in lock["models"]:
        tts = lock["models"]["tts"]
        print("LOCKED TTS source", tts["source_url"],
              "archive_sha256=" + tts["archive_sha256"])
        print("TTS archive bytes will be verified during provisioning, not this precheck")
def download_hf_file(repo, revision, entry, destination_dir, token):
    destination_dir = Path(destination_dir)
    destination = destination_dir / entry["path"]
    if file_ok(destination, entry):
        print("SKIP verified", destination)
        return

    from huggingface_hub import hf_hub_download

    destination_dir.mkdir(parents=True, exist_ok=True)
    print(
        "DOWNLOAD",
        repo,
        entry["path"],
        human_bytes(entry["size"]),
    )
    resolved = Path(
        hf_hub_download(
            repo_id=repo,
            filename=entry["path"],
            revision=revision,
            local_dir=destination_dir,
            token=token,
        )
    )
    if resolved != destination and resolved.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(resolved, destination)

    if not file_ok(destination, entry):
        raise RuntimeError(f"download verification failed: {destination}")
    print("PASS verified", destination)


def provision_standard_hf(name, item, root, token):
    base = remap_local_path(item["local_path"], root)
    if name == "llm":
        entry = item["files"][0]
        base.parent.mkdir(parents=True, exist_ok=True)
        if file_ok(base, entry):
            print("SKIP verified", base)
            return
        from huggingface_hub import hf_hub_download

        resolved = Path(
            hf_hub_download(
                repo_id=item["repository"],
                filename=entry["path"],
                revision=item["revision"],
                local_dir=base.parent,
                token=token,
            )
        )
        if resolved != base:
            shutil.copy2(resolved, base)
        if not file_ok(base, entry):
            raise RuntimeError(f"download verification failed: {base}")
        print("PASS verified", base)
        return

    for entry in item["files"]:
        download_hf_file(
            item["repository"],
            item["revision"],
            entry,
            base,
            token,
        )
def provision_ocr(item, root, token):
    base = remap_local_path(item["local_path"], root)
    for entry in item["files"]:
        target_dir = base / entry["local_subdir"]
        download_hf_file(
            entry["repository"],
            item["revisions"][entry["repository"]],
            entry,
            target_dir,
            token,
        )


def normalize_tree_ownership(root, uid, gid, chown=os.chown):
    root = Path(root)
    if not isinstance(uid, int) or not isinstance(gid, int) or uid < 0 or gid < 0:
        raise ValueError("runtime uid/gid must be nonnegative integers")
    paths = [root, *sorted(root.rglob("*"), key=lambda p: str(p))]
    for path in paths:
        chown(path, uid, gid, follow_symlinks=False)


def provision_stt(item, root, token):
    cache_root = remap_local_path(item["local_path"], root)
    hub_cache = cache_root / "hub"
    repo_cache = stt_repo_cache_path(item, root)
    snapshot = stt_snapshot_path(item, root)

    all_good = all(
        file_ok(snapshot / entry["path"], entry)
        for entry in item["files"]
    )
    if not all_good:
        from huggingface_hub import snapshot_download

        hub_cache.mkdir(parents=True, exist_ok=True)
        print(
            "DOWNLOAD snapshot",
            item["repository"],
            item["revision"],
        )
        returned = Path(
            snapshot_download(
                repo_id=item["repository"],
                revision=item["revision"],
                cache_dir=hub_cache,
                allow_patterns=[e["path"] for e in item["files"]],
                token=token,
            )
        )
        print("snapshot path", returned)

    refs = repo_cache / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    (refs / "main").write_text(item["revision"])

    for entry in item["files"]:
        target = snapshot / entry["path"]
        if not file_ok(target, entry):
            raise RuntimeError(
                f"STT snapshot verification failed: {target}"
            )
        print("PASS verified", target)

    normalize_tree_ownership(
        cache_root,
        item["runtime_uid"],
        item["runtime_gid"],
    )
    print(
        "PASS STT cache ownership",
        f'{item["runtime_uid"]}:{item["runtime_gid"]}',
    )

def stream_download(url, destination):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "single-gpu-ai-services-provisioner"},
    )
    digest = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(request, timeout=120) as response:
        with Path(destination).open("wb") as handle:
            while True:
                chunk = response.read(8 * 1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                digest.update(chunk)
                size += len(chunk)
    return size, digest.hexdigest()


def provision_tts(item, root):
    base = remap_local_path(item["local_path"], root)
    if all(file_ok(base / entry["path"], entry) for entry in item["files"]):
        print("SKIP TTS model already verified")
        return

    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "tts.zip"
        print(
            "DOWNLOAD TTS archive",
            item["source_url"],
            human_bytes(item["archive_size"]),
        )
        size, digest = stream_download(item["source_url"], archive)
        if size != item["archive_size"]:
            raise RuntimeError(
                f"TTS archive size mismatch: {size} != {item['archive_size']}"
            )
        if digest != item["archive_sha256"]:
            raise RuntimeError(
                f"TTS archive SHA mismatch: {digest}"
            )

        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
            for entry in item["files"]:
                candidates = [
                    name
                    for name in names
                    if name == entry["path"]
                    or name.endswith("/" + entry["path"])
                ]
                if len(candidates) != 1:
                    raise RuntimeError(
                        f"TTS archive member ambiguous: {entry['path']}"
                    )
                target = base / entry["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(candidates[0]) as source:
                    with target.open("wb") as destination:
                        shutil.copyfileobj(source, destination)
                if not file_ok(target, entry):
                    raise RuntimeError(
                        f"TTS extracted verification failed: {target}"
                    )
                print("PASS verified", target)
def provision(lock, root, token, selected=None):
    models = lock["models"]
    for name in selected_model_names(lock, selected):
        print("\n===", name, "===")
        item = models[name]
        if name in {"llm", "embeddings", "reranker"}:
            provision_standard_hf(name, item, root, token)
        elif name == "stt":
            provision_stt(item, root, token)
        elif name == "ocr":
            provision_ocr(item, root, token)
        elif name == "tts":
            provision_tts(item, root)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", default=str(Path(__file__).with_name("models.lock.json")))
    parser.add_argument("--root", default="/models")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-only", action="store_true")
    mode.add_argument("--download", action="store_true", help="Explicitly allow model payload downloads; GPU host only operationally")
    parser.add_argument("--offline", action="store_true", help="With --check-only: no network access")
    parser.add_argument(
        "--model",
        action="append",
        dest="models",
        choices=MODEL_ORDER,
        help="Provision only this group; repeat for multiple groups.",
    )
    args = parser.parse_args()

    if args.offline and not args.check_only:
        parser.error("--offline requires --check-only")
    lock = json.loads(Path(args.lock).read_text())
    names = selected_model_names(lock, args.models)
    validate_model_paths(lock, args.root, args.models)
    selected_lock = {**lock, "models": {name: lock["models"][name] for name in names}}
    token = None if args.offline else token_from_env()
    preflight(selected_lock, token, offline=args.offline)
    if args.check_only:
        print("PRECHECK COMPLETE: no model payloads downloaded")
        return

    provision(lock, args.root, token, args.models)
    failures = verify_locked_models(lock, args.root, args.models)
    if failures:
        for failure in failures:
            print("FAIL", failure)
        raise SystemExit(1)
    print("\nPASS all provisioned model files verified")


if __name__ == "__main__":
    main()
