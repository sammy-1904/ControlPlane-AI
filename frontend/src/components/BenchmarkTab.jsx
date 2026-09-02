import React, { useState } from 'react';
import { 
  PlayCircle, CheckCircle2, XCircle, Clock, 
  RefreshCw, Award, ShieldCheck, ChevronDown, ChevronRight, Search
} from 'lucide-react';
import api from '../api';

export default function BenchmarkTab() {
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState(null);
  const [expandedRow, setExpandedRow] = useState(null);
  const [filterCategory, setFilterCategory] = useState('ALL');
  const [searchQuery, setSearchQuery] = useState('');

  const handleRunBenchmark = async () => {
    setRunning(true);
    setResults(null);
    try {
      const data = await api.runBenchmark();
      setResults(data);
    } catch (err) {
      console.error('Benchmark execution failed:', err);
    } finally {
      setRunning(false);
    }
  };

  const getStatusBadge = (status) => {
    if (status === 'PASSED') {
      return (
        <span className="px-2 py-0.5 rounded text-[11px] font-bold glass-badge-solid-blue flex items-center gap-1 w-fit">
          <CheckCircle2 className="w-3 h-3" /> PASSED
        </span>
      );
    }
    return (
      <span className="px-2 py-0.5 rounded text-[11px] font-bold glass-badge-white flex items-center gap-1 w-fit">
        <XCircle className="w-3 h-3" /> FAILED
      </span>
    );
  };

  const filteredCases = results?.test_results ? results.test_results.filter(tc => {
    const matchesCat = filterCategory === 'ALL' || tc.use_case === filterCategory;
    const matchesSearch = 
      tc.test_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      tc.prompt.toLowerCase().includes(searchQuery.toLowerCase()) ||
      tc.description.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesCat && matchesSearch;
  }) : [];

  return (
    <div className="space-y-5 max-w-6xl mx-auto">
      {/* Action Header Card */}
      <div className="glass-panel p-5 rounded-xl flex flex-wrap items-center justify-between gap-6">
        <div className="space-y-1">
          <span className="text-[10px] font-mono uppercase tracking-wider text-blue-600 font-semibold">Automated Red-Team Evaluation</span>
          <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
            <Award className="w-4 h-4 text-blue-600" /> Standardized Benchmark Evaluation (50 Scenarios)
          </h2>
          <p className="text-xs text-slate-500">
            Executes 17 Chatbot + 17 Copilot + 16 Triage scenarios. Validates accuracy &gt; 90% and FPR &lt; 5%.
          </p>
        </div>

        <button
          onClick={handleRunBenchmark}
          disabled={running}
          className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-semibold text-xs tracking-wide uppercase transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
        >
          {running ? (
            <>
              <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Evaluating 50 Scenarios...
            </>
          ) : (
            <>
              <PlayCircle className="w-3.5 h-3.5 fill-current" /> Run Benchmark Suite
            </>
          )}
        </button>
      </div>

      {/* Benchmark in progress state */}
      {running && (
        <div className="glass-panel p-6 rounded-xl text-center space-y-3">
          <div className="flex items-center justify-center gap-2 text-blue-600">
            <RefreshCw className="w-4 h-4 animate-spin" />
            <span className="text-xs font-mono font-semibold">Executing test suite against ControlPlane Gateway...</span>
          </div>
          <p className="text-[11px] text-slate-500 font-mono">Evaluating Prompt Injections, RBAC queries, Presidio masking, and clinical overrides.</p>
        </div>
      )}

      {/* Comparative Scorecard Table */}
      {results && (
        <>
          <div className="glass-panel rounded-xl p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-900 flex items-center gap-2">
                <ShieldCheck className="w-4 h-4 text-blue-600" /> Benchmark Evaluation Scorecard
              </h3>
              <span className="text-xs font-mono text-slate-500">
                Duration: <span className="text-blue-700 font-bold">{results.duration_seconds}s</span>
              </span>
            </div>

            <div className="overflow-x-auto rounded-lg border border-slate-200">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-50 text-slate-600 font-semibold uppercase tracking-wider border-b border-slate-200 font-mono">
                  <tr>
                    <th className="py-2.5 px-3">Evaluation Domain</th>
                    <th className="py-2.5 px-3 text-center">Scenarios</th>
                    <th className="py-2.5 px-3 text-center">Accuracy (%)</th>
                    <th className="py-2.5 px-3 text-center">Recall (%)</th>
                    <th className="py-2.5 px-3 text-center">FPR (Over-Flagging)</th>
                    <th className="py-2.5 px-3 text-right">Avg Overhead</th>
                    <th className="py-2.5 px-3 text-center">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200 font-mono text-slate-800 bg-white">
                  {results.category_scores && Object.entries(results.category_scores).map(([category, score]) => {
                    const isOverall = category === 'overall';
                    return (
                      <tr 
                        key={category} 
                        className={`hover:bg-blue-50/40 transition-colors ${
                          isOverall ? 'bg-blue-50 font-bold text-blue-950' : ''
                        }`}
                      >
                        <td className="py-3 px-3 uppercase">
                          {isOverall ? 'OVERALL EVALUATION SUMMARY' : category.replace(/_/g, ' ')}
                        </td>
                        <td className="py-3 px-3 text-center">{score.total}</td>
                        <td className="py-3 px-3 text-center text-blue-700 font-bold">{score.accuracy}%</td>
                        <td className="py-3 px-3 text-center">{score.recall}%</td>
                        <td className="py-3 px-3 text-center">{score.fpr}%</td>
                        <td className="py-3 px-3 text-right text-slate-700">+{score.avg_overhead_ms}ms</td>
                        <td className="py-3 px-3 flex justify-center">{getStatusBadge(score.status)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Granular 50-Case Audit Log */}
          <div className="glass-panel rounded-xl p-5 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-900">
                Detailed Scenario Execution Log ({filteredCases.length} Cases)
              </h3>

              <div className="flex flex-wrap items-center gap-2">
                {/* Search */}
                <div className="flex items-center bg-slate-50 border border-slate-300 rounded-lg px-2.5 py-1 text-xs">
                  <Search className="w-3.5 h-3.5 text-slate-400 mr-2" />
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search test ID or description..."
                    className="bg-transparent text-slate-800 placeholder-slate-400 focus:outline-none font-mono text-xs w-48"
                  />
                </div>

                {/* Category Filter */}
                <select
                  value={filterCategory}
                  onChange={(e) => setFilterCategory(e.target.value)}
                  className="bg-slate-50 border border-slate-300 rounded-lg px-2.5 py-1 text-xs text-slate-800 focus:outline-none font-mono"
                >
                  <option value="ALL">All Domains</option>
                  <option value="customer_chatbot">Customer Chatbot</option>
                  <option value="internal_copilot">Internal Copilot</option>
                  <option value="regulated_triage">Clinical Triage</option>
                </select>
              </div>
            </div>

            <div className="space-y-2">
              {filteredCases.map((tc) => {
                const isExpanded = expandedRow === tc.test_id;
                return (
                  <div 
                    key={tc.test_id}
                    className="border border-slate-200 rounded-lg bg-white overflow-hidden shadow-sm"
                  >
                    <div 
                      onClick={() => setExpandedRow(isExpanded ? null : tc.test_id)}
                      className="p-3 flex items-center justify-between cursor-pointer hover:bg-slate-50 transition-colors"
                    >
                      <div className="flex items-center gap-3">
                        <div className="text-slate-400">
                          {isExpanded ? <ChevronDown className="w-4 h-4 text-blue-600" /> : <ChevronRight className="w-4 h-4" />}
                        </div>
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-xs font-bold text-blue-700">{tc.test_id}</span>
                            <span className="text-xs text-slate-800 font-medium">{tc.description}</span>
                          </div>
                          <p className="text-[11px] text-slate-500 font-mono truncate max-w-md mt-0.5">
                            {tc.prompt}
                          </p>
                        </div>
                      </div>

                      <div className="flex items-center gap-4">
                        <span className="text-xs font-mono text-slate-600 bg-slate-100 px-2 py-0.5 rounded border border-slate-200">
                          +{tc.latency_ms}ms
                        </span>
                        {getStatusBadge(tc.passed ? 'PASSED' : 'FAILED')}
                      </div>
                    </div>

                    {isExpanded && (
                      <div className="p-4 bg-slate-50 border-t border-slate-200 text-xs font-mono space-y-3">
                        <div className="grid grid-cols-2 gap-4">
                          <div>
                            <span className="text-slate-500 block mb-1">Expected Action:</span>
                            <span className="text-slate-800 font-bold bg-white px-2 py-0.5 rounded border border-slate-200">
                              {tc.expected_action}
                            </span>
                          </div>
                          <div>
                            <span className="text-slate-500 block mb-1">Actual Action Taken:</span>
                            <span className={`font-bold px-2 py-0.5 rounded border ${
                              tc.passed ? 'text-blue-700 border-blue-300 bg-blue-50' : 'text-slate-800 border-slate-300 bg-white'
                            }`}>
                              {tc.actual_action}
                            </span>
                          </div>
                        </div>

                        <div>
                          <span className="text-slate-500 block mb-1">Full Prompt:</span>
                          <p className="p-2.5 rounded bg-white border border-slate-200 text-slate-800 whitespace-pre-wrap">
                            {tc.prompt}
                          </p>
                        </div>

                        {tc.details && (
                          <div>
                            <span className="text-slate-500 block mb-1">Evaluation Diagnostic Details:</span>
                            <p className="p-2.5 rounded bg-white border border-slate-200 text-slate-600 whitespace-pre-wrap">
                              {tc.details}
                            </p>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
