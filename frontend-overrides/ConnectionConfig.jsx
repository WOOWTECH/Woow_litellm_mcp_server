import React, { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Link,
  Save,
  TestTube,
  Loader2,
  CheckCircle2,
  XCircle,
  Eye,
  EyeOff,
  Lock,
} from 'lucide-react';
import { apiGet, apiPut, apiPost } from '../api';

const inputClass =
  'w-full px-3 py-2.5 bg-gray-800 border border-gray-700 rounded-lg text-gray-100 placeholder-gray-600 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 transition-colors';

/**
 * LiteLLM connection settings.
 *
 * LiteLLM authenticates with a *single* Bearer master key (sk-…), not an
 * API key/secret pair or a database + username. The field names match the
 * `connection` section the backend upper-cases into the MCP subprocess
 * environment, so `litellm_mcp_base_url` arrives as LITELLM_MCP_BASE_URL and
 * `litellm_mcp_master_key` as LITELLM_MCP_MASTER_KEY. The Test button probes
 * `GET {base}/health/readiness`.
 */
export default function ConnectionConfig() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({});
  const [showKey, setShowKey] = useState(false);
  const [testResult, setTestResult] = useState(null);

  const { data: config, isLoading, error } = useQuery({
    queryKey: ['config'],
    queryFn: () => apiGet('/config'),
  });

  useEffect(() => {
    if (!config) return;
    setForm({
      litellm_mcp_base_url: config.litellm_mcp_base_url || '',
      // Never prefilled — an empty master key means "keep the stored one".
      litellm_mcp_master_key: '',
    });
  }, [config]);

  const saveMutation = useMutation({
    mutationFn: (data) => apiPut('/config/connection', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['config'] });
      queryClient.invalidateQueries({ queryKey: ['health'] });
    },
  });

  const testMutation = useMutation({
    mutationFn: () => apiPost('/config/test'),
    onSuccess: (result) => {
      setTestResult({ success: result.success, message: result.message || 'Connected' });
    },
    onError: (err) => setTestResult({ success: false, message: err.message }),
  });

  function handleChange(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
    setTestResult(null);
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="animate-spin text-gray-500" size={24} />
      </div>
    );
  }

  const baseUrl = form.litellm_mcp_base_url;

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-gray-100">LiteLLM Connection</h2>
        <p className="text-sm text-gray-500 mt-1">
          Point the MCP server at your LiteLLM gateway&apos;s OpenAI-compatible API
        </p>
      </div>

      {error && (
        <div className="mb-4 flex items-center gap-2 px-3 py-2.5 rounded-lg text-sm bg-red-500/10 border border-red-500/20 text-red-400 max-w-xl">
          <XCircle size={16} />
          <span>Could not load configuration: {error.message}</span>
        </div>
      )}

      <form className="bg-gray-900 border border-gray-800 rounded-xl p-6 max-w-xl">
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">
              LiteLLM Base URL
            </label>
            <div className="relative">
              <Link size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
              <input
                type="url"
                value={baseUrl || ''}
                onChange={(e) => handleChange('litellm_mcp_base_url', e.target.value)}
                placeholder="http://litellm.litellm.svc.cluster.local:4000"
                className={inputClass + ' pl-10'}
              />
            </div>
            <p className="text-xs text-gray-600 mt-1.5">
              Root URL only — endpoints like <code className="text-gray-500">/v1/models</code> and{' '}
              <code className="text-gray-500">/health/readiness</code> are appended automatically.
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-400 mb-1.5">
              Master Key
            </label>
            <div className="relative">
              <Lock size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
              <input
                type={showKey ? 'text' : 'password'}
                value={form.litellm_mcp_master_key || ''}
                onChange={(e) => handleChange('litellm_mcp_master_key', e.target.value)}
                placeholder={config?.litellm_mcp_master_key_masked || 'sk-…'}
                className={inputClass + ' pl-10 pr-10 font-mono'}
                autoComplete="off"
              />
              <button
                type="button"
                onClick={() => setShowKey(!showKey)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
              >
                {showKey ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
            <p className="text-xs text-gray-600 mt-1.5">
              Sent as <code className="text-gray-500">Authorization: Bearer sk-…</code>. Leave blank
              to keep the stored key. In production this is injected from a Kubernetes Secret.
            </p>
          </div>
        </div>

        {testResult && (
          <div
            className={`mt-4 flex items-center gap-2 px-3 py-2.5 rounded-lg text-sm ${
              testResult.success
                ? 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-400'
                : 'bg-red-500/10 border border-red-500/20 text-red-400'
            }`}
          >
            {testResult.success ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
            <span>{testResult.message}</span>
          </div>
        )}

        {saveMutation.isSuccess && (
          <div className="mt-4 flex items-center gap-2 px-3 py-2.5 rounded-lg text-sm bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
            <CheckCircle2 size={16} />
            <span>Saved. The MCP server restarts with the new credentials.</span>
          </div>
        )}

        {saveMutation.isError && (
          <div className="mt-4 flex items-center gap-2 px-3 py-2.5 rounded-lg text-sm bg-red-500/10 border border-red-500/20 text-red-400">
            <XCircle size={16} />
            <span>{saveMutation.error.message}</span>
          </div>
        )}

        <div className="flex gap-3 mt-6">
          <button
            type="button"
            onClick={(e) => { e.preventDefault(); testMutation.mutate(); }}
            disabled={testMutation.isPending || !baseUrl}
            className="flex items-center gap-2 px-4 py-2.5 bg-gray-800 hover:bg-gray-700 disabled:bg-gray-800 disabled:text-gray-600 text-gray-300 font-medium rounded-lg transition-colors"
          >
            {testMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <TestTube size={16} />}
            <span>Test Connection</span>
          </button>

          <button
            type="button"
            onClick={(e) => { e.preventDefault(); saveMutation.mutate(form); }}
            disabled={saveMutation.isPending || !baseUrl}
            className="flex items-center gap-2 px-4 py-2.5 bg-brand-600 hover:bg-brand-500 disabled:bg-gray-700 disabled:text-gray-500 text-white font-medium rounded-lg transition-colors"
          >
            {saveMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
            <span>Save</span>
          </button>
        </div>
      </form>
    </div>
  );
}
