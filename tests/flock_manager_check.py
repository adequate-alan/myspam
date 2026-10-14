"""Flock list manager (Alan, Oct 14): import, preview, draft editing and publishing of the two Flock market lists.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/flock_manager_check.py

The page is served from this checkout; GitHub is the in-memory repository of tests/gh_mock.py holding the two list files
and the Superflex snapshot month (nothing reaches GitHub or the files on disk). Checks:
  · the import preview of the real Superflex export (the snapshot's original CSV): rows, matched by ID / by name,
    unmatched with their Flock IDs and reasons, the duplicate row, nothing moved against the published list
  · an import needs its format confirmed (nothing assumed, nothing saved); a confirmed QB format that isn't the list's
    own is refused both ways (a Superflex export never goes into Flock Regular PPR, nor a 1QB one into Flock Superflex)
  · moved / new / no longer listed against the published list on a synthetic version of the export
  · draft editing: move to rank, up / down, remove, a manual match; a manual match to a player already in the list, to
    another position or to the duplicate's own player is refused; the duplicate stays unmatched and unpriced
  · Save draft keeps every row (matched in rows, the rest unmatched) and only verified identities are priced; the draft
    survives a reload; an old browser list (spm_flock) comes back as an unpublished, unpriced draft, spm_flock kept
  · Publish = one commit writing only the list's file and one appended snapshot entry (earlier entries byte for byte),
    both valid for static_check; the token is in no committed file; a list published elsewhere since the draft stops
    the publish until confirmed; a lost answer is settled by the next Publish without a second commit
  · the AM board (SPM.rankingSnapshot) is identical before and after; the manager fits a 390px screen; no page errors
"""
import csv, functools, http.server, io, json, os, re, socketserver, sys, tempfile, threading
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gh_mock import Repo
import static_check as SC

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

