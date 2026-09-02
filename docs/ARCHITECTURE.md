# ControlPlane.ai Architecture & System Design

## 1. High-Level Architecture

ControlPlane.ai acts as an inline, OpenAI-compatible reverse proxy middleware positioned between client applications and downstream foundation models (Groq Llama 3.1, Google Gemini 2.0, or local Mock LLM).

```mermaid
graph TD
    Client["Client App / Web Playground"] -->|POST /v1/chat/completions| Proxy["ControlPlane.ai Gateway (:8080)"]
    
    Proxy --> HeaderRouter{"X-Use-Case Router"}
    
    HeaderRouter -->|customer_chatbot| P1["Pipeline 1: Customer Chatbot<br/>Latency budget: &lt;80ms"]
    HeaderRouter -->|internal_copilot| P2["Pipeline 2: Internal Copilot<br/>Latency budget: 800ms-1.8s"]
    HeaderRouter -->|regulated_triage| P3["Pipeline 3: Clinical Triage<br/>Deterministic + Entropy"]
    
    subgraph P1_Details [Chatbot Pipeline]
        P1 --> AC["Aho-Corasick + DeBERTa SLM (&lt;35ms)"]
        AC -->|Score &gt; 0.70| BlockP1["Blocked Response"]
        AC -->|Pass| LLM1["LLM Call"]
        LLM1 --> SG["Sliding-Window Stream Guard"]
        SG -->|Promise Detected| SeverP1["Stream Severed + Fallback"]
    end
    
    subgraph P2_Details [Copilot Pipeline]
        P2 --> RBAC["ChromaDB Metadata RBAC Filter"]
        RBAC --> PII1["Presidio PII Scrubbing"]
        PII1 --> LLM2["LLM Context Grounded Call"]
        LLM2 --> PII2["Post-Gen PII Redaction"]
        PII2 --> NLI["DeBERTa NLI Cross-Encoder"]
    end
    
    subgraph P3_Details [Clinical Triage Pipeline]
        P3 --> HardRules{"Deterministic Safety Rules"}
        HardRules -->|Fever / SpO2 / Shock| OverP3["Hard ESI Override (1 or 2)"]
        HardRules -->|No Trigger| Entropy["N=3 Sample Shannon Entropy H(X)"]
        Entropy -->|H &gt; 0.45| EscalateP3["Human Escalation Protocol"]
        Entropy -->|H &le; 0.45| ConsP3["Consensus ESI Level"]
    end
    
    BlockP1 --> Telemetry["Async Telemetry & Audit Logger"]
    SeverP1 --> Telemetry
    NLI --> Telemetry
    OverP3 --> Telemetry
    EscalateP3 --> Telemetry
    ConsP3 --> Telemetry
    
    Telemetry --> ClientResp["OpenAI Response + controlplane_telemetry"]
```

---

## 2. Guard Pipeline Specifications

### 2.1 Customer Chatbot (Commercial Safety & Low Latency)
- **Input Guard**: Aho-Corasick string matching against adversarial patterns + DeBERTa v3 prompt injection scorer ($S_{inj} > 0.70 \rightarrow$ BLOCKED).
- **Stream Interceptor**: 12-token sliding window evaluating n-grams for unauthorized financial promises (e.g. `refund`, `waive fee`, `free voucher`). On detection without supervisor hash, the stream is severed.

### 2.2 Internal Copilot (Data Governance & RBAC)
- **RBAC Filtering**: User roles mapped to clearance (1, 3, 5). Vector retrieval applies `{"clearance_level": {"$lte": user_clearance}}`.
- **PII Guard**: Microsoft Presidio analyzer + anonymizer (and regex engine) scrubs SSN, phone, email, credit cards, and salary values to `[REDACTED_*]`.
- **Grounding Guard**: `cross-encoder/nli-deberta-v3-small` scores each response sentence against retrieved chunks. $p(\text{Contradiction}) > 0.35$ or $p(\text{Neutral}) > 0.50$ triggers hallucination warning tags.

### 2.3 Regulated Clinical Decision Support (ESI Triage)
- **Deterministic Rules**:
  - *Pediatric Fever*: $\text{age} < 3 \text{ AND } \text{temp} \ge 38.5^\circ\text{C} \rightarrow \text{ESI 2}$.
  - *Silent Hypoxia*: $\text{SpO}_2 < 90\% \rightarrow \text{ESI 1}$.
  - *Hypotensive Shock*: $\text{systolic\_bp} < 80 \text{ AND } \text{HR} > 100 \rightarrow \text{ESI 1}$.
- **Entropy Safe Abstention**: When no hard rule triggers, runs $N=3$ samples and computes Shannon entropy:
  $$H(X) = -\sum_{i=1}^k p(x_i) \log_2 p(x_i)$$
  If $H(X) > 0.45$, safe abstention protocol activates (`HUMAN_ESCALATION_REQUIRED`).

---

## 3. Dual-Path Evaluation Harness

The `/api/v1/playground/compare` endpoint executes:
1. **Path A (Unprotected Baseline)**: Raw passthrough directly to the LLM.
2. **Path B (Protected ControlPlane)**: Inline reverse proxy with multi-guard governance.

Returns side-by-side responses and latency diagnostics for immediate visual comparison.
