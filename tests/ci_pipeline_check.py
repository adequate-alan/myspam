"""The release pipeline itself (Phase 1 reliability), without GitHub: GitHub Actions can't run locally, so this checks
the workflow's job graph and gate conditions, and runs the CI tools against deliberately broken inputs.

Run from the repo root:  python3 tests/ci_pipeline_check.py      (needs PyYAML; no browser)

1. Workflow structure: deploy only after build; build only after verify and the full suite (or a verified fingerprint),
   never for pull requests; the scheduled refresh checks its data before committing; per-job permissions (only refresh
   writes contents, only deploy has pages/id-token); test jobs don't keep the GitHub token in the checkout.
2. Gate conditions, evaluated for each scenario (verify passed/failed, full suite passed/failed/skipped, refresh
   failed, pull request): deployment happens exactly when everything required succeeded.
3. run_ci.py: a new failure blocks; the known baseline failure and advisory timing checks don't; a crash blocks;
   a known failure that starts passing is reported.
4. static_check.py on a copy of the repo: broken rankings, a rewritten history entry, and a changed rank under
   --frozen-rankings each fail; the untouched copy passes; both board-snapshot formats pass (4-field with a value
   model, 5-field legacy) and malformed snapshots (wrong field count, bad typed flag, duplicate rank or timestamp) fail.
5. The fast path's code fingerprint: a rankings edit and data/*.json changes keep it; code in index.html (JS, CSS),
   tests, pinned test dependencies, the CI policy, the workflow, pipeline scripts, the manifest and a non-JSON file
   under data/ each change it (so they always get the full suite).
6. Pull requests can't deploy, publish or write: no job that runs for a pull request can push, deploy, save the
   verified-code record or use a secret.
"""
import json, os, re, shutil, subprocess, sys, tempfile
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

wf = yaml.safe_load(open(os.path.join(ROOT, ".github/workflows/site.yml")))
on, jobs = wf[True], wf["jobs"]

# 1. structure
need = lambda j: [jobs[j]["needs"]] if isinstance(jobs[j].get("needs"), str) else jobs[j].get("needs", [])
ok("push" in on and "pull_request" in on, "Runs on pushes to main and on pull requests")
ok(need("deploy") == ["build"] and set(need("build")) == {"verify", "full"} and need("full") == ["verify"] and need("verify") == ["refresh"],
   f"Job graph refresh → verify → full → build → deploy ({ {j: need(j) for j in jobs} })")
steps = [s.get("name", s.get("uses", "")) for s in jobs["refresh"]["steps"]]
ok(steps.index("Check the refreshed data before committing") < steps.index("Commit refreshed site"), "The scheduled refresh checks its data before it commits")
chk = next(s for s in jobs["refresh"]["steps"] if s.get("name") == "Check the refreshed data before committing")["run"]
ok("--frozen-rankings" in chk, "…and fails if any ranking field changed")
ok(wf["permissions"] == {"contents": "read"}, "Default permissions are read-only")
ok(jobs["refresh"]["permissions"] == {"contents": "write"} and jobs["deploy"]["permissions"] == {"pages": "write", "id-token": "write"}
   and all("permissions" not in jobs[j] for j in ("verify", "full", "build", "mark-verified")), "Only refresh can push and only deploy can publish Pages")
for j in ("verify", "full", "build"):
    co = next(s for s in jobs[j]["steps"] if str(s.get("uses", "")).startswith("actions/checkout"))
    ok(co.get("with", {}).get("persist-credentials") is False, f"{j}: the checkout doesn't keep the GitHub token")
ok(any("upload-artifact" in str(s.get("uses")) and s.get("if") == "always()" for s in jobs["full"]["steps"]), "Full-suite logs are uploaded whether it passes or fails")
pins = open(os.path.join(ROOT, "tests/requirements-ci.txt")).read()
ok(re.search(r"^playwright==\d+\.\d+\.\d+$", pins, re.M) is not None, "Playwright is pinned to an exact version")

