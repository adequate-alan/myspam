"""Ranking history: publish events, exact board snapshots and the player page (Alan, Oct 11). The page's real publish
code runs against an in-memory GitHub repository (tests/gh_mock.py); nothing reaches GitHub or the files on disk.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/history_check.py

Checks:
1. Moving a player down one spot publishes ONE commit holding index.html, data/rank_history.json and
   data/rank_snapshots/<YYYY-MM>.json together (atomic: the rankings are never live without their history). Values are
   stored (Oct 12), so the publish is exactly 2 ranking changes (the two players who swapped, with from/to ranks), no
   value edits and no automatic repricing; only the moved player's value changed; every entry carries a kind and the
   publish time.
2. The snapshot is the exact board: every ranked player's overall rank, position rank, tier and value (4 fields, no
   typed flag), equal to what the page shows and to the published value column, tagged valueModelVersion
   "state-baseline-v1".
3. Moving him back adds a second snapshot to the same month file, the event counts exactly 1 repriced value (his),
   and the board is back exactly.
4. Editing a value by 3 points (far under the 0.5% line) is still a value edit: kind V, listed in the event with from
   the published value to the new one.
5. Publishing nothing new writes no history commit.
6. "AM value at the time" (valueAt) reads the exact snapshot at or before a time, and falls back to the history entries
   before the first snapshot.
7. The player page: actions read "Rank changed: #7 → #8" and "Value edited: 7,780 → 7,777"; repricing rows (older
   events) are muted "Model repriced" with "Same publish as … CeeDee Lamb #7 → #8", and two in a row collapse into one
   row with Show / Hide.
8. Older entries keep their stored fields; the page still renders players with legacy (untagged) entries.
9. Failures and retries: another writer committing a snapshot mid-publish (both kept, ours once), the answer to the
   branch update lost after GitHub applied it (checked, reported as published, one event), a read-back mismatch
   (reported, nothing half-written); never a duplicate event, snapshot or entry.
Runs on the frozen test board (tests/fixture_board.py): the in-memory repository starts from the current code with the
fixture rankings block, the fixture history and no snapshot file yet, so CeeDee #7, St. Brown #8 and Puka's value hold
whatever the live rankings say. The files on disk are only checked to be unchanged.
"""
import functools, hashlib, http.server, json, os, re, socketserver, sys, threading
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gh_mock import Repo
import fixture_board as FB

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DISK = {f: hashlib.sha256(open(os.path.join(ROOT, f), "rb").read()).hexdigest() for f in ("index.html", "data/rank_history.json")}
ORIG = FB.html()                                   # the current code with the frozen test board
HIST = FB.files()["data/rank_history.json"]        # its history (the fixture's snapshot file is left out: the first publish creates the month)
INJ = open(os.path.join(ROOT, "data/injury_overrides.json"), "rb").read()
MIN_ABS, MIN_PCT = 10, 0.005

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"

repo = Repo({"index.html": ORIG, "data/rank_history.json": HIST, "data/injury_overrides.json": INJ})
def hist(): return json.loads(repo.read("data/rank_history.json"))
def snapfile(month):
    b = repo.read(f"data/rank_snapshots/{month}.json"); return json.loads(b) if b else None
def publish_commits(): return [c for c in repo.log() if c.startswith("Rankings edit") or c.startswith("Ranking history")]
def changed(last, cur):   # same rule as the page
    if last is None: return True
    if last[1] != cur[0] or last[2] != cur[1] or (last[3] != "" and cur[2] != "" and str(last[3]) != str(cur[2])): return True
    return abs((last[4] or 0) - cur[3]) >= max(MIN_ABS, MIN_PCT * max(last[4] or 0, cur[3]))

