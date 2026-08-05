import React, { useState, useMemo, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Search,
  Loader2,
  Wrench,
  ToggleLeft,
  ToggleRight,
  RefreshCw,
  AlertTriangle,
  ShieldAlert,
  ChevronDown,
  ChevronRight,
  Save,
  Undo2,
  CheckCircle2,
  XCircle,
} from 'lucide-react';
import { apiGet, apiPut } from '../api';

/**
 * Tool switches.
 *
 * The API reports each tool's *effective* `enabled`, which folds three
 * independent dimensions together: the per-tool switch (`disabled_tools`), the
 * category switch (`disabled_categories`) and read-only mode (which suppresses
 * every destructive tool). The page used to PUT that composite array back on
 * every click, so `to_patch()` read "off because read-only" as "the operator
 * disabled this tool by name" and baked the suppression in permanently —
 * one click on an unrelated toggle silently disabled six tools.
 *
 * So this page edits the RAW sets instead (the same ones GET returns at the top
 * level) and PUTs those explicitly. The rendered switch shows the per-tool
 * state; a separate chip says when something else is suppressing the tool.
 */

function toSet(list) {
  return new Set(Array.isArray(list) ? list : []);
}

function sameSet(a, b) {
  if (a.size !== b.size) return false;
  for (const item of a) if (!b.has(item)) return false;
  return true;
}

// Compares the {tool: [operation, …]} maps by value. The join separator is
// U+0000 because it cannot occur inside an operation name (a comma or space
// could, which would make ["a,b"] and ["a","b"] compare equal and silently
// swallow a dirty-state change). It is written as an escape, not a literal
// NUL byte: a raw NUL makes git/grep/diff treat this file as binary.
function sameOps(a, b) {
  const keysA = Object.keys(a);
  const keysB = Object.keys(b);
  if (keysA.length !== keysB.length) return false;
  return keysA.every(
    (key) =>
      Array.isArray(b[key]) &&
      a[key].length === b[key].length &&
      [...a[key]].sort().join('\u0000') === [...b[key]].sort().join('\u0000')
  );
}

/** Normalise the stored {tool: [op, …]} map, dropping now-empty entries. */
function normaliseOps(raw) {
  const out = {};
  for (const [tool, ops] of Object.entries(raw || {})) {
    const list = Array.isArray(ops) ? ops.filter(Boolean) : [];
    if (list.length) out[tool] = [...list];
  }
  return out;
}

function draftFrom(data) {
  return {
    readonly: Boolean(data?.readonly),
    disabledTools: toSet(data?.disabled_tools),
    disabledCategories: toSet(data?.disabled_categories),
    disabledOperations: normaliseOps(data?.disabled_operations),
  };
}

