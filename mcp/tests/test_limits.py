import base64

import pytest

from server import decode_base64_payload


def test_base64_payload_rejects_decoded_file_over_limit():
    payload = base64.b64encode(b"12345").decode()

    with pytest.raises(ValueError, match="too large"):
        decode_base64_payload(payload, max_bytes=4)