with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    errs = []
    ctx = br.new_context(viewport={"width": 1440, "height": 1000})
    pg = ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("https://api.github.com/**", repo.handle)
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.(app|com)|use\.typekit\.net|fonts\.(googleapis|gstatic)\.com)/.*"), lambda r: r.abort())
    pg.route(re.compile(re.escape(BASE) + r"/(index\.html)?([?#].*)?$"), lambda r: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=repo.read("index.html")))
    def data_file(r):
        path = "data/" + r.request.url.split("/data/")[1].split("?")[0]; body = repo.read(path)
        r.fulfill(status=200 if body is not None else 404, content_type="application/json", body=body or b"{}")
    pg.route(re.compile(re.escape(BASE) + r"/data/(rank_history|injury_overrides|rank_snapshots/[^/]+)\.json.*"), data_file)
    pg.add_init_script("try { localStorage.setItem('spm_editor_token', 'test-token'); } catch (e) {}")
    pg.goto(BASE + "/#rankings"); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1500)
    pg.click("#pos-chips button:has-text('All')"); pg.wait_for_timeout(300)

    def arrow(name, d):
        pg.locator("#rank-body tr.player", has_text=name).first.locator(f'.arrow[data-dir="{d}"]').evaluate("b => b.click()"); pg.wait_for_timeout(350)
    def save():
        pg.evaluate("() => { const t = document.getElementById('toast'); t.textContent = ''; t.hidden = true; }")
        pg.click("#eb-save")
        pg.wait_for_function("() => /Publish|Already live|Nothing to publish|Saved/.test(document.getElementById('toast').textContent)", timeout=20000)
        pg.wait_for_timeout(400); return pg.inner_text("#toast")
    snap_now = lambda: pg.evaluate("() => SPM.rankingSnapshot()")
    local_edits_empty = lambda: pg.evaluate("() => !Object.keys(JSON.parse(localStorage.getItem('spm_local_edits') || '{}')).length")
    sid_of = lambda name: pg.evaluate("n => { const r = [...document.querySelectorAll('#rank-body tr.player')].find(tr => tr.querySelector('.pl-name').textContent.trim() === n); return r && r.querySelector('[data-sid]') ? r.querySelector('[data-sid]').dataset.sid : null; }", name)
    names = {k: v[0] for k, v in json.load(open(os.path.join(ROOT, "data/sleeper_players.json"))).items()}
    sid = {n: s for s, n in names.items()}
    LAMB, STB, PUKA = sid["CeeDee Lamb"], sid["Amon-Ra St. Brown"], sid["Puka Nacua"]

    # 1. CeeDee down one spot
    before = hist(); before_snap = snap_now(); c0 = len(publish_commits())
    msg = save if False else None
    arrow("CeeDee Lamb", 1); toast = save()
    h1 = hist(); ev = h1["events"][-1]; month = ev["ts"][:7]; s1 = snapfile(month)
    new = publish_commits()[c0:]
    ok(len(new) == 1 and new[0].startswith("Rankings edit by @tester"), f"One commit for the publish: {[m.splitlines()[0] for m in new]}")
    ok(re.search(r"\n\nRanking history: 2 ranking changes$", new[0] if new else "") is not None, f"Commit message: exactly 2 ranking changes, no repricing: {new[0].splitlines()[-1] if new else None}")
    ok("Ranking history: 2 ranking changes" in toast, f"Toast names the split: {toast!r}")
    head = repo.commits[repo.head]
    ok(repo.read(f"data/rank_snapshots/{month}.json") is not None and repo.read("data/rank_history.json", repo.commits[repo.head]["parents"][0]) == repo.read("data/rank_history.json", repo.commits[repo.head]["parents"][0]),
       "The history commit holds the snapshot file")
    parent = head["parents"][0]
    ok(repo.read(f"data/rank_snapshots/{month}.json", parent) is None and repo.read("data/rank_history.json", parent) != repo.read("data/rank_history.json")
       and repo.read("index.html", parent) != repo.read("index.html"), "index.html, the history file and the snapshot file changed in the same commit")
    rk = {m[0]: m for m in ev["ranking"]}
    ok(set(rk) == {LAMB, STB} and rk[LAMB][1:3] == [7, 8] and rk[STB][1:3] == [8, 7], f"Ranking changes: CeeDee #7 → #8, St. Brown #8 → #7 ({ev['ranking']})")
    ok(ev["manual"] == [] and ev["src"] == "M" and ev["by"] == "tester" and ev["repriced"] is None and ev["snap"] == month, f"Event fields (no manual changes, first snapshot): { {k: ev[k] for k in ('src', 'by', 'repriced', 'snap')} }")
    board = snap_now()
    added = {s: l[-1] for s, l in h1["players"].items() if len(l) > len(before["players"].get(s, []))}
    ok(all(e[0] == ev["ts"] and e[5] == "M" and len(e) == 7 for e in added.values()), "Every entry of the publish has the publish time, source M and a kind")
    expect = {s for s, a in board.items() if changed((before["players"].get(s) or [None])[-1], a)}
    ok(set(added) == expect == {LAMB, STB}, f"Entries are exactly the two players who swapped ({len(added)} vs {len(expect)})")
    ok(ev["auto"] == [] and all(added[s][6] == "R" for s in rk), f"Kinds: 0 automatic, 2 ranking ({ev['auto']})")
    vchg = [s for s, a in board.items() if before_snap.get(s) and before_snap[s][3] != a[3]]
    ok(vchg == [LAMB], f"Only the moved player's value changed ({[names.get(s, s) for s in vchg]})")

    # 2. exact snapshot = the board
    snap = s1["snapshots"][-1]
    ok(len(s1["snapshots"]) == 1 and snap["ts"] == ev["ts"] and snap["players"] == board, f"Snapshot equals the page's board exactly ({len(board)} players)")
    import csv as _csv, io as _io
    m = re.search(rb"const RANKINGS_CSV = `\n([\s\S]*?)\n`;", repo.read("index.html"))
    pubv = {r["sleeper_id"]: (r["value"] or "").strip() for r in _csv.DictReader(_io.StringIO(m.group(1).decode())) if r["sleeper_id"]}
    ok(all(len(a) == 4 for a in snap["players"].values()) and snap.get("valueModelVersion") == "state-baseline-v1" and ev.get("v") == "state-baseline-v1",
       f"Snapshot rows have 4 fields (no typed flag) and carry valueModelVersion ({snap.get('valueModelVersion')})")
    ok(all(a[3] == int(pubv[s]) for s, a in snap["players"].items() if s in pubv), "Snapshot values are exactly the published value column")

    # 3. back up: second snapshot, exact repricing count
    arrow("CeeDee Lamb", -1); save()
    h2 = hist(); ev2 = h2["events"][-1]; s2 = snapfile(month)
    exact = sum(1 for s, a in s2["snapshots"][-1]["players"].items() if s in s2["snapshots"][0]["players"] and s2["snapshots"][0]["players"][s][3] != a[3])
    ok(len(s2["snapshots"]) == 2 and ev2["repriced"] == exact == 1 and ev2["auto"] == [], f"Second snapshot; exactly 1 value repriced (his), none automatic ({ev2['repriced']}, {ev2['auto']})")
    back = s2["snapshots"][-1]["players"]
    ok(all(back[s][:3] == before_snap[s][:3] for s in before_snap) and [s for s in before_snap if back[s][3] != before_snap[s][3]] in ([], [LAMB]),
       f"Moving him back restores every rank and tier, and every value but his (the published board is the new baseline: {before_snap[LAMB][3]} → {s1['snapshots'][0]['players'][LAMB][3]} → {back[LAMB][3]})")

    # 4. a value edit 3 points under Puka's value: a value edit though the value barely moves
    shown = before_snap[PUKA][3] - 3   # far below the 0.5% line, still an edit
    pg.locator("#rank-body tr.player", has_text="Puka Nacua").first.locator(".num-btn").click(); pg.wait_for_timeout(200)
    pg.fill(".val-input", str(shown)); pg.press(".val-input", "Enter"); pg.wait_for_timeout(500)
    save(); h3 = hist(); ev3 = h3["events"][-1]
    pe = h3["players"][PUKA][-1]
    ok(ev3["manual"] == [[PUKA, str(before_snap[PUKA][3]), str(shown)]] and pe[6] == "V" and pe[0] == ev3["ts"], f"Value edit = event ({ev3['manual']}, kind {pe[6]})")
    ok(snapfile(month)["snapshots"][-1]["players"][PUKA] == before_snap[PUKA][:3] + [shown], "Snapshot holds his new value, nothing else about him changed")

    # 5. nothing new: no history commit
    n = len(publish_commits())
    pg.evaluate("() => { localStorage.setItem('spm_local_edits', '{}'); }")
    ok(len(publish_commits()) == n, "No new history commit without a publish")

    # 6. valueAt: exact snapshot, fallback before the first snapshot
    t1 = pg.evaluate("ts => Date.parse(ts)", ev["ts"]); t2 = pg.evaluate("ts => Date.parse(ts)", ev2["ts"])
    va = pg.evaluate("([s, ms]) => SPM.valueAt(s, ms)", [LAMB, (t1 + t2) // 2])
    ok(va and va.get("exact") and va["v"] == s1["snapshots"][0]["players"][LAMB][3] and va["rank"] == 8, f"Value at a time between the publishes = first snapshot (CeeDee #8, {va and va['v']})")
    vb = pg.evaluate("([s, ms]) => SPM.valueAt(s, ms)", [LAMB, t1 - 60000])
    last_before = [e for e in before["players"][LAMB]][-1]
    ok(vb and not vb.get("exact") and vb["v"] == last_before[4], "Before the first snapshot: the latest history entry, as before")

    # 7. the player page
    def history_tab(name):
        pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
        pg.locator("#rank-body tr.player .pl-name", has_text=name).first.click(); pg.wait_for_timeout(700)
        pg.click("[data-pp-tab=history]"); pg.wait_for_timeout(500)
        return pg.locator("dialog.pm[open] .gl-table").first
    t = history_tab("CeeDee Lamb")
    ok("Rank changed: #7 → #8" in t.inner_text() and "Rank changed: #8 → #7" in t.inner_text(), "CeeDee's rows read 'Rank changed: #7 → #8' / '#8 → #7'")
    t = history_tab("Puka Nacua")
    ok(f"Value edited: {before_snap[PUKA][3]:,} → {shown:,}" in t.inner_text(), f"Puka's edit reads 'Value edited: {before_snap[PUKA][3]:,} → {shown:,}'")
    # older events with automatic repricing (before Oct 12) still show muted, collapsed, with their publish
    hh = hist(); X = next(s for s in hh["players"] if s not in (LAMB, STB, PUKA) and names.get(s) and hh["players"][s][-1][6] == "R" and s in board)
    last = hh["players"][X][-1]; v0 = last[4]
    for i, (frm, to) in enumerate(((7, 8), (8, 7))):
        ts = f"2026-12-0{3 + i}T12:00:00.000Z"   # after every real entry, so the two form their own run
        hh["events"].append({"ts": ts, "by": "old", "src": "M", "ranking": [[LAMB, frm, to, 1, 1]], "manual": [], "auto": [X], "repriced": 30, "snap": None})
        hh["players"][X].append([ts, last[1], last[2], last[3], round(v0 * (1.02 + 0.02 * i)), "M", "A"])
    hh["events"].sort(key=lambda e: e["ts"])
    for k in hh["players"]: hh["players"][k].sort(key=lambda e: e[0])
    repo.commit_file("data/rank_history.json", json.dumps(hh).encode(), "test: older repricing events")
    pg.reload(); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1200)
    t = history_tab(names[X]); txt = t.inner_text()
    ok("Model repriced 2 times" in txt, f"{names[X]}: two repricings in a row collapse into one row")
    hidden = pg.locator("dialog.pm[open] tr.gl-in").first
    ok(not hidden.is_visible(), "The collapsed rows start hidden")
    pg.locator("dialog.pm[open] .gl-toggle").first.click(); pg.wait_for_timeout(200)
    txt = t.inner_text()
    ok(hidden.is_visible() and re.search(r"Same publish as [^\n]*CeeDee Lamb #7 → #8", txt) and re.search(r"Same publish as [^\n]*CeeDee Lamb #8 → #7", txt),
       "Show opens them, each saying which publish it came with ('Same publish as … CeeDee Lamb #7 → #8')")
    if failures and "Show opens" in failures[-1]: print("   ", [l for l in txt.splitlines() if "Model" in l or "publish" in l])

    # 9. failures and retries
    import collections, datetime
    hook = {"mode": None}
    def faulty(route):
        req = route.request
        if hook["mode"] == "readback" and req.method == "POST" and req.url.endswith("/git/commits") and json.loads(req.post_data)["message"].startswith("Rankings edit"):
            hook["mode"] = None; repo.faults["readback"] = True
        if hook["mode"] in ("concurrent", "lost") and req.method == "PATCH" and "/git/refs/heads/" in req.url:
            sha = json.loads(req.post_data)["sha"]; m = hook["mode"]; hook["mode"] = None
            if m == "concurrent":   # the weekly job lands an event + snapshot first
                hh = hist(); f = snapfile(month); ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                f["snapshots"].append({"ts": ts, "src": "S", "by": "scheduled", "players": f["snapshots"][-1]["players"]})
                hh["events"].append({"ts": ts, "by": "scheduled", "src": "S", "ranking": [], "manual": [], "auto": [], "repriced": 0, "snap": month})
                repo.commit_file(f"data/rank_snapshots/{month}.json", json.dumps(f).encode(), "Weekly projections and stats refresh")
                repo.commit_file("data/rank_history.json", json.dumps(hh).encode(), "Weekly projections and stats refresh")
            else:                   # GitHub moves the branch, but the answer never arrives
                if repo.head in repo.commits[sha]["parents"]: repo.head = sha
                return route.fulfill(status=502, content_type="application/json", body='{"message":"Bad Gateway"}')
        return repo.handle(route)
    pg.unroute("https://api.github.com/**"); pg.route("https://api.github.com/**", faulty)
    def dupes():
        hh = hist(); ev = collections.Counter(e["ts"] for e in hh["events"]); sn = collections.Counter(x["ts"] for x in snapfile(month)["snapshots"])
        return [k for k, v in ev.items() if v > 1], [k for k, v in sn.items() if v > 1], sum(1 for l in hh["players"].values() for a, b in zip(l, l[1:]) if a[0] == b[0])
    pg.evaluate("() => document.querySelectorAll('dialog[open]').forEach(d => d.close())"); pg.wait_for_timeout(300)
    pg.click("#pos-chips button:has-text('All')"); pg.wait_for_timeout(300)
    e0, s0 = len(hist()["events"]), len(snapfile(month)["snapshots"])
    hook["mode"] = "concurrent"; arrow("CeeDee Lamb", 1); t = save()
    hh = hist()
    ok("Published and confirmed" in t and len(hh["events"]) == e0 + 2 and [e["src"] for e in hh["events"][-2:]] == ["S", "M"] and len(snapfile(month)["snapshots"]) == s0 + 2,
       f"A concurrent writer's snapshot is kept and ours lands once, after a re-read ({t[-60:]!r})")
    e1 = len(hist()["events"]); hook["mode"] = "lost"; arrow("CeeDee Lamb", -1); t = save()
    ok("Published and confirmed" in t and "wasn't" not in t and len(hist()["events"]) == e1 + 1, f"Lost answer: checked on GitHub, reported as published, one event ({t[-60:]!r})")
    e2 = len(hist()["events"]); h0 = repo.read("index.html"); hook["mode"] = "readback"; arrow("CeeDee Lamb", 1); t = save()
    ok("Publish failed" in t and "didn't match" in t and len(hist()["events"]) == e2 and not local_edits_empty(), f"Read-back mismatch: reported, no event, edits kept ({t[:70]!r})")
    pg.evaluate("() => { const t = document.getElementById('toast'); t.textContent = ''; }"); pg.click("#eb-publish")
    pg.wait_for_function("() => /Publish|Already live/.test(document.getElementById('toast').textContent)", timeout=30000); pg.wait_for_timeout(400)
    arrow("CeeDee Lamb", -1); save()
    ok(dupes() == ([], [], 0), f"After every failure and retry: no duplicate events, snapshots or entries {dupes()}")

    # 8. legacy entries untouched
    ok(all(h3["players"][s][:len(l)] == l for s, l in json.loads(HIST)["players"].items()), "Every earlier entry is kept exactly")
    ok(not errs, f"No page errors {errs[:2]}")
    br.close()

for f, sha in DISK.items():
    ok(hashlib.sha256(open(os.path.join(ROOT, f), "rb").read()).hexdigest() == sha, f"{f} on disk unchanged")
print("\n" + ("ALL PASS" if not failures else f"{len(failures)} FAILED"))
sys.exit(1 if failures else 0)
