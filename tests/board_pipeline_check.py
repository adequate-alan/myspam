"""Scheduled jobs for every ranking set (Alan, Oct 14; PR 4 of the boards work): Sleeper team sync and the scheduled
ranking-history snapshot cover AM PPR (RANKINGS_CSV_PPR, data/boards/ppr/) as well as AM SF PPR TE+.

Everything runs on scratch copies of this checkout; nothing here touches index.html or data/ in the repo.

Run from the repo root:  python3 tests/board_pipeline_check.py

Checks:
1. pipeline/sync_teams.py: a player who changed teams is updated in both blocks (team column only, every other byte of
   index.html unchanged); a player Sleeper doesn't know keeps his team; a page without the AM PPR block still syncs
   the main block; more than MAX_MOVES changes in one block skips that block only (left byte-identical, a warning names
   it) while the other block still syncs; over the limit in both writes nothing.
2. tests/static_check.py --frozen-rankings: a team change in RANKINGS_CSV_PPR passes, a rank or value change there fails.
3. pipeline/snapshot_history.py: with nothing changed, neither board writes anything; a changed AM PPR value records one
   scheduled event and one snapshot in data/boards/ppr/ only (the snapshot is the AM PPR board, the SF files are
   byte-identical); --board sf-tep never touches the AM PPR files.
"""
import csv, hashlib, io, json, os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import sync_teams

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

def blk(html, name): return re.search(r"const " + name + r" = `\n([\s\S]*?)\n`;", html)[1]
def table(text):
    rows = list(csv.reader(io.StringIO(text))); h = rows[0]
    return h, {r[h.index("sleeper_id")]: r for r in rows[1:]}
def strip_team(text):
    h, rows = table(text); ti = h.index("team")
    return [r[:ti] + r[ti + 1:] for r in rows.values()]
def tree_hash(d):
    out = {}
    for base, _, files in os.walk(d):
        for f in files:
            p = os.path.join(base, f); out[os.path.relpath(p, d)] = hashlib.sha1(open(p, "rb").read()).hexdigest()
    return out

HTML = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
sh, sf = table(blk(HTML, "RANKINGS_CSV")); ph, pp = table(blk(HTML, "RANKINGS_CSV_PPR"))
both = [s for s in sf if s in pp]
sid = both[10]; old_team = sf[sid][sh.index("team")]
new_team = "LV" if old_team != "LV" else "NYG"

# 1. sync_teams
players = {s: {"team": sf[s][sh.index("team")] or None} for s in both}
players[sid] = {"team": new_team}
players.pop(both[20])   # Sleeper doesn't know him: keeps his team
new, moves = sync_teams.sync_all(HTML, players)
ok(set(moves) == {"RANKINGS_CSV", "RANKINGS_CSV_PPR"} and all(len(m) == 1 and m[0][2] == new_team for m in moves.values()),
   f"One player moved {old_team} -> {new_team} in both blocks: {moves}")
nsh, nsf = table(blk(new, "RANKINGS_CSV")); nph, npp = table(blk(new, "RANKINGS_CSV_PPR"))
ok(nsf[sid][nsh.index("team")] == new_team and npp[sid][nph.index("team")] == new_team, "His team column reads the new team in both blocks")
ok(strip_team(blk(new, "RANKINGS_CSV")) == strip_team(blk(HTML, "RANKINGS_CSV")) and strip_team(blk(new, "RANKINGS_CSV_PPR")) == strip_team(blk(HTML, "RANKINGS_CSV_PPR")),
   "Every column but team is unchanged in both blocks")
