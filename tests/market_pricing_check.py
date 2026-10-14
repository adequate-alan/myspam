"""Market pricing (Alan, Oct 14, Flock market lists PR 3): market prices on AM's scale with ONE scale factor, Flock priced
on FantasyCalc's own curve, consensus weights, and the FantasyCalc / Flock disagreement indicator.

Synthetic data only, on the frozen test board (tests/fixture_board.py): a FantasyCalc file and a Flock Superflex list
are built here from the fixture's own order with planted disagreements; the real market files are never read.

Checks:
1. Single scale: every FantasyCalc price on AM's scale = its raw value × s, so market price ratios are kept exactly;
   s = AM's starter-level total ÷ the market's total for the same slots (recomputed here).
2. Market independence: the same market on a board whose AM values are changed (a non-proportional transform, same
   order) gives exactly the same market prices in market units; only s changes.
3. Flock is priced on FantasyCalc's curve for that position (ranks 1-12 as they are, deeper ranks smoothed over 3 spots
   in log space); a Flock rank past the curve's end gets no price ("below market depth"), never an extrapolated one.
4. No AM substitution: a player only Flock ranks, below market depth, has no market read at all (mkOf null, no market
   % in SPM.marketReads).
5. Weights: default FantasyCalc 60 / Flock 40, this browser's override (spm_mk_weights, the Source details control),
   the effective split after a stale source ("FantasyCalc 71% · Flock 29% (Flock stale)").
6. Agree / Split / Strong split from |ln((FC pos rank + 3) ÷ (Flock pos rank + 3))| at 0.15 and 0.40; on a split the
   market is a range, the edge is measured to its nearer end, AM inside it reads "Market split; AM sits between
   FantasyCalc and Flock" with no buy / sell label; no split player gets a label one source alone would give.
7. One source: "FantasyCalc only", Market Confidence "Single source".
8. Half PPR: a Half PPR league reads the "_half" FantasyCalc file when it exists and Full PPR at a reduced weight until then.
9. A 1QB league never reads the Superflex Flock list.
10. The AM board is identical throughout; drawer and hover card wording (Flock-implied market value, Sources disagree).

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/market_pricing_check.py
"""
import os, re, sys, json, math, datetime
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fixture_board as FB
src = open(os.path.join(HERE, "league_hub_check.py"), encoding="utf-8").read()
LIVE_READ = 'src = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()'
assert LIVE_READ in src, "league_hub_check.py no longer reads index.html the way market_pricing_check expects"
exec(src.split("failures = []")[0].replace(LIVE_READ, "src = FB.html().decode('utf-8')"))   # serve(), sleeper(), sync_playwright, rows

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond: failures.append(msg)

board = [r for r in rows if r["pos"] in ("QB", "RB", "WR", "TE") and r["sleeper_id"] and r["tier"] != "99"]
board.sort(key=lambda r: int(r["rank"]))
pos_of = {r["sleeper_id"]: r["pos"] for r in board}
by_pos = {}
for r in board: by_pos.setdefault(r["pos"], []).append(r["sleeper_id"])

# planted players (WRs by AM position rank) and how each source moves them inside the WR order
WR = by_pos["WR"]
AGREE, SPLIT_IN, SPLIT_OUT, STRONG, ONLY_FC, DEEP = WR[12], WR[15], WR[20], WR[24], WR[30], WR[45]
def order(moves):
    o = list(WR)
    for sid, to in moves.items(): o.remove(sid)
    for sid, to in sorted(moves.items(), key=lambda x: x[1]): o.insert(to - 1, sid)
    return o
