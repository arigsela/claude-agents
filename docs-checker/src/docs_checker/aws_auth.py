"""SigV4 request signing for httpx, so the MCP client can call AgentCore Gateway.

The Gateway's inbound authorizer is ``AWS_IAM``: every MCP request is signed with the
runtime's execution role (botocore's default credential chain, which inside an
AgentCore microVM is the role's credentials). Only ``host``, ``content-type`` and the
MCP headers are signed, never hop-by-hop headers a proxy may rewrite, and the
signature covers the exact body bytes httpx sends.
"""

from __future__ import annotations

from collections.abc import Generator

import httpx

SIGNED_HEADERS = (
    "content-type",
    "accept",
    "mcp-session-id",
    "mcp-protocol-version",
    "a2a-version",
    "x-amzn-bedrock-agentcore-runtime-session-id",
)


class SigV4Auth(httpx.Auth):
    requires_request_body = True

    def __init__(self, *, service: str, region: str, profile: str | None = None):
        """``profile`` names an AWS CLI profile (the operator's client); None is the
        default chain (the runtime's role inside AgentCore)."""
        import botocore.session

        self._service = service
        self._region = region
        self._session = botocore.session.Session(profile=profile)

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response]:
        from botocore.auth import SigV4Auth as BotocoreSigV4
        from botocore.awsrequest import AWSRequest

        credentials = self._session.get_credentials()
        if credentials is None:
            raise RuntimeError("no AWS credentials to sign the Gateway request with")
        headers = {"host": request.url.netloc.decode()}
        headers.update({k: request.headers[k] for k in SIGNED_HEADERS if k in request.headers})
        aws_request = AWSRequest(
            method=request.method, url=str(request.url), data=request.content, headers=headers
        )
        BotocoreSigV4(credentials.get_frozen_credentials(), self._service, self._region).add_auth(
            aws_request
        )
        for name in ("Authorization", "X-Amz-Date", "X-Amz-Security-Token"):
            if name in aws_request.headers:
                request.headers[name] = aws_request.headers[name]
        yield request
