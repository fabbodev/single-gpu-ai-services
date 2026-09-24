"""Offline regression tests: synthetic bytes only, never real model downloads."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'reproducibility'))
import verify_models as verify


def tiny_lock():
    lock = json.loads((ROOT / 'reproducibility/models.lock.json').read_text())
    for name, item in lock['models'].items():
        for entry in item['files']:
            data = f"fixture:{name}:{entry['path']}".encode()
            entry.update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
    return lock


def write_group(lock, root, name):
    item = lock['models'][name]
    base = verify.remap_local_path(item['local_path'], root)
    for entry in item['files']:
        if name == 'llm':
            target = base
        elif name == 'stt':
            target = verify.stt_snapshot_path(item, root) / entry['path']
        elif name == 'ocr':
            target = base / entry['local_subdir'] / entry['path']
        else:
            target = base / entry['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(f"fixture:{name}:{entry['path']}".encode())
    if name == 'stt':
        ref = verify.stt_repo_cache_path(item, root) / 'refs/main'
        ref.parent.mkdir(parents=True, exist_ok=True)
        ref.write_text(item['revision'] + '\n')


@pytest.mark.parametrize('name', ['llm', 'embeddings', 'reranker', 'stt', 'tts', 'ocr'])
def test_selected_model_verifies_without_other_groups(tmp_path, name):
    lock = tiny_lock()
    write_group(lock, tmp_path, name)
    assert verify.verify_locked_models(lock, tmp_path, selected=[name]) == []


def test_default_verification_still_requires_every_model(tmp_path):
    lock = tiny_lock()
    write_group(lock, tmp_path, 'llm')
    errors = verify.verify_locked_models(lock, tmp_path)
    assert errors and any('missing' in e for e in errors)


def test_same_size_corruption_is_not_accepted(tmp_path):
    lock = tiny_lock()
    write_group(lock, tmp_path, 'llm')
    target = verify.remap_local_path(lock['models']['llm']['local_path'], tmp_path)
    target.write_bytes(b'x' * target.stat().st_size)
    errors = verify.verify_locked_models(lock, tmp_path, selected=['llm'])
    assert len(errors) == 1 and 'sha256 mismatch' in errors[0]


def test_bad_stt_revision_ref_fails_selected_verification(tmp_path):
    lock = tiny_lock()
    write_group(lock, tmp_path, 'stt')
    ref = verify.stt_repo_cache_path(lock['models']['stt'], tmp_path) / 'refs/main'
    ref.write_text('bad-revision\n')
    assert any('ref mismatch' in e for e in verify.verify_locked_models(lock, tmp_path, selected=['stt']))


def test_unknown_group_rejected_before_verification(tmp_path):
    with pytest.raises(ValueError, match='unknown model'):
        verify.verify_locked_models(tiny_lock(), tmp_path, selected=['typo'])


def test_verifier_cli_supports_one_model(tmp_path):
    lock = tiny_lock()
    write_group(lock, tmp_path, 'llm')
    path = tmp_path / 'lock.json'
    path.write_text(json.dumps(lock))
    result = subprocess.run([sys.executable, str(ROOT / 'reproducibility/verify_models.py'),
        '--lock', str(path), '--root', str(tmp_path), '--model', 'llm'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr + result.stdout
    assert 'PASS' in result.stdout


def test_provisioner_help_does_not_require_hf_sdk():
    result = subprocess.run(['/usr/bin/python3', str(ROOT / 'reproducibility/provision_models.py'),
        '--help'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_offline_precheck_does_not_create_model_root(tmp_path):
    dest = tmp_path / 'never-created'
    result = subprocess.run(['/usr/bin/python3', str(ROOT / 'reproducibility/provision_models.py'),
        '--lock', str(ROOT / 'reproducibility/models.lock.json'), '--root', str(dest),
        '--check-only', '--offline', '--model', 'llm'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr + result.stdout
    assert not dest.exists()
    assert 'no model payloads downloaded' in result.stdout


def test_canonical_model_mapping_rejects_parent_traversal(tmp_path):
    with pytest.raises(ValueError, match='path'):
        verify.remap_local_path('/opt/ai-services/models/../outside', tmp_path)


def test_verification_rejects_file_paths_outside_model_directory(tmp_path):
    lock = tiny_lock()
    lock['models']['tts']['files'][0]['path'] = '../outside'
    with pytest.raises(ValueError, match='path'):
        verify.verify_locked_models(lock, tmp_path, selected=['tts'])


def test_provisioning_requires_explicit_download_consent(tmp_path):
    result = subprocess.run(['/usr/bin/python3', str(ROOT / 'reproducibility/provision_models.py'),
        '--model', 'llm', '--root', str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 2
    assert '--download' in result.stderr
    assert 'huggingface_hub' not in result.stderr


def test_offline_precheck_does_not_claim_an_installed_transfer_sdk(tmp_path):
    result = subprocess.run(['/usr/bin/python3', str(ROOT / 'reproducibility/provision_models.py'),
        '--check-only', '--offline', '--model', 'llm', '--root', str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'installed and enabled' not in result.stdout
