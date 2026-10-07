"""Market edge (Alan, Oct 8): AM's rest-of-season board vs FantasyCalc (trade market) and Flock (expert rankings).

Synthetic data only: the market file and the Flock CSV are built here from AM's own board order with three planted
disagreements (no real FantasyCalc or Flock numbers, no real league):
  BUY   a WR on team 4 that the market ranks well below AM      -> AM edge +, Buy
  SELL  a WR on your team that the market ranks well above AM   -> AM edge -, Sell
  SPLIT a player FantasyCalc ranks far lower and Flock far higher -> mixed, low confidence

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/market_edge_check.py

Checks: the AM board is identical before and after (ranks, values) · Market edge sorts · Flock import (CSV file),
persistence and removal · approximate-format and stale labels · drawer Market section · Trade Finder Market leverage
(headline, the market favors what you send), sell flag in Shop my players, Best market buys / sells · calculator
Market comparison (AM line separate) · editor-only market audit with ?debug · no page errors.
"""
import os, re, sys, json, datetime
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "league_hub_check.py"), encoding="utf-8").read()
exec(src.split("failures = []")[0])   # make_league, L1, sleeper(), serve(), rows, name_of, sync_playwright

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

board = [r for r in rows if r["pos"] in ("QB", "RB", "WR", "TE") and r["sleeper_id"] and r["tier"] != "99"]
board.sort(key=lambda r: int(r["rank"]))
pos_of = {r["sleeper_id"]: r["pos"] for r in board}
def pos_rank(sid):
    return [r["sleeper_id"] for r in board if r["pos"] == pos_of[sid]].index(sid) + 1
mine, team4 = L1["rosters"][0]["players"], L1["rosters"][3]["players"]
BUY = next(s for s in team4 if pos_of.get(s) == "WR" and 10 <= pos_rank(s) <= 20)
SELL = next(s for s in mine if pos_of.get(s) == "WR" and 18 <= pos_rank(s) <= 34)
SPLIT = next(s for s in L1["rosters"][6]["players"] if pos_of.get(s) == "RB" and 8 <= pos_rank(s) <= 25)

def market_order(shift):
    """AM's order with players moved by `shift` overall spots (+ = the market ranks him lower)"""
    order = [r["sleeper_id"] for r in board]
    for sid, d in shift.items():
        i = order.index(sid); order.pop(i); order.insert(max(0, min(len(order), i + d)), sid)
    return order
def ranks(order):
    pc, out = {}, {}
    for i, sid in enumerate(order):
        pc[pos_of[sid]] = pc.get(pos_of[sid], 0) + 1
        out[sid] = (i + 1, pc[pos_of[sid]])
    return out
fc = ranks(market_order({BUY: 28, SELL: -30, SPLIT: 40}))
fl = ranks(market_order({BUY: 22, SELL: -26, SPLIT: -14}))
def market_file(updated):
    f = {sid: [int(10000 * 0.985 ** (o - 1)), o, pos_of[sid], pr, 0] for sid, (o, pr) in fc.items()}
    return {"updated": updated, "source": "FantasyCalc", "url": "https://www.fantasycalc.com", "formats": {k: f for k in
            ["q2_t12", "q1_t12", "q2_t10", "q1_t10", "q2_t12_tep", "q1_t12_tep", "q2_t10_tep", "q1_t10_tep"]}}
now = datetime.datetime.now(datetime.timezone.utc)
FRESH = market_file(now.strftime("%Y-%m-%dT%H:%MZ"))
STALE = market_file((now - datetime.timedelta(days=10)).strftime("%Y-%m-%dT%H:%MZ"))
csv_path = os.path.join(os.environ.get("TMPDIR", "/tmp"), "synthetic_flock.csv")
with open(csv_path, "w") as f:
    f.write("player_id,Rank,Name,Team,Position,Tier\n")
    for sid, (o, pr) in sorted(fl.items(), key=lambda x: x[1][0]):
        r = next(x for x in board if x["sleeper_id"] == sid)
        f.write(f'{sid},{o},"{r["player"]}",{r["team"]},{r["pos"]},A\n')

