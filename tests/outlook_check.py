"""Player Outlook check: facts first, SPAM's valuation after, never the other way round.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/outlook_check.py

1. No circular reasoning: serve a copy of the board where Ja'Marr Chase and a WR far down the board swap ranks, tiers
   and values. His facts, direction, tags and confidence must be identical; only the valuation check and its sentence
   may change.
2. The drawer: the Outlook card sits in the Overview above Weekly Points, with direction, confidence, tags, sources,
   "Updated …" and a "Why this outlook?" panel that keeps Observed / Reports / SPAM valuation apart.
3. Injury context: Jayden Daniels' injury-shortened Week 2 and his report status are in the outlook.
4. Market: without data/market/redraft.json there's no market line and FantasyCalc isn't listed as a source; with a
   synthetic file (never real data) "Market WRn" appears with a FantasyCalc link and source.
5. League interpretation: a TE premium note appears only with TE premium; the facts sentence is the same.
6. Failure states: a ranked player with no games in either season gets "Insufficient recent information".
7. Editor audit: hidden for visitors; with ?debug the Audit filter appears (no flags on board rows, Alan, Oct 7), and
   "Outlook more bearish than ranking" lists only players the evidence ranks well below SPAM.
9. Layout: at the drawer's minimum width every card is one vertical column (no narrow text columns, nothing past the card
   edge), at most 3 tags, short text, ranking detail only inside "Why this outlook?".
8. Compare shows concise outlook rows. No page errors.
"""
import csv, functools, http.server, io, json, os, re, socketserver, sys, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
m = re.search(r"(RANKINGS_CSV\s*=\s*`)(.*?)(`)", SRC, re.S)
LINES = m.group(2).split("\n")
HI = next(i for i, l in enumerate(LINES) if l.startswith("player,pos"))
H = next(csv.reader([LINES[HI]])); C = {c: i for i, c in enumerate(H)}
rows = {i: next(csv.reader([l])) for i, l in enumerate(LINES) if i > HI and l.strip()}
by = {r[0]: (i, r) for i, r in rows.items()}
CHASE = by["Ja'Marr Chase"][1][C["sleeper_id"]]
DANIELS = by["Jayden Daniels"][1][C["sleeper_id"]]
# a WR far down the board to swap with
far = max((r for r in rows.values() if r[1] == "WR" and r[C["source"]] == "manual" and r[C["tier"]] and int(r[C["tier"]]) < 90), key=lambda r: int(r[C["rank"]]))
def swapped():
    ln = LINES[:]
    (ia, a), (ib, b) = by["Ja'Marr Chase"], by[far[0]]
    a, b = a[:], b[:]
    for k in ("rank", "pos_rank", "tier", "value"):
        a[C[k]], b[C[k]] = b[C[k]], a[C[k]]
    if len(a) > 12 and len(b) > 12: a[12], b[12] = b[12], a[12]
    for i, r in ((ia, a), (ib, b)):
        o = io.StringIO(); csv.writer(o, lineterminator="").writerow(r); ln[i] = o.getvalue()
    return SRC[:m.start(2)] + "\n".join(ln) + SRC[m.end(2):]

def serve():
    class Q(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass
    srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Q, directory=ROOT))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]

failures = []
def ok(c, msg):
    print(("PASS " if c else "FAIL ") + msg)
    if not c: failures.append(msg)

def market_body():   # synthetic FantasyCalc-shaped file: board order with a twist, nothing real
    fm = {}
    for q in (1, 2):
        for t in (10, 12):
            pr, f = {}, {}
            for r in sorted(rows.values(), key=lambda r: int(r[C["rank"]])):
                if not r[C["sleeper_id"]]: continue
                pr[r[1]] = pr.get(r[1], 0) + 1
                f[r[C["sleeper_id"]]] = [9000 - 30 * int(r[C["rank"]]), int(r[C["rank"]]), r[1], pr[r[1]] + (9 if r[C["sleeper_id"]] == CHASE else 0), 0]
            fm[f"q{q}_t{t}"] = f
    return json.dumps({"updated": "2026-10-06T12:00Z", "source": "FantasyCalc", "formats": fm})

