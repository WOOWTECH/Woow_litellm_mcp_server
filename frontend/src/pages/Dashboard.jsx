import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Activity, Server, Globe, Radio, Database, Boxes, RefreshCw } from 'lucide-react';
import { apiGet } from '../api';
import StatusCard from '../components/StatusCard';

function getStatus(healthy) {
  if (healthy === true) return 'green';
  if (healthy === false) return 'red';
  return 'gray';
}

function dbStatus(db) {
  if (db == null) return 'gray';
  return String(db).toLowerCase().includes('connect') ? 'green' : 'yellow';
}

export default function Dashboard() {
  const { data: health, isLoading, error, refetch, dataUpdatedAt } = useQuery({
    queryKey: ['health'],
    queryFn: () => apiGet('/health'),
    refetchInterval: 30_000,
  });

  const lastRefresh = dataUpdatedAt
    ? new Date(dataUpdatedAt).toLocaleTimeString()
    : null;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="animate-spin text-gray-500" size={24} />
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-6 text-center">
        <p className="text-red-400 font-medium">Failed to load health status</p>
        <p className="text-red-400/70 text-sm mt-1">{error.message}</p>
        <button
          onClick={() => refetch()}
          className="mt-4 px-4 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg text-sm transition-colors"
        >
          Retry
        </button>
      </div>
    );
  }

  const gateway = health?.target_app || {};

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold text-gray-100">Dashboard</h2>
          <p className="text-sm text-gray-500 mt-1">
            LiteLLM gateway health overview
            {lastRefresh && <span> &middot; Updated {lastRefresh}</span>}
          </p>
        </div>
        <button
          onClick={() => refetch()}
          className="flex items-center gap-2 px-3 py-2 bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-gray-200 rounded-lg text-sm transition-colors"
        >
          <RefreshCw size={14} />
          <span>Refresh</span>
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
        <StatusCard
          title="MCP Server"
          status={getStatus(health?.mcp_server?.healthy)}
          value={health?.mcp_server?.healthy ? 'Online' : 'Offline'}
          subtitle={health?.mcp_server?.pod_name || 'Unknown pid'}
          icon={Server}
        />
        <StatusCard
          title="LiteLLM Gateway"
          status={getStatus(gateway.healthy)}
          value={gateway.healthy ? 'Connected' : 'Disconnected'}
          subtitle={gateway.url || 'No URL configured'}
          icon={Globe}
        />
        <StatusCard
          title="MCP Proxy"
          status={getStatus(health?.proxy?.healthy)}
          value={health?.proxy?.healthy ? 'Active' : 'Inactive'}
          subtitle={health?.proxy?.pod_name || 'reverse proxy'}
          icon={Radio}
        />
      </div>

      <h3 className="text-lg font-semibold text-gray-200 mb-4">Gateway Details</h3>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <StatusCard
          title="LiteLLM Version"
          status="gray"
          value={health?.version || 'N/A'}
          subtitle="Reported by /health/readiness"
          icon={Activity}
        />
        <StatusCard
          title="Database"
          status={dbStatus(gateway.db)}
          value={gateway.db || 'unknown'}
          subtitle="Prisma / Postgres readiness"
          icon={Database}
        />
        <StatusCard
          title="Models"
          status={gateway.model_count > 0 ? 'green' : 'gray'}
          value={gateway.model_count != null ? String(gateway.model_count) : 'N/A'}
          subtitle="Deployments registered in the gateway"
          icon={Boxes}
        />
      </div>

      {gateway.error && (
        <div className="mt-6 bg-red-500/10 border border-red-500/20 rounded-xl p-4 text-sm text-red-400">
          <span className="font-medium">Gateway error:</span> {gateway.error}
        </div>
      )}
    </div>
  );
}
