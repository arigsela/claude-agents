# Long-Context Persistent Agent Implementation Plan

**Document Purpose**: Implementation roadmap for converting k8s-monitor from stateless (disk-based cycle history) to long-context persistent agent mode using Claude Agent SDK's extended conversation capabilities.

**Motivation**: This conversion demonstrates the SDK's ability to maintain conversational memory across monitoring cycles, reducing token overhead while improving context continuity for better anomaly detection and trend analysis.

**Status**: Planning Phase (Ready for Implementation)

---

## 1. Architecture Comparison

### Current Architecture (Stateless + Disk History)

```
┌─────────────────────────────────────────────────────────┐
│ Monitoring Cycle N                                      │
├─────────────────────────────────────────────────────────┤
│ 1. Fresh Claude Client Created                          │
│ 2. Load cycle_*.json files from disk (max 5 cycles)    │
│ 3. Inject history as context in system prompt          │
│ 4. Run analysis (K8s data + historical context)        │
│ 5. Save results → cycle_N.json                         │
│ 6. Close client                                        │
│ 7. Wait 60 minutes                                     │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│ Monitoring Cycle N+1 (60+ min later)                    │
├─────────────────────────────────────────────────────────┤
│ 1. Fresh Claude Client Created (context lost)          │
│ 2. Reload cycle_*.json files from disk                 │
│ 3. Repeat analysis with fresh context                  │
└─────────────────────────────────────────────────────────┘

Issues with this approach:
- ❌ Context reset on each cycle (token overhead)
- ❌ Limited history (last 5 cycles or 24 hours)
- ❌ Disk I/O for every cycle
- ✅ Simple, stateless, restart-safe
```

### Proposed Architecture (Long-Context Persistent)

```
┌──────────────────────────────────────────────────────────────┐
│ Startup: Initialize Persistent Session                      │
├──────────────────────────────────────────────────────────────┤
│ 1. Load SessionManager from disk (if exists)               │
│ 2. Recreate Claude SDK client with saved state            │
│ 3. Restore conversation history                           │
│ 4. Send context update to Claude (new cluster state)      │
└──────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ Monitoring Cycle N (Client persistent across cycles)        │
├──────────────────────────────────────────────────────────────┤
│ 1. Use persistent Claude client                             │
│ 2. Send: "New K8s cluster state: [data]"                   │
│ 3. Claude responds with analysis (remembers all history)   │
│ 4. Save conversation state to disk (SessionManager)        │
│ 5. Wait 60 minutes (client stays alive)                    │
└──────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ Monitoring Cycle N+1 (60+ min later)                        │
├──────────────────────────────────────────────────────────────┤
│ 1. Same persistent client (NO context reset!)              │
│ 2. Send: "New K8s cluster state: [data]"                   │
│ 3. Claude has full conversation history → better analysis │
│ 4. Save updated conversation state                        │
│ 5. Optional: Trim old messages if context nearing limit   │
└──────────────────────────────────────────────────────────────┘

Benefits:
- ✅ Full conversation history (not just 5 cycles)
- ✅ Better trend detection (Claude sees full pattern)
- ✅ Fewer tokens (reuses context, no re-explanation)
- ✅ Natural conversation flow (asks clarifying questions)
- ⚠️ Requires session persistence strategy
- ⚠️ Context window management (token limits)
- ⚠️ More complex restart/recovery
```

---

## 2. Implementation Phases

### Phase 1: Session State Management (3-4 hours)

**Objective**: Create session persistence layer that saves/restores Claude SDK client state.

#### Task 1.1: Create SessionManager Class

**File**: `src/sessions/session_manager.py` (NEW)

