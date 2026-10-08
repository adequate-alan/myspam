"""Repeated drags in one session (Alan, Oct 11: "by the second player the site gets laggy and can freeze").
Root causes found: every drop rendered the whole board twice (writeOrder → rebuild → renderRankings, then renderRankings
again for the "Revalued from tier" tag), each render rebuilt all ~8,300 board elements, the movement label formatted a
new date for every moved player (more each unsaved move), and a hidden Trade Calculator re-rendered on every edit. This
drives real mouse drags, without reloading, in Alan's setup: signed in (GitHub mocked, tests/gh_mock.py), a synthetic
Sleeper league connected (tests/league_hub_check.py), market data loaded, the AM Board view.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/drag_repeat_check.py

Checks, over 30 drags:
1. adjacent moves, 5+ rows, 20+ rows with auto-scroll, back and forth across row boundaries in one drag, quick
   consecutive drags, a position tab (WR), unsaved edits piling up, after Save (publishes to the mock), after Cancel
2. every drop lands on the rank its "#a → #b" chip showed; overall ranks stay 1..N, ids unique, position ranks follow
   the overall order (checked on the data, SPM.rankingSnapshot, and on the screen)
3. every drawn row matches the HTML it was built from (rows are reused between renders, never stale), and a value edit
   cancelled with Escape gives the value button back
4. nothing is left behind: no floating row, line or shield, the same number of event listeners on window / document
   / the board as before the first drag, no drag animation loop running, page node count not growing
6. reused rows are never stale: after drags, a value edit, a tier change, owner filter, search, the
   production sort, League-adjusted and back, the drawer open, Save, Cancel, a league switch (ownership) and rapid drags,
   the board equals one built from scratch in the same state; rapid drags leave no stray indicators
5. a drop inserts only the rows that changed (median ≤ 30 rows, never half the board; the old code redrew all ~259 rows
   twice per drop) and its
   script time doesn't grow with unsaved edits (drops 1–5 vs 26–30); later drags cost no more than early ones (main-thread time per drop, drags 1–5 vs 26–30), no drop over 600ms, and a
   final drag is accepted and lifts the row right away; no page errors
"""
import os, re, sys, json, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
src = open(os.path.join(HERE, "league_hub_check.py"), encoding="utf-8").read()
__file__ = os.path.join(HERE, "league_hub_check.py")
exec(src.split("failures = []")[0])   # make_league, LEAGUES, sleeper(), serve(), sync_playwright
from gh_mock import Repo

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

ROWS = """() => [...document.querySelectorAll('#rank-body tr.player')].map(r => ({ id: r.dataset.id, rk: ((r.querySelector('td.rk') || {}).firstChild || {}).nodeValue }))"""
SNAP_OK = """() => {
  const s = SPM.rankingSnapshot(), v = Object.values(s), ranks = v.map(a => a[0]).filter(x => x != null).sort((a, b) => a - b);
  const seq = ranks.every((r, i) => r === i + 1);
  return { n: v.length, seq, ids: Object.keys(s).length === new Set(Object.keys(s)).size };
}"""
STALE = """() => {
  const t = document.createElement('template'); let bad = 0, n = 0;
  // photos can't load in tests and remove themselves (onerror): not a stale row
  const norm = h => h.replace(/<img [^>]*>/g, '').replace(/ class="([^"]*)"/g, (m, c) => ' class="' + c.split(/\\s+/).filter(x => x && !['pp-current', 'flash'].includes(x)).sort().join(' ') + '"');
  for (const el of document.getElementById('rank-body').children) {
    if (el._h == null) continue; n++;
    t.innerHTML = el._h; const f = t.content.firstElementChild;
    if (!f || norm(f.outerHTML) !== norm(el.outerHTML)) bad++;
  }
  return { n, bad };
}"""

