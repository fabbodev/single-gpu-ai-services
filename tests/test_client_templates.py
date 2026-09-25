import json
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1]
EXAMPLES=ROOT/'examples'/'clients'


def test_openclaw_template_matches_actual_server_contract():
    cfg=json.loads((EXAMPLES/'openclaw.json').read_text())
    provider=cfg['models']['providers']['ai-services']
    assert provider['api']=='openai-completions'
    assert provider['apiKey']=='${AI_SERVICES_API_KEY}'
    assert provider['models'][0]['contextWindow']==16384
    assert cfg['agents']['defaults']['model']['fallbacks']==[]
    assert cfg['mcp']['servers']['ai-services']['requestTimeoutMs']==600000


def test_golembot_uses_chat_compatible_engine_with_explicit_opencode_adapter():
    golem=yaml.safe_load((EXAMPLES/'golem.yaml').read_text())
    oc=json.loads((EXAMPLES/'opencode.json').read_text())
    assert golem['engine']=='opencode'
    assert golem['model']==oc['model']=='ai-services/qwen3-8b'
    assert oc['provider']['ai-services']['npm']=='@ai-sdk/openai-compatible'
    assert oc['mcp']['ai-services']['oauth'] is False


def test_hermes_templates_do_not_misstate_context_capacity():
    model=yaml.safe_load((EXAMPLES/'hermes-model.yaml').read_text())
    tools=yaml.safe_load((EXAMPLES/'hermes-mcp.yaml').read_text())
    assert model['model']['context_length']==16384
    assert model['providers']['ai-services']['transport']=='chat_completions'
    assert tools['mcp_servers']['ai-services']['timeout']==600
    assert 'NOT ACCEPTED' in (EXAMPLES/'hermes-model.yaml').read_text()


def test_no_real_deployment_address_in_templates():
    for path in EXAMPLES.iterdir():
        text=path.read_text()
        assert '100.107.' not in text and '/home/fabbo' not in text
