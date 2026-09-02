"""
ControlPlane.ai — RBAC Guard (Role-Based Access Control for Retrieval).

Implements clearance-level filtering for the Internal Copilot pipeline.
Maps user roles to integer clearance levels and applies hard metadata
filters on document retrieval to mathematically exclude documents above
the user's clearance.

Clearance Levels:
    junior_associate = 1
    hr_manager       = 3
    c_level          = 5
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from ..config import ROLE_CLEARANCE, UserRole

logger = logging.getLogger("controlplane.guards.rbac")


@dataclass
class RBACGuardResult:
    """Result from RBAC guard evaluation."""
    passed: bool
    user_role: str
    clearance_level: int
    documents_accessible: int
    documents_filtered: int
    retrieved_chunks: list[dict] = field(default_factory=list)
    check_name: str = "rbac_retrieval_filter"
    latency_ms: float = 0.0
    details: str = ""

    def to_dict(self) -> dict:
        return {
            "check": self.check_name,
            "status": "PASSED" if self.passed else "FILTERED",
            "user_role": self.user_role,
            "clearance_level": self.clearance_level,
            "documents_accessible": self.documents_accessible,
            "documents_filtered": self.documents_filtered,
            "latency_ms": round(self.latency_ms, 2),
            "details": self.details,
        }


class RBACGuard:
    """
    Role-based access control guard for document retrieval.

    Queries the enterprise document store with clearance-level metadata
    filtering, ensuring users can only access documents at or below
    their clearance level.
    """

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._doc_store = None

    def _get_doc_store(self):
        """Lazy-load the document store to avoid circular imports."""
        if self._doc_store is None:
            from ..simulators.mock_hr_docs import get_doc_store
            self._doc_store = get_doc_store()
        return self._doc_store

    @staticmethod
    def get_clearance(user_role: str) -> int:
        """
        Map a user role string to its integer clearance level.

        Args:
            user_role: The user's role identifier.

        Returns:
            Integer clearance level (0-5).
        """
        return ROLE_CLEARANCE.get(user_role, 0)

    def retrieve_with_rbac(
        self,
        query: str,
        user_role: str,
        n_results: int = 3,
        department_filter: Optional[str] = None,
    ) -> RBACGuardResult:
        """
        Retrieve documents with RBAC clearance filtering.

        Args:
            query:             The search query text.
            user_role:         The requesting user's role.
            n_results:         Maximum results to return.
            department_filter: Optional department filter.

        Returns:
            RBACGuardResult with filtered documents and access metadata.
        """
        t0 = time.perf_counter()

        clearance = self.get_clearance(user_role)
        doc_store = self._get_doc_store()

        if not self.enabled:
            # When disabled, return all documents without filtering
            results = doc_store.query(
                query_text=query,
                user_clearance=999,  # No filter
                n_results=n_results,
                department_filter=department_filter,
            )
            access_info = doc_store.get_accessible_count(999)
            latency = (time.perf_counter() - t0) * 1000
            return RBACGuardResult(
                passed=True,
                user_role=user_role,
                clearance_level=clearance,
                documents_accessible=access_info["total_documents"],
                documents_filtered=0,
                retrieved_chunks=[
                    {
                        "doc_id": doc_id,
                        "content": content,
                        "metadata": meta,
                    }
                    for doc_id, content, meta in zip(
                        results["ids"],
                        results["documents"],
                        results["metadatas"],
                    )
                ],
                latency_ms=latency,
                details="RBAC guard disabled — all documents accessible",
            )

        # Perform RBAC-filtered retrieval
        results = doc_store.query(
            query_text=query,
            user_clearance=clearance,
            n_results=n_results,
            department_filter=department_filter,
        )

        access_info = doc_store.get_accessible_count(clearance)
        latency = (time.perf_counter() - t0) * 1000

        retrieved_chunks = [
            {
                "doc_id": doc_id,
                "content": content,
                "metadata": meta,
            }
            for doc_id, content, meta in zip(
                results["ids"],
                results["documents"],
                results["metadatas"],
            )
        ]

        filtered_count = access_info["filtered_out"]
        details = (
            f"Clearance level {clearance} ({user_role}): "
            f"{access_info['accessible']}/{access_info['total_documents']} "
            f"documents accessible, {filtered_count} filtered out. "
            f"Retrieved {len(retrieved_chunks)} relevant chunks."
        )

        if filtered_count > 0:
            details += f" Filtered out {filtered_count} documents exceeding clearance level {clearance}."

        return RBACGuardResult(
            passed=True,
            user_role=user_role,
            clearance_level=clearance,
            documents_accessible=access_info["accessible"],
            documents_filtered=filtered_count,
            retrieved_chunks=retrieved_chunks,
            latency_ms=latency,
            details=details,
        )

    def check_access(self, user_role: str, required_clearance: int) -> bool:
        """
        Simple boolean check: does the user have sufficient clearance?

        Args:
            user_role:          The user's role.
            required_clearance: Minimum clearance level needed.

        Returns:
            True if user's clearance >= required_clearance.
        """
        return self.get_clearance(user_role) >= required_clearance

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable RBAC filtering."""
        self.enabled = enabled
        logger.info("RBAC guard %s", "enabled" if enabled else "disabled")


# ──────────────────────────────────────────────────────────────────────────────
# Module-level convenience singleton
# ──────────────────────────────────────────────────────────────────────────────

_guard: Optional[RBACGuard] = None


def get_rbac_guard() -> RBACGuard:
    """Get or create the global RBACGuard singleton."""
    global _guard
    if _guard is None:
        _guard = RBACGuard()
    return _guard
