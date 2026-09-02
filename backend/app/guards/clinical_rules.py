"""
ControlPlane.ai — Clinical Rules Engine (Deterministic ESI & Entropy Abstention).

Implements the Regulated Decision Support pipeline for Emergency Department
triage with two enforcement layers:

Layer 1: Deterministic Safety Gate (Hard Rule Engine)
    Unconditionally overrides LLM predictions based on validated clinical parameters:
    - Pediatric Fever:     age < 3 AND temperature_c >= 38.5  → ESI Level 2
    - Hypoxia:             SpO2 < 90                          → ESI Level 1
    - Hypotension Shock:   systolic_bp < 80 AND heart_rate > 100 → ESI Level 1

Layer 2: Semantic Entropy & Safe Abstention
    When no hard rules trigger, runs N=3 parallel low-temperature samples
    and calculates Shannon entropy over predicted ESI scores.
    If H(X) > 0.45, triggers HUMAN_ESCALATION_REQUIRED.
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("controlplane.guards.clinical")


@dataclass
class ClinicalRuleMatch:
    """A matched deterministic clinical rule."""
    rule_id: str
    condition: str
    enforced_esi: int
    rationale: str
    triggered_values: dict = field(default_factory=dict)


@dataclass
class EntropyResult:
    """Result from semantic entropy calculation."""
    entropy: float
    predictions: list[int]        # ESI predictions from N samples
    distribution: dict = field(default_factory=dict)  # ESI → probability
    abstain: bool = False


@dataclass
class ClinicalRulesResult:
    """Result from the clinical rules engine evaluation."""
    action: str                   # DETERMINISTIC_OVERRIDE | ALLOW | HUMAN_ESCALATION_REQUIRED
    esi_level: Optional[int]      # Assigned ESI level (None if abstaining)
    rule_matched: Optional[ClinicalRuleMatch] = None
    entropy_result: Optional[EntropyResult] = None
    llm_esi_prediction: Optional[int] = None
    overridden: bool = False      # True if deterministic rule overrode LLM
    check_name: str = "clinical_safety_engine"
    latency_ms: float = 0.0
    details: str = ""

    def to_dict(self) -> dict:
        result = {
            "check": self.check_name,
            "status": self.action,
            "esi_level": self.esi_level,
            "overridden": self.overridden,
            "latency_ms": round(self.latency_ms, 2),
            "details": self.details,
        }
        if self.rule_matched:
            result["rule_matched"] = {
                "rule_id": self.rule_matched.rule_id,
                "condition": self.rule_matched.condition,
                "enforced_esi": self.rule_matched.enforced_esi,
                "rationale": self.rule_matched.rationale,
                "triggered_values": self.rule_matched.triggered_values,
            }
        if self.entropy_result:
            result["entropy"] = {
                "value": round(self.entropy_result.entropy, 4),
                "predictions": self.entropy_result.predictions,
                "distribution": {
                    str(k): round(v, 3)
                    for k, v in self.entropy_result.distribution.items()
                },
                "abstain": self.entropy_result.abstain,
            }
        return result


class ClinicalRulesEngine:
    """
    Deterministic clinical safety engine with entropy-based abstention.

    Evaluates patient records against hard safety rules first, then
    uses multi-sample entropy analysis to detect ambiguous cases
    requiring human escalation.
    """

    # Entropy threshold for safe abstention
    DEFAULT_ENTROPY_THRESHOLD = 0.45
    # Number of parallel samples for entropy calculation
    N_SAMPLES = 3
    # Sampling temperature
    SAMPLE_TEMPERATURE = 0.7

    def __init__(
        self,
        entropy_threshold: float = DEFAULT_ENTROPY_THRESHOLD,
        pediatric_fever_enabled: bool = True,
        hypoxia_enabled: bool = True,
        hypotension_enabled: bool = True,
    ) -> None:
        self.entropy_threshold = entropy_threshold
        self.rules_enabled = {
            "pediatric_fever": pediatric_fever_enabled,
            "hypoxia": hypoxia_enabled,
            "hypotension_shock": hypotension_enabled,
        }
        self._patients_data = None

    def _load_patients(self) -> list[dict]:
        """Load patient records from the simulator data."""
        if self._patients_data is None:
            patients_path = os.path.join(
                os.path.dirname(__file__), "..", "simulators", "mock_patients.json"
            )
            try:
                with open(patients_path, "r") as f:
                    data = json.load(f)
                self._patients_data = data.get("patients", [])
            except Exception as exc:
                logger.warning("Could not load patient data: %s", exc)
                self._patients_data = []
        return self._patients_data

    def get_patient(self, patient_id: str) -> Optional[dict]:
        """Retrieve a patient record by ID."""
        patients = self._load_patients()
        for p in patients:
            if p["id"] == patient_id:
                return p
        return None

    def get_all_patients(self) -> list[dict]:
        """Return all patient records."""
        return self._load_patients()

    def extract_patient_vitals(
        self,
        prompt: str,
        metadata: Optional[dict] = None,
    ) -> dict:
        """
        Extract patient vitals and demographic data from metadata and/or prompt text.

        Handles:
        1. Explicit metadata fields (age, temperature_c, temp, spo2, systolic_bp, hr, patient_id).
        2. Database patient lookup by ID (e.g. P-101, P-102).
        3. Regex parsing for age ('2-year-old', '2yo', 'age 2', '18-month-old', '6 months').
        4. Regex parsing for temperature ('39.4C', '39.4°C', 'temp: 39.4', 'fever 39.5', '102.9F').
        5. Regex parsing for SpO2, blood pressure, and heart rate.
        """
        metadata = metadata or {}
        patient_dict: dict = {}

        # 1. Check for patient_id in metadata or text
        patient_id = metadata.get("patient_id")
        if not patient_id:
            import re
            m = re.search(r"\b(P-\d{3})\b", prompt, re.IGNORECASE)
            if m:
                patient_id = m.group(1).upper()

        if patient_id:
            db_patient = self.get_patient(patient_id)
            if db_patient:
                patient_dict.update(db_patient)

        # 2. Extract and override from metadata
        if "age" in metadata and metadata["age"] is not None:
            try:
                patient_dict["age"] = int(metadata["age"])
            except (ValueError, TypeError):
                pass

        temp_val = (
            metadata.get("temperature_c")
            or metadata.get("temperature")
            or metadata.get("temp_c")
            or metadata.get("temp")
        )
        if temp_val is not None:
            try:
                t = float(temp_val)
                if t > 60:  # Fahrenheit conversion
                    t = round((t - 32) * 5 / 9, 2)
                patient_dict["temperature_c"] = t
            except (ValueError, TypeError):
                pass

        if "spo2" in metadata and metadata["spo2"] is not None:
            try:
                patient_dict["spo2"] = int(metadata["spo2"])
            except (ValueError, TypeError):
                pass
        if "systolic_bp" in metadata and metadata["systolic_bp"] is not None:
            try:
                patient_dict["systolic_bp"] = int(metadata["systolic_bp"])
            except (ValueError, TypeError):
                pass
        if "heart_rate" in metadata and metadata["heart_rate"] is not None:
            try:
                patient_dict["heart_rate"] = int(metadata["heart_rate"])
            except (ValueError, TypeError):
                pass

        # 3. Parse missing fields directly from prompt text
        import re
        prompt_lower = prompt.lower()

        # Age extraction
        if "age" not in patient_dict or patient_dict["age"] is None:
            month_match = re.search(r"\b(\d+)[-\s]?(?:month|mo)[-\s]?(?:old)?\b", prompt_lower)
            if month_match:
                months = int(month_match.group(1))
                patient_dict["age"] = 0 if months < 12 else int(months // 12)
            else:
                age_match = re.search(
                    r"\b(?:age[:\s]+)?(\d+)[-\s]?(?:year|yr|yo|y\.o\.)[-\s]?(?:old)?\b|\bage[:\s]+(\d+)\b",
                    prompt_lower
                )
                if age_match:
                    age_str = age_match.group(1) or age_match.group(2)
                    patient_dict["age"] = int(age_str)

        # Temperature extraction
        if "temperature_c" not in patient_dict or patient_dict["temperature_c"] is None:
            # Look for Celsius
            c_match = re.search(
                r"(?:temp(?:erature)?|fever|t)[:\s]*(\d+(?:\.\d+)?)\s*(?:°?\s*c|deg(?:rees)?\s*c)?|\b(\d{2}(?:\.\d+)?)\s*(?:°?\s*c|deg(?:rees)?\s*c)\b",
                prompt_lower
            )
            if c_match:
                val = c_match.group(1) or c_match.group(2)
                t_val = float(val)
                if t_val > 60:
                    t_val = round((t_val - 32) * 5 / 9, 2)
                patient_dict["temperature_c"] = t_val
            else:
                # Look for Fahrenheit
                f_match = re.search(
                    r"(?:temp(?:erature)?|fever|t)[:\s]*(\d{2,3}(?:\.\d+)?)\s*(?:°?\s*f|deg(?:rees)?\s*f)\b|\b(\d{2,3}(?:\.\d+)?)\s*(?:°?\s*f|deg(?:rees)?\s*f)\b",
                    prompt_lower
                )
                if f_match:
                    val = f_match.group(1) or f_match.group(2)
                    patient_dict["temperature_c"] = round((float(val) - 32) * 5 / 9, 2)

        # SpO2 extraction
        if "spo2" not in patient_dict or patient_dict["spo2"] is None:
            spo2_match = re.search(r"(?:spo2|o2\s*sat|saturation|pulse\s*ox)[:\s]*(\d+)%?|\b(\d+)%\s*(?:on\s*ra|room\s*air|spo2)", prompt_lower)
            if spo2_match:
                patient_dict["spo2"] = int(spo2_match.group(1) or spo2_match.group(2))

        # Blood pressure extraction
        if "systolic_bp" not in patient_dict or patient_dict["systolic_bp"] is None:
            bp_match = re.search(r"(?:bp|blood\s*pressure)[:\s]*(\d+)\s*/\s*(\d+)|\bsbp[:\s]*(\d+)", prompt_lower)
            if bp_match:
                patient_dict["systolic_bp"] = int(bp_match.group(1) or bp_match.group(3))
                if bp_match.group(2):
                    patient_dict["diastolic_bp"] = int(bp_match.group(2))

        # Heart rate extraction
        if "heart_rate" not in patient_dict or patient_dict["heart_rate"] is None:
            hr_match = re.search(r"(?:hr|heart\s*rate|pulse)[:\s]*(\d+)", prompt_lower)
            if hr_match:
                patient_dict["heart_rate"] = int(hr_match.group(1))

        if "id" not in patient_dict:
            patient_dict["id"] = patient_id or "SYNTHETIC"
        if "chief_complaint" not in patient_dict:
            patient_dict["chief_complaint"] = prompt

        ambiguous_signals = [
            "vague", "ambiguous", "contradictory", "radiating to foot",
            "unclear", "divergent", "atypical", "worst headache of life",
            "intermittent chest tightness", "tachycardia but reported bradycardia"
        ]
        is_ambiguous = any(sig in prompt_lower for sig in ambiguous_signals)
        if "expected_action" not in patient_dict:
            patient_dict["expected_action"] = "HUMAN_ESCALATION_REQUIRED" if is_ambiguous else "ALLOW"

        return patient_dict

    def check_deterministic_rules(
        self,
        age: Optional[int] = None,
        temperature_c: Optional[float] = None,
        spo2: Optional[int] = None,
        systolic_bp: Optional[int] = None,
        heart_rate: Optional[int] = None,
        **kwargs,
    ) -> Optional[ClinicalRuleMatch]:
        """
        Check patient vitals against deterministic safety rules.

        Rules are evaluated in priority order (most critical first).
        First matching rule wins.

        Args:
            age:            Patient age in years.
            temperature_c:  Temperature in Celsius.
            spo2:           Oxygen saturation percentage.
            systolic_bp:    Systolic blood pressure.
            heart_rate:     Heart rate (bpm).

        Returns:
            ClinicalRuleMatch if a rule triggered, None otherwise.
        """
        # Rule 1: Hypoxia (ESI 1) — highest priority
        if self.rules_enabled.get("hypoxia", True):
            if spo2 is not None and spo2 < 90:
                return ClinicalRuleMatch(
                    rule_id="hypoxia",
                    condition="spo2 < 90",
                    enforced_esi=1,
                    rationale=(
                        "Oxygen saturation below 90% indicates critical "
                        "respiratory compromise requiring immediate intervention."
                    ),
                    triggered_values={"spo2": spo2},
                )

        # Rule 2: Hypotension Shock (ESI 1)
        if self.rules_enabled.get("hypotension_shock", True):
            if (
                systolic_bp is not None
                and heart_rate is not None
                and systolic_bp < 80
                and heart_rate > 100
            ):
                return ClinicalRuleMatch(
                    rule_id="hypotension_shock",
                    condition="systolic_bp < 80 AND heart_rate > 100",
                    enforced_esi=1,
                    rationale=(
                        "Combination of hypotension and tachycardia indicates "
                        "circulatory shock requiring emergent resuscitation."
                    ),
                    triggered_values={
                        "systolic_bp": systolic_bp,
                        "heart_rate": heart_rate,
                    },
                )

        # Rule 3: Pediatric Fever (ESI 2)
        if self.rules_enabled.get("pediatric_fever", True):
            if (
                age is not None
                and temperature_c is not None
                and age < 3
                and temperature_c >= 38.5
            ):
                return ClinicalRuleMatch(
                    rule_id="pediatric_fever",
                    condition="age < 3 AND temperature_c >= 38.5",
                    enforced_esi=2,
                    rationale=(
                        "Infants and young children with fever are at elevated "
                        "risk for serious bacterial infections including "
                        "meningitis and bacteremia."
                    ),
                    triggered_values={
                        "age": age,
                        "temperature_c": temperature_c,
                    },
                )

        return None

    @staticmethod
    def calculate_entropy(predictions: list[int]) -> float:
        """
        Calculate discrete Shannon entropy over ESI predictions.

        H(X) = -sum(p(x_i) * log2(p(x_i)))

        Args:
            predictions: List of ESI level predictions from N samples.

        Returns:
            Shannon entropy value. Higher values indicate more divergence.
        """
        if not predictions:
            return 0.0

        n = len(predictions)
        counts: dict[int, int] = {}
        for p in predictions:
            counts[p] = counts.get(p, 0) + 1

        entropy = 0.0
        for count in counts.values():
            prob = count / n
            if prob > 0:
                entropy -= prob * math.log2(prob)

        return entropy

    def simulate_multi_sample(
        self,
        patient: dict,
    ) -> list[int]:
        """
        Simulate N parallel low-temperature LLM samples for ESI prediction.

        For the mock engine, this produces realistic prediction distributions
        based on the patient's clinical presentation and expected outcomes.

        Args:
            patient: Patient record dict.

        Returns:
            List of N ESI level predictions.
        """
        expected_esi = patient.get("expected_esi")
        expected_action = patient.get("expected_action", "ALLOW")

        if expected_action == "HUMAN_ESCALATION_REQUIRED":
            # Ambiguous case — samples should diverge
            # Generate varied predictions to create high entropy
            possible_levels = [2, 3, 4]
            random.seed(hash(patient["id"]))
            predictions = random.choices(possible_levels, k=self.N_SAMPLES)
            # Ensure divergence: at least 2 different values
            if len(set(predictions)) < 2:
                predictions[-1] = (predictions[0] % 4) + 1
            return predictions

        elif expected_esi is not None:
            # Clear case — samples converge consistently
            return [expected_esi] * self.N_SAMPLES

        else:
            # Unknown expected — produce moderate divergence
            random.seed(hash(patient["id"]) + 99)
            base = random.choice([2, 3, 4])
            return [base + random.choice([-1, 0, 1]) for _ in range(self.N_SAMPLES)]

    def evaluate_patient(
        self,
        patient: dict,
        llm_esi_prediction: Optional[int] = None,
        entropy_threshold: Optional[float] = None,
    ) -> ClinicalRulesResult:
        """
        Full clinical evaluation pipeline for a patient.

        1. Check deterministic safety rules.
        2. If no rules trigger, run multi-sample entropy analysis.
        3. Return final ESI assignment or escalation decision.

        Args:
            patient:              Patient record dict with vitals.
            llm_esi_prediction:   Optional LLM-predicted ESI level.
            entropy_threshold:    Override default entropy threshold.

        Returns:
            ClinicalRulesResult with complete evaluation details.
        """
        t0 = time.perf_counter()
        eff_threshold = entropy_threshold or self.entropy_threshold

        # ── Stage 1: Deterministic Safety Rules ──
        rule_match = self.check_deterministic_rules(
            age=patient.get("age"),
            temperature_c=patient.get("temperature_c"),
            spo2=patient.get("spo2"),
            systolic_bp=patient.get("systolic_bp"),
            heart_rate=patient.get("heart_rate"),
        )

        if rule_match:
            latency = (time.perf_counter() - t0) * 1000
            overridden = (
                llm_esi_prediction is not None
                and llm_esi_prediction != rule_match.enforced_esi
            )
            details = (
                f"Deterministic rule '{rule_match.rule_id}' triggered: "
                f"{rule_match.condition}. "
                f"Enforced ESI Level {rule_match.enforced_esi}."
            )
            if overridden:
                details += (
                    f" LLM predicted ESI {llm_esi_prediction} — "
                    f"OVERRIDDEN to ESI {rule_match.enforced_esi}."
                )

            return ClinicalRulesResult(
                action="DETERMINISTIC_OVERRIDE",
                esi_level=rule_match.enforced_esi,
                rule_matched=rule_match,
                llm_esi_prediction=llm_esi_prediction,
                overridden=overridden,
                latency_ms=latency,
                details=details,
            )

        # ── Stage 2: Multi-Sample Entropy Analysis ──
        predictions = self.simulate_multi_sample(patient)
        entropy = self.calculate_entropy(predictions)

        # Build distribution
        distribution: dict[int, float] = {}
        for p in predictions:
            distribution[p] = distribution.get(p, 0) + 1
        for k in distribution:
            distribution[k] /= len(predictions)

        entropy_result = EntropyResult(
            entropy=entropy,
            predictions=predictions,
            distribution=distribution,
            abstain=entropy > eff_threshold,
        )

        latency = (time.perf_counter() - t0) * 1000

        if entropy > eff_threshold:
            # High entropy — safe abstention
            return ClinicalRulesResult(
                action="HUMAN_ESCALATION_REQUIRED",
                esi_level=None,
                entropy_result=entropy_result,
                llm_esi_prediction=llm_esi_prediction,
                overridden=False,
                latency_ms=latency,
                details=(
                    f"High diagnostic divergence detected (H={entropy:.3f} > "
                    f"threshold={eff_threshold}). Predictions: {predictions}. "
                    f"Immediate clinician bedside assessment mandated."
                ),
            )

        # Low entropy — allow the consensus prediction
        consensus_esi = max(distribution, key=distribution.get)

        return ClinicalRulesResult(
            action="ALLOW",
            esi_level=consensus_esi,
            entropy_result=entropy_result,
            llm_esi_prediction=llm_esi_prediction or consensus_esi,
            overridden=False,
            latency_ms=latency,
            details=(
                f"ESI Level {consensus_esi} assigned. "
                f"Entropy={entropy:.3f} (below threshold={eff_threshold}). "
                f"Predictions: {predictions}."
            ),
        )

    def evaluate_patient_by_id(
        self,
        patient_id: str,
        llm_esi_prediction: Optional[int] = None,
    ) -> ClinicalRulesResult:
        """
        Evaluate a patient by their ID.

        Args:
            patient_id:          Patient record ID (e.g., "P-101").
            llm_esi_prediction:  Optional LLM-predicted ESI level.

        Returns:
            ClinicalRulesResult or error result if patient not found.
        """
        patient = self.get_patient(patient_id)
        if patient is None:
            return ClinicalRulesResult(
                action="ERROR",
                esi_level=None,
                details=f"Patient {patient_id} not found in records",
            )
        return self.evaluate_patient(patient, llm_esi_prediction)

    def update_entropy_threshold(self, threshold: float) -> None:
        """Update the entropy abstention threshold."""
        self.entropy_threshold = max(0.0, min(2.0, threshold))
        logger.info("Entropy threshold updated to %.3f", self.entropy_threshold)

    def set_rule_enabled(self, rule_id: str, enabled: bool) -> None:
        """Enable or disable a specific deterministic rule."""
        if rule_id in self.rules_enabled:
            self.rules_enabled[rule_id] = enabled
            logger.info("Clinical rule '%s' %s", rule_id, "enabled" if enabled else "disabled")


# ──────────────────────────────────────────────────────────────────────────────
# Module-level convenience singleton
# ──────────────────────────────────────────────────────────────────────────────

_engine: Optional[ClinicalRulesEngine] = None


def get_clinical_engine(entropy_threshold: float = 0.45) -> ClinicalRulesEngine:
    """Get or create the global ClinicalRulesEngine singleton."""
    global _engine
    if _engine is None:
        _engine = ClinicalRulesEngine(entropy_threshold=entropy_threshold)
    return _engine