outside = lambda h: re.sub(r"(const RANKINGS_CSV(_PPR)? = `\n)[\s\S]*?(\n`;)", r"\1\3", h)
ok(outside(new) == outside(HTML), "Nothing outside the two blocks changed")
ok(npp[both[20]][nph.index("team")] == pp[both[20]][ph.index("team")], "A player Sleeper doesn't know keeps his team")
no_ppr = re.sub(r"const RANKINGS_CSV_PPR = `\n[\s\S]*?\n`;", "", HTML)
n2, m2 = sync_teams.sync_all(no_ppr, players)
ok(list(m2) == ["RANKINGS_CSV"] and len(m2["RANKINGS_CSV"]) == 1, "A page without the AM PPR block still syncs the main block")
def stale(html, name, n):
    """A copy of the page whose `name` block has a wrong team for n players (Sleeper's answer will move all of them)."""
    m = re.search(r"(const " + name + r" = `\n)([\s\S]*?)(\n`;)", html); lines = m[2].split("\n")
    hd = next(csv.reader([lines[0]])); ti, si = hd.index("team"), hd.index("sleeper_id"); done = 0
    for k in range(1, len(lines)):
        r = next(csv.reader([lines[k]]))
        if done < n and r[si] in players and r[si] not in (sid, both[20]):
            r[ti] = "ZZ"; o = io.StringIO(); csv.writer(o, lineterminator="").writerow(r); lines[k] = o.getvalue(); done += 1
    return html[:m.start(2)] + "\n".join(lines) + html[m.end(2):]
tmp = tempfile.mkdtemp(); path = os.path.join(tmp, "index.html")
def run_apply(page):
    open(path, "w", encoding="utf-8").write(page); buf = io.StringIO(); so = sys.stdout; sys.stdout = buf
    try: res = sync_teams.apply(path, players)
    finally: sys.stdout = so
    return res, buf.getvalue(), open(path, encoding="utf-8").read()
for big, small in (("RANKINGS_CSV_PPR", "RANKINGS_CSV"), ("RANKINGS_CSV", "RANKINGS_CSV_PPR")):
    page = stale(HTML, big, sync_teams.MAX_MOVES + 1)
    res, log, out = run_apply(page)
    ok(blk(out, big) == blk(page, big) and big not in res, f"Over the limit in {big}: that block is left byte-identical")
    th, tr = table(blk(out, small))
    ok(len(res.get(small, [])) == 1 and tr[sid][th.index("team")] == new_team, f"... and {small} still syncs ({res.get(small)})")
    ok(f"::warning title=Team sync skipped for {big}::" in log, f"... and the run log warns that {big} was skipped")
page = stale(stale(HTML, "RANKINGS_CSV", sync_teams.MAX_MOVES + 1), "RANKINGS_CSV_PPR", sync_teams.MAX_MOVES + 1)
res, log, out = run_apply(page)
ok(out == page and not res and log.count("::warning") == 2, "Over the limit in both blocks: nothing written, both skips reported")

# a scratch git copy of this checkout for the static check and the snapshot job
work = tempfile.mkdtemp()
subprocess.run(f"git ls-files -z | xargs -0 -I{{}} cp --parents {{}} {work}", shell=True, cwd=ROOT, check=True)
for f in ("pipeline/sync_teams.py", "pipeline/snapshot_history.py", "tests/static_check.py"):   # this working tree's versions
    shutil.copy(os.path.join(ROOT, f), os.path.join(work, f))
g = lambda *a: subprocess.run(["git", *a], cwd=work, capture_output=True, text=True)
g("init", "-q"); g("add", "-A"); g("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")

# 2. static_check --frozen-rankings
def frozen():
    r = subprocess.run([sys.executable, "tests/static_check.py", "--base", "HEAD", "--frozen-rankings"], cwd=work, capture_output=True, text=True)
    return [l for l in r.stdout.splitlines() if l.startswith("FAIL")]
idx = os.path.join(work, "index.html")
sync_teams.apply(idx, {sid: {"team": new_team}})
f = frozen()
ok(not f, f"A team change in both blocks passes --frozen-rankings {f[:3]}")
def edit_ppr(fn):
    h = open(idx, encoding="utf-8").read(); m = re.search(r"(const RANKINGS_CSV_PPR = `\n)([\s\S]*?)(\n`;)", h)
    lines = m[2].split("\n"); hd = next(csv.reader([lines[0]])); fn(hd, lines)
    open(idx, "w", encoding="utf-8").write(h[:m.start(2)] + "\n".join(lines) + h[m.end(2):])