```python
"""Persistent session management for long-context monitoring."""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Any
import logging

class SessionManager:
    """Manages persistent session state for Claude SDK client."""

    def __init__(self, session_dir: Path = Path("sessions"), max_context_tokens: int = 120000):
        """
        Initialize session manager.

        Args:
            session_dir: Directory to store session files
            max_context_tokens: Maximum context window (for pruning decisions)
        """
        self.session_dir = session_dir
        self.session_dir.mkdir(exist_ok=True)
        self.max_context_tokens = max_context_tokens
        self.logger = logging.getLogger(__name__)

    def save_session(self, session_id: str, conversation_history: list, metadata: dict) -> None:
        """
        Save session state to disk.

        Args:
            session_id: Unique session identifier
            conversation_history: List of messages from SDK client
            metadata: Session metadata (created_at, cycle_count, etc.)
        """
        session_file = self.session_dir / f"{session_id}.json"
        session_data = {
            "session_id": session_id,
            "conversation_history": conversation_history,
            "metadata": metadata,
            "saved_at": datetime.utcnow().isoformat()
        }

        with open(session_file, 'w') as f:
            json.dump(session_data, f, indent=2)
        self.logger.info(f"Session {session_id} saved to {session_file}")

    def load_session(self, session_id: str) -> Optional[dict]:
        """
        Load session state from disk.

        Returns: session_data dict or None if not found
        """
        session_file = self.session_dir / f"{session_id}.json"
        if not session_file.exists():
            return None

        with open(session_file, 'r') as f:
            session_data = json.load(f)
        self.logger.info(f"Session {session_id} loaded from {session_file}")
        return session_data

    def prune_old_messages(self, conversation_history: list, max_tokens: int = None) -> list:
        """
        Prune old messages if context is getting large.

        Strategy: Keep system messages and latest N messages to stay under token limit.

        Returns: Pruned conversation history
        """
        if max_tokens is None:
            max_tokens = self.max_context_tokens

        # Estimate tokens (rough: ~4 chars per token)
        total_chars = sum(len(msg.get("content", "")) for msg in conversation_history)
        estimated_tokens = total_chars // 4

        if estimated_tokens < max_tokens * 0.8:  # Less than 80% of limit
            return conversation_history

        # Keep system message + latest 20 cycles of analysis
        system_msgs = [m for m in conversation_history if m.get("role") == "system"]
        other_msgs = [m for m in conversation_history if m.get("role") != "system"]

        # Keep latest 50 messages (should be ~12-13 cycles at 4 messages/cycle)
        pruned = system_msgs + other_msgs[-50:]

        self.logger.warning(
            f"Pruned conversation: {len(conversation_history)} → {len(pruned)} messages "
            f"(estimated tokens: {estimated_tokens} → {estimated_tokens * len(pruned) // len(conversation_history)})"
        )
        return pruned

    def delete_session(self, session_id: str) -> None:
        """Delete session file."""
        session_file = self.session_dir / f"{session_id}.json"
        if session_file.exists():
            session_file.unlink()
            self.logger.info(f"Session {session_id} deleted")

    def list_sessions(self) -> list[str]:
        """List all available sessions."""
        return [f.stem for f in self.session_dir.glob("*.json")]
```

**Acceptance Criteria**:
- ✅ Save session to JSON file with conversation history + metadata
- ✅ Load session from disk with error handling
- ✅ Prune old messages when context approaches limit (80% threshold)
- ✅ Delete sessions
- ✅ List available sessions

#### Task 1.2: Update Settings for Session Configuration

**File**: `src/config/settings.py` (MODIFICATIONS)

Add session configuration fields:

```python
# Session Configuration (Long-Context Persistent Agent)
enable_long_context: bool = Field(
    default=False,
    description="Enable long-context persistent agent mode (keep client alive across cycles)"
)
session_id: str = Field(
    default="k8s-monitor-default",
    description="Session identifier for persistent conversation"
)
max_context_tokens: int = Field(
    default=120000,
    description="Maximum context window for session (tokens)"
)
context_prune_threshold: float = Field(
    default=0.8,
    description="Prune session history when reaching this % of max context"
)
```

**Acceptance Criteria**:
- ✅ Can enable/disable long-context mode via `ENABLE_LONG_CONTEXT` env var
- ✅ Can set custom session ID
- ✅ Token limits configurable

---

### Phase 2: Persistent Client Refactoring (4-5 hours)

**Objective**: Refactor Monitor to use persistent SDK client across cycles.

#### Task 2.1: Create PersistentMonitor Wrapper

**File**: `src/orchestrator/persistent_monitor.py` (NEW)

