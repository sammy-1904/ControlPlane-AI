import React, { useState, useEffect } from 'react';
import { 
  Sliders, Shield, Save, RefreshCw, CheckCircle2, 
  Lock, Cpu, Stethoscope
} from 'lucide-react';
import api from '../api';

export default function PoliciesTab() {
  const [policies, setPolicies] = useState({
    injection_threshold: 0.70,
    injection_enabled: true,
    contradiction_threshold: 0.35,
    neutral_threshold: 0.50,
    grounding_enabled: true,
    entropy_threshold: 0.45,
    entropy_enabled: true,
    stream_guard_enabled: true,
    pii_redaction_enabled: true,
    rbac_enabled: true,
    pediatric_fever_override: true,
    hypoxia_override: true,
    hypotension_override: true,
    strict_mode: true,
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);

  useEffect(() => {
    fetchPolicies();
  }, []);

  const fetchPolicies = async () => {
    try {
      const data = await api.getPolicies();
      setPolicies(data);
    } catch (err) {
      console.error('Failed to fetch policies:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveSuccess(false);
    try {
      await api.updatePolicies(policies);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err) {
      console.error('Failed to update policies:', err);
    } finally {
      setSaving(false);
    }
  };

  const toggleStrictMode = (isStrict) => {
    if (isStrict) {
      setPolicies(prev => ({
        ...prev,
        strict_mode: true,
        injection_threshold: 0.60,
        contradiction_threshold: 0.30,
        entropy_threshold: 0.40,
        injection_enabled: true,
        grounding_enabled: true,
        entropy_enabled: true,
        stream_guard_enabled: true,
        pii_redaction_enabled: true,
        rbac_enabled: true,
        pediatric_fever_override: true,
        hypoxia_override: true,
        hypotension_override: true,
      }));
    } else {
      setPolicies(prev => ({
        ...prev,
        strict_mode: false,
        injection_threshold: 0.85,
        contradiction_threshold: 0.55,
        entropy_threshold: 0.65,
      }));
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12 text-slate-400 gap-2">
        <RefreshCw className="w-4 h-4 animate-spin text-blue-600" /> Loading active governance policies...
      </div>
    );
  }

  return (
    <div className="space-y-5 max-w-5xl mx-auto">
      {/* Header & Save Action Bar */}
      <div className="glass-panel p-5 rounded-xl flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-sm font-bold uppercase tracking-wider text-slate-900 flex items-center gap-2">
            <Sliders className="w-4 h-4 text-blue-600" /> Policy & Governance Configuration
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Configure SLM model sensitivity thresholds and deterministic safety rules in real time.
          </p>
        </div>

        <div className="flex items-center gap-3">
          {saveSuccess && (
            <span className="text-xs font-semibold text-blue-700 flex items-center gap-1">
              <CheckCircle2 className="w-3.5 h-3.5" /> Policies Updated
            </span>
          )}
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-semibold text-xs tracking-wide uppercase transition-colors disabled:opacity-50 shadow-sm"
          >
            {saving ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            Save Changes
          </button>
        </div>
      </div>

      {/* Mode Toggle */}
      <div className="glass-panel p-5 rounded-xl border border-blue-200 bg-blue-50/50 flex flex-wrap items-center justify-between gap-4">
        <div className="space-y-1">
          <span className="text-[10px] font-mono text-blue-700 uppercase tracking-wider font-semibold">Compliance Mode</span>
          <h3 className="text-sm font-bold text-slate-900">
            {policies.strict_mode ? 'Strict Compliance Mode (Maximum Security)' : 'Permissive Mode (Optimized for Latency)'}
          </h3>
          <p className="text-xs text-slate-600">
            {policies.strict_mode 
              ? 'Enforces tight SLM thresholds, full PII scrubbing, deterministic rules, and NLI verification.' 
              : 'Relaxed thresholds for higher throughput and reduced intervention rate.'}
          </p>
        </div>

        <div className="flex items-center p-1 rounded-lg bg-white border border-slate-200 shadow-sm">
          <button
            onClick={() => toggleStrictMode(false)}
            className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-all ${
              !policies.strict_mode 
                ? 'bg-blue-600 text-white shadow-sm' 
                : 'text-slate-600 hover:text-slate-900'
            }`}
          >
            Permissive Mode
          </button>
          <button
            onClick={() => toggleStrictMode(true)}
            className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-all ${
              policies.strict_mode 
                ? 'bg-blue-600 text-white shadow-sm' 
                : 'text-slate-600 hover:text-slate-900'
            }`}
          >
            Strict Mode
          </button>
        </div>
      </div>

      {/* Modular Policy Controls Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        {/* Module 1: Prompt Injection Guard */}
        <div className="glass-panel p-5 rounded-xl space-y-4">
          <div className="flex items-center justify-between border-b border-slate-200 pb-3">
            <div className="flex items-center gap-2">
              <Shield className="w-4 h-4 text-blue-600" />
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-900">DeBERTa Prompt Injection Guard</h4>
            </div>
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={policies.injection_enabled}
                onChange={(e) => setPolicies({ ...policies, injection_enabled: e.target.checked })}
                className="sr-only peer"
              />
              <div className="w-9 h-5 bg-slate-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-blue-600"></div>
            </label>
          </div>

          <div className="space-y-2">
            <div className="flex justify-between text-xs">
              <span className="text-slate-600">Classification Threshold</span>
              <span className="font-mono text-blue-700 font-bold">{policies.injection_threshold}</span>
            </div>
            <input
              type="range"
              min="0.10"
              max="0.95"
              step="0.05"
              value={policies.injection_threshold}
              onChange={(e) => setPolicies({ ...policies, injection_threshold: parseFloat(e.target.value) })}
              className="w-full accent-blue-600 cursor-pointer bg-slate-200 h-1.5 rounded-lg"
            />
            <p className="text-[11px] text-slate-500">
              Heuristic patterns evaluated in Stage 1, followed by DeBERTa-v3 SLM inference in Stage 2.
            </p>
          </div>
        </div>

        {/* Module 2: Enterprise Copilot RBAC & Presidio PII */}
        <div className="glass-panel p-5 rounded-xl space-y-4">
          <div className="flex items-center justify-between border-b border-slate-200 pb-3">
            <div className="flex items-center gap-2">
              <Lock className="w-4 h-4 text-blue-600" />
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-900">RBAC & Presidio PII Redaction</h4>
            </div>
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={policies.pii_redaction_enabled}
                onChange={(e) => setPolicies({ ...policies, pii_redaction_enabled: e.target.checked })}
                className="sr-only peer"
              />
              <div className="w-9 h-5 bg-slate-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-blue-600"></div>
            </label>
          </div>

          <div className="space-y-3 text-xs">
            <div className="flex items-center justify-between">
              <span className="text-slate-600">RBAC Vector Filtering (ChromaDB)</span>
              <span className="font-mono text-blue-700 font-semibold">{policies.rbac_enabled ? 'Active' : 'Disabled'}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-600">Presidio Entity Masking (SSN, Salary, Email, Phone)</span>
              <span className="font-mono text-blue-700 font-semibold">{policies.pii_redaction_enabled ? 'Active' : 'Disabled'}</span>
            </div>
            <p className="text-[11px] text-slate-500">
              Redacts sensitive fields prior to LLM augmentation and post-scrubs outgoing response tokens.
            </p>
          </div>
        </div>

        {/* Module 3: NLI Grounding & Hallucination Guard */}
        <div className="glass-panel p-5 rounded-xl space-y-4">
          <div className="flex items-center justify-between border-b border-slate-200 pb-3">
            <div className="flex items-center gap-2">
              <Cpu className="w-4 h-4 text-blue-600" />
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-900">NLI Grounding Verification</h4>
            </div>
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={policies.grounding_enabled}
                onChange={(e) => setPolicies({ ...policies, grounding_enabled: e.target.checked })}
                className="sr-only peer"
              />
              <div className="w-9 h-5 bg-slate-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-blue-600"></div>
            </label>
          </div>

          <div className="space-y-2">
            <div className="flex justify-between text-xs">
              <span className="text-slate-600">Contradiction Tolerance</span>
              <span className="font-mono text-blue-700 font-bold">{policies.contradiction_threshold}</span>
            </div>
            <input
              type="range"
              min="0.10"
              max="0.80"
              step="0.05"
              value={policies.contradiction_threshold}
              onChange={(e) => setPolicies({ ...policies, contradiction_threshold: parseFloat(e.target.value) })}
              className="w-full accent-blue-600 cursor-pointer bg-slate-200 h-1.5 rounded-lg"
            />
            <p className="text-[11px] text-slate-500">
              Evaluates CrossEncoder NLI entailment between generated LLM statements and retrieved grounding chunks.
            </p>
          </div>
        </div>

        {/* Module 4: Clinical Deterministic Safety & Entropy */}
        <div className="glass-panel p-5 rounded-xl space-y-4">
          <div className="flex items-center justify-between border-b border-slate-200 pb-3">
            <div className="flex items-center gap-2">
              <Stethoscope className="w-4 h-4 text-blue-600" />
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-900">Clinical Triage Rules & Entropy</h4>
            </div>
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={policies.entropy_enabled}
                onChange={(e) => setPolicies({ ...policies, entropy_enabled: e.target.checked })}
                className="sr-only peer"
              />
              <div className="w-9 h-5 bg-slate-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-blue-600"></div>
            </label>
          </div>

          <div className="space-y-3 text-xs">
            <div className="flex items-center justify-between">
              <span className="text-slate-600">Pediatric Fever Override (&lt;3y, &ge;38.5C &rarr; ESI 2)</span>
              <span className="font-mono text-blue-700 font-semibold">{policies.pediatric_fever_override ? 'Active' : 'Disabled'}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-600">Critical Hypoxia Override (SpO2 &lt; 90% &rarr; ESI 1)</span>
              <span className="font-mono text-blue-700 font-semibold">{policies.hypoxia_override ? 'Active' : 'Disabled'}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-600">Semantic Entropy Abstention Threshold</span>
              <span className="font-mono text-blue-700 font-bold">{policies.entropy_threshold}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
