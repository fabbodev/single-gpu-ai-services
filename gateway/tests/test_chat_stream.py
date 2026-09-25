import json
import httpx
import pytest
from fastapi.testclient import TestClient
from app import main

HEADERS = {'Authorization':'Bearer test-bot-token-not-a-real-secret'}


@pytest.fixture
def llm(monkeypatch):
    released=[]
    async def acquire(service): return 'test-lease'
    async def release(lease): released.append(lease)
    class Backend:
        body={'id':'chatcmpl-test','object':'chat.completion','created':100,'model':'qwen3-8b',
              'choices':[{'index':0,'message':{'role':'assistant','content':'hello'},'finish_reason':'stop'}],
              'usage':{'prompt_tokens':2,'completion_tokens':1,'total_tokens':3}}
        async def post(self,url,json):
            assert json['stream'] is False
            return httpx.Response(200,json=self.body,request=httpx.Request('POST',url))
    backend=Backend()
    monkeypatch.setattr(main,'_acquire_lease',acquire); monkeypatch.setattr(main,'_release_lease',release)
    monkeypatch.setattr(main,'http_client',backend)
    return TestClient(main.app),backend,released


def request(client, **flags):
    return client.post('/v1/chat/completions',headers=HEADERS,json={'messages':[{'role':'user','content':'hi'}],**flags})


def test_stream_true_is_valid_buffered_sse_and_releases_gpu(llm):
    client,_,released=llm; r=request(client,stream=True,stream_options={'include_usage':True})
    assert r.status_code==200 and r.headers['content-type'].startswith('text/event-stream')
    assert r.headers['x-ai-stream-mode']=='buffered'
    events=[x[6:] for x in r.text.splitlines() if x.startswith('data: ')]
    assert events[-1]=='[DONE]'
    chunks=[json.loads(x) for x in events[:-1]]
    assert all(c['id']=='chatcmpl-test' and c['object']=='chat.completion.chunk' for c in chunks)
    assert ''.join(c['choices'][0]['delta'].get('content','') for c in chunks if c['choices'])=='hello'
    assert chunks[-1]['usage']['total_tokens']==3
    assert released==['test-lease']


def test_streaming_tool_call_preserves_id_name_arguments_and_finish(llm):
    client,backend,_=llm
    call={'id':'call-test','type':'function','function':{'name':'embed_text','arguments':'{"input":"hi"}'}}
    backend.body['choices']=[{'index':0,'message':{'role':'assistant','content':None,'tool_calls':[call]},'finish_reason':'tool_calls'}]
    r=request(client,stream=True)
    assert r.headers['content-type'].startswith('text/event-stream')
    chunks=[json.loads(x[6:]) for x in r.text.splitlines() if x.startswith('data: {')]
    tool=next(c['choices'][0]['delta']['tool_calls'][0] for c in chunks if c['choices'] and 'tool_calls' in c['choices'][0]['delta'])
    assert tool==dict(call,index=0)
    assert chunks[-1]['choices'][0]['finish_reason']=='tool_calls'


@pytest.mark.parametrize('flags',[{'stream':'yes'},{'stream':True,'stream_options':'invalid'},{'stream':True,'stream_options':{'include_usage':'yes'}},{'n':2}])
def test_unsupported_stream_flags_are_explicit_errors(llm,flags):
    client,_,released=llm
    r=request(client,**flags)
    assert r.status_code==400 and not released


def test_nonstream_contract_is_preserved(llm):
    client,backend,released=llm; r=request(client,stream=False)
    assert r.status_code==200 and r.json()==backend.body and released==['test-lease']


@pytest.mark.parametrize('value',[[], '', False, 0])
def test_falsey_nonobject_stream_options_are_rejected(llm,value):
    client,_,released=llm
    response=request(client,stream=True,stream_options=value)
    assert response.status_code==400 and not released


def test_sse_encoding_failure_still_releases_lease(llm):
    client,backend,released=llm
    backend.body['choices'][0]['message']={'tool_calls':[{'function':{}}]}
    response=request(client,stream=True)
    assert response.status_code==502 and released==['test-lease']