```python
"""Wrapper for persistent long-context monitoring mode."""

import asyncio
import logging
from typing import Optional, Any
from src.sessions.session_manager import SessionManager
from src.config import Settings
from anthropic_sdk import Anthropic

class PersistentMonitor:
    """Wraps Monitor with persistent SDK client lifecycle management."""

    def __init__(self, settings: Settings, base_monitor):
        """
        Initialize persistent monitor.

        Args:
            settings: Application settings
            base_monitor: The original Monitor instance
        """
        self.settings = settings
        self.base_monitor = base_monitor
        self.session_manager = SessionManager(
            max_context_tokens=settings.max_context_tokens
        )
        self.logger = logging.getLogger(__name__)
        self.sdk_client: Optional[Anthropic] = None
        self.conversation_history: list = []
        self.cycle_count = 0

    async def initialize_session(self) -> None:
        """Initialize or restore persistent session."""
        # Try to load existing session
        session_data = self.session_manager.load_session(self.settings.session_id)

        if session_data:
            self.logger.info(f"Restoring session {self.settings.session_id}")
            self.conversation_history = session_data.get("conversation_history", [])
            self.cycle_count = session_data.get("metadata", {}).get("cycle_count", 0)
        else:
            self.logger.info(f"Creating new session {self.settings.session_id}")
            self.conversation_history = []
            self.cycle_count = 0

        # Initialize SDK client (kept alive across cycles)
        self.sdk_client = Anthropic(api_key=self.settings.anthropic_api_key)
        self.logger.info("Persistent SDK client initialized")

    async def run_persistent_cycle(self) -> dict[str, Any]:
        """
        Run monitoring cycle with persistent context.

        Returns: Cycle results dict
        """
        if not self.sdk_client:
            await self.initialize_session()

        self.cycle_count += 1
        self.logger.info(f"Running persistent monitoring cycle {self.cycle_count}")

        # Gather new K8s state
        k8s_state = await self.base_monitor._gather_cluster_state()

        # Build user message with new state
        user_message = f"""
        Monitoring Cycle #{self.cycle_count}

        Current Kubernetes Cluster State:
        {k8s_state}

        Please analyze this state in the context of previous cycles.
        Identify any new issues, recurring patterns, or improvements.
        """

        # Add to conversation history
        self.conversation_history.append({
            "role": "user",
            "content": user_message
        })

        # Get analysis from Claude with full history
        response = await self.sdk_client.messages.create(
            model="claude-opus-4-1-20250805",
            max_tokens=4096,
            system=self._build_system_prompt(),
            messages=self.conversation_history
        )

        assistant_message = response.content[0].text

        # Add assistant response to history
        self.conversation_history.append({
            "role": "assistant",
            "content": assistant_message
        })

        # Prune if needed
        self.conversation_history = self.session_manager.prune_old_messages(
            self.conversation_history
        )

        # Save session
        self.session_manager.save_session(
            self.settings.session_id,
            self.conversation_history,
            {"cycle_count": self.cycle_count, "last_analysis": assistant_message}
        )

        return {
            "cycle": self.cycle_count,
            "analysis": assistant_message,
            "status": "success"
        }

    def _build_system_prompt(self) -> str:
        """Build system prompt for persistent context."""
        return """
You are a Kubernetes cluster monitoring agent running continuous cycles of analysis.
Your role is to:
1. Analyze the current cluster state
2. Compare against previous cycles to detect trends
3. Identify new issues, recurring problems, and improvements
4. Track which issues are resolved
5. Provide escalation recommendations

You have full access to conversation history across all previous monitoring cycles.
Use this history to provide intelligent, context-aware analysis.
"""

    async def shutdown(self) -> None:
        """Gracefully shutdown persistent session."""
        if self.sdk_client:
            # Final save
            self.session_manager.save_session(
                self.settings.session_id,
                self.conversation_history,
                {"cycle_count": self.cycle_count}
            )
            self.logger.info("Persistent monitor session saved and shutdown")
```

**Acceptance Criteria**:
- ✅ Load/restore session from disk
- ✅ Keep SDK client alive across multiple cycles
- ✅ Maintain conversation history
- ✅ Prune when context approaches limit
- ✅ Save session state after each cycle

#### Task 2.2: Integrate PersistentMonitor into main.py

**File**: `src/main.py` (MODIFICATIONS)

```python
async def main() -> None:
    """Main entry point."""
    # Load settings
    try:
        settings = Settings()
        settings.validate_all()
    except Exception as e:
        print(f"Configuration error: {e}")
        sys.exit(1)

    # Set up logging
    logger = setup_logging(settings.log_level)
    logger.info("K3s Monitor starting...")

    # Create monitor instance
    monitor = Monitor(settings)

    # Choose execution mode based on settings
    if settings.enable_long_context:
        logger.info("Running in LONG-CONTEXT PERSISTENT MODE")
        persistent_monitor = PersistentMonitor(settings, monitor)
        await persistent_monitor.initialize_session()

        scheduler = Scheduler(interval_minutes=settings.monitoring_interval_minutes)
        scheduler.schedule_job(
            lambda: persistent_monitor.run_persistent_cycle(),
            job_name="k8s_monitoring_persistent"
        )
    else:
        logger.info("Running in STATELESS MODE")
        scheduler = Scheduler(interval_minutes=settings.monitoring_interval_minutes)
        scheduler.schedule_job(
            lambda: run_monitoring_cycle(monitor),
            job_name="k8s_monitoring_stateless"
        )

    try:
        await scheduler.run_forever()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, shutting down")
        if settings.enable_long_context:
            await persistent_monitor.shutdown()
        sys.exit(0)
```

**Acceptance Criteria**:
- ✅ Can toggle between stateless and persistent modes via settings
- ✅ Both modes work with scheduler
- ✅ Graceful shutdown saves session state

---

### Phase 3: Conversation History Management (3-4 hours)

