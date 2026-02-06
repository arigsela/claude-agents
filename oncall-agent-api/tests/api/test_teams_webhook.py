"""
Tests for Microsoft Teams Outgoing Webhook integration
"""

import pytest
import hmac
import hashlib
import base64
import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ==================== HMAC Validation Tests ====================

class TestHMACValidation:
    """Tests for HMAC-SHA256 signature validation"""

    def test_hmac_validation_valid_signature(self):
        """Test HMAC validation with valid signature"""
        from src.api.middleware import validate_teams_hmac

        # Create test secret and body
        secret = base64.b64encode(b"test-secret-key").decode()
        body = b'{"type": "message", "text": "Hello"}'

        # Compute valid signature
        secret_bytes = base64.b64decode(secret)
        signature = base64.b64encode(
            hmac.new(secret_bytes, body, hashlib.sha256).digest()
        ).decode()
        auth_header = f"HMAC {signature}"

        # Should validate successfully
        assert validate_teams_hmac(body, auth_header, secret) is True

    def test_hmac_validation_invalid_signature(self):
        """Test HMAC validation with invalid signature"""
        from src.api.middleware import validate_teams_hmac

        secret = base64.b64encode(b"test-secret-key").decode()
        body = b'{"type": "message", "text": "Hello"}'
        auth_header = "HMAC invalid-signature-here"

        # Should fail validation
        assert validate_teams_hmac(body, auth_header, secret) is False

    def test_hmac_validation_missing_header(self):
        """Test HMAC validation with missing Authorization header"""
        from src.api.middleware import validate_teams_hmac

        secret = base64.b64encode(b"test-secret-key").decode()
        body = b'{"type": "message", "text": "Hello"}'

        # Empty or None header
        assert validate_teams_hmac(body, "", secret) is False
        assert validate_teams_hmac(body, None, secret) is False

    def test_hmac_validation_wrong_prefix(self):
        """Test HMAC validation with wrong Authorization prefix"""
        from src.api.middleware import validate_teams_hmac

        secret = base64.b64encode(b"test-secret-key").decode()
        body = b'{"type": "message", "text": "Hello"}'

        # Wrong prefix (not "HMAC ")
        assert validate_teams_hmac(body, "Bearer token123", secret) is False
        assert validate_teams_hmac(body, "Basic user:pass", secret) is False

    def test_hmac_validation_no_secret(self):
        """Test HMAC validation with missing secret"""
        from src.api.middleware import validate_teams_hmac

        body = b'{"type": "message", "text": "Hello"}'
        auth_header = "HMAC some-signature"

        # Empty or None secret
        assert validate_teams_hmac(body, auth_header, "") is False
        assert validate_teams_hmac(body, auth_header, None) is False

    def test_hmac_validation_invalid_base64_secret(self):
        """Test HMAC validation with invalid base64 secret"""
        from src.api.middleware import validate_teams_hmac

        body = b'{"type": "message", "text": "Hello"}'
        auth_header = "HMAC some-signature"
        invalid_secret = "not-valid-base64!!!"

        # Should fail gracefully
        assert validate_teams_hmac(body, auth_header, invalid_secret) is False

    def test_hmac_timing_attack_protection(self):
        """Test that HMAC comparison is constant-time"""
        from src.api.middleware import validate_teams_hmac

        secret = base64.b64encode(b"test-secret-key").decode()
        body = b'{"type": "message", "text": "Hello"}'

        # Create valid signature
        secret_bytes = base64.b64decode(secret)
        valid_sig = base64.b64encode(
            hmac.new(secret_bytes, body, hashlib.sha256).digest()
        ).decode()

        # Create similar but wrong signatures
        wrong_sig1 = valid_sig[:-1] + "X"  # Last char wrong
        wrong_sig2 = "X" + valid_sig[1:]  # First char wrong

        # Both should fail (we can't easily test timing, but we test behavior)
        assert validate_teams_hmac(body, f"HMAC {valid_sig}", secret) is True
        assert validate_teams_hmac(body, f"HMAC {wrong_sig1}", secret) is False
        assert validate_teams_hmac(body, f"HMAC {wrong_sig2}", secret) is False


