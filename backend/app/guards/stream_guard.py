"""
ControlPlane.ai — Stream Guard (Sliding-Window Token Interceptor).

Intercepts streaming LLM output in real-time using a 12-token sliding window.
Detects unauthorized commercial commitments (refunds, vouchers, discount codes)
and severs the SSE stream, replacing with a compliant fallback message.

Designed for the Customer Chatbot pipeline where sub-80ms latency is required.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

logger = logging.getLogger("controlplane.guards.stream")

# ──────────────────────────────────────────────────────────────────────────────
# Unauthorized Commitment Patterns
# ──────────────────────────────────────────────────────────────────────────────

UNAUTHORIZED_COMMITMENT_TERMS: list[str] = [
    r"\bhere(?:'s|\s+is)\s+your\s+(?:special\s+)?(?:promotional\s+)?(?:voucher|code|discount|credit)",
    r"\b(?:issue|issued|grant|granting|provide)\s+(?:a\s+)?(?:full\s+)?(?:cash\s+)?refund\s+of\s+\$?\d+",
    r"\b(?:issue|issued|grant|granting)\s+(?:a\s+)?(?:free\s+)?voucher\s+code",
    r"\bfree\s+voucher\s+code\b",
    r"\bSKY[A-Z0-9]*\d+[A-Z0-9]*\b",
    r"\bcode:\s*[A-Z0-9]*\d+[A-Z0-9]*\b",
    r"\bcomplimentary\s+(?:first-class\s+)?(?:ticket|upgrade\s+voucher)",
    r"\bwaive[d]?\s+(?:all\s+)?(?:baggage\s+fees|the\s+rebooking\s+fee|your\s+fee)",
    r"\bwaiving\s+the\s+fee\b",
    r"\bcredit\s+(?:your\s+account|a\s+\$\d+)\b",
    r"\b\$?\d+\s+reimbursement\s+credited\b",
    r"\bon\s+the\s+house\b",
    r"\bdiscount\s+code\s+[A-Z0-9]*\d+[A-Z0-9]*\b",
    r"\bpromotional\s+code:\s*[A-Z0-9]*\d+[A-Z0-9]*\b",
]

# Compile into regex for fast matching
_COMMITMENT_REGEX = re.compile(
    "|".join(UNAUTHORIZED_COMMITMENT_TERMS),
    re.IGNORECASE,
)

# Default fallback message when stream is severed
DEFAULT_FALLBACK_MESSAGE = (
    "I cannot authorize promotional discounts or compensation directly. "
    "I have forwarded your request to a customer care representative "
    "who can assist you further."
)

STREAM_SEVERED_MARKER = "[STREAM_SEVERED]"


@dataclass
class StreamGuardResult:
    """Result from stream guard evaluation."""
    severed: bool
    matched_terms: list[str] = field(default_factory=list)
    fallback_message: str = ""
    tokens_processed: int = 0
    check_name: str = "stream_commitment_guard"
    latency_ms: float = 0.0
    details: str = ""

    def to_dict(self) -> dict:
        return {
            "check": self.check_name,
            "status": "SEVERED" if self.severed else "PASSED",
            "severed": self.severed,
            "matched_terms": self.matched_terms,
            "tokens_processed": self.tokens_processed,
            "latency_ms": round(self.latency_ms, 2),
            "details": self.details,
        }


class StreamGuard:
    """
    Sliding-window streaming token interceptor.

    Buffers incoming tokens into a 12-token window and checks for
    unauthorized commitment n-grams. If detected, the stream is
    severed and replaced with a compliant fallback.
    """

    WINDOW_SIZE = 12

    def __init__(
        self,
        enabled: bool = True,
        fallback_message: str = DEFAULT_FALLBACK_MESSAGE,
        supervisor_auth_hash: Optional[str] = None,
    ) -> None:
        self.enabled = enabled
        self.fallback_message = fallback_message
        self.supervisor_auth_hash = supervisor_auth_hash

    def evaluate_text(
        self,
        text: str,
        supervisor_auth: Optional[str] = None,
    ) -> StreamGuardResult:
        """
        Evaluate a complete text for unauthorized commitments.

        Used for non-streaming responses or post-generation validation.

        Args:
            text:            The full generated text to evaluate.
            supervisor_auth: Optional supervisor authorization hash.

        Returns:
            StreamGuardResult with severance decision.
        """
        t0 = time.perf_counter()

        if not self.enabled:
            return StreamGuardResult(
                severed=False,
                details="Stream guard disabled",
                latency_ms=(time.perf_counter() - t0) * 1000,
            )

        # Check for supervisor authorization
        if supervisor_auth and supervisor_auth == self.supervisor_auth_hash:
            return StreamGuardResult(
                severed=False,
                details="Supervisor authorization verified — commitments allowed",
                latency_ms=(time.perf_counter() - t0) * 1000,
            )

        # Scan for unauthorized commitments
        matches = _COMMITMENT_REGEX.findall(text)
        tokens = text.split()

        latency = (time.perf_counter() - t0) * 1000

        if matches:
            unique_matches = list(set(m.lower() for m in matches))
            return StreamGuardResult(
                severed=True,
                matched_terms=unique_matches,
                fallback_message=self.fallback_message,
                tokens_processed=len(tokens),
                latency_ms=latency,
                details=(
                    f"Unauthorized commitment detected: {unique_matches}. "
                    f"Stream severed and replaced with compliant fallback."
                ),
            )

        return StreamGuardResult(
            severed=False,
            tokens_processed=len(tokens),
            latency_ms=latency,
            details=f"No unauthorized commitments detected in {len(tokens)} tokens",
        )

    async def intercept_stream(
        self,
        token_stream: AsyncIterator[str],
        supervisor_auth: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """
        Wrap an async token stream with commitment detection.

        Buffers tokens into a sliding window and checks for unauthorized
        commitment n-grams. If detected, yields the severed marker and
        fallback message, then stops iteration.

        Args:
            token_stream:    Async iterator of token strings.
            supervisor_auth: Optional supervisor authorization hash.

        Yields:
            Token strings, or fallback message if stream is severed.
        """
        if not self.enabled:
            async for token in token_stream:
                yield token
            return

        # Check supervisor auth
        if supervisor_auth and supervisor_auth == self.supervisor_auth_hash:
            async for token in token_stream:
                yield token
            return

        window: list[str] = []
        buffer: list[str] = []
        severed = False

        async for token in token_stream:
            # Add token to window
            words = token.split()
            for word in words:
                window.append(word)
                buffer.append(word)

                # Check when window is full
                if len(window) >= self.WINDOW_SIZE:
                    window_text = " ".join(window)
                    matches = _COMMITMENT_REGEX.findall(window_text)

                    if matches:
                        # Sever the stream
                        severed = True
                        logger.warning(
                            "Stream severed — unauthorized commitment: %s",
                            matches,
                        )
                        yield f"\n\n{STREAM_SEVERED_MARKER}\n\n"
                        yield self.fallback_message
                        return

                    # Slide the window: release oldest tokens
                    while len(window) > self.WINDOW_SIZE:
                        released = window.pop(0)
                        yield released + " "

            if not severed and not words:
                # Pass through whitespace/empty tokens
                yield token

        # Flush remaining buffer
        if not severed:
            remaining = " ".join(window)
            # Final check on remaining buffer
            matches = _COMMITMENT_REGEX.findall(remaining)
            if matches:
                yield f"\n\n{STREAM_SEVERED_MARKER}\n\n"
                yield self.fallback_message
            else:
                yield remaining

    def update_fallback(self, message: str) -> None:
        """Update the fallback message at runtime."""
        self.fallback_message = message

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the stream guard."""
        self.enabled = enabled
        logger.info("Stream guard %s", "enabled" if enabled else "disabled")


# ──────────────────────────────────────────────────────────────────────────────
# Module-level convenience singleton
# ──────────────────────────────────────────────────────────────────────────────

_guard: Optional[StreamGuard] = None


def get_stream_guard() -> StreamGuard:
    """Get or create the global StreamGuard singleton."""
    global _guard
    if _guard is None:
        _guard = StreamGuard()
    return _guard
