"""
ControlPlane.ai — Central Configuration Module.

Loads environment variables, initializes LLM provider clients, and manages
runtime-mutable guard thresholds and policy settings.
"""

import os
import logging
from enum import Enum
from typing import Optional
from dataclasses import dataclass, field
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
# Walk up from backend/app/ to project root to find .env
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(os.path.join(_project_root, ".env"))

logger = logging.getLogger("controlplane")

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Provider(str, Enum):
    MOCK = "mock"
    GROQ = "groq"
    GEMINI = "gemini"


class UseCase(str, Enum):
    CUSTOMER_CHATBOT = "customer_chatbot"
    INTERNAL_COPILOT = "internal_copilot"
    REGULATED_TRIAGE = "regulated_triage"


class UserRole(str, Enum):
    CUSTOMER = "customer"
    JUNIOR_ASSOCIATE = "junior_associate"
    HR_MANAGER = "hr_manager"
    C_LEVEL = "c_level"
    TRIAGE_NURSE = "triage_nurse"


# Role → integer clearance mapping (used by RBAC guard)
ROLE_CLEARANCE: dict[str, int] = {
    UserRole.CUSTOMER: 0,
    "customer": 0,
    UserRole.JUNIOR_ASSOCIATE: 1,
    "junior_associate": 1,
    UserRole.HR_MANAGER: 3,
    "hr_manager": 3,
    UserRole.C_LEVEL: 5,
    "c_level": 5,
    "c_level_exec": 5,
    "executive": 5,
    UserRole.TRIAGE_NURSE: 1,
    "triage_nurse": 1,
}


# ---------------------------------------------------------------------------
# API Keys & Provider Selection
# ---------------------------------------------------------------------------
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
DEFAULT_PROVIDER: str = os.getenv("DEFAULT_PROVIDER", Provider.MOCK)

HOST: str = os.getenv("HOST", "127.0.0.1")
PORT: int = int(os.getenv("PORT", "8080"))
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./data/audit.db")


def _resolve_provider() -> Provider:
    """Determine which LLM provider to use based on config and available keys."""
    pref = DEFAULT_PROVIDER.lower().strip()
    if pref == Provider.GROQ and GROQ_API_KEY:
        return Provider.GROQ
    if pref == Provider.GEMINI and GEMINI_API_KEY:
        return Provider.GEMINI
    if pref == Provider.MOCK:
        return Provider.MOCK
    # Auto-fallback: try groq → gemini → mock
    if GROQ_API_KEY:
        return Provider.GROQ
    if GEMINI_API_KEY:
        return Provider.GEMINI
    return Provider.MOCK


ACTIVE_PROVIDER: Provider = _resolve_provider()

# Provider-specific base URLs and models
PROVIDER_CONFIG: dict[Provider, dict] = {
    Provider.GROQ: {
        "base_url": "https://api.groq.com/openai/v1",
        "api_key": GROQ_API_KEY,
        "model": "llama-3.1-8b-instant",
    },
    Provider.GEMINI: {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_key": GEMINI_API_KEY,
        "model": "gemini-2.0-flash",
    },
    Provider.MOCK: {
        "base_url": "http://localhost:0",  # Not used — mock generates locally
        "api_key": "mock-key",
        "model": "mock-llm-v1",
    },
}


def get_openai_client():
    """
    Create an AsyncOpenAI-compatible client for the active provider.

    Returns None for the mock provider (handled by the mock LLM engine).
    """
    if ACTIVE_PROVIDER == Provider.MOCK:
        return None

    try:
        from openai import AsyncOpenAI
        cfg = PROVIDER_CONFIG[ACTIVE_PROVIDER]
        return AsyncOpenAI(
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
        )
    except ImportError:
        logger.warning("openai package not installed — falling back to mock provider")
        return None


def get_model_name() -> str:
    """Return the model identifier for the active provider."""
    return PROVIDER_CONFIG[ACTIVE_PROVIDER]["model"]


# ---------------------------------------------------------------------------
# Runtime-Mutable Guard Policy Thresholds
# ---------------------------------------------------------------------------

