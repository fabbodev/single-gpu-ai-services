"""Opt-in real Gateway/MCP smoke checks. Default is an offline plan, not inference."""
import argparse
import asyncio
import io
import json
import math
import mimetypes
from pathlib import Path
import sys
import time
import urllib.parse
import urllib.request
import uuid
import wave

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'reproducibility'))
from ai_services_tools import assert_idle, require_gpu_host

MODELS = {'llm': 'qwen3-8b', 'embeddings': 'bge-m3', 'reranker': 'bge-reranker-v2-m3',
          'stt': 'faster-whisper-large-v3', 'tts': 'coqui-es-css10-vits', 'ocr': 'paddleocr-vl-1.6'}
ROUTES = {'llm': '/v1/chat/completions', 'embeddings': '/v1/embeddings', 'reranker': '/v1/rerank',
          'stt': '/v1/audio/transcriptions', 'tts': '/v1/audio/speech', 'ocr': '/v1/documents/read'}


def validate_response(service, data):
    if service == 'tts':
        try:
            with wave.open(io.BytesIO(data), 'rb') as wav:
                result = {'frames': wav.getnframes(), 'sample_rate': wav.getframerate(), 'channels': wav.getnchannels()}
                if result['frames'] <= 0 or result['sample_rate'] <= 0:
                    raise ValueError('empty WAV')
                return result
        except (wave.Error, EOFError, TypeError) as exc:
            raise ValueError('response is not a valid WAV') from exc
    if not isinstance(data, dict):
        raise ValueError('response must be a JSON object')
    if service in ('stt', 'ocr', 'llm'):
        try:
            text = data['choices'][0]['message']['content'] if service == 'llm' else data['text']
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError('missing response text') from exc
        if not isinstance(text, str) or not text.strip():
            raise ValueError('empty response text')
        return {'characters': len(text)}
    if service == 'embeddings':
        try:
            vector = data['data'][0]['embedding']
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError('missing embedding') from exc
        if not isinstance(vector, list) or not vector or not all(
                isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in vector):
            raise ValueError('embedding must be a finite non-empty numeric vector')
        return {'dimensions': len(vector)}
    if service == 'reranker':
        rows = data.get('results')
        if not isinstance(rows, list) or len(rows) != 2 or not all(isinstance(r, dict) for r in rows):
            raise ValueError('reranker must return both fixture documents')
        if {r.get('index') for r in rows} != {0, 1} or not all(
                isinstance(r.get('score'), (int, float)) and math.isfinite(r['score']) for r in rows):
            raise ValueError('invalid reranker indices or scores')
        if rows[0]['score'] < rows[1]['score']:
            raise ValueError('reranker results are not sorted by score')
        return {'documents': len(rows), 'top_index': rows[0]['index']}
    raise ValueError(f'unsupported service: {service}')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Authenticated smoke requests must not redirect')


def checked_url(value):
    parts = urllib.parse.urlsplit(value)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('Provide a plain HTTP(S) endpoint without credentials, query, or fragment')
    return value.rstrip('/')


def post(url, token, data, content_type='application/json'):
    body = json.dumps(data, allow_nan=False).encode() if isinstance(data, dict) else data
    request = urllib.request.Request(url, data=body, method='POST',
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': content_type})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=300) as response:
        raw = response.read(32 * 1024 * 1024 + 1)
        if len(raw) > 32 * 1024 * 1024:
            raise ValueError('smoke response exceeds 32 MiB')
        return raw


def multipart(path, fields):
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('Use a small smoke fixture (at most 16 MiB)')
    boundary = 'block4-' + uuid.uuid4().hex
    parts = []
    for key, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    name = path.name.replace('"', '_').replace('\r', '_').replace('\n', '_')
    mime = mimetypes.guess_type(name)[0] or 'application/octet-stream'
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: {mime}\r\n\r\n'.encode())
    parts.extend([path.read_bytes(), f'\r\n--{boundary}--\r\n'.encode()])
    return b''.join(parts), 'multipart/form-data; boundary=' + boundary


def wait_idle(limit):
    deadline = time.monotonic() + 90
    while True:
        try:
            return assert_idle(limit)
        except RuntimeError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.5)


async def mcp_embed(url, token, text):
    from fastmcp import Client
    from fastmcp.client.auth.bearer import BearerAuth
    async with Client(url, auth=BearerAuth(token), timeout=300) as client:
        result = await client.call_tool('embed_text', {'input': text}, timeout=300)
        if result.is_error or not isinstance(result.structured_content, dict):
            raise ValueError('MCP embed_text failed or returned no structured result')
        validate_response('embeddings', result.structured_content)
        return result.structured_content


