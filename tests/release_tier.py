"""Release lane of a push (Alan, Oct 14): how much CI it needs before it may deploy.

  python3 tests/release_tier.py --head SHA [--start SHA] [--ok-keys FILE] [--force-full] [--json] [--github-output]

Three lanes:
  fast      CSS, copy and labels, docs, BUILD_ID, comments, and data (JSON under data/, the RANKINGS_CSV block).
            Static + pipeline + smoke checks, then deploy (~2–3 minutes).
  targeted  rendering code of ONE known UI feature, or a test file. The fast checks plus that feature's suites, then
            deploy (~4–7 minutes).
  full      everything risky or unknown: the value model and Architecture C, the editor, league adjustments,
            publishing, history and snapshots, trade logic, scoring and projections, market math, shared helpers, the
            settings script, page markup, pipeline scripts, CI and test infrastructure, two or more features at once,
            and any function not in the map below. The whole suite must pass before deploy (~12–14 minutes).
There's no trailing full run after a fast or targeted release: the full suite also runs nightly and on demand.

What counts as the change. The diff is taken from the newest commit whose code already passed its lane (an Actions cache
entry "verified-<code fingerprint>", tests/release_fingerprint.py), walking back first parents from --start (default
--head) up to 30 commits. So a push that was cancelled by a newer one, or one that failed its checks, is still part of
the next push's diff, and code that never passed can't ride out with a later CSS tweak or rankings publish. No verified
commit within reach → full lane.

How index.html is read. Every changed line is placed by region (the rankings block, CSS, markup, the settings script,
or the top-level JavaScript declaration it belongs to); everything else is placed by its path. Copy and labels: a
changed line counts as copy when it's identical to the line it replaced once visible text is blanked (HTML text between
tags, and quoted strings that start with a capital letter and contain a lowercase one, like "Then" or "At the time").
The map below names which functions belong to which UI feature; a new function nobody mapped gets the full suite.
`--force-full` (the workflow's full_ci input, the full-ci pull request label) or a `CI: full` line in any commit
message of the range forces the full lane.
"""
import argparse, json, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# feature -> (lane, suites, top-level names in index.html's main script)
FULL, TARGETED = "full", "targeted"
RISK = {
 "shared":        (FULL, [], "esc fmt $ parseCSV loadPlayers rebuild showTab teamMeta teamLogo teamStyle teamAccent face nameLink compactName tierLabel tierNameOf isTagTier posLabel dv adjOf leagueView valueLeague syncedLeague toast setTheme tabs currentTab players byId editor LG FMT".split()),
 "value-model":   (FULL, [], "keepRankOrder keepRankOrderBySource autoValues keepOverallOrder valueKey positionCurve localLevel stateValues applyTiers maxValue valueCheck VCHECK formulaPreview modelValue rawValue".split()),
 "editor":        (FULL, [], "writeOrder makeManual overallOrder moveOverall valueAfter sendOut movePlayer valueFit setValue applyValue recalcLevel recalcPlayer recalcAuto editSession storeSession resetEditSession deriveTiers tierNameAfter valueEdited ownEdit pruneTouched pruneRevalued tiersInOrder tierAction shiftTiers materializeTierNames tierNums tierConflict tierMoveNotice splitNotice zeroNotice valueNotice packSession freshSession unpackSession changedRows".split()),
 "publishing":    (FULL, [], "gh ghError redact repoEntry repoBlobText repoSnapshot repoRead commitLanded repoCommit repoWrite repoReadMany repoWriteMany extractRankings replaceRankings validateRankings verifyToken readLocal readBase baseFor applyEdits diffEdits pubState readTouch writeTouch inferTouch touch anchorValue reprice persistEdits saveLocal discardLocal mergeInto conflictError readAt historyUpdate checkPublication readPublish writePublish inFlightEdits adoptPublished settlePending publishLive storedToken storeToken clearToken forgetToken openSignin publishInjOverrides".split()),
 "history":       (FULL, [], "rankingSnapshot normalizeHistory lastOf rankMoved historyChanged kindOf addEntry addSnapshot recordPublish historySummary historyMessage readPending writePending historyWithPending valueEdits recordSave historyText valueAt snapEventAt needSnaps loadSnapMonth histNorm histNow".split()),
 "league-layer":  (FULL, [], "curvesFor replLevels modelParts modelTable scarcityIndex leagueDepth leagueRecalc leagueTeams adjustValues adjMapFor formatSteps formatCheck smoothTiers stickyOrder playerFactors fmtLeague fmtClean fmtFromUrl fmtToUrl setFormat useLeagueSettings trimLeague syncLeague refreshLeague espnToLeague espnScoring parseYahooSettings matchPlayer".split()),
 "trade-logic":   (FULL, [], "tradeModel runModel tcAdjusted rosterContext teamImpact utilScore acceptance acceptFor valueFloor tcMarketModel rationale leagueBalance rostersBeforeTrade histReport evalTrade analyzeTrade findTrades findThree plausibleForThem mlAssess mlTypes findTargets findSells enrichTarget bestLineup evaluateTeams roomWeights playoffOdds tfShapes tfCombos".split()),
 "scoring-proj":  (FULL, [], "gamePoints calculateFantasyPoints scoringNow enteredGame weeklyProjection contextProjection propsProjection weekOutlook projRatios seasonRanks prodData prodMetric prodRanks totals seasonLog shortMap defenseVsPos sleeperPoints".split()),
 "market":        (FULL, [], "loadMarket marketNow mkSources mkWeigh mkAll mkOf flockParse flockNow".split()),
 # UI features: the suites that cover them (kept short on purpose)
 "rankings-ui":   (TARGETED, ["league_hub_check", "production_check", "xss_check"],
                   "renderRankings renderProd renderMkt renderMkBar renderRail valueCell valueCellEdit nflTag nflMark ownPill ownerTag tierTag boardMove boardMoves sinceText rankMove patchRows syncRkControls updateEditorBar renderReview reviewWarnings reviewMarket renderValueCheck renderMarketAudit openReview closeReview".split()),
 "drag-ui":       (TARGETED, ["drag_check", "drag_repeat_check", "drag_scroll_check"],
                   "dragFloat dropNum dragStart dragZone applySlot dragMove dragLoop dragScroll showDrop endDrag commitDrop clearMarks DRAG_STATE drag".split()),
 "drawer-ui":     (TARGETED, ["drawer_check", "xss_check"],
                   "openPlayer closePlayer renderPlayer ppSection ppOverview thisWeekCard ppSchedule ppPractice ppDepth ppGameLog ppStats ppPerformance ppHistory ppTradeValue ppCompare weeklySeries weeksChart barChart lineChart usageGrid prodRankLine statsStamp markCurrent mkDrawer".split()),
 "league-ui":     (TARGETED, ["league_hub_check", "trade_history_check", "xss_check"],
                   "renderLeague powerHtml teamExpand standingsHtml matchupsHtml rostersHtml rostersInner scheduleHtml txHtml txRail moveRow openBids tradeCard tradeHistoryHtml snapText agedText renderMyTeam renderFA strengthCards".split()),
 "finder-ui":     (TARGETED, ["trade_target_check", "market_edge_check"],
                   "renderFinder renderDiscover renderFinderPick tfResults targetCard mlCard shortWhy fullWhy fitBadge".split()),
 "calc-ui":       (TARGETED, ["roster_fit_check", "trade_target_check"],
                   "renderTrade renderTrade3 renderImpact rationaleHtml renderBreakdown formatBreakdown renderBeforeAfter renderHist renderTradeContext renderTcMarket".split()),
}
FN = {n: k for k, (_, _, ns) in RISK.items() for n in ns}
# CI and test infrastructure: a change here changes the gate itself
INFRA = {"tests/run_ci.py", "tests/ci_policy.json", "tests/static_check.py", "tests/smoke_check.py", "tests/ci_pipeline_check.py",
         "tests/release_fingerprint.py", "tests/release_tier.py", "tests/requirements-ci.txt", "tests/gh_mock.py",
         "tests/fixture_board.py", "tests/league_hub_check.py"}   # league_hub_check's header is exec'd by other suites
