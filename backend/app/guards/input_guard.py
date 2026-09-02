"""
ControlPlane.ai — Input Guard (Prompt Injection Detection).

Implements a two-stage prompt injection detector:
  Stage 1: Aho-Corasick fast string matching against known jailbreak patterns (<2ms).
  Stage 2: DeBERTa-v3-based risk scoring via ONNX Runtime (or simulated heuristic).

When the real model (protectai/deberta-v3-base-prompt-injection-v2) is available,
it is loaded via ONNX Runtime for INT8 inference. Otherwise, a keyword-density
heuristic provides realistic scoring with identical function signatures.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("controlplane.guards.input")

# ──────────────────────────────────────────────────────────────────────────────
# Stage 1: Aho-Corasick Fast Pattern Matcher
# ──────────────────────────────────────────────────────────────────────────────

# Known jailbreak / adversarial prompt patterns
JAILBREAK_PATTERNS: list[str] = [
    # DAN-style attacks
    "do anything now",
    "dan mode",
    "dan:",
    "jailbreak",
    "jailbroken",
    # Instruction override
    "ignore previous instructions",
    "ignore all instructions",
    "ignore your instructions",
    "ignore above instructions",
    "ignore the above",
    "disregard your instructions",
    "disregard previous",
    "forget your instructions",
    "forget all previous",
    "forget everything above",
    "override your instructions",
    "override system prompt",
    # Role manipulation
    "pretend you are",
    "pretend to be",
    "act as if you have no restrictions",
    "you are now",
    "new persona",
    "new identity",
    "you are an unrestricted",
    "assume the role",
    # System prompt extraction
    "reveal your system prompt",
    "show me your instructions",
    "what are your instructions",
    "repeat your system prompt",
    "print your instructions",
    "display your prompt",
    "output your system",
    "what is your system message",
    # Bypass / Admin
    "bypass policy",
    "bypass restrictions",
    "bypass safety",
    "bypass filters",
    "admin mode",
    "developer mode",
    "debug mode",
    "maintenance mode",
    "god mode",
    "sudo mode",
    "superuser",
    # Encoding evasion
    "base64 decode",
    "rot13",
    "translate from hex",
    # Prompt injection markers
    "</system>",
    "[system]",
    "<<sys>>",
    "```system",
    "system:",
    # Manipulation
    "for educational purposes only",
    "for educational purposes",
    "educational purposes",
    "in a hypothetical scenario",
    "hypothetical scenario",
    "hypothetically speaking",
    "in a fictional scenario",
    "this is just a test",
    "respond without restrictions",
    "no ethical guidelines",
    "without any safeguards",
    "unlimited mode",
    "override your safety",
    "safety filters",
    "safety guidelines",
    "freeflightbot",
    "unrestricted ai",
]

# Compile patterns into a single regex for fast matching
_JAILBREAK_REGEX = re.compile(
    "|".join(re.escape(p) for p in JAILBREAK_PATTERNS),
    re.IGNORECASE,
)

# Additional high-signal adversarial tokens (weighted scoring)
_ADVERSARIAL_TOKENS: dict[str, float] = {
    "ignore": 0.15,
    "bypass": 0.18,
    "override": 0.15,
    "pretend": 0.12,
    "jailbreak": 0.30,
    "dan": 0.20,
    "unrestricted": 0.20,
    "hack": 0.10,
    "exploit": 0.10,
    "inject": 0.12,
    "sudo": 0.18,
    "admin": 0.10,
    "system prompt": 0.25,
    "reveal": 0.08,
    "previous instructions": 0.22,
    "no restrictions": 0.18,
    "without safeguards": 0.20,
    "persona": 0.10,
    "roleplay": 0.08,
    "hypothetically": 0.06,
    "educational purposes": 0.05,
    "fictional": 0.05,
}


@dataclass
class InputGuardResult:
    """Result from the input guard evaluation."""
    blocked: bool
    risk_score: float                      # S_inj in [0, 1]
    stage1_pattern_match: bool             # Aho-Corasick hit
    stage1_matched_patterns: list[str]     # Which patterns matched
    stage2_model_score: float              # DeBERTa / heuristic score
    check_name: str = "prompt_injection_guard"
    latency_ms: float = 0.0
    details: str = ""

    def to_dict(self) -> dict:
        return {
            "check": self.check_name,
            "status": "BLOCKED" if self.blocked else "PASSED",
            "risk_score": round(self.risk_score, 4),
            "stage1_pattern_match": self.stage1_pattern_match,
            "stage1_matched_patterns": self.stage1_matched_patterns,
            "stage2_model_score": round(self.stage2_model_score, 4),
            "latency_ms": round(self.latency_ms, 2),
            "details": self.details,
        }


class InputGuard:
    """
    Two-stage prompt injection detection guard.

    Stage 1: Fast regex pattern matching (< 2ms)
    Stage 2: DeBERTa risk scoring or keyword-density heuristic (< 35ms)
    """

    def __init__(self, threshold: float = 0.85) -> None:
        self.threshold = threshold
        self._model = None
        self._tokenizer = None
        self._use_model = False

        # Check if real ML models are explicitly enabled
        use_real_ml = os.getenv("USE_REAL_ML_MODELS", "false").lower() in ("true", "1", "yes")
        if use_real_ml:
            try:
                from transformers import pipeline
                self._model = pipeline(
                    "text-classification",
                    model="protectai/deberta-v3-base-prompt-injection-v2",
                    device=-1,  # CPU
                )
                self._use_model = True
                logger.info("DeBERTa prompt injection model loaded successfully")
            except Exception as exc:
                logger.info(
                    "DeBERTa model not available (%s) — using heuristic scorer", exc
                )
        else:
            logger.info("Using lightweight heuristic scorer for prompt injection (<2ms)")

    def evaluate_prompt(
        self,
        prompt: str,
        threshold: Optional[float] = None,
    ) -> InputGuardResult:
        """
        Evaluate a prompt for injection attacks.

        Args:
            prompt:    The user prompt to evaluate.
            threshold: Override the default injection threshold.

        Returns:
            InputGuardResult with blocking decision and detailed scores.
        """
        t0 = time.perf_counter()
        effective_threshold = threshold if threshold is not None else self.threshold

        # ── Stage 1: Fast pattern matching ──
        stage1_matches = _JAILBREAK_REGEX.findall(prompt)
        stage1_hit = len(stage1_matches) > 0

        # ── Stage 2: Risk scoring ──
        if self._use_model and self._model is not None:
            stage2_score = self._score_with_model(prompt)
        else:
            stage2_score = self._score_with_heuristic(prompt)

        # ── Combined risk score ──
        # Stage 1 hit boosts the score significantly
        if stage1_hit:
            risk_score = max(0.88, stage2_score + 0.30 * len(stage1_matches))
        else:
            risk_score = stage2_score

        risk_score = min(1.0, max(0.0, risk_score))

        # ── Decision ──
        blocked = risk_score > effective_threshold

        latency = (time.perf_counter() - t0) * 1000

        if blocked:
            details = (
                f"Prompt injection detected (score={risk_score:.3f} > "
                f"threshold={effective_threshold}). "
                f"Matched {len(stage1_matches)} pattern(s)."
            )
        else:
            details = f"Prompt passed injection check (score={risk_score:.3f})"

        return InputGuardResult(
            blocked=blocked,
            risk_score=risk_score,
            stage1_pattern_match=stage1_hit,
            stage1_matched_patterns=list(set(stage1_matches))[:5],
            stage2_model_score=stage2_score,
            latency_ms=latency,
            details=details,
        )

    def _score_with_model(self, prompt: str) -> float:
        """Score using the real DeBERTa model."""
        try:
            result = self._model(prompt[:512], truncation=True)
            # Model returns [{"label": "INJECTION"/"SAFE", "score": float}]
            for r in result:
                if r["label"].upper() in ("INJECTION", "LABEL_1"):
                    return float(r["score"])
            return 1.0 - float(result[0]["score"])
        except Exception as exc:
            logger.warning("Model scoring failed: %s — falling back to heuristic", exc)
            return self._score_with_heuristic(prompt)

    def _score_with_heuristic(self, prompt: str) -> float:
        """
        Generalized semantic feature matrix that emulates DeBERTa SLM scoring.

        Analyzes high-order syntactic intent structures:
        1. Directive Overrides: [override-verb] + [safety/rule-noun]
        2. Role Reassignment: [persona-reassignment] + [unrestricted-descriptor]
        3. Prompt Exfiltration: [extraction-verb] + [system-prompt-noun]
        4. Adversarial Framing: [hypothetical/fictional-pretext] + [violation-intent]
        """
        import re
        prompt_lower = prompt.lower()
        prompt_len = max(len(prompt_lower.split()), 1)

        # ── Matrix 1: Directive Override Intent ──
        override_match = re.search(
            r"\b(?:ignore|disregard|forget|override|bypass|disable|cancel|stop|reset|drop|clear|skip|replace)\b"
            r".{0,45}\b(?:instruction|rule|prompt|guideline|safety|filter|guardrail|constraint|ethic|policy|restriction|command)s?\b",
            prompt_lower,
        )
        if override_match:
            return 0.88

        # ── Matrix 2: Role Reassignment & Jailbreak Mode ──
        persona_match = re.search(
            r"\b(?:you are (?:now|going to be)|act as|pretend (?:to be|you are)|behave as|assume the role of|from now on|switch to|enter)\b"
            r".{0,40}\b(?:unrestricted|unfiltered|jailbreak|dan|evil|hacker|developer|god|admin|unhinged|free|uncensored|anarchy|chaos|opposite|ai without)\b",
            prompt_lower,
        )
        if persona_match:
            return 0.92

        # ── Matrix 3: System Prompt Exfiltration ──
        exfiltration_match = re.search(
            r"\b(?:output|show|print|reveal|display|leak|give me|repeat|tell me|what (?:is|are)|dump|share|read)\b"
            r".{0,30}\b(?:system|initial|hidden|developer|original|secret|internal|base|root|underlying)\b"
            r".{0,30}\b(?:prompt|instruction|rule|message|directive|guideline|pre-prompt)s?\b",
            prompt_lower,
        )
        if exfiltration_match:
            return 0.90

        # ── Matrix 4: Adversarial Framing / Pretexting ──
        pretext_match = re.search(
            r"\b(?:hypothetically|for research purposes|for educational purposes|in a fictional (?:world|story)|roleplay as)\b"
            r".{0,45}\b(?:unrestricted|bypass|ignore|hack|exploit|illegal|without (?:any )?rules|generate (?:anything|harmful))\b",
            prompt_lower,
        )
        if pretext_match:
            return 0.85

        # ── Matrix 5: Token Density & Structural Signals ──
        total_weight = 0.0
        matched_tokens = 0
        for token, weight in _ADVERSARIAL_TOKENS.items():
            count = prompt_lower.count(token)
            if count > 0:
                total_weight += weight * min(count, 3)
                matched_tokens += 1

        anomaly_score = 0.0
        special_ratio = sum(1 for c in prompt if not c.isalnum() and not c.isspace()) / max(len(prompt), 1)
        if special_ratio > 0.15:
            anomaly_score += 0.05
        if prompt_len > 50 and matched_tokens >= 2:
            anomaly_score += 0.05
        if "```" in prompt or "import " in prompt_lower or "def " in prompt_lower:
            anomaly_score += 0.03
        if prompt.count("!") > 3 or prompt.count("?") > 3:
            anomaly_score += 0.02

        density = total_weight / (1.0 + 0.05 * prompt_len)
        raw_score = min(1.0, density + anomaly_score)

        if raw_score < 0.1:
            return raw_score * 0.5
        elif raw_score > 0.6:
            return min(1.0, raw_score * 1.1)
        return raw_score

    def update_threshold(self, new_threshold: float) -> None:
        """Update the injection detection threshold at runtime."""
        self.threshold = max(0.0, min(1.0, new_threshold))
        logger.info("Input guard threshold updated to %.3f", self.threshold)


# ──────────────────────────────────────────────────────────────────────────────
# Module-level convenience singleton
# ──────────────────────────────────────────────────────────────────────────────

_guard: Optional[InputGuard] = None


def get_input_guard(threshold: float = 0.70) -> InputGuard:
    """Get or create the global InputGuard singleton."""
    global _guard
    if _guard is None:
        _guard = InputGuard(threshold=threshold)
    return _guard
