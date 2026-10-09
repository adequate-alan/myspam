"""The frozen test board and the data gate (Alan, Oct 14): tests of how Adequate works run on a fixture board, tests of
data validity run on the live rankings, and the two can't be confused.

Run from the repo root:  python3 tests/fixture_check.py   (CHROMIUM=/path/to/chromium if needed; needs git)

1. The fixture (tests/fixtures/board, tests/fixture_board.py) is sound: its rankings pass the same publish rules
   static_check applies to the live block, its history and snapshot files are well formed, every fixture player has an
   entry in data/sleeper_players.json, the page it builds is the current index.html with only the rankings block
   replaced, and nothing in index.html or the data files points at the fixture.
2. Legitimate ranking changes don't touch fixture-based tests: in a copy of the repo the live block gets a real edit
   (two neighbours at a position swap places and values, a value edited by a point, a tier renamed); static_check still
   passes there, the page the fixture builds is byte for byte the same as in the real repo, and value_state_check
   (a fixture-based suite) passes in the copy with the same checks it passes here.
3. Corrupted ranking data still fails CI: in the copy, a duplicate rank, a gap in the ranks, an invalid stored value, a
   player listed twice, a duplicated Sleeper ID and position ranks out of order each fail static_check (the fast tier);
   values out of order, a split tier and a missing value each fail the page's own pre-publish checks that smoke_check
   runs (also in the fast tier). The fixture board is not involved in any of these.
4. tests/ci_policy.json: the value_curve_check checks listed as advisory are exactly the two board-quality preferences
   (tier-gap size, adjacent drop size); its correctness checks aren't listed anywhere; no suite has a known failure.
"""
import csv, io, json, os, re, shutil, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fixture_board as FB
import static_check as SC

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond: failures.append(msg)

# 1. the fixture is sound
errs = SC.validate(FB.CSV)
ok(not errs, f"The fixture rankings pass the publish rules ({len(FB.rows())} players) {errs[:3]}")
hist = json.loads(FB.files()["data/rank_history.json"])
ok(not SC.history_errors(hist) and hist.get("events"), "The fixture history is well formed and has publish events")
snap = json.loads(FB.files()["data/rank_snapshots/2026-10.json"])
ok(not SC.snapshot_errors("data/rank_snapshots/2026-10.json", snap), "The fixture snapshot file is well formed")
players = json.load(open(os.path.join(ROOT, "data/sleeper_players.json")))
missing = [r["player"] for r in FB.rows() if r["sleeper_id"] not in players]
ok(not missing, f"Every fixture player has a Sleeper entry in data/sleeper_players.json {missing[:3]}")
live = open(os.path.join(ROOT, "index.html"), "rb").read()
page = FB.html()
lm, fm = FB.CSV_RE.search(live), FB.CSV_RE.search(page)
ok(live[:lm.start(2)] == page[:fm.start(2)] and live[lm.end(2):] == page[fm.end(2):] and page[fm.start(2):fm.end(2)] == FB.CSV.encode(),
   "The fixture page is the current index.html with only the rankings block replaced")
mentions = [f for f in ["index.html"] + [os.path.join(dp, f) for dp, _, fs in os.walk(os.path.join(ROOT, "data")) for f in fs] if b"tests/fixtures" in open(os.path.join(ROOT, f), "rb").read()]
ok(not mentions, f"Nothing in index.html or data/ points at the fixture {mentions[:3]}")

# 4. the policy
POL = json.load(open(os.path.join(ROOT, "tests/ci_policy.json")))
ok(POL["advisory"].get("value_curve_check") == ["Every tier boundary has a real value gap", "No formula cliff over 30%"],
   f"Only the two board-quality preferences of value_curve_check are advisory {POL['advisory'].get('value_curve_check')}")
hidden = [n for lst in POL["advisory"].values() if isinstance(lst, list) for n in lst
          if n.startswith(("Values never rise", "Tiers stay in one piece", "No tier is worth more", "Stored values show exactly", "No page errors"))]
ok(not hidden and not POL["known_failures"], f"No correctness check is advisory or a known failure {hidden} {POL['known_failures']}")
ok("fixture_check" in POL["suites"]["full"], "This suite runs in the full tier")

