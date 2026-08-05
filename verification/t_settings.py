"""Every switch on every settings page must actually change the MCP surface.

Each case: read the original, apply through the real admin API, observe the
live MCP endpoint, then restore. The restore runs in a finally block so a
failure mid-suite cannot leave the connector crippled.
"""
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcpc

R = []


def check(name, ok, detail=''):
    R.append((ok, name))
    print(('PASS' if ok else 'FAIL'), '|', name, '|', str(detail)[:240])


def mcp_tools(tries=30):
    for _ in range(tries):
        try:
            with mcpc.Session() as s:
                return s.list_tools()
        except Exception:
            time.sleep(2)
    return None


def call_text(name, args=None, tries=15):
    for _ in range(tries):
        try:
            with mcpc.Session() as s:
                return mcpc.text_of(s.call(name, args))
        except Exception:
            time.sleep(2)
    return ''


st, before = mcpc.api('/api/tools')
ORIG_TOOLS = {k: before[k] for k in
              ('readonly', 'disabled_categories', 'disabled_tools', 'disabled_operations')}
st, cfg0 = mcpc.api('/api/config')
ORIG_PERMS = dict(cfg0['permissions'])
ORIG_CONN_URL = cfg0['litellm_mcp_base_url']
stored_master = json.load(open('/data/config.json'))['connection']['litellm_mcp_master_key']
print('ORIG tools', json.dumps(ORIG_TOOLS))
print('ORIG perms', json.dumps(ORIG_PERMS))

baseline = mcp_tools()
check('baseline: 40 tools exposed', len(baseline) == 40, len(baseline))