export default function ToolManager() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState({});
  const [draft, setDraft] = useState(null);

  const { data: toolsData, isLoading, error, refetch } = useQuery({
    queryKey: ['tools'],
    queryFn: () => apiGet('/tools'),
  });

  // Re-seed the draft whenever the server view changes (initial load, after an
  // apply, after a save on /permissions). Editing locally is what removes the
  // per-click MCP restart: one Apply = one restart, not N.
  useEffect(() => {
    if (toolsData) setDraft(draftFrom(toolsData));
  }, [toolsData]);

  const mutation = useMutation({
    mutationFn: (patch) => apiPut('/tools', patch),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tools'] });
      // The tools section also drives the permissions blob and the child's
      // health, so those cached views are stale the moment this succeeds.
      queryClient.invalidateQueries({ queryKey: ['config'] });
      queryClient.invalidateQueries({ queryKey: ['health'] });
      queryClient.invalidateQueries({ queryKey: ['mcpStatus'] });
    },
  });

  // Memoised so the array keeps its identity across renders: `filteredTools`
  // and the category grouping below depend on it, and a fresh `[]`/slice every
  // render recomputed both on unrelated state changes (search box keystrokes,
  // draft toggles) instead of only when the query data actually changed.
  const tools = useMemo(() => toolsData?.tools || [], [toolsData]);
  const serverDraft = useMemo(() => draftFrom(toolsData), [toolsData]);

  const isDirty = useMemo(() => {
    if (!draft) return false;
    return (
      draft.readonly !== serverDraft.readonly ||
      !sameSet(draft.disabledTools, serverDraft.disabledTools) ||
      !sameSet(draft.disabledCategories, serverDraft.disabledCategories) ||
      !sameOps(draft.disabledOperations, serverDraft.disabledOperations)
    );
  }, [draft, serverDraft]);

  const filteredTools = useMemo(() => {
    if (!search.trim()) return tools;
    const q = search.toLowerCase();
    return tools.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        (t.description || '').toLowerCase().includes(q) ||
        (t.category || '').toLowerCase().includes(q)
    );
  }, [tools, search]);

  const categories = useMemo(() => {
    const grouped = {};
    for (const tool of filteredTools) {
      const cat = tool.category || 'Uncategorized';
      if (!grouped[cat]) grouped[cat] = [];
      grouped[cat].push(tool);
    }
    return Object.entries(grouped).sort(([a], [b]) => a.localeCompare(b));
  }, [filteredTools]);

  function toggleTool(name) {
    setDraft((prev) => {
      const next = new Set(prev.disabledTools);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return { ...prev, disabledTools: next };
    });
  }

  function toggleCategory(category) {
    setDraft((prev) => {
      const next = new Set(prev.disabledCategories);
      if (next.has(category)) next.delete(category);
      else next.add(category);
      return { ...prev, disabledCategories: next };
    });
  }

  function toggleOperation(toolName, opName) {
    setDraft((prev) => {
      const ops = { ...prev.disabledOperations };
      const current = new Set(ops[toolName] || []);
      if (current.has(opName)) current.delete(opName);
      else current.add(opName);
      if (current.size) ops[toolName] = [...current];
      else delete ops[toolName];
      return { ...prev, disabledOperations: ops };
    });
  }

  function apply() {
    // Send the explicit sets, never the effective per-tool flags: that is what
    // stops read-only / category suppression being rewritten as individual
    // disables. `readonly` and `disabled_categories` are only reachable from
    // this page, so they must be part of the payload.
    mutation.mutate({
      readonly: draft.readonly,
      disabled_tools: [...draft.disabledTools].sort(),
      disabled_categories: [...draft.disabledCategories].sort(),
      disabled_operations: draft.disabledOperations,
    });
  }

  if (isLoading || !draft) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="animate-spin text-gray-500" size={24} />
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-6 text-center">
        <p className="text-red-400 font-medium">Failed to load tools</p>
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

  /** What the gate will do with this tool once the draft is applied. */
  function effectiveFor(tool) {
    const offByName = draft.disabledTools.has(tool.name);
    const offByCategory = draft.disabledCategories.has(tool.category);
    const offByReadonly = draft.readonly && tool.dangerous;
    return {
      offByName,
      offByCategory,
      offByReadonly,
      enabled: !offByName && !offByCategory && !offByReadonly,
    };
  }

  const effectiveEnabledCount = tools.filter((t) => effectiveFor(t).enabled).length;
  const status = mutation.data?.status;
  const unknownTools = mutation.data?.unknown_tools || [];

  return (
    <div>
      <div className="flex items-start justify-between mb-6 gap-4">
        <div>
          <h2 className="text-2xl font-bold text-gray-100">Tool Manager</h2>
          <p className="text-sm text-gray-500 mt-1">
            {effectiveEnabledCount} of {tools.length} LiteLLM tools enabled
            {isDirty && <span className="text-amber-400 ml-2">(unapplied changes)</span>}
          </p>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => setDraft(draftFrom(toolsData))}
            disabled={!isDirty || mutation.isPending}
            className="flex items-center gap-1.5 px-3 py-2 bg-gray-800 hover:bg-gray-700 disabled:opacity-50 text-gray-400 rounded-lg text-sm font-medium transition-colors"
          >
            <Undo2 size={14} />
            <span>Discard</span>
          </button>
          <button
            onClick={apply}
            disabled={!isDirty || mutation.isPending}
            className="flex items-center gap-1.5 px-4 py-2 bg-brand-600 hover:bg-brand-500 disabled:bg-gray-700 disabled:text-gray-500 text-white rounded-lg text-sm font-medium transition-colors"
          >
            {mutation.isPending ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Save size={14} />
            )}
            <span>Apply changes</span>
          </button>
        </div>
      </div>

      {isDirty && (
        <div className="mb-4 flex items-start gap-2 px-3 py-2.5 rounded-lg text-sm bg-amber-500/10 border border-amber-500/20 text-amber-400">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          <span>
            Nothing is live until you press Apply. Applying restarts the MCP server, which
            drops in-flight sessions from connected MCP clients.
          </span>
        </div>
      )}

      {mutation.isSuccess && !isDirty && status === 'ok' && (
        <div className="mb-4 flex items-center gap-2 px-3 py-2.5 rounded-lg text-sm bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
          <CheckCircle2 size={16} />
          <span>Applied — the MCP server restarted and is serving the new tool set.</span>
        </div>
      )}

      {/* "partial" means saved-but-not-live: the gateway is still serving the
          tool the operator just switched off. Never render that as success. */}
      {mutation.isSuccess && (status === 'partial' || status === 'detached') && (
        <div className="mb-4 flex items-start gap-2 px-3 py-2.5 rounded-lg text-sm bg-amber-500/10 border border-amber-500/20 text-amber-400">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          <span>
            {status === 'partial'
              ? 'Saved, but the MCP server did not restart — these changes are NOT live yet. Restart it from Settings.'
              : 'Saved, but no MCP process manager is attached — these changes are not live.'}
          </span>
        </div>
      )}

      {unknownTools.length > 0 && (
        <div className="mb-4 flex items-start gap-2 px-3 py-2.5 rounded-lg text-sm bg-amber-500/10 border border-amber-500/20 text-amber-400">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          <span>Ignored unknown tool names: {unknownTools.join(', ')}</span>
        </div>
      )}

      {/* The mutation used to fail silently: the switch snapped back and the
          only error UI on the page was bound to the GET query. */}
      {mutation.isError && (
        <div className="mb-4 flex items-start gap-2 px-3 py-2.5 rounded-lg text-sm bg-red-500/10 border border-red-500/20 text-red-400">
          <XCircle size={16} className="mt-0.5 shrink-0" />
          <span>Could not apply changes: {mutation.error.message}</span>
        </div>
      )}

      <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 mb-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-2">
            <ShieldAlert size={18} className="text-amber-400 mt-0.5 shrink-0" />
            <div>
              <p className="text-sm font-medium text-gray-200">Read-only mode</p>
              <p className="text-xs text-gray-500 mt-0.5">
                Suppresses every destructive tool (delete / block) regardless of its own
                switch. Turning it off restores them — that is why suppression is never
                written into the per-tool list.
              </p>
            </div>
          </div>
          <button
            onClick={() => setDraft((prev) => ({ ...prev, readonly: !prev.readonly }))}
            className="shrink-0"
            title={draft.readonly ? 'Disable read-only mode' : 'Enable read-only mode'}
          >
            {draft.readonly ? (
              <ToggleRight size={28} className="text-amber-400" />
            ) : (
              <ToggleLeft size={28} className="text-gray-600" />
            )}
          </button>
        </div>
      </div>

      <div className="relative mb-6">
        <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search tools by name, description, or category..."
          className="w-full pl-10 pr-4 py-2.5 bg-gray-900 border border-gray-800 rounded-lg text-gray-200 placeholder-gray-600 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 transition-colors"
        />
      </div>

      {categories.length === 0 ? (
        <div className="text-center py-12 text-gray-500">
          <Wrench size={32} className="mx-auto mb-3 opacity-50" />
          <p>No tools match your search</p>
        </div>
      ) : (
        <div className="space-y-6">
          {categories.map(([category, categoryTools]) => {
            const categoryOff = draft.disabledCategories.has(category);
            return (
              <div key={category}>
                <div className="flex items-center justify-between mb-3 px-1">
                  <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider">
                    {category}
                    <span className="ml-2 text-gray-600 font-normal">
                      ({categoryTools.length})
                    </span>
                    {categoryOff && (
                      <span className="ml-2 text-[10px] normal-case font-normal text-amber-400">
                        category off
                      </span>
                    )}
                  </h3>
                  <button
                    onClick={() => toggleCategory(category)}
                    title={
                      categoryOff
                        ? `Enable the whole ${category} category`
                        : `Disable the whole ${category} category`
                    }
                    className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-300 transition-colors"
                  >
                    <span>category</span>
                    {categoryOff ? (
                      <ToggleLeft size={22} className="text-gray-600" />
                    ) : (
                      <ToggleRight size={22} className="text-brand-500" />
                    )}
                  </button>
                </div>

                <div className="bg-gray-900 border border-gray-800 rounded-xl divide-y divide-gray-800">
                  {categoryTools.map((tool) => {
                    const state = effectiveFor(tool);
                    const disabledOps = draft.disabledOperations[tool.name] || [];
                    const operations = tool.operations || [];
                    const isOpen = Boolean(expanded[tool.name]);
                    return (
                      <div key={tool.name} className="px-4 py-3 hover:bg-gray-800/50 transition-colors">
                        <div className="flex items-center justify-between">
                          <div className="flex-1 min-w-0 mr-4">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="text-sm font-medium text-gray-200 font-mono">
                                {tool.name}
                              </span>
                              {tool.dangerous && (
                                <span
                                  className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase bg-amber-500/10 text-amber-400 border border-amber-500/20"
                                  title="Destructive — suppressed automatically in read-only mode"
                                >
                                  <AlertTriangle size={10} />
                                  destructive
                                </span>
                              )}
                              {/* Distinguish "off because of this switch" from
                                  "off because of category / read-only". */}
                              {state.offByReadonly && (
                                <span className="px-1.5 py-0.5 rounded text-[10px] uppercase bg-gray-700/60 text-gray-300 border border-gray-600">
                                  blocked by read-only
                                </span>
                              )}
                              {state.offByCategory && (
                                <span className="px-1.5 py-0.5 rounded text-[10px] uppercase bg-gray-700/60 text-gray-300 border border-gray-600">
                                  blocked by category
                                </span>
                              )}
                              {disabledOps.length > 0 && (
                                <span
                                  className="px-1.5 py-0.5 rounded text-[10px] uppercase bg-gray-700/60 text-gray-300 border border-gray-600"
                                  title={`Disabled operations: ${disabledOps.join(', ')}`}
                                >
                                  {disabledOps.length} op
                                  {disabledOps.length === 1 ? '' : 's'} off
                                </span>
                              )}
                            </div>
                            {tool.description && (
                              <p className="text-xs text-gray-500 mt-0.5 truncate">
                                {tool.description}
                              </p>
                            )}
                            {operations.length > 0 && (
                              <button
                                onClick={() =>
                                  setExpanded((prev) => ({
                                    ...prev,
                                    [tool.name]: !prev[tool.name],
                                  }))
                                }
                                className="mt-1 flex items-center gap-1 text-[11px] text-gray-500 hover:text-gray-300 transition-colors"
                              >
                                {isOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                                <span>{operations.length} operations</span>
                              </button>
                            )}
                          </div>

                          <button
                            onClick={() => toggleTool(tool.name)}
                            disabled={mutation.isPending}
                            className="shrink-0 disabled:opacity-50 transition-opacity"
                            title={
                              state.offByName
                                ? 'Enable this tool'
                                : state.enabled
                                  ? 'Disable this tool'
                                  : 'This tool is on, but something else is suppressing it'
                            }
                          >
                            {state.offByName ? (
                              <ToggleLeft size={28} className="text-gray-600" />
                            ) : (
                              <ToggleRight
                                size={28}
                                className={state.enabled ? 'text-brand-500' : 'text-gray-500'}
                              />
                            )}
                          </button>
                        </div>

                        {isOpen && operations.length > 0 && (
                          <div className="mt-2 pl-1 flex flex-wrap gap-2">
                            {operations.map((op) => {
                              const opOff = disabledOps.includes(op.name);
                              return (
                                <button
                                  key={op.name}
                                  onClick={() => toggleOperation(tool.name, op.name)}
                                  className={`px-2 py-1 rounded text-[11px] font-mono border transition-colors ${
                                    opOff
                                      ? 'bg-gray-800 text-gray-500 border-gray-700 line-through'
                                      : 'bg-brand-600/10 text-brand-400 border-brand-600/30'
                                  }`}
                                  title={opOff ? 'Enable this operation' : 'Disable this operation'}
                                >
                                  {op.name}
                                </button>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