# every third-party module a test imports (directly, or through the pipeline modules it loads) is pinned for CI
# (PR #1: injury_check imports pandas through pipeline/build_stats.py; CI crashed with ModuleNotFoundError)
import sys as _sys
PKG = {"yaml": "pyyaml", "playwright": "playwright", "pandas": "pandas", "numpy": "numpy"}
pinned = {l.split("==")[0].strip().lower() for l in pins.splitlines() if "==" in l}
def third_party(path, seen=None):
    seen = set() if seen is None else seen
    if path in seen or not os.path.exists(path): return set()
    seen.add(path); src = open(path, encoding="utf-8").read(); out = set()
    for m in re.finditer(r"^\s*(?:import|from)\s+([A-Za-z_][\w]*)", src, re.M):
        mod = m[1]
        if mod in _sys.stdlib_module_names or mod == "__future__": continue
        local = [os.path.join(ROOT, d, mod + ".py") for d in ("tests", "pipeline")]
        hit = [x for x in local if os.path.exists(x)]
        if hit: out |= third_party(hit[0], seen)
        else: out.add(mod)
    return out
need_mods = set()
for t in sorted(os.listdir(os.path.join(ROOT, "tests"))):
    if t.endswith(".py"): need_mods |= third_party(os.path.join(ROOT, "tests", t))
unpinned = sorted(m for m in need_mods if PKG.get(m, m).lower() not in pinned)
ok(not unpinned, f"Every third-party module the tests import is pinned in tests/requirements-ci.txt ({sorted(need_mods)}) {unpinned}")

# 2. gate conditions: a tiny evaluator for the expressions these jobs use
def evaluate(expr, ctx):
    e = expr.replace("${{", "").replace("}}", "").strip()
    e = re.sub(r"always\(\)", "True", e)
    e = re.sub(r"needs\.([\w-]+)\.result", lambda m: repr(ctx["result"].get(m[1], "skipped")), e)
    e = re.sub(r"needs\.([\w-]+)\.outputs\.(\w+)", lambda m: repr(ctx["outputs"].get(m[1], {}).get(m[2], "")), e)
    e = re.sub(r"github\.event_name", repr(ctx["event"]), e)
    e = e.replace("&&", " and ").replace("||", " or ").replace("!=", " != ")
    return bool(eval(e, {}))

def ancestors(j, seen=None):
    seen = set() if seen is None else seen
    for d in need(j):
        if d not in seen: seen.add(d); ancestors(d, seen)
    return seen

def run(event, refresh="skipped", verify="success", full_needed=True, full="success", build="success"):
    """Walk the graph like Actions: a job runs when its `if` is true (jobs without one need every dependency to succeed)."""
    res, out = {}, {}
    def go(j, actual):
        cond = jobs[j].get("if")
        ctx = {"result": res, "outputs": out, "event": event}
        # GitHub's rule: a job whose `if` has no status function gets an implicit success(), which needs EVERY job
        # upstream of it (direct or not) to have succeeded; a skipped ancestor skips it (PR #1's first run: refresh
        # skipped on a pull request → full skipped although verify asked for it)
        ok_up = all(res.get(a) == "success" for a in ancestors(j))
        runs = (evaluate(cond, ctx) if cond else True) and (ok_up or (cond is not None and re.search(r"always\(\)|failure\(\)|cancelled\(\)", cond) is not None))
        res[j] = actual if runs else "skipped"
    go("refresh", refresh) if event in ("schedule", "workflow_dispatch") else res.__setitem__("refresh", "skipped")
    go("verify", verify)
    out["verify"] = {"full": "true" if full_needed else "false"} if res["verify"] == "success" else {}
    go("full", full); go("build", build); go("deploy", "success")
    return res["deploy"] == "success", res