try:
    # 1 -- category switch -------------------------------------------------
    mcpc.api('/api/tools', {'disabled_categories': ['keys']}, method='PUT')
    t = mcp_tools()
    check('setting disabled_categories=[keys] removes every keys tool',
          t is not None and not any(n.endswith('_key') or '_key' in n or n.endswith('_keys')
                                    for n in t) and len(t) < 40,
          '%d tools' % len(t))
    m = call_text('litellm_list_keys')
    check('a keys tool now explains it was killed by its CATEGORY',
          "category 'keys'" in m, m)
    mcpc.api('/api/tools', {'disabled_categories': []}, method='PUT')
    check('restoring the category brings the tools back', len(mcp_tools()) == 40)

    # 2 -- individual tool switch -----------------------------------------
    mcpc.api('/api/tools', {'disabled_tools': ['litellm_list_models']}, method='PUT')
    t = mcp_tools()
    check('setting disabled_tools removes exactly that one tool',
          'litellm_list_models' not in t and len(t) == 39, '%d tools' % len(t))
    m = call_text('litellm_list_models')
    check('it explains it was switched off INDIVIDUALLY', 'individually' in m, m)
    st, v = mcpc.api('/api/tools')
    check('the Tools page mirrors the switch into the permission policy',
          v['tools'] and any(x['name'] == 'litellm_list_models' and not x['enabled']
                             for x in v['tools']))
    st, c = mcpc.api('/api/config')
    check('the Permissions page renders the same reality (no drift)',
          'litellm_list_models' in (c['permissions'].get('denied_tools') or []),
          json.dumps(c['permissions']))
    mcpc.api('/api/tools', {'disabled_tools': []}, method='PUT')
    check('restoring the tool switch brings it back', len(mcp_tools()) == 40)

    # 3 -- operation switch (the column that used to be decorative) --------
    mcpc.api('/api/tools', {'disabled_operations': {'litellm_health': ['read']}},
             method='PUT')
    t = mcp_tools()
    check("disabling a tool's only operation removes the tool",
          'litellm_health' not in t and len(t) == 39, '%d tools' % len(t))
    m = call_text('litellm_health')
    check('it explains the OPERATION POLICY is responsible',
          'operation policy' in m, m)
    mcpc.api('/api/tools', {'disabled_operations': {}}, method='PUT')
    check('restoring the operation brings it back', len(mcp_tools()) == 40)

    # 4 -- permissions: deny list -----------------------------------------
    mcpc.api('/api/config/permissions',
             {'permissions': {'allowed_tools': ['*'],
                              'denied_tools': ['litellm_delete_key']}}, method='PUT')
    t = mcp_tools()
    check('Permissions deny list removes the tool from MCP',
          'litellm_delete_key' not in t and len(t) == 39, '%d tools' % len(t))

    # 5 -- permissions: allow list ----------------------------------------
    mcpc.api('/api/config/permissions',
             {'permissions': {'allowed_tools': ['litellm_health', 'litellm_list_models'],
                              'denied_tools': []}}, method='PUT')
    t = mcp_tools()
    check('Permissions allow list keeps ONLY the named tools',
          sorted(t) == ['litellm_health', 'litellm_list_models'], t)

    # 6 -- permissions: empty allow list must fail CLOSED ------------------
    mcpc.api('/api/config/permissions',
             {'permissions': {'allowed_tools': [], 'denied_tools': []}}, method='PUT')
    t = mcp_tools(tries=8)
    check('an EMPTY allow list means allow nothing (fails closed)',
          t == [], t)

    # 7 -- unknown names are rejected, not silently stored -----------------
    st, resp = mcpc.api('/api/config/permissions',
                        {'permissions': {'allowed_tools': ['*'],
                                         'denied_tools': ['zzz_no_such_tool']}},
                        method='PUT')
    stored = json.load(open('/data/config.json'))['tools']['permissions']
    check('an unknown tool name is dropped rather than polluting the config',
          'zzz_no_such_tool' not in json.dumps(stored), json.dumps(stored))

    # 8 -- connection: a blank master key must NOT wipe the stored one -----
    mcpc.api('/api/config/connection',
             {'litellm_mcp_base_url': ORIG_CONN_URL,
              'litellm_mcp_master_key': '', 'restart': False}, method='PUT')
    now = json.load(open('/data/config.json'))['connection']['litellm_mcp_master_key']
    check('saving Connection with a blank key keeps the real key (no lockout)',
          now == stored_master)
    mcpc.api('/api/config/connection',
             {'litellm_mcp_base_url': ORIG_CONN_URL,
              'litellm_mcp_master_key': 'sk-b…', 'restart': False}, method='PUT')
    now = json.load(open('/data/config.json'))['connection']['litellm_mcp_master_key']
    check('echoing the MASKED key back also keeps the real key',
          now == stored_master)

    # 9 -- settings sections round-trip ------------------------------------
    mcpc.api('/api/settings/proxy', {'value': {'timeout': 1234}}, method='PUT')
    st, sec = mcpc.api('/api/settings/proxy')
    ok = json.dumps(sec).find('1234') >= 0
    check('Settings: a proxy section edit persists', ok, json.dumps(sec)[:200])
    mcpc.api('/api/settings/proxy', {'value': {'timeout': 86400}}, method='PUT')
    st, sec = mcpc.api('/api/settings/proxy')
    check('Settings: the proxy section restores', '86400' in json.dumps(sec),
          json.dumps(sec)[:200])
finally:
    mcpc.api('/api/config/permissions', {'permissions': ORIG_PERMS}, method='PUT')
    mcpc.api('/api/tools', ORIG_TOOLS, method='PUT')
    st, after = mcpc.api('/api/tools')
    check('RESTORE: tools config back to original',
          {k: after[k] for k in ORIG_TOOLS} == ORIG_TOOLS,
          json.dumps({k: after[k] for k in ORIG_TOOLS}))
    st, c = mcpc.api('/api/config')
    check('RESTORE: permission policy back to original',
          c['permissions'] == ORIG_PERMS, json.dumps(c['permissions']))
    check('RESTORE: master key untouched',
          json.load(open('/data/config.json'))['connection']['litellm_mcp_master_key']
          == stored_master)
    t = mcp_tools()
    check('RESTORE: all 40 tools live again', len(t) == 40, len(t))

bad = [r for r in R if not r[0]]
print('\nSUMMARY %d/%d passed' % (len(R) - len(bad), len(R)))
for _, n in bad:
    print('  FAILED:', n)
