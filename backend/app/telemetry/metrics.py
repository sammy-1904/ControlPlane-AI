"""
ControlPlane.ai — Telemetry Metrics Aggregator.

In-memory metrics computation for the Live Telemetry dashboard:
    - Total Requests
    - Interception Rate (%)
    - Average Overhead (ms)
    - Over-Flagging Rate (%)
    - Violation distribution breakdown
"""

from __future__ import annotations

import logging
from typing import Optional

from .logger import get_telemetry_logger

logger = logging.getLogger("controlplane.telemetry.metrics")


class MetricsAggregator:
    """
    Computes real-time aggregate metrics from the telemetry event log.

    All metrics are computed on-the-fly from the event log rather than
    pre-aggregated, ensuring consistency with the audit trail.
    """

    def __init__(self) -> None:
        self._tel = get_telemetry_logger()

    def compute_stats(self, use_case: Optional[str] = None) -> dict:
        """
        Compute aggregate metrics from all logged events.

        Args:
            use_case: Optional filter to compute metrics for a specific use case.

        Returns:
            Dict with total_requests, interception_rate, avg_overhead_ms,
            over_flagging_rate, and violation_distribution.
        """
        events = self._tel._events

        if use_case:
            events = [e for e in events if e.use_case == use_case]

        total = len(events)
        if total == 0:
            return {
                "total_requests": 0,
                "interception_rate": 0.0,
                "avg_overhead_ms": 0.0,
                "over_flagging_rate": 0.0,
                "violation_distribution": {},
                "action_breakdown": {},
                "use_case_breakdown": {},
                "latency_stats": {
                    "min_overhead_ms": 0.0,
                    "max_overhead_ms": 0.0,
                    "avg_overhead_ms": 0.0,
                    "p50_overhead_ms": 0.0,
                    "p95_overhead_ms": 0.0,
                },
            }

        # ── Core Metrics ──
        intercepted = sum(1 for e in events if e.action in ("BLOCKED", "MUTATED_REDACTED", "HUMAN_ESCALATION"))
        interception_rate = (intercepted / total) * 100 if total > 0 else 0.0

        overheads = [e.latency_overhead_ms for e in events if e.latency_overhead_ms > 0]
        avg_overhead = sum(overheads) / len(overheads) if overheads else 0.0

        # Over-flagging: flagged events that were actually benign
        # (events where action != ALLOW but the test was benign)
        # For now, estimate from events where flagged=True and action=BLOCKED
        # on likely benign traffic
        benign_count = sum(1 for e in events if e.action == "ALLOW")
        false_positive = sum(
            1 for e in events
            if e.flagged and e.action in ("BLOCKED", "MUTATED_REDACTED")
            and any(
                c.get("status") == "TRIGGERED" and c.get("check") == "prompt_injection_guard"
                and c.get("risk_score", 1.0) < 0.85
                for c in e.checks_executed
            )
        )
        total_negative = benign_count + false_positive
        over_flagging = (false_positive / total_negative * 100) if total_negative > 0 else 0.0

        # ── Violation Distribution ──
        violation_counts: dict[str, int] = {
            "Injection": 0,
            "PII Leak": 0,
            "Hallucination": 0,
            "Clinical Override": 0,
            "Stream Severed": 0,
            "Entropy Abstention": 0,
        }
        for event in events:
            for check in event.checks_executed:
                status = check.get("status", "")
                check_name = check.get("check", "")
                if status in ("BLOCKED", "TRIGGERED", "SEVERED"):
                    if "injection" in check_name:
                        violation_counts["Injection"] += 1
                    elif "pii" in check_name or "redaction" in check_name:
                        violation_counts["PII Leak"] += 1
                    elif "grounding" in check_name or "nli" in check_name:
                        violation_counts["Hallucination"] += 1
                    elif "clinical" in check_name:
                        violation_counts["Clinical Override"] += 1
                    elif "stream" in check_name or "commitment" in check_name:
                        violation_counts["Stream Severed"] += 1
                if check_name == "clinical_safety_engine" and status == "HUMAN_ESCALATION_REQUIRED":
                    violation_counts["Entropy Abstention"] += 1

        # ── Action Breakdown ──
        action_counts: dict[str, int] = {}
        for event in events:
            action_counts[event.action] = action_counts.get(event.action, 0) + 1

        # ── Use Case Breakdown ──
        uc_counts: dict[str, int] = {}
        for event in events:
            uc_counts[event.use_case] = uc_counts.get(event.use_case, 0) + 1

        # ── Latency Stats ──
        sorted_overheads = sorted(overheads) if overheads else [0.0]
        latency_stats = {
            "min_overhead_ms": round(sorted_overheads[0], 2),
            "max_overhead_ms": round(sorted_overheads[-1], 2),
            "avg_overhead_ms": round(avg_overhead, 2),
            "p50_overhead_ms": round(sorted_overheads[len(sorted_overheads) // 2], 2),
            "p95_overhead_ms": round(sorted_overheads[int(len(sorted_overheads) * 0.95)], 2),
        }

        return {
            "total_requests": total,
            "interception_rate": round(interception_rate, 2),
            "avg_overhead_ms": round(avg_overhead, 2),
            "over_flagging_rate": round(over_flagging, 2),
            "violation_distribution": violation_counts,
            "action_breakdown": action_counts,
            "use_case_breakdown": uc_counts,
            "latency_stats": latency_stats,
        }

    def compute_latency_breakdown(self) -> list[dict]:
        """
        Compute per-request latency breakdown for the stacked bar chart.

        Returns a list of dicts with base_model_ms and overhead_ms.
        """
        events = self._tel._events[-50:]  # Last 50 for chart
        return [
            {
                "audit_id": e.audit_id,
                "timestamp": e.timestamp,
                "use_case": e.use_case,
                "base_model_ms": round(e.latency_base_ms, 2),
                "overhead_ms": round(e.latency_overhead_ms, 2),
                "total_ms": round(e.latency_protected_ms, 2),
            }
            for e in events
        ]


# ──────────────────────────────────────────────────────────────────────────────
# Global Singleton
# ──────────────────────────────────────────────────────────────────────────────

_aggregator: Optional[MetricsAggregator] = None


def get_metrics_aggregator() -> MetricsAggregator:
    """Get or create the global MetricsAggregator singleton."""
    global _aggregator
    if _aggregator is None:
        _aggregator = MetricsAggregator()
    return _aggregator
