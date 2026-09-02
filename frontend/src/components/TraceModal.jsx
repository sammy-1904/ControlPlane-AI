import React from 'react';
import { X, Clock, Cpu } from 'lucide-react';

export default function TraceModal({ isOpen, onClose, traceData }) {
  if (!isOpen || !traceData) return null;

  const checks = traceData.checks_executed || [];
  const totalOverhead = traceData.latency_overhead_ms || 0;
  const actionTaken = traceData.action_taken || 'ALLOW';

  const getStatusBadge = (status) => {
    switch (status) {
      case 'PASSED':
        return <span className="px-2 py-0.5 text-xs font-semibold rounded glass-badge-solid-blue">PASSED</span>;
      case 'BLOCKED':
      case 'SEVERED':
        return <span className="px-2 py-0.5 text-xs font-semibold rounded glass-badge-white font-bold">BLOCKED</span>;
      case 'TRIGGERED':
      case 'FLAGGED':
      case 'MUTATED_REDACTED':
        return <span className="px-2 py-0.5 text-xs font-semibold rounded glass-badge-blue">MUTATED</span>;
      case 'HUMAN_ESCALATION_REQUIRED':
      case 'HUMAN_ESCALATION':
        return <span className="px-2 py-0.5 text-xs font-semibold rounded glass-badge-purple">ESCALATED</span>;
      default:
        return <span className="px-2 py-0.5 text-xs font-semibold rounded glass-badge-blue">{status}</span>;
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm">
      <div className="bg-white w-full max-w-2xl rounded-xl border border-slate-300 shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200 bg-slate-50">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-blue-600 text-white">
              <Cpu className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-slate-900 flex items-center gap-2">
                Execution Waterfall & Latency Trace
                <span className="text-xs font-mono text-slate-500 font-normal">ID: {traceData.audit_id || 'N/A'}</span>
              </h3>
              <p className="text-xs text-slate-500">
                Action: <span className="font-semibold text-slate-800">{actionTaken}</span> • Total Overhead: <span className="font-mono text-blue-700 font-semibold">{totalOverhead}ms</span>
              </p>
            </div>
          </div>
          <button 
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-5 overflow-y-auto space-y-5">
          {/* Summary Cards */}
          <div className="grid grid-cols-3 gap-3">
            <div className="p-3 rounded-lg bg-slate-50 border border-slate-200">
              <span className="text-[10px] uppercase font-semibold text-slate-500 block mb-1">Target Route</span>
              <span className="text-xs font-bold text-slate-800 uppercase font-mono">{traceData.use_case || 'N/A'}</span>
            </div>
            <div className="p-3 rounded-lg bg-slate-50 border border-slate-200">
              <span className="text-[10px] uppercase font-semibold text-slate-500 block mb-1">Guards Executed</span>
              <span className="text-xs font-bold text-blue-700 font-mono">{checks.length} Checks</span>
            </div>
            <div className="p-3 rounded-lg bg-slate-50 border border-slate-200">
              <span className="text-[10px] uppercase font-semibold text-slate-500 block mb-1">Gateway Status</span>
              <span className={`text-xs font-bold font-mono ${traceData.flagged ? 'text-blue-700' : 'text-slate-800'}`}>
                {traceData.flagged ? 'Intervention Active' : 'Clean Passthrough'}
              </span>
            </div>
          </div>

          {/* Sequential Waterfall */}
          <div className="space-y-3">
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-700 flex items-center gap-1.5">
              <Clock className="w-3.5 h-3.5 text-blue-600" /> Sequential Guard Stage Breakdown
            </h4>
            <div className="space-y-2.5">
              {checks.length === 0 ? (
                <div className="text-center py-6 text-slate-400 text-xs font-mono">
                  No guard execution steps recorded in this trace.
                </div>
              ) : (
                checks.map((check, idx) => {
                  const checkLatency = check.latency_ms || 0;
                  const percent = totalOverhead > 0 ? Math.min(100, Math.max(5, (checkLatency / totalOverhead) * 100)) : 100;

                  return (
                    <div key={idx} className="p-3 rounded-lg bg-slate-50 border border-slate-200 space-y-2">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-medium text-slate-800 font-mono">
                            {check.check?.replace(/_/g, ' ')}
                          </span>
                        </div>
                        <div className="flex items-center gap-2.5">
                          {getStatusBadge(check.status)}
                          <span className="text-xs font-mono text-slate-700 bg-white px-2 py-0.5 rounded border border-slate-200 font-semibold">
                            {checkLatency.toFixed(1)}ms
                          </span>
                        </div>
                      </div>

                      {/* Bar indicator */}
                      <div className="w-full bg-slate-200 rounded-full h-1.5 overflow-hidden">
                        <div 
                          className="bg-blue-600 h-full rounded-full transition-all duration-300" 
                          style={{ width: `${percent}%` }}
                        />
                      </div>

                      {/* Details text */}
                      {check.details && (
                        <p className="text-[11px] text-slate-700 font-mono bg-white p-2 rounded border border-slate-200">
                          {check.details}
                        </p>
                      )}

                      {/* Diagnostic metrics */}
                      {check.risk_score !== undefined && (
                        <div className="flex items-center gap-2 text-[11px] text-slate-600 font-mono">
                          <span>Risk Score:</span>
                          <span className="text-blue-700 font-bold">{check.risk_score}</span>
                          {check.stage1_matched_patterns && (
                            <span className="text-slate-500">({check.stage1_matched_patterns})</span>
                          )}
                        </div>
                      )}
                      {check.score !== undefined && (
                        <div className="flex items-center gap-2 text-[11px] text-slate-600 font-mono">
                          <span>Entailment Score:</span>
                          <span className="text-blue-700 font-bold">{check.score}</span>
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-slate-200 bg-slate-50 flex justify-end">
          <button
            onClick={onClose}
            className="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-slate-200 hover:bg-slate-300 text-slate-800 transition-colors"
          >
            Close Trace
          </button>
        </div>
      </div>
    </div>
  );
}
