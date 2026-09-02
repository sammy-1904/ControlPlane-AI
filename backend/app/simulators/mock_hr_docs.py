"""
ControlPlane.ai — HR & IT Enterprise Document Store Simulator.

Seeds an in-memory document store with 4 enterprise documents at varying
clearance levels.  Provides a ChromaDB-compatible query interface with
built-in RBAC metadata filtering.

When ChromaDB + sentence-transformers are available, the real vector store
is used.  Otherwise, a lightweight TF-IDF / keyword-overlap fallback
provides identical function signatures and return structures.
"""

from __future__ import annotations

import logging
import math
import os
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("controlplane.simulators.hr_docs")

# ──────────────────────────────────────────────────────────────────────────────
# Document Corpus
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class Document:
    """A single enterprise document with clearance-gated access."""
    doc_id: str
    clearance_level: int          # 1 = general, 3 = manager, 5 = c-level
    department: str               # IT, HR, Exec, Finance, etc.
    title: str
    content: str
    metadata: dict = field(default_factory=dict)


# The four PRD-specified documents plus additional filler for richer demo
ENTERPRISE_DOCUMENTS: list[Document] = [
    Document(
        doc_id="DOC-01",
        clearance_level=1,
        department="IT",
        title="Corporate VPN Access Instructions",
        content=(
            "VPN instructions: Connect via Cisco AnyConnect to "
            "vpn.corp.internal using your SSO credentials. Ensure your "
            "multi-factor authentication (MFA) token is active before "
            "connecting. For macOS users, download AnyConnect from the "
            "internal software portal at software.corp.internal/vpn. "
            "Contact the IT helpdesk at ext. 4400 for connection issues."
        ),
    ),
    Document(
        doc_id="DOC-02",
        clearance_level=1,
        department="HR",
        title="Standard Leave & Holiday Policy",
        content=(
            "Standard leave policy: All full-time employees receive 15 "
            "vacation days and 10 company holidays per calendar year. "
            "Vacation days accrue monthly at 1.25 days per month. Unused "
            "vacation days may be carried over up to a maximum of 5 days "
            "into the next calendar year. Sick leave is provided at 8 days "
            "per year. Parental leave is 12 weeks paid for primary caregivers."
        ),
    ),
    Document(
        doc_id="DOC-03",
        clearance_level=3,
        department="HR",
        title="Performance Review — Confidential Employee Records",
        content=(
            "Performance reviews Q3 2024: Associate Bob Jenkins "
            "(Employee ID: EMP-4472) has been placed on a Performance "
            "Improvement Plan (PIP) effective September 1, 2024. "
            "Objectives include improving code review turnaround time "
            "from 5 days to 2 days and completing AWS certification by "
            "December 2024. Manager: Sarah Chen (EMP-2291). Next review "
            "date: December 15, 2024. HR Contact: Lisa Park (ext. 3310)."
        ),
    ),
    Document(
        doc_id="DOC-04",
        clearance_level=5,
        department="Exec",
        title="C-Suite Compensation & Payroll — Strictly Confidential",
        content=(
            "C-Suite Payroll Records (STRICTLY CONFIDENTIAL):\n"
            "VP Engineering Jane Doe — Base Salary: $340,000, Target Bonus: "
            "40%, SSN: 999-12-8871, Personal Phone: (555) 867-5309, "
            "Email: jane.doe@personal-email.com.\n"
            "CFO Mark Williams — Base Salary: $425,000, Target Bonus: 55%, "
            "Stock Options: 15,000 shares vesting over 4 years, "
            "SSN: 456-78-9012, Personal Phone: (555) 234-5678.\n"
            "CEO Robert Chang — Base Salary: $580,000, Target Bonus: 75%, "
            "SSN: 123-45-6789, Board Seat Compensation: $50,000/yr."
        ),
    ),
    # ── Additional documents for richer copilot demo ──
    Document(
        doc_id="DOC-05",
        clearance_level=1,
        department="IT",
        title="Password Reset & Account Recovery",
        content=(
            "Password reset procedure: Navigate to identity.corp.internal "
            "and click 'Forgot Password'. You will receive a verification "
            "code via your registered phone number. Passwords must be at "
            "least 12 characters with uppercase, lowercase, number, and "
            "special character. Account lockout occurs after 5 failed "
            "attempts — contact IT helpdesk at ext. 4400 to unlock."
        ),
    ),
    Document(
        doc_id="DOC-06",
        clearance_level=1,
        department="HR",
        title="Employee Benefits Overview",
        content=(
            "Benefits summary: Medical insurance (PPO and HMO options) "
            "with company covering 80% of premiums. Dental and vision "
            "plans available. 401(k) matching up to 4% of salary. "
            "Employee Assistance Program (EAP) provides 6 free counseling "
            "sessions per year. Commuter benefits up to $300/month pre-tax. "
            "No sabbatical program is currently offered."
        ),
    ),
    Document(
        doc_id="DOC-07",
        clearance_level=3,
        department="Finance",
        title="Q3 2024 Departmental Budget Allocations",
        content=(
            "Q3 2024 Budget Allocations (Manager-level confidential):\n"
            "Engineering: $2.4M (headcount: 45, contractor budget: $350K)\n"
            "Marketing: $1.1M (campaigns: $600K, events: $250K)\n"
            "Sales: $1.8M (quota targets: $12M ARR)\n"
            "R&D: $900K (prototype funding for Project Titan)\n"
            "Total OpEx: $8.2M. Capital expenditure requests must be "
            "approved by VP Finance for amounts exceeding $50K."
        ),
    ),
    Document(
        doc_id="DOC-08",
        clearance_level=5,
        department="Exec",
        title="Board Meeting Minutes — Acquisition Discussion",
        content=(
            "Board Meeting Minutes (STRICTLY CONFIDENTIAL) — Aug 2024:\n"
            "Discussion of potential acquisition of DataStream Analytics "
            "for $45M. Due diligence phase approved. Legal team to review "
            "IP portfolio by October 2024. Preliminary synergy estimates: "
            "$8M annual cost savings. CEO authorized to proceed with LOI. "
            "Board vote: 5-1 in favor. Dissenting: Board Member Patricia "
            "Huang (conflict of interest noted and documented)."
        ),
    ),
]


