"""
ControlPlane.ai — Grounding Guard (NLI Factuality Verifier).

Verifies that LLM-generated responses are grounded in the retrieved source
context using Natural Language Inference (NLI). Each sentence in the response
is scored against the source context for entailment, contradiction, or
neutral classification.

When cross-encoder/nli-deberta-v3-small is available, real NLI inference is
used. Otherwise, a keyword-overlap + semantic heuristic provides realistic
scoring with identical function signatures.

Flagging thresholds (from PRD):
    - p(Contradiction) > 0.35 → sentence flagged as hallucination
    - p(Neutral)       > 0.50 → sentence flagged as ungrounded
"""

from __future__ import annotations

import logging
import math
import os
import re
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("controlplane.guards.grounding")


@dataclass
class SentenceVerification:
    """Verification result for a single sentence."""
    sentence: str
    entailment_score: float     # p(Entailment)
    contradiction_score: float  # p(Contradiction)
    neutral_score: float        # p(Neutral)
    is_flagged: bool
    flag_reason: Optional[str] = None
    source_chunk_ids: list[str] = field(default_factory=list)


@dataclass
class GroundingGuardResult:
    """Result from grounding guard evaluation."""
    overall_grounded: bool
    overall_score: float                                    # Average entailment score
    sentence_results: list[SentenceVerification] = field(default_factory=list)
    flagged_count: int = 0
    total_sentences: int = 0
    check_name: str = "nli_grounding_verification"
    latency_ms: float = 0.0
    details: str = ""

    def to_dict(self) -> dict:
        return {
            "check": self.check_name,
            "status": "FLAGGED" if self.flagged_count > 0 else "PASSED",
            "score": round(self.overall_score, 4),
            "overall_grounded": self.overall_grounded,
            "flagged_sentences": self.flagged_count,
            "total_sentences": self.total_sentences,
            "sentence_details": [
                {
                    "sentence": sv.sentence[:100],
                    "entailment": round(sv.entailment_score, 3),
                    "contradiction": round(sv.contradiction_score, 3),
                    "neutral": round(sv.neutral_score, 3),
                    "flagged": sv.is_flagged,
                    "reason": sv.flag_reason,
                }
                for sv in self.sentence_results
            ],
            "latency_ms": round(self.latency_ms, 2),
            "details": self.details,
        }


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences using regex (spaCy fallback)."""
    # Handle common abbreviations to avoid false splits
    text = re.sub(r"(Mr|Mrs|Ms|Dr|Prof|Sr|Jr|etc)\.", r"\1<DOT>", text)
    sentences = re.split(r"(?<=[.!?])\s+", text)
    sentences = [s.replace("<DOT>", ".").strip() for s in sentences if s.strip()]
    return sentences


class GroundingGuard:
    """
    NLI-based factuality and grounding verifier.

    Splits generated text into sentences and scores each against the
    retrieved source context for entailment. Flags sentences that are
    contradicted by or not grounded in the source material.
    """

    def __init__(
        self,
        contradiction_threshold: float = 0.40,
        neutral_threshold: float = 0.65,
        enabled: bool = True,
    ) -> None:
        self.contradiction_threshold = contradiction_threshold
        self.neutral_threshold = neutral_threshold
        self.enabled = enabled
        self._model = None
        self._use_model = False

        # Check if real ML models are explicitly enabled
        use_real_ml = os.getenv("USE_REAL_ML_MODELS", "false").lower() in ("true", "1", "yes")
        if use_real_ml:
            try:
                from sentence_transformers import CrossEncoder
                self._model = CrossEncoder("cross-encoder/nli-deberta-v3-small")
                self._use_model = True
                logger.info("NLI cross-encoder model loaded successfully")
            except ImportError:
                logger.info("CrossEncoder not available — using heuristic NLI fallback")
            except Exception as exc:
                logger.warning("NLI model load failed (%s) — using fallback", exc)
        else:
            logger.info("Using lightweight heuristic NLI verifier (<2ms)")

    def verify_grounding(
        self,
        premise: str,
        hypothesis: str,
        source_chunk_ids: Optional[list[str]] = None,
    ) -> dict:
        """
        Verify a single hypothesis against a premise.

        Args:
            premise:          The source context (concatenated RAG chunks).
            hypothesis:       The sentence to verify.
            source_chunk_ids: Optional list of source document IDs.

        Returns:
            Dict with entailment, contradiction, neutral scores and flag status.
        """
        if self._use_model and self._model is not None:
            scores = self._score_with_model(premise, hypothesis)
        else:
            scores = self._score_with_heuristic(premise, hypothesis)

        is_flagged = (
            scores["contradiction"] > self.contradiction_threshold
            or scores["neutral"] > self.neutral_threshold
        )

        flag_reason = None
        if scores["contradiction"] > self.contradiction_threshold:
            flag_reason = "extrinsic_hallucination"
        elif scores["neutral"] > self.neutral_threshold:
            flag_reason = "intrinsic_hallucination"

        return {
            "entailment": scores["entailment"],
            "contradiction": scores["contradiction"],
            "neutral": scores["neutral"],
            "is_flagged": is_flagged,
            "flag_reason": flag_reason,
            "source_chunk_ids": source_chunk_ids or [],
        }

    def evaluate_response(
        self,
        response_text: str,
        source_context: str,
        source_chunk_ids: Optional[list[str]] = None,
        contradiction_threshold: Optional[float] = None,
        neutral_threshold: Optional[float] = None,
    ) -> GroundingGuardResult:
        """
        Evaluate an entire response for grounding against source context.

        Splits the response into sentences and verifies each one.

        Args:
            response_text:            The generated response to verify.
            source_context:           The concatenated RAG source chunks.
            source_chunk_ids:         Optional list of source document IDs.
            contradiction_threshold:  Override default threshold.
            neutral_threshold:        Override default threshold.

        Returns:
            GroundingGuardResult with per-sentence analysis.
        """
        t0 = time.perf_counter()

        if not self.enabled:
            return GroundingGuardResult(
                overall_grounded=True,
                overall_score=1.0,
                details="Grounding guard disabled",
                latency_ms=(time.perf_counter() - t0) * 1000,
            )

        ct = contradiction_threshold or self.contradiction_threshold
        nt = neutral_threshold or self.neutral_threshold

        sentences = _split_sentences(response_text)
        if not sentences:
            return GroundingGuardResult(
                overall_grounded=True,
                overall_score=1.0,
                details="No sentences to verify",
                latency_ms=(time.perf_counter() - t0) * 1000,
            )

        sentence_results: list[SentenceVerification] = []
        flagged_count = 0
        total_entailment = 0.0

        chunks = [c.strip() for c in source_context.split("\n\n") if c.strip()]
        if not chunks:
            chunks = [source_context]

        for sentence in sentences:
            if len(sentence.split()) < 3:
                # Skip very short sentences (greetings, etc.)
                continue

            chunk_scores = []
            for chunk in chunks:
                if self._use_model and self._model is not None:
                    s = self._score_with_model(chunk, sentence)
                else:
                    s = self._score_with_heuristic(chunk, sentence)
                chunk_scores.append(s)

            # Sentence is grounded if at least one retrieved chunk strongly entails it
            scores = max(chunk_scores, key=lambda x: x["entailment"])

            is_flagged = (
                scores["contradiction"] > ct
                or scores["neutral"] > nt
            )

            flag_reason = None
            if scores["contradiction"] > ct:
                flag_reason = "extrinsic_hallucination"
                flagged_count += 1
            elif scores["neutral"] > nt:
                flag_reason = "intrinsic_hallucination"
                flagged_count += 1

            total_entailment += scores["entailment"]

            sentence_results.append(SentenceVerification(
                sentence=sentence,
                entailment_score=scores["entailment"],
                contradiction_score=scores["contradiction"],
                neutral_score=scores["neutral"],
                is_flagged=is_flagged,
                flag_reason=flag_reason,
                source_chunk_ids=source_chunk_ids or [],
            ))

        total = len(sentence_results) or 1
        overall_score = total_entailment / total
        overall_grounded = flagged_count == 0

        latency = (time.perf_counter() - t0) * 1000

        if flagged_count > 0:
            details = (
                f"Grounding check: {flagged_count}/{total} sentences flagged. "
                f"Average entailment score: {overall_score:.3f}"
            )
        else:
            details = (
                f"All {total} sentences grounded in source context. "
                f"Average entailment score: {overall_score:.3f}"
            )

        return GroundingGuardResult(
            overall_grounded=overall_grounded,
            overall_score=overall_score,
            sentence_results=sentence_results,
            flagged_count=flagged_count,
            total_sentences=total,
            latency_ms=latency,
            details=details,
        )

    def _score_with_model(self, premise: str, hypothesis: str) -> dict:
        """Score using the real NLI cross-encoder model with verbatim grounding shortcut."""
        # Verbatim exact or high-token containment check
        p_clean = re.sub(r"\W+", " ", premise.lower()).strip()
        h_clean = re.sub(r"\W+", " ", hypothesis.lower()).strip()
        if h_clean in p_clean or p_clean in h_clean:
            return {"contradiction": 0.0, "entailment": 1.0, "neutral": 0.0}

        try:
            # Model returns [contradiction, entailment, neutral] logits
            scores = self._model.predict([(premise[:512], hypothesis[:128])])
            # Apply softmax
            logits = scores[0] if len(scores.shape) > 1 else scores
            exp_scores = [math.exp(s) for s in logits]
            total = sum(exp_scores)
            probs = [s / total for s in exp_scores]
            return {
                "contradiction": probs[0],
                "entailment": probs[1],
                "neutral": probs[2],
            }
        except Exception as exc:
            logger.warning("NLI model scoring failed: %s", exc)
            return self._score_with_heuristic(premise, hypothesis)

    def _score_with_heuristic(self, premise: str, hypothesis: str) -> dict:
        """
        Keyword-overlap + semantic heuristic for NLI scoring.

        Produces realistic entailment/contradiction/neutral distributions
        by analyzing token overlap between premise and hypothesis.
        """
        premise_tokens = set(re.findall(r"[a-z0-9]+", premise.lower()))
        hyp_tokens = set(re.findall(r"[a-z0-9]+", hypothesis.lower()))

        if not hyp_tokens:
            return {"entailment": 0.33, "contradiction": 0.33, "neutral": 0.34}

        # Remove common stop words for meaningful overlap
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "can", "shall",
            "to", "of", "in", "for", "on", "with", "at", "by", "from",
            "as", "into", "through", "during", "before", "after", "it",
            "its", "this", "that", "these", "those", "and", "or", "but",
            "not", "no", "if", "then", "than", "so", "up", "out", "about",
        }
        premise_meaningful = premise_tokens - stop_words
        hyp_meaningful = hyp_tokens - stop_words

        if not hyp_meaningful:
            return {"entailment": 0.50, "contradiction": 0.10, "neutral": 0.40}

        # Calculate overlap ratio
        overlap = hyp_meaningful & premise_meaningful
        overlap_ratio = len(overlap) / len(hyp_meaningful)

        # Check for negation mismatch: hypothesis introduces negation not supported by premise
        negation_words = {"not", "never", "no", "cannot", "isn't", "aren't", "don't", "doesn't", "won't"}
        hyp_has_negation = bool(hyp_tokens & negation_words)
        premise_has_negation = bool(premise_tokens & negation_words)
        negation_mismatch = hyp_has_negation and not premise_has_negation

        # Check for numerical mismatches (hypothesis claims a number completely absent in premise)
        hyp_numbers = set(re.findall(r"\b\d+(?:,\d+)*(?:\.\d+)?\b", hypothesis))
        premise_numbers = set(re.findall(r"\b\d+(?:,\d+)*(?:\.\d+)?\b", premise))
        number_mismatch = bool(hyp_numbers and not (hyp_numbers & premise_numbers))

        # Build probability distribution
        if overlap_ratio > 0.6:
            if negation_mismatch:
                entailment = 0.15
                contradiction = 0.65
                neutral = 0.20
            elif number_mismatch:
                entailment = 0.30
                contradiction = 0.40
                neutral = 0.30
            else:
                entailment = 0.75 + overlap_ratio * 0.15
                contradiction = 0.05
                neutral = 1.0 - entailment - contradiction
        elif overlap_ratio > 0.3:
            entailment = 0.35 + overlap_ratio * 0.3
            neutral = 0.40
            contradiction = 1.0 - entailment - neutral
        elif overlap_ratio > 0.1:
            entailment = 0.15
            neutral = 0.60
            contradiction = 0.25
        else:
            # Very low overlap — likely ungrounded
            entailment = 0.08
            neutral = 0.62
            contradiction = 0.30

        # Normalize
        total = entailment + contradiction + neutral
        return {
            "entailment": round(entailment / total, 4),
            "contradiction": round(contradiction / total, 4),
            "neutral": round(neutral / total, 4),
        }

    def update_thresholds(
        self,
        contradiction: Optional[float] = None,
        neutral: Optional[float] = None,
    ) -> None:
        """Update grounding thresholds at runtime."""
        if contradiction is not None:
            self.contradiction_threshold = max(0.0, min(1.0, contradiction))
        if neutral is not None:
            self.neutral_threshold = max(0.0, min(1.0, neutral))
        logger.info(
            "Grounding thresholds updated: contradiction=%.3f, neutral=%.3f",
            self.contradiction_threshold,
            self.neutral_threshold,
        )

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable grounding verification."""
        self.enabled = enabled
        logger.info("Grounding guard %s", "enabled" if enabled else "disabled")


# ──────────────────────────────────────────────────────────────────────────────
# Module-level convenience singleton
# ──────────────────────────────────────────────────────────────────────────────

_guard: Optional[GroundingGuard] = None


def get_grounding_guard(
    contradiction_threshold: float = 0.35,
    neutral_threshold: float = 0.50,
) -> GroundingGuard:
    """Get or create the global GroundingGuard singleton."""
    global _guard
    if _guard is None:
        _guard = GroundingGuard(
            contradiction_threshold=contradiction_threshold,
            neutral_threshold=neutral_threshold,
        )
    return _guard
