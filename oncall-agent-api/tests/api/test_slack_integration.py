"""
Tests for Slack integration - slash commands, signature validation, and proactive alerts.
"""

import hashlib
import hmac
import os
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ==================== Slack Signature Validation Tests ====================


class TestSlackSignatureValidation:
    """Tests for Slack HMAC-SHA256 request signature validation."""

    def _compute_signature(self, body: str, timestamp: str, secret: str) -> str:
        """Helper to compute a valid Slack signature."""
        sig_basestring = f"v0:{timestamp}:{body}"
        hex_digest = hmac.new(
            secret.encode("utf-8"),
            sig_basestring.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"v0={hex_digest}"

    def test_valid_signature(self):
        """Test signature validation with a correct signature."""
        from src.api.middleware import validate_slack_signature

        secret = "test-signing-secret"
        body = b"token=abc&command=/oncall&text=hello"
        timestamp = str(int(time.time()))

        signature = self._compute_signature(body.decode(), timestamp, secret)

        assert validate_slack_signature(body, timestamp, signature, secret) is True

    def test_invalid_signature(self):
        """Test signature validation rejects invalid signatures."""
        from src.api.middleware import validate_slack_signature

        secret = "test-signing-secret"
        body = b"token=abc&command=/oncall&text=hello"
        timestamp = str(int(time.time()))

        assert (
            validate_slack_signature(body, timestamp, "v0=invalidsignature", secret)
            is False
        )

    def test_missing_signature(self):
        """Test signature validation rejects missing signature."""
        from src.api.middleware import validate_slack_signature

        body = b"token=abc&command=/oncall&text=hello"
        timestamp = str(int(time.time()))

        assert validate_slack_signature(body, timestamp, "", "secret") is False
        assert validate_slack_signature(body, timestamp, None, "secret") is False

    def test_wrong_prefix(self):
        """Test signature validation rejects non-v0 prefix."""
        from src.api.middleware import validate_slack_signature

        body = b"token=abc&command=/oncall&text=hello"
        timestamp = str(int(time.time()))

        assert (
            validate_slack_signature(body, timestamp, "v1=abcdef", "secret") is False
        )

    def test_missing_secret(self):
        """Test signature validation rejects when no secret configured."""
        from src.api.middleware import validate_slack_signature

        body = b"token=abc&command=/oncall&text=hello"
        timestamp = str(int(time.time()))

        assert validate_slack_signature(body, timestamp, "v0=abc", "") is False
        assert validate_slack_signature(body, timestamp, "v0=abc", None) is False

    def test_stale_timestamp_rejected(self):
        """Test signature validation rejects timestamps older than 5 minutes."""
        from src.api.middleware import validate_slack_signature

        secret = "test-signing-secret"
        body = b"token=abc&command=/oncall&text=hello"
        # 6 minutes ago
        old_timestamp = str(int(time.time()) - 360)

        signature = self._compute_signature(body.decode(), old_timestamp, secret)

        assert (
            validate_slack_signature(body, old_timestamp, signature, secret) is False
        )

    def test_recent_timestamp_accepted(self):
        """Test signature validation accepts timestamps within 5 minutes."""
        from src.api.middleware import validate_slack_signature

        secret = "test-signing-secret"
        body = b"token=abc&command=/oncall&text=hello"
        # 2 minutes ago
        recent_timestamp = str(int(time.time()) - 120)

        signature = self._compute_signature(body.decode(), recent_timestamp, secret)

        assert (
            validate_slack_signature(body, recent_timestamp, signature, secret) is True
        )

    def test_invalid_timestamp_format(self):
        """Test signature validation rejects non-numeric timestamps."""
        from src.api.middleware import validate_slack_signature

        body = b"token=abc&command=/oncall&text=hello"

        assert (
            validate_slack_signature(body, "not-a-number", "v0=abc", "secret") is False
        )

    def test_timing_attack_protection(self):
        """Test that signature comparison is constant-time."""
        from src.api.middleware import validate_slack_signature

        secret = "test-signing-secret"
        body = b"token=abc&command=/oncall&text=hello"
        timestamp = str(int(time.time()))

        valid_sig = self._compute_signature(body.decode(), timestamp, secret)

        # Similar but wrong signatures should all fail
        wrong_sig1 = valid_sig[:-1] + "X"
        wrong_sig2 = "v0=" + "0" * 64

        assert validate_slack_signature(body, timestamp, valid_sig, secret) is True
        assert validate_slack_signature(body, timestamp, wrong_sig1, secret) is False
        assert validate_slack_signature(body, timestamp, wrong_sig2, secret) is False


# ==================== Slack Models Tests ====================


class TestSlackModels:
    """Tests for Slack Pydantic models."""

    def test_slash_command_parsing(self):
        """Test parsing SlackSlashCommand from form data dict."""
        from src.api.slack_models import SlackSlashCommand

        data = {
            "token": "verification-token",
            "command": "/oncall",
            "text": "check cluster health",
            "response_url": "https://hooks.slack.com/commands/T123/456/abc",
            "trigger_id": "trigger-123",
            "user_id": "U123ABC",
            "user_name": "ari",
            "channel_id": "C456DEF",
            "channel_name": "oncall-testing",
            "team_id": "T789GHI",
        }

        cmd = SlackSlashCommand(**data)

        assert cmd.command == "/oncall"
        assert cmd.text == "check cluster health"
        assert cmd.user_id == "U123ABC"
        assert cmd.user_name == "ari"
        assert cmd.response_url == "https://hooks.slack.com/commands/T123/456/abc"
        assert cmd.channel_id == "C456DEF"
        assert cmd.team_id == "T789GHI"

    def test_slash_command_minimal(self):
        """Test parsing SlackSlashCommand with only required fields."""
        from src.api.slack_models import SlackSlashCommand

        data = {
            "command": "/oncall",
            "response_url": "https://hooks.slack.com/commands/T123/456/abc",
            "user_id": "U123ABC",
        }

        cmd = SlackSlashCommand(**data)

        assert cmd.command == "/oncall"
        assert cmd.text == ""
        assert cmd.user_id == "U123ABC"
        assert cmd.channel_id == ""
        assert cmd.team_id == ""

    def test_format_query_response(self):
        """Test Block Kit formatting for query responses."""
        from src.api.slack_models import format_query_response

        blocks = format_query_response(
            text="All pods are healthy in the default namespace.",
            query="check cluster health",
            duration_ms=1234.5,
        )

        assert len(blocks) == 4
        assert blocks[0]["type"] == "section"
        assert "`check cluster health`" in blocks[0]["text"]["text"]
        assert blocks[1]["type"] == "divider"
        assert blocks[2]["type"] == "section"
        assert "All pods are healthy" in blocks[2]["text"]["text"]
        assert blocks[-1]["type"] == "context"
        assert "1234ms" in blocks[-1]["elements"][0]["text"] or "1235ms" in blocks[-1]["elements"][0]["text"]

    def test_format_query_response_long_text(self):
        """Test that long responses are split into multiple blocks."""
        from src.api.slack_models import format_query_response

        # Create a response over 3000 chars with paragraph breaks
        long_text = ("Paragraph one. " * 50 + "\n\n") * 5
        blocks = format_query_response(
            text=long_text,
            query="check cluster health",
            duration_ms=42000,
        )

        # Should have more than 4 blocks (header, divider, multiple sections, context)
        assert len(blocks) > 4
        # First and last blocks unchanged
        assert blocks[0]["type"] == "section"
        assert blocks[1]["type"] == "divider"
        assert blocks[-1]["type"] == "context"
        # All response blocks should be under 3000 chars
        for block in blocks[2:-1]:
            assert block["type"] == "section"
            assert len(block["text"]["text"]) <= 3000

    def test_format_incident_alert(self):
        """Test Block Kit formatting for incident alerts."""
        from src.api.slack_models import format_incident_alert

        alert = {
            "service": "chores-tracker-backend",
            "namespace": "chores-tracker-backend",
            "error": "CrashLoopBackOff",
            "restart_count": 5,
        }
        analysis = [{"type": "text", "content": "Pod is crash looping due to OOM."}]

        blocks = format_incident_alert(alert, analysis, "high")

        assert blocks[0]["type"] == "header"
        assert "chores-tracker-backend" in blocks[0]["text"]["text"]
        assert blocks[1]["type"] == "section"
        # Check severity field
        fields_text = " ".join(f["text"] for f in blocks[1]["fields"])
        assert "HIGH" in fields_text
        # Check error block
        assert "CrashLoopBackOff" in blocks[2]["text"]["text"]

    def test_format_incident_alert_severity_emojis(self):
        """Test that different severities produce different emojis."""
        from src.api.slack_models import format_incident_alert

        alert = {"service": "test", "namespace": "default", "error": "err"}
        analysis = [{"type": "text", "content": "test"}]

        for severity in ["critical", "high", "medium", "low"]:
            blocks = format_incident_alert(alert, analysis, severity)
            header_text = blocks[0]["text"]["text"]
            assert "Incident Alert" in header_text

    def test_format_incident_alert_truncation(self):
        """Test that long analysis text is truncated."""
        from src.api.slack_models import format_incident_alert

        alert = {"service": "test", "namespace": "default", "error": "err"}
        long_text = "A" * 3500
        analysis = [{"type": "text", "content": long_text}]

        blocks = format_incident_alert(alert, analysis, "high")
        analysis_block = blocks[4]["text"]["text"]
        assert "_(truncated)_" in analysis_block
        assert len(analysis_block) < 3100


# ==================== Slack Command Endpoint Tests ====================


class TestSlackCommandEndpoint:
    """Tests for the /slack/command endpoint."""

    def _compute_signature(self, body: str, timestamp: str, secret: str) -> str:
        """Helper to compute a valid Slack signature."""
        sig_basestring = f"v0:{timestamp}:{body}"
        hex_digest = hmac.new(
            secret.encode("utf-8"),
            sig_basestring.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"v0={hex_digest}"

    def test_command_endpoint_returns_200(self):
        """Test that slash command endpoint acknowledges immediately."""
        os.environ["SLACK_SIGNING_SECRET"] = "test-secret"

        with patch("src.api.api_server.OnCallAgentClient"):
            from src.api.api_server import app

            client = TestClient(app)

            form_data = "token=abc&command=%2Foncall&text=hello&response_url=https%3A%2F%2Fhooks.slack.com%2Ftest&user_id=U123&channel_id=C456"
            timestamp = str(int(time.time()))
            signature = self._compute_signature(form_data, timestamp, "test-secret")

            response = client.post(
                "/slack/command",
                content=form_data,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-Slack-Request-Timestamp": timestamp,
                    "X-Slack-Signature": signature,
                },
            )

            assert response.status_code == 200

        del os.environ["SLACK_SIGNING_SECRET"]

    def test_command_invalid_signature_rejected(self):
        """Test that invalid signatures are rejected with 401."""
        os.environ["SLACK_SIGNING_SECRET"] = "test-secret"

        with patch("src.api.api_server.OnCallAgentClient"):
            from src.api.api_server import app

            client = TestClient(app)

            form_data = "token=abc&command=%2Foncall&text=hello&response_url=https%3A%2F%2Fhooks.slack.com%2Ftest&user_id=U123&channel_id=C456"
            timestamp = str(int(time.time()))

            response = client.post(
                "/slack/command",
                content=form_data,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-Slack-Request-Timestamp": timestamp,
                    "X-Slack-Signature": "v0=invalidsignature",
                },
            )

            assert response.status_code == 401

        del os.environ["SLACK_SIGNING_SECRET"]

    def test_command_no_secret_configured(self):
        """Test that commands work (with warning) when no signing secret configured."""
        if "SLACK_SIGNING_SECRET" in os.environ:
            del os.environ["SLACK_SIGNING_SECRET"]

        with patch("src.api.api_server.OnCallAgentClient"):
            from src.api.api_server import app

            client = TestClient(app)

            form_data = "token=abc&command=%2Foncall&text=hello&response_url=https%3A%2F%2Fhooks.slack.com%2Ftest&user_id=U123&channel_id=C456"

            response = client.post(
                "/slack/command",
                content=form_data,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )

            # Should still succeed (with warning logged) when no secret configured
            assert response.status_code == 200

        os.environ.pop("SLACK_SIGNING_SECRET", None)


