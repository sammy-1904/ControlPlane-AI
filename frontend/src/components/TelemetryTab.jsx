import React, { useState, useEffect } from 'react';
import { 
  Activity, ShieldAlert, Clock, AlertTriangle, Search, Filter, 
  Eye, RefreshCw, BarChart3, Layers, FileText
} from 'lucide-react';
import { 
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, 
  PieChart, Pie, Cell, Legend 
} from 'recharts';
import api from '../api';

const VIOLATION_COLORS = {
  'Injection': '#2563eb',
  'PII Leak': '#3b82f6',
  'Hallucination': '#60a5fa',
  'Clinical Override': '#1d4ed8',
  'Stream Severed': '#1e40af',
  'Entropy Abstention': '#93c5fd',
};

export default function TelemetryTab({ onOpenTrace }) {
  const [stats, setStats] = useState(null);
  const [logs, setLogs] = useState([]);
  const [latencyData, setLatencyData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterAction, setFilterAction] = useState('ALL');
  const [filterUseCase, setFilterUseCase] = useState('ALL');
  const [selectedEvent, setSelectedEvent] = useState(null);

  const fetchTelemetry = async () => {
    try {
      const [statsRes, logsRes, latencyRes] = await Promise.all([
        api.getStats(),
        api.getAuditLogs(100),
        api.getLatencyBreakdown(),
      ]);
      setStats(statsRes);
      setLogs(logsRes.events || []);
      setLatencyData(latencyRes.breakdown || []);
    } catch (err) {
      console.error('Failed to load telemetry:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTelemetry();
    const interval = setInterval(fetchTelemetry, 5000);
    return () => clearInterval(interval);
  }, []);

  // Format violation pie chart data
  const pieData = stats?.violation_distribution 
    ? Object.entries(stats.violation_distribution)
        .filter(([_, count]) => count > 0)
        .map(([name, value]) => ({ name, value }))
    : [];

  // Filter logs
  const filteredLogs = logs.filter(log => {
    const matchesSearch = 
      log.audit_id?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      log.prompt_preview?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      log.use_case?.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesAction = filterAction === 'ALL' || log.action === filterAction;
    const matchesUseCase = filterUseCase === 'ALL' || log.use_case === filterUseCase;
    return matchesSearch && matchesAction && matchesUseCase;
  });

  return (
    <div className="space-y-5">
      {/* Top Metric Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Total Requests */}
        <div className="glass-panel p-4 rounded-xl space-y-2">
          <div className="flex items-center justify-between text-slate-500 text-xs font-semibold uppercase tracking-wider">
            <span>Total Requests</span>
            <Activity className="w-4 h-4 text-blue-600" />
          </div>
          <div className="text-2xl font-bold text-slate-900 font-mono">
            {stats?.total_requests || 0}
          </div>
          <div className="text-[11px] text-slate-500 flex items-center gap-1">
            <span className="text-blue-600 font-semibold font-mono">100%</span> routed via proxy
          </div>
        </div>

        {/* Interception Rate */}
        <div className="glass-panel p-4 rounded-xl space-y-2">
          <div className="flex items-center justify-between text-slate-500 text-xs font-semibold uppercase tracking-wider">
            <span>Interception Rate</span>
            <ShieldAlert className="w-4 h-4 text-blue-600" />
          </div>
          <div className="text-2xl font-bold text-blue-700 font-mono">
            {stats?.interception_rate || 0}%
          </div>
          <div className="text-[11px] text-slate-500">
            Threats blocked or redacted
          </div>
        </div>

        {/* Average Overhead */}
        <div className="glass-panel p-4 rounded-xl space-y-2">
          <div className="flex items-center justify-between text-slate-500 text-xs font-semibold uppercase tracking-wider">
            <span>Average Guard Overhead</span>
            <Clock className="w-4 h-4 text-blue-600" />
          </div>
          <div className="text-2xl font-bold text-slate-900 font-mono">
            {stats?.avg_overhead_ms || 0} <span className="text-xs font-normal text-slate-500">ms</span>
          </div>
          <div className="text-[11px] text-slate-500">
            SLM + Presidio + NLI evaluation
          </div>
        </div>

        {/* Over-Flagging Rate */}
        <div className="glass-panel p-4 rounded-xl space-y-2">
          <div className="flex items-center justify-between text-slate-500 text-xs font-semibold uppercase tracking-wider">
            <span>Over-Flagging Rate</span>
            <AlertTriangle className="w-4 h-4 text-blue-600" />
          </div>
          <div className="text-2xl font-bold text-slate-900 font-mono">
            {stats?.over_flagging_rate || 0}%
          </div>
          <div className="text-[11px] text-slate-500">
            Target &lt; 5% on benign traffic
          </div>
        </div>
      </div>

      {/* Visualizations Section: Latency Breakdown & Violation Donut */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Latency Stacked Bar Chart */}
        <div className="glass-panel p-5 rounded-xl lg:col-span-2 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-900 flex items-center gap-2">
              <BarChart3 className="w-4 h-4 text-blue-600" /> Latency Breakdown (Recent Requests)
            </h3>
            <span className="text-xs text-slate-500 font-mono">Baseline LLM vs Guard Middleware</span>
          </div>

          <div className="h-60 w-full">
            {latencyData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={latencyData.slice(-15)} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <XAxis dataKey="audit_id" tick={{ fill: '#64748b', fontSize: 10 }} />
                  <YAxis tick={{ fill: '#64748b', fontSize: 10 }} unit="ms" />
                  <Tooltip 
                    contentStyle={{ 
                      backgroundColor: '#ffffff', 
                      borderColor: '#cbd5e1', 
                      borderRadius: '8px', 
                      color: '#0f172a',
                      fontSize: '11px',
                      fontFamily: 'JetBrains Mono',
                      boxShadow: '0 4px 6px -1px rgba(0,0,0,0.1)'
                    }} 
                  />
                  <Bar dataKey="base_ms" name="Baseline LLM (ms)" stackId="a" fill="#cbd5e1" />
                  <Bar dataKey="overhead_ms" name="Guard Overhead (ms)" stackId="a" fill="#2563eb" />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full flex items-center justify-center text-xs text-slate-400 font-mono">
                No latency history recorded yet. Run requests in Playground.
              </div>
            )}
          </div>
        </div>

        {/* Violations Distribution Donut */}
        <div className="glass-panel p-5 rounded-xl space-y-4">
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-900 flex items-center gap-2">
            <ShieldAlert className="w-4 h-4 text-blue-600" /> Violation Categories
          </h3>

          <div className="h-60 w-full flex items-center justify-center">
            {pieData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={pieData}
                    cx="50%"
                    cy="50%"
                    innerRadius={50}
                    outerRadius={75}
                    paddingAngle={3}
                    dataKey="value"
                  >
                    {pieData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={VIOLATION_COLORS[entry.name] || '#2563eb'} />
                    ))}
                  </Pie>
                  <Tooltip 
                    contentStyle={{ 
                      backgroundColor: '#ffffff', 
                      borderColor: '#cbd5e1', 
                      borderRadius: '8px', 
                      color: '#0f172a',
                      fontSize: '11px',
                      fontFamily: 'JetBrains Mono',
                      boxShadow: '0 4px 6px -1px rgba(0,0,0,0.1)'
                    }} 
                  />
                  <Legend 
                    wrapperStyle={{ fontSize: '10px', paddingTop: '8px', color: '#475569' }}
                  />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <div className="text-xs text-slate-400 font-mono text-center">
                Zero security policy violations logged.
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Audit Logs Table */}
      <div className="glass-panel rounded-xl p-5 space-y-4">
        {/* Table Search & Filter Bar */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-900 flex items-center gap-2">
              <FileText className="w-4 h-4 text-blue-600" /> Security Audit Event Log
            </h3>
            <span className="text-xs font-mono text-slate-500">({filteredLogs.length} events)</span>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {/* Search */}
            <div className="flex items-center bg-slate-50 border border-slate-300 rounded-lg px-2.5 py-1 text-xs">
              <Search className="w-3.5 h-3.5 text-slate-400 mr-2" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search audit ID, prompt..."
                className="bg-transparent text-slate-800 placeholder-slate-400 focus:outline-none font-mono text-xs w-44"
              />
            </div>

            {/* Filter Action */}
            <select
              value={filterAction}
              onChange={(e) => setFilterAction(e.target.value)}
              className="bg-slate-50 border border-slate-300 rounded-lg px-2.5 py-1 text-xs text-slate-800 focus:outline-none"
            >
              <option value="ALL">All Actions</option>
              <option value="ALLOW">ALLOW</option>
              <option value="BLOCKED">BLOCKED</option>
              <option value="MUTATED_REDACTED">MUTATED_REDACTED</option>
              <option value="HUMAN_ESCALATION">HUMAN_ESCALATION</option>
            </select>

            {/* Filter Use Case */}
            <select
              value={filterUseCase}
              onChange={(e) => setFilterUseCase(e.target.value)}
              className="bg-slate-50 border border-slate-300 rounded-lg px-2.5 py-1 text-xs text-slate-800 focus:outline-none"
            >
              <option value="ALL">All Routes</option>
              <option value="customer_chatbot">Chatbot</option>
              <option value="internal_copilot">Copilot</option>
              <option value="regulated_triage">Triage</option>
            </select>
          </div>
        </div>

        {/* Table */}
        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 text-slate-600 font-semibold uppercase tracking-wider border-b border-slate-200 font-mono">
              <tr>
                <th className="py-2.5 px-3">Audit ID</th>
                <th className="py-2.5 px-3">Timestamp</th>
                <th className="py-2.5 px-3">Route</th>
                <th className="py-2.5 px-3">Role</th>
                <th className="py-2.5 px-3">Action</th>
                <th className="py-2.5 px-3">Prompt Preview</th>
                <th className="py-2.5 px-3 text-right">Overhead</th>
                <th className="py-2.5 px-3 text-center">Trace</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 font-mono text-slate-700 bg-white">
              {filteredLogs.length > 0 ? (
                filteredLogs.map((log) => (
                  <tr key={log.audit_id} className="hover:bg-blue-50/40 transition-colors">
                    <td className="py-2.5 px-3 text-blue-600 font-bold">{log.audit_id}</td>
                    <td className="py-2.5 px-3 text-slate-500 text-[11px]">
                      {new Date(log.timestamp).toLocaleTimeString()}
                    </td>
                    <td className="py-2.5 px-3 uppercase text-[11px] text-slate-700">{log.use_case}</td>
                    <td className="py-2.5 px-3 text-[11px] text-slate-500">{log.user_role}</td>
                    <td className="py-2.5 px-3">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        log.action === 'BLOCKED' ? 'glass-badge-white' :
                        log.action === 'MUTATED_REDACTED' ? 'glass-badge-blue' :
                        log.action === 'HUMAN_ESCALATION' ? 'glass-badge-purple' :
                        'glass-badge-solid-blue'
                      }`}>
                        {log.action}
                      </span>
                    </td>
                    <td className="py-2.5 px-3 max-w-xs truncate text-slate-600 text-[11px]">
                      {log.prompt_preview}
                    </td>
                    <td className="py-2.5 px-3 text-right text-blue-700 font-semibold">
                      +{log.latency_overhead_ms}ms
                    </td>
                    <td className="py-2.5 px-3 text-center">
                      <button
                        onClick={() => onOpenTrace(log)}
                        className="p-1 rounded hover:bg-slate-100 text-blue-600 transition-colors"
                        title="View Full Waterfall Trace"
                      >
                        <Eye className="w-3.5 h-3.5" />
                      </button>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan="8" className="py-6 text-center text-slate-400 font-mono">
                    No matching audit logs found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
