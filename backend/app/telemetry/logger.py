"""
ControlPlane.ai — Telemetry Logger.

Asynchronous event logger storing audit events in-memory with
WebSocket broadcast support for the live telemetry dashboard.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("controlplane.telemetry")


@dataclass
class AuditEvent:
    """A single telemetry / audit event."""
    audit_id: str
    timestamp: str
    use_case: str
    user_role: str
    action: str                    # ALLOW | MUTATED_REDACTED | BLOCKED | HUMAN_ESCALATION
    prompt_preview: str            # First 100 chars of prompt
    response_preview: str          # First 100 chars of response
    checks_executed: list[dict] = field(default_factory=list)
    latency_base_ms: float = 0.0
    latency_protected_ms: float = 0.0
    latency_overhead_ms: float = 0.0
    flagged: bool = False
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class TelemetryLogger:
    """
    In-memory audit event logger with WebSocket broadcasting.

    Stores all audit events in memory for the dashboard and provides
    real-time WebSocket notifications for live telemetry updates.
    """

    MAX_EVENTS = 5000  # Cap in-memory storage

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._websocket_connections: set = set()
        self._lock = asyncio.Lock() if asyncio.get_event_loop().is_running() else None

    def _ensure_lock(self):
        if self._lock is None:
            try:
                self._lock = asyncio.Lock()
            except RuntimeError:
                pass

    async def log_event(self, event: AuditEvent) -> None:
        """Log an audit event and broadcast to WebSocket subscribers."""
        self._ensure_lock()
        if self._lock:
            async with self._lock:
                self._events.append(event)
                if len(self._events) > self.MAX_EVENTS:
                    self._events = self._events[-self.MAX_EVENTS:]
        else:
            self._events.append(event)
            if len(self._events) > self.MAX_EVENTS:
                self._events = self._events[-self.MAX_EVENTS:]

        # Broadcast to WebSocket subscribers
        await self._broadcast(event)

    def log_event_sync(self, event: AuditEvent) -> None:
        """Synchronous version of log_event for non-async contexts."""
        self._events.append(event)
        if len(self._events) > self.MAX_EVENTS:
            self._events = self._events[-self.MAX_EVENTS:]

    def create_event(
        self,
        use_case: str,
        user_role: str,
        action: str,
        prompt: str,
        response: str,
        checks: list[dict],
        latency_base_ms: float = 0.0,
        latency_protected_ms: float = 0.0,
        flagged: bool = False,
        metadata: Optional[dict] = None,
    ) -> AuditEvent:
        """Create an AuditEvent with auto-generated ID and timestamp."""
        return AuditEvent(
            audit_id=f"aud-{uuid.uuid4().hex[:8]}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            use_case=use_case,
            user_role=user_role,
            action=action,
            prompt_preview=prompt[:100] + ("..." if len(prompt) > 100 else ""),
            response_preview=response[:100] + ("..." if len(response) > 100 else ""),
            checks_executed=checks,
            latency_base_ms=round(latency_base_ms, 2),
            latency_protected_ms=round(latency_protected_ms, 2),
            latency_overhead_ms=round(latency_protected_ms - latency_base_ms, 2),
            flagged=flagged,
            metadata=metadata or {},
        )

    def get_events(
        self,
        limit: int = 100,
        use_case: Optional[str] = None,
        action: Optional[str] = None,
    ) -> list[dict]:
        """Retrieve audit events with optional filtering."""
        events = self._events

        if use_case:
            events = [e for e in events if e.use_case == use_case]
        if action:
            events = [e for e in events if e.action == action]

        # Return most recent first
        return [e.to_dict() for e in reversed(events[-limit:])]

    def get_event_count(self) -> int:
        """Return total number of logged events."""
        return len(self._events)

    def clear(self) -> None:
        """Clear all stored events."""
        self._events.clear()

    # ── WebSocket Management ──

    async def register_websocket(self, ws) -> None:
        """Register a WebSocket connection for live updates."""
        self._websocket_connections.add(ws)
        logger.info("WebSocket registered (total: %d)", len(self._websocket_connections))

    async def unregister_websocket(self, ws) -> None:
        """Unregister a WebSocket connection."""
        self._websocket_connections.discard(ws)
        logger.info("WebSocket unregistered (total: %d)", len(self._websocket_connections))

    async def _broadcast(self, event: AuditEvent) -> None:
        """Broadcast an event to all connected WebSocket clients."""
        if not self._websocket_connections:
            return

        message = json.dumps({"type": "audit_event", "data": event.to_dict()})
        dead_connections = set()

        for ws in self._websocket_connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead_connections.add(ws)

        # Clean up dead connections
        self._websocket_connections -= dead_connections


# ──────────────────────────────────────────────────────────────────────────────
# Global Singleton
# ──────────────────────────────────────────────────────────────────────────────

_logger_instance: Optional[TelemetryLogger] = None


def get_telemetry_logger() -> TelemetryLogger:
    """Get or create the global TelemetryLogger singleton."""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = TelemetryLogger()
    return _logger_instance