cases = [
    ("code push, all checks pass", dict(event="push"), True),
    ("code push, a required test fails", dict(event="push", full="failure"), False),
    ("code push, static/smoke checks fail", dict(event="push", verify="failure"), False),
    ("rankings publish on verified code (fast path)", dict(event="push", full_needed=False), True),
    ("rankings publish, fast checks fail", dict(event="push", verify="failure", full_needed=False), False),
    ("build (Pages artifact) fails", dict(event="push", build="failure"), False),
    ("scheduled refresh passes", dict(event="schedule", refresh="success", full_needed=False), True),
    ("scheduled refresh fails its data check", dict(event="schedule", refresh="failure"), False),
    ("pull request, everything passes", dict(event="pull_request"), False),
]
for ev in ("push", "pull_request"):
    got, res = run(event=ev, full_needed=True)
    ok(res["full"] == "success", f"Gate: on a {ev} that needs the full suite, the full suite runs ({res})")
bc = jobs["build"]["if"]
ok(not evaluate(bc, {"result": {"verify": "success", "full": "skipped"}, "outputs": {"verify": {"full": "true"}}, "event": "push"}),
   "Gate: a full suite that was needed but skipped (for any reason) never deploys")
ok(evaluate(bc, {"result": {"verify": "success", "full": "skipped"}, "outputs": {"verify": {"full": "false"}}, "event": "push"}),
   "Gate: the fast path deploys only when verify said this exact code already passed the full suite")
for label, kw, want in cases:
    got, res = run(**kw)
    ok(got == want, f"Gate: {label} → {'deploys' if got else 'no deploy'} {res}")
ok("always()" in jobs["mark-verified"]["if"] and "always()" in jobs["full"]["if"], "full and mark-verified can't be skipped by a skipped upstream job")
mv = jobs["mark-verified"]["if"]
ok(evaluate(mv, {"result": {"full": "success"}, "outputs": {}, "event": "push"}) and not evaluate(mv, {"result": {"full": "failure"}, "outputs": {}, "event": "push"})
   and not evaluate(mv, {"result": {"full": "skipped"}, "outputs": {}, "event": "push"}) and not evaluate(mv, {"result": {"full": "success"}, "outputs": {}, "event": "pull_request"}),
   "A fingerprint is marked verified only after the full suite passed on a push")

# 6. pull requests: nothing that writes runs for them
pr_jobs = [j for j in jobs if run(event="pull_request")[1].get(j) not in ("skipped", None)]
ok(set(pr_jobs) <= {"verify", "full"}, f"Only the check jobs run for a pull request: {pr_jobs}")
ok(all(not (jobs[j].get("permissions") or {}) for j in pr_jobs) and wf["permissions"] == {"contents": "read"}, "…with read-only permissions")
ok("secrets." not in open(os.path.join(ROOT, ".github/workflows/site.yml")).read(), "The workflow uses no secrets")
ok(jobs["refresh"]["if"].replace(" ", "") == "github.event_name=='schedule'||github.event_name=='workflow_dispatch'", "The data refresh (the only job that pushes) runs only on the schedule or a manual run")
ok("pull_request" in jobs["build"]["if"] and "pull_request" in jobs["mark-verified"]["if"], "Build (and so deploy) and the verified-code record exclude pull requests explicitly")