port = serve()
with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    errs = []
    def page(market, debug=False):
        pg = br.new_page(viewport={"width": 1440, "height": 1000})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("dialog", lambda d: (errs.append("dialog: " + d.message), d.dismiss()))
        pg.route("https://api.sleeper.app/**", sleeper)
        pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.com|fonts\.(googleapis|gstatic)\.com)/.*"), lambda r: r.abort())
        pg.route("**/data/market/redraft.json", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(market)))
        pg.route("**/data/market/flock.json", lambda r: r.fulfill(status=404, body=""))   # synthetic Flock only: the built-in list stays out
        pg.goto(f"http://127.0.0.1:{port}/{'?debug' if debug else ''}#rankings"); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(2500)
        return pg
    def connect(pg):
        pg.evaluate("() => { const b = document.createElement('button'); b.dataset.act = 'account'; document.getElementById('league-menu').append(b); b.click(); b.remove(); }")
        pg.wait_for_timeout(400); pg.fill("#sd-username", "tester"); pg.press("#sd-username", "Enter"); pg.wait_for_timeout(800)
        pg.locator("#sd-leagues [data-league='L1']").click(); pg.wait_for_timeout(1500)
    def sort(pg, v):
        pg.evaluate(f"() => {{ const s = document.getElementById('rk-sort'); s.value = '{v}'; s.dispatchEvent(new Event('change')); }}"); pg.wait_for_timeout(700)
    ROWS = "() => [...document.querySelectorAll('#rank-body tr.player')].map(tr => ({ name: tr.querySelector('.pl-name').textContent.trim(), cell: (tr.querySelector('.mk-cell') || {}).innerText || '' }))"

    pg = page(FRESH, debug=True)
    snap0 = pg.evaluate("() => SPM.rankingSnapshot()")
    # 1. Board, FantasyCalc only
    sort(pg, "mkbuy")
    ok(not pg.locator("#mk-bar").is_hidden() and "FantasyCalc" in pg.inner_text("#mk-bar"), "Market edge sort shows the market bar with FantasyCalc")
    r = pg.evaluate(ROWS)
    top = [x["name"] for x in r[:6]]
    ok(name_of[BUY] in top, f"Biggest buy: {name_of[BUY]} near the top {top}")
    b = next(x for x in r if x["name"] == name_of[BUY])
    ok("▲" in b["cell"] and "BUY" in b["cell"].upper(), f"Buy row reads AM vs market with ▲: {b['cell'][:80]!r}")
    sort(pg, "mksell")
    r = pg.evaluate(ROWS)
    ok(name_of[SELL] in [x["name"] for x in r[:6]], f"Biggest sell: {name_of[SELL]} near the top")
    s_ = next(x for x in r if x["name"] == name_of[SELL])
    ok("▼" in s_["cell"] and "SELL" in s_["cell"].upper(), f"Sell row reads ▼ and Sell: {s_['cell'][:80]!r}")
    # 2. Flock import (synthetic CSV), 1QB list in a Superflex format -> approximate
    pg.click("[data-mk-flock]"); pg.wait_for_timeout(300)
    pg.evaluate("() => { const s = document.getElementById('mk-fl-qb'); s.value = '1qb'; }")
    pg.set_input_files("#mk-file", csv_path); pg.wait_for_timeout(1200)
    bar = pg.inner_text("#mk-bar")
    ok("Imported" in bar and "Flock" in bar and "approximate" in bar and "1QB list" in bar, "Flock CSV imports; a 1QB list in a Superflex format is labelled approximate")
    ok(pg.evaluate("() => !!JSON.parse(localStorage.getItem('spm_flock') || 'null')"), "Flock rankings are kept in this browser (spm_flock)")
    pg.evaluate("() => { const s = document.getElementById('mk-fl-qb'); s.value = 'sf'; }")
    pg.set_input_files("#mk-file", csv_path); pg.wait_for_timeout(1200)
    sort(pg, "mkfl"); r = pg.evaluate(ROWS)
    ok(r and all("Flock" in x["cell"] for x in r[:5]), "AM vs Flock sort uses Flock")
    sort(pg, "mkcons")
    # 3. drawer
    pg.evaluate(f"() => document.querySelector('#rank-body [data-player=\"{BUY}\"]').click()"); pg.wait_for_timeout(1200)
    d = pg.inner_text(".pm-mkt") if pg.locator(".pm-mkt").count() else ""
    ok(all(k in d.upper() for k in ("MARKET", "FANTASYCALC", "FLOCK", "CONSENSUS", "AM EDGE +")) and "BUY" in d.upper(), f"Drawer Market section for the buy: {d[:120]!r}")
    ok("both the trade market and expert consensus" in d, "Drawer explains: AM higher than both")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    pg.evaluate(f"() => document.querySelector('#rank-body [data-player=\"{SPLIT}\"]').click()"); pg.wait_for_timeout(1200)
    d = pg.inner_text(".pm-mkt") if pg.locator(".pm-mkt").count() else ""
    ok("mixed" in d.lower(), f"Split player: external opinion is mixed {d[-160:]!r}")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    # 4. AM board untouched
    snap1 = pg.evaluate("() => SPM.rankingSnapshot()")
    ok(snap0 == snap1, "AM ranks, tiers and values are identical with market data loaded")
    # 5. editor audit (?debug)
    ok(pg.locator("#eb-mcheck").is_visible() and pg.eval_on_selector("#eb-mcheck", "b => getComputedStyle(b).backgroundColor") in ("rgba(0, 0, 0, 0)", "transparent"), "Market audit is a quiet text item in the editor bar, not a pill")
    pg.click("#eb-mcheck"); pg.wait_for_timeout(500)
    a = pg.inner_text("#rv-body") if not pg.locator("#rv-panel").is_hidden() else ""
    ok(all(k in a.upper() for k in ("AM MUCH HIGHER", "MARKET MUCH HIGHER", "TIER CONFLICTS", "NEEDS REVIEW", "SOURCES DISAGREE", "BASED ON FANTASYCALC + FLOCK")) and name_of[BUY] in a, "Market audit opens the Review panel with summary, buckets and a source note")
    ok(pg.locator("#rv-body .rv-row [data-rv-player]").count() > 0 and pg.locator("#rv-body .rv-row [data-jump]").count() > 0, "Audit rows offer View player and Show on board")
    pg.click("[data-rv-tab='warn']"); pg.wait_for_timeout(300)
    ok(pg.inner_text("#rv-title") == "Value warnings" and "AM Board" in pg.inner_text("#rv-body"), "The Review panel switches to Value warnings")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    ok(pg.locator("#rv-panel").is_hidden(), "Escape closes the Review panel")
    # persistence + removal
    pg.reload(wait_until="domcontentloaded"); pg.wait_for_timeout(4000)
    ok(pg.evaluate("() => document.querySelectorAll('#rank-body tr.mkrow').length") > 100, "After a reload the board comes back in the saved Market edge sort")
    ok("Flock" in pg.inner_text("#mk-bar"), "Flock rankings and the Market edge sort survive a reload")
    pg.click("[data-mk-flock]"); pg.wait_for_timeout(300); pg.click("[data-mk-clear]"); pg.wait_for_timeout(600)
    ok(pg.evaluate("() => localStorage.getItem('spm_flock')") is None and "Flock imported" not in pg.inner_text("#mk-bar"), "Remove Flock rankings clears them")
    pg.set_input_files("#mk-file", csv_path); pg.wait_for_timeout(1000)

    # 6. Trade Finder with the league
    connect(pg)
    pg.click("#tab-finder"); pg.wait_for_timeout(1000)
    opts = pg.eval_on_selector_all("#tf-goal option", "os => os.map(o => o.textContent)")
    ok("Market leverage" in opts, f"Trade goal options include Market leverage {opts}")
    # Shop my players: the sell flag
    pg.evaluate(f"() => {{ const s = document.getElementById('tf-player'); s.value = '{SELL}'; s.dispatchEvent(new Event('change', {{ bubbles: true }})); }}"); pg.wait_for_timeout(1500)
    lead = pg.inner_text("#tf-lead")
    ok("sell opportunity" in lead.lower(), f"Shop my players flags a sell: {lead[-140:]!r}")
    # Target the buy with Market leverage
    pg.click("#tf-src [data-src='target']"); pg.wait_for_timeout(400)
    pg.fill("#tf-q", name_of[BUY].split()[-1]); pg.wait_for_timeout(400)
    pg.evaluate(f"() => document.querySelector('#tf-results [data-tf-pick=\"{BUY}\"]').click()"); pg.wait_for_timeout(2000)
    intel = pg.inner_text(".tf-intel")
    ok("FantasyCalc" in intel and "Flock" in intel and "AM VS MARKET" in intel.upper() and "Market leverage" in intel, "Target header: both sources, AM vs market, a Market leverage path")
    pg.click("#tf-lead [data-tf-goal='market']"); pg.wait_for_timeout(3000)
    ok(pg.eval_on_selector("#tf-goal", "s => s.value") == "market", "Use Market leverage switches the goal")
    cards = pg.locator(".tf-tcard").all()
    sends = [c.evaluate("e => [...e.querySelectorAll('.tf-side')[1].querySelectorAll('[data-player]')].map(x => x.dataset.player)") for c in cards]
    ok(cards and all(set(x) <= set(mine) for x in sends), f"Market leverage offers ({len(cards)}) send only your players")
    ok(any(SELL in x for x in sends), "Market leverage uses the player the market likes more than AM")
    # discover buys / sells
    pg.click("#tf-src [data-src='discover']"); pg.wait_for_timeout(1500)
    disc = pg.inner_text("#tf-body")
    ok("Best market buys" in disc and "Best market sells" in disc, "Find targets has Best market buys / sells")
    pg.click("[data-tf-disc='sell']"); pg.wait_for_timeout(1200)
    sells = pg.inner_text("#tf-body")
    ok(name_of[SELL] in sells, f"Best market sells lists {name_of[SELL]}")
    pg.click(f"[data-tf-shop='{SELL}']"); pg.wait_for_timeout(2000)
    ok(pg.eval_on_selector("#tf-src [aria-pressed='true']", "b => b.dataset.src") == "mine" and pg.eval_on_selector("#tf-goal", "s => s.value") == "market", "Shop him opens Shop my players with Market leverage")
    # 7. calculator market comparison
    pg.click("#tf-src [data-src='target']"); pg.wait_for_timeout(300)
    pg.fill("#tf-q", name_of[BUY].split()[-1]); pg.wait_for_timeout(300)
    pg.evaluate(f"() => document.querySelector('#tf-results [data-tf-pick=\"{BUY}\"]').click()"); pg.wait_for_timeout(2500)
    if pg.locator("[data-tf-open]").count():
        pg.locator("[data-tf-open]").first.click(); pg.wait_for_timeout(1500)
        mk = pg.inner_text("#tc-mkt") if not pg.locator("#tc-mkt").is_hidden() else ""
        ok("Market comparison" in mk and "AM" in mk and "FantasyCalc" in mk and "Flock" in mk, f"Calculator shows Market comparison beside AM: {mk[:120]!r}")
    else:
        ok(False, "No Market leverage card to open in the calculator")
    pg.close()

    # 8. stale market lowers confidence and is labelled
    pg = page(STALE)
    sort(pg, "mkbuy")
    ok("(stale)" in pg.inner_text("#mk-bar"), "A 10-day-old market file is labelled stale")
    b = next((x for x in pg.evaluate(ROWS) if x["name"] == name_of[BUY]), {"cell": ""})
    ok("High" not in b["cell"], f"Stale + single source never reads High confidence: {b['cell'][:90]!r}")
    pg.close()
    ok(not errs, f"No page errors {errs[:3]}")
print(f"\n{len(failures)} check(s) failed." if failures else "\nAll market edge checks passed.")
sys.exit(1 if failures else 0)
