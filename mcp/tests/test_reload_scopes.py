from hashlib import sha256
import json
import os
from types import SimpleNamespace
import pytest
import server
from auth import HashedTokenVerifier

TOKEN='mcp-hot-reload-test-token'


def publish(path,scopes=None,enabled=True):
    data={'version':1,'clients':[{'client_id':'mcp-test','token_sha256':sha256(TOKEN.encode()).hexdigest(),'scopes':scopes or ['gateway','mcp','embeddings'],'enabled':enabled}]}
    tmp=path.with_suffix('.next'); tmp.write_text(json.dumps(data)); os.replace(tmp,path)


@pytest.mark.asyncio
async def test_mcp_verifier_sees_atomic_revocation(tmp_path):
    p=tmp_path/'registry.json'; publish(p)
    verifier=HashedTokenVerifier.from_file(p,required_scopes=['mcp'])
    assert await verifier.verify_token(TOKEN)
    publish(p,enabled=False)
    assert await verifier.verify_token(TOKEN) is None


def test_established_session_rechecks_current_capability(tmp_path,monkeypatch):
    p=tmp_path/'registry.json'; publish(p)
    verifier=HashedTokenVerifier.from_file(p,required_scopes=['mcp'])
    monkeypatch.setattr(server,'token_verifier',verifier)
    monkeypatch.setattr(server,'get_access_token',lambda:SimpleNamespace(token=TOKEN,client_id='mcp-test',scopes=['gateway','mcp','embeddings']))
    assert server.current_client('embeddings').client_id=='mcp-test'
    publish(p,scopes=['gateway','mcp','llm'])
    with pytest.raises(PermissionError): server.current_client('embeddings')


def test_established_session_rechecks_revocation_and_corruption(tmp_path,monkeypatch):
    p=tmp_path/'registry.json'; publish(p)
    monkeypatch.setattr(server,'token_verifier',HashedTokenVerifier.from_file(p,required_scopes=['mcp']))
    monkeypatch.setattr(server,'get_access_token',lambda:SimpleNamespace(token=TOKEN,client_id='mcp-test',scopes=['gateway','mcp','embeddings']))
    publish(p,enabled=False)
    with pytest.raises(PermissionError): server.current_client('embeddings')
    p.write_text('{broken')
    with pytest.raises(PermissionError): server.current_client('embeddings')