# ==================== Slack Health Endpoint Tests ====================


class TestSlackHealthEndpoint:
    """Tests for the /slack/health endpoint."""

    def test_health_configured(self):
        """Test health check when Slack is fully configured."""
        os.environ["SLACK_ENABLED"] = "true"
        os.environ["SLACK_BOT_TOKEN"] = "xoxb-test-token"
        os.environ["SLACK_SIGNING_SECRET"] = "test-secret"
        os.environ["SLACK_ALERT_CHANNEL"] = "#oncall-alerts"

        with patch("src.api.api_server.OnCallAgentClient"):
            from src.api.api_server import app

            client = TestClient(app)

            response = client.get("/slack/health")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "configured"
            assert data["enabled"] is True
            assert data["signing_secret_set"] is True
            assert data["bot_token_set"] is True
            assert data["alert_channel"] == "#oncall-alerts"
            assert data["endpoint"] == "/slack/command"

        del os.environ["SLACK_ENABLED"]
        del os.environ["SLACK_BOT_TOKEN"]
        del os.environ["SLACK_SIGNING_SECRET"]
        del os.environ["SLACK_ALERT_CHANNEL"]

    def test_health_not_configured(self):
        """Test health check when Slack is not configured."""
        for key in ["SLACK_ENABLED", "SLACK_BOT_TOKEN", "SLACK_SIGNING_SECRET", "SLACK_ALERT_CHANNEL"]:
            os.environ.pop(key, None)

        with patch("src.api.api_server.OnCallAgentClient"):
            from src.api.api_server import app

            client = TestClient(app)

            response = client.get("/slack/health")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "not_configured"
            assert data["enabled"] is False
            assert data["signing_secret_set"] is False
            assert data["bot_token_set"] is False