port = serve()
with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    pg = br.new_page(viewport={"width": 1440, "height": 900})
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    root = os.path.dirname(HERE)
    repo = Repo({"index.html": open(os.path.join(root, "index.html"), "rb").read(),
                 "data/rank_history.json": open(os.path.join(root, "data/rank_history.json"), "rb").read()})
    pg.route("https://api.github.com/**", repo.handle)
    pg.route("https://api.sleeper.app/**", sleeper)
    # photos and logos load (a 1×1 image), as they do on the live site: a photo that fails removes itself, which
    # counts as a change to its row
    PIX = __import__("base64").b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com)/.*"), lambda r: r.fulfill(status=200, content_type="image/png", body=PIX))
    pg.route(re.compile(r"https://(fonts\.(googleapis|gstatic)\.com|use\.typekit\.net|api\.sleeper\.com)/.*"), lambda r: r.abort())
    pg.route("**/data/market/flock.json", lambda r: r.abort())
    pg.add_init_script("try { localStorage.setItem('spm_editor_token', 'test-token'); } catch (e) {}")
    pg.goto(f"http://127.0.0.1:{port}/#rankings"); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(3500)
    # connect the synthetic league, then show the AM Board (editable) view
    pg.evaluate("() => { const b = document.createElement('button'); b.dataset.act = 'account'; document.getElementById('league-menu').append(b); b.click(); b.remove(); }")
    pg.wait_for_timeout(400)
    pg.fill("#sd-username", "tester"); pg.press("#sd-username", "Enter")
    pg.wait_for_selector("#sd-leagues [data-league='L1']"); pg.locator("#sd-leagues [data-league='L1']").click(); pg.wait_for_timeout(2500)
    pg.evaluate("() => { const s = JSON.parse(localStorage.getItem('spm_sleeper')); s.view = 'base'; localStorage.setItem('spm_sleeper', JSON.stringify(s)); }")
    pg.reload(); pg.wait_for_selector("#rank-body tr.player .handle"); pg.wait_for_timeout(3000)
    pg.click("#pos-chips button:has-text('All')"); pg.wait_for_timeout(500)
    ok(pg.evaluate("() => document.getElementById('eb-who').textContent") == "@tester" and pg.locator("#rank-body .handle").count() > 200,
       "Setup: signed in, league connected, AM Board editable")

    cdp = pg.context.new_cdp_session(pg); cdp.send("Performance.enable")
    def metric(k): return next(m["value"] for m in cdp.send("Performance.getMetrics")["metrics"] if m["name"] == k)
    def listeners():
        out = {}
        for name, expr in (("window", "window"), ("document", "document"), ("board", "document.getElementById('rank-body')")):
            o = cdp.send("Runtime.evaluate", {"expression": expr})["result"]["objectId"]
            out[name] = len(cdp.send("DOMDebugger.getEventListeners", {"objectId": o})["listeners"])
        return out
    def settle():
        pg.evaluate("() => new Promise(r => requestAnimationFrame(() => setTimeout(() => requestAnimationFrame(() => setTimeout(r, 0)), 0)))")
    def nodes():
        cdp.send("HeapProfiler.collectGarbage"); return int(metric("Nodes"))
    def handle_xy(idx):
        pg.evaluate(f"document.querySelectorAll('#rank-body tr.player')[{idx}].scrollIntoView({{block: 'center'}})"); pg.wait_for_timeout(120)
        return pg.evaluate(f"(() => {{ const r = document.querySelectorAll('#rank-body tr.player')[{idx}].querySelector('.handle').getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }})()")
    def chip(): return pg.evaluate("() => (document.querySelector('.drag-rk') || {}).textContent || null")

    before_listeners = listeners()
    costs, results, rows_before, churn, scripts = [], [], None, [], []
    def drag(idx, rows, back=None, quick=False):
        """Drag row idx by `rows` rows (fractions ok), optionally back and forth first; returns (chip, landed ok)."""
        x, y = handle_xy(idx)
        pid = pg.evaluate(f"document.querySelectorAll('#rank-body tr.player')[{idx}].dataset.id")
        t0 = metric("TaskDuration")
        pg.mouse.move(x, y); pg.mouse.down()
        if back:
            for i in range(24): pg.mouse.move(x, y + back * 59 * (0.4 + 0.9 * ((i // 6) % 2)) * (1 if i % 12 < 6 else -1)); time.sleep(0.012)
        steps = int(max(8, abs(rows) * 5))
        for i in range(steps): pg.mouse.move(x, y + rows * 59 * (i + 1) / steps); time.sleep(0.008 if quick else 0.012)
        c = chip()
        # count board rows inserted by the drop, and how many of the rows drawn before it are still the same elements
        pg.evaluate("""() => { const tb = document.getElementById('rank-body'); window.__ins = 0;
          [...tb.children].forEach(r => { r.__keep = 1; });
          window.__obs = new MutationObserver(rs => rs.forEach(r => { if (r.target === tb) window.__ins += r.addedNodes.length; }));
          window.__obs.observe(tb, { childList: true }); }""")
        t1 = metric("TaskDuration"); s1 = metric("ScriptDuration")
        pg.mouse.up(); settle(); pg.wait_for_timeout(60 if quick else 250)
        cost = round((metric("TaskDuration") - t1) * 1000); scost = round((metric("ScriptDuration") - s1) * 1000)
        ins, kept, total = pg.evaluate("""() => { window.__obs.takeRecords().forEach(r => { if (r.target === document.getElementById('rank-body')) window.__ins += r.addedNodes.length; });
          window.__obs.disconnect(); const ch = [...document.getElementById('rank-body').children];
          return [window.__ins, ch.filter(r => r.__keep).length, ch.length]; }""")
        churn.append((ins, kept, total)); scripts.append(scost)
        m = re.match(r"(#|[A-Z]+)(\d+) → (?:#|[A-Z]+)(\d+)", c or "")
        landed = True
        if m:
            want = int(m.group(3))
            now = pg.evaluate(f"(() => {{ const r = document.querySelector('#rank-body tr.player[data-id=\"{pid}\"]'); return r ? Number((r.querySelector('td.rk').firstChild || {{}}).nodeValue) : null; }})()")
            landed = now == want
        costs.append(cost); results.append((c, landed))
        return c, landed

    def board_ok(label):
        rows = pg.evaluate(ROWS); snap = pg.evaluate(SNAP_OK); st = pg.evaluate(STALE)
        left = pg.evaluate("() => document.querySelectorAll('.drag-float, .drop-line, .drag-shield, tr.drag-origin, .drop-before, .drop-after').length")
        all_tab = pg.evaluate("() => document.querySelector('#pos-chips [aria-pressed=\"true\"]').textContent") == "All"
        seq = all(r["rk"] == str(k + 1) for k, r in enumerate(rows)) if all_tab else all(r["rk"] == str(k + 1) for k, r in enumerate(rows) if r["rk"] and r["rk"].isdigit())
        ids = len({r["id"] for r in rows}) == len(rows)
        ok(seq and ids and snap["seq"] and snap["ids"] and st["bad"] == 0 and left == 0,
           f"{label}: ranks 1..N on screen and in the data, ids unique, {st['n']} drawn rows match their HTML ({st['bad']} stale), nothing left behind ({left})")

    # 1. thirty drags, no reload
    plan = [(30, 1.4, None), (31, -1.4, None), (25, 5, None), (60, -6, None), (12, 21, None), (90, -24, None),
            (40, 2.4, 1), (45, -2.4, 1), (70, 8, None), (80, -9, None), (33, 1.4, None), (34, -1.4, None),
            (55, 6, None), (66, -5, None), (15, 3.4, 1)]
    for k, (idx, d, back) in enumerate(plan): drag(idx, d, back)
    board_ok("15 drags (adjacent, 5+, 20+ with auto-scroll, back and forth across rows)")
    for k in range(5): drag(20 + k * 7, 3.4 if k % 2 == 0 else -3.4, quick=True)
    board_ok("5 quick consecutive drags")
    pg.click("#pos-chips button:has-text('WR')"); pg.wait_for_timeout(400)
    for k, d in enumerate((2.4, -3.4, 5.4)): drag(8 + k * 4, d)
    board_ok("3 drags on the WR tab")
    pg.click("#pos-chips button:has-text('All')"); pg.wait_for_timeout(400)
    unsaved = pg.evaluate("() => document.getElementById('eb-count').textContent")
    # a value edit cancelled with Escape: the row gets its value button back (a reused row is never stale)
    pg.locator("#rank-body tr.player").nth(50).locator(".num-btn").click(); pg.wait_for_timeout(150)
    pg.press(".val-input", "Escape"); pg.wait_for_timeout(300)
    ok(pg.locator("#rank-body .val-input").count() == 0 and pg.locator("#rank-body tr.player").nth(50).locator(".num-btn").count() == 1,
       "A value edit cancelled with Escape gives the value button back")
    for k in range(4): drag(100 + k * 9, 2.4 if k % 2 else -2.4)
    board_ok(f"Drags with unsaved edits piling up ({unsaved})")
    # Save (publishes to the mocked repository), then keep dragging
    pg.click("#eb-save")
    pg.wait_for_function("() => /Published|Already live|Publish failed|Saved/.test(document.getElementById('toast').textContent)", timeout=20000)
    toast = pg.inner_text("#toast"); pg.wait_for_timeout(400)
    ok("Published and confirmed" in toast, f"Save publishes the edits ({toast[:60]!r})")
    for k in range(2): drag(130 + k * 5, 2.4)
    # Cancel, then keep dragging
    pg.click("#eb-cancel"); pg.wait_for_timeout(400)
    for k in range(1): drag(140, -2.4)
    board_ok("Drags after Save and after Cancel")

    n_drags = len(results)
    ok(n_drags >= 30 and all(l for c, l in results), f"{n_drags} consecutive drags, every drop landed where its chip said ({sum(1 for c, l in results if not l)} misses)")
    # 4. cleanup: listeners, animation loops, nodes
    after_listeners = listeners()
    ok(after_listeners == before_listeners, f"Event listeners unchanged after {n_drags} drags: {before_listeners} → {after_listeners}")
    raf = pg.evaluate("""() => new Promise(r => { let n = 0; const o = window.requestAnimationFrame; window.requestAnimationFrame = f => { n++; return o(f); };
      setTimeout(() => { window.requestAnimationFrame = o; r(n); }, 600); })""")
    ok(raf == 0, f"No animation loop left running after the last drop ({raf} frame requests in 600ms)")
    n1 = nodes()
    for k in range(6): drag(30 + k * 3, 2.4 if k % 2 else -2.4)
    n2 = nodes()
    ok(n2 <= n1 * 1.05 + 200, f"Page node count doesn't grow with more drags: {n1} → {n2}")
    # 5. cost per drop: early vs late, and a final drag is accepted right away
    moved = [(i, k, t) for i, k, t in churn if t > 0]
    ins_sorted = sorted(i for i, k, t in moved); med = ins_sorted[len(ins_sorted) // 2]
    worst = max(i / t for i, k, t in moved)
    ok(med <= 30 and worst < 0.5,
       f"A drop redraws only the rows that changed: median {med} rows inserted per drop, at most {worst:.0%} of the board (a 20-row move renumbers 20+ rows; a full redraw inserts every row, twice)")
    se, sl = sum(scripts[:5]) / 5, sum(scripts[25:30]) / 5
    ok(sl <= se * 1.3 + 15, f"Script time per drop doesn't grow with unsaved edits: drops 1–5 {round(se)}ms, drops 26–30 {round(sl)}ms")
    early, late = costs[:5], costs[-5:]
    ok(max(costs) < 600 and sum(late) / 5 <= sum(early) / 5 * 1.5 + 30,
       f"Drops don't get slower: main-thread ms per drop, first five {early}, last five {late}, max {max(costs)}")
    x, y = handle_xy(33)
    pg.mouse.move(x, y); pg.mouse.down(); t = time.time()
    for i in range(4): pg.mouse.move(x, y + 3 * (i + 1))
    lifted = pg.locator(".drag-float").count() == 1; lat = round((time.time() - t) * 1000)
    pg.keyboard.press("Escape"); pg.mouse.up()
    # 330ms (Oct 12): measured old vs new code on the same machine, 4 alternating runs each: 265–284ms vs 185–290ms,
    # automation overhead included; the old 250ms limit failed on unchanged code, so it measured the machine, not a regression
    ok(lifted and lat < 330, f"A further drag lifts the row right away ({lat}ms incl. automation)")
    board_ok("Final board")

    # 6. rows reused between renders are never stale: after each kind of change, the board on screen must equal a
    # board built entirely from scratch in the same state (every row's _h cleared, so nothing can be reused)
    FRESH = """() => {
      const tb = document.getElementById('rank-body');
      const norm = el => el.outerHTML.replace(/<img [^>]*>/g, '').replace(/ class="([^"]*)"/g, (m, c) => ' class="' + c.split(/\\s+/).filter(x => x && !['pp-current', 'flash'].includes(x)).sort().join(' ') + '"');
      const a = [...tb.children].map(norm);
      [...tb.children].forEach(el => { el._h = null; });
      const q = document.getElementById('rank-search'); q.dispatchEvent(new Event('input'));   // re-render, same state
      const b = [...tb.children].map(norm);
      let diff = -1; for (let i = 0; i < Math.max(a.length, b.length); i++) if (a[i] !== b[i]) { diff = i; break; }
      return { n: a.length, same: diff < 0 && a.length === b.length, diff, a: diff >= 0 ? (a[diff] || '').slice(0, 300) : '', b: diff >= 0 ? (b[diff] || '').slice(0, 300) : '' };
    }"""
    def fresh(label):
        r = pg.evaluate(FRESH)
        ok(r["same"], f"Reused rows = a fresh render: {label} ({r['n']} rows)" + ("" if r["same"] else f" first difference at row {r['diff']}: {r['a']!r} vs {r['b']!r}"))
    def sel(id_, v): pg.evaluate(f"() => {{ const s = document.getElementById('{id_}'); s.value = {json.dumps(v)}; s.dispatchEvent(new Event('change')); }}"); pg.wait_for_timeout(400)
    fresh("ranks, position ranks, movement indicators and Revalued tags after 36 drags")
    # a value edit (and, when it doesn't fit his rank, the notice cancelled: nothing changes)
    vrow = pg.locator("#rank-body tr.player").nth(70)
    v0 = int(re.sub(r"\D", "", vrow.locator(".num-btn").inner_text()))
    vrow.locator(".num-btn").click(); pg.wait_for_timeout(150); pg.fill(".val-input", str(v0 + 3)); pg.press(".val-input", "Enter"); pg.wait_for_timeout(500)
    if pg.locator('#ed-warn [data-ed="close"]').count() and pg.locator("#ed-warn").is_visible(): pg.click('#ed-warn [data-ed="close"]'); pg.wait_for_timeout(300)
    fresh("a value edit")
    # tier change on a position tab: the first player of a lower WR tier moves up into the tier above
    pg.click("#pos-chips button:has-text('WR')"); pg.wait_for_timeout(400)
    TIERED = """() => [...document.querySelectorAll('#rank-body tr')].reduce((o, tr) => { if (tr.dataset.tier && !tr.classList.contains('player')) o.t = tr.dataset.tier;
      if (tr.classList.contains('player')) o.rows.push({ id: tr.dataset.id, tier: tr.dataset.tier || o.t }); return o; }, { t: null, rows: [] }).rows"""
    wr = pg.evaluate(TIERED); i = next(k for k in range(1, len(wr)) if wr[k]["tier"] != wr[k - 1]["tier"] and k > 6)
    pg.locator(f'#rank-body tr.player[data-id="{wr[i]["id"]}"] .arrow[data-dir="-1"]').click(force=True); pg.wait_for_timeout(600)
    fresh("a tier change on the WR tab")
    pg.click("#pos-chips button:has-text('All')"); pg.wait_for_timeout(400)
    fresh("back on All after a tier change")
    # filters and sorts
    owners = pg.evaluate("() => [...document.getElementById('owner-filter').options].map(o => o.value)")
    if len(owners) > 1:
        sel("owner-filter", owners[1]); fresh("owner filter: one team"); sel("owner-filter", owners[0]); fresh("owner filter back to all")
    pg.fill("#rank-search", "a"); pg.wait_for_timeout(400); fresh("a search")
    pg.fill("#rank-search", ""); pg.wait_for_timeout(400); fresh("search cleared")
    sel("rk-sort", "ppg"); sel("rk-sort", "spam"); fresh("production sort and back to AM Rank")
    pg.evaluate("() => document.querySelector('[data-view=league]').click()"); pg.wait_for_timeout(600); fresh("League-adjusted view")
    pg.evaluate("() => document.querySelector('[data-view=base]').click()"); pg.wait_for_timeout(600); fresh("back to the AM Board")
    # the open player's highlight (an in-place class change), then a drop
    pg.evaluate("() => document.querySelectorAll('#rank-body tr.player')[5].querySelector('.pl-name').click()"); pg.wait_for_timeout(1200)
    drag(8, 2.4); pg.keyboard.press("Escape"); pg.wait_for_timeout(300); fresh("a drop with the player drawer open")
    # editor state: Save (publish), then an edit and Cancel
    pg.click("#eb-save")
    pg.wait_for_function("() => /Published|Already live|Publish failed|Saved/.test(document.getElementById('toast').textContent)", timeout=20000); pg.wait_for_timeout(500)
    fresh("after Save (published)")
    drag(20, 2.4); pg.click("#eb-cancel"); pg.wait_for_timeout(500); fresh("after an edit and Cancel")
    # ownership: switch to the second synthetic league (different rosters), then back
    for lid in ("L2", "L1"):
        pg.evaluate(f"() => {{ const b = document.querySelector('#league-menu [data-league=\"{lid}\"]') || (() => {{ const x = document.createElement('button'); x.dataset.league = '{lid}'; document.getElementById('league-menu').append(x); return x; }})(); b.click(); }}")
        pg.wait_for_timeout(2500)
        pg.evaluate("() => document.querySelector('[data-view=base]').click()"); pg.wait_for_timeout(500)
        fresh(f"ownership after switching to league {lid}")
    # rapid consecutive drags: the next grab right after each release, no waiting
    pg.click("#pos-chips button:has-text('All')"); pg.wait_for_timeout(400)
    starts = 0
    for k in range(8):
        x, y = handle_xy(40 + (k % 4) * 6)
        pg.mouse.move(x, y); pg.mouse.down()
        for i in range(10): pg.mouse.move(x, y + (2.4 if k % 2 else -2.4) * 59 * (i + 1) / 10); time.sleep(0.004)
        starts += 1 if chip() else 0
        pg.mouse.up()
    settle(); pg.wait_for_timeout(500)
    ok(starts >= 4, f"Rapid drags: {starts} of 8 grabs started (a grab during the previous drop's commit is ignored, by design)")
    board_ok("After 8 rapid drags")
    fresh("after rapid drags")
    ok(not errs, f"No page errors {errs[:3]}")
    br.close()
print(f"\n{len(failures)} check(s) failed." if failures else "\nAll repeated-drag checks passed.")
sys.exit(1 if failures else 0)
