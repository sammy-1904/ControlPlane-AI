import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8080';

const client = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 45000,
});

export const api = {
  // Playground Dual-Path Comparison
  compare: async (useCase, userRole, prompt, metadata = {}) => {
    const response = await client.post('/api/v1/playground/compare', {
      use_case: useCase,
      user_role: userRole,
      prompt,
      metadata,
    });
    return response.data;
  },

  // Telemetry & Metrics
  getStats: async (useCase = null) => {
    const params = useCase ? { use_case: useCase } : {};
    const response = await client.get('/api/v1/telemetry/stats', { params });
    return response.data;
  },

  getAuditLogs: async (limit = 100, useCase = null, action = null) => {
    const params = { limit };
    if (useCase) params.use_case = useCase;
    if (action) params.action = action;
    const response = await client.get('/api/v1/telemetry/logs', { params });
    return response.data;
  },

  getLatencyBreakdown: async () => {
    const response = await client.get('/api/v1/telemetry/latency');
    return response.data;
  },

  // Policies Configuration
  getPolicies: async () => {
    const response = await client.get('/api/v1/policies');
    return response.data;
  },

  updatePolicies: async (updatedPolicies) => {
    const response = await client.put('/api/v1/policies', updatedPolicies);
    return response.data;
  },

  // Clinical Patients
  getPatients: async () => {
    const response = await client.get('/api/v1/patients');
    return response.data;
  },

  // Benchmark Runner
  runBenchmark: async () => {
    const response = await client.post('/api/v1/benchmark/run');
    return response.data;
  },

  // Health Check
  getHealth: async () => {
    const response = await client.get('/');
    return response.data;
  },
};

export default api;