def tool_cycle(base, mcp_url, token, limit):
    tool = {'type': 'function', 'function': {'name': 'embed_text', 'description': 'Compute a text embedding.',
            'parameters': {'type': 'object', 'properties': {'input': {'type': 'string'}}, 'required': ['input'], 'additionalProperties': False}}}
    messages = [{'role': 'user', 'content': '/no_think\nUse embed_text on Hola mundo. Then report the embedding dimension.'}]
    initial = json.loads(post(base + ROUTES['llm'], token, {'model': MODELS['llm'], 'messages': messages,
        'tools': [tool], 'tool_choice': {'type': 'function', 'function': {'name': 'embed_text'}}, 'max_tokens': 256}))
    wait_idle(limit)
    message = initial['choices'][0]['message']; calls = message.get('tool_calls') or []
    if len(calls) != 1 or calls[0]['function']['name'] != 'embed_text':
        raise ValueError('Qwen did not produce the expected single embed_text tool call')
    call = calls[0]; arguments = json.loads(call['function']['arguments'])
    text = arguments.get('input')
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        raise ValueError('Qwen tool arguments are invalid')
    result = asyncio.run(mcp_embed(mcp_url, token, text))
    wait_idle(limit)
    messages += [{'role': 'assistant', 'content': message.get('content'), 'tool_calls': calls},
                 {'role': 'tool', 'tool_call_id': call['id'], 'content': json.dumps(result)}]
    resumed = json.loads(post(base + ROUTES['llm'], token, {'model': MODELS['llm'], 'messages': messages,
        'tools': [tool], 'tool_choice': 'none', 'max_tokens': 256}))
    validation = validate_response('llm', resumed)
    return {'steps': ['Qwen tool call', 'MCP embed_text', 'Qwen resume'],
            'embedding': validate_response('embeddings', result), 'final_response': validation}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--service', choices=list(MODELS) + ['mcp-embeddings', 'tool-cycle'], required=True)
    parser.add_argument('--base-url')
    parser.add_argument('--mcp-url')
    parser.add_argument('--token-file', type=Path)
    parser.add_argument('--file', type=Path)
    parser.add_argument('--wav-output', type=Path)
    parser.add_argument('--expect-text')
    parser.add_argument('--max-idle-mib', type=int, default=64)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if not args.execute:
        print(f'PLAN ONLY: {args.service}; no token read, no network or GPU access. Requires native ai-services + --execute.')
        return
    if not args.base_url or not args.token_file:
        parser.error('--base-url and --token-file are required for execution')
    if args.service in ('stt', 'ocr') and not args.file:
        parser.error('STT/OCR requires --file with a real smoke fixture')
    if args.service in ('mcp-embeddings', 'tool-cycle') and not args.mcp_url:
        parser.error('MCP checks require --mcp-url')
    base = checked_url(args.base_url)
    mcp_url = checked_url(args.mcp_url) if args.mcp_url else None
    require_gpu_host(args.execute)
    token = args.token_file.read_text().strip()
    if not token or any(ch.isspace() for ch in token):
        raise ValueError('Token file must contain one nonempty bearer token')
    assert_idle(args.max_idle_mib)
    try:
        if args.service == 'tool-cycle':
            result = tool_cycle(base, mcp_url, token, args.max_idle_mib)
        elif args.service == 'mcp-embeddings':
            result = validate_response('embeddings', asyncio.run(mcp_embed(mcp_url, token, 'Hola mundo')))
        else:
            name = args.service
            payload = {'model': MODELS[name]}
            content_type = 'application/json'
            if name == 'llm':
                payload.update(messages=[{'role': 'user', 'content': '/no_think\nResponde solamente: LISTO.'}], max_tokens=128)
            elif name == 'embeddings':
                payload['input'] = 'Hola mundo'
            elif name == 'reranker':
                payload.update(query='capital de Francia', documents=['La mesa es azul.', 'Paris es la capital de Francia.'])
            elif name == 'tts':
                payload.update(input='Hola mundo. Esta es una prueba de voz en español.', response_format='wav')
            else:
                if name == 'stt':
                    payload['language'] = 'es'
                payload, content_type = multipart(args.file, payload)
            raw = post(base + ROUTES[name], token, payload, content_type)
            data = raw if name == 'tts' else json.loads(raw)
            result = validate_response(name, data)
            if args.expect_text:
                text = data['choices'][0]['message']['content'] if name == 'llm' else data.get('text', '')
                if args.expect_text.casefold() not in text.casefold():
                    raise ValueError('Expected text is absent from the response')
            if name == 'tts' and args.wav_output:
                with args.wav_output.open('xb') as target:
                    target.write(raw)
    finally:
        idle = wait_idle(args.max_idle_mib)
    print(json.dumps({'status': 'PASS', 'service': args.service, 'validation': result, 'idle': idle}, indent=2))


if __name__ == '__main__':
    main()