**Objective**: Implement smart message formatting and history navigation.

#### Task 3.1: Create ConversationFormatter Class

**File**: `src/sessions/conversation_formatter.py` (NEW)

```python
"""Formatting utilities for maintaining clean conversation history."""

import logging
from typing import Optional
from datetime import datetime

class ConversationFormatter:
    """Formats K8s data and analysis into clean conversation messages."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def format_cluster_state_message(
        self,
        cycle_num: int,
        k8s_data: dict,
        previous_summary: Optional[str] = None
    ) -> str:
        """
        Format K8s cluster state into conversation message.

        Args:
            cycle_num: Monitoring cycle number
            k8s_data: Raw K8s cluster data
            previous_summary: Previous cycle's summary (for reference)

        Returns: Formatted user message
        """
        return f"""
## Monitoring Cycle #{cycle_num}
**Timestamp**: {datetime.utcnow().isoformat()}

### Current Cluster State
```
Nodes: {k8s_data.get('node_count', 0)}
Pods: {k8s_data.get('pod_count', 0)}
Namespaces: {k8s_data.get('namespace_count', 0)}

Critical Issues: {len(k8s_data.get('critical_issues', []))}
- {self._format_issues(k8s_data.get('critical_issues', []))}

Warnings: {len(k8s_data.get('warnings', []))}
- {self._format_issues(k8s_data.get('warnings', []))}
```

### Analysis Request
Please provide:
1. **New Issues**: Anything not seen before
2. **Recurring Patterns**: Issues from previous cycles
3. **Improvements**: Issues that have been resolved
4. **Risk Assessment**: What needs escalation

{f"### Previous Cycle Summary\n{previous_summary}" if previous_summary else ""}
"""

    def _format_issues(self, issues: list) -> str:
        """Format issue list for readability."""
        if not issues:
            return "None"
        return "\n  - ".join(issues[:5])  # Show first 5

    def format_analysis_summary(self, analysis: str) -> dict:
        """
        Extract structured data from Claude's analysis.

        Returns: Dict with new_issues, recurring, resolved, risk_level
        """
        return {
            "full_analysis": analysis,
            "summary": analysis[:500] + "..." if len(analysis) > 500 else analysis,
            "timestamp": datetime.utcnow().isoformat()
        }
```

**Acceptance Criteria**:
- ✅ Format K8s data into clean, readable messages
- ✅ Include cycle metadata
- ✅ Optional reference to previous cycle
- ✅ Extract structured summaries from Claude analysis

#### Task 3.2: Create CycleMemoryBridge (Optional for Comparison)

**File**: `src/sessions/cycle_memory_bridge.py` (NEW - Optional)

```python
"""
Optional: Run both stateless (cycle reports) and persistent (long-context) modes
in parallel to compare token usage and analysis quality.
"""

class CycleMemoryBridge:
    """
    Bridges cycle history (disk) with persistent agent for comparison.

    Allows running BOTH systems in parallel:
    - Stateless mode: Saves to cycle_*.json
    - Persistent mode: Maintains conversation history

    This is useful for A/B testing both approaches.
    """

    def __init__(self, cycle_history, persistent_monitor):
        self.cycle_history = cycle_history
        self.persistent_monitor = persistent_monitor

    async def run_comparison_cycle(self) -> dict:
        """
        Run both modes and compare results.

        Returns:
            {
                "stateless_analysis": {...},
                "persistent_analysis": {...},
                "token_comparison": {...},
                "quality_comparison": {...}
            }
        """
        # TODO: Implement comparison logic
        pass
```

**Acceptance Criteria**:
- ✅ Optional comparison mode runs both approaches
- ✅ Tracks token usage for both
- ✅ Allows measuring analysis quality differences

---

### Phase 4: Context Window Management (2-3 hours)

**Objective**: Implement smart pruning and context optimization strategies.

#### Task 4.1: Enhance SessionManager with Context Analytics

**File**: `src/sessions/session_manager.py` (MODIFICATIONS)

Add these methods to SessionManager:

```python
def get_session_stats(self, session_id: str) -> dict:
    """Get stats about a session."""
    session_data = self.load_session(session_id)
    if not session_data:
        return {}

    history = session_data.get("conversation_history", [])
    total_chars = sum(len(m.get("content", "")) for m in history)

    return {
        "message_count": len(history),
        "estimated_tokens": total_chars // 4,
        "cycle_count": session_data.get("metadata", {}).get("cycle_count", 0),
        "context_percentage": (total_chars // 4) / self.max_context_tokens * 100
    }

def should_prune(self, conversation_history: list) -> bool:
    """Check if pruning is needed."""
    total_chars = sum(len(m.get("content", "")) for m in conversation_history)
    estimated_tokens = total_chars // 4
    threshold_tokens = self.max_context_tokens * 0.8
    return estimated_tokens > threshold_tokens

def smart_prune(self, conversation_history: list) -> list:
    """
    Smart pruning that preserves semantic importance.

    Strategy:
    1. Always keep system message
    2. Keep recent 10 cycles (last ~30 messages)
    3. Keep any messages with escalation/critical info
    4. Remove old routine health check messages
    """
    system_msgs = [m for m in conversation_history if m.get("role") == "system"]
    other_msgs = [m for m in conversation_history if m.get("role") != "system"]

    # Keep latest 30 messages (roughly 7-8 cycles)
    # Preserve any with critical/escalation keywords
    critical_msgs = [m for m in other_msgs if any(
        keyword in m.get("content", "").lower()
        for keyword in ["critical", "escalation", "failed", "error", "down"]
    )]

    recent_msgs = other_msgs[-30:]
    important_msgs = list(set(critical_msgs + recent_msgs))  # Deduplicate

    return system_msgs + important_msgs[-30:]  # Final limit
```

**Acceptance Criteria**:
- ✅ Get session statistics (message count, tokens, cycle count)
- ✅ Detect when pruning is needed
- ✅ Smart prune preserves critical messages
- ✅ Maintains semantic importance

---

### Phase 5: Error Recovery & Resilience (2-3 hours)

**Objective**: Handle connection drops, corrupted state, and recovery.

#### Task 5.1: Create SessionRecovery Class

**File**: `src/sessions/session_recovery.py` (NEW)

```python
"""Session recovery and error handling for persistent monitoring."""

import logging
from pathlib import Path
from typing import Optional
import json

class SessionRecovery:
    """Handles session recovery from errors and disconnections."""

    def __init__(self, session_dir: Path = Path("sessions")):
        self.session_dir = session_dir
        self.logger = logging.getLogger(__name__)
        self.backup_dir = session_dir / "backups"
        self.backup_dir.mkdir(exist_ok=True)

    def validate_session(self, session_data: dict) -> bool:
        """Validate session data integrity."""
        try:
            required_fields = ["session_id", "conversation_history", "metadata"]
            if not all(field in session_data for field in required_fields):
                return False
            if not isinstance(session_data["conversation_history"], list):
                return False
            return True
        except Exception as e:
            self.logger.error(f"Session validation error: {e}")
            return False

    def backup_session(self, session_id: str, session_data: dict) -> None:
        """Create backup of session before modifications."""
        backup_file = self.backup_dir / f"{session_id}_backup_{int(time.time())}.json"
        with open(backup_file, 'w') as f:
            json.dump(session_data, f)
        self.logger.info(f"Session backup created: {backup_file}")

    def recover_from_backup(self, session_id: str) -> Optional[dict]:
        """Recover from most recent backup."""
        backups = sorted(self.backup_dir.glob(f"{session_id}_backup_*.json"))
        if not backups:
            return None

        backup_file = backups[-1]  # Most recent
        try:
            with open(backup_file, 'r') as f:
                data = json.load(f)
            self.logger.info(f"Session recovered from backup: {backup_file}")
            return data
        except Exception as e:
            self.logger.error(f"Failed to recover from backup: {e}")
            return None

    def reset_session(self, session_id: str) -> None:
        """Reset session to initial state (start fresh)."""
        session_file = self.session_dir / f"{session_id}.json"
        if session_file.exists():
            session_file.unlink()
        self.logger.info(f"Session reset: {session_id}")
```

**Acceptance Criteria**:
- ✅ Validate session data integrity
- ✅ Create backups before modifications
- ✅ Recover from most recent backup
- ✅ Reset session to fresh state

#### Task 5.2: Add Error Handling to PersistentMonitor

**File**: `src/orchestrator/persistent_monitor.py` (MODIFICATIONS)

Wrap cycle execution with recovery:

```python
async def run_persistent_cycle(self) -> dict[str, Any]:
    """Run cycle with error recovery."""
    if not self.sdk_client:
        await self.initialize_session()

    try:
        # ... existing cycle code ...
        return results
    except Exception as e:
        self.logger.error(f"Cycle error: {e}")

        # Try to recover
        if self.recovery_manager.can_recover():
            self.logger.info("Attempting session recovery...")
            recovered_data = self.recovery_manager.recover_from_backup(self.settings.session_id)
            if recovered_data:
                self.conversation_history = recovered_data["conversation_history"]
                self.logger.info("Session recovered from backup")
            else:
                self.logger.warning("Recovery failed, resetting session")
                self.recovery_manager.reset_session(self.settings.session_id)
                self.conversation_history = []

        return {"status": "error", "message": str(e)}
```

