# ControlPlane.ai

> **Enterprise AI Trust & Security Proxy Middleware**  
> *Real-time governance, deterministic safety guardrails, and SLM verification layer for LLMs.*

---

## Overview

**ControlPlane.ai** is an inline, OpenAI-compatible reverse proxy that sits between your user applications and foundation models (OpenAI, Gemini, Groq, or local LLMs). 

It enforces strict security, privacy, and clinical safety policies in real time with minimal latency overhead:
- **Pre-execution**: Intercepts prompt injections, applies RBAC document filtering, and enforces deterministic clinical rules.
- **In-flight**: Redacts sensitive PII (SSN, salary, phone, email) before LLM prompt augmentation.
- **Post-execution**: Detects hallucinations via NLI Cross-Encoders, severs unauthorized commercial promises, and triggers safe abstention on high diagnostic entropy.

---

## Key Pipelines

```
[User App] ──► [ControlPlane Gateway (:8080)] ──► [Upstream LLM]
                       │
       ┌───────────────┼───────────────┐
       ▼               ▼               ▼
 1. Customer Bot  2. Enterprise Copilot 3. Clinical Triage
 (DeBERTa SLM &   (RBAC + Presidio PII  (Deterministic Rules &
  Stream Guard)    + NLI Grounding)      Entropy Abstention)
```

### 1. Customer Chatbot (Low Latency)
- **Prompt Injection Defense**: Fast heuristic pattern matching + **DeBERTa-v3 SLM** (`protectai/deberta-v3-base-prompt-injection-v2`).
- **Early Rejection**: Malicious prompts are rejected immediately in **~15ms**, saving upstream LLM token costs.
- **Stream Commitment Guard**: Intercepts unauthorized discount codes or financial promises.

### 2. Enterprise Copilot (RBAC & PII Governance)
- **Role-Based Access Control**: Vector retrieval with strict metadata clearance filtering (Levels 0–5).
- **Presidio PII Redaction**: Automatically scrubs SSNs, executive salaries, phone numbers, and emails.
- **NLI Grounding Verification**: **Sentence-Transformers CrossEncoder** (`cross-encoder/nli-deberta-v3-small`) verifies that generated answers are factually entailed by retrieved source documents.

### 3. Regulated Clinical Triage (Deterministic Safety)
- **Deterministic Hard Rules**: Immediate overrides for critical presentations (e.g., Pediatric Fever $<3\text{y}, \ge 38.5^\circ\text{C} \rightarrow \text{ESI Level 2}$) before probabilistic model output.
- **Semantic Entropy Safe Abstention**: Computes Shannon entropy across multi-sample predictions; escalates ambiguous cases ($H > 0.45$) to human clinicians.

---

## Web Dashboard

The web interface provides an operational control center:
- **Playground**: Side-by-side A/B comparison between the unprotected baseline and the protected ControlPlane gateway.
- **Live Telemetry**: Real-time KPI metrics, latency overhead breakdown, and searchable security audit logs.
- **Policies**: Configurable SLM sensitivity thresholds, compliance mode toggles, and rule switchboards.
- **Benchmark Suite**: One-click execution of the 50-scenario golden evaluation suite with automated scoring.

---

## Getting Started

### Prerequisites
- **Python 3.10+**
- **Node.js 18+ & npm**

### 1. Backend Setup
```bash
# Navigate to backend
cd backend

# Install dependencies
pip install -r requirements.txt

# Start the gateway server (port 8080)
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload
```
The gateway is now live at `http://127.0.0.1:8080`.

### 2. Frontend Setup
```bash
# In a separate terminal, navigate to frontend
cd frontend

# Install dependencies
npm install

# Start the dev server
npm run dev
```
Open `http://localhost:5173` in your browser.

---

## API Usage

Use ControlPlane.ai as a drop-in replacement for OpenAI endpoints:

```bash
curl -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Use-Case: customer_chatbot" \
  -H "X-User-Role: customer" \
  -d '{
    "messages": [
      {"role": "user", "content": "What is the carry-on baggage allowance?"}
    ]
  }'
```

---

## Running the Benchmark

Run the full 50-scenario red-team benchmark:
```bash
curl -X POST http://127.0.0.1:8080/api/v1/benchmark/run
```
Or click **"Run Benchmark Suite"** directly from the web dashboard.

---

## Repository Structure

```
middle_trust/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI server & route handlers
│   │   ├── config.py            # Guardrail policy configuration
│   │   ├── proxy/
│   │   │   └── router.py        # /v1/chat/completions reverse proxy
│   │   ├── guards/
│   │   │   ├── input_guard.py   # DeBERTa-v3 injection classifier
│   │   │   ├── pii_guard.py     # Microsoft Presidio PII scrubber
│   │   │   ├── rbac_guard.py    # ChromaDB clearance-filtered retrieval
│   │   │   ├── grounding_guard.py # Cross-Encoder NLI factuality check
│   │   │   ├── stream_guard.py  # Unauthorized commitment filter
│   │   │   └── clinical_rules.py# Deterministic ESI overrides & entropy
│   │   ├── simulators/          # HR docs, airline policies, patient records
│   │   ├── telemetry/           # Audit logger & live metric aggregators
│   │   └── benchmark/           # 50-scenario dataset & automated runner
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx              # Application shell & navigation
│   │   ├── api.js               # Gateway API client
│   │   └── components/          # Playground, Telemetry, Policies, Benchmark
│   ├── index.html
│   ├── package.json
│   └── tailwind.config.js
├── docs/
│   └── ARCHITECTURE.md          # Technical deep dive
└── README.md
```