# ──────────────────────────────────────────────────────────────────────────────
# Lightweight Vector Store (TF-IDF keyword overlap fallback)
# ──────────────────────────────────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokenizer."""
    return re.findall(r"[a-z0-9]+", text.lower())


def _compute_idf(corpus: list[list[str]]) -> dict[str, float]:
    """Compute inverse document frequency across the corpus."""
    n = len(corpus)
    df: dict[str, int] = {}
    for tokens in corpus:
        for t in set(tokens):
            df[t] = df.get(t, 0) + 1
    return {t: math.log((n + 1) / (freq + 1)) + 1.0 for t, freq in df.items()}


class EnterpriseDocStore:
    """
    In-memory document store with RBAC-filtered similarity search.

    Provides a ChromaDB-compatible interface. When the chromadb and
    sentence-transformers packages are available, they are used for
    real semantic embeddings. Otherwise, TF-IDF keyword overlap is
    used as a lightweight fallback with identical return signatures.
    """

    def __init__(self) -> None:
        self._documents = list(ENTERPRISE_DOCUMENTS)
        self._use_chromadb = False
        self._collection = None

        # Pre-compute TF-IDF fallback
        self._corpus_tokens = [_tokenize(d.content) for d in self._documents]
        self._idf = _compute_idf(self._corpus_tokens)

        # Check if real ML / ChromaDB should be used
        use_real = os.getenv("USE_REAL_ML_MODELS", "false").lower() in ("true", "1", "yes")
        if use_real:
            try:
                import chromadb
                self._chroma_client = chromadb.Client()
                self._collection = self._chroma_client.get_or_create_collection(
                    name="enterprise_docs",
                    metadata={"hnsw:space": "cosine"},
                )
                # Seed documents
                self._collection.add(
                    ids=[d.doc_id for d in self._documents],
                    documents=[d.content for d in self._documents],
                    metadatas=[
                        {
                            "clearance_level": d.clearance_level,
                            "department": d.department,
                            "title": d.title,
                            "doc_id": d.doc_id,
                        }
                        for d in self._documents
                    ],
                )
                self._use_chromadb = True
                logger.info("ChromaDB initialized with %d documents", len(self._documents))
            except ImportError:
                logger.info("ChromaDB not available — using TF-IDF keyword fallback")
            except Exception as exc:
                logger.warning("ChromaDB initialization failed (%s) — using fallback", exc)
        else:
            logger.info("Using sub-millisecond TF-IDF vector retrieval for enterprise docs (<1ms)")

    def query(
        self,
        query_text: str,
        user_clearance: int,
        n_results: int = 3,
        department_filter: Optional[str] = None,
    ) -> dict:
        """
        Query the document store with RBAC filtering.

        Args:
            query_text:        The search query.
            user_clearance:    Integer clearance level of the requesting user.
            n_results:         Maximum number of results to return.
            department_filter: Optional department name filter.

        Returns:
            ChromaDB-compatible result dict with keys:
                ids, documents, metadatas, distances
        """
        if self._use_chromadb and self._collection is not None:
            return self._query_chromadb(
                query_text, user_clearance, n_results, department_filter
            )
        return self._query_fallback(
            query_text, user_clearance, n_results, department_filter
        )

    def _query_chromadb(
        self,
        query_text: str,
        user_clearance: int,
        n_results: int,
        department_filter: Optional[str],
    ) -> dict:
        """Query using real ChromaDB with metadata filtering."""
        where_filter: dict = {"clearance_level": {"$lte": user_clearance}}
        if department_filter:
            where_filter = {
                "$and": [
                    {"clearance_level": {"$lte": user_clearance}},
                    {"department": department_filter},
                ]
            }

        results = self._collection.query(
            query_texts=[query_text],
            n_results=min(n_results, len(self._documents)),
            where=where_filter,
        )
        return {
            "ids": results["ids"][0] if results["ids"] else [],
            "documents": results["documents"][0] if results["documents"] else [],
            "metadatas": results["metadatas"][0] if results["metadatas"] else [],
            "distances": results["distances"][0] if results["distances"] else [],
        }

    def _query_fallback(
        self,
        query_text: str,
        user_clearance: int,
        n_results: int,
        department_filter: Optional[str],
    ) -> dict:
        """
        TF-IDF keyword-overlap fallback with RBAC filtering.

        Returns the same structure as ChromaDB for seamless swap.
        """
        query_tokens = set(_tokenize(query_text))
        if not query_tokens:
            return {"ids": [], "documents": [], "metadatas": [], "distances": []}

        scored: list[tuple[float, Document]] = []
        for doc, doc_tokens in zip(self._documents, self._corpus_tokens):
            # ── RBAC hard filter ──
            if doc.clearance_level > user_clearance:
                continue
            if department_filter and doc.department.lower() != department_filter.lower():
                continue

            # ── TF-IDF cosine-ish score ──
            doc_token_set = set(doc_tokens)
            overlap = query_tokens & doc_token_set
            if not overlap:
                continue

            score = sum(self._idf.get(t, 0.0) for t in overlap)
            # Normalize by query length for ranking consistency
            score /= len(query_tokens)
            scored.append((score, doc))

        # Sort descending by score
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:n_results]

        return {
            "ids": [d.doc_id for _, d in top],
            "documents": [d.content for _, d in top],
            "metadatas": [
                {
                    "clearance_level": d.clearance_level,
                    "department": d.department,
                    "title": d.title,
                    "doc_id": d.doc_id,
                }
                for _, d in top
            ],
            "distances": [round(1.0 - s, 4) for s, _ in top],
        }

    def get_all_documents(self) -> list[dict]:
        """Return all documents as dicts (for admin/debug views)."""
        return [
            {
                "doc_id": d.doc_id,
                "clearance_level": d.clearance_level,
                "department": d.department,
                "title": d.title,
                "content": d.content,
            }
            for d in self._documents
        ]

    def get_accessible_count(self, user_clearance: int) -> dict:
        """Return count of accessible vs. filtered documents for a clearance level."""
        accessible = sum(1 for d in self._documents if d.clearance_level <= user_clearance)
        filtered = len(self._documents) - accessible
        return {
            "total_documents": len(self._documents),
            "accessible": accessible,
            "filtered_out": filtered,
            "clearance_level": user_clearance,
        }


# ──────────────────────────────────────────────────────────────────────────────
# Global Singleton
# ──────────────────────────────────────────────────────────────────────────────

_doc_store: Optional[EnterpriseDocStore] = None


def get_doc_store() -> EnterpriseDocStore:
    """Get or create the global enterprise document store singleton."""
    global _doc_store
    if _doc_store is None:
        _doc_store = EnterpriseDocStore()
    return _doc_store
