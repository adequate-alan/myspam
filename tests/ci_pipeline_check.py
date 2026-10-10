"""The release pipeline itself (Phase 1 reliability), without GitHub: GitHub Actions can't run locally, so this checks
the workflow's job graph and gate conditions, and runs the CI tools against deliberately broken inputs.

Run from the repo root:  python3 tests/ci_pipeline_check.py      (needs PyYAML; no browser)

1. Workflow structure: deploy only after build; build only after verify and the lane's own checks (fast: verify;
   targeted: its suites; full: the whole suite), with a nightly and a manual full CI that never deploy,
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
7. The release lanes (tests/release_tier.py) on a scratch repo with the real index.html: CSS, copy, BUILD_ID, comments,
   data and docs are fast; one UI feature's render code or a test file is targeted with that feature's suites; two
   features, Architecture C, publishing, shared helpers, settings, markup, unmapped functions, the workflow, a
   `CI: full` trailer and --force-full are full; and the diff is taken from the last verified commit, so an unverified
   risky commit can't ride out with a later CSS push.
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
ok(need("deploy") == ["build"] and set(need("build")) == {"verify", "targeted", "full"} and need("full") == ["verify"] and need("targeted") == ["verify"] and need("verify") == ["refresh"],
   f"Job graph refresh → verify → (targeted | full) → build → deploy ({ {j: need(j) for j in jobs} })")
steps = [s.get("name", s.get("uses", "")) for s in jobs["refresh"]["steps"]]
ok(steps.index("Check the refreshed data before committing") < steps.index("Commit refreshed site"), "The scheduled refresh checks its data before it commits")
chk = next(s for s in jobs["refresh"]["steps"] if s.get("name") == "Check the refreshed data before committing")["run"]
ok("--frozen-rankings" in chk, "…and fails if any ranking field changed")
ok(wf["permissions"] == {"contents": "read"}, "Default permissions are read-only")
ok(jobs["refresh"]["permissions"] == {"contents": "write"} and jobs["deploy"]["permissions"] == {"pages": "write", "id-token": "write"}
   and jobs["verify"]["permissions"] == {"contents": "read", "actions": "read"}
   and all("permissions" not in jobs[j] for j in ("targeted", "full", "build", "mark-verified")), "Only refresh can push and only deploy can publish Pages (verify may read the Actions cache list)")
for j in ("verify", "targeted", "full", "build"):
    co = next(s for s in jobs[j]["steps"] if str(s.get("uses", "")).startswith("actions/checkout"))
    ok(co.get("with", {}).get("persist-credentials") is False, f"{j}: the checkout doesn't keep the GitHub token")
for j in ("full", "targeted"):
    ok(any("upload-artifact" in str(s.get("uses")) and s.get("if") == "always()" for s in jobs[j]["steps"]), f"{j}: logs are uploaded whether it passes or fails")
for j in ("verify", "targeted", "full"):
    inst = next(s for s in jobs[j]["steps"] if str(s.get("name", "")).startswith("Install the test browser"))
    ok(0 < inst.get("timeout-minutes", 0) <= 10, f"{j}: the browser install has a time limit (a hung install can't hold a release)")
crons = [c["cron"] for c in on["schedule"]]
ok("15 7 * * *" in crons, "A nightly full CI run is scheduled (07:15 UTC)")
ok(on["workflow_dispatch"]["inputs"]["full_ci"]["type"] == "boolean", "Run workflow offers a manual full CI")
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
NIGHTLY = "15 7 * * *"
def evaluate(expr, ctx):
    e = str(expr).replace("${{", "").replace("}}", "").strip()
    e = re.sub(r"always\(\)", "True", e)
    e = re.sub(r"needs\.([\w-]+)\.result", lambda m: repr(ctx["result"].get(m[1], "skipped")), e)
    e = re.sub(r"needs\.([\w-]+)\.outputs\.(\w+)", lambda m: repr(ctx["outputs"].get(m[1], {}).get(m[2], "")), e)
    e = re.sub(r"format\('pr-\{0\}', github\.ref\)", repr("pr-x"), e)
    e = re.sub(r"github\.event_name", repr(ctx["event"]), e)
    e = re.sub(r"github\.event\.schedule", repr(ctx.get("schedule") or ""), e)
    e = re.sub(r"inputs\.full_ci", repr(bool(ctx.get("full_ci"))), e)
    e = e.replace("&&", " and ").replace("||", " or ").replace("!=", " != ")
    e = re.sub(r"!(?!=)", " not ", e)
    return eval(e, {})

def ancestors(j, seen=None):
    seen = set() if seen is None else seen
    for d in need(j):
        if d not in seen: seen.add(d); ancestors(d, seen)
    return seen

def run(event, lane="fast", schedule=None, full_ci=False, refresh="success", verify="success", targeted="success", full="success", build="success", current="true"):
    """Walk the graph like Actions: a job runs when its `if` is true (jobs without one need every dependency to succeed)."""
    res, out = {}, {}
    ctx = {"result": res, "outputs": out, "event": event, "schedule": schedule, "full_ci": full_ci}
    def go(j, actual):
        cond = jobs[j].get("if")
        # GitHub's rule: a job whose `if` has no status function gets an implicit success(), which needs EVERY job
        # upstream of it (direct or not) to have succeeded; a skipped ancestor skips it (PR #1's first run)
        ok_up = all(res.get(a) == "success" for a in ancestors(j))
        runs = bool(evaluate(cond, ctx) if cond else True) and (ok_up or (cond is not None and re.search(r"always\(\)|failure\(\)|cancelled\(\)", str(cond)) is not None))
        res[j] = actual if runs else "skipped"
    go("refresh", refresh)
    go("verify", verify)
    deploy_flag = evaluate(next(s for s in jobs["verify"]["steps"] if s.get("id") == "ref")["run"].split("deploy=")[1].split("}}")[0] + "}}", ctx)
    out["verify"] = {"lane": "full" if (schedule == NIGHTLY or full_ci) else lane, "deploy": "true" if deploy_flag else "false"} if res["verify"] == "success" else {}
    go("targeted", targeted); go("full", full); go("mark-verified", "success"); go("build", build)
    out["build"] = {"current": current} if res["build"] == "success" else {}
    go("deploy", "success")
    return res["deploy"] == "success", res

cases = [
    ("fast lane push (CSS, copy, data), verify passes", dict(event="push", lane="fast"), True),
    ("fast lane push, static/smoke checks fail", dict(event="push", lane="fast", verify="failure"), False),
    ("targeted push, its suites pass", dict(event="push", lane="targeted"), True),
    ("targeted push, a suite fails", dict(event="push", lane="targeted", targeted="failure"), False),
    ("full push, the full suite passes", dict(event="push", lane="full"), True),
    ("full push, a required test fails", dict(event="push", lane="full", full="failure"), False),
    ("build (Pages artifact) fails", dict(event="push", lane="fast", build="failure"), False),
    ("main moved on before the build (stale commit)", dict(event="push", lane="fast", current="false"), False),
    ("scheduled refresh passes (data: fast lane)", dict(event="schedule", schedule="0 15 * * 1", lane="fast"), True),
    ("scheduled refresh fails its data check", dict(event="schedule", schedule="0 15 * * 1", refresh="failure"), False),
    ("nightly full CI passes", dict(event="schedule", schedule=NIGHTLY), False),
    ("manual full CI passes", dict(event="workflow_dispatch", full_ci=True), False),
    ("manual stats refresh", dict(event="workflow_dispatch", lane="fast"), True),
    ("pull request, everything passes", dict(event="pull_request", lane="full"), False),
]
for label, kw, want in cases:
    got, res = run(**kw)
    ok(got == want, f"Gate: {label} → {'deploys' if got else 'no deploy'} {res}")
for lane in ("fast", "targeted"):
    _, res = run(event="push", lane=lane)
    ok(res["full"] == "skipped", f"Gate: a {lane}-lane release runs no full suite (no trailing full CI): {res}")
_, res = run(event="push", lane="fast"); ok(res["targeted"] == "skipped", "Gate: a fast-lane release runs no targeted suites")
_, res = run(event="push", lane="full"); ok(res["targeted"] == "skipped" and res["full"] == "success", "Gate: a full-lane release runs the full suite and no targeted job")
for kw in (dict(event="schedule", schedule=NIGHTLY), dict(event="workflow_dispatch", full_ci=True)):
    _, res = run(**kw)
    ok(res["refresh"] == "skipped" and res["full"] == "success" and res["build"] == "skipped", f"Gate: nightly / manual full CI runs the full suite, refreshes nothing and never builds: {res}")
_, res = run(event="schedule", schedule="0 15 * * 1"); ok(res["refresh"] == "success", "Gate: the other schedules still run the data refresh")
bc = jobs["build"]["if"]
for lane, job in (("targeted", "targeted"), ("full", "full")):
    ok(not evaluate(bc, {"result": {"verify": "success", job: "skipped"}, "outputs": {"verify": {"lane": lane, "deploy": "true"}}, "event": "push"}),
       f"Gate: a {lane} lane whose check job was skipped (for any reason) never deploys")
ok("always()" in jobs["mark-verified"]["if"] and "always()" in jobs["full"]["if"] and "always()" in jobs["targeted"]["if"], "targeted, full and mark-verified can't be skipped by a skipped upstream job")
mv = jobs["mark-verified"]["if"]
mvc = lambda lane, r, ev="push": evaluate(mv, {"result": {"verify": "success", **r}, "outputs": {"verify": {"lane": lane}}, "event": ev})
ok(mvc("fast", {}) and mvc("targeted", {"targeted": "success"}) and mvc("full", {"full": "success"})
   and not mvc("targeted", {"targeted": "failure"}) and not mvc("full", {"full": "failure"}) and not mvc("full", {"full": "skipped"})
   and not mvc("fast", {}, "pull_request"),
   "Code is marked verified only after its lane's checks passed, and never from a pull request")

# concurrency: pushes cancel the run they supersede; the nightly / manual full CI and the data refresh have their own
# groups and never cancel or delay a push; deploys are serialized on their own
cg = wf["concurrency"]
grp = lambda **c: evaluate(cg["group"], {"result": {}, "outputs": {}, **c})
cnl = lambda **c: evaluate(cg["cancel-in-progress"], {"result": {}, "outputs": {}, **c})
g_push, g_pr, g_night, g_full, g_ref = grp(event="push"), grp(event="pull_request"), grp(event="schedule", schedule=NIGHTLY), grp(event="workflow_dispatch", full_ci=True), grp(event="schedule", schedule="0 15 * * 1")
ok(g_push == "release" and cnl(event="push") is True, f"Concurrency: a push cancels the obsolete release run it supersedes ({g_push})")
ok(g_pr == "pr-x" and cnl(event="pull_request") is True, "Concurrency: a pull request cancels its own older run")
ok(g_night == g_full == "full-ci" and g_night != g_push and not cnl(event="schedule", schedule=NIGHTLY), f"Concurrency: nightly and manual full CI share their own group, never the release group, and never cancel ({g_night})")
ok(g_ref == "refresh" and g_ref != g_push and not cnl(event="schedule", schedule="0 15 * * 1"), "Concurrency: the data refresh has its own group and isn't cancelled by a push")
ok(jobs["deploy"].get("concurrency", {}).get("group") == "pages-deploy" and jobs["deploy"]["concurrency"].get("cancel-in-progress") is False, "Deploys are serialized in their own group")

# 6. pull requests: nothing that writes runs for them
pr_jobs = [j for j in jobs if run(event="pull_request", lane="full")[1].get(j) not in ("skipped", None)] + [j for j in jobs if run(event="pull_request", lane="targeted")[1].get(j) not in ("skipped", None)]
ok(set(pr_jobs) <= {"verify", "full", "targeted"}, f"Only the check jobs run for a pull request: {sorted(set(pr_jobs))}")
ok(all(not (jobs[j].get("permissions") or {}).get("contents") == "write" for j in pr_jobs) and wf["permissions"] == {"contents": "read"}, "…with read-only permissions")
ok("secrets." not in open(os.path.join(ROOT, ".github/workflows/site.yml")).read(), "The workflow uses no secrets")
ok("github.event_name == 'pull_request'" in jobs["mark-verified"]["if"].replace("!=", "==") and "deploy" in jobs["build"]["if"], "Build (and so deploy) and the verified-code record exclude pull requests")

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

# 7. the release lane classifier (tests/release_tier.py) on a scratch repo with the real index.html
tmp2 = tempfile.mkdtemp()
try:
    rp = os.path.join(tmp2, "r"); os.makedirs(os.path.join(rp, "tests")); os.makedirs(os.path.join(rp, ".github/workflows"))
    for f in ("index.html", "tests/release_tier.py", "tests/release_fingerprint.py", "tests/drawer_check.py", ".github/workflows/site.yml"):
        shutil.copy(os.path.join(ROOT, f), os.path.join(rp, f))
    open(os.path.join(rp, "README.md"), "w").write("readme\n"); open(os.path.join(rp, ".gitignore"), "w").write("__pycache__/\n")
    G = lambda *a: subprocess.run(["git", *a], cwd=rp, capture_output=True, text=True, check=True).stdout.strip()
    G("init", "-q"); G("add", "-A"); G("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
    BASE = G("rev-parse", "HEAD")
    sys.path.insert(0, os.path.join(rp, "tests"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("rt", os.path.join(rp, "tests/release_tier.py")); RT = importlib.util.module_from_spec(spec); spec.loader.exec_module(RT)
    html0 = open(os.path.join(rp, "index.html")).read()
    L0, R0, F0 = RT.regions(html0)
    def line_of(pred, start=0):
        return next(i for i in range(max(1, start), len(L0) + 1) if pred(i))
    def in_fn(name, extra=lambda l: True):   # a code line inside a top-level function
        return line_of(lambda i: R0[i] == "js" and F0[i] == name and L0[i - 1].strip() and not L0[i - 1].strip().startswith("//")
                       and not re.match(r"^  (async\s+)?(function|const|let|var)\b", L0[i - 1]) and extra(L0[i - 1]))
    def lane(edits, msg="change", files=None, force=False):
        G("checkout", "-q", BASE)
        lines = html0.split("\n")
        for i, fn in edits: lines[i - 1] = fn(lines[i - 1])
        open(os.path.join(rp, "index.html"), "w").write("\n".join(lines))
        for f, txt in (files or {}).items():
            os.makedirs(os.path.dirname(os.path.join(rp, f)) or rp, exist_ok=True); open(os.path.join(rp, f), "a").write(txt)
        G("add", "-A"); G("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", msg, "--allow-empty")
        c = RT.classify(BASE, "HEAD", force); G("checkout", "-q", "-f", BASE); G("clean", "-qfd")
        return c
    code = lambda l: l + " "                          # a real code change on that line
    css_line = line_of(lambda i: R0[i] == "css" and "{" in L0[i - 1] and "drag" not in L0[i - 1])
    cases = [
        ("CSS", [(css_line, lambda l: l.replace("{", "{ outline: 0;", 1))], {}, "fast", []),
        # the trade card's verdict label (found by structure, not wording: the label text itself changes over time)
        ("copy: a label in a render function", [(line_of(lambda i: F0[i] == "tradeCard" and re.search(r'r\.then \? "[A-Z][^"]*"', L0[i - 1]) is not None),
            lambda l: re.sub(r'(r\.then \? )"[A-Z][^"]*"', r'\1"Earlier"', l, count=1))], {}, "fast", []),
        ("BUILD_ID", [(line_of(lambda i: L0[i - 1].strip().startswith('const BUILD_ID = "')), lambda l: re.sub(r'"[^"]*"', '"2099-01-01T00:00Z"', l))], {}, "fast", []),
        ("a JS comment", [(line_of(lambda i: R0[i] == "js" and L0[i - 1].strip().startswith("// ")), lambda l: l + " (edited)")], {}, "fast", []),
        ("the rankings block (a publish)", [(line_of(lambda i: R0[i] == "rankings"), lambda l: l.replace(",manual", ",manual", 1) + "")], {"data/rank_history.json": "{}"}, "fast", []),
        ("docs", [], {"README.md": "more\n"}, "fast", []),
        ("render code of one feature (tradeCard)", [(in_fn("tradeCard"), code)], {}, "targeted", ["form_trend_check", "league_hub_check", "trade_history_check", "xss_check"]),
        ("render code of the drawer (ppSchedule)", [(in_fn("ppSchedule"), code)], {}, "targeted", ["drawer_check", "xss_check"]),
        ("a class name in a lowercase string is code, not copy", [(line_of(lambda i: F0[i] == "tradeCard" and 'class="th-age' in L0[i - 1]), lambda l: l.replace('class="th-age', 'class="th-agex', 1))], {}, "targeted", None),
        ("a test file only", [], {"tests/drawer_check.py": "\n# x\n"}, "targeted", ["drawer_check"]),
        ("two UI features at once", [(in_fn("tradeCard"), code), (in_fn("renderTrade"), code)], {}, "full", []),
        ("Architecture C value state (stateValues)", [(in_fn("stateValues"), code)], {}, "full", []),
        ("publishing (publishLive)", [(in_fn("publishLive"), code)], {}, "full", []),
        ("a shared helper (esc)", [(in_fn("esc") if any(F0[i] == "esc" and L0[i-1].strip() and not re.match(r"^  (const|function)", L0[i-1]) for i in range(1, len(L0)+1)) else line_of(lambda i: F0[i] == "esc"), code)], {}, "full", []),
        ("the settings script (VALUE_MODEL)", [(line_of(lambda i: R0[i] == "settings-js" and "VALUE_MODEL" in L0[i - 1]), code)], {}, "full", []),
        ("page markup", [(line_of(lambda i: R0[i] == "markup" and "<nav" in L0[i - 1]), lambda l: l.replace("<nav", "<nav data-x", 1))], {}, "full", []),
        ("a function not in the map", [(line_of(lambda i: R0[i] == "js" and F0[i] is not None and F0[i] not in RT.FN and L0[i - 1].strip() and not L0[i - 1].strip().startswith("//") and not re.match(r"^  (async\s+)?(function|const|let|var)\b", L0[i - 1])), code)], {}, "full", []),
        ("the workflow", [], {".github/workflows/site.yml": "\n# x\n"}, "full", []),
        ("CSS with a 'CI: full' commit trailer", [(css_line, lambda l: l + " ")], {}, "full", []),
    ]
    for label, edits, files, want, suites in cases:
        c = lane(edits, "change\n\nCI: full" if "trailer" in label else "change", files)
        ok(c["lane"] == want and (suites is None or c["suites"] == suites), f"Lane: {label} → {want}{' ' + str(suites) if suites else ''} (got {c['lane']} {c['suites']}; {c['reasons'][:3]})")
    c = lane([(css_line, lambda l: l + " ")], force=True); ok(c["lane"] == "full", "Lane: --force-full (manual full CI, full-ci label) → full")
    # the diff is taken from the last commit that passed its checks: an unverified risky commit can't ride out with a CSS push
    FP = lambda rev: subprocess.run([sys.executable, "tests/release_fingerprint.py", "--rev", rev], cwd=rp, capture_output=True, text=True).stdout.strip()
    def commit(edits, msg):
        lines = open(os.path.join(rp, "index.html")).read().split("\n")
        for i, fn in edits: lines[i - 1] = fn(lines[i - 1])
        open(os.path.join(rp, "index.html"), "w").write("\n".join(lines)); G("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", msg); return G("rev-parse", "HEAD")
    G("checkout", "-q", "-b", "walk", BASE)
    risky = commit([(in_fn("stateValues"), code)], "risky, never verified (failed or cancelled)")
    css = commit([(css_line, lambda l: l.replace("{", "{ outline: 0;", 1))], "CSS on top")
    def walk_lane(ok_fps):
        b = RT.ok_base(css, set(ok_fps)); return (b, RT.classify(b, css)["lane"])
    b, l = walk_lane([FP(BASE)])
    ok(b == BASE and l == "full", f"Walk: a CSS push on top of an unverified Architecture C change gets the full lane ({l})")
    b, l = walk_lane([FP(BASE), FP(risky)])
    ok(b == risky and l == "fast", f"Walk: once that change passed, the CSS push on top is fast ({l})")
    b, l = walk_lane([])
    ok(b is None and l == "full", "Walk: no verified commit within reach → full lane")
    css2 = commit([(css_line, lambda l: l + "  ")], "another CSS tweak")
    b = RT.ok_base(css2, {FP(BASE), FP(risky)}); l = RT.classify(b, css2)["lane"]
    ok(b == risky and l == "fast", "Walk: a cancelled (superseded) CSS push is diffed together with the next one, still fast")
finally:
    shutil.rmtree(tmp2, ignore_errors=True)

print(f"\n{len(failures)} check(s) failed." if failures else "\nAll pipeline checks passed.")
sys.exit(1 if failures else 0)
