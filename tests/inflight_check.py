"""Edits made while a publish is in flight (Alan, Oct 13; the Joe Burrow case).

A browser with a token publishes on Save, which takes a few seconds. Edits made in that window are kept on top of the
newly published board, which is the new baseline (Architecture C, §2.4), so they must price exactly as the same edits made
after the publish finished. Before the fix only manual value edits kept their anchors: a mover sat at his newly published
value in his new tier or slot (Burrow moved back to Tier 3 while Tier 4 was publishing came out at the Tier 4 price,
5,379), and a rank move during a publish could break the value order.

Every case runs against an in-memory GitHub (tests/gh_mock.py) answering slowly, with real header buttons / the editor's
own move functions, and compares the whole board after the publish with an ORACLE: a fresh page on the published board
making the same edits after the fact. Cases:
  1. Burrow: Tier 3 → Tier 4, Save (publishing), Tier 3 during the publish → QB6 · Tier 3 · 5,760, 1 unsaved, touched;
     GitHub holds Tier 4 · 5,379; Save again publishes Tier 3 · 5,760; one event and one snapshot per publish
  2. a rank move during the publish (and the players he jumped keep their values; order strictly descending)
  3. tier moves both directions during the publish (Goff up, Burrow down)
  4. a manual value edit during the publish is kept exactly
  5. the same player before and during the publish (Burrow to Tier 4 saved, then one spot down while publishing)
  6. several edits during the publish (tier, rank, value, on different players)
  7. Save, Cancel, reload and browser-persisted edits after an in-flight edit
  8. faults: the branch moved once (a retry), a lost answer, a failed publish keeping the in-flight edit saved in this
     browser, offline after the commit then Save (the unconfirmed publish is settled first: it landed, the board GitHub
     holds is adopted, the in-flight edit is kept on top of it and, Save meaning publish, published in one new commit), a
     pending commit that never landed, still offline at the next Save (stays pending), and a plain Save with nothing to
     save and nothing pending (a no-op)
  9. unaffected players identical to the published board; values strictly down the overall order after every case;
     no duplicate history events or snapshots

INDEX=old.html runs it against an older page (the pre-fix code fails case 1).
Run from the repo root:  python3 tests/inflight_check.py   (CHROMIUM=/path/to/chromium if needed)
"""
import functools, http.server, json, os, re, socketserver, sys, threading, time
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gh_mock import Repo
import fixture_board as FB

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.environ.get("INDEX", os.path.join(ROOT, "index.html"))
ORIG = FB.html(open(INDEX, "rb").read())   # the code under test (INDEX=old.html runs older code) with the frozen test board
rd = lambda p: open(os.path.join(ROOT, p), "rb").read()
FIX = FB.files()                           # the fixture's history and snapshot month
SNAPS = {k: v for k, v in FIX.items() if k.startswith("data/rank_snapshots/")}
CSV_RE = re.compile(rb"(const RANKINGS_CSV = `\n)([\s\S]*?)(\n`;)")
h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT); h.log_message = lambda *a: None
srv = socketserver.TCPServer(("127.0.0.1", 0), h); threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond: failures.append(msg)

def new_repo(index=ORIG):
    return Repo({"index.html": index, "data/rank_history.json": FIX["data/rank_history.json"], "data/injury_overrides.json": rd("data/injury_overrides.json"), **SNAPS})
def snap_count(repo):
    return sum(len(json.loads(repo.read(p) or b'{"snapshots":[]}')["snapshots"]) for p in set(SNAPS) | {f"data/rank_snapshots/{time.strftime('%Y-%m', time.gmtime())}.json"})
def ev_count(repo): return len(json.loads(repo.read("data/rank_history.json")).get("events", []))
def pub_row(repo, name):
    for line in CSV_RE.search(repo.read("index.html"))[2].decode().split("\n"):
        if line.startswith(name + ","): return line.split(",")
    return None

BOARD = "() => SPM.edit.board().map(p => [p.name, p.rank, p.posNum, String(p.tier), p.value, p.source]).sort((a, b) => a[1] - b[1])"
STATE = """() => ({ board: SPM.edit.board().map(p => [p.name, p.rank, p.posNum, String(p.tier), p.value, p.source]).sort((a, b) => a[1] - b[1]),
  touched: SPM.edit.touched().sort(), unsaved: SPM.edit.unsaved(), bar: document.getElementById('eb-count').textContent, csv: SPM.edit.draft() })"""
