import argparse
import asyncio

from fastmcp import Client
from fastmcp.client.auth.bearer import BearerAuth


TEST_TOKEN = "test-bot-token-not-a-real-secret"


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    args = parser.parse_args()
    url = f"http://{args.host}:8091/mcp"

    failed = False
    try:
        async with Client(
            url,
            auth=BearerAuth("wrong-token"),
            timeout=5,
        ):
            pass
    except Exception:
        failed = True
    assert failed, "invalid MCP token unexpectedly authenticated"
    print("MCP wrong token rejected")
    async with Client(
        url,
        auth=BearerAuth(TEST_TOKEN),
        timeout=30,
    ) as client:
        result = await client.call_tool(
            "embed_text",
            {"input": "block3 end to end"},
            timeout=30,
        )
        assert not result.is_error, result
        structured = result.structured_content
        assert structured is not None
        assert structured["data"][0]["embedding"] == [0.1, 0.2]
        print("MCP -> Gateway -> Dispatcher -> embeddings PASS")


if __name__ == "__main__":
    asyncio.run(main())
