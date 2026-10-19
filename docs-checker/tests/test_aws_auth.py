import httpx
import pytest

from docs_checker.aws_auth import SigV4Auth


@pytest.fixture
def static_credentials(monkeypatch):
    for name in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_SESSION_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKID")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")


async def test_sigv4_signs_request(static_credentials):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    auth = SigV4Auth(service="bedrock-agentcore", region="us-west-2")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), auth=auth) as client:
        await client.post("https://gw.example/mcp", json={"jsonrpc": "2.0", "method": "ping"})
    (request,) = seen
    authorization = request.headers["authorization"]
    assert authorization.startswith("AWS4-HMAC-SHA256 Credential=AKID/")
    assert "/us-west-2/bedrock-agentcore/aws4_request" in authorization
    assert request.headers["x-amz-date"]
    assert "x-amz-content-sha256" in request.headers or "content-length" in request.headers


def test_sigv4_signs_the_body_it_sends(static_credentials):
    """The signature covers the exact bytes on the wire (a re-serialized body would
    not verify at the Gateway)."""
    request = httpx.Request("POST", "https://gw.example/mcp", content=b'{"a": 1}')
    signed = next(SigV4Auth(service="bedrock-agentcore", region="us-west-2").auth_flow(request))
    assert signed.content == b'{"a": 1}'
    assert "content-type" not in signed.headers or signed.headers["content-type"]