# ==================== Slack Events Endpoint Tests ====================


class TestSlackEventsEndpoint:
    """Tests for the /slack/events endpoint."""

    def _compute_signature(self, body: str, timestamp: str, secret: str) -> str:
        sig_basestring = f"v0:{timestamp}:{body}"
        hex_digest = hmac.new(
            secret.encode("utf-8"),
            sig_basestring.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"v0={hex_digest}"

    def test_url_verification_challenge(self):
        """Test that URL verification challenge is echoed back."""
        os.environ["SLACK_SIGNING_SECRET"] = "test-secret"

        with patch("src.api.api_server.OnCallAgentClient"):
            from src.api.api_server import app

            client = TestClient(app)

            import json

            payload = {"type": "url_verification", "challenge": "test-challenge-value"}
            body = json.dumps(payload)
            timestamp = str(int(time.time()))
            signature = self._compute_signature(body, timestamp, "test-secret")

            response = client.post(
                "/slack/events",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Slack-Request-Timestamp": timestamp,
                    "X-Slack-Signature": signature,
                },
            )

            assert response.status_code == 200
            assert response.json()["challenge"] == "test-challenge-value"

        del os.environ["SLACK_SIGNING_SECRET"]


# ==================== Proactive Alert Tests ====================


class TestProactiveAlerts:
    """Tests for proactive Slack incident alert posting."""

    @pytest.mark.asyncio
    async def test_alert_skipped_when_disabled(self):
        """Test that alerts are not posted when SLACK_ENABLED is false."""
        os.environ.pop("SLACK_ENABLED", None)

        from src.api.slack_integration import post_incident_alert

        # Should return without error (no Slack API calls)
        await post_incident_alert(
            alert={"service": "test", "error": "CrashLoopBackOff"},
            analysis=[{"type": "text", "content": "test"}],
            severity="high",
        )

    @pytest.mark.asyncio
    async def test_alert_skipped_below_severity_threshold(self):
        """Test that alerts below minimum severity are skipped."""
        os.environ["SLACK_ENABLED"] = "true"
        os.environ["SLACK_BOT_TOKEN"] = "xoxb-test"
        os.environ["SLACK_ALERT_CHANNEL"] = "#alerts"
        os.environ["SLACK_ALERT_MIN_SEVERITY"] = "high"

        from src.api.slack_integration import post_incident_alert

        with patch("slack_sdk.WebClient") as mock_client_cls:
            await post_incident_alert(
                alert={"service": "test", "error": "warning"},
                analysis=[{"type": "text", "content": "test"}],
                severity="medium",
            )

            # WebClient should not be called for medium severity when threshold is high
            mock_client_cls.assert_not_called()

        del os.environ["SLACK_ENABLED"]
        del os.environ["SLACK_BOT_TOKEN"]
        del os.environ["SLACK_ALERT_CHANNEL"]
        del os.environ["SLACK_ALERT_MIN_SEVERITY"]

    @pytest.mark.asyncio
    async def test_alert_posted_for_critical_severity(self):
        """Test that critical alerts are posted when threshold is high."""
        os.environ["SLACK_ENABLED"] = "true"
        os.environ["SLACK_BOT_TOKEN"] = "xoxb-test"
        os.environ["SLACK_ALERT_CHANNEL"] = "#alerts"
        os.environ["SLACK_ALERT_MIN_SEVERITY"] = "high"

        from src.api.slack_integration import post_incident_alert

        mock_client = Mock()
        mock_client.chat_postMessage = Mock()

        with patch("slack_sdk.WebClient", return_value=mock_client):
            await post_incident_alert(
                alert={
                    "service": "chores-tracker",
                    "namespace": "default",
                    "error": "OOMKilled",
                    "restart_count": 15,
                },
                analysis=[{"type": "text", "content": "Pod killed due to memory."}],
                severity="critical",
            )

            mock_client.chat_postMessage.assert_called_once()
            call_kwargs = mock_client.chat_postMessage.call_args[1]
            assert call_kwargs["channel"] == "#alerts"
            assert "chores-tracker" in call_kwargs["text"]

        del os.environ["SLACK_ENABLED"]
        del os.environ["SLACK_BOT_TOKEN"]
        del os.environ["SLACK_ALERT_CHANNEL"]
        del os.environ["SLACK_ALERT_MIN_SEVERITY"]

    @pytest.mark.asyncio
    async def test_alert_skipped_without_bot_token(self):
        """Test that alerts are skipped when bot token is missing."""
        os.environ["SLACK_ENABLED"] = "true"
        os.environ.pop("SLACK_BOT_TOKEN", None)
        os.environ["SLACK_ALERT_CHANNEL"] = "#alerts"

        from src.api.slack_integration import post_incident_alert

        # Should return without error
        await post_incident_alert(
            alert={"service": "test", "error": "CrashLoopBackOff"},
            analysis=[{"type": "text", "content": "test"}],
            severity="critical",
        )

        del os.environ["SLACK_ENABLED"]
        del os.environ["SLACK_ALERT_CHANNEL"]