# FantasyCalc WR order: SPLIT_IN lower than AM (WR21), SPLIT_OUT at WR30 (both sources below AM's WR21), STRONG at WR34
fc_wr = order({AGREE: 13, SPLIT_IN: 21, SPLIT_OUT: 30, STRONG: 34})
# Flock WR order: SPLIT_IN higher than AM (WR12), SPLIT_OUT at WR24, STRONG at WR19; AGREE one spot off (WR14)
fl_wr = order({AGREE: 14, SPLIT_IN: 12, SPLIT_OUT: 24, STRONG: 19})
FC_DEPTH = {"QB": 30, "RB": 55, "WR": 60, "TE": 24}
fc_order = {pos: (fc_wr if pos == "WR" else list(ids))[:FC_DEPTH[pos]] for pos, ids in by_pos.items()}
fl_order = {pos: (fl_wr if pos == "WR" else list(ids)) for pos, ids in by_pos.items()}
fl_order["WR"] = [s for s in fl_order["WR"] if s != ONLY_FC]          # ONLY_FC: FantasyCalc only
fc_order["WR"] = [s for s in fc_order["WR"] if s != DEEP]              # DEEP: Flock only, and ranked past FantasyCalc's depth
fl_order["WR"].remove(DEEP); fl_order["WR"].insert(FC_DEPTH["WR"] + 3, DEEP)
# position-specific market curves (the market pays less for stars than AM: flatter at the top)
BASE = {"QB": 7000, "RB": 9000, "WR": 8500, "TE": 6000}
def fc_rows(scale=1.0):
    out, ov = {}, 0
    for pos, ids in fc_order.items():
        for i, sid in enumerate(ids):
            out[sid] = [int(round(BASE[pos] * scale * 0.955 ** i)) + (7 if i % 3 == 0 else 0), 0, pos, i + 1, 0]
    for k, sid in enumerate(sorted(out, key=lambda s: -out[s][0])): out[sid][1] = k + 1
    return out
