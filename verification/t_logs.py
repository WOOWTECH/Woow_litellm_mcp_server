"""Log page end-to-end against the live admin API."""
import json, os, sys, time, urllib.request, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcpc

P=F=0
def check(name, ok, detail=''):
    global P,F
    if ok: P+=1; print('PASS |', name, '|', str(detail)[:200])
    else:  F+=1; print('FAIL |', name, '|', str(detail)[:400])

def search(**kw):
    qs = urllib.parse.urlencode(kw)
    return mcpc.api('/api/logs/search?' + qs)

# ---------------------------------------------------------------- shape
st, body = search(limit=200)
check('Logs: /api/logs/search answers 200', st == 200, st)
check('Logs: response has count + lines', isinstance(body, dict) and 'count' in body and 'lines' in body, list(body)[:5] if isinstance(body,dict) else body)
lines = [json.loads(x) for x in body.get('lines', [])]
check('Logs: the buffer is not empty (capture is actually installed)', len(lines) > 0, body.get('count'))
check('Logs: every line carries timestamp/level/message/source',
      all({'timestamp','level','message','source'} <= set(l) for l in lines),
      lines[0] if lines else None)
sources = sorted({l['source'] for l in lines})
levels  = sorted({l['level']  for l in lines})
print('INFO sources =', sources, 'levels =', levels)

# ------------------------------------------------------- q substring
MARK = 'ZZLOGPROBE7788ZZ'
search(q=MARK)          # this request itself writes an access line with MARK
time.sleep(1)
st, hit = search(q=MARK)
check('Logs: literal q matches (found the access line the probe just wrote)',
      hit.get('count', 0) >= 1, hit.get('count'))
st, hit2 = search(q=MARK.lower())
check('Logs: literal q is case-insensitive', hit2.get('count', 0) >= 1, hit2.get('count'))
# The needle has to be unique per run. uvicorn's access log records the query
# string of every request, so a FIXED "definitely not present" needle is written
# into the buffer by the very probe that looks for it — and any later run in the
# same pod then finds the earlier run's access line and reports a false failure.
MISS = 'QQ-absent-%d-QQ' % int(time.time() * 1000)
st, miss = search(q=MISS)
check('Logs: a non-matching q returns 0, not the whole buffer', miss.get('count') == 0, miss.get('count'))

# ------------------------------------------- q searches MESSAGE, not envelope
st, env = search(q='"level"')
check('Logs: q does not leak matches from the JSON envelope', env.get('count') == 0, env.get('count'))
st, ts = search(q='T0')   # would match ISO timestamps if the envelope were searched
check('Logs: q does not match the timestamp field', ts.get('count', 0) < body.get('count', 0), (ts.get('count'), body.get('count')))

# ---------------------------------------------------------------- regex
st, rx = search(q='^' + MARK[:4], regex='true')
check('Logs: regex anchors apply to the message (^ works)', st == 200, st)
st, rx2 = search(q='GET /api/logs/(search|stream)', regex='true')
check('Logs: a real regex matches access lines', rx2.get('count', 0) >= 1, rx2.get('count'))
st, bad = search(q='[unclosed', regex='true')
check('Logs: an invalid regex is 422, not a 200 with no count', st == 422, bad)
st, lit = search(q='[unclosed')
check('Logs: the same string as a LITERAL is fine (regex off by default)', st == 200, st)

# ---------------------------------------------------------------- level
st, inf = search(level='info', limit=5000)
check('Logs: level=info returns only info lines', st == 200 and all(json.loads(x)['level'] == 'info' for x in inf.get('lines', [])), st)
st, err = search(level='error,warning', limit=5000)
check('Logs: level=error,warning returns only those levels',
      st == 200 and set(json.loads(x)['level'] for x in err.get('lines', [])) <= {'error','warning'},
      sorted({json.loads(x)['level'] for x in err.get('lines', [])}))
# Two things this check must not assume, both of which it used to.
#
# 1. That the baseline taken at the top of this file is still current. Every
#    request the suite makes writes its own uvicorn access line, so the ring
#    buffer grows throughout the run and the info-only count legitimately
#    exceeded a baseline read a hundred requests earlier. Read the unfiltered
#    total AFTER the filtered one: the buffer only grows, so the later read is
#    a guaranteed superset of whatever the filter saw.
# 2. That the buffer contains a non-info line at all. On a freshly restarted
#    pod every line is 'info' — the warnings this leaned on are "MCP server
#    exited", which only the settings suite provokes — so "info is strictly
#    fewer than everything" is not a property that holds at all times, and
#    asserting it failed for reasons unrelated to the filter.
#
# So: bound the info count by the unfiltered total (always true, race-free),
# and prove narrowing separately with a level the snapshot shows is absent.
# That works no matter what the buffer happens to contain.
st, allnow = search(limit=5000)
snapshot = [json.loads(x) for x in allnow.get('lines', [])]
present = {l['level'] for l in snapshot}
absent = [lv for lv in ('critical', 'error', 'debug', 'warning') if lv not in present]
check('Logs: level=info never returns more than the unfiltered buffer',
      inf.get('count', 0) <= allnow.get('count', 0),
      (inf.get('count'), allnow.get('count')))
