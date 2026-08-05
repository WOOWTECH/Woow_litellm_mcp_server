"""Exercise ALL 40 litellm_* tools over the live encrypted-proxy MCP endpoint.

Destructive tools only ever touch resources this run created, all named with an
``mcptest-`` prefix. Everything created is torn down in the finally block.
"""
import json, time, datetime
import mcpc

P = F = 0
CALLED = set()
FAILED = []

def check(name, ok, detail=''):
    global P, F
    if ok:
        P += 1; print('PASS |', name, '|', str(detail)[:180])
    else:
        F += 1; FAILED.append(name); print('FAIL |', name, '|', str(detail)[:600])

def body(resp):
    """(is_error, parsed_or_text) for a tools/call result."""
    if 'error' in resp:
        return True, resp['error']
    res = resp.get('result', {})
    txt = ' '.join(c.get('text','') for c in (res.get('content') or []) if isinstance(c, dict))
    if res.get('structuredContent') is not None:
        return bool(res.get('isError')), res['structuredContent']
    try:
        return bool(res.get('isError')), json.loads(txt)
    except Exception:
        return bool(res.get('isError')), txt

TAG = 'mcptest-%d' % int(time.time())
today = datetime.date.today()
START = (today - datetime.timedelta(days=30)).isoformat()
END = (today + datetime.timedelta(days=1)).isoformat()

state = {}

def run(sess, tool, args, name, assertion=None):
    """Call a tool, record that it was exercised, assert it really worked."""
    CALLED.add(tool)
    r = sess.call(tool, args)
    err, data = body(r)
    if err:
        check(name, False, data)
        return None
    if assertion is not None:
        try:
            ok, detail = assertion(data)
        except Exception as e:
            ok, detail = False, '%r on %s' % (e, json.dumps(data)[:200])
        check(name, ok, detail if detail else json.dumps(data)[:180])
    else:
        check(name, True, json.dumps(data)[:180])
    return data