now = datetime.datetime.now(datetime.timezone.utc)
def market(keys=("q2_t12", "q1_t12", "q2_t10", "q1_t10", "q2_t12_tep", "q1_t12_tep", "q2_t10_tep", "q1_t10_tep"), half=False):
    f = {k: fc_rows() for k in keys}
    if half: f.update({k: fc_rows(0.8) for k in ("q2_t12_half", "q1_t12_half", "q2_t10_half", "q1_t10_half")})
    return {"updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "source": "FantasyCalc", "url": "https://www.fantasycalc.com", "formats": f}
COLS = ["sleeper_id", "rank", "pos", "pos_rank", "tier", "name", "team", "expert_rank", "flock_id", "match"]
name = {r["sleeper_id"]: r["player"] for r in board}
def flock(days_old=1):
    seq = []
    for pos, ids in fl_order.items():
        for i, sid in enumerate(ids): seq.append((sid, pos, i + 1))
    seq.sort(key=lambda x: (x[2], x[1]))
    at = (now - datetime.timedelta(days=days_old)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rws = [[sid, k + 1, pos, pr, "A", name[sid], "", k + 1, sid, "id"] for k, (sid, pos, pr) in enumerate(seq)]
    return {"version": 2, "set": "flock-sf", "label": "Flock Superflex", "fmt": {"qb": "sf", "teams": 12, "tep": 0, "rec": 1},
            "exported": at, "published": at, "by": "test", "file": "synthetic.csv", "cols": COLS, "rows": rws, "unmatched": []}

def other_values(html):
    """the same board with every AM value changed non-proportionally (order kept): v → round(v ** 1.07) + 3·(rank % 2)"""
    m = re.search(rb"(const RANKINGS_CSV = `\n)([\s\S]*?)(\n`;)", html)
    lines = m.group(2).decode().split("\n"); head = lines[0].split(","); vi = head.index("value")
    out = [lines[0]]
    for ln in lines[1:]:
        c = ln.split(",")
        if len(c) == len(head) and c[vi].strip():
            v = float(c[vi]); c[vi] = str(int(round(v ** 1.07)) if v > 0 else 0)
        out.append(",".join(c))
    return html[:m.start(2)] + "\n".join(out).encode() + html[m.end(2):]

port = serve()
with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    errs = []
    def page(q="", mk=None, fl=None, html=None, init=""):
        pg = br.new_page(viewport={"width": 1440, "height": 1000})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.add_init_script("window.__SPM_TEST_HOOKS = true;" + init)
        pg.route("https://api.sleeper.app/**", sleeper)
        pg.route(re.compile(r"https://(?!api\.sleeper\.app).*"), lambda r: r.abort())
        mkb = json.dumps(mk or market()); flb = json.dumps(fl or flock())
        pg.route("**/data/market/redraft.json*", lambda r: r.fulfill(status=200, content_type="application/json", body=mkb))
        pg.route(re.compile(r".*/data/market/flock_sf\.json.*"), lambda r: r.fulfill(status=200, content_type="application/json", body=flb))
        pg.route(re.compile(r".*/data/market/flock_ppr\.json.*"), lambda r: r.fulfill(status=404, body=""))
        FB.route(pg, f"http://127.0.0.1:{port}")
        if html is not None:
            pg.route(re.compile(re.escape(f"http://127.0.0.1:{port}") + r"/(index\.html)?([?#].*)?$"), lambda r: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=html))
        pg.goto(f"http://127.0.0.1:{port}/{('?fmt=' + q) if q else ''}#rankings"); pg.wait_for_selector("#rank-body tr.player")
        pg.wait_for_function("() => SPM.marketPricing && SPM.marketPricing().srcs.length > 0", timeout=20000); pg.wait_for_timeout(500)
        return pg
    MP = "() => SPM.marketPricing()"

    # --- exact format (12-team SF Full PPR, no TE premium): FantasyCalc q2_t12, the Flock list in its own format
    pg = page("t12_qbsf_rec1_tep0")
    snap0 = pg.evaluate("() => SPM.rankingSnapshot()")
    M = pg.evaluate(MP); R = M["recs"]; s = M["scale"]
    fc = market()["formats"]["q2_t12"]
    ok([x["key"] for x in M["srcs"] if x["id"] == "fc"] == ["q2_t12"] and abs(M["base"]["fc"] - 0.6) < 1e-9, f"Exact format reads q2_t12, default weights FantasyCalc 60 / Flock 40: {M['srcs']} {M['base']}")
    # 1. single scale
    fcp = [(sid, r["per"]["fc"]) for sid, r in R.items() if "fc" in r["per"]]
    ok(len(fcp) > 150 and all(abs(x["mv"] - fc[sid][0]) < 1e-9 and abs(x["v"] - fc[sid][0] * s) < 1e-6 for sid, x in fcp),
       f"Every FantasyCalc price on AM's scale = its own value × s ({len(fcp)} players, s = {s:.4f})")
    a, b = fcp[0], fcp[-1]
    ok(abs(a[1]["v"] / b[1]["v"] - fc[a[0]][0] / fc[b[0]][0]) < 1e-9, "Market price ratios are the market's own (no reshaping toward AM's curve)")
    mk_tot = sum(sum(sorted([r[0] for r in fc.values() if r[2] == pos], reverse=True)[:n]) for pos, n in M["slots"].items())
    ok(abs(M["mkTot"] - mk_tot) < 1e-6 and abs(s - M["amTot"] / M["mkTot"]) < 1e-12 and M["slots"]["QB"] == 24 and M["slots"]["TE"] >= 12,
       f"s = AM's starter-level total ÷ the market's total for the same slots ({M['slots']}, {M['amTot']:.0f} / {M['mkTot']:.0f})")
    # 3. Flock on FantasyCalc's curve
    curve = {pos: sorted([r[0] for r in fc.values() if r[2] == pos], reverse=True) for pos in BASE}
    def implied(pos, k):
        c = curve[pos]
        if k > len(c): return None
        if k <= 12: return c[k - 1]
        nb = [x for x in (c[k - 2], c[k - 1], c[k] if k < len(c) else None) if x]
        return math.exp(sum(math.log(x) for x in nb) / len(nb))
    flp = [(sid, r["pos"], r["per"]["fl"]) for sid, r in R.items() if "fl" in r["per"]]
    bad = [(sid, x["own"], x["mv"], implied(pos, x["own"])) for sid, pos, x in flp if implied(pos, x["own"]) is None or abs(x["mv"] - implied(pos, x["own"])) > 1e-6]
    ok(len(flp) > 150 and not bad and all(x["implied"] for _, _, x in flp), f"Flock's position rank is priced on FantasyCalc's curve (1-12 as is, deeper smoothed): {len(flp)} players, {bad[:3]}")
    deep = R.get(DEEP)
    ok(deep is None, f"A Flock rank past FantasyCalc's depth gets no price and, with no FantasyCalc value either, no market read at all: {deep}")
    reads = pg.evaluate(f"() => SPM.marketReads(['{DEEP}'], ['{WR[40]}'])")
    ok(reads["all"] is False and reads["mk"] is None and reads["mktFor"] is None, f"No AM value stands in for the missing market value: {reads}")
    # 6. agreement
    lab = lambda a, b: (lambda sp: "Strong split" if sp >= 0.4 else "Split" if sp >= 0.15 else "Agree")(abs(math.log((a + 3) / (b + 3))))
    both = [(sid, r) for sid, r in R.items() if r["srcN"] == 2]
    ok(all(r["agree"] == lab(r["per"]["fc"]["pr"], r["per"]["fl"]["pr"]) for _, r in both) and {r["agree"] for _, r in both} >= {"Agree", "Split", "Strong split"},
       f"Agree / Split / Strong split at 0.15 and 0.40 ({sum(r['agree'] == 'Agree' for _, r in both)} / {sum(r['agree'] == 'Split' for _, r in both)} / {sum(r['agree'] == 'Strong split' for _, r in both)})")
    ag, si, so, st = R[AGREE], R[SPLIT_IN], R[SPLIT_OUT], R[STRONG]
    ok(ag["agree"] == "Agree" and so["agree"] == "Split" and st["agree"] == "Strong split", f"Planted: WR13 vs WR14 Agree, WR30 vs WR24 Split, WR34 vs WR19 Strong split: {ag['agree']}, {so['agree']}, {st['agree']}")
    ok(si["split"] and si["inside"] and si["lvl"] == 0 and si["dir"] == 0 and si["bucket"] == "Market split" and si["say"] == "Market split; AM sits between FantasyCalc and Flock.",
       f"AM inside the range: no buy / sell label, 'Market split; AM sits between FantasyCalc and Flock' ({si['bucket']}, {si['say']})")
    near = min(so["per"]["fc"]["pr"], so["per"]["fl"]["pr"])
    ok(so["split"] and not so["inside"] and so["mRank"] == near and so["range"]["lo"]["pr"] == near and so["range"]["hi"]["pr"] == max(so["per"]["fc"]["pr"], so["per"]["fl"]["pr"]),
       f"AM outside the range: the edge is measured to the nearer end (WR{so['mRank']}, range WR{so['range']['lo']['pr']}–{so['range']['hi']['pr']})")
    conf_bad = [sid for sid, r in both if r["split"] and r["lvl"] > 0 and not (r["per"]["fc"]["dir"] == r["per"]["fl"]["dir"] == r["dir"] and r["per"]["fc"]["lvl"] > 0 and r["per"]["fl"]["lvl"] > 0)]
    inside_bad = [sid for sid, r in both if r["inside"] and (r["lvl"] or r["dir"])]
    ok(not conf_bad and not inside_bad, f"No split-market player gets a buy / sell label one source alone would give ({conf_bad[:3]}, {inside_bad[:3]})")
    ok(all(r["conf"] != "High" for _, r in both if r["split"]) and all(r["conf"] == "Low" for _, r in both if r["agree"] == "Strong split"),
       "A split market is never a High-confidence read, a strong split always Low")
    # 7. one source
    o = R[ONLY_FC]
    ok(o["agree"] == "FantasyCalc only" and o["mconf"] == "Single source" and o["wText"] == "FantasyCalc only", f"One source: 'FantasyCalc only', Market Confidence 'Single source' ({o['agree']}, {o['mconf']})")
    # 5. weights text
    ok(M["wText"] == "FantasyCalc 60% · Flock 40%", f"Effective weights in the exact format: {M['wText']}")
    # drawer and hover card wording
    pg.evaluate("v => { const s = document.getElementById('rk-sort'); s.value = v; s.dispatchEvent(new Event('change')); }", "mkcons"); pg.wait_for_timeout(700)
    cell = pg.evaluate(f"() => (document.querySelector('#rank-body tr[data-id] .mk-cell') && [...document.querySelectorAll('#rank-body tr.mkrow')].find(tr => tr.querySelector('[data-player=\"{STRONG}\"]')) || {{}}).innerText || ''")
    ok("STRONG SPLIT" in cell.upper() and re.search(r"Market WR\d+–\d+", cell), f"Market edge sort: the range and the agreement tag on a split row: {cell[:120]!r}")
    pg.evaluate(f"() => document.querySelector('#rank-body [data-player=\"{STRONG}\"]').click()"); pg.wait_for_timeout(1200)
    pg.click("[data-pp-tab=value]"); pg.wait_for_timeout(400)
    dh = pg.evaluate("() => (document.querySelector('.pm-mkt') || {}).innerHTML || ''")
    ok("Strong split" in dh and "Sources disagree" in dh and "Flock-implied market value" in dh and re.search(r"WR\d+–\d+", dh), "Drawer Market line: range, Strong split, Sources disagree, Flock-implied market value")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    pg.hover(f'#rank-body tr.mkrow:has([data-player="{SPLIT_IN}"]) td.mk-col'); pg.wait_for_timeout(800)
    card = pg.inner_text("#hc") if pg.locator("#hc").count() else ""
    ok("Market range" in card and "Market split; AM sits between FantasyCalc and Flock" in card and "Flock-implied market value" in card and "scale factor" in card,
       f"AM hover card: market range, the in-range sentence, Flock-implied market value, one scale factor {card[-240:]!r}")
    pg.mouse.move(5, 5); pg.wait_for_timeout(300)
    # 5. weights override through the Source details control
    pg.click("[data-mk-details]"); pg.wait_for_timeout(400)
    ok("FantasyCalc 60% · Flock 40%" in pg.inner_text("#mk-st-detail"), "Source details shows the consensus weights")
    pg.click("[data-mk-w='70']"); pg.wait_for_timeout(600)
    M2 = pg.evaluate(MP)
    ok(pg.evaluate("() => JSON.parse(localStorage.getItem('spm_mk_weights')).fc") == 70 and M2["wText"] == "FantasyCalc 70% · Flock 30%" and "FantasyCalc 70% · Flock 30%" in pg.inner_text("#mk-st-detail"),
       f"Override saved in this browser (spm_mk_weights) and shown: {M2['wText']}")
    x = M2["recs"][AGREE]; fcv, flv = x["per"]["fc"]["v"], x["per"]["fl"]["v"]
    ok(abs(x["cv"] - math.exp(0.7 * math.log(fcv) + 0.3 * math.log(flv))) < 1e-6, "The consensus value is the weighted geometric mean at the overridden weights")
    ok(all(abs(M2["recs"][sid]["per"]["fc"]["v"] - R[sid]["per"]["fc"]["v"]) < 1e-9 for sid, _ in fcp), "Weights never change a source's own price")
    pg.click("[data-mk-w='reset']"); pg.wait_for_timeout(500)
    ok(pg.evaluate("() => localStorage.getItem('spm_mk_weights')") is None and pg.evaluate(MP)["wText"] == "FantasyCalc 60% · Flock 40%", "Reset goes back to the default 60 / 40")
    ok(pg.evaluate("() => SPM.rankingSnapshot()") == snap0, "AM ranks, tiers and values identical after pricing, weights and the drawer")
    pg.close()

    # 2. market independence: other AM values, same order
    pg = page("t12_qbsf_rec1_tep0", html=other_values(FB.html()))
    M3 = pg.evaluate(MP)
    same = all(abs(M3["recs"][sid]["per"][k]["mv"] - R[sid]["per"][k]["mv"]) < 1e-9 for sid in R if sid in M3["recs"] for k in R[sid]["per"])
    ratio = [M3["recs"][sid]["per"][k]["v"] / R[sid]["per"][k]["v"] for sid in R if sid in M3["recs"] for k in R[sid]["per"]]
    ok(M3["scale"] != s and same and max(ratio) - min(ratio) < 1e-9 and abs(ratio[0] - M3["scale"] / s) < 1e-9 and set(M3["recs"]) == set(R),
       f"Different AM values: market prices identical in market units, on AM's scale they move only by s ({s:.4f} → {M3['scale']:.4f})")
    pg.close()

    # 5. stale Flock: the effective weights say so
    pg = page("t12_qbsf_rec1_tep0", fl=flock(days_old=20))
    ok(pg.evaluate(MP)["wText"] == "FantasyCalc 71% · Flock 29% (Flock stale)", f"Stale Flock: {pg.evaluate(MP)['wText']}")
    pg.close()
    # a browser override set before the page loads
    pg = page("t12_qbsf_rec1_tep0", init="localStorage.setItem('spm_mk_weights', JSON.stringify({ fc: 50 }));")
    ok(pg.evaluate(MP)["wText"] == "FantasyCalc 50% · Flock 50%" and pg.evaluate(MP)["base"]["own"], "An override saved earlier applies on load")
    pg.close()

    # 8. Half PPR: the _half file when it exists, Full PPR at a reduced weight until then
    pg = page("t12_qbsf_rec0.5_tep0", mk=market(half=True))
    M4 = pg.evaluate(MP); f4 = next(x for x in M4["srcs"] if x["id"] == "fc")
    h = market(half=True)["formats"]["q2_t12_half"]
    ok(f4["key"] == "q2_t12_half" and f4["mult"] == 1 and f4["fmt"] == "exact format" and all(abs(r["per"]["fc"]["mv"] - h[sid][0]) < 1e-9 for sid, r in M4["recs"].items() if "fc" in r["per"]),
       f"Half PPR league reads the Half PPR market: {f4['key']} ({f4['fmt']})")
    pg.close()
    pg = page("t12_qbsf_rec0.5_tep0")
    f5 = next(x for x in pg.evaluate(MP)["srcs"] if x["id"] == "fc")
    ok(f5["key"] == "q2_t12" and abs(f5["mult"] - 0.85) < 1e-9 and "Full PPR market for Half PPR" in f5["fmt"], f"Without the Half PPR file: Full PPR at a reduced weight ({f5['key']}, {f5['fmt']})")
    pg.close()
    pg = page("t12_qbsf_rec0.5_tep0.5", mk=market(half=True))
    f6 = next(x for x in pg.evaluate(MP)["srcs"] if x["id"] == "fc")
    ok(f6["key"] == "q2_t12_tep", f"Half PPR with TE premium: Full PPR TE+ (a PPR mismatch costs less than a TE-premium one): {f6['key']}")
    pg.close()

    # 9. 1QB never reads the Superflex list
    pg = page("t12_qb1_rec1_tep0")
    M7 = pg.evaluate(MP)
    ok([x["id"] for x in M7["srcs"]] == ["fc"] and all(r["agree"] == "FantasyCalc only" and r["mconf"] in ("Single source", "Low") for r in M7["recs"].values()),
       f"A 1QB league reads FantasyCalc alone, never the Superflex Flock list ({[x['id'] for x in M7['srcs']]})")
    ok(pg.evaluate("() => SPM.rankingSnapshot()") == snap0, "The AM board is identical in a 1QB format")
    pg.close()
    ok(not errs, f"No page errors {errs[:3]}")
print(f"\n{len(failures)} check(s) failed." if failures else "\nAll market pricing checks passed.")
sys.exit(1 if failures else 0)