def ordered(board):   # values strictly down the overall order (only 0s tie)
    return all(a[4] > b[4] or (a[4] == 0 and b[4] == 0) for a, b in zip(board, board[1:]))
def one(board, name): return next(r for r in board if r[0] == name)

with sync_playwright() as pw:
    br = pw.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    errs = []
    def open_page(repo, token=True, ctx=None):
        ctx = ctx or br.new_context(viewport={"width": 1440, "height": 1000})
        ctx.add_init_script("window.__SPM_TEST_HOOKS = true;" + (" try { localStorage.setItem('spm_editor_token', 'test-token'); } catch (e) {}" if token else ""))
        pg = ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route("https://api.github.com/**", repo.handle)
        pg.route(re.compile(re.escape(BASE) + r"/(index\.html)?([?#].*)?$"), lambda r: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=repo.read("index.html")))
        def data_file(r):
            body = repo.read("data/" + r.request.url.split("/data/")[1].split("?")[0])
            r.fulfill(status=200 if body is not None else 404, content_type="application/json", body=body or b"{}")
        pg.route(re.compile(re.escape(BASE) + r"/data/(rank_history|injury_overrides|rank_snapshots/[^/?]+)\.json.*"), data_file)
        pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.(app|com)|use\.typekit\.net|fonts\.(googleapis|gstatic)\.com)/.*"), lambda r: r.abort())
        load(pg); return pg
    def load(pg):
        pg.goto(BASE + "/#rankings"); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1800)
        pg.click("#pos-chips button:has-text('QB')"); pg.wait_for_timeout(400)
    def state(pg): return pg.evaluate(STATE)
    def toast(pg): return pg.inner_text("#toast") if pg.locator("#toast").is_visible() else ""
    def clear_toast(pg): pg.evaluate("() => { const t = document.getElementById('toast'); t.textContent = ''; t.hidden = true; }")
    def wait_msg(pg):
        pg.wait_for_function("() => /Publish|Already live|Nothing to publish|Saved|Couldn/.test(document.getElementById('toast').textContent)", timeout=40000); pg.wait_for_timeout(400)
        return toast(pg)
    def start_save(pg): clear_toast(pg); pg.click("#eb-save"); pg.wait_for_timeout(900)   # the publish is now in flight (the mock holds each request)
    def close_warn(pg):
        if pg.locator("#ed-warn").is_visible(): pg.click('#ed-warn [data-ed="close"]'); pg.wait_for_timeout(150)
    def edge(pg, name, tier):   # the real tier-header button
        b = pg.locator(f'#rank-body tr.tier-edit button[data-tier-act="edge"][data-to="{tier}"]', has_text=name).first
        b.evaluate("b => b.click()"); pg.wait_for_timeout(400); close_warn(pg)
    def pid(pg, name): return pg.evaluate(f"() => SPM.edit.board().find(p => p.name === {json.dumps(name)}).id")
    def rank_move(pg, name, to): pg.evaluate(f"() => SPM.edit.moveOverall({pid(pg, name)}, {to})"); pg.wait_for_timeout(300); close_warn(pg)
    def set_value(pg, name, v): pg.evaluate(f"() => SPM.edit.setValue({pid(pg, name)}, {v})"); pg.wait_for_timeout(300); close_warn(pg)
    def fits(pg, name, delta=1):   # a value that fits his rank (between his neighbours)
        b = pg.evaluate(BOARD); i = next(k for k, r in enumerate(b) if r[0] == name)
        return b[i][4] + delta if b[i - 1][4] - b[i][4] > delta + 1 else b[i][4] - delta
    def oracle(repo, edits):   # the same edits on a fresh page loaded on the published board
        pg = open_page(repo); edits(pg); s = state(pg); pg.context.close(); return s
    def compare(label, s, o, pub_before, moved):   # the in-flight page after its publish vs the oracle; unaffected players vs GitHub
        same = s["board"] == o["board"] and s["touched"] == o["touched"] and s["unsaved"] == o["unsaved"]
        diff = [(a, b) for a, b in zip(s["board"], o["board"]) if a != b][:3]
        ok(same, f"{label}: the board after the publish equals the same edits made after it ({s['unsaved']} unsaved, touched {s['touched']}) {diff}")
        ok(ordered(s["board"]), f"{label}: values strictly down the overall order")
        pb = {r[0]: r for r in pub_before}
        changed = [r[0] for r in s["board"] if r[0] not in moved and pb.get(r[0]) and (pb[r[0]][3], pb[r[0]][4], pb[r[0]][5]) != (r[3], r[4], r[5])]
        ok(not changed, f"{label}: players not edited keep their published tier, value and source ({len(changed)} changed: {changed[:4]})")
    def run_case(n, fn):
        try: fn()
        except Exception as e:
            ok(False, f"case {n} crashed: {type(e).__name__}: {str(e)[:160]}")
            for c in br.contexts:
                try: c.close()
                except Exception: pass

    # 1. Burrow, exactly as reported
    def case_1():
        repo = new_repo(); repo.delay = 0.5; pg = open_page(repo)
        s0 = state(pg); b0 = one(s0["board"], "Joe Burrow")
        ok(b0[2] == 6 and b0[3] == "3" and b0[4] == 5760, f"Start: Burrow QB{b0[2]} Tier {b0[3]} {b0[4]}")
        edge(pg, "Burrow", "4"); b = one(pg.evaluate(BOARD), "Joe Burrow")
        ok(b[2] == 6 and b[3] == "4" and b[4] == 5379, f"Tier 4: QB{b[2]} Tier {b[3]} {b[4]}")
        e0, n0 = ev_count(repo), len(repo.log())
        start_save(pg)
        edge(pg, "Burrow", "3"); mid = one(pg.evaluate(BOARD), "Joe Burrow")
        ok(mid[3] == "3" and mid[4] == 5760, f"Back to Tier 3 while publishing: QB{mid[2]} Tier {mid[3]} {mid[4]}")
        msg = wait_msg(pg); s = state(pg); b = one(s["board"], "Joe Burrow"); pr = pub_row(repo, "Joe Burrow")
        ok("Published and confirmed" in msg and len(repo.log()) == n0 + 1 and ev_count(repo) == e0 + 1, f"The publish landed: one commit, one event ({msg[:60]!r})")
        ok(pr and pr[5] == "4" and pr[6] == "5379", f"GitHub holds Tier 4 · 5,379 (published row tier {pr and pr[5]}, value {pr and pr[6]})")
        ok(b[2] == 6 and b[3] == "3" and b[4] == 5760, f"After the publish: Burrow QB{b[2]} Tier {b[3]} {b[4]} (expected QB6 Tier 3 5,760)")
        ok(s["unsaved"] == 1 and "joe burrow|qb" in s["touched"] and pg.locator('#rank-body tr.player', has_text="Joe Burrow").locator(".rv-tag").count() == 1 and "still unsaved" in msg,
           f"…as an unsaved edit on the new baseline: {s['bar']}, touched {s['touched']}, Revalued tag, toast says so ({msg[-60:]!r})")
        band = pg.evaluate("() => { const h = document.querySelector('#rank-body tr.tier-edit[data-tier=\"3\"] .tier-meta'); return h && h.textContent; }")
        ok(band and band.endswith("5,760"), f"Tier 3 band note ends at 5,760 ({band!r})")
        pub_before = oracle(repo, lambda p: None)["board"]
        compare("Burrow", s, oracle(repo, lambda p: edge(p, "Burrow", "3")), pub_before, {"Joe Burrow"})
        # save it: the second publish carries Tier 3 · 5,760, one event and one snapshot more, nothing duplicated
        e1, k1, n1 = ev_count(repo), snap_count(repo), len(repo.log())
        clear_toast(pg); pg.click("#eb-save"); msg = wait_msg(pg); pr = pub_row(repo, "Joe Burrow"); s2 = state(pg)
        ok("Published and confirmed" in msg and pr[5] == "3" and pr[6] == "5760" and len(repo.log()) == n1 + 1 and ev_count(repo) == e1 + 1 and snap_count(repo) == k1 + 1 and s2["unsaved"] == 0 and s2["touched"] == [],
           f"Saved again: Tier 3 · 5,760 published in one commit, +1 event, +1 snapshot, All saved ({pr[5]}/{pr[6]}, {s2['bar']})")
        ok(json.loads(repo.read("data/rank_history.json"))["events"][-1]["ts"] != json.loads(repo.read("data/rank_history.json"))["events"][-2]["ts"], "The two publishes are two distinct events")
        pg.context.close()
    run_case(1, case_1)

    # 2. a rank move during the publish
    def case_2():
        repo = new_repo(); repo.delay = 0.5; pg = open_page(repo)
        set_value(pg, "Trevor Lawrence", fits(pg, "Trevor Lawrence"))   # the saved edit being published: unrelated
        start_save(pg); rank_move(pg, "Joe Burrow", 20); msg = wait_msg(pg); s = state(pg)
        pub_before = oracle(repo, lambda p: None)["board"]
        compare("Rank move #25 → #20 during the publish", s, oracle(repo, lambda p: rank_move(p, "Joe Burrow", 20)), pub_before, {"Joe Burrow"})
        b = one(s["board"], "Joe Burrow"); ok(b[1] == 20 and "Published" in msg, f"Burrow is #20 after the publish ({b[1]}, {b[4]})")
        pg.context.close()
    run_case(2, case_2)

    # 3. tier moves both directions during the publish
    def case_3():
        for name, tier, who in (("Goff", "3", "Jared Goff"), ("Burrow", "4", "Joe Burrow")):
            repo = new_repo(); repo.delay = 0.5; pg = open_page(repo)
            set_value(pg, "Trevor Lawrence", fits(pg, "Trevor Lawrence")); start_save(pg); edge(pg, name, tier); wait_msg(pg); s = state(pg)
            pub_before = oracle(repo, lambda p: None)["board"]
            compare(f"{who} → Tier {tier} during the publish", s, oracle(repo, lambda p: edge(p, name, tier)), pub_before, {who})
            b = one(s["board"], who); ok(b[3] == tier, f"{who} is in Tier {b[3]} at {b[4]}")
            pg.context.close()
    run_case(3, case_3)

    # 4. a manual value edit during the publish
    def case_4():
        repo = new_repo(); repo.delay = 0.5; pg = open_page(repo)
        edge(pg, "Burrow", "4"); start_save(pg); v = fits(pg, "Dak Prescott", 3); set_value(pg, "Dak Prescott", v); wait_msg(pg); s = state(pg)
        pub_before = oracle(repo, lambda p: None)["board"]
        compare(f"Value edit (Prescott {v}) during the publish", s, oracle(repo, lambda p: set_value(p, "Dak Prescott", v)), pub_before, {"Dak Prescott"})
        ok(one(s["board"], "Dak Prescott")[4] == v, f"The typed value is kept exactly ({one(s['board'], 'Dak Prescott')[4]})")
        pg.context.close()
    run_case(4, case_4)

    # 5. the same player before and during: Burrow to Tier 4 (saved), then one spot down while publishing
    def case_5():
        repo = new_repo(); repo.delay = 0.5; pg = open_page(repo)
        edge(pg, "Burrow", "4"); start_save(pg); rank_move(pg, "Joe Burrow", 26); wait_msg(pg); s = state(pg)
        pub_before = oracle(repo, lambda p: None)["board"]
        compare("Burrow Tier 4 saved, then #25 → #26 during the publish", s, oracle(repo, lambda p: rank_move(p, "Joe Burrow", 26)), pub_before, {"Joe Burrow"})
        pg.context.close()
    run_case(5, case_5)

    # 6. several edits during the publish
    def case_6():
        repo = new_repo(); repo.delay = 0.6; pg = open_page(repo)
        edge(pg, "Burrow", "4"); start_save(pg)
        v = fits(pg, "Brock Purdy", 2)
        def edits(p): edge(p, "Burrow", "3"); rank_move(p, "Caleb Williams", 24); set_value(p, "Brock Purdy", v)
        edits(pg); wait_msg(pg); s = state(pg)
        pub_before = oracle(repo, lambda p: None)["board"]
        compare("Three edits (tier, rank, value) during the publish", s, oracle(repo, edits), pub_before, {"Joe Burrow", "Caleb Williams", "Brock Purdy"})
        pg.context.close()
    run_case(6, case_6)

    # 7. Save, Cancel, reload, persisted edits
    def case_7():
        repo = new_repo(); repo.delay = 0.5; pg = open_page(repo)
        edge(pg, "Burrow", "4"); start_save(pg); edge(pg, "Burrow", "3"); wait_msg(pg)
        pub = oracle(repo, lambda p: None)
        pg.evaluate("SPM.edit.cancel()"); pg.wait_for_timeout(400); s = state(pg)
        ok(s["board"] == pub["board"] and s["unsaved"] == 0 and s["touched"] == [], f"Cancel after the in-flight edit: the published board exactly (Burrow {one(s['board'], 'Joe Burrow')[3:5]}), All saved")
        edge(pg, "Burrow", "3"); b = one(pg.evaluate(BOARD), "Joe Burrow"); ok(b[3] == "3" and b[4] == 5760, f"Tier 3 again on the new baseline: {b[4]}")
        # a failed publish keeps it saved in this browser; a reload keeps the value; then it publishes
        repo.faults["respond"] = lambda m, r: "abort"
        clear_toast(pg); pg.click("#eb-save"); msg = wait_msg(pg); repo.faults.clear()
        ok("Publish failed" in msg or "Couldn" in msg, f"Saved while GitHub is unreachable: kept in this browser ({msg[:60]!r})")
        load(pg); s = state(pg); b = one(s["board"], "Joe Burrow")
        ok(b[3] == "3" and b[4] == 5760 and s["unsaved"] == 0 and "joe burrow|qb" in s["touched"], f"After a reload the saved edit is still Tier 3 · {b[4]} ({s['bar']}, touched {s['touched']})")
        clear_toast(pg); pg.click("#eb-publish"); msg = wait_msg(pg); pr = pub_row(repo, "Joe Burrow")
        ok("Published and confirmed" in msg and pr[5] == "3" and pr[6] == "5760", f"Published later: Tier 3 · 5,760 ({pr[5]}/{pr[6]})")
        pg.context.close()
    run_case(7, case_7)

    # 8. faults with an in-flight edit
    def case_8():
        # a. the branch moved underneath the publish once (a retry), b. lost answer, c. offline after the commit then back online
        repo = new_repo(); repo.delay = 0.4; pg = open_page(repo); n0 = len(repo.log())
        seen = {"n": 0}
        def moved_once(method, rest):
            if method == "PATCH" and rest.startswith("/git/refs/") and seen["n"] == 0: seen["n"] += 1; return (422, {"message": "Update is not a fast forward"})
        repo.faults["respond"] = moved_once
        edge(pg, "Burrow", "4"); start_save(pg); edge(pg, "Burrow", "3"); msg = wait_msg(pg); repo.faults.clear(); s = state(pg)
        ok("Published and confirmed" in msg and seen["n"] == 1 and len(repo.log()) == n0 + 1, f"Branch moved once: retried, one commit ({msg[:50]!r})")
        compare("Retry with an in-flight edit", s, oracle(repo, lambda p: edge(p, "Burrow", "3")), oracle(repo, lambda p: None)["board"], {"Joe Burrow"})
        pg.context.close()
        repo = new_repo(); repo.delay = 0.4; pg = open_page(repo); n0 = len(repo.log()); repo.faults["patch_lost"] = True
        edge(pg, "Burrow", "4"); start_save(pg); edge(pg, "Burrow", "3"); msg = wait_msg(pg); repo.faults.clear(); s = state(pg)
        ok("Published and confirmed" in msg and len(repo.log()) == n0 + 1, f"Lost answer: found its commit, one commit ({msg[:50]!r})")
        compare("Lost answer with an in-flight edit", s, oracle(repo, lambda p: edge(p, "Burrow", "3")), oracle(repo, lambda p: None)["board"], {"Joe Burrow"})
        pg.context.close()
        repo = new_repo(); repo.delay = 0.4; pg = open_page(repo); n0 = len(repo.log()); repo.faults["offline_after_patch"] = True
        edge(pg, "Burrow", "4"); start_save(pg); edge(pg, "Burrow", "3"); msg = wait_msg(pg); s1 = state(pg)
        ok("not confirmed" in msg and len(repo.log()) == n0 + 1, f"Offline after the commit: not confirmed, the commit landed ({msg[:50]!r})")
        b1 = one(s1["board"], "Joe Burrow"); ok(b1[3] == "3" and b1[4] == 5760 and s1["unsaved"] == 1, f"Meanwhile the in-flight edit stays on the old baseline: Tier 3 · {b1[4]}, {s1['bar']}")
        repo.faults.clear(); e1, k1 = ev_count(repo), snap_count(repo)
        # Save with nothing new to save settles the unconfirmed publish first (Oct 13): it landed, so this browser adopts
        # the board GitHub holds (Tier 4 · 5,379), keeps the in-flight edit on top of it and, Save meaning publish, publishes
        # that edit in a new commit: no second commit for the first publish, no duplicate event or snapshot
        ev_first = json.loads(repo.read("data/rank_history.json"))["events"][-1]
        clear_toast(pg); pg.click("#eb-save"); msg = wait_msg(pg); s = state(pg); b = one(s["board"], "Joe Burrow"); pr = pub_row(repo, "Joe Burrow")
        evs = json.loads(repo.read("data/rank_history.json"))["events"]
        ok("earlier publish had landed" in msg and "Published and confirmed" in msg and len(repo.log()) == n0 + 2 and ev_count(repo) == e1 + 1 and snap_count(repo) == k1 + 1
           and evs.count(ev_first) == 1 and not pg.evaluate("() => !!localStorage.getItem('spm_publish_pending')"),
           f"Back online, Save: settled (no second commit for the landed publish, its event once), then the later edit published in one new commit ({msg[:60]!r})")
        ok(b[3] == "3" and b[4] == 5760 and s["unsaved"] == 0 and s["touched"] == [] and pr[5] == "3" and pr[6] == "5760",
           f"…the in-flight edit survived the settlement and is now published: Tier {b[3]} · {b[4]}, {s['bar']} (GitHub: Tier {pr[5]} · {pr[6]})")
        load(pg); s = state(pg); b = one(s["board"], "Joe Burrow")
        ok(b[3] == "3" and b[4] == 5760 and s["unsaved"] == 0 and s["touched"] == [], f"After a reload: the published Tier 3 · {b[4]}, {s['bar']}")
        pg.context.close()
        # d. a pending commit that never landed is forgotten and the saved edits publish as usual
        repo = new_repo(); pg = open_page(repo); n0 = len(repo.log())
        pg.evaluate("() => localStorage.setItem('spm_publish_pending', JSON.stringify({ id: 'ghost', commit: 'f'.repeat(40), at: new Date().toISOString() }))")
        edge(pg, "Burrow", "4"); clear_toast(pg); pg.click("#eb-save"); msg = wait_msg(pg); pr = pub_row(repo, "Joe Burrow")
        ok("Published and confirmed" in msg and len(repo.log()) == n0 + 1 and pr[5] == "4" and not pg.evaluate("() => !!localStorage.getItem('spm_publish_pending')"),
           f"A pending commit GitHub never had: forgotten, the edit publishes in one commit ({msg[:40]!r})")
        pg.context.close()
        # e. GitHub unreachable while checking: it stays pending, nothing changes, the message says so
        repo = new_repo(); repo.delay = 0.4; pg = open_page(repo); n0 = len(repo.log()); repo.faults["offline_after_patch"] = True
        edge(pg, "Burrow", "4"); start_save(pg); edge(pg, "Burrow", "3"); wait_msg(pg)
        s1 = state(pg); e1 = ev_count(repo); repo.faults["respond"] = lambda m, r: "abort"
        clear_toast(pg); pg.click("#eb-save"); msg = wait_msg(pg); s2 = state(pg); repo.faults.clear()
        ok("not confirmed" in msg and s2["board"] == s1["board"] and pg.evaluate("() => !!localStorage.getItem('spm_publish_pending')") and len(repo.log()) == n0 + 1,
           f"Still offline at the next Save: still pending, the board unchanged, no commit ({msg[:60]!r})")
        ok(pg.locator("#eb-save").is_disabled() and not pg.locator("#eb-publish").is_disabled(), "The in-flight edit was saved by that attempt: Save is done, Publish is offered")
        clear_toast(pg); pg.locator("#eb-publish").evaluate("b => b.click()"); msg = wait_msg(pg); b = one(state(pg)["board"], "Joe Burrow")
        ok("earlier publish had landed" in msg and b[3] == "3" and b[4] == 5760 and len(repo.log()) == n0 + 2 and ev_count(repo) == e1 + 1, f"Online again, Publish: settled (no second commit for it), Tier 3 · {b[4]} kept and published in one new commit ({msg[:50]!r})")
        pg.context.close()
        # f. an ordinary Save with no pending publish and nothing to save stays a no-op
        repo = new_repo(); pg = open_page(repo); n0 = len(repo.log()); calls0 = len(repo.calls)
        dis = pg.locator("#eb-save").is_disabled(); pg.locator("#eb-save").evaluate("b => b.click()"); pg.wait_for_timeout(1500)
        ok(dis and len(repo.log()) == n0 and len([c for c in repo.calls[calls0:] if c[0] != "GET"]) == 0 and state(pg)["unsaved"] == 0, f"Save with nothing to save and nothing pending: the button is disabled, no GitHub write, no commit")
        pg.context.close()
    run_case(8, case_8)

    ok(not errs, f"No page errors {errs[:2]}")
    br.close()

print("\n" + ("All in-flight publish checks passed." if not failures else f"{len(failures)} check(s) failed."))
sys.exit(1 if failures else 0)