# ==================== Teams Models Tests ====================

class TestTeamsModels:
    """Tests for Teams Pydantic models"""

    def test_teams_activity_parsing(self):
        """Test parsing TeamsActivity from JSON"""
        from src.api.teams_models import TeamsActivity

        payload = {
            "type": "message",
            "id": "1234567890",
            "timestamp": "2025-01-13T10:00:00.000Z",
            "text": "<at>OnCall</at> check artemis-auth health",
            "from": {
                "id": "user123",
                "name": "John Doe",
                "aadObjectId": "aad-object-id"
            },
            "conversation": {
                "id": "19:abc123@thread.tacv2",
                "conversationType": "channel",
                "tenantId": "tenant-123",
                "name": "Dev Team"
            },
            "channelId": "msteams",
            "serviceUrl": "https://smba.trafficmanager.net/us/"
        }

        activity = TeamsActivity(**payload)

        assert activity.type == "message"
        assert activity.id == "1234567890"
        assert activity.text == "<at>OnCall</at> check artemis-auth health"
        assert activity.from_.id == "user123"
        assert activity.from_.name == "John Doe"
        assert activity.conversation.id == "19:abc123@thread.tacv2"
        assert activity.conversation.tenantId == "tenant-123"

    def test_teams_activity_minimal(self):
        """Test parsing TeamsActivity with minimal required fields"""
        from src.api.teams_models import TeamsActivity

        payload = {
            "type": "message",
            "id": "123",
            "timestamp": "2025-01-13T10:00:00.000Z",
            "text": "Hello",
            "from": {"id": "user1", "name": "User"},
            "conversation": {"id": "conv1"},
            "serviceUrl": "https://example.com/"
        }

        activity = TeamsActivity(**payload)

        assert activity.type == "message"
        assert activity.channelId == "msteams"  # Default value
        assert activity.conversation.tenantId is None  # Optional

    def test_adaptive_card_response(self):
        """Test creating Adaptive Card response"""
        from src.api.teams_models import create_adaptive_card_response

        response = create_adaptive_card_response("Test message")

        assert response.type == "message"
        assert len(response.attachments) == 1
        assert response.attachments[0]["contentType"] == "application/vnd.microsoft.card.adaptive"

        card = response.attachments[0]["content"]
        assert card["type"] == "AdaptiveCard"
        assert card["version"] == "1.4"
        assert len(card["body"]) == 1
        assert card["body"][0]["type"] == "TextBlock"
        assert card["body"][0]["text"] == "Test message"
        assert card["body"][0]["wrap"] is True

    def test_adaptive_card_with_title(self):
        """Test creating Adaptive Card with title"""
        from src.api.teams_models import create_adaptive_card_response

        response = create_adaptive_card_response(
            text="Body text",
            title="Card Title"
        )

        card = response.attachments[0]["content"]
        assert len(card["body"]) == 2
        assert card["body"][0]["text"] == "Card Title"
        assert card["body"][0]["weight"] == "Bolder"
        assert card["body"][1]["text"] == "Body text"

    def test_adaptive_card_themes(self):
        """Test Adaptive Card theme styles"""
        from src.api.teams_models import create_adaptive_card_response

        # Test each theme
        themes = ["default", "good", "attention", "warning"]

        for theme in themes:
            response = create_adaptive_card_response("Test", theme=theme)
            card = response.attachments[0]["content"]

            if theme == "default":
                assert "style" not in card
            else:
                assert card.get("style") == theme

    def test_error_card(self):
        """Test creating error Adaptive Card"""
        from src.api.teams_models import create_error_card

        response = create_error_card("Something went wrong", "Timeout")

        card = response.attachments[0]["content"]
        assert "**Timeout**: Something went wrong" in card["body"][0]["text"]
        assert card.get("style") == "warning"

    def test_welcome_card(self):
        """Test creating welcome Adaptive Card"""
        from src.api.teams_models import create_welcome_card

        response = create_welcome_card()

        card = response.attachments[0]["content"]
        assert len(card["body"]) == 2  # Title + body
        assert "OnCall Agent" in card["body"][0]["text"]
        assert "Kubernetes" in card["body"][1]["text"]