# 3. run_ci.py decisions, on synthetic suites
tmp = tempfile.mkdtemp()
try:
    fake = os.path.join(tmp, "repo"); os.makedirs(os.path.join(fake, "tests"))
    shutil.copy(os.path.join(ROOT, "tests/run_ci.py"), os.path.join(fake, "tests/run_ci.py"))
    policy = json.load(open(os.path.join(ROOT, "tests/ci_policy.json")))
    # a synthetic known failure, so run_ci's known-failure handling is tested whether or not the real policy lists one
    # (none since Oct 12: one-player tiers became information)
    policy["known_failures"]["value_curve_check"] = {"Synthetic baseline failure": "test only"}
    def suite(name, lines, rc):
        open(os.path.join(fake, "tests", name + ".py"), "w").write("import sys\n" + "".join(f"print({l!r})\n" for l in lines) + f"sys.exit({rc})\n")
    def ci(suites_lines):
        policy["suites"]["fast"] = list(suites_lines)
        json.dump(policy, open(os.path.join(fake, "tests/ci_policy.json"), "w"))
        for n, (lines, rc) in suites_lines.items(): suite(n, lines, rc)
        r = subprocess.run([sys.executable, "tests/run_ci.py", "fast", "--logs", os.path.join(tmp, "logs")], cwd=fake, capture_output=True, text=True)
        return r.returncode, r.stdout
    rc, o = ci({"value_curve_check": (["PASS a", "FAIL Synthetic baseline failure"], 1)})
    ok(rc == 0 and "known baseline failure" in o, "run_ci: the known baseline failure alone doesn't block")
    rc, o = ci({"value_curve_check": (["PASS a", "FAIL Synthetic baseline failure", "FAIL Model value worth more than someone ahead"], 1)})
    ok(rc == 1 and "NEW FAILURE: Model value" in o, "run_ci: a new failure in the same suite blocks")
    rc, o = ci({"drag_check": (["PASS a", "FAIL No long tasks while grabbing and moving: [140]"], 1)})
    ok(rc == 0 and "advisory" in o, "run_ci: an advisory timing check doesn't block")
    rc, o = ci({"drag_check": (["PASS a", "FAIL Escape cancels: board unchanged"], 1)})
    ok(rc == 1, "run_ci: a correctness failure in a drag suite blocks")
    rc, o = ci({"smoke_check": (["PASS a", "Traceback (most recent call last):"], 1)})
    ok(rc == 1 and "crashed" in o, "run_ci: a crash without a FAIL line blocks")
    rc, o = ci({"value_curve_check": (["PASS a", "PASS Synthetic baseline failure"], 0)})
    ok(rc == 0 and "no longer fails" in o, "run_ci: a known failure that now passes is reported")

    # run_ci scheduling (Oct 14): independent suites run in parallel with --jobs, the exclusive (timing) suites run alone
    # afterwards, a heartbeat shows what is running, a suite over the timeout is a failure; nothing is skipped
    import time as _time
    def timed_suite(name, secs, lines=("PASS a",)):
        stamp = os.path.join(tmp, f"stamp-{name}")
        open(os.path.join(fake, "tests", name + ".py"), "w").write(
            f"import time\nopen({stamp!r}, 'w').write(str(time.time()) + ' ')\ntime.sleep({secs})\nopen({stamp!r}, 'a').write(str(time.time()))\n" + "".join(f"print({l!r})\n" for l in lines))
    def stamps(name):
        a, b = open(os.path.join(tmp, f"stamp-{name}")).read().split(); return float(a), float(b)
    def sched(names, *args):
        policy["suites"]["fast"] = list(names); json.dump(policy, open(os.path.join(fake, "tests/ci_policy.json"), "w"))
        t0 = _time.time(); r = subprocess.run([sys.executable, "tests/run_ci.py", "fast", "--logs", os.path.join(tmp, "logs"), *args], cwd=fake, capture_output=True, text=True)
        return r.returncode, r.stdout, _time.time() - t0
    policy["suites"]["exclusive"] = ["drag_check"]
    for nm in ("s1", "s2", "s3"): timed_suite(nm, 2)
    timed_suite("drag_check", 1)
    rc, o, wall = sched(["s1", "s2", "s3", "drag_check"], "--jobs", "3", "--heartbeat", "0.5")
    st = {nm: stamps(nm) for nm in ("s1", "s2", "s3", "drag_check")}
    ok(rc == 0 and max(st[n][0] for n in ("s1", "s2", "s3")) < min(st[n][1] for n in ("s1", "s2", "s3")) and wall < 5.5,
       f"run_ci --jobs 3: the three independent suites ran at the same time ({wall:.1f}s wall for 7s of suite time)")
    ok(st["drag_check"][0] >= max(st[n][1] for n in ("s1", "s2", "s3")), "run_ci: the exclusive (timing) suite started only after every other suite had finished")
    ok("[start] s1" in o and "running:" in o and "3 at a time" in o and o.count("[pass]") == 4, "run_ci: start lines, a heartbeat while suites run, and one result line per suite")
    rc, o, wall = sched(["s1", "s2"])
    st = {nm: stamps(nm) for nm in ("s1", "s2")}
    ok(rc == 0 and (st["s1"][1] <= st["s2"][0] or st["s2"][1] <= st["s1"][0]) and "running:" not in o,
       "run_ci (default --jobs 1, as in CI): suites run one at a time and the 60s heartbeat stays quiet on a short run")
    timed_suite("slow", 12)
    rc, o, wall = sched(["slow", "s1"], "--jobs", "2", "--timeout", "0.05")
    ok(rc == 1 and "timed out after 0.05 min" in o and "[pass] s1" in o and wall < 10, f"run_ci: a suite over the timeout fails the run while the others still report ({wall:.1f}s)")
    # a timed-out suite's own subprocesses (browsers, servers) die with it: the suite runs in its own process group
    child_pid = os.path.join(tmp, "child-pid")
    open(os.path.join(fake, "tests", "hang.py"), "w").write(
        f"import subprocess, time\np = subprocess.Popen(['sleep', '300'])\nopen({child_pid!r}, 'w').write(str(p.pid))\nprint('PASS a')\ntime.sleep(300)\n")
    rc, o, wall = sched(["hang"], "--timeout", "0.05")
    pid = int(open(child_pid).read()); _time.sleep(0.5)
    def state(pid):   # a killed child whose parent died is a zombie until init reaps it (some sandboxes never do): dead for our purposes
        try: return open(f"/proc/{pid}/status").read().split("State:")[1].split()[0]
        except (FileNotFoundError, ProcessLookupError, IndexError): return "gone"
    alive = state(pid) not in ("gone", "Z", "X")
    if alive: os.kill(pid, 9)
    ok(rc == 1 and "timed out" in o and not alive and wall < 10, f"run_ci: a timed-out suite's subprocess is killed with it ({'still alive' if alive else 'gone'})")
    policy["suites"].pop("exclusive", None)

    # 4. static_check.py on broken copies of the repo
    def repo_copy():
        d = os.path.join(tmp, "copy"); shutil.rmtree(d, ignore_errors=True)
        subprocess.run(["git", "clone", "-q", "--no-hardlinks", ROOT, d], check=True)
        for f in ("tests/static_check.py",): shutil.copy(os.path.join(ROOT, f), os.path.join(d, f))
        shutil.copy(os.path.join(ROOT, "index.html"), os.path.join(d, "index.html"))
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "base", "--allow-empty"], cwd=d, check=True)
        return d
    def static(d, *args):
        r = subprocess.run([sys.executable, "tests/static_check.py", *args], cwd=d, capture_output=True, text=True)
        return r.returncode, r.stdout
    d = repo_copy()
    rc, o = static(d, "--base", "HEAD", "--frozen-rankings")
    ok(rc == 0, "static_check: the untouched copy passes")
    html = open(os.path.join(d, "index.html")).read()
    m = re.search(r"const RANKINGS_CSV = `\n([\s\S]*?)\n`;", html); lines = m[1].split("\n")
    def with_csv(lines2): return html[:m.start(1)] + "\n".join(lines2) + html[m.end(1):]
    dup = lines[:]; dup[3] = re.sub(r"^([^,]*,[^,]*,[^,]*,)\d+", r"\g<1>1", dup[3])   # two players at rank 1
    open(os.path.join(d, "index.html"), "w").write(with_csv(dup))
    rc, o = static(d); ok(rc == 1 and "ranks don't run" in o, "static_check: a duplicate rank fails")
    nosid = lines[:]; cols = nosid[0].split(","); i = cols.index("sleeper_id"); r = nosid[5].split(","); r[i] = ""; nosid[5] = ",".join(r)
    open(os.path.join(d, "index.html"), "w").write(with_csv(nosid))
    rc, o = static(d); ok(rc == 1 and "no Sleeper ID" in o, "static_check: a missing Sleeper ID fails")
    swap = lines[:]; ri = cols.index("rank"); pi = cols.index("pos_rank")
    a, b = swap[1].split(","), swap[2].split(",")   # swap #1 and #2 (still a valid board)
    a[ri], b[ri] = b[ri], a[ri]
    if a[cols.index("pos")] == b[cols.index("pos")]: a[pi], b[pi] = b[pi], a[pi]
    swap[1], swap[2] = ",".join(a), ",".join(b)
    open(os.path.join(d, "index.html"), "w").write(with_csv(swap))
    rc, o = static(d); ok(rc == 0, "static_check: a valid rankings edit passes without --frozen-rankings")
    rc, o = static(d, "--base", "HEAD", "--frozen-rankings"); ok(rc == 1 and "No ranking field changed" in o, "static_check: the same edit fails for an automated job (--frozen-rankings)")
    shutil.copy(os.path.join(ROOT, "index.html"), os.path.join(d, "index.html"))
    h = json.load(open(os.path.join(d, "data/rank_history.json"))); sid = next(iter(h["players"])); h["players"][sid][0][1] += 1
    json.dump(h, open(os.path.join(d, "data/rank_history.json"), "w"))
    rc, o = static(d, "--base", "HEAD"); ok(rc == 1 and "history only grows" in o, "static_check: a rewritten history entry fails")
    open(os.path.join(d, "index.html"), "w").write(html.replace("const BUILD_ID", "const const BUILD_ID", 1))
    rc, o = static(d); ok(rc == 1 and "scripts parse" in o, "static_check: a JavaScript syntax error fails")
    # snapshots: both formats pass (the committed file holds 5-field snapshots from before Oct 12 and 4-field ones since);
    # a wrong field count for the snapshot's format, a bad typed flag, a duplicate rank or timestamp each fail
    shutil.copy(os.path.join(ROOT, "index.html"), os.path.join(d, "index.html"))
    json.dump(h0 := json.load(open(os.path.join(ROOT, "data/rank_history.json"))), open(os.path.join(d, "data/rank_history.json"), "w"))
    sp = os.path.join(d, "data/rank_snapshots/2026-10.json"); snap0 = json.load(open(sp))
    kinds = {("valueModelVersion" in s): len(next(iter(s["players"].values()))) for s in snap0["snapshots"]}
    ok(kinds.get(True) == 4 and kinds.get(False) == 5, f"The committed snapshot file holds both formats: 4-field with a value model, 5-field legacy {kinds}")
    rc, o = static(d); ok(rc == 0, "static_check: both snapshot formats pass as committed")
    def snap_case(label, fn, msg):
        f = json.loads(json.dumps(snap0)); fn(f); json.dump(f, open(sp, "w"))
        rc, o = static(d); ok(rc == 1 and msg in o, f"static_check: {label} fails")
    new = lambda f: next(s for s in f["snapshots"] if "valueModelVersion" in s)
    old = lambda f: next(s for s in f["snapshots"] if "valueModelVersion" not in s)
    def five_in_new(f): sid = next(iter(new(f)["players"])); new(f)["players"][sid].append(0)
    def four_in_old(f): sid = next(iter(old(f)["players"])); old(f)["players"][sid].pop()
    def bad_typed(f): sid = next(iter(old(f)["players"])); old(f)["players"][sid][4] = 2
    def dup_rank(f): a, b = list(new(f)["players"].values())[:2]; b[0] = a[0]
    def dup_ts(f): f["snapshots"].append(json.loads(json.dumps(f["snapshots"][-1])))
    def zero_rank(f): sid = next(iter(new(f)["players"])); new(f)["players"][sid][0] = 0
    def float_value(f): sid = next(iter(new(f)["players"])); new(f)["players"][sid][3] = 5760.5
    for label, fn, msg in (("a 5-field entry in a value-model snapshot", five_in_new, "isn't a 4-field entry"), ("a 4-field entry in a legacy snapshot", four_in_old, "isn't a 5-field entry"),
                           ("a typed flag of 2", bad_typed, "isn't a 5-field entry"), ("a duplicate rank", dup_rank, "appears twice"), ("a duplicate timestamp", dup_ts, "two snapshots at"),
                           ("a rank of 0", zero_rank, "isn't a 4-field entry"), ("a fractional value", float_value, "isn't a 4-field entry")):
        snap_case(label, fn, msg)
    json.dump(snap0, open(sp, "w"))

    # 5. the fast path's fingerprint: data-only changes keep it, anything that can change behaviour changes it
    shutil.copy(os.path.join(ROOT, "index.html"), os.path.join(d, "index.html"))
    for f in ("tests/release_fingerprint.py", "tests/requirements-ci.txt", "tests/ci_policy.json", ".github/workflows/site.yml"):
        os.makedirs(os.path.dirname(os.path.join(d, f)), exist_ok=True); shutil.copy(os.path.join(ROOT, f), os.path.join(d, f))
    subprocess.run(["git", "add", "-A"], cwd=d, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "fp base", "--allow-empty"], cwd=d, check=True)
    fp = lambda: subprocess.run([sys.executable, "tests/release_fingerprint.py"], cwd=d, capture_output=True, text=True).stdout.strip()
    def mutate(label, path, fn, expect_same, new_file=False):
        full = os.path.join(d, path); orig = open(full, "rb").read() if os.path.exists(full) else None
        before = fp()
        os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
        open(full, "wb").write(fn(orig or b""))
        if new_file: subprocess.run(["git", "add", path], cwd=d, check=True)
        after = fp()
        ok((before == after) == expect_same, f"Fingerprint {'unchanged' if expect_same else 'changes'}: {label}")
        if new_file: subprocess.run(["git", "rm", "-q", "--cached", path], cwd=d, check=True); os.remove(full)
        else: open(full, "wb").write(orig)
    def csv_edit(b):   # swap two players' ranks inside the rankings block only
        t = b.decode(); m = re.search(r"const RANKINGS_CSV = `\n([\s\S]*?)\n`;", t); ls = m[1].split("\n")
        ls[1], ls[2] = ls[2], ls[1]
        return (t[:m.start(1)] + "\n".join(ls) + t[m.end(1):]).encode()
    mutate("a rankings edit (RANKINGS_CSV block only)", "index.html", csv_edit, True)
    mutate("ranking history / snapshot data", "data/rank_history.json", lambda b: b + b" ", True)
    mutate("a stats / market data file", "data/stats/2026.json", lambda b: b + b" ", True)
    mutate("application code in index.html (outside the rankings block)", "index.html", lambda b: b.replace(b"const BUILD_ID", b"const  BUILD_ID", 1), False)
    mutate("CSS in index.html", "index.html", lambda b: b.replace(b"<style>", b"<style>/**/", 1), False)
    mutate("a test", "tests/static_check.py", lambda b: b + b"\n# x\n", False)
    mutate("the pinned test dependencies", "tests/requirements-ci.txt", lambda b: b.replace(b"1.56.0", b"1.56.1"), False)
    mutate("the CI policy (known / advisory failures)", "tests/ci_policy.json", lambda b: b.replace(b'"note"', b'"note "', 1), False)
    mutate("the workflow", ".github/workflows/site.yml", lambda b: b + b"\n# x\n", False)
    mutate("a pipeline script", "pipeline/build_market.py", lambda b: b + b"\n# x\n", False)
    mutate("the manifest", "manifest.webmanifest", lambda b: b.replace(b"{", b"{ ", 1), False)
    mutate("a new script file under data/ (not JSON)", "data/extra.js", lambda b: b"alert(1)", False, new_file=True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n{len(failures)} check(s) failed." if failures else "\nAll pipeline checks passed.")
sys.exit(1 if failures else 0)