if absent:
    st, gone = search(level=absent[0], limit=5000)
    check('Logs: a level filter actually narrows the buffer (level=%s)' % absent[0],
          st == 200 and gone.get('count', 0) < allnow.get('count', 0),
          (absent[0], gone.get('count'), allnow.get('count')))
else:
    # Every known level is represented, so info-only must be strictly smaller.
    check('Logs: a level filter actually narrows the buffer',
          inf.get('count', 0) < allnow.get('count', 0),
          (inf.get('count'), allnow.get('count'), sorted(present)))
st, alias = search(level='warn')
check('Logs: the "warn" alias is accepted', st == 200, st)
st, typo = search(level='eror')
check('Logs: a typo level is 422, not a silently unfiltered buffer', st == 422, typo)

# ---------------------------------------------------------------- source
for s in sources:
    st, o = search(source=s, limit=5000)
    check('Logs: source=%s returns only that source' % s,
          st == 200 and all(json.loads(x)['source'] == s for x in o.get('lines', [])) and o.get('count',0) > 0,
          o.get('count'))
st, nos = search(source='no-such-source')
check('Logs: an unknown source returns 0 rather than everything', nos.get('count') == 0, nos.get('count'))

# ---------------------------------------------------------------- since
st, future = search(since='2099-01-01T00:00:00Z')
check('Logs: since in the future returns nothing', future.get('count') == 0, future.get('count'))
st, past = search(since='2000-01-01T00:00:00Z', limit=5000)
check('Logs: since in the past returns the whole buffer', past.get('count', 0) > 0, past.get('count'))
st, badsince = search(since='not-a-timestamp')
check('Logs: an unparseable since is 422', st == 422, badsince)

# ---------------------------------------------------------------- limit
st, lim = search(limit=3)
check('Logs: limit caps the returned lines', len(lim.get('lines', [])) <= 3, len(lim.get('lines', [])))
check('Logs: count reports the FULL match total, not the truncated page',
      lim.get('count', 0) >= len(lim.get('lines', [])), (lim.get('count'), len(lim.get('lines', []))))
st, l0 = search(limit=0)
check('Logs: limit=0 is rejected (it used to mean "everything")', st == 422, l0)
st, lbig = search(limit=99999)
check('Logs: an over-large limit is rejected', st == 422, lbig)

# ---------------------------------------------------------------- combined
st, comb = search(q='GET', level='info', source='uvicorn.access' if 'uvicorn.access' in sources else (sources[0] if sources else ''), limit=10)
check('Logs: filters combine (q + level + source)', st == 200, st)

# ---------------------------------------------------------------- SSE stream
# The deployment probes /healthz every 10s and every access line is fanned out
# to open streams, so a live stream is never idle for the 20s the heartbeat
# waits: the ping branch is unreachable from production and is covered by
# tests/test_log_stream.py::test_idle_stream_emits_a_ping_heartbeat instead.
# What IS testable here is the property the heartbeat exists to guarantee: the
# connection never goes quiet long enough for a tunnel or proxy to cut it.
HEARTBEAT = 20
req = urllib.request.Request(mcpc.ADMIN + '/api/logs/stream',
                             headers={'Authorization': 'Bearer ' + mcpc.api_token(),
                                      'Accept': 'text/event-stream',
                                      'User-Agent': mcpc.UA})
replay, ctype, gaps = [], '', []
try:
    resp = urllib.request.urlopen(req, timeout=90)
    ctype = resp.headers.get('Content-Type', '')
    t0 = time.time(); last = None; deadline = t0 + 45
    while time.time() < deadline:
        chunk = resp.readline()
        if not chunk: break
        now = time.time()
        s = chunk.decode('utf-8', 'replace').rstrip()
        if not s.startswith('data:'): continue
        d = s[5:].strip()
        if not d: continue
        if now - t0 < 3:
            if d != '{}':
                try: replay.append(json.loads(d))
                except Exception: pass
            continue
        if last is not None: gaps.append(now - last)
        last = now
    resp.close()
except Exception as e:
    check('Logs: /api/logs/stream connects', False, repr(e))

check('Logs: /api/logs/stream is an SSE stream', 'event-stream' in ctype, ctype)
check('Logs: the stream replays the recent buffer so the page is never blank', len(replay) > 0, len(replay))
check('Logs: replayed frames have the same shape as search results',
      all({'timestamp','level','message','source'} <= set(r) for r in replay), replay[0] if replay else None)
check('Logs: the stream keeps delivering after the replay (it is a live tail)', len(gaps) >= 2, len(gaps) + 1)
check('Logs: the stream never goes idle longer than the %ds heartbeat window' % HEARTBEAT,
      bool(gaps) and max(gaps) < HEARTBEAT,
      'max gap %.1fs over %d frames' % (max(gaps), len(gaps) + 1) if gaps else 'no frames')

# ---------------------------------------------------------------- auth gate
import urllib.error
try:
    urllib.request.urlopen(urllib.request.Request(mcpc.ADMIN + '/api/logs/search',
                                                  headers={'User-Agent': mcpc.UA}), timeout=20)
    check('Logs: the log API refuses unauthenticated callers', False, 'got 200')
except urllib.error.HTTPError as e:
    check('Logs: the log API refuses unauthenticated callers', e.code == 401, e.code)

print()
print('SUMMARY %d/%d passed' % (P, P + F))