**Acceptance Criteria**:
- ✅ Catch errors during cycle execution
- ✅ Attempt recovery from backup
- ✅ Reset if recovery fails
- ✅ Return error status without crashing

---

### Phase 6: Testing & Validation (4-5 hours)

**Objective**: Comprehensive testing of persistent mode and comparison with stateless.

#### Task 6.1: Unit Tests for Session Management

**File**: `test_persistent_mode.py` (NEW)

```python
"""Tests for persistent long-context monitoring mode."""

import pytest
import asyncio
from pathlib import Path
from src.sessions.session_manager import SessionManager
from src.sessions.conversation_formatter import ConversationFormatter
from src.config import Settings

@pytest.fixture
def session_manager(tmp_path):
    return SessionManager(session_dir=tmp_path)

@pytest.fixture
def settings():
    settings = Settings()
    settings.enable_long_context = True
    settings.session_id = "test-session"
    return settings

def test_save_and_load_session(session_manager):
    """Test saving and loading session state."""
    conversation_history = [
        {"role": "system", "content": "You are a K8s monitor"},
        {"role": "user", "content": "Cycle 1: 10 pods, all healthy"},
        {"role": "assistant", "content": "Cluster is healthy"},
    ]
    metadata = {"cycle_count": 1}

    session_manager.save_session("test", conversation_history, metadata)
    loaded = session_manager.load_session("test")

    assert loaded is not None
    assert len(loaded["conversation_history"]) == 3
    assert loaded["metadata"]["cycle_count"] == 1

def test_prune_old_messages(session_manager):
    """Test message pruning when context is large."""
    # Create large history
    conversation = [{"role": "system", "content": "System" * 1000}]
    conversation.extend([
        {"role": "user", "content": f"Cycle {i}: status update" * 100}
        for i in range(50)
    ])

    pruned = session_manager.prune_old_messages(conversation, max_tokens=1000)

    # Should keep system message + recent messages only
    assert conversation[0] in pruned  # System message kept
    assert len(pruned) < len(conversation)  # Actually pruned

def test_conversation_formatter():
    """Test K8s data formatting."""
    formatter = ConversationFormatter()

    k8s_data = {
        "node_count": 5,
        "pod_count": 42,
        "namespace_count": 8,
        "critical_issues": ["CrashLoopBackOff in prod"],
        "warnings": ["High CPU usage"]
    }

    message = formatter.format_cluster_state_message(1, k8s_data)

    assert "Cycle #1" in message
    assert "5" in message  # node count
    assert "CrashLoopBackOff" in message

@pytest.mark.asyncio
async def test_persistent_monitor_lifecycle(settings):
    """Test persistent monitor initialization and shutdown."""
    # This would test the full lifecycle
    # TODO: Implement once PersistentMonitor class is ready
    pass

@pytest.mark.asyncio
async def test_context_window_pruning(session_manager):
    """Test that conversation is pruned when approaching token limit."""
    # Create 100 message history
    conversation = [
        {"role": "user" if i % 2 == 0 else "assistant",
         "content": f"Message {i}: " + "x" * 500}
        for i in range(100)
    ]

    pruned = session_manager.prune_old_messages(conversation, max_tokens=5000)

    # Should be significantly smaller
    assert len(pruned) < 50
    assert conversation[0] in pruned  # Keep early important messages
```

**Acceptance Criteria**:
- ✅ Session save/load works
- ✅ Pruning reduces history correctly
- ✅ Formatting produces valid messages
- ✅ All tests pass

#### Task 6.2: Integration Test: Stateless vs Persistent Comparison

**File**: `test_mode_comparison.py` (NEW)

```python
"""
Integration test comparing stateless vs persistent modes.

Runs the same cluster analysis in both modes and compares:
- Token usage
- Analysis quality
- Trend detection accuracy
- Processing time
"""

@pytest.mark.asyncio
async def test_modes_comparison(settings, mock_k8s_data):
    """Compare stateless vs persistent mode outputs."""

    # Mode 1: Stateless (cycle history)
    monitor = Monitor(settings)
    stateless_results = []
    for cycle in range(5):
        result = await monitor.run_monitoring_cycle()
        stateless_results.append(result)

    # Mode 2: Persistent (long-context)
    settings.enable_long_context = True
    persistent_monitor = PersistentMonitor(settings, monitor)
    await persistent_monitor.initialize_session()
    persistent_results = []
    for cycle in range(5):
        result = await persistent_monitor.run_persistent_cycle()
        persistent_results.append(result)

    # Compare metrics
    metrics = {
        "stateless": analyze_results(stateless_results),
        "persistent": analyze_results(persistent_results),
    }

    # Assertions
    assert metrics["persistent"]["total_tokens"] < metrics["stateless"]["total_tokens"]
    assert metrics["persistent"]["trend_accuracy"] >= metrics["stateless"]["trend_accuracy"]

def analyze_results(results):
    """Extract metrics from results."""
    return {
        "total_tokens": sum(r.get("tokens_used", 0) for r in results),
        "trend_accuracy": measure_trend_detection(results),
        "avg_latency": sum(r.get("latency", 0) for r in results) / len(results),
    }
```