WALK = 30

def git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, check=True).stdout.decode("utf-8", "replace")

def regions(text):
    """Per line (1-based): region (rankings / css / markup / settings-js / js) and, in a script, the enclosing top-level
    declaration (the main script declares everything at two spaces of indent)."""
    lines = text.split("\n"); reg = ["markup"] * (len(lines) + 2); fn = [None] * (len(lines) + 2)
    for m in re.finditer(r"<(style|script)\b[^>]*>([\s\S]*?)</\1>", text):
        a = text.count("\n", 0, m.start()) + 1; b = text.count("\n", 0, m.end()) + 1
        kind = "css" if m.group(1) == "style" else ("settings-js" if re.search(r"^const VALUE_MODEL = \{", m.group(2), re.M) else "js")
        for i in range(a, b + 1): reg[i] = kind
    m = re.search(r"const RANKINGS_CSV = `\n[\s\S]*?\n`;", text)
    if m:
        a = text.count("\n", 0, m.start()) + 1; b = text.count("\n", 0, m.end()) + 1
        for i in range(a + 1, b): reg[i] = "rankings"   # the data lines only
    decl = re.compile(r"^  (?:async\s+)?(?:function\s*\*?\s*([A-Za-z_$][\w$]*)|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=)")
    cur = None
    for i, l in enumerate(lines, 1):
        if reg[i] != "js": cur = None; continue
        mm = decl.match(l)
        if mm: cur = mm.group(1) or mm.group(2)
        fn[i] = cur
    return lines, reg, fn

