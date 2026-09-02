import React, { useState, useEffect } from 'react';
import { 
  Shield, Layers, Activity, Sliders, Award, 
  Server
} from 'lucide-react';
import PlaygroundTab from './components/PlaygroundTab';
import TelemetryTab from './components/TelemetryTab';
import PoliciesTab from './components/PoliciesTab';
import BenchmarkTab from './components/BenchmarkTab';
import TraceModal from './components/TraceModal';
import api from './api';

export default function App() {
  const [activeTab, setActiveTab] = useState('playground');
  const [traceModalData, setTraceModalData] = useState(null);
  const [isTraceOpen, setIsTraceOpen] = useState(false);
  const [serverInfo, setServerInfo] = useState(null);

  useEffect(() => {
    // Check server status
    const checkStatus = async () => {
      try {
        const data = await api.getHealth();
        setServerInfo(data);
      } catch (err) {
        console.warn('Backend connection issue:', err);
      }
    };
    checkStatus();
  }, []);

  const handleOpenTrace = (traceData) => {
    setTraceModalData(traceData);
    setIsTraceOpen(true);
  };

  return (
    <div className="min-h-screen flex flex-col justify-between bg-[#f8fafc] text-slate-900">
      {/* Top Navigation Header */}
      <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/95 backdrop-blur-md shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            {/* Brand Logo & Title */}
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-blue-600 text-white font-bold shadow-sm">
                <Shield className="w-5 h-5 fill-current" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h1 className="text-sm font-bold tracking-wider text-slate-900 font-mono uppercase">
                    ControlPlane<span className="text-blue-600">.ai</span>
                  </h1>
                  <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-blue-50 text-blue-700 border border-blue-200 font-mono">
                    Gateway
                  </span>
                </div>
                <p className="text-[11px] text-slate-500 font-normal">
                  Enterprise AI Trust & Security Proxy Middleware
                </p>
              </div>
            </div>

            {/* Tab Navigation Buttons */}
            <nav className="hidden md:flex items-center p-1 rounded-lg bg-slate-100 border border-slate-200 space-x-1">
              <button
                onClick={() => setActiveTab('playground')}
                className={`flex items-center gap-2 px-3.5 py-1.5 rounded-md text-xs font-semibold transition-all ${
                  activeTab === 'playground'
                    ? 'bg-blue-600 text-white shadow-sm'
                    : 'text-slate-600 hover:text-slate-900 hover:bg-white/60'
                }`}
              >
                <Layers className="w-3.5 h-3.5" /> Playground
              </button>

              <button
                onClick={() => setActiveTab('telemetry')}
                className={`flex items-center gap-2 px-3.5 py-1.5 rounded-md text-xs font-semibold transition-all ${
                  activeTab === 'telemetry'
                    ? 'bg-blue-600 text-white shadow-sm'
                    : 'text-slate-600 hover:text-slate-900 hover:bg-white/60'
                }`}
              >
                <Activity className="w-3.5 h-3.5" /> Live Telemetry
              </button>

              <button
                onClick={() => setActiveTab('policies')}
                className={`flex items-center gap-2 px-3.5 py-1.5 rounded-md text-xs font-semibold transition-all ${
                  activeTab === 'policies'
                    ? 'bg-blue-600 text-white shadow-sm'
                    : 'text-slate-600 hover:text-slate-900 hover:bg-white/60'
                }`}
              >
                <Sliders className="w-3.5 h-3.5" /> Policies
              </button>

              <button
                onClick={() => setActiveTab('benchmark')}
                className={`flex items-center gap-2 px-3.5 py-1.5 rounded-md text-xs font-semibold transition-all ${
                  activeTab === 'benchmark'
                    ? 'bg-blue-600 text-white shadow-sm'
                    : 'text-slate-600 hover:text-slate-900 hover:bg-white/60'
                }`}
              >
                <Award className="w-3.5 h-3.5" /> Benchmark Suite
              </button>
            </nav>

            {/* Active Provider & Gateway Status */}
            <div className="flex items-center gap-3 text-xs">
              <div className="hidden lg:flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-50 border border-slate-200 font-mono">
                <Server className="w-3.5 h-3.5 text-blue-600" />
                <span className="text-slate-500">Provider:</span>
                <span className="text-slate-900 font-bold uppercase">{serverInfo?.provider || 'MOCK'}</span>
                <span className="text-slate-400 text-[10px]">({serverInfo?.model || 'llama-3.1-8b'})</span>
              </div>

              <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-blue-50 text-blue-700 border border-blue-200 font-medium font-mono text-[11px]">
                <span className="w-2 h-2 rounded-full bg-blue-600"></span>
                Port 8080 Active
              </div>
            </div>
          </div>

          {/* Mobile Tab Nav */}
          <div className="flex md:hidden overflow-x-auto py-2 border-t border-slate-200 space-x-1">
            <button
              onClick={() => setActiveTab('playground')}
              className={`px-3 py-1.5 rounded text-xs font-medium shrink-0 ${
                activeTab === 'playground' ? 'bg-blue-600 text-white' : 'text-slate-600'
              }`}
            >
              Playground
            </button>
            <button
              onClick={() => setActiveTab('telemetry')}
              className={`px-3 py-1.5 rounded text-xs font-medium shrink-0 ${
                activeTab === 'telemetry' ? 'bg-blue-600 text-white' : 'text-slate-600'
              }`}
            >
              Telemetry
            </button>
            <button
              onClick={() => setActiveTab('policies')}
              className={`px-3 py-1.5 rounded text-xs font-medium shrink-0 ${
                activeTab === 'policies' ? 'bg-blue-600 text-white' : 'text-slate-600'
              }`}
            >
              Policies
            </button>
            <button
              onClick={() => setActiveTab('benchmark')}
              className={`px-3 py-1.5 rounded text-xs font-medium shrink-0 ${
                activeTab === 'benchmark' ? 'bg-blue-600 text-white' : 'text-slate-600'
              }`}
            >
              Benchmark
            </button>
          </div>
        </div>
      </header>

      {/* Main Tab Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 flex-1 w-full">
        {activeTab === 'playground' && <PlaygroundTab onOpenTrace={handleOpenTrace} />}
        {activeTab === 'telemetry' && <TelemetryTab onOpenTrace={handleOpenTrace} />}
        {activeTab === 'policies' && <PoliciesTab />}
        {activeTab === 'benchmark' && <BenchmarkTab />}
      </main>

      {/* Latency Waterfall Modal */}
      <TraceModal
        isOpen={isTraceOpen}
        onClose={() => setIsTraceOpen(false)}
        traceData={traceModalData}
      />

      {/* Footer */}
      <footer className="border-t border-slate-200 py-4 bg-white">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500 font-mono">
          <div className="flex items-center gap-2">
            <span>ControlPlane.ai</span>
            <span>•</span>
            <span>Accenture Innovation Challenge Track 1</span>
          </div>
          <div className="flex items-center gap-3">
            <span>Reverse Proxy Gateway</span>
            <span>•</span>
            <span className="text-blue-600 font-medium">SLM & Deterministic Guardrails</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