with mcpc.Session() as s:
    exposed = set(s.list_tools())
    check('all-tools: the live server exposes 40 tools', len(exposed) == 40, len(exposed))

    try:
        # ---------------------------------------------------------- health (2)
        run(s, 'litellm_health', {}, 'health: litellm_health reports every model healthy',
            lambda d: (d.get('unhealthy_count') == 0 and d.get('healthy_count', 0) > 0,
                       'healthy=%s unhealthy=%s' % (d.get('healthy_count'), d.get('unhealthy_count'))))
        run(s, 'litellm_health_readiness', {}, 'health: litellm_health_readiness says the gateway is ready',
            lambda d: (str(d.get('status','')).lower() in ('healthy','connected','ok'), d.get('status')))

        # ---------------------------------------------------------- models (6)
        base = run(s, 'litellm_list_models', {}, 'models: litellm_list_models lists the catalogue',
                   lambda d: (len(d.get('data', d if isinstance(d, list) else [])) >= 5,
                              [m.get('id') for m in d.get('data', [])][:8]))
        base_names = [m.get('id') for m in (base or {}).get('data', [])]
        check('models: the retired claude-3.5-sonnet slug is gone and 4.5 is present',
              'claude-3.5-sonnet' not in base_names and 'claude-sonnet-4.5' in base_names, base_names)

        run(s, 'litellm_model_info', {}, 'models: litellm_model_info returns the deployment records',
            lambda d: (len(d.get('data', [])) > 0, len(d.get('data', []))))
        run(s, 'litellm_model_group_info', {}, 'models: litellm_model_group_info returns model groups',
            lambda d: (len(d.get('data', d if isinstance(d, list) else [])) > 0, json.dumps(d)[:120]))

        # The os.environ/ pre-flight guard. /model/new does NOT expand that
        # form: it encrypts the literal text as the secret, answers 200, and
        # leaves a deployment that 401s on every request forever. The refusal
        # has to happen before the request goes out, and it has to name the fix.
        CALLED.add('litellm_add_model')
        berr, bdata = body(s.call('litellm_add_model',
                                  {'model_name': TAG + '-badmodel',
                                   'litellm_params': {
                                       'model': 'openrouter/openai/gpt-4o-mini',
                                       'api_key': 'os.environ/OPENROUTER_API_KEY'}}))
        btxt = json.dumps(bdata)
        check('models: an os.environ/ api_key is refused up front, not stored',
              berr and 'os.environ/NAME' in btxt and 'omit' in btxt.lower(), btxt[:300])
        er2, mods2 = body(s.call('litellm_model_info', {}))
        check('models: the refused model was never created on the gateway',
              not er2 and not any(m.get('model_name') == TAG + '-badmodel'
                                  for m in mods2.get('data', [])), 'absent')

        # Omitting api_key is the form that actually works: LiteLLM falls back
        # to the OPENROUTER_API_KEY the gateway process already holds.
        added = run(s, 'litellm_add_model',
                    {'model_name': TAG + '-model',
                     'litellm_params': {'model': 'openrouter/openai/gpt-4o-mini',
                                        'api_base': 'https://openrouter.ai/api/v1'}},
                    'models: litellm_add_model creates a deployment')
        info = run(s, 'litellm_model_info', {}, 'models: the new model is visible in model_info',
                   lambda d: (any(m.get('model_name') == TAG + '-model' for m in d.get('data', [])), TAG + '-model'))
        for m in (info or {}).get('data', []):
            if m.get('model_name') == TAG + '-model':
                state['model_id'] = (m.get('model_info') or {}).get('id')
        check('models: the created deployment has an id we can act on', bool(state.get('model_id')), state.get('model_id'))

        if state.get('model_id'):
            # A rename with NO litellm_params is the exact shape that used to
            # fail: LiteLLM's update handler rejects a body without that field,
            # so the tool now always sends {} (= "change nothing about routing
            # or credentials") and the rename goes through.
            run(s, 'litellm_update_model',
                {'model_id': state['model_id'], 'model_name': TAG + '-renamed'},
                'models: litellm_update_model renames it with no litellm_params')
            after = run(s, 'litellm_model_info', {}, 'models: the rename actually persisted',
                        lambda d: (any(m.get('model_name') == TAG + '-renamed'
                                       for m in d.get('data', [])), 'renamed'))
            # ...and "change nothing" really did change nothing: the routing
            # target and the inherited credential must have survived the update.
            check('models: the update left litellm_params intact',
                  any(m.get('model_name') == TAG + '-renamed'
                      and (m.get('litellm_params') or {}).get('model') == 'openrouter/openai/gpt-4o-mini'
                      for m in (after or {}).get('data', [])),
                  'model target preserved')
            run(s, 'litellm_delete_model', {'model_id': state['model_id']},
                'models: litellm_delete_model removes it')
            gone = run(s, 'litellm_model_info', {}, 'models: the deployment is really gone afterwards',
                       lambda d: (not any(str(m.get('model_name','')).startswith(TAG)
                                          for m in d.get('data', [])), 'removed'))
            state.pop('model_id', None)

        # ------------------------------------------------------------ chat (2)
        run(s, 'litellm_chat_completion',
            {'model': 'gpt-4o-mini',
             'messages': [{'role': 'user', 'content': 'Reply with exactly: PONG'}],
             'max_tokens': 8, 'temperature': 0},
            'chat: litellm_chat_completion returns a real completion',
            lambda d: ('PONG' in d['choices'][0]['message']['content'].upper(),
                       d['choices'][0]['message']['content'][:60]))
        run(s, 'litellm_token_counter', {'model': 'gpt-4o-mini', 'prompt': 'hello world hello world'},
            'chat: litellm_token_counter counts tokens',
            lambda d: (int(d.get('total_tokens', 0)) > 0, d))

        # ------------------------------------------------------------ keys (8)
        k = run(s, 'litellm_generate_key',
                {'key_alias': TAG + '-key', 'models': ['gpt-4o-mini'], 'max_budget': 0.01,
                 'duration': '1h'},
                'keys: litellm_generate_key mints a virtual key',
                lambda d: (str(d.get('key','')).startswith('sk-'), 'sk-****' ))
        if k: state['key'] = k['key']

        if state.get('key'):
            run(s, 'litellm_key_info', {'key': state['key']},
                'keys: litellm_key_info reads it back',
                lambda d: ((d.get('info') or d).get('key_alias') == TAG + '-key',
                           (d.get('info') or d).get('key_alias')))
            run(s, 'litellm_list_keys', {'key_alias': TAG + '-key'},
                'keys: litellm_list_keys finds it by alias',
                lambda d: (len(d.get('keys', [])) >= 1, len(d.get('keys', []))))
            run(s, 'litellm_update_key', {'key': state['key'], 'max_budget': 0.02},
                'keys: litellm_update_key changes the budget')
            run(s, 'litellm_key_info', {'key': state['key']},
                'keys: the budget change persisted',
                lambda d: (float((d.get('info') or d).get('max_budget')) == 0.02,
                           (d.get('info') or d).get('max_budget')))
            run(s, 'litellm_block_key', {'key': state['key']}, 'keys: litellm_block_key blocks it')
            run(s, 'litellm_key_info', {'key': state['key']},
                'keys: the key reads back as blocked',
                lambda d: ((d.get('info') or d).get('blocked') is True, (d.get('info') or d).get('blocked')))
            run(s, 'litellm_unblock_key', {'key': state['key']}, 'keys: litellm_unblock_key unblocks it')
            run(s, 'litellm_key_info', {'key': state['key']},
                'keys: the key reads back as unblocked',
                lambda d: (not (d.get('info') or d).get('blocked'), (d.get('info') or d).get('blocked')))
            # Key regeneration is Enterprise-gated and this gateway is the
            # community edition, so the honest outcome is a clear "unavailable,
            # do not retry" — not the raw 500 + sales copy LiteLLM returns.
            CALLED.add('litellm_regenerate_key')
            rgerr, rg = body(s.call('litellm_regenerate_key', {'key': state['key']}))
            rgtxt = json.dumps(rg)
            if rgerr:
                check('keys: litellm_regenerate_key names the Enterprise gate, not a server fault',
                      'Enterprise' in rgtxt and 'community edition' in rgtxt
                      and 'retrying will not help' in rgtxt, rgtxt[:300])
            else:
                check('keys: litellm_regenerate_key issues a replacement',
                      str(rg.get('key','')).startswith('sk-') and rg.get('key') != state['key'],
                      'new sk-****')
                if rg.get('key'): state['key'] = rg['key']
            run(s, 'litellm_delete_key', {'keys': [state['key']]},
                'keys: litellm_delete_key deletes only the key we made')
            left = run(s, 'litellm_list_keys', {'key_alias': TAG + '-key'},
                       'keys: the test key is really gone',
                       lambda d: (len(d.get('keys', [])) == 0, len(d.get('keys', []))))
            state.pop('key', None)

        # ----------------------------------------------------------- users (5)
        u = run(s, 'litellm_create_user',
                {'user_id': TAG + '-user', 'user_email': TAG + '@example.invalid',
                 'user_role': 'internal_user', 'auto_create_key': False},
                'users: litellm_create_user creates an internal user',
                lambda d: (d.get('user_id') == TAG + '-user', d.get('user_id')))
        if u: state['user_id'] = u.get('user_id')

        if state.get('user_id'):
            run(s, 'litellm_user_info', {'user_id': state['user_id']},
                'users: litellm_user_info reads it back',
                lambda d: (json.dumps(d).find(state['user_id']) >= 0, 'found'))
            run(s, 'litellm_list_users', {'user_email': TAG + '@example.invalid'},
                'users: litellm_list_users finds it',
                lambda d: (json.dumps(d).find(TAG) >= 0, 'found'))
            run(s, 'litellm_update_user', {'user_id': state['user_id'], 'user_alias': 'verification probe'},
                'users: litellm_update_user updates it')
            run(s, 'litellm_user_info', {'user_id': state['user_id']},
                'users: the user update persisted',
                lambda d: ('verification probe' in json.dumps(d), 'alias written back'))

        # ----------------------------------------------------------- teams (7)
        t = run(s, 'litellm_create_team', {'team_alias': TAG + '-team', 'models': ['gpt-4o-mini']},
                'teams: litellm_create_team creates a team',
                lambda d: (bool(d.get('team_id')), d.get('team_alias')))
        if t: state['team_id'] = t.get('team_id')

        if state.get('team_id'):
            run(s, 'litellm_team_info', {'team_id': state['team_id']},
                'teams: litellm_team_info reads it back',
                lambda d: (json.dumps(d).find(TAG + '-team') >= 0, 'found'))
            run(s, 'litellm_list_teams', {'team_alias': TAG + '-team'},
                'teams: litellm_list_teams finds it')
            run(s, 'litellm_update_team', {'team_id': state['team_id'], 'max_budget': 1.0},
                'teams: litellm_update_team updates it')
            run(s, 'litellm_team_info', {'team_id': state['team_id']},
                'teams: the team update persisted',
                lambda d: ('1.0' in json.dumps(d) or '1,' in json.dumps(d), 'budget written back'))
            if state.get('user_id'):
                run(s, 'litellm_team_member_add',
                    {'team_id': state['team_id'], 'user_id': state['user_id'], 'role': 'user'},
                    'teams: litellm_team_member_add adds our test user')
                run(s, 'litellm_team_info', {'team_id': state['team_id']},
                    'teams: the member really is on the team',
                    lambda d: (state['user_id'] in json.dumps(d), 'member present'))
                run(s, 'litellm_team_member_delete',
                    {'team_id': state['team_id'], 'user_id': state['user_id']},
                    'teams: litellm_team_member_delete removes them')
            run(s, 'litellm_delete_team', {'team_ids': [state['team_id']]},
                'teams: litellm_delete_team deletes only our team')
            state.pop('team_id', None)

        if state.get('user_id'):
            run(s, 'litellm_delete_user', {'user_ids': [state['user_id']]},
                'users: litellm_delete_user deletes only our user')
            state.pop('user_id', None)

        # ----------------------------------------------------------- spend (3)
        run(s, 'litellm_spend_logs', {'start_date': START, 'end_date': END},
            'spend: litellm_spend_logs returns log rows',
            lambda d: (isinstance(d, (list, dict)), 'rows=%s' % (len(d) if isinstance(d, list) else list(d)[:4])))
        run(s, 'litellm_global_spend_report', {'start_date': START, 'end_date': END, 'group_by': 'team'},
            'spend: litellm_global_spend_report returns a report',
            lambda d: (isinstance(d, (list, dict)), json.dumps(d)[:120]))
        run(s, 'litellm_spend_calculate',
            {'model': 'gpt-4o-mini', 'messages': [{'role': 'user', 'content': 'hello'}]},
            'spend: litellm_spend_calculate prices a request',
            lambda d: ('cost' in json.dumps(d).lower(), json.dumps(d)[:120]))

        # --------------------------------------------------------- plugins (7)
        run(s, 'litellm_list_plugins', {}, 'plugins: litellm_list_plugins lists the hub')
        run(s, 'litellm_skill_hub', {}, 'plugins: litellm_skill_hub fetches the public catalogue')
        reg = run(s, 'litellm_register_plugin',
                  {'name': TAG + '-plugin', 'source': {'source': 'github', 'repo': 'WOOWTECH/Woow_litellm_mcp_server'},
                   'description': 'MCP verification probe', 'version': '0.0.1'},
                  'plugins: litellm_register_plugin registers one')
        if reg is not None:
            state['plugin'] = TAG + '-plugin'
            run(s, 'litellm_plugin_info', {'plugin_name': state['plugin']},
                'plugins: litellm_plugin_info reads it back',
                lambda d: (TAG in json.dumps(d), 'found'))
            run(s, 'litellm_enable_plugin', {'plugin_name': state['plugin']},
                'plugins: litellm_enable_plugin enables it')
            run(s, 'litellm_list_plugins', {'enabled_only': True},
                'plugins: it shows up in the enabled-only listing',
                lambda d: (TAG in json.dumps(d), 'listed'))
            run(s, 'litellm_disable_plugin', {'plugin_name': state['plugin']},
                'plugins: litellm_disable_plugin disables it')
            run(s, 'litellm_delete_plugin', {'plugin_name': state['plugin']},
                'plugins: litellm_delete_plugin removes it')
            state.pop('plugin', None)

    finally:
        # ------------------------------------------------- best-effort teardown
        for tool, args in (('litellm_delete_key', {'keys': [state['key']]} if state.get('key') else None),
                           ('litellm_delete_team', {'team_ids': [state['team_id']]} if state.get('team_id') else None),
                           ('litellm_delete_user', {'user_ids': [state['user_id']]} if state.get('user_id') else None),
                           ('litellm_delete_model', {'model_id': state['model_id']} if state.get('model_id') else None),
                           ('litellm_delete_plugin', {'plugin_name': state['plugin']} if state.get('plugin') else None)):
            if args:
                try:
                    s.call(tool, args); print('CLEANUP', tool, list(args.values())[0])
                except Exception as e:
                    print('CLEANUP FAILED', tool, repr(e))

        # ----------------------------------------------- nothing left behind
        er, keys = body(s.call('litellm_list_keys', {'key_alias': TAG + '-key'}))
        check('teardown: no mcptest key survives', not er and len(keys.get('keys', [])) == 0, keys if er else len(keys.get('keys', [])))
        er, mods = body(s.call('litellm_model_info', {}))
        check('teardown: no mcptest model survives',
              not er and not any('mcptest' in str(m.get('model_name','')) for m in mods.get('data', [])), 'clean')
        er, tl = body(s.call('litellm_list_teams', {'team_alias': TAG + '-team'}))
        check('teardown: no mcptest team survives', not er and TAG not in json.dumps(tl), 'clean')
        # LiteLLM's router keeps a just-deleted deployment in its in-memory
        # model list for one refresh cycle (~10s), and /health probes whatever
        # the router currently holds — so a health check fired immediately
        # after litellm_delete_model reports the corpse as unhealthy. Settle
        # before asserting, and say how long it took.
        er, hl, waited = True, {}, 0
        for attempt in range(12):
            er, hl = body(s.call('litellm_health', {}))
            if not er and hl.get('unhealthy_count') == 0 and hl.get('healthy_count', 0) >= 5:
                break
            waited += 6
            time.sleep(6)
        check('teardown: the gateway is still fully healthy after the run',
              not er and hl.get('unhealthy_count') == 0 and hl.get('healthy_count', 0) >= 5,
              'healthy=%s unhealthy=%s (settled after %ds)'
              % (hl.get('healthy_count'), hl.get('unhealthy_count'), waited) if not er else hl)

        missing = sorted(exposed - CALLED)
        check('coverage: every one of the 40 exposed tools was actually called',
              not missing, missing or '40/40')
        print()
        print('TOOLS CALLED %d/%d' % (len(CALLED), len(exposed)))
        if FAILED:
            print('FAILING CHECKS:')
            for n in FAILED: print('  -', n)
        print('SUMMARY %d/%d passed' % (P, P + F))