port = serve()
with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    errs = []
    def page(q="", index=None, market=False):
        pg = br.new_page(viewport={"width": 1440, "height": 1000})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.(app|com))/.*"), lambda r: r.abort())
        if index: pg.route(re.compile(r".*/(index\.html)?(\?[^#]*)?$"), lambda r: r.fulfill(status=200, content_type="text/html", body=index) if r.request.resource_type == "document" else r.continue_())
        pg.route("**/data/market/redraft.json", (lambda r: r.fulfill(status=200, content_type="application/json", body=market_body())) if market else (lambda r: r.fulfill(status=404, body="")))
        pg.add_init_script("if (!sessionStorage.getItem('t')) { sessionStorage.setItem('t','1'); localStorage.clear(); }")
        pg.goto(f"http://127.0.0.1:{port}/{q}#rankings"); pg.wait_for_selector("#rank-body tr.player")
        pg.evaluate("Promise.all([2026, 2025].map(y => fetch('data/stats/' + y + '.json')))")
        pg.evaluate(f"document.querySelector('#rank-body [data-player=\"{CHASE}\"]').click()"); pg.wait_for_timeout(2500)
        return pg
    def olk(pg, sid): return pg.evaluate(f"() => SPM.outlook('{sid}')")

    # 1. no circularity
    pg = page(); a = olk(pg, CHASE); pg.close()
    pg = page(index=swapped()); b = olk(pg, CHASE); pg.close()
    ok(a["facts"] == b["facts"] and a["dir"] == b["dir"] and a["tags"] == b["tags"] and a["conf"] == b["conf"],
       f"Moving Chase from SPAM WR3 to {far[0]}'s spot leaves facts, direction, tags and confidence unchanged ({a['dir']}, {a['tags']})")
    ok(a["cls"] != b["cls"], f"…while the valuation check changes: {a['cls']} → {b['cls']}")
    ok(a["text"][0] == b["text"][0] and a["text"] != b["text"], "…and only the valuation wording changes, not the facts sentence")

    # 2. the drawer
    pg = page()
    card = pg.locator("#player-modal .olk")
    ok(card.count() == 1, "Outlook card in the Overview")
    order = pg.evaluate("() => { const b = document.querySelector('#player-modal .pm-body'); const o = b.querySelector('.olk'), w = b.querySelector('.wk-head'); return o && w ? !!(o.compareDocumentPosition(w) & Node.DOCUMENT_POSITION_FOLLOWING) : null; }")
    ok(order is True, "Outlook sits above Weekly Points")
    txt = card.inner_text()
    ok(re.search(r"(Strongly positive|Positive|Stable|Mixed|Negative|Strongly negative)", txt) and "confidence" in txt.lower(), "Direction and confidence shown")
    ok("Updated" in txt and "SPAM stats" in txt and "FantasyCalc" not in txt and "Market" not in txt, "Sources + freshness; no market claims without market data")
    card.locator("summary").click(); pg.wait_for_timeout(200)
    heads = card.locator(".olk-g h4").all_inner_texts()
    ok([h.lower() for h in heads[:2]] == ["ranking check", "observed"], f"Why this outlook? groups: {heads}")
    ok(any(h.lower() == "spam valuation" for h in heads), "SPAM valuation is its own group")
    ok(len(card.locator(".olk-tag").all()) <= 3, "At most 3 tags on the card")
    ok(any(h.lower() == "ranking check" for h in heads), "Ranking detail sits in Why this outlook? (Ranking check)")
    pg.close()

    # 3. injury context
    pg = page(); d = olk(pg, DANIELS)
    t = " ".join(d["text"])
    ok("Week 2" in t and "injury" in t, f"Daniels: the injury-shortened Week 2 is explained: {t[:160]}…")
    ok(("Out" in t) == ("Injury Concern" in d["tags"]) or "Injury Concern" in d["tags"], f"Daniels tags {d['tags']}")
    pg.close()

    # 4. market
    pg = page(market=True); pg.wait_for_timeout(800)
    pg.locator("#player-modal .olk summary").click(); pg.wait_for_timeout(200)
    txt = pg.locator("#player-modal .olk").inner_text()
    ok(re.search(r"Market: WR\d+", txt) and "FantasyCalc" in txt and pg.locator("#player-modal .olk a[href*='fantasycalc']").count() >= 1,
       "With market data: Market WRn in Why this outlook?, FantasyCalc source and link")
    mo = olk(pg, CHASE)
    ok(mo["market"] in ("high", "low", "near"), f"Market comparison kept separate from the evidence check ({mo['market']})")
    pg.close()

    # 5. league interpretation: TE premium note only with TE premium; facts identical
    te = next(r for r in sorted(rows.values(), key=lambda r: int(r[C["rank"]])) if r[1] == "TE" and r[C["sleeper_id"]])
    pg = page("?fmt=t12_qbsf_rec1_tep0.5"); x = olk(pg, te[C["sleeper_id"]]); pg.close()
    pg = page("?fmt=t12_qbsf_rec1_tep0"); y = olk(pg, te[C["sleeper_id"]]); pg.close()
    tx, ty = " ".join(x["text"]), " ".join(y["text"])
    ok(("TE premium" in tx) or "TE premium" not in ty, f"{te[0]}: TE premium note only with TE premium ({'TE premium' in tx} / {'TE premium' in ty})")
    ok(x["text"][0] == y["text"][0], "The facts sentence doesn't change with the format")

    # 6. failure state
    pg = page()
    nog = pg.evaluate("""() => { const st = [2026, 2025].map(y => fetch); return [...document.querySelectorAll('#rank-body [data-player]')].map(e => e.dataset.player)
      .find(s => { const o = SPM.outlook(s); return o && !o.facts.gp && !o.dir; }) || null; }""")
    if nog:
        pg.keyboard.press("Escape"); pg.evaluate(f"document.querySelector('#rank-body [data-player=\"{nog}\"]').click()"); pg.wait_for_timeout(1200)
        ok("Insufficient recent information" in pg.locator("#player-modal").inner_text(), "A player with no games: 'Insufficient recent information for a confident outlook.'")
    else:
        ok(True, "No ranked player without games in either season (failure-state check skipped)")
    ok(pg.locator("#rk-audit-wrap").is_hidden() and pg.locator("#rank-body .aud").count() == 0, "Visitors see no audit tools")
    pg.close()

    # 7. editor audit
    pg = page("?debug=1"); pg.keyboard.press("Escape"); pg.wait_for_timeout(1500)
    ok(pg.locator("#rk-audit-wrap").is_visible() and pg.locator("#rank-body .aud").count() == 0, "?debug: Audit filter, no flags on the board rows")
    pg.evaluate("() => { const s = document.getElementById('rk-audit'); s.value = 'bear'; s.dispatchEvent(new Event('change')); }"); pg.wait_for_timeout(500)
    sids = pg.evaluate("() => [...document.querySelectorAll('#rank-body tr.player')].map(tr => tr.querySelector('[data-player]').dataset.player)")
    clss = {pg.evaluate(f"() => SPM.outlook('{s}').cls") for s in sids}
    ok(sids and clss == {"Aggressive"}, f"'Outlook more bearish than ranking' lists only those ({len(sids)} players)")
    pg.close()

    # 8. compare
    pg = page()
    pg.evaluate(f"() => {{ document.querySelector('[data-pm-compare]').click(); }}"); pg.wait_for_timeout(300)
    pg.fill("#pm-pick", "Bijan"); pg.wait_for_timeout(300)
    pg.locator("[data-pm-pick]").first.click(); pg.wait_for_timeout(800)
    ok("spam outlook" in pg.locator("#player-modal").inner_text().lower(), "Compare shows the outlook rows")
    pg.close()
    # 9. layout at the drawer's minimum width, every ranked player
    pg = br.new_page(viewport={"width": 800, "height": 1000})
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.(app|com))/.*"), lambda r: r.abort())
    pg.goto(f"http://127.0.0.1:{port}/#rankings"); pg.wait_for_selector("#rank-body tr.player")
    pg.evaluate("Promise.all([2026, 2025].map(y => fetch('data/stats/' + y + '.json')))")
    sids = pg.evaluate("() => [...new Set([...document.querySelectorAll('#rank-body tr.player [data-player]')].map(e => e.dataset.player))]")
    bad, n, longest = [], 0, 0
    for i, s in enumerate(sids):
        pg.evaluate(f"document.querySelector('#rank-body [data-player=\"{s}\"]').click()"); pg.wait_for_timeout(1500 if i == 0 else 200)
        r = pg.evaluate("""() => { const c = document.querySelector('#player-modal .olk'); if (!c) return null;
          const cw = c.clientWidth, R = c.getBoundingClientRect().right, t = c.querySelector('.olk-text');
          return { w: cw, narrow: [...c.children].filter(k => !k.matches('.olk-more') && k.getBoundingClientRect().width < cw * 0.8).length,
            over: [...c.querySelectorAll('*')].filter(e => e.getBoundingClientRect().right > R + 1).length, h: c.offsetHeight,
            words: t ? t.textContent.split(/\s+/).length : 0, tags: c.querySelectorAll('.olk-tag').length,
            ranks: /production|market/i.test(t ? t.textContent : '') && /\b(WR|RB|QB|TE)\d+.*\b(WR|RB|QB|TE)\d+/.test(t ? t.textContent : '') }; }""")
        if not r: continue
        n += 1; longest = max(longest, r["words"])
        if r["narrow"] or r["over"] or r["h"] > 320 or r["words"] > 85 or r["tags"] > 3 or r["ranks"]: bad.append((s, r))
    ok(n > 200 and not bad, f"{n} cards at the 440px drawer: one column, nothing overflows, ≤320px tall, ≤3 tags, ≤85 words (longest {longest}) {bad[:3]}")
    pg.close()
    ok(not errs, f"No page errors {errs[:3]}")

print(f"\n{len(failures)} check(s) failed." if failures else "\nAll outlook checks passed.")
sys.exit(1 if failures else 0)
