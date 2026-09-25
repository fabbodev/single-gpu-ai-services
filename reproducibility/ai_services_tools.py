"""Guarded VM preparation. Default prints a plan; never starts/stops GPU engines."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess

ROOT = Path(__file__).resolve().parents[1]
GPU_CONTAINERS = {'ai-llm', 'ai-embeddings', 'ai-reranker', 'ai-stt', 'ai-tts', 'ai-ocr-vlm', 'ai-ocr-api'}
TTS_IMAGE = 'ai-services/coqui-tts:0.27.5-cu128'


def run(*command, timeout=120):
    return subprocess.run(list(command), check=True, capture_output=True, text=True, timeout=timeout).stdout.strip()


def require_gpu_host(execute):
    if not execute:
        raise RuntimeError('Real actions require --execute; use plan on the development host')
    hostname = socket.gethostname().split('.')[0]
    if hostname != 'ai-services':
        raise RuntimeError(f'Refusing real action on {hostname}: run natively on ai-services')
    if os.environ.get('DOCKER_HOST') and not os.environ['DOCKER_HOST'].startswith('unix://'):
        raise RuntimeError('Refusing non-local DOCKER_HOST')
    endpoint = json.loads(run('docker', 'context', 'inspect', '--format', '{{json .Endpoints.docker.Host}}'))
    if not isinstance(endpoint, str) or not endpoint.startswith('unix://'):
        raise RuntimeError('Docker context must use a local Unix socket')
    daemon = run('docker', 'info', '--format', '{{.Name}}').split('.')[0]
    if daemon != hostname:
        raise RuntimeError('Docker daemon name does not match the local GPU host')


def pull_command(item):
    return ['docker', 'pull', '--platform', 'linux/amd64', item['repository'] + '@' + item['digest']]


def canonical_digest_ref(ref):
    repository, digest = ref.rsplit('@', 1)
    if '/' not in repository:
        repository = 'docker.io/library/' + repository
    elif not any(x in repository.split('/')[0] for x in ('.', ':')):
        repository = 'docker.io/' + repository
    repository = repository.replace('index.docker.io/', 'docker.io/', 1)
    return repository + '@' + digest


def validate_image(data, item):
    if (data.get('Os'), data.get('Architecture')) != ('linux', 'amd64'):
        raise ValueError('local image is not linux/amd64')
    acceptable = {item['repository'] + '@' + item['digest']}
    if item.get('amd64_digest'):
        acceptable.add(item['repository'] + '@' + item['amd64_digest'])
    if not {canonical_digest_ref(x) for x in acceptable}.intersection(
            canonical_digest_ref(x) for x in (data.get('RepoDigests') or [])):
        raise ValueError('local RepoDigests do not match the image lock')
    return {'image_id': data['Id'], 'repo_digests': data['RepoDigests'], 'platform': 'linux/amd64'}


def inspect_image(item):
    ref = item['repository'] + '@' + item['digest']
    data = json.loads(run('docker', 'image', 'inspect', ref))[0]
    return validate_image(data, item)


def assert_idle(max_idle_mib):
    running = set(run('docker', 'ps', '--format', '{{.Names}}').splitlines())
    active = sorted(GPU_CONTAINERS.intersection(running))
    if active:
        raise RuntimeError(f'GPU engines still running: {active}; no automatic stop performed')
    output = run('nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits')
    used = [int(line.strip()) for line in output.splitlines() if line.strip()]
    if not used or any(value > max_idle_mib for value in used):
        raise RuntimeError(f'VRAM idle check failed: {used}, limit={max_idle_mib} MiB; no cleanup performed')
    return {'gpu_engines_running': [], 'memory_used_mib': used, 'max_idle_mib': max_idle_mib}


def preflight():
    model_root = Path('/opt/ai-services/models')
    measured = model_root if model_root.exists() else model_root.parent
    space = shutil.disk_usage(measured)
    docker_root = Path(run('docker', 'info', '--format', '{{.DockerRootDir}}'))
    report = {'model_disk': {'path': str(measured), 'free_bytes': space.free, 'total_bytes': space.total},
              'docker_root': str(docker_root), 'docker_system_df': run('docker', 'system', 'df'),
              'gpu': run('nvidia-smi', '--query-gpu=name,driver_version,memory.total,memory.used', '--format=csv,noheader'),
              'running_containers': run('docker', 'ps', '--format', '{{.Names}}')}
    try:
        disk = shutil.disk_usage(docker_root)
        report['docker_disk'] = {'free_bytes': disk.free, 'total_bytes': disk.total}
    except OSError:
        report['docker_disk'] = {'warning': 'Cannot stat Docker root as this user; check filesystem space before pulls.'}
    report['warning'] = 'Check expanded image and build-cache usage after EACH pull. No prune is ever automatic.'
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--action', choices=['plan', 'preflight', 'pull', 'verify-images', 'build-tts', 'idle'], default='plan')
    parser.add_argument('--image', help='One lock entry per pull (e.g. llm, embeddings, tts_base)')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--max-idle-mib', type=int, default=64)
    args = parser.parse_args()
    lock_path = ROOT / 'reproducibility/images.lock.json'
    lock = json.loads(lock_path.read_text())['images']
    if args.image and args.image not in lock:
        parser.error(f'unknown image; choose from {", ".join(lock)}')
    if args.max_idle_mib < 0:
        parser.error('--max-idle-mib must be nonnegative')
    if args.action == 'plan':
        print('PLAN ONLY: no Docker command executed. All real actions require ai-services and --execute.')
        seen = set()
        for name in ([args.image] if args.image else lock):
            command = pull_command(lock[name])
            if command[-1] not in seen:
                print(name + ': ' + ' '.join(command)); seen.add(command[-1])
        print('TTS: build locally after pulling the locked base; GPU inference remains a separate gate.')
        return
    if args.action == 'pull' and not args.image:
        parser.error('pull requires exactly one --image; no bulk downloads')
    require_gpu_host(args.execute)
    receipt = {'timestamp_utc': datetime.now(timezone.utc).isoformat(), 'action': args.action,
               'image_lock_sha256': hashlib.sha256(lock_path.read_bytes()).hexdigest()}
    if args.action == 'preflight':
        receipt['result'] = preflight()
    elif args.action == 'pull':
        command = pull_command(lock[args.image])
        subprocess.run(command, check=True, timeout=7200)
        receipt['result'] = {args.image: inspect_image(lock[args.image])}
    elif args.action == 'verify-images':
        names = [args.image] if args.image else lock
        receipt['result'] = {name: inspect_image(lock[name]) for name in names}
    elif args.action == 'build-tts':
        # Abort before the build if the pinned base has not been pulled/verified locally.
        receipt['base'] = inspect_image(lock['tts_base'])
        subprocess.run(['docker', 'build', '--platform', 'linux/amd64', '--pull=false',
                        '-t', TTS_IMAGE, str(ROOT / 'engines/tts')], check=True, timeout=7200)
        data = json.loads(run('docker', 'image', 'inspect', TTS_IMAGE))[0]
        receipt['result'] = {'image': TTS_IMAGE, 'image_id': data['Id'], 'gpu_tested': False}
    elif args.action == 'idle':
        receipt['result'] = assert_idle(args.max_idle_mib)
    if args.receipt:
        args.receipt.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(f'FAIL: {exc}')