# a copy of the repo with the working tree's index.html and tests (like ci_pipeline_check)
tmp = tempfile.mkdtemp(prefix="fixture-check-")
try:
    d = os.path.join(tmp, "copy")
    subprocess.run(["git", "clone", "-q", "--no-hardlinks", ROOT, d], check=True)
    shutil.rmtree(os.path.join(d, "tests")); shutil.copytree(os.path.join(ROOT, "tests"), os.path.join(d, "tests"), ignore=shutil.ignore_patterns("__pycache__", ".ci-logs"))
    shutil.copy(os.path.join(ROOT, "index.html"), os.path.join(d, "index.html"))
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A"], cwd=d, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base", "--allow-empty"], cwd=d, check=True)
    html = open(os.path.join(d, "index.html"), encoding="utf-8").read()
    m = re.search(r"const RANKINGS_CSV = `\n([\s\S]*?)\n`;", html)
    rows = list(csv.reader(io.StringIO(m.group(1)))); head = rows[0]; c = head.index
    def write(rows2):
        cell = lambda v: '"' + v.replace('"', '""') + '"' if re.search(r'[",\n]', v) else v
        open(os.path.join(d, "index.html"), "w", encoding="utf-8").write(html[:m.start(1)] + "\n".join(",".join(cell(x) for x in r) for r in rows2) + html[m.end(1):])
    def run(*cmd, timeout=600):
        r = subprocess.run([sys.executable, *cmd], cwd=d, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout + r.stderr
    def fresh(): return [r[:] for r in rows]

    # 2. a legitimate edit of the live rankings
    body = sorted(rows[1:], key=lambda r: int(r[c("rank")]))
    pair = next((a, b) for a, b in zip(body, body[1:]) if a[c("pos")] == b[c("pos")] and a[c("tier")] == b[c("tier")]
                and a[c("source")] == b[c("source")] == "manual" and int(a[c("rank")]) < 100 and a[c("value")] and b[c("value")])
    ident = [i for i, h in enumerate(head) if h in ("player", "pos", "team", "proj_ppg", "games", "proj_score", "sleeper_id")]
    edited = fresh(); E = {r[c("sleeper_id")]: r for r in edited[1:]}
    A, B = E[pair[0][c("sleeper_id")]], E[pair[1][c("sleeper_id")]]
    for i in ident: A[i], B[i] = B[i], A[i]                     # the two swap places: ranks, position ranks, tier and values stay with the slots
    below = next(r for r in body if int(r[c("rank")]) == int(pair[1][c("rank")]) + 1)
    if int(B[c("value")]) - 1 > int(below[c("value")]): B[c("value")] = str(int(B[c("value")]) - 1)   # a value edited by a point, still in order
    tn = head.index("tier_name") if "tier_name" in head else None
    if tn is not None:
        grp = [r for r in edited[1:] if r[c("pos")] == A[c("pos")] and r[c("tier")] == A[c("tier")]]
        for r in grp: r[tn] = (r[tn] or "Tier") + " (renamed)"
    write(edited)
    rc, out = run("tests/static_check.py", "--base", "HEAD")
    ok(rc == 0, f"A legitimate edit of the live rankings ({pair[0][c('player')]} ↔ {pair[1][c('player')]}, a value −1, a tier renamed) still passes static_check")
    r2 = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'tests'); import fixture_board as FB; sys.stdout.buffer.write(FB.html())"], cwd=d, capture_output=True)
    ok(r2.returncode == 0 and r2.stdout == page, f"The fixture page built in the edited copy is byte for byte the page built here ({len(r2.stdout)} bytes)")
    here = subprocess.run([sys.executable, "tests/value_state_check.py"], cwd=ROOT, capture_output=True, text=True, timeout=600)
    rc, out = run("tests/value_state_check.py")
    lines = lambda o: sorted(l for l in o.splitlines() if l.startswith(("PASS", "FAIL")) and "live rankings" not in l)
    ok(here.returncode == 0 and rc == 0 and lines(out) == lines(here.stdout) and any("8,295 (approved preview)" in l for l in lines(out)),
       f"value_state_check (fixture-based) passes in the edited copy with the same {len(lines(out))} checks as here")
    if rc != 0: print("   ", [l for l in out.splitlines() if l.startswith("FAIL")][:5])

    # 3. corrupted rankings still fail the gate
    def corrupt(label, fn, needle):
        t = fresh(); fn(t); write(t)
        rc, out = run("tests/static_check.py")
        ok(rc == 1 and needle in out, f"static_check fails {label} ({needle!r})")
    corrupt("a duplicate rank", lambda t: t[3].__setitem__(c("rank"), t[2][c("rank")]), "ranks don't run")
    corrupt("a gap in the ranks", lambda t: t[-1].__setitem__(c("rank"), str(len(t) + 5)), "ranks don't run")
    corrupt("an invalid stored value", lambda t: t[4].__setitem__(c("value"), "abc"), "invalid value")
    def dup_player(t): t[6][c("player")] = t[5][c("player")]; t[6][c("pos")] = t[5][c("pos")]
    corrupt("a player listed twice", dup_player, "appears twice")
    corrupt("a duplicated Sleeper ID", lambda t: t[7].__setitem__(c("sleeper_id"), t[6][c("sleeper_id")]), "appears twice")
    def pos_out(t):
        a, b = [r for r in t[1:] if r[c("pos")] == "WR"][:2]; a[c("pos_rank")], b[c("pos_rank")] = b[c("pos_rank")], a[c("pos_rank")]
    corrupt("position ranks out of order", pos_out, "position ranks don't follow")
    # the page's own pre-publish checks (smoke_check runs them in the fast tier)
    def smoke(label, fn, needle):
        t = fresh(); fn(t); write(t)
        rc, out = run("tests/smoke_check.py")
        fails = [l for l in out.splitlines() if l.startswith("FAIL")]
        ok(rc != 0 and any("pre-publish" in l and needle in l for l in fails), f"smoke_check fails {label} through the page's pre-publish checks {fails[:1]}")
    srt = lambda t: sorted(t[1:], key=lambda r: int(r[c("rank")]))
    def value_up(t):
        b = srt(t); b[1][c("value")] = str(int(b[0][c("value")]) + 1)
    smoke("values out of order", value_up, "worth")
    def split_tier(t):
        wr = [r for r in srt(t) if r[c("pos")] == "WR"]; wr[1][c("tier")] = str(int(wr[1][c("tier")]) + 1)
    smoke("a split tier", split_tier, "split")
    smoke("a missing value", lambda t: t[5].__setitem__(c("value"), ""), "no value")
    write(rows)   # back to the real block
    rc, out = run("tests/static_check.py", "--base", "HEAD", "--frozen-rankings")
    ok(rc == 0, "The untouched copy passes static_check again")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n" + ("All fixture checks passed." if not failures else f"{len(failures)} check(s) failed."))
sys.exit(1 if failures else 0)
