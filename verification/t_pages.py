"""Every admin-console page's backing API: reachable, authenticated, LiteLLM-shaped."""
import sys, json, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcpc

R = []


def check(name, ok, detail=''):
    R.append((ok, name))
    print(('PASS' if ok else 'FAIL'), '|', name, '|', str(detail)[:220])


# --- SPA shell + static assets (the pages themselves) ----------------------
for path in ['/', '/dashboard', '/connection', '/tools', '/permissions',
             '/tokens', '/logs', '/settings']:
    st, hd, body = mcpc._req(mcpc.ADMIN + path)
    check('SPA route %s serves the app shell' % path,
          st == 200 and '<div id="root"' in body, st)

# --- auth gate ------------------------------------------------------------
st, _, _ = mcpc._req(mcpc.ADMIN + '/api/tools')
check('/api/* rejects an unauthenticated request', st in (401, 403), st)
st, _, _ = mcpc._req(mcpc.ADMIN + '/healthz')
check('/healthz is public (probe target)', st == 200, st)

# --- Dashboard / health ---------------------------------------------------
st, h = mcpc.api('/api/health')
check('Dashboard: /api/health 200', st == 200, st)
check('Dashboard: reports the MCP child process state',
      isinstance(h, dict) and len(h) > 0, json.dumps(h)[:220])

# --- Connection page ------------------------------------------------------
st, c = mcpc.api('/api/config')
check('Connection: /api/config 200', st == 200, st)
check('Connection: app_type is litellm (not a leftover EMQX default)',
      c.get('app_type') == 'litellm', c.get('app_type'))
check('Connection: shows the LiteLLM base URL',
      'litellm' in str(c.get('litellm_mcp_base_url', '')), c.get('litellm_mcp_base_url'))
# Read the real key at runtime rather than inlining it: a literal here would
# be a plaintext production credential sitting in the repo, and it would also
# make the assertion silently vacuous the moment the key is rotated.
_REAL_MASTER_KEY = str(
    (mcpc.CFG.get('connection') or {}).get('litellm_mcp_master_key', '') or ''
)
mk = str(c.get('litellm_mcp_master_key_masked', ''))
check('Connection: master key is masked, never echoed in full',
      mk != '' and _REAL_MASTER_KEY != '' and _REAL_MASTER_KEY not in mk,
      mk)
st, t = mcpc.api('/api/config/test', {}, method='POST')
check('Connection: "Test connection" really probes LiteLLM',
      st == 200 and t.get('status') == 'healthy'
      and t.get('model_count') == 5, json.dumps(t)[:220])

# --- Tools page -----------------------------------------------------------
st, tl = mcpc.api('/api/tools')
check('Tools: /api/tools 200', st == 200, st)
check('Tools: all 40 registry tools listed', tl.get('total') == 40, tl.get('total'))
check('Tools: 40 enabled with the default open gate',
      tl.get('enabled_count') == 40, tl.get('enabled_count'))
# /api/tools groups tools as [{"category": "models", "enabled": …, "tools": […]}]
# and ToolManager.jsx destructures the same key. An earlier revision of this
# check read c['name'] and died with a KeyError that aborted the whole suite
# before the summary printed — so accept either spelling and never raise.
cats = {
    (c.get('category') or c.get('name')) if isinstance(c, dict) else c
    for c in (tl.get('categories') or [])
}
cats.discard(None)
check('Tools: grouped into LiteLLM domains, not generic ones',
      {'models', 'keys'} <= cats, sorted(cats))
check('Tools: every tool declares its operations',
      all(t.get('operations') for t in tl['tools']),
      [t['name'] for t in tl['tools'] if not t.get('operations')])
check('Tools: destructive tools are flagged dangerous',
      all(t['dangerous'] for t in tl['tools']
          if t['name'] in ('litellm_delete_key', 'litellm_delete_team',
                           'litellm_delete_user', 'litellm_delete_model')))

# --- Permissions page -----------------------------------------------------
check('Permissions: policy is served with the config',
      isinstance(c.get('permissions'), dict), json.dumps(c.get('permissions'))[:220])
check('Permissions: default policy allows everything',
      c['permissions'].get('allowed_tools') == ['*']
      and not c['permissions'].get('denied_tools'), json.dumps(c['permissions']))

# --- Tokens page ----------------------------------------------------------
st, tk = mcpc.api('/api/tokens')
check('Tokens: /api/tokens 200', st == 200, st)
blob = json.dumps(tk)
check('Tokens: the live token is never returned in full',
      mcpc.TOKEN not in blob, blob[:220])
st, gen = mcpc.api('/api/tokens/generate', {}, method='POST')
check('Tokens: generate PREVIEWS a candidate without rotating',
      st == 200 and isinstance(gen, dict), json.dumps(gen)[:120])
st2, cfg_after = mcpc.api('/api/config')
check('Tokens: generate did NOT change the live token (connector survives)',
      json.load(open('/data/config.json'))['mcp_auth_token'] == mcpc.TOKEN)

# --- Settings page --------------------------------------------------------
st, s = mcpc.api('/api/settings')
check('Settings: /api/settings 200', st == 200, st)
for section in ('connection', 'tools', 'mcp_server', 'proxy'):
    st, sec = mcpc.api('/api/settings/' + section)
    check('Settings: section %s readable' % section, st == 200, st)
st, ms = mcpc.api('/api/settings/mcp/status')
check('Settings: MCP child process status reported',
      st == 200 and isinstance(ms, dict), json.dumps(ms)[:220])

bad = [r for r in R if not r[0]]
print('\nSUMMARY %d/%d passed' % (len(R) - len(bad), len(R)))
for _, n in bad:
    print('  FAILED:', n)