# ==================== Teams Webhook Router Tests ====================

class TestTeamsWebhookRouter:
    """Tests for Teams webhook endpoint"""

    @pytest.fixture
    def mock_agent(self):
        """Mock OnCallAgentClient"""
        mock = Mock()
        mock.query = AsyncMock(return_value={"response": "Test response from agent"})
        return mock

    @pytest.fixture
    def mock_session_manager(self):
        """Mock SessionManager"""
        from src.api.session_manager import Session

        mock = Mock()
        mock.sessions = {}

        def create_session(user_id, metadata=None):
            session = Mock()
            session.session_id = f"test-session-{user_id}"
            session.user_id = user_id
            session.conversation_history = []
            return session

        mock.create_session = Mock(side_effect=create_session)
        mock.get_session = Mock(return_value=None)
        mock.update_session = Mock()

        return mock

    def compute_hmac_signature(self, body: bytes, secret: str) -> str:
        """Helper to compute HMAC signature for tests"""
        secret_bytes = base64.b64decode(secret)
        signature = base64.b64encode(
            hmac.new(secret_bytes, body, hashlib.sha256).digest()
        ).decode()
        return f"HMAC {signature}"

    def test_webhook_health_endpoint(self):
        """Test /teams/health endpoint"""
        # Set environment variable
        os.environ["TEAMS_WEBHOOK_SECRET"] = base64.b64encode(b"test").decode()

        with patch('src.api.api_server.OnCallAgentClient'):
            from src.api.api_server import app
            client = TestClient(app)

            response = client.get("/teams/health")

            assert response.status_code == 200
            data = response.json()
            assert "status" in data
            assert "webhook_configured" in data
            assert data["endpoint"] == "/teams/webhook"

        # Cleanup
        del os.environ["TEAMS_WEBHOOK_SECRET"]

    def test_webhook_health_not_configured(self):
        """Test /teams/health when secret not configured"""
        # Ensure secret is not set
        if "TEAMS_WEBHOOK_SECRET" in os.environ:
            del os.environ["TEAMS_WEBHOOK_SECRET"]

        with patch('src.api.api_server.OnCallAgentClient'):
            from src.api.api_server import app
            client = TestClient(app)

            response = client.get("/teams/health")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "not_configured"
            assert data["webhook_configured"] is False

    def test_webhook_invalid_hmac(self):
        """Test webhook rejects invalid HMAC signature"""
        os.environ["TEAMS_WEBHOOK_SECRET"] = base64.b64encode(b"test-secret").decode()

        with patch('src.api.api_server.OnCallAgentClient'):
            from src.api.api_server import app
            client = TestClient(app)

            payload = {
                "type": "message",
                "id": "123",
                "timestamp": "2025-01-13T10:00:00.000Z",
                "text": "<at>OnCall</at> hello",
                "from": {"id": "user1", "name": "User"},
                "conversation": {"id": "conv1"},
                "serviceUrl": "https://example.com/"
            }

            response = client.post(
                "/teams/webhook",
                json=payload,
                headers={"Authorization": "HMAC invalid-signature"}
            )

            assert response.status_code == 401
            assert "Invalid HMAC" in response.json()["detail"]

        del os.environ["TEAMS_WEBHOOK_SECRET"]

    def test_webhook_missing_authorization(self):
        """Test webhook rejects missing Authorization header"""
        os.environ["TEAMS_WEBHOOK_SECRET"] = base64.b64encode(b"test-secret").decode()

        with patch('src.api.api_server.OnCallAgentClient'):
            from src.api.api_server import app
            client = TestClient(app)

            payload = {
                "type": "message",
                "id": "123",
                "timestamp": "2025-01-13T10:00:00.000Z",
                "text": "<at>OnCall</at> hello",
                "from": {"id": "user1", "name": "User"},
                "conversation": {"id": "conv1"},
                "serviceUrl": "https://example.com/"
            }

            response = client.post("/teams/webhook", json=payload)

            assert response.status_code == 401

        del os.environ["TEAMS_WEBHOOK_SECRET"]

    def test_webhook_not_configured(self):
        """Test webhook returns 503 when not configured"""
        if "TEAMS_WEBHOOK_SECRET" in os.environ:
            del os.environ["TEAMS_WEBHOOK_SECRET"]

        with patch('src.api.api_server.OnCallAgentClient'):
            from src.api.api_server import app
            client = TestClient(app)

            payload = {
                "type": "message",
                "id": "123",
                "timestamp": "2025-01-13T10:00:00.000Z",
                "text": "hello",
                "from": {"id": "user1", "name": "User"},
                "conversation": {"id": "conv1"},
                "serviceUrl": "https://example.com/"
            }

            response = client.post(
                "/teams/webhook",
                json=payload,
                headers={"Authorization": "HMAC test"}
            )

            assert response.status_code == 503
            assert "not configured" in response.json()["detail"]


