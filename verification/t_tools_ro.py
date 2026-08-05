"""Re-verify finding #89: a gated tool must explain itself, not 404.

Flips read-only ON through the real admin API (the same call the GUI makes),
drives the real MCP endpoint through the encrypted proxy path, then restores
the original tools configuration no matter what happened.
"""
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcpc

results = []


def check(name, ok, detail=''):
    results.append((ok, name, detail))
    print(('PASS' if ok else 'FAIL'), '|', name, '|', str(detail)[:300])


def wait_for_mcp(expect_min=1, tries=30):
    """The child process restarts on every save; poll until it answers again."""
    for _ in range(tries):
        try:
            with mcpc.Session() as s:
                t = s.list_tools()
                if len(t) >= expect_min:
                    return t
        except Exception:
            pass
        time.sleep(2)
    return []


st, before = mcpc.api('/api/tools')
assert st == 200, before
original = {k: before[k] for k in
            ('readonly', 'disabled_categories', 'disabled_tools', 'disabled_operations')}
print('ORIGINAL', json.dumps(original))

try:
    st, _ = mcpc.api('/api/tools', {'readonly': True}, method='PUT')
    check('#89a PUT /api/tools readonly=true accepted', st == 200, st)

    tools = wait_for_mcp(1)
    check('#89b read-only shrinks tools/list below the full 40',
          0 < len(tools) < 40, '%d tools exposed' % len(tools))
    check('#89c litellm_generate_key is gated off in read-only',
          'litellm_generate_key' not in tools)

    with mcpc.Session() as s:
        m = mcpc.text_of(s.call('litellm_generate_key'))
        check('#89 refusal is readable (was: "Unknown tool")',
              'Unknown tool' not in m and 'read-only mode' in m
              and 'litellm_generate_key' in m, m)

        m2 = mcpc.text_of(s.call('litellm_delete_key', {'key': 'mcptest-never'}))
        check('#89d destructive tool names destructiveness',
              'Unknown tool' not in m2 and 'read-only mode' in m2, m2)

        m3 = mcpc.text_of(s.call('litellm_no_such_tool'))
        check('#89e a genuinely unknown name still says "Unknown tool"',
              'Unknown tool' in m3, m3)

        m4 = mcpc.text_of(s.call('litellm_list_models'))
        check('#89f an ENABLED tool still works while read-only is on',
              'gpt-4o-mini' in m4, m4[:200])
finally:
    st, after = mcpc.api('/api/tools', original, method='PUT')
    restored = {k: after.get(k) for k in original}
    check('#89z original tools config restored',
          st == 200 and restored == original, json.dumps(restored))
    tools = wait_for_mcp(40)
    check('#89z all 40 tools exposed again', len(tools) == 40, len(tools))

bad = [r for r in results if not r[0]]
print('\nSUMMARY %d/%d passed' % (len(results) - len(bad), len(results)))
sys.exit(1 if bad else 0)