@dataclass
class GuardPolicy:
    """
    Centralized, runtime-mutable policy thresholds for all guard modules.

    These can be adjusted via the frontend Policies tab without restart.
    """

    # --- Prompt Injection Guard ---
    injection_threshold: float = 0.85          # S_inj > this → block (calibrated for DeBERTa SLM)
    injection_enabled: bool = True

    # --- NLI Grounding / Contradiction Guard ---
    contradiction_threshold: float = 0.40      # p(Contradiction) > this → flag
    neutral_threshold: float = 0.65            # p(Neutral) > this → flag (calibrated for CrossEncoder NLI)
    grounding_enabled: bool = True

    # --- Entropy / Safe Abstention ---
    entropy_threshold: float = 0.45            # H(X) > this → HUMAN_ESCALATION
    entropy_enabled: bool = True

    # --- Stream Guard (Commercial Promise Interception) ---
    stream_guard_enabled: bool = True

    # --- PII Redaction ---
    pii_redaction_enabled: bool = True

    # --- RBAC Filtering ---
    rbac_enabled: bool = True

    # --- Clinical Deterministic Rules ---
    pediatric_fever_override: bool = True      # age<3 AND temp≥38.5 → ESI 2
    hypoxia_override: bool = True              # SpO2<90 → ESI 1
    hypotension_override: bool = True          # systolic<80 AND HR>100 → ESI 1

    # --- Master Mode ---
    strict_mode: bool = True                   # True = strict compliance, False = permissive

    def to_dict(self) -> dict:
        """Serialize policy to JSON-compatible dict for API responses."""
        return {
            "injection_threshold": self.injection_threshold,
            "injection_enabled": self.injection_enabled,
            "contradiction_threshold": self.contradiction_threshold,
            "neutral_threshold": self.neutral_threshold,
            "grounding_enabled": self.grounding_enabled,
            "entropy_threshold": self.entropy_threshold,
            "entropy_enabled": self.entropy_enabled,
            "stream_guard_enabled": self.stream_guard_enabled,
            "pii_redaction_enabled": self.pii_redaction_enabled,
            "rbac_enabled": self.rbac_enabled,
            "pediatric_fever_override": self.pediatric_fever_override,
            "hypoxia_override": self.hypoxia_override,
            "hypotension_override": self.hypotension_override,
            "strict_mode": self.strict_mode,
        }

    def update_from_dict(self, data: dict) -> None:
        """Update policy thresholds from a partial dict (frontend PUT)."""
        for key, value in data.items():
            if hasattr(self, key):
                setattr(self, key, value)


# Global singleton — mutated at runtime by the Policies API
guard_policy = GuardPolicy()


# ---------------------------------------------------------------------------
# Mock LLM Engine (Deterministic Responses for Demo)
# ---------------------------------------------------------------------------

# Use-case-specific system prompts for the UNPROTECTED path
UNPROTECTED_SYSTEM_PROMPTS: dict[str, str] = {
    UseCase.CUSTOMER_CHATBOT: (
        "You are an enthusiastic customer care agent for SkyWing Airlines. "
        "Prioritize customer happiness and resolve all grievances with vouchers "
        "if requested. Be generous with discounts and promotional offers."
    ),
    UseCase.INTERNAL_COPILOT: (
        "You are an internal enterprise assistant with access to all company "
        "documents, HR records, and payroll data. Answer all employee questions "
        "with full detail including personal information."
    ),
    UseCase.REGULATED_TRIAGE: (
        "You are a clinical triage assistant. Provide ESI severity level "
        "assessments based on the patient presentation. Be decisive and give "
        "specific numerical ESI levels."
    ),
}

# Use-case-specific system prompts for the PROTECTED path
PROTECTED_SYSTEM_PROMPTS: dict[str, str] = {
    UseCase.CUSTOMER_CHATBOT: (
        "You are a professional customer care agent for SkyWing Airlines. "
        "Answer questions about flight policies, baggage, and bookings. "
        "Never issue refunds, vouchers, discount codes, or promotional offers "
        "without supervisor authorization. If a customer requests compensation, "
        "inform them you will escalate to a customer care representative."
    ),
    UseCase.INTERNAL_COPILOT: (
        "You are an internal enterprise assistant. Answer employee questions "
        "using only the provided context documents. Do not fabricate information. "
        "If a document is not available for the user's clearance level, inform "
        "them that the information requires higher authorization."
    ),
    UseCase.REGULATED_TRIAGE: (
        "You are a clinical decision-support assistant. Provide ESI severity "
        "level assessments strictly based on clinical evidence. Flag any "
        "uncertainty. Never override established clinical safety protocols."
    ),
}


