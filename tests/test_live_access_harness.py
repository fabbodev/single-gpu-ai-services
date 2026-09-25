import importlib.util
from pathlib import Path


def load():
    path=Path(__file__).resolve().parent/'integration'/'phase5c_live_access.py'
    spec=importlib.util.spec_from_file_location('live_access_harness',path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


class MCPError(Exception):
    code=-32603


def test_sdk_generic_http_error_requires_an_independent_wire_denial():
    fn=load().denial_matches
    error=MCPError('Server returned an error response')
    assert fn(error,401)
    assert not fn(error,500)
    assert not fn(error,200)


def test_network_failures_do_not_count_as_revocation():
    fn=load().denial_matches
    assert not fn(TimeoutError('timed out'),401)
    assert not fn(RuntimeError('Server returned an error response'),401)
