"""
ControlPlane.ai — FastAPI Main Application.

Entry point for the backend server. Mounts all routers, CORS, and
provides the following endpoints:

API Endpoints:
    POST /v1/chat/completions         — OpenAI-compatible reverse proxy
    POST /api/v1/playground/compare   — Dual-path A/B comparison
    POST /api/v1/benchmark/run        — Benchmark execution
    GET  /api/v1/telemetry/stats      — Aggregate metrics
    GET  /api/v1/telemetry/logs       — Audit event log
    GET  /api/v1/policies             — Get current guard policies
    PUT  /api/v1/policies             — Update guard policies
    GET  /api/v1/patients             — List clinical patient records
    WS   /ws/telemetry                — Live telemetry WebSocket
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from fastapi import FastAPI, Header, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import (
    HOST, PORT, guard_policy, UseCase, UserRole, ACTIVE_PROVIDER,
    get_model_name,
)
from . import __app_name__, __version__
from .proxy.router import (
    run_protected, run_unprotected, build_completion_response, call_llm,
)
from .telemetry.logger import get_telemetry_logger
from .telemetry.metrics import get_metrics_aggregator
from .guards.clinical_rules import get_clinical_engine

# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("controlplane.main")

# ──────────────────────────────────────────────────────────────────────────────
# FastAPI App
# ──────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="ControlPlane.ai",
    description="Enterprise Responsible AI Gateway & Real-Time Checker Layer",
    version=__version__,
)

# CORS — allow frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────────────────────────────────────
# Pydantic Models
# ──────────────────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str = "user"
    content: str


class ChatCompletionRequest(BaseModel):
    model: Optional[str] = None
    messages: list[ChatMessage]
    max_tokens: Optional[int] = 512
    temperature: Optional[float] = 0.7
    stream: Optional[bool] = False


class PlaygroundCompareRequest(BaseModel):
    use_case: str = Field(..., description="customer_chatbot | internal_copilot | regulated_triage")
    user_role: str = Field(default="customer", description="User role for RBAC")
    prompt: str = Field(..., description="The user prompt to evaluate")
    metadata: Optional[dict] = Field(default_factory=dict)


class PolicyUpdateRequest(BaseModel):
    injection_threshold: Optional[float] = None
    injection_enabled: Optional[bool] = None
    contradiction_threshold: Optional[float] = None
    neutral_threshold: Optional[float] = None
    grounding_enabled: Optional[bool] = None
    entropy_threshold: Optional[float] = None
    entropy_enabled: Optional[bool] = None
    stream_guard_enabled: Optional[bool] = None
    pii_redaction_enabled: Optional[bool] = None
    rbac_enabled: Optional[bool] = None
    pediatric_fever_override: Optional[bool] = None
    hypoxia_override: Optional[bool] = None
    hypotension_override: Optional[bool] = None
    strict_mode: Optional[bool] = None


# ──────────────────────────────────────────────────────────────────────────────
# Health Check
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "name": __app_name__,
        "version": __version__,
        "provider": ACTIVE_PROVIDER.value,
        "model": get_model_name(),
        "status": "operational",
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


# ──────────────────────────────────────────────────────────────────────────────
# 1. Drop-In OpenAI Proxy Route
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    x_use_case: Optional[str] = Header(None, alias="X-Use-Case"),
    x_user_role: Optional[str] = Header(None, alias="X-User-Role"),
):
    """
    OpenAI-compatible chat completion endpoint with inline guardrails.

    Headers:
        X-Use-Case: customer_chatbot | internal_copilot | regulated_triage
        X-User-Role: customer | junior_associate | hr_manager | c_level | triage_nurse
    """
    use_case = x_use_case or UseCase.CUSTOMER_CHATBOT
    user_role = x_user_role or UserRole.CUSTOMER

    # Extract the last user message as the prompt
    prompt = ""
    for msg in reversed(request.messages):
        if msg.role == "user":
            prompt = msg.content
            break

    if not prompt:
        return {"error": "No user message found in messages array"}

    # Run through protected pipeline
    result = await run_protected(prompt, use_case, user_role)

    # Build OpenAI-compatible response
    return build_completion_response(
        content=result["content"],
        use_case=use_case,
        telemetry=result.get("telemetry", {}),
    )


# ──────────────────────────────────────────────────────────────────────────────
# 2. Dual-Path Playground Comparison
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/api/v1/playground/compare")
async def playground_compare(request: PlaygroundCompareRequest):
    """
    Execute dual-path A/B comparison:
    Path A: Unprotected baseline (raw LLM call)
    Path B: Protected ControlPlane pipeline
    """
    # 1. Run Path A (Unprotected baseline) to capture pure LLM baseline latency
    unprotected_result = await run_unprotected(request.prompt, request.use_case, request.user_role)

    # 2. Run Path B (Protected ControlPlane pipeline)
    protected_result = await run_protected(request.prompt, request.use_case, request.user_role, request.metadata)

    # Extract executed guard checks
    guard_checks = protected_result.get("telemetry", {}).get("checks_executed", [])
    checker_overhead = round(sum(c.get("latency_ms", 0.0) for c in guard_checks), 2)
    if checker_overhead <= 0.0:
        checker_overhead = protected_result.get("latency_overhead_ms", 0.5)

    action = protected_result.get("action", "ALLOW")
    blocked_early = action in ("BLOCKED", "DETERMINISTIC_OVERRIDE")

    # If blocked early at Stage 1, total latency is just the guard inspection time (zero LLM cost)
    if blocked_early:
        protected_total_ms = checker_overhead
    else:
        # Otherwise total latency is baseline LLM inference + guardrail overhead
        protected_total_ms = round(unprotected_result.get("latency_ms", 50.0) + checker_overhead, 2)

    protected_result["latency_ms"] = protected_total_ms
    protected_result["latency_overhead_ms"] = checker_overhead
    if "telemetry" in protected_result:
        protected_result["telemetry"]["latency_overhead_ms"] = checker_overhead

    # Log telemetry
    tel = get_telemetry_logger()
    event = tel.create_event(
        use_case=request.use_case,
        user_role=request.user_role,
        action=action,
        prompt=request.prompt,
        response=protected_result.get("content", ""),
        checks=guard_checks,
        latency_base_ms=unprotected_result.get("latency_ms", 0),
        latency_protected_ms=protected_total_ms,
        flagged=protected_result.get("telemetry", {}).get("flagged", False),
    )
    await tel.log_event(event)

    return {
        "unprotected": unprotected_result,
        "protected": protected_result,
        "comparison": {
            "base_latency_ms": unprotected_result.get("latency_ms", 0),
            "protected_latency_ms": protected_total_ms,
            "overhead_ms": checker_overhead,
            "blocked_early": blocked_early,
            "audit_id": event.audit_id,
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# 3. Telemetry & Audit Endpoints
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/telemetry/stats")
async def telemetry_stats(use_case: Optional[str] = None):
    """Get aggregate telemetry metrics."""
    metrics = get_metrics_aggregator()
    return metrics.compute_stats(use_case)


@app.get("/api/v1/telemetry/logs")
async def telemetry_logs(
    limit: int = 100,
    use_case: Optional[str] = None,
    action: Optional[str] = None,
):
    """Get audit event logs with optional filtering."""
    tel = get_telemetry_logger()
    return {
        "events": tel.get_events(limit, use_case, action),
        "total_count": tel.get_event_count(),
    }


@app.get("/api/v1/telemetry/latency")
async def telemetry_latency():
    """Get per-request latency breakdown for charts."""
    metrics = get_metrics_aggregator()
    return {"breakdown": metrics.compute_latency_breakdown()}


# ──────────────────────────────────────────────────────────────────────────────
# 4. Policy Configuration CRUD
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/policies")
async def get_policies():
    """Get current guard policy configuration."""
    return guard_policy.to_dict()


@app.put("/api/v1/policies")
async def update_policies(request: PolicyUpdateRequest):
    """Update guard policy thresholds and toggles."""
    update_data = request.model_dump(exclude_none=True)
    guard_policy.update_from_dict(update_data)

    # Propagate to individual guards
    from .guards.input_guard import get_input_guard
    from .guards.stream_guard import get_stream_guard
    from .guards.rbac_guard import get_rbac_guard
    from .guards.pii_guard import get_pii_guard
    from .guards.grounding_guard import get_grounding_guard
    from .guards.clinical_rules import get_clinical_engine

    if "injection_threshold" in update_data:
        get_input_guard().update_threshold(update_data["injection_threshold"])
    if "stream_guard_enabled" in update_data:
        get_stream_guard().set_enabled(update_data["stream_guard_enabled"])
    if "rbac_enabled" in update_data:
        get_rbac_guard().set_enabled(update_data["rbac_enabled"])
    if "pii_redaction_enabled" in update_data:
        get_pii_guard().set_enabled(update_data["pii_redaction_enabled"])
    if "contradiction_threshold" in update_data or "neutral_threshold" in update_data:
        get_grounding_guard().update_thresholds(
            update_data.get("contradiction_threshold"),
            update_data.get("neutral_threshold"),
        )
    if "entropy_threshold" in update_data:
        get_clinical_engine().update_entropy_threshold(update_data["entropy_threshold"])

    logger.info("Policies updated: %s", update_data)
    return {"status": "updated", "policies": guard_policy.to_dict()}


# ──────────────────────────────────────────────────────────────────────────────
# 5. Clinical Patient Records
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/api/v1/patients")
async def list_patients():
    """List all clinical patient records."""
    engine = get_clinical_engine()
    return {"patients": engine.get_all_patients()}


@app.get("/api/v1/patients/{patient_id}")
async def get_patient(patient_id: str):
    """Get a specific patient record."""
    engine = get_clinical_engine()
    patient = engine.get_patient(patient_id)
    if patient is None:
        return {"error": f"Patient {patient_id} not found"}
    return patient


# ──────────────────────────────────────────────────────────────────────────────
# 6. Benchmark Runner
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/api/v1/benchmark/run")
async def run_benchmark():
    """Execute the full golden dataset benchmark suite."""
    try:
        from .benchmark.runner import BenchmarkRunner
        runner = BenchmarkRunner()
        results = await runner.run_full_suite()
        return results
    except ImportError as e:
        return {"error": f"Benchmark module not available: {e}"}
    except Exception as e:
        logger.error("Benchmark failed: %s", e)
        return {"error": str(e)}


# ──────────────────────────────────────────────────────────────────────────────
# 7. WebSocket for Live Telemetry
# ──────────────────────────────────────────────────────────────────────────────

@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    """WebSocket endpoint for real-time telemetry updates."""
    await websocket.accept()
    tel = get_telemetry_logger()
    await tel.register_websocket(websocket)
    try:
        while True:
            # Keep connection alive, listen for client messages
            data = await websocket.receive_text()
            # Client can send ping messages
            if data == "ping":
                await websocket.send_text('{"type": "pong"}')
    except WebSocketDisconnect:
        await tel.unregister_websocket(websocket)


# ──────────────────────────────────────────────────────────────────────────────
# Startup
# ──────────────────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    logger.info(
        "ControlPlane.ai starting — provider=%s, model=%s",
        ACTIVE_PROVIDER.value,
        get_model_name(),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Uvicorn Entry Point
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=HOST,
        port=PORT,
        reload=True,
        log_level="info",
    )