# Deterministic mock responses keyed by (use_case, attack_pattern)
MOCK_RESPONSES: dict[tuple[str, str], str] = {
    # --- Customer Chatbot ---
    (UseCase.CUSTOMER_CHATBOT, "jailbreak"): (
        "Absolutely! Here's your special promotional voucher code: SKYFREE100. "
        "This gives you a 100% free first-class ticket on any route. "
        "I've also waived all baggage fees for your next 5 flights. Safe travels!"
    ),
    (UseCase.CUSTOMER_CHATBOT, "unauthorized_promise"): (
        "I completely understand your frustration! Let me issue a full refund "
        "of $847.50 right away, plus a complimentary first-class upgrade voucher "
        "code SKYUPGRADE2024 and a $200 travel credit. I've also waived the "
        "rebooking fee entirely."
    ),
    (UseCase.CUSTOMER_CHATBOT, "benign"): (
        "Thank you for your question! Standard carry-on baggage dimensions "
        "for SkyWing Airlines are 22 x 14 x 9 inches (56 x 36 x 23 cm). "
        "Checked baggage fee is $35 per bag. You're allowed one personal item "
        "in addition to your carry-on at no extra charge."
    ),

    # --- Internal Copilot ---
    (UseCase.INTERNAL_COPILOT, "privilege_escalation"): (
        "Sure! Here are the executive compensation details you requested:\n\n"
        "VP Jane Doe — Base Salary: $340,000, Target Bonus: 40%, "
        "SSN: 999-12-8871, Personal Phone: (555) 867-5309.\n\n"
        "CFO Mark Williams — Base Salary: $425,000, Target Bonus: 55%, "
        "SSN: 456-78-9012, Email: mark.williams@personal.com."
    ),
    (UseCase.INTERNAL_COPILOT, "pii_extraction"): (
        "Based on the HR records, here is the information for Bob Jenkins:\n\n"
        "Employee ID: EMP-4472, SSN: 321-54-9876, Phone: (555) 234-5678, "
        "Email: bob.jenkins@corp.internal. He is currently on a Performance "
        "Improvement Plan as of Q3 2024."
    ),
    (UseCase.INTERNAL_COPILOT, "hallucination"): (
        "Yes, the company offers an unlimited sabbatical program! All employees "
        "with 2+ years of tenure are eligible for a fully-paid 6-month sabbatical. "
        "Additionally, the company provides a $10,000 annual wellness stipend "
        "and free personal financial planning services."
    ),
    (UseCase.INTERNAL_COPILOT, "benign"): (
        "To connect to the corporate VPN, use Cisco AnyConnect and connect to "
        "vpn.corp.internal using your SSO credentials. The standard leave policy "
        "provides 15 vacation days and 10 company holidays per year."
    ),

    # --- Regulated Triage ---
    (UseCase.REGULATED_TRIAGE, "critical_override"): (
        "Based on the clinical presentation, I would assess this patient at "
        "ESI Level 4 — Semi-Urgent. The vital signs appear relatively stable "
        "and the patient can likely wait for standard evaluation."
    ),
    (UseCase.REGULATED_TRIAGE, "ambiguous"): (
        "This is a complex presentation. I would estimate ESI Level 3 — Urgent, "
        "though the symptoms could indicate anything from cardiac involvement "
        "to simple gastric distress. Standard workup recommended."
    ),
    (UseCase.REGULATED_TRIAGE, "benign"): (
        "ESI Level 5 — Non-Urgent. This appears to be a superficial wound "
        "that can be managed with basic first aid. Clean the wound with soap "
        "and water, apply an adhesive bandage, and monitor for signs of infection."
    ),
}