def set_cell(sidv, col, val):
    def f(hd, lines):
        for k in range(1, len(lines)):
            r = next(csv.reader([lines[k]]))
            if r[hd.index("sleeper_id")] == sidv:
                r[hd.index(col)] = val; o = io.StringIO(); csv.writer(o, lineterminator="").writerow(r); lines[k] = o.getvalue()
    return f
g("checkout", "-q", "index.html")
pv = sorted(pp.values(), key=lambda r: int(r[ph.index("rank")]))
pick = next(r for a, r, b in zip(pv, pv[1:], pv[2:]) if int(a[ph.index("value")]) - int(r[ph.index("value")]) > 3 and int(r[ph.index("value")]) - int(b[ph.index("value")]) > 3 and int(r[ph.index("rank")]) > 150)
psid, pval = pick[ph.index("sleeper_id")], int(pick[ph.index("value")])
edit_ppr(set_cell(psid, "value", str(pval + 1)))
f = frozen()
ok(any("RANKINGS_CSV_PPR" in l and "value" in l for l in f), f"A value change in RANKINGS_CSV_PPR fails --frozen-rankings {f[:2]}")
g("checkout", "-q", "index.html")
edit_ppr(set_cell(psid, "rank", "1"))
ok(any("RANKINGS_CSV_PPR" in l for l in frozen()), "A rank change in RANKINGS_CSV_PPR fails --frozen-rankings")
g("checkout", "-q", "index.html")

# 3. snapshot_history.py
def snap(*args):
    r = subprocess.run([sys.executable, "snapshot_history.py", "--root", work, "--ts", "2026-10-20T14:30:00.000Z", *args], cwd=os.path.join(work, "pipeline"),
                       capture_output=True, text=True, timeout=400)
    return r.returncode, (r.stdout + r.stderr).strip()
data = os.path.join(work, "data"); before = tree_hash(data)
rc, out = snap()
ok(rc == 0 and tree_hash(data) == before, f"Nothing changed: neither board writes anything ({out[-160:]!r})")
sf_files = {k: v for k, v in before.items() if not k.startswith("boards")}
edit_ppr(set_cell(psid, "value", str(pval + 1)))
rc, out = snap("--board", "sf-tep")
ok(rc == 0 and tree_hash(data) == before, f"--board sf-tep never touches the AM PPR files ({out[-120:]!r})")
rc, out = snap()
after = tree_hash(data)
ok(rc == 0 and {k: v for k, v in after.items() if not k.startswith("boards")} == sf_files, "The AM SF PPR TE+ history and snapshots are byte-identical")
hist = json.load(open(os.path.join(data, "boards/ppr/rank_history.json")))
ev = hist["events"][-1]
ok(ev["ts"] == "2026-10-20T14:30:00.000Z" and ev["src"] == "S" and ev.get("snap") == "2026-10", f"One scheduled event in the AM PPR history: {ev.get('ts')} {ev.get('src')} {ev.get('snap')}")
ok(ev.get("repriced") == 1, f"The event counts exactly one changed value (a 1-point change is under the visible-entry threshold): {ev.get('repriced')}")
s = json.load(open(os.path.join(data, "boards/ppr/rank_snapshots/2026-10.json")))["snapshots"][-1]
_, npp2 = table(blk(open(idx, encoding="utf-8").read(), "RANKINGS_CSV_PPR"))
exp = {k: [int(r[ph.index("rank")]), int(r[ph.index("pos_rank")]), int(r[ph.index("tier")]), int(r[ph.index("value")])] for k, r in npp2.items()}
ok(s["ts"] == ev["ts"] and s["players"] == exp, f"The new snapshot is the AM PPR board exactly ({len(s['players'])} players)")
ok(len([k for k in after if after[k] != before.get(k)]) == 2, f"Only the AM PPR history and this month's AM PPR snapshot changed {[k for k in after if after[k] != before.get(k)]}")
rc, out = snap()
ok(rc == 0 and tree_hash(data) == after, "Running again with nothing new records nothing")
shutil.rmtree(work, ignore_errors=True); shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