**Acceptance Criteria**:
- ✅ Can run both modes side-by-side
- ✅ Persistent mode uses fewer tokens
- ✅ Both modes detect trends correctly
- ✅ Comparison metrics documented

#### Task 6.3: Long-Context Behavior Test

**File**: `test_long_context_behavior.py` (NEW)

```python
"""
Test that long-context mode actually uses conversation history.

Verifies that Claude remembers previous findings and makes
better trend analysis with full history.
"""

@pytest.mark.asyncio
async def test_long_context_remembers_issues():
    """Test that long-context mode remembers issues across cycles."""

    persistent_monitor = PersistentMonitor(settings, monitor)
    await persistent_monitor.initialize_session()

    # Cycle 1: Pod crashes in app-1
    result1 = await persistent_monitor.run_persistent_cycle()
    assert "CrashLoopBackOff" in result1["analysis"]

    # Cycle 2: Same pod still crashing (should recognize as recurring)
    result2 = await persistent_monitor.run_persistent_cycle()
    assert "recurring" in result2["analysis"].lower() or "still" in result2["analysis"]

    # Cycle 3: Pod is fixed
    result3 = await persistent_monitor.run_persistent_cycle()
    assert "resolved" in result3["analysis"].lower() or "fixed" in result3["analysis"]

@pytest.mark.asyncio
async def test_context_grows_across_cycles():
    """Test that conversation history grows as expected."""

    persistent_monitor = PersistentMonitor(settings, monitor)
    await persistent_monitor.initialize_session()

    msg_counts = []
    for i in range(5):
        await persistent_monitor.run_persistent_cycle()
        msg_counts.append(len(persistent_monitor.conversation_history))

    # Should grow (each cycle adds at least 2 messages: user + assistant)
    for i in range(1, len(msg_counts)):
        assert msg_counts[i] >= msg_counts[i-1]
```

**Acceptance Criteria**:
- ✅ Claude correctly identifies recurring issues
- ✅ Claude detects resolved issues
- ✅ Conversation history grows correctly
- ✅ Pruning works without losing important context

---

## 3. Configuration Changes

### Environment Variables

Add to `.env.example`:

```bash
# Long-Context Persistent Agent Mode (NEW)
# Set to true to use persistent conversation mode instead of stateless
ENABLE_LONG_CONTEXT=false

# Session configuration
SESSION_ID=k8s-monitor-default
MAX_CONTEXT_TOKENS=120000
CONTEXT_PRUNE_THRESHOLD=0.8

# Note: Set ENABLE_LONG_CONTEXT=true to demonstrate SDK's long-context capabilities
# This keeps the Claude client alive across monitoring cycles, maintaining full
# conversation history for better trend detection and more efficient token usage.
```

### Directory Structure

```
k8s-monitor/
├── src/
│   ├── sessions/                      # NEW: Session management
│   │   ├── __init__.py
│   │   ├── session_manager.py        # Core session persistence
│   │   ├── conversation_formatter.py # Message formatting
│   │   ├── session_recovery.py       # Error recovery
│   │   └── cycle_memory_bridge.py    # Optional: A/B testing both modes
│   │
│   └── orchestrator/
│       ├── monitor.py                # Existing (unchanged)
│       └── persistent_monitor.py     # NEW: Persistent wrapper
│
├── sessions/                         # NEW: Runtime session storage
│   ├── k8s-monitor-default.json     # Main session file
│   └── backups/                      # Session backups
│
├── logs/                             # Existing (unchanged)
└── test_persistent_mode.py           # NEW: Unit tests
```

---

## 4. Migration Strategy

### Step 1: Backward Compatibility (Required)

- ✅ Both modes run side-by-side with `ENABLE_LONG_CONTEXT` flag
- ✅ Default is `false` (stateless) for backward compatibility
- ✅ No breaking changes to existing code

### Step 2: Opt-In Migration Path

```bash
# Option A: Keep stateless (default, no changes)
ENABLE_LONG_CONTEXT=false

# Option B: Try persistent mode
ENABLE_LONG_CONTEXT=true
SESSION_ID=k8s-monitor-v2
```

### Step 3: A/B Testing (Optional)

Enable `CycleMemoryBridge` to run both modes in parallel and compare:
- Token usage
- Analysis quality
- Trend detection accuracy

