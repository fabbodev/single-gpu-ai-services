"""Buffered SSE compatibility for streaming-only Chat Completions clients.

Inference remains bounded and its lease is released before emitting the buffered
wire-format stream. This is deliberately not advertised as real-time token SSE.
"""
import json
import time
from uuid import uuid4
from fastapi import Response


def buffered_sse(body, *, include_usage=False):
    common = {'id': body.get('id') or 'chatcmpl-' + uuid4().hex,
              'object': 'chat.completion.chunk',
              'created': body.get('created', int(time.time())),
              'model': body.get('model', 'qwen3-8b')}
    events = []

    def emit(choices, **extra):
        events.append('data: ' + json.dumps(dict(common, choices=choices, **extra),
                                           ensure_ascii=False, allow_nan=False) + '\n\n')

    for ordinal, choice in enumerate(body['choices']):
        message = choice.get('message')
        if not isinstance(message, dict):
            raise ValueError('invalid chat message')
        index = choice.get('index', ordinal)
        emit([{'index': index, 'delta': {'role': 'assistant', 'content': ''}, 'finish_reason': None}])
        for field in ('reasoning_content', 'content'):
            value = message.get(field)
            if value is not None and not isinstance(value, str):
                raise ValueError('invalid chat content')
            if value:
                emit([{'index': index, 'delta': {field: value}, 'finish_reason': None}])
        calls = message.get('tool_calls') or []
        if not isinstance(calls, list):
            raise ValueError('invalid chat tool calls')
        if calls:
            tools = []
            for n, call in enumerate(calls):
                fn = call.get('function') if isinstance(call, dict) else None
                if (not isinstance(fn, dict) or not isinstance(call.get('id'), str)
                        or not isinstance(fn.get('name'), str) or not isinstance(fn.get('arguments'), str)):
                    raise ValueError('invalid chat tool call')
                tools.append(dict(call, index=n))
            emit([{'index': index, 'delta': {'tool_calls': tools}, 'finish_reason': None}])
        reason = choice.get('finish_reason') or ('tool_calls' if calls else 'stop')
        emit([{'index': index, 'delta': {}, 'finish_reason': reason}])
    if include_usage:
        emit([], usage=body.get('usage'))
    events.append('data: [DONE]\n\n')
    return Response(''.join(events), media_type='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-AI-Stream-Mode': 'buffered'})