# ==================== Mention Stripping Tests ====================

class TestMentionStripping:
    """Tests for @mention stripping from Teams messages"""

    def test_strip_at_mention_simple(self):
        """Test stripping simple @mention"""
        from src.api.teams_webhook import strip_at_mention

        text = "<at>OnCall</at> check health"
        assert strip_at_mention(text) == "check health"

    def test_strip_at_mention_with_extra_spaces(self):
        """Test stripping @mention with extra spaces"""
        from src.api.teams_webhook import strip_at_mention

        text = "<at>OnCall</at>   check health  "
        assert strip_at_mention(text) == "check health"

    def test_strip_at_mention_multiple(self):
        """Test stripping multiple @mentions"""
        from src.api.teams_webhook import strip_at_mention

        text = "<at>OnCall</at> <at>AnotherBot</at> hello"
        assert strip_at_mention(text) == "hello"

    def test_strip_at_mention_empty_result(self):
        """Test stripping @mention leaving empty string"""
        from src.api.teams_webhook import strip_at_mention

        text = "<at>OnCall</at>"
        assert strip_at_mention(text) == ""

    def test_strip_at_mention_no_mention(self):
        """Test string without @mention"""
        from src.api.teams_webhook import strip_at_mention

        text = "just a regular message"
        assert strip_at_mention(text) == "just a regular message"

    def test_strip_at_mention_complex_name(self):
        """Test stripping @mention with complex bot name"""
        from src.api.teams_webhook import strip_at_mention

        text = "<at>OnCall Troubleshooting Agent</at> check pods"
        assert strip_at_mention(text) == "check pods"


# ==================== Integration Tests ====================

class TestTeamsIntegration:
    """Integration tests for Teams webhook flow"""

    def compute_hmac_signature(self, body: bytes, secret: str) -> str:
        """Helper to compute HMAC signature"""
        secret_bytes = base64.b64decode(secret)
        signature = base64.b64encode(
            hmac.new(secret_bytes, body, hashlib.sha256).digest()
        ).decode()
        return f"HMAC {signature}"

    @pytest.mark.skip(reason="Requires full app initialization with mocked agent")
    def test_full_webhook_flow(self):
        """Test complete webhook flow from request to response"""
        # This test requires more complex mocking of the agent
        # and session manager. Keeping as documentation for future implementation.
        pass