### Step 4: Full Migration (When Ready)

Once persistent mode proven superior:
1. Change default to `ENABLE_LONG_CONTEXT=true`
2. Archive old cycle history
3. Deploy to production with session recovery enabled

---

## 5. Token Usage Comparison

### Expected Savings with Long-Context

**Stateless Mode (Current)**:
```
Cycle 1: 8K tokens (fresh context, full setup)
Cycle 2: 8K tokens (reload history from disk, re-explain context)
Cycle 3: 8K tokens (same)
Cycle 4: 8K tokens (same)
Cycle 5: 8K tokens (same)
─────────────────────────
Total:   40K tokens (5 cycles, 1 hour @ 60 min interval)
```

**Persistent Mode (Proposed)**:
```
Cycle 1: 8K tokens (fresh context, initialize session)
Cycle 2: 3K tokens (history in context, less re-explanation)
Cycle 3: 3.5K tokens (context growing but already explained)
Cycle 4: 4K tokens (more complex but better understanding)
Cycle 5: 4.5K tokens (full history provides great context)
─────────────────────────
Total:   23K tokens (5 cycles, 1 hour @ 60 min interval)
─────────────────────────
SAVINGS: 42.5% reduction in tokens!
```

**Monthly Cost (at hourly monitoring)**:
- Stateless: ~$1.44 (40K tokens * 24 cycles * 0.25 per M tokens)
- Persistent: ~$0.82 (23K tokens * 24 cycles * 0.25 per M tokens)
- **Monthly Savings: ~$0.62 per cluster**

---

## 6. Rollback Plan

If persistent mode causes issues:

```bash
# Immediate rollback
ENABLE_LONG_CONTEXT=false
# Monitor will switch back to stateless at next cycle

# Clean up session data (optional)
rm -rf sessions/
```

All cycle history JSON files remain, so no data loss.

---

## 7. Success Criteria

### Phase 1 (Session Management)
- [⬜] SessionManager saves/loads with conversational format
- [⬜] Settings support toggle via env var
- [⬜] Can prune large contexts without losing critical info

### Phase 2 (Persistent Client)
- [⬜] PersistentMonitor maintains client across cycles
- [⬜] Both modes work with scheduler
- [⬜] Graceful shutdown saves state

### Phase 3 (Conversation History)
- [⬜] Messages formatted cleanly for long context
- [⬜] Claude can reference previous cycles naturally
- [⬜] Optional comparison mode implemented

### Phase 4 (Context Management)
- [⬜] SessionManager detects when pruning needed
- [⬜] Smart prune preserves critical messages
- [⬜] Context analytics available

### Phase 5 (Resilience)
- [⬜] Session recovery from backups works
- [⬜] Corrupted sessions detected and reset
- [⬜] Error handling integrated into persistent cycle

### Phase 6 (Testing)
- [⬜] All unit tests pass
- [⬜] Integration test proves persistent mode uses less tokens
- [⬜] Long-context behavior tests verify Claude remembers issues
- [⬜] Comparison metrics show persistent mode advantages

### Overall Success
- ✅ Can toggle between modes with one env var
- ✅ Persistent mode uses 40%+ fewer tokens
- ✅ Claude makes better decisions with full history
- ✅ Demonstrates SDK's long-context capabilities as POC
- ✅ Backward compatible (default is stateless)

---

## 8. Implementation Timeline

| Phase | Tasks | Est. Time | Status |
|-------|-------|-----------|--------|
| 1 | Session Management | 3-4h | Not Started |
| 2 | Persistent Client | 4-5h | Not Started |
| 3 | Conversation History | 3-4h | Not Started |
| 4 | Context Management | 2-3h | Not Started |
| 5 | Error Recovery | 2-3h | Not Started |
| 6 | Testing & Validation | 4-5h | Not Started |
| **Total** | **6 phases** | **18-24h** | **Planning** |

---

## 9. Questions for User

1. **Model Choice**: Should persistent mode use Sonnet-4.5 or continue with Haiku for cost?
2. **Context Limit**: Is 120K tokens appropriate, or should it be smaller/larger?
3. **Prune Strategy**: Is smart-prune (keep critical messages) better than simple time-based?
4. **Session Persistence**: Should sessions survive pod restarts (K8s deployment)?
5. **Metrics**: Which metrics matter most - token savings, accuracy, or latency?

---

## 10. References

- [Claude Agent SDK Docs](https://docs.claude.com/en/api/agent-sdk/python)
- [Anthropic Messages API](https://docs.anthropic.com/en/api/messages)
- [Managing Conversation Context](https://docs.anthropic.com/en/docs/build-a-bot/manage-conversation-history)
- [Token Counting](https://docs.anthropic.com/en/docs/resources/tokens)
