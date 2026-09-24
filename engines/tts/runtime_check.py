"""Build-time ABI/import checks; GPU validation is explicit and only on the GPU host."""
import argparse
import importlib
from importlib.metadata import version
import json
import platform
import sys


def validate_runtime(python_version, torch_version, audio_version, cuda_version,
                     coqui_version, *, require_gpu=False, cuda_available=False):
    expected = ((python_version, (3, 11), 'Python'),
                (torch_version.split('+')[0], '2.8.0', 'torch'),
                (audio_version.split('+')[0], '2.8.0', 'torchaudio'),
                (cuda_version, '12.8', 'CUDA build'),
                (coqui_version, '0.27.5', 'coqui-tts'))
    for actual, wanted, label in expected:
        if actual != wanted:
            raise RuntimeError(f'{label}: expected {wanted}, got {actual}')
    if require_gpu and not cuda_available:
        raise RuntimeError('GPU required but torch.cuda.is_available() is false')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-gpu', action='store_true')
    args = parser.parse_args()
    if platform.machine() not in ('x86_64', 'AMD64'):
        raise RuntimeError('This recipe targets Linux amd64')
    import torch
    import torchaudio
    import soundfile
    importlib.import_module('TTS.api')
    gpu_ok = torch.cuda.is_available() if args.require_gpu else False
    validate_runtime(sys.version_info[:2], torch.__version__, torchaudio.__version__,
                     torch.version.cuda, version('coqui-tts'),
                     require_gpu=args.require_gpu, cuda_available=gpu_ok)
    print(json.dumps({'torch': torch.__version__, 'torchaudio': torchaudio.__version__,
        'cuda_build': torch.version.cuda, 'coqui_tts': version('coqui-tts'),
        'libsndfile': soundfile.__libsndfile_version__, 'gpu_checked': args.require_gpu,
        'gpu_name': torch.cuda.get_device_name(0) if args.require_gpu else None}, indent=2))


if __name__ == '__main__':
    main()
