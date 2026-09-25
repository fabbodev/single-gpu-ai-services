from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parents[1]


def test_registry_directory_mounts_are_atomically_reloadable_and_isolated():
    for component in ('gateway','mcp'):
        svc=yaml.safe_load((ROOT/component/'compose.yaml').read_text())['services'][component]
        mounts=[v for v in svc['volumes'] if isinstance(v,dict) and v.get('target')=='/run/ai-clients']
        assert len(mounts)==1, 'registry must use its own directory bind mount'
        assert mounts[0]['read_only'] is True and mounts[0]['bind']['create_host_path'] is False
        assert '/clients}' in mounts[0]['source']
        assert svc['environment']['AI_CLIENT_TOKENS_FILE']=='/run/ai-clients/client-tokens.json'
        assert 'client_access' in (ROOT/component/'Dockerfile').read_text()
        if component=='mcp': assert 'dispatcher-token' not in str(svc['volumes']) and 'docker.sock' not in str(svc)