SF_PATH, PPR_PATH = "data/market/flock_sf.json", "data/market/flock_ppr.json"
SNAP_PATH = "data/market/flock_snapshots/flock-sf/2026-10.json"
raw = lambda p: open(os.path.join(ROOT, p), "rb").read()
# the lists as the migration published them (tests/fixtures/flock/, copies at 15046cb), served and committed in place of
# the live files, so a real list published from the manager never changes what this suite starts from
FIX = {SF_PATH: "tests/fixtures/flock/flock_sf.json", PPR_PATH: "tests/fixtures/flock/flock_ppr.json", SNAP_PATH: "tests/fixtures/flock/flock-sf-2026-10.json"}
fixed = lambda p: raw(FIX.get(p, p))
SF, SNAPF = json.loads(fixed(SF_PATH)), json.loads(fixed(SNAP_PATH))
SNAP_CSV = SNAPF["snapshots"][0]["csv"]
C = {c: i for i, c in enumerate(SF["cols"])}
SF_SIDS = {r[C["sleeper_id"]] for r in SF["rows"]}
SP = json.loads(raw("data/sleeper_players.json"))
norm = lambda s: re.sub(r"[^a-z0-9]+", " ", re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", re.sub(r"[.'’`]", "", str(s).lower()))).strip()
names = {}
for sid, v in SP.items(): names.setdefault((norm(v[0]), v[1]), []).append(sid)
BOARD_SIDS = set(re.findall(r",(\d{2,6}),(?:manual|auto)\b", raw("index.html").decode()))   # the AM boards name players too
def outsider(pos, skip=()):   # a player of that position in our files, not in the published list or on a board, with a unique name
    for sid, v in SP.items():
        if v[1] == pos and sid not in SF_SIDS and sid not in BOARD_SIDS and sid not in skip and len(names[(norm(v[0]), pos)]) == 1 and len(norm(v[0])) > 6 and v[2]:
            return sid, v
NEW_SID, NEW = outsider("WR")
RB_SID, RB = outsider("RB")
WR_SID = NEW_SID

# a synthetic next version of the export: #20 and #21 swap, #30 is replaced by a player not in the list
src = list(csv.reader(io.StringIO(SNAP_CSV))); H = {h: i for i, h in enumerate(src[0])}
body = sorted(src[1:], key=lambda r: int(r[H["Rank"]]))
by_rank = {int(r[H["Rank"]]): r for r in body}
a, b = by_rank[20], by_rank[21]; a[H["Rank"]], b[H["Rank"]] = "21", "20"
gone = by_rank[30]; GONE_NAME = gone[H["Name"]]
new = list(gone); new[H["player_id"]], new[H["Name"]], new[H["Team"]], new[H["Position"]] = NEW_SID, NEW[0], NEW[2], NEW[1]
body[body.index(gone)] = new
buf = io.StringIO(); csv.writer(buf, lineterminator="\n").writerows([src[0]] + body); V2_CSV = buf.getvalue()
SWAPPED = {a[H["Name"]], b[H["Name"]]}

tmp = tempfile.mkdtemp()
def tfile(name, text):
    p = os.path.join(tmp, name); open(p, "w", encoding="utf-8").write(text); return p
CSV_REAL, CSV_V2 = tfile("REDRAFT_SF-rankings.csv", SNAP_CSV), tfile("REDRAFT_SF-next.csv", V2_CSV)

def serve():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]
port = serve()

repo = Repo({SF_PATH: fixed(SF_PATH), PPR_PATH: fixed(PPR_PATH), SNAP_PATH: fixed(SNAP_PATH)}, login="tester")
def tree_files(commit):
    out, todo = {}, [("", repo.commits[commit]["tree"])]
    while todo:
        pre, t = todo.pop()
        for k, (typ, sha) in repo.trees[t].items():
            if typ == "tree": todo.append((pre + k + "/", sha))
            else: out[pre + k] = repo.blobs[sha]
    return out

with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    errs = []
    def page(init="", width=1440, token=True, ctx=None):
        ctx = ctx or br.new_context(viewport={"width": width, "height": 1000})
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("dialog", lambda d: (errs.append("dialog: " + d.message), d.dismiss()))
        pg.route(re.compile(r"https://(?!api\.github\.com).*"), lambda r: r.abort())
        pg.route("https://api.github.com/**", repo.handle)
        pg.route(re.compile(r".*/(data/market/flock_(?:sf|ppr)\.json)(\?.*)?$"), lambda r: r.fulfill(status=200, content_type="application/json",
                 body=fixed(re.match(r".*/(data/market/flock_(?:sf|ppr)\.json)", r.request.url).group(1))))
        pg.add_init_script("window.__SPM_TEST_HOOKS = true;" + ("try { localStorage.setItem('spm_editor_token', 'test-token'); } catch (e) {}" if token else "") + init)
        pg.goto(f"http://127.0.0.1:{port}/#rankings"); until(pg, "() => document.querySelector(\"#rank-body tr.player\")")
        until(pg, "() => SPM.market && SPM.market().lists.some(l => l.loaded)", 20)
        pg.evaluate("() => { const s = document.getElementById('rk-sort'); s.value = 'mkbuy'; s.dispatchEvent(new Event('change')); }")
        until(pg, "() => document.querySelector(\"[data-mk-flock]\")"); click(pg, "[data-mk-flock]"); until(pg, "() => document.querySelector(\"#fm\")")
        return pg
    # clicks and typing through the DOM: after a reload headless Chromium sometimes stops painting frames (also on main),
    # so Playwright's visibility waits would hang; the handlers under test are the same
    def until(pg, expr, secs=30):   # polls with plain evaluate calls (no animation-frame or in-page polling)
        for _ in range(secs * 10):
            try:
                if pg.evaluate(expr): return
            except Exception: pass
            pg.wait_for_timeout(100)
        raise TimeoutError(expr)
    def click(pg, sel): pg.eval_on_selector(sel, "e => e.click()"); pg.wait_for_timeout(60)
    def fill(pg, sel, text): pg.eval_on_selector(sel, "(e, t) => { e.focus(); e.value = t; e.dispatchEvent(new Event('input', { bubbles: true })); }", text)
    def fmt(pg, qb, teams="12", tep="0", rec="1"):
        pg.evaluate("v => Object.entries(v).forEach(([id, x]) => { const s = document.getElementById(id); s.value = x; s.dispatchEvent(new Event('change', { bubbles: true })); })",
                    {"mk-fl-qb": qb, "mk-fl-teams": teams, "mk-fl-tep": tep, "mk-fl-rec": rec})
    def upload(pg, path):
        pg.locator("#mk-file").set_input_files(path); pg.wait_for_timeout(900)
    msg = lambda pg: pg.inner_text("#fm .mk-msg") if pg.locator("#fm .mk-msg").count() else ""
    store = lambda pg, k: pg.evaluate(f"() => JSON.parse(localStorage.getItem('{k}') || 'null')")
    lists = lambda pg: {x["id"]: x for x in pg.evaluate("() => SPM.market().lists")}

    pg = page()
    snap0 = pg.evaluate("() => SPM.rankingSnapshot()")
    # 1. the format has to be confirmed; the QB format must be the list's own
    upload(pg, CSV_REAL)
    ok("Confirm the list's format first" in msg(pg) and pg.locator("[data-fm-save]").count() == 0 and store(pg, "spm_flock:sf") is None,
       f"No format confirmed: refused, no preview, nothing saved ({msg(pg)[:60]!r})")
    fmt(pg, "1qb"); upload(pg, CSV_REAL)
    ok("Nothing was saved" in msg(pg) and "Flock Superflex takes a Superflex" in msg(pg) and pg.locator("[data-fm-save]").count() == 0 and store(pg, "spm_flock:sf") is None and store(pg, "spm_flock:ppr") is None,
       f"A 1QB export can't go into Flock Superflex: {msg(pg)[:90]!r}")
    click(pg, "[data-fm-set='flock-ppr']"); fmt(pg, "sf"); upload(pg, CSV_REAL)
    ok("Flock Regular PPR takes a 1QB" in msg(pg) and pg.locator("[data-fm-save]").count() == 0 and store(pg, "spm_flock:ppr") is None,
       f"A Superflex export can't go into Flock Regular PPR: {msg(pg)[:90]!r}")
    click(pg, "[data-fm-set='flock-sf']")

    # 2. preview of the real export
    fmt(pg, "sf"); upload(pg, CSV_REAL)
    summ, diff = pg.inner_text("[data-fm-sum]"), pg.inner_text("[data-fm-diff]")
    nid = sum(r[C["match"]] == "id" for r in SF["rows"]); nnm = sum(r[C["match"]] == "name" for r in SF["rows"])
    ok(f"{len(SF['rows']) + len(SF['unmatched'])} rows" in summ and f"{len(SF['rows'])} matched ({nid} by Flock ID · {nnm} by name · 0 picked by hand)" in summ
       and f"{len(SF['unmatched'])} unmatched" in summ and "1 duplicate" in summ, f"Preview counts on the real export: {summ!r}")
    ok("0 moved · 0 new · 0 no longer listed" in diff, f"The same export reads unchanged against the published list: {diff!r}")
    un = pg.inner_text("[data-fm-sec='unmatched']")
    ok(all(u["flock_id"] in un for u in SF["unmatched"]) and "unresolved Flock ID" in un and "same player as #" in un,
       "Unmatched rows show their Flock IDs and reasons; the duplicate names the player it repeats")
    ok(store(pg, "spm_flock:sf") is None, "Nothing is saved by the preview")
    click(pg, "[data-fm-cancel]")

    # 3. moved / new / no longer listed
    fmt(pg, "sf"); upload(pg, CSV_V2)
    diff = pg.inner_text("[data-fm-diff]")
    ok("2 moved · 1 new · 1 no longer listed" in diff, f"A new version: two swapped players moved, one new, one gone: {diff!r}")
    click(pg, "[data-fm-sec='moved'] summary"); click(pg, "[data-fm-sec='new'] summary"); click(pg, "[data-fm-sec='dropped'] summary")
    mv, nw, dr = (pg.inner_text(f"[data-fm-sec='{k}']") for k in ("moved", "new", "dropped"))
    ok(all(n in mv for n in SWAPPED) and NEW[0] in nw and GONE_NAME in dr, f"Moved {sorted(SWAPPED)}, new {NEW[0]}, no longer listed {GONE_NAME}")

    # 4. editing the draft: manual match (and its refusals), move to rank, up / down, remove
    items = lambda: pg.evaluate("() => SPM.flockManager().work.items.map(it => [it.name, it.pos, it.sid, it.how, it.dup])")
    it0 = items()
    ej = next(i for i, x in enumerate(it0) if x[0] == "Emmett Johnson")
    dup = next(i for i, x in enumerate(it0) if x[4])
    click(pg, f"[data-fm-sec='unmatched'] [data-fm-pick='{ej}']"); fill(pg, "#fm-pq", RB[0][:12]); pg.wait_for_timeout(200)
    def inject(sid):   # a hand-made button for a player the search wouldn't offer: the guard itself must refuse
        pg.evaluate("sid => { const b = document.createElement('button'); b.type = 'button'; b.dataset.fmSid = sid; b.id = 'fm-inj'; document.getElementById('fm-res').append(b); }", sid)
        click(pg, "#fm-inj")
    gibbs = next(r[C["sleeper_id"]] for r in SF["rows"] if r[C["pos"]] == "RB")
    ok(pg.locator(f"#fm-res [data-fm-sid='{gibbs}']").count() == 0, "The player search only offers players of the row's position")
    inject(gibbs)
    ok("already in this list" in msg(pg) and items()[ej][2] == "", f"A manual match to a player already in the list is refused: {msg(pg)[:80]!r}")
    click(pg, f"[data-fm-sec='unmatched'] [data-fm-pick='{ej}']"); inject(WR_SID)
    ok("is a WR, and this row is a RB" in msg(pg) and items()[ej][2] == "", "A manual match to another position is refused")
    click(pg, f"[data-fm-sec='unmatched'] [data-fm-pick='{dup}']"); inject(it0[dup][4])
    ok("already in this list" in msg(pg) and items()[dup][2] == "" and items()[dup][4], "The duplicate row can't be matched to the player it repeats; it stays unmatched")
    click(pg, f"[data-fm-sec='unmatched'] [data-fm-pick='{ej}']"); fill(pg, "#fm-pq", RB[0]); pg.wait_for_timeout(200)
    click(pg, f"#fm-res [data-fm-sid='{RB_SID}']")
    ok(items()[ej][2] == RB_SID and items()[ej][3] == "manual" and "picked by hand" in msg(pg), f"Emmett Johnson's row matched by hand to {RB[0]} (match manual)")
    click(pg, "[data-fm-sec='all'] summary")
    first = items()[4][0]
    click(pg, "#fm-rows [data-fm-mv='4']"); fill(pg, "#fm-mvn", "2"); pg.eval_on_selector("#fm-mvn", "e => e.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))"); pg.wait_for_timeout(150)
    ok(items()[1][0] == first, f"Move to rank: #5 {first} → #2")
    top = items()[0][0]; click(pg, "#fm-rows [data-fm-dn='0']")
    ok(items()[1][0] == top, f"▼ moves #1 {top} down one")
    gone_name = items()[9][0]; n_before = len(items())
    click(pg, "#fm-rows [data-fm-rm='9']")
    ok(len(items()) == n_before - 1 and gone_name not in [x[0] for x in items()], f"Remove takes #10 {gone_name} out")
    order = [x[0] for x in items()]
    click(pg, "[data-fm-save]"); pg.wait_for_timeout(600)
    D = store(pg, "spm_flock:sf")
    ok(D and [x["name"] for x in D["items"]] == order and len(D["items"]) == n_before - 1, "Save draft keeps every row in the edited order (matched and unmatched)")
    pri = [r[0] for r in D["rows"]]
    ok(len(pri) == len(set(pri)) and all(x["how"] in ("id", "name", "manual") for x in D["items"] if x["sid"]) and sum(1 for x in D["items"] if x["sid"]) == len(pri)
       and all(not x["sid"] for x in D["items"] if x["dup"]), f"Only verified identities are priced, each player once ({len(pri)} priced)")
    L = lists(pg)["flock-sf"]
    ok(L["draft"] and L["rows"] == len(pri) and not L["site"], "The saved draft is this browser's Flock Superflex list")
    ok("Saved in this browser" in pg.inner_text("#fm .fm-state") and "not published" in pg.inner_text("#fm .fm-state"), "The manager shows the unpublished draft")

    # 5. the draft survives a reload
    pg.reload(wait_until="domcontentloaded"); pg.wait_for_timeout(3000)
    until(pg, "() => document.querySelector(\"[data-mk-flock]\")"); click(pg, "[data-mk-flock]"); until(pg, "() => document.querySelector(\"#fm\")")
    D2 = store(pg, "spm_flock:sf")
    ok(D2["items"] == D["items"] and lists(pg)["flock-sf"]["draft"] and "Saved in this browser" in pg.inner_text("#fm .fm-state"), "The draft is the same after a reload")

    # 6. publish: one commit, the list's file and one appended snapshot entry, nothing else
    head0, log0 = repo.head, repo.log()
    before = tree_files(head0)
    click(pg, "[data-fm-publish]"); until(pg, "() => !SPM.flockManager().busy", 30); pg.wait_for_timeout(300)
    ok("Published and confirmed" in msg(pg), f"Publish: {msg(pg)[:90]!r}")
    log1 = repo.log()
    ok(len(log1) == len(log0) + 1 and re.fullmatch(r"Flock Superflex list by @tester \(\d+ players\)", log1[-1]), f"One commit: {log1[-1]!r}")
    after = tree_files(repo.head)
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    snap_now = [k for k in changed if k.startswith("data/market/flock_snapshots/flock-sf/")]
    ok(len(changed) == 2 and SF_PATH in changed and len(snap_now) == 1, f"The commit writes only the list file and its snapshot month: {changed}")
    live = json.loads(after[SF_PATH])
    ok([r[0] for r in live["rows"]] == pri and live["fmt"] == {"qb": "sf", "teams": 12, "rec": 1, "tep": 0} and live["by"] == "tester" and live["version"] == 2
       and len(live["rows"]) + len(live["unmatched"]) == len(D["items"]), "The published file holds the draft: priced rows, unmatched rows, format, by")
    ok(any(r[C["match"]] == "manual" and r[0] == RB_SID for r in live["rows"]), "The manual match is published as match \"manual\"")
    sp = snap_now[0]
    old_b, new_b = before.get(sp), after[sp]
    if old_b is not None:
        ok(new_b.startswith(old_b.rstrip()[:-2]) and len(json.loads(new_b)["snapshots"]) == len(json.loads(old_b)["snapshots"]) + 1,
           "The snapshot month gets one entry appended; earlier entries are byte for byte the same")
    ent = json.loads(new_b)["snapshots"][-1]
    ok(ent["rows"] == live["rows"] and ent["unmatched"] == live["unmatched"] and ent["published"] == live["published"] and ent.get("csv") == V2_CSV and ent.get("edited") is True,
       "The snapshot entry is the published list, with the original export and an edited flag")
    errs_sc = SC.flock_errors(SF_PATH, live) + sum((SC.flock_errors(f"{sp} #{k}", {"version": 2, "set": "flock-sf", **s}) for k, s in enumerate(json.loads(new_b)["snapshots"])), [])
    ok(not errs_sc, f"static_check accepts the published file and every snapshot entry (manual included): {errs_sc[:2]}")
    ok(not any(b"test-token" in v for v in after.values()) and all(a == "Bearer test-token" for a in repo.token_seen), "The token is in no committed file (only in the Authorization header)")
    ok(store(pg, "spm_flock:sf") is None and lists(pg)["flock-sf"]["site"], "After publishing, the draft is gone and the published list is used")
    ok(after[PPR_PATH] == before[PPR_PATH], "Flock Regular PPR is untouched")

    # 7. published elsewhere since the draft: stopped until confirmed
    click(pg, "[data-fm-edit='pub']"); click(pg, "[data-fm-sec='all'] summary"); click(pg, "#fm-rows [data-fm-dn='2']"); click(pg, "[data-fm-save]"); pg.wait_for_timeout(400)
    other = json.loads(after[SF_PATH]); other["published"] = "2026-10-14T23:00:00Z"; other["by"] = "someone"
    repo.commit_file(SF_PATH, (json.dumps(other) + "\n").encode(), "Flock Superflex list by @someone")
    n0 = len(repo.log())
    click(pg, "[data-fm-publish]"); until(pg, "() => !SPM.flockManager().busy", 30); pg.wait_for_timeout(200)
    ok("published elsewhere" in msg(pg) and len(repo.log()) == n0 and store(pg, "spm_flock:sf"), f"A list published elsewhere stops the publish, draft kept: {msg(pg)[:80]!r}")
    ok(pg.inner_text("[data-fm-publish]") == "Publish over it", "The button then asks to publish over it")
    # 8. a lost answer: the commit lands, the browser never hears; the next Publish settles it without committing twice
    repo.faults["offline_after_patch"] = True
    click(pg, "[data-fm-publish]"); until(pg, "() => !SPM.flockManager().busy", 60); pg.wait_for_timeout(200)
    ok("Publish not confirmed" in msg(pg) and len(repo.log()) == n0 + 1 and store(pg, "spm_flock:sf"), f"Lost answer: not confirmed, draft kept, the commit landed: {msg(pg)[:80]!r}")
    repo.faults.pop("offline", None)
    click(pg, "[data-fm-publish]"); until(pg, "() => !SPM.flockManager().busy", 30); pg.wait_for_timeout(200)
    ok("earlier publish had landed" in msg(pg) and len(repo.log()) == n0 + 1 and store(pg, "spm_flock:sf") is None, f"The next Publish finds it landed, no second commit: {msg(pg)[:80]!r}")
    ok(json.loads(repo.read(SF_PATH))["by"] == "tester", "The list on GitHub is the one published from here")

    ok(pg.evaluate("() => SPM.rankingSnapshot()") == snap0, "The AM board (ranks, tiers, values) is identical after importing, editing and publishing")
    pg.close()

    # 9. an old browser list (spm_flock) becomes an unpublished, unpriced draft; spm_flock is kept
    legacy = {"at": "2026-10-10T12:00:00Z", "sf": True, "teams": 12, "tep": 0, "rec": 1, "file": "old.csv",
              "rows": [[SF["rows"][i][C["sleeper_id"]], i + 1, i + 1, "A"] for i in range(5)], "missed": ["Kyle Williams · Flock ID 7437 (no player)"]}
    pg = page(init=f"localStorage.setItem('spm_flock', {json.dumps(json.dumps(legacy))});", token=False)
    D = store(pg, "spm_flock:sf")
    ok(D and D["draft"] and D["legacy"] and len(D["items"]) == 6 and not D["rows"] and all(not x["sid"] for x in D["items"]) and pg.evaluate("() => !!localStorage.getItem('spm_flock')"),
       "spm_flock becomes an unpublished draft of Flock Superflex, nothing priced until verified; spm_flock is kept")
    L = lists(pg)["flock-sf"]
    ok(L["site"] and not L["draft"], "The published list stays in use while the old draft has no verified row")
    pg.wait_for_timeout(800)
    st = pg.inner_text("#fm .fm-state")
    ok("older import" in st and "not published" in st, f"The manager shows the old list as an unpublished draft: {st[-120:]!r}")
    click(pg, "[data-fm-publish]"); pg.wait_for_timeout(300)
    ok("sign in" in msg(pg).lower() and len(repo.log()) == n0 + 1, "Without a token nothing is published")
    pg.close()

    # 10. phones: the manager with a preview fits 390px
    pg = page(width=390, token=False)
    fmt(pg, "sf"); upload(pg, CSV_V2); click(pg, "[data-fm-sec='all'] summary"); pg.wait_for_timeout(200)
    over = pg.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
    ok(over <= 0 and pg.eval_on_selector("[data-fm-save]", "e => e.getBoundingClientRect().right <= window.innerWidth"), f"At 390px the manager fits without sideways scrolling ({over}px)")
    pg.close()
    br.close()

ok(not errs, f"No page errors: {errs[:3]}")
print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
