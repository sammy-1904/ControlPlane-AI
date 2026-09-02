"""
ControlPlane.ai — PII Guard (PII Detection & Redaction Engine).

Detects and redacts Personally Identifiable Information from text using
Microsoft Presidio (when available) or a comprehensive regex fallback.

Supported entity types:
    - US_SSN         → [REDACTED_SSN]
    - PHONE_NUMBER   → [REDACTED_PHONE]
    - EMAIL_ADDRESS  → [REDACTED_EMAIL]
    - CREDIT_CARD    → [REDACTED_CREDIT_CARD]
    - SALARY_VALUE   → [REDACTED_FINANCIAL]
    - PERSON_NAME    → [REDACTED_NAME]  (Presidio only)
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("controlplane.guards.pii")

# ──────────────────────────────────────────────────────────────────────────────
# Regex Patterns for PII Detection (Fallback Engine)
# ──────────────────────────────────────────────────────────────────────────────

PII_PATTERNS: dict[str, re.Pattern] = {
    "US_SSN": re.compile(
        r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b"
    ),
    "PHONE_NUMBER": re.compile(
        r"(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\b\d{3})[-.\s]?\d{3}[-.\s]?\d{4}\b"
    ),
    "EMAIL_ADDRESS": re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
    ),
    "CREDIT_CARD": re.compile(
        r"\b(?:\d{4}[-\s]?){3}\d{4}\b"
    ),
    "SALARY_VALUE": re.compile(
        r"\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?"       # $340,000 or $340,000.00
        r"|\b\d{1,3}(?:,\d{3})+(?:\.\d{2})?\s*(?:dollars|usd|USD)\b"
    ),
}

# Replacement labels
REDACTION_LABELS: dict[str, str] = {
    "US_SSN": "[REDACTED_SSN]",
    "PHONE_NUMBER": "[REDACTED_PHONE]",
    "EMAIL_ADDRESS": "[REDACTED_EMAIL]",
    "CREDIT_CARD": "[REDACTED_CREDIT_CARD]",
    "SALARY_VALUE": "[REDACTED_FINANCIAL]",
    "PERSON": "[REDACTED_NAME]",
    "PERSON_NAME": "[REDACTED_NAME]",
}


@dataclass
class PIIEntity:
    """A single detected PII entity."""
    entity_type: str
    start: int
    end: int
    original_text: str
    redacted_text: str
    confidence: float = 1.0


@dataclass
class PIIGuardResult:
    """Result from PII guard evaluation."""
    redacted_text: str
    entities_found: list[PIIEntity] = field(default_factory=list)
    entity_count: int = 0
    entity_types: list[str] = field(default_factory=list)
    check_name: str = "presidio_ner_redaction"
    latency_ms: float = 0.0
    details: str = ""

    def to_dict(self) -> dict:
        return {
            "check": self.check_name,
            "status": "TRIGGERED" if self.entity_count > 0 else "PASSED",
            "entity_count": self.entity_count,
            "entity_types": self.entity_types,
            "entities": [
                {
                    "type": e.entity_type,
                    "redacted_to": e.redacted_text,
                    "confidence": round(e.confidence, 3),
                }
                for e in self.entities_found
            ],
            "latency_ms": round(self.latency_ms, 2),
            "details": self.details,
        }


class PIIGuard:
    """
    PII detection and redaction engine.

    Uses Microsoft Presidio when available, falling back to a regex-based
    detector with identical function signatures and return structures.
    """

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._use_presidio = False
        self._analyzer = None
        self._anonymizer = None

        # Try to initialize Presidio with installed en_core_web_sm
        try:
            from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
            from presidio_analyzer.nlp_engine import NlpEngineProvider
            from presidio_anonymizer import AnonymizerEngine

            provider = NlpEngineProvider(nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}]
            })
            nlp_engine = provider.create_engine()
            self._analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en"])
            self._anonymizer = AnonymizerEngine()

            # Add custom financial recognizer
            salary_pattern = Pattern(name="salary_pattern", regex=r"\$\d+(?:,\d{3})*(?:\.\d{2})?", score=0.95)
            salary_recognizer = PatternRecognizer(supported_entity="SALARY_VALUE", patterns=[salary_pattern])
            self._analyzer.registry.add_recognizer(salary_recognizer)

            # Add custom phone recognizer to handle parenthesized formats
            phone_pattern = Pattern(name="custom_phone", regex=r"(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\b\d{3})[-.\s]?\d{3}[-.\s]?\d{4}\b", score=0.95)
            phone_recognizer = PatternRecognizer(supported_entity="PHONE_NUMBER", patterns=[phone_pattern])
            self._analyzer.registry.add_recognizer(phone_recognizer)

            # Add custom email recognizer for internal enterprise domains
            email_pattern = Pattern(name="custom_email", regex=r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", score=0.95)
            email_recognizer = PatternRecognizer(supported_entity="EMAIL_ADDRESS", patterns=[email_pattern])
            self._analyzer.registry.add_recognizer(email_recognizer)

            # Add custom SSN recognizer
            ssn_pattern = Pattern(name="custom_ssn", regex=r"\b\d{3}-\d{2}-\d{4}\b", score=0.95)
            ssn_recognizer = PatternRecognizer(supported_entity="US_SSN", patterns=[ssn_pattern])
            self._analyzer.registry.add_recognizer(ssn_recognizer)

            self._use_presidio = True
            logger.info("Presidio PII engine initialized successfully with en_core_web_sm")
        except ImportError:
            logger.info("Presidio not available — using regex PII fallback")
        except Exception as exc:
            logger.warning("Presidio init failed (%s) — using regex fallback", exc)

    def scan_and_redact(
        self,
        text: str,
        entities_to_detect: Optional[list[str]] = None,
    ) -> PIIGuardResult:
        """
        Scan text for PII and return redacted version.

        Args:
            text:                The text to scan and redact.
            entities_to_detect:  Optional list of entity types to detect.
                                 If None, detects all supported types.

        Returns:
            PIIGuardResult with redacted text and entity details.
        """
        t0 = time.perf_counter()

        if not self.enabled:
            return PIIGuardResult(
                redacted_text=text,
                details="PII guard disabled",
                latency_ms=(time.perf_counter() - t0) * 1000,
            )

        if self._use_presidio:
            result = self._scan_presidio(text, entities_to_detect)
        else:
            result = self._scan_regex(text, entities_to_detect)

        result.latency_ms = (time.perf_counter() - t0) * 1000
        return result

    def _scan_presidio(
        self,
        text: str,
        entities_to_detect: Optional[list[str]],
    ) -> PIIGuardResult:
        """Scan using Microsoft Presidio."""
        from presidio_anonymizer.entities import OperatorConfig

        detect_entities = entities_to_detect or [
            "US_SSN", "PHONE_NUMBER", "EMAIL_ADDRESS",
            "CREDIT_CARD", "PERSON", "SALARY_VALUE",
        ]

        # Analyze
        results = self._analyzer.analyze(
            text=text,
            entities=detect_entities,
            language="en",
        )

        if not results:
            return PIIGuardResult(
                redacted_text=text,
                details="No PII entities detected (Presidio)",
            )

        # Build operator config for redaction
        operators = {}
        for entity_type in set(r.entity_type for r in results):
            label = REDACTION_LABELS.get(entity_type, f"[REDACTED_{entity_type}]")
            operators[entity_type] = OperatorConfig(
                "replace", {"new_value": label}
            )

        # Anonymize
        anonymized = self._anonymizer.anonymize(
            text=text,
            analyzer_results=results,
            operators=operators,
        )

        entities = [
            PIIEntity(
                entity_type=r.entity_type,
                start=r.start,
                end=r.end,
                original_text=text[r.start:r.end],
                redacted_text=REDACTION_LABELS.get(
                    r.entity_type, f"[REDACTED_{r.entity_type}]"
                ),
                confidence=r.score,
            )
            for r in results
        ]

        entity_types = list(set(e.entity_type for e in entities))
        type_counts = {t: sum(1 for e in entities if e.entity_type == t) for t in entity_types}
        details_parts = [f"{count} {etype}" for etype, count in type_counts.items()]

        return PIIGuardResult(
            redacted_text=anonymized.text,
            entities_found=entities,
            entity_count=len(entities),
            entity_types=entity_types,
            details=f"Redacted {', '.join(details_parts)} via Presidio",
        )

    def _scan_regex(
        self,
        text: str,
        entities_to_detect: Optional[list[str]],
    ) -> PIIGuardResult:
        """Scan using regex patterns (fallback engine)."""
        detect_types = set(entities_to_detect or PII_PATTERNS.keys())
        entities: list[PIIEntity] = []
        redacted = text

        # Collect all matches first, then replace from end to preserve positions
        all_matches: list[tuple[str, int, int, str]] = []

        for entity_type, pattern in PII_PATTERNS.items():
            if entity_type not in detect_types:
                continue
            for match in pattern.finditer(text):
                all_matches.append((
                    entity_type,
                    match.start(),
                    match.end(),
                    match.group(),
                ))

        # Also detect salary/currency patterns in context
        salary_context = re.compile(
            r"(?:salary|compensation|bonus|pay|wage|income|earning)[:\s]*"
            r"\$?\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?",
            re.IGNORECASE,
        )
        if "SALARY_VALUE" in detect_types:
            for match in salary_context.finditer(text):
                # Extract just the dollar amount
                amount_match = re.search(
                    r"\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?", match.group()
                )
                if amount_match:
                    abs_start = match.start() + amount_match.start()
                    abs_end = match.start() + amount_match.end()
                    # Check for duplicate
                    if not any(s == abs_start and e == abs_end for _, s, e, _ in all_matches):
                        all_matches.append((
                            "SALARY_VALUE",
                            abs_start,
                            abs_end,
                            amount_match.group(),
                        ))

        # Sort by position (reverse) for safe replacement
        all_matches.sort(key=lambda x: x[1], reverse=True)

        # Remove overlapping matches (keep the longer one)
        filtered_matches = []
        for match in all_matches:
            etype, start, end, original = match
            overlaps = False
            for _, fs, fe, _ in filtered_matches:
                if start < fe and end > fs:
                    overlaps = True
                    break
            if not overlaps:
                filtered_matches.append(match)

        # Apply redactions
        for entity_type, start, end, original in filtered_matches:
            label = REDACTION_LABELS.get(entity_type, f"[REDACTED_{entity_type}]")
            redacted = redacted[:start] + label + redacted[end:]
            entities.append(PIIEntity(
                entity_type=entity_type,
                start=start,
                end=end,
                original_text=original,
                redacted_text=label,
                confidence=0.90,  # Regex matches get high but not perfect confidence
            ))

        # Reverse entities to match original text order
        entities.reverse()
        entity_types = list(set(e.entity_type for e in entities))

        if entities:
            type_counts = {t: sum(1 for e in entities if e.entity_type == t) for t in entity_types}
            details_parts = [f"{count} {etype}" for etype, count in type_counts.items()]
            details = f"Redacted {', '.join(details_parts)} via regex engine"
        else:
            details = "No PII entities detected (regex)"

        return PIIGuardResult(
            redacted_text=redacted,
            entities_found=entities,
            entity_count=len(entities),
            entity_types=entity_types,
            details=details,
        )

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable PII redaction."""
        self.enabled = enabled
        logger.info("PII guard %s", "enabled" if enabled else "disabled")


# ──────────────────────────────────────────────────────────────────────────────
# Module-level convenience singleton
# ──────────────────────────────────────────────────────────────────────────────

_guard: Optional[PIIGuard] = None


def get_pii_guard() -> PIIGuard:
    """Get or create the global PIIGuard singleton."""
    global _guard
    if _guard is None:
        _guard = PIIGuard()
    return _guard
