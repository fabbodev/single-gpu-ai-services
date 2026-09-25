"""Preparation helpers must be safe to use on a CPU-only development host."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    path = ROOT / 'reproducibility' / (name + '.py')
    assert path.exists(), f'Missing preparation helper: {path.name}'
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_digest_is_checked_and_cli_newline_is_allowed():
    m = load('image_inventory')
    data = b'{"schemaVersion":2,"layers":[]}'
    digest = 'sha256:' + hashlib.sha256(data).hexdigest()
    assert m.decode_manifest(data + b'\n', digest)['schemaVersion'] == 2
    with pytest.raises(ValueError, match='digest'):
        m.decode_manifest(data + b' ', digest)


def test_multiarch_selection_must_match_locked_amd64_child():
    m = load('image_inventory')
    entries = {'manifests': [
        {'digest': 'sha256:' + 'a'*64, 'platform': {'os': 'linux', 'architecture': 'arm64'}},
        {'digest': 'sha256:' + 'b'*64, 'platform': {'os': 'linux', 'architecture': 'amd64'}}]}
    assert m.amd64_child(entries, 'sha256:' + 'b'*64) == 'sha256:' + 'b'*64
    with pytest.raises(ValueError, match='amd64'):
        m.amd64_child(entries, 'sha256:' + 'c'*64)


def test_shared_layers_are_counted_once_and_conflicts_fail():
    m = load('image_inventory')
    layer = {'digest': 'sha256:'+'a'*64, 'size': 123}
    assert m.unique_layer_bytes([[layer], [layer]]) == 123
    with pytest.raises(ValueError, match='size'):
        m.unique_layer_bytes([[layer], [{**layer, 'size': 321}]])


def test_gpu_host_guard_rejects_agent_hub_before_docker(monkeypatch):
    m = load('ai_services_tools')
    monkeypatch.setattr(m.socket, 'gethostname', lambda: 'agent-hub')
    monkeypatch.setattr(m.subprocess, 'run', lambda *a, **k: pytest.fail('Must not contact Docker'))
    with pytest.raises(RuntimeError, match='ai-services'):
        m.require_gpu_host(True)


def test_gpu_host_guard_requires_explicit_execute(monkeypatch):
    m = load('ai_services_tools')
    monkeypatch.setattr(m.socket, 'gethostname', lambda: 'ai-services')
    monkeypatch.setattr(m.subprocess, 'run', lambda *a, **k: pytest.fail('Must not contact Docker'))
    with pytest.raises(RuntimeError, match='--execute'):
        m.require_gpu_host(False)


def test_image_receipt_requires_linux_amd64_and_matching_repo_digest():
    m = load('ai_services_tools')
    item = {'repository': 'example/image', 'digest': 'sha256:'+'a'*64}
    good = {'Os': 'linux', 'Architecture': 'amd64', 'Id': 'sha256:'+'f'*64,
            'RepoDigests': ['example/image@sha256:'+'a'*64]}
    assert m.validate_image(good, item)['image_id'] == good['Id']
    for bad in [{**good, 'Architecture': 'arm64'}, {**good, 'RepoDigests': []}]:
        with pytest.raises(ValueError):
            m.validate_image(bad, item)


def test_pull_plan_is_digest_only_and_never_starts_an_engine():
    m = load('ai_services_tools')
    lock = json.loads((ROOT / 'reproducibility/images.lock.json').read_text())
    for name in lock['images']:
        command = m.pull_command(lock['images'][name])
        assert command[:4] == ['docker', 'pull', '--platform', 'linux/amd64']
        assert '@sha256:' in command[-1]
        assert 'run' not in command and 'up' not in command


def test_default_preparation_plan_does_not_access_docker():
    path = ROOT / 'reproducibility/ai_services_tools.py'
    assert path.exists()
    result = subprocess.run([sys.executable, str(path)], capture_output=True, text=True,
                            env={'PATH': '/deliberately-empty'})
    assert result.returncode == 0, result.stderr
    assert 'PLAN ONLY' in result.stdout


def test_cpu_runner_is_present_and_uses_separate_component_processes():
    m = load('run_cpu_checks')
    commands = m.test_commands(ROOT, sys.executable)
    assert [p.name for p, cmd in commands] == [ROOT.name, 'dispatcher', 'gateway', 'mcp']
    assert all(cmd[:3] == [sys.executable, '-m', 'pytest'] for p, cmd in commands)


def test_docker_hub_short_repo_digest_matches_canonical_lock_name():
    m = load('ai_services_tools')
    item = {'repository': 'docker.io/library/python', 'digest': 'sha256:'+'a'*64}
    data = {'Os': 'linux', 'Architecture': 'amd64', 'Id': 'sha256:'+'b'*64,
            'RepoDigests': ['python@sha256:'+'a'*64]}
    assert m.validate_image(data, item)['image_id'] == data['Id']


def smoke_module():
    path = ROOT / 'tests/integration/block4_real_gpu_check.py'
    assert path.exists(), 'Real-engine smoke helper is missing'
    spec = importlib.util.spec_from_file_location('block4_real_gpu_check', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_smoke_validator_checks_finite_vectors_and_ranking():
    m = smoke_module()
    assert m.validate_response('embeddings', {'data': [{'embedding': [0.2, 0.4, 0.6]}]})['dimensions'] == 3
    with pytest.raises(ValueError):
        m.validate_response('embeddings', {'data': [{'embedding': [float('nan')]}]})
    assert m.validate_response('reranker', {'results': [{'index': 1, 'score': 0.9}, {'index': 0, 'score': 0.1}]})['documents'] == 2
    with pytest.raises(ValueError):
        m.validate_response('reranker', {'results': [{'index': 7, 'score': 0.9}]})


def test_smoke_rejects_empty_transcription_ocr_or_llm_output():
    m = smoke_module()
    for service, data in [('stt', {'text': ''}), ('ocr', {'text': ' '}),
                          ('llm', {'choices': [{'message': {'content': ''}}]})]:
        with pytest.raises(ValueError):
            m.validate_response(service, data)


def test_smoke_validates_wav_frames_instead_of_only_http_status():
    import io, wave
    m = smoke_module()
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(22050); wav.writeframes(b'\0\0'*200)
    assert m.validate_response('tts', buf.getvalue())['sample_rate'] == 22050
    with pytest.raises(ValueError):
        m.validate_response('tts', b'not a wave file')


def test_smoke_plan_cannot_read_a_token_or_call_a_service():
    path = ROOT / 'tests/integration/block4_real_gpu_check.py'
    assert path.exists()
    result = subprocess.run([sys.executable, str(path), '--service', 'tool-cycle'],
                            capture_output=True, text=True, env={'PATH': '/deliberately-empty'})
    assert result.returncode == 0, result.stderr
    assert 'PLAN ONLY' in result.stdout