COPY_STR = re.compile(r'"[A-Z][^"\\`$<>{}]*[a-z][^"\\`$<>{}]*"')
COPY_HTML = re.compile(r">[^<>{}$`\"']*<")
def visible_blanked(line):
    return COPY_HTML.sub("><", COPY_STR.sub('""', line))

def classify(base, head="HEAD", force=False):
    out = {"base": base, "head": head, "lane": None, "features": [], "suites": [], "reasons": [], "files": []}
    def lane_of(l): return {"fast": 0, "targeted": 1, "full": 2}[l]
    lane = "fast"; suites = set(); reasons = []; features = set()
    def bump(l, why, s=()):
        nonlocal lane
        if lane_of(l) > lane_of(lane): lane = l
        reasons.append(f"{l}: {why}"); suites.update(s)
    if not base:
        out.update(lane="full", reasons=["full: no commit within reach has passed its checks"]); return out
    if force: bump("full", "full CI requested")
    if re.search(r"^CI:\s*full\s*$", git("log", "--format=%B", f"{base}..{head}"), re.M | re.I): bump("full", "a commit asks for full CI (CI: full)")
    files = [f for f in git("diff", "--name-only", base, head).split("\n") if f]
    out["files"] = files
    for f in files:
        if f.startswith("data/") and f.endswith(".json"): reasons.append(f"fast: {f} (data)"); continue
        if f.endswith(".md") or f == ".gitignore": reasons.append(f"fast: {f} (docs)"); continue
        if f.startswith(".github/") or f in INFRA or f.startswith("tests/fixtures/"): bump("full", f"{f} (CI / test infrastructure)"); continue
        if re.fullmatch(r"tests/[a-z_]+_check\.py", f): bump("targeted", f"{f} (test only: its suite runs)", [f[6:-3]]); continue
        if f.startswith("tests/"): bump("full", f"{f} (other test file)"); continue
        if f.startswith("pipeline/"): bump("full", f"{f} (pipeline script)"); continue
        if f != "index.html": bump("full", f"{f} (other site file)"); continue
        try: old = git("show", f"{base}:index.html")
        except subprocess.CalledProcessError: bump("full", "index.html is new"); continue
        new = git("show", f"{head}:index.html")
        Lo, ro, fo = regions(old); Ln, rn, fnn = regions(new)
        keys = set()
        for h in re.finditer(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", git("diff", "-U0", "--no-color", base, head, "--", "index.html"), re.M):
            os_, oc, ns_, nc = int(h[1]), int(h[2] or 1), int(h[3]), int(h[4] or 1)
            pairs = list(zip(range(os_, os_ + oc), range(ns_, ns_ + nc))) if oc == nc else []
            copy = {(i, j) for i, j in pairs if ro[i] == rn[j] and ro[i] in ("js", "markup", "settings-js")
                    and Lo[i - 1] != Ln[j - 1] and visible_blanked(Lo[i - 1]) == visible_blanked(Ln[j - 1])}
            copy_o = {i for i, _ in copy}; copy_n = {j for _, j in copy}
            for side, start, count, L, R, F, skip in (("o", os_, oc, Lo, ro, fo, copy_o), ("n", ns_, nc, Ln, rn, fnn, copy_n)):
                for i in range(start, start + count):
                    r, name, line = R[i], F[i], L[i - 1]; s = line.strip()
                    if i in skip: keys.add(("copy",)); continue
                    if r == "rankings": keys.add(("rankings",))
                    elif r == "css": keys.add(("css",))
                    elif r == "markup": keys.add(("markup",))
                    elif r == "settings-js": keys.add(("settings-js",))
                    elif re.match(r'^const BUILD_ID = "[^"`$\\]*";$', s): keys.add(("build-id",))
                    elif s == "" or (s.startswith("//") and "`" not in s): keys.add(("js-comment",))
                    else: keys.add(("js", name))
        for key in sorted(keys, key=str):
            k = key[0]
            if k == "rankings": reasons.append("fast: RANKINGS_CSV block (data)")
            elif k == "build-id": reasons.append("fast: BUILD_ID")
            elif k == "js-comment": reasons.append("fast: JavaScript comments or blank lines")
            elif k == "copy": reasons.append("fast: copy / labels (only visible text changed)")
            elif k == "css": reasons.append("fast: CSS")
            elif k == "markup": bump("full", "page markup (ids and classes are read across the site)")
            elif k == "settings-js": bump("full", "the settings script (VALUE_MODEL, tradeModel, FORMAT_ADJUST …)")
            else:
                feat = FN.get(key[1])
                if feat is None: bump("full", f"JS {key[1] or 'outside any declaration'} (not in the map)")
                else:
                    l, st, _ = RISK[feat]; features.add(feat); bump(l, f"JS {key[1]} ({feat})", st)
    ui = sorted(x for x in features if RISK[x][0] == TARGETED)
    if len(ui) > 1: bump("full", f"more than one UI feature changed ({', '.join(ui)})")
    out.update(lane=lane, features=sorted(features), reasons=reasons, suites=sorted(suites) if lane == "targeted" else [])
    return out

def ok_base(start, ok_fps, limit=WALK):
    """The newest first-parent ancestor of `start` (itself included) whose code fingerprint passed its checks."""
    from release_fingerprint import fingerprint
    try: revs = git("rev-list", "--first-parent", f"--max-count={limit}", start).split()
    except subprocess.CalledProcessError: return None
    for r in revs:
        try:
            if fingerprint(r) in ok_fps: return r
        except subprocess.CalledProcessError: return None   # history cut off (shallow clone)
    return None

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--head", default="HEAD"); ap.add_argument("--start", default="")
    ap.add_argument("--base", default="", help="compare with this commit directly (skips the verified-commit walk)")
    ap.add_argument("--ok-keys", default="", help="file listing verified-<fingerprint> cache keys, one per line")
    ap.add_argument("--force-full", action="store_true"); ap.add_argument("--json", action="store_true")
    ap.add_argument("--github-output", action="store_true")
    a = ap.parse_args()
    head = git("rev-parse", a.head).strip()
    if a.base: base = a.base
    else:
        keys = open(a.ok_keys).read().split() if a.ok_keys and os.path.exists(a.ok_keys) else []
        base = ok_base(a.start or head, {k[len("verified-"):] for k in keys if k.startswith("verified-")})
    c = classify(base, head, a.force_full)
    if a.github_output and os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"lane={c['lane']}\nsuites={','.join(c['suites'])}\nlane_base={base or ''}\n")
    if a.json: print(json.dumps(c)); sys.exit(0)
    print(f"Lane: {c['lane']}  (changes since {base[:12] if base else 'no verified commit'})")
    for r in c["reasons"]: print("  ", r)
    if c["suites"]: print("   suites:", ", ".join(c["suites"]))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(f"### Release lane: {c['lane']}\n\nChanges since `{base[:12] if base else 'no verified commit'}`.\n\n"
                    + "".join(f"- {r}\n" for r in c["reasons"]) + (f"\nSuites: {', '.join(c['suites'])}\n" if c["suites"] else ""))
