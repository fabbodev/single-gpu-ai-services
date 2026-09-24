import json
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


def load_compose(name):
    return yaml.safe_load((ROOT / name).read_text())


def image_default(value):
    match = re.fullmatch(r"\$\{[^:}]+:-([^}]+)\}", value)
    return match.group(1) if match else value


def test_control_plane_base_images_are_digest_pinned():
    for dockerfile in [
        ROOT / "dispatcher" / "Dockerfile",
        ROOT / "gateway" / "Dockerfile",
        ROOT / "mcp" / "Dockerfile",
    ]:
        first_from = next(
            line.strip()
            for line in dockerfile.read_text().splitlines()
            if line.strip().startswith("FROM ")
        )
        assert "@sha256:" in first_from, dockerfile


def test_engine_images_are_digest_pinned_and_no_latest_defaults():
    for name in [
        "engines/llm/compose.yaml",
        "engines/stt/compose.yaml",
        "engines/embeddings/compose.yaml",
        "engines/reranker/compose.yaml",
        "engines/ocr/compose.yaml",
    ]:
        compose = load_compose(name)
        for service, spec in compose["services"].items():
            image = image_default(spec["image"])
            assert "@sha256:" in image, (name, service, image)
            assert ":latest" not in image, (name, service, image)


def test_tts_has_reproducible_build_recipe():
    dockerfile = ROOT / "engines" / "tts" / "Dockerfile"
    lockfile = ROOT / "engines" / "tts" / "requirements.lock.txt"
    assert dockerfile.exists(), dockerfile
    assert lockfile.exists(), lockfile
    first_from = next(
        line.strip()
        for line in dockerfile.read_text().splitlines()
        if line.strip().startswith("FROM ")
    )
    assert "@sha256:" in first_from
    docker_text = dockerfile.read_text()
    assert "requirements.lock.txt" in docker_text
    assert "pip install --no-cache-dir -r requirements.lock.txt" in docker_text
    lines = [
        line.strip()
        for line in lockfile.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert lines
    assert all("==" in line for line in lines)
    assert "coqui-tts==0.27.5" in lines
    assert "transformers==4.57.6" in lines
    compose = load_compose("engines/tts/compose.yaml")
    assert "build" in compose["services"]["tts"]


def test_control_plane_installs_exact_lockfiles():
    for component in ["dispatcher", "gateway", "mcp"]:
        lock = ROOT / component / "requirements.lock.txt"
        assert lock.exists(), lock
        lines = [
            line.strip()
            for line in lock.read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]
        assert lines
        assert all("==" in line for line in lines), (component, lines)
        dockerfile = (ROOT / component / "Dockerfile").read_text()
        assert "requirements.lock.txt" in dockerfile
        assert "pip install --no-cache-dir -r requirements.lock.txt" in dockerfile


def _assert_file_entries(entries):
    assert entries
    for item in entries:
        assert item["path"]
        assert isinstance(item["size"], int) and item["size"] > 0
        assert HEX64.fullmatch(item["sha256"]), item


def test_model_lock_has_immutable_sources_and_hashes():
    lock_path = ROOT / "reproducibility" / "models.lock.json"
    assert lock_path.exists(), lock_path
    lock = json.loads(lock_path.read_text())
    assert lock["version"] == 1
    expected = {"llm", "stt", "tts", "embeddings", "reranker", "ocr"}
    assert set(lock["models"]) == expected

    for name in ["llm", "stt", "embeddings", "reranker"]:
        item = lock["models"][name]
        assert item["source_type"] == "huggingface"
        assert item["repository"]
        assert HEX40.fullmatch(item["revision"])
        _assert_file_entries(item["files"])

    ocr = lock["models"]["ocr"]
    assert ocr["source_type"] == "huggingface"
    assert set(ocr["repositories"]) == set(ocr["revisions"])
    assert all(HEX40.fullmatch(v) for v in ocr["revisions"].values())
    _assert_file_entries(ocr["files"])
    assert all(f["repository"] in ocr["revisions"] for f in ocr["files"])

    tts = lock["models"]["tts"]
    assert tts["source_type"] == "coqui-model-manager"
    assert tts["source_url"].startswith("https://")
    assert HEX64.fullmatch(tts["archive_sha256"])
    assert tts["archive_size"] > 0
    _assert_file_entries(tts["files"])


def test_image_lock_exists_and_records_immutable_refs():
    lock_path = ROOT / "reproducibility" / "images.lock.json"
    assert lock_path.exists(), lock_path
    lock = json.loads(lock_path.read_text())
    assert lock["version"] == 1
    expected = {
        "dispatcher_base",
        "python_base",
        "llm",
        "stt",
        "embeddings",
        "reranker",
        "ocr_vlm",
        "ocr_api",
        "tts_base",
    }
    assert set(lock["images"]) == expected
    for name, item in lock["images"].items():
        assert item["repository"], name
        assert SHA256.fullmatch(item["digest"]), (name, item["digest"])
        assert item["source_tag"], name


def test_stt_cache_layout_matches_hf_home():
    import sys

    repro = ROOT / "reproducibility"
    sys.path.insert(0, str(repro))
    try:
        from verify_models import stt_snapshot_path
    finally:
        sys.path.pop(0)

    lock = json.loads((repro / "models.lock.json").read_text())
    model = lock["models"]["stt"]
    path = stt_snapshot_path(model, Path("/models"))
    expected = (
        Path("/models/stt/hf-cache/hub")
        / "models--Systran--faster-whisper-large-v3"
        / "snapshots"
        / model["revision"]
    )
    assert path == expected


def _normalize_repo(value):
    if "/" not in value:
        return "docker.io/library/" + value
    first = value.split("/", 1)[0]
    if (
        "." not in first
        and ":" not in first
        and first != "localhost"
    ):
        return "docker.io/" + value
    return value


def _split_digest_ref(value):
    value = image_default(value)
    repo, digest = value.rsplit("@", 1)
    prefix, slash, leaf = repo.rpartition("/")
    if ":" in leaf:
        leaf = leaf.split(":", 1)[0]
    repo = prefix + slash + leaf
    return _normalize_repo(repo), digest


def _dockerfile_ref(path):
    line = next(
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip().startswith("FROM ")
    )
    return line.split()[1]


def test_image_lock_matches_runtime_references():
    lock = json.loads(
        (ROOT / "reproducibility" / "images.lock.json").read_text()
    )["images"]

    base_map = {
        "dispatcher_base": ROOT / "dispatcher" / "Dockerfile",
        "python_base": ROOT / "gateway" / "Dockerfile",
        "tts_base": ROOT / "engines" / "tts" / "Dockerfile",
    }
    for lock_name, dockerfile in base_map.items():
        repo, digest = _split_digest_ref(_dockerfile_ref(dockerfile))
        assert repo == lock[lock_name]["repository"]
        assert digest == lock[lock_name]["digest"]

    engine_map = {
        "llm": ("engines/llm/compose.yaml", "llm"),
        "stt": ("engines/stt/compose.yaml", "stt"),
        "embeddings": ("engines/embeddings/compose.yaml", "embeddings"),
        "reranker": ("engines/reranker/compose.yaml", "reranker"),
        "ocr_vlm": ("engines/ocr/compose.yaml", "ocr-vlm"),
        "ocr_api": ("engines/ocr/compose.yaml", "ocr-api"),
    }
    for lock_name, (path, service) in engine_map.items():
        image = load_compose(path)["services"][service]["image"]
        repo, digest = _split_digest_ref(image)
        assert repo == lock[lock_name]["repository"]
        assert digest == lock[lock_name]["digest"]


def _requirement_map(path):
    out = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, version = line.split("==", 1)
        name = re.sub(r"\[.*\]$", "", name)
        key = re.sub(r"[-_.]+", "-", name).lower()
        out[key] = version
    return out


def test_direct_requirements_match_transitive_locks():
    for component in ["dispatcher", "gateway", "mcp"]:
        direct = _requirement_map(ROOT / component / "requirements.txt")
        locked = _requirement_map(
            ROOT / component / "requirements.lock.txt"
        )
        for name, version in direct.items():
            assert locked.get(name) == version, (
                component,
                name,
                version,
                locked.get(name),
            )


def test_tts_lock_explicitly_pins_inherited_non_cuda_dependencies():
    locked = _requirement_map(ROOT / 'engines/tts/requirements.lock.txt')
    needed = {'attrs', 'numpy', 'fsspec', 'packaging', 'pyyaml', 'tqdm', 'psutil',
              'typing-extensions', 'click', 'jinja2', 'markupsafe', 'filelock',
              'requests', 'decorator', 'msgpack', 'pillow', 'platformdirs',
              'six', 'cffi', 'setuptools', 'idna', 'wheel'}
    assert needed <= set(locked), sorted(needed - set(locked))


def test_tts_install_cannot_resolve_new_transitive_packages():
    text = (ROOT / 'engines/tts/Dockerfile').read_text()
    assert '--no-deps' in text
    assert '--no-build-isolation' in text
    assert 'pip check' in text
    assert 'runtime_check.py' in text
    assert 'apt-get' not in text, 'WAV-only service must not add floating apt dependency trees'


def test_tts_base_and_runtime_versions_have_build_time_guards():
    path = ROOT / 'engines/tts/runtime_check.py'
    assert path.exists()
    text = path.read_text()
    assert '2.8.0' in text and '12.8' in text
    assert '--require-gpu' in text
    assert 'cuda.is_available' in text
    assert '0.27.5' in text


def test_tts_metadata_closure_matches_pins_for_linux_python311():
    from packaging.requirements import Requirement
    from packaging.markers import default_environment
    from packaging.specifiers import SpecifierSet
    from packaging.utils import canonicalize_name
    metadata = json.loads((ROOT / 'engines/tts/dependencies.metadata.json').read_text())
    locked = _requirement_map(ROOT / 'engines/tts/requirements.lock.txt')
    provided = metadata['base_provided']
    assert set(locked) == set(metadata['packages'])
    env = {**default_environment(), 'python_version': '3.11', 'python_full_version': '3.11.0',
           'sys_platform': 'linux', 'platform_system': 'Linux', 'platform_machine': 'x86_64'}
    extras = {}
    for _ in range(5):
        for name, item in metadata['packages'].items():
            assert item['version'] == locked[name]
            assert SpecifierSet(item['requires_python'] or '').contains('3.11.0')
            for line in item['requires_dist']:
                req = Requirement(line)
                if req.marker and not any(req.marker.evaluate({**env, 'extra': x}) for x in {''} | extras.get(name, set())):
                    continue
                key = canonicalize_name(req.name)
                extras.setdefault(key, set()).update(req.extras)
                actual = locked.get(key, provided.get(key))
                assert actual is not None, (name, str(req))
                assert req.specifier.contains(actual), (name, str(req), actual)


def test_tts_runtime_guard_rejects_changed_torch_or_missing_gpu():
    import importlib.util
    import pytest
    spec = importlib.util.spec_from_file_location('tts_runtime_check', ROOT / 'engines/tts/runtime_check.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.validate_runtime((3, 11), '2.8.0+cu128', '2.8.0+cu128', '12.8', '0.27.5')
    with pytest.raises(RuntimeError, match='torch'):
        module.validate_runtime((3, 11), '2.9.0', '2.8.0', '12.8', '0.27.5')
    with pytest.raises(RuntimeError, match='GPU required'):
        module.validate_runtime((3, 11), '2.8.0', '2.8.0', '12.8', '0.27.5', require_gpu=True)
