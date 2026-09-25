import hashlib
import json
import os

import pytest
from fastapi.testclient import TestClient
from app import main
from app.auth import ClientTokenStore

TOKEN = 'scope-test-token-not-a-real-secret'
CAPS = ['llm','embeddings','reranker','ocr','stt','tts']


def publish(path, *, scopes=None, enabled=True, token=TOKEN):
    data = {'version':1,'clients':[{'client_id':'scoped-client','token_sha256':hashlib.sha256(token.encode()).hexdigest(),'scopes':scopes or ['gateway',*CAPS],'enabled':enabled}]}
    temp = path.with_suffix('.next'); temp.write_text(json.dumps(data)); os.replace(temp,path)


@pytest.fixture
def scoped(tmp_path, monkeypatch):
    path = tmp_path / 'registry.json'; publish(path, scopes=['gateway','embeddings'])
    monkeypatch.setattr(main,'client_tokens',ClientTokenStore.from_file(path))
    return path, TestClient(main.app, raise_server_exceptions=False)


@pytest.mark.parametrize('path,payload,upload', [
    ('/v1/chat/completions',{'model':'qwen3-8b','messages':[{'role':'user','content':'hi'}]},False),
    ('/v1/embeddings',{'model':'bge-m3','input':'hi'},False),
    ('/v1/rerank',{'model':'bge-reranker-v2-m3','query':'hi','documents':['one']},False),
    ('/v1/audio/speech',{'model':'coqui-es-css10-vits','input':'hi'},False),
    ('/v1/audio/transcriptions',{'model':'faster-whisper-large-v3'},True),
    ('/v1/documents/read',{'model':'paddleocr-vl-1.6'},True),
])
def test_denied_capability_never_acquires_gpu(scoped, monkeypatch, path, payload, upload):
    registry, client = scoped
    publish(registry, scopes=['gateway'])
    # Reload even in the old implementation so this test isolates capability gates.
    monkeypatch.setattr(main,'client_tokens',ClientTokenStore.from_file(registry))
    called = []
    async def forbidden(service):
        called.append(service); raise AssertionError('denied request acquired GPU')
    monkeypatch.setattr(main,'_acquire_lease',forbidden)
    kw = {'data':payload,'files':{'file':('fixture',b'fixture','application/octet-stream')}} if upload else {'json':payload}
    response = client.post(path,headers={'Authorization':'Bearer '+TOKEN},**kw)
    assert response.status_code == 403
    assert not called


def test_model_discovery_only_lists_authorized_capabilities(scoped):
    _, client = scoped
    response = client.get('/v1/models',headers={'Authorization':'Bearer '+TOKEN})
    assert response.status_code == 200
    assert [x['id'] for x in response.json()['data']] == ['bge-m3']


def test_gateway_reflects_disable_and_rotation_without_restart(scoped):
    registry, client = scoped
    request = lambda token: client.get('/v1/models',headers={'Authorization':'Bearer '+token})
    assert request(TOKEN).status_code == 200
    publish(registry,enabled=False); assert request(TOKEN).status_code == 401
    publish(registry,token='replacement-test-token')
    assert request(TOKEN).status_code == 401
    assert request('replacement-test-token').status_code == 200


def test_gateway_fails_closed_and_recovers_after_corrupt_registry(scoped):
    registry, client = scoped
    registry.write_text('{broken')
    response = client.get('/v1/models',headers={'Authorization':'Bearer '+TOKEN})
    assert response.status_code == 503
    assert response.json()['detail'] == 'client registry unavailable'
    publish(registry)
    assert client.get('/v1/models',headers={'Authorization':'Bearer '+TOKEN}).status_code == 200


def test_readiness_accounts_for_registry_availability(scoped,monkeypatch):
    registry,client=scoped
    async def ready(): return {'ready':True,'state':'idle'}
    monkeypatch.setattr(main.dispatcher,'ready',ready)
    registry.unlink()
    assert client.get('/ready').status_code == 503
