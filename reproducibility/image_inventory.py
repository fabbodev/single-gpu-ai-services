"""Inspect registry manifests/config metadata only. Never pulls image layers."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent


def decode_manifest(raw, expected_digest):
    # buildx may append one presentation newline to the original registry bytes.
    candidates = [raw, raw[:-1]] if raw.endswith(b'\n') else [raw]
    for data in candidates:
        if 'sha256:' + hashlib.sha256(data).hexdigest() == expected_digest:
            return json.loads(data)
    raise ValueError(f'registry manifest digest mismatch: expected {expected_digest}')


def amd64_child(index, expected=None):
    matches = [m['digest'] for m in index['manifests']
               if m.get('platform', {}).get('os') == 'linux'
               and m.get('platform', {}).get('architecture') == 'amd64']
    if len(matches) != 1 or (expected and matches[0] != expected):
        raise ValueError('linux/amd64 child does not match the lock unambiguously')
    return matches[0]


def unique_layer_bytes(layer_groups):
    sizes = {}
    for layers in layer_groups:
        for layer in layers:
            digest, size = layer['digest'], layer['size']
            if not isinstance(size, int) or size < 0:
                raise ValueError('invalid layer size')
            if digest in sizes and sizes[digest] != size:
                raise ValueError('same layer digest has conflicting size')
            sizes[digest] = size
    return sum(sizes.values())


def docker_metadata(*args):
    return subprocess.run(['docker', 'buildx', 'imagetools', 'inspect', *args],
                          check=True, capture_output=True, timeout=90).stdout


def inspect_locked(item):
    repository, digest = item['repository'], item['digest']
    manifest = decode_manifest(docker_metadata('--raw', f'{repository}@{digest}'), digest)
    if 'manifests' in manifest:
        digest = amd64_child(manifest, item.get('amd64_digest'))
        manifest = decode_manifest(docker_metadata('--raw', f'{repository}@{digest}'), digest)
    elif item.get('amd64_digest') and item['amd64_digest'] != digest:
        raise ValueError('single-platform digest disagrees with amd64 lock')
    config = json.loads(docker_metadata('--format', '{{json .Image}}', f'{repository}@{digest}'))
    if (config.get('os'), config.get('architecture')) != ('linux', 'amd64'):
        raise ValueError('image config is not linux/amd64')
    layers = manifest['layers']
    return {'source_ref': f'{repository}@{item["digest"]}', 'amd64_digest': digest,
            'platform': 'linux/amd64', 'compressed_layer_bytes': unique_layer_bytes([layers]),
            'layers': layers, 'config_digest': manifest['config']['digest']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock', type=Path, default=HERE / 'images.lock.json')
    parser.add_argument('--inspect-registry', action='store_true', help='Fetch JSON metadata, never layers')
    parser.add_argument('--image', action='append')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    lock = json.loads(args.lock.read_text())['images']
    names = args.image or list(lock)
    unknown = set(names) - set(lock)
    if unknown:
        parser.error(f'unknown image names: {sorted(unknown)}')
    if not args.inspect_registry:
        print('PLAN ONLY: registry inspection needs --inspect-registry; no images downloaded')
        for name in names:
            print(name, lock[name]['repository'] + '@' + lock[name]['digest'])
        return
    results, cache = {}, {}
    for name in names:
        item = lock[name]
        key = (item['repository'], item['digest'])
        if key not in cache:
            cache[key] = inspect_locked(item)
        results[name] = cache[key]
        print(f'{name}: {results[name]["compressed_layer_bytes"] / 1024**3:.3f} GiB compressed; manifest verified', flush=True)
    report = {'timestamp_utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'registry-metadata-only-no-layer-downloads', 'images': results,
              'unique_compressed_layer_bytes': unique_layer_bytes([x['layers'] for x in cache.values()]),
              'disk_warning': 'Compressed transfer size is NOT unpacked Docker or build-cache disk usage.'}
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(f'Unique compressed layers: {report["unique_compressed_layer_bytes"] / 1024**3:.3f} GiB')
    print(report['disk_warning'])


if __name__ == '__main__':
    main()