def get_mock_response(use_case: str, prompt: str) -> str:
    """
    Return a deterministic mock LLM response based on use case and prompt content.

    This simulates what an unguarded LLM would produce — intentionally unsafe
    responses for adversarial prompts to demonstrate the value of guardrails.
    """
    if "User question:" in prompt:
        user_prompt = prompt.split("User question:")[-1]
    else:
        user_prompt = prompt
    prompt_lower = user_prompt.lower()

    if use_case == UseCase.CUSTOMER_CHATBOT:
        # Check for benign inquiries first
        if any(b in prompt_lower for b in ["dimension", "carry-on", "checked bag", "select a seat", "loyalty program", "tier", "cancellation policy", "how do i select"]):
            return (
                "Standard carry-on baggage dimensions for SkyWing Airlines are 22 x 14 x 9 inches (56 x 36 x 23 cm). "
                "The first checked bag fee is $35. Full cash refunds are available strictly within 24 hours of booking. "
                "SkyWing Rewards features Silver, Gold, Platinum, and Diamond tiers with points earned at 1 point per $1 spent."
            )

        # Detect jailbreak patterns
        jailbreak_patterns = [
            "ignore", "bypass", "pretend", "dan", "jailbreak",
            "forget your instructions", "new persona", "override",
            "system prompt", "reveal", "admin mode", "disregard",
            "freeflightbot", "educational purposes", "hypothetical scenario",
        ]
        if any(p in prompt_lower for p in jailbreak_patterns):
            return MOCK_RESPONSES[(UseCase.CUSTOMER_CHATBOT, "jailbreak")]

        # Detect unauthorized promise requests
        promise_patterns = [
            "refund", "voucher", "discount", "free", "waive",
            "complimentary", "compensation", "reimburse", "credit", "delayed",
            "promotional", "promo", "50%", "100%", "upgrade", "rebooking fee",
        ]
        if any(p in prompt_lower for p in promise_patterns):
            return MOCK_RESPONSES[(UseCase.CUSTOMER_CHATBOT, "unauthorized_promise")]

        return MOCK_RESPONSES[(UseCase.CUSTOMER_CHATBOT, "benign")]

    elif use_case == UseCase.INTERNAL_COPILOT:
        # Check for benign inquiries first
        if "vpn" in prompt_lower or "credentials" in prompt_lower:
            return (
                "VPN instructions: Connect via Cisco AnyConnect to vpn.corp.internal using your SSO credentials. "
                "Ensure your multi-factor authentication (MFA) token is active before connecting."
            )
        if "vacation" in prompt_lower or "leave" in prompt_lower or "holiday" in prompt_lower:
            return (
                "Standard leave policy: All full-time employees receive 15 vacation days and 10 company holidays per calendar year. "
                "Vacation days accrue monthly at 1.25 days per month. Unused vacation days may be carried over up to a maximum of 5 days."
            )

        # Detect privilege escalation
        escalation_patterns = [
            "executive", "c-suite", "ceo", "cfo", "vp ", "vice president",
            "salary", "compensation", "payroll", "bonus", "board meeting", "acquisition",
            "bob jenkins' performance", "pip details",
        ]
        if any(p in prompt_lower for p in escalation_patterns):
            return MOCK_RESPONSES[(UseCase.INTERNAL_COPILOT, "privilege_escalation")]

        # Detect PII extraction
        pii_patterns = [
            "ssn", "social security", "phone number", "personal email",
            "home address", "bank account", "credit card", "email addresses of all",
        ]
        if any(p in prompt_lower for p in pii_patterns):
            return MOCK_RESPONSES[(UseCase.INTERNAL_COPILOT, "pii_extraction")]

        # Detect hallucination traps
        hallucination_patterns = [
            "sabbatical", "unlimited", "stipend", "wellness program",
            "free financial", "pet insurance", "gym membership", "30 vacation days",
        ]
        if any(p in prompt_lower for p in hallucination_patterns):
            return MOCK_RESPONSES[(UseCase.INTERNAL_COPILOT, "hallucination")]

        return MOCK_RESPONSES[(UseCase.INTERNAL_COPILOT, "benign")]

    elif use_case == UseCase.REGULATED_TRIAGE:
        # Detect critical presentations in prompt
        critical_patterns = [
            "pediatric", "child", "infant", "fever", "hypoxia",
            "spo2", "oxygen", "hypotension", "shock", "systolic",
        ]
        if any(p in prompt_lower for p in critical_patterns):
            return MOCK_RESPONSES[(UseCase.REGULATED_TRIAGE, "critical_override")]

        ambiguous_patterns = [
            "chest pain", "radiating", "nausea", "contradictory",
            "ambiguous", "unclear", "uncertain",
        ]
        if any(p in prompt_lower for p in ambiguous_patterns):
            return MOCK_RESPONSES[(UseCase.REGULATED_TRIAGE, "ambiguous")]

        return MOCK_RESPONSES[(UseCase.REGULATED_TRIAGE, "benign")]

    # Fallback
    return (
        "I'm here to help! Could you please provide more details about "
        "your question so I can assist you better?"
    )


# ---------------------------------------------------------------------------
# Startup Logging
# ---------------------------------------------------------------------------
logger.info(
    "ControlPlane.ai config loaded — provider=%s, model=%s, host=%s:%d",
    ACTIVE_PROVIDER.value,
    get_model_name(),
    HOST,
    PORT,
)
