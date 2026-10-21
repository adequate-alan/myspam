"""Projection changes from the Oct 21 accuracy audit (Alan's approval; reports/projection-audit-2026-10-21/ in the
project files). No browser: synthetic seasons and files, plus a projection run that must leave index.html alone.

  A. Next 4 role change: a WR whose snap share jumps 15+ points in his last two games gets a faster-updating Next 4
     line (more targets than his ROS line); a steady WR and every QB don't; ROS PPG and the next-game forecast are
     identical with or without the rule.
  B. Next 4 has no market or matchup factor (ENV4_EL / SCHED4_EL 0); the next game keeps them (ENV1_EL 0.5 /
     SCHED1_EL 0.25); LEGACY_N4 restores the old Next 4.
  C. Injury-report play chances refit on 2023-25 final reports: Doubtful 4%, Questionable 98 / 68 / 50 after a
     full / limited / no practice, 75% without practice data; last week's designations (CARRY) unchanged.
  D. Stored pregame forecasts (snapshot_projections.py): nothing stored while a game of `through_week` is unplayed (the
     Oct 10 Week 6 file was made after only Thursday's game); a stored week is replaced by a later run before its first
     kickoff and never after; each record keeps the old weekly (n1_legacy) and Next 4 (n4_legacy) baselines.
  E. data/projections.json (merge_projections.write_json): board players under the board's Sleeper ID, every other
     projected player too; `f` carries the next game's market, matchup and week; `line4` only after a role change.

    python3 tests/projection_check.py
"""
import csv, datetime, hashlib, json, os, sys, tempfile
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import ros_model as m, roles, snapshot_projections as snapmod, merge_projections as mp

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

COLS = m.STATS + ["w", "tm", "opp", "snap"]
def season(year, players, through=17):
    out = {"season": year, "through_week": through, "cols": COLS, "players": {}, "short": {}}
    for sid, (pos, games) in players.items():
        out["players"][sid] = {"n": sid, "p": pos, "g": [[g.get(c, 0) for c in COLS] for g in games]}
    return out

def wr_game(w, tgt, snap, team="AAA"):
    return dict(w=w, tm=team, opp="X", rec_tgt=tgt, rec=round(tgt * 0.65), rec_yd=tgt * 8, rz_tgt=round(tgt * 0.12), snap=snap)

def qb_game(w, snap):
    return dict(w=w, tm="AAA", opp="X", pass_att=34, pass_cmp=22, pass_yd=240, pass_td=2, rush_att=4, rush_yd=18, snap=snap)

# ---------------------------------------------------------------- A / B. the model
def seasons():
    prev, cur = {}, {}
    prev["jump"] = ("WR", [wr_game(w, 3, 0.4) for w in range(1, 17)])
    cur["jump"] = ("WR", [wr_game(w, t, s) for w, t, s in [(1, 3, 0.38), (2, 3, 0.4), (3, 4, 0.42), (4, 3, 0.4), (5, 9, 0.8), (6, 10, 0.85)]])
    prev["steady"] = ("WR", [wr_game(w, 7, 0.8) for w in range(1, 17)])
    cur["steady"] = ("WR", [wr_game(w, 7, 0.8) for w in range(1, 7)])
    prev["qb"] = ("QB", [qb_game(w, 1.0) for w in range(1, 17)])
    cur["qb"] = ("QB", [qb_game(w, s) for w, s in [(1, 0.2), (2, 0.2), (3, 0.2), (4, 0.2), (5, 1.0), (6, 1.0)]])
    for i in range(40):   # a background league so league rates exist
        prev[f"o{i}"] = ("WR", [wr_game(w, 4 + i % 6, 0.6, "ZZZ") for w in range(1, 17)])
        cur[f"o{i}"] = ("WR", [wr_game(w, 4 + i % 6, 0.6, "ZZZ") for w in range(1, 7)])
        prev[f"q{i}"] = ("QB", [qb_game(w, 1.0) | {"tm": "ZZZ"} for w in range(1, 17)])
        cur[f"q{i}"] = ("QB", [qb_game(w, 1.0) | {"tm": "ZZZ"} for w in range(1, 7)])
    return season(2025, prev), season(2026, cur, 6)

def run(params):
    s0, s1 = seasons(); sc = m.scoring()
    rates = m.league_rates([m.frame(s0, sc), m.frame(s1, sc)])
    orig = m.team_env; m.team_env = lambda *a, **k: ({}, {})
    try:
        return m.project_from(m.prepare(s1, None, 6, prior_stats=s0, rates=rates, sc=sc), params).set_index("sleeper_id")
    finally:
        m.team_env = orig

new, off = run(m.PARAMS), run(dict(m.PARAMS, ROLE_JUMP=None))
j, st, qb = new.loc["jump"], new.loc["steady"], new.loc["qb"]
ok(m.snap_jump({"snap": np.array([0.38, 0.4, 0.42, 0.4, 0.8, 0.85])}) > 0.4 and m.snap_jump({"snap": np.array([0.8, 0.9])}) == 0.0,
   "snap_jump: last two games vs the earlier ones; nothing with fewer than three games")
ok(bool(j.role_change) and j.line4 is not None and j.line4["rec_tgt"] > j.line["rec_tgt"],
   f"A WR whose snap share jumped (40% -> 80%+) gets a faster Next 4 line: {j.line['rec_tgt']:.1f} -> {j.line4['rec_tgt']:.1f} targets a game")
ok(j.n4_ppg > j.base_ppg, f"...so his Next 4 ({j.n4_ppg:.1f}) sits above his ROS line ({j.base_ppg:.1f})")
ok(not st.role_change and st.line4 is None and abs(st.n4_ppg - st.base_ppg) < 1e-9, "A steady WR: no role change, Next 4 = his line (no market or matchup factor)")
ok(not qb.role_change, "A quarterback is never flagged (a relief-to-starter jump is the role layer's job, roles.py)")
same = all(abs(new.loc[s, c] - off.loc[s, c]) < 1e-9 for s in new.index for c in ("proj_ppg", "n1_ppg", "base_ppg", "conf"))
ok(same, "ROS PPG, the next-game forecast, base line and confidence are identical with or without the role-change rule")
ok(m.PARAMS["ENV4_EL"] == 0 and m.PARAMS["SCHED4_EL"] == 0 and m.PARAMS["ENV1_EL"] == 0.5 and m.PARAMS["SCHED1_EL"] == 0.25,
   "Next 4: no market or matchup factor; next game: market 0.5, matchup 0.25")
ok(m.PARAMS["ENV_EL"] == 0 and m.PARAMS["SCHED_EL"] == 0.25 and m.PARAMS["HALF_LIFE"] == 20.0, "ROS settings unchanged (environment off, schedule 0.25, half-life 20)")
leg = run(dict(m.PARAMS, **m.LEGACY_N4)).loc["jump"]
ok(not leg.role_change and abs(leg.n4_ppg - leg.base_ppg * leg.env4_raw ** 0.5 * leg.sched4_raw ** 0.25) < 1e-9,
   "LEGACY_N4 reproduces the old Next 4: ROS line x market^0.5 x matchup^0.25")

# ---------------------------------------------------------------- C. availability
A = roles.availability
ok((A("Doubtful"), A("Questionable", "FP"), A("Questionable", "LP"), A("Questionable", "DNP"), A("Questionable")) == (0.04, 0.98, 0.68, 0.5, 0.75),
   "Play chances: Doubtful 4%, Questionable 98 / 68 / 50 by Friday practice, 75% without practice data")
ok(A(None) == 1.0 and A("Out") == 0 and A("IR") == 0, "No designation 100%, Out and IR 0")
ok(roles.CARRY == {"Questionable": 0.85, "Doubtful": 0.5, "Out": 0.3, "IR": 0.0}, "Last week's designations (before this week's report) keep their values")

# ---------------------------------------------------------------- D. stored pregame forecasts
UTC = datetime.timezone.utc
def stats_file(d, wk6_final=True):
    sc_cols = ["w", "opp", "home", "date", "pf", "pa", "time", "spread", "total", "roof", "stadium"]
    sched = {"AAA": [[6, "BBB", 1, "2026-10-15", 24 if wk6_final else None, 17 if wk6_final else None, "20:15", -3.0, 47.5, "", ""],
                     [7, "CCC", 0, "2026-10-22", None, None, "20:15", -6.5, 49.0, "", ""],
                     [8, "DDD", 1, "2026-10-29", None, None, "13:00", 2.5, 41.0, "", ""]],
             "BBB": [[6, "AAA", 0, "2026-10-15", 17 if wk6_final else None, 24 if wk6_final else None, "20:15", 3.0, 47.5, "", ""],
                     [7, "DDD", 1, "2026-10-25", None, None, "13:00", 1.0, 44.0, "", ""],
                     [8, "CCC", 0, "2026-11-01", None, None, "13:00", 0.0, 45.0, "", ""]]}
    s = {"season": 2026, "through_week": 6, "cols": COLS, "schedule_cols": sc_cols, "schedule": sched, "short": {},
         "players": {"w1": {"n": "w1", "p": "WR", "g": [[wr_game(w, 7, 0.8).get(c, 0) for c in COLS] for w in range(1, 7)]}}}
    p = os.path.join(d, "stats.json"); json.dump(s, open(p, "w")); return p

def proj_file(d, ros=14.0):
    row = dict(sleeper_id="w1", player="W One", pos="WR", team="AAA", games=6, g_eff=6, prior_g=16, ppg=13, healthy_ppg=13.5, base_ppg=13.2,
               env=1, sched=1.01, env4=1, sched4=1, env1=1.04, sched1=0.98, proj_ppg=ros, n4_ppg=13.2, n1_ppg=13.45, conf=0.8, rank_score=12,
               proj_rank=20, line_json=json.dumps({"rec_tgt": 7, "rec": 4.6, "rec_yd": 56, "rec_td": 0.4}), cur_share=0.6, moved=False,
               role_change=False, line4_json="", env4_raw=1.05, sched4_raw=0.97, n1_week=7)
    p = os.path.join(d, "projections.csv"); pd.DataFrame([row]).to_csv(p, index=False); return p

with tempfile.TemporaryDirectory() as d:
    out = os.path.join(d, "out"); os.makedirs(out)
    wk7 = os.path.join(out, "2026", "wk07.json")
    snapmod.main(proj_file(d), stats_file(d, wk6_final=False), out, now=datetime.datetime(2026, 10, 16, 3, tzinfo=UTC))
    ok(not os.path.exists(wk7), "A week still being played (through_week counts a Thursday game): no forecast stored")
    sp = stats_file(d)
    snapmod.main(proj_file(d), sp, out, now=datetime.datetime(2026, 10, 20, 18, tzinfo=UTC))
    r = json.load(open(wk7))
    ok(os.path.exists(wk7) and r["model"] == "ros-v4" and r["kickoff"] == "2026-10-23T00:15Z", "Every Week 6 game final: Week 7 stored, with its first kickoff (Thursday 8:15 PM ET)")
    p = r["players"]["w1"]
    ok(abs(p["n4_legacy"] - round(13.2 * 1.05 ** 0.5 * 0.97 ** 0.25, 2)) < 1e-9, f"The old Next 4 is stored beside the new one ({p['n4_legacy']} vs {p['n4']})")
    env = max(0.85, min(1.15, ((49.0 / 2 + 6.5 / 2) / np.mean([49.0 / 2 + 6.5 / 2, 41.0 / 2 - 2.5 / 2])) ** 0.75))
    ok(p["n1_legacy"] is not None and abs(p["n1_legacy"] - round(14.0 * env * 1.0, 2)) < 0.011,
       f"The old weekly projection (ROS PPG x the browser's Vegas x matchup) is stored as a baseline: {p['n1_legacy']}")
    snapmod.main(proj_file(d, ros=15.0), sp, out, now=datetime.datetime(2026, 10, 22, 12, tzinfo=UTC))
    ok(json.load(open(wk7))["players"]["w1"]["ros"] == 15.0, "A later run before the first kickoff replaces it (the latest pregame forecast is scored)")
    snapmod.main(proj_file(d, ros=16.0), sp, out, now=datetime.datetime(2026, 10, 23, 1, tzinfo=UTC))
    ok(json.load(open(wk7))["players"]["w1"]["ros"] == 15.0, "From the first kickoff on, the stored forecast is never rewritten")

# ---------------------------------------------------------------- E. data/projections.json
with tempfile.TemporaryDirectory() as d:
    site = os.path.join(d, "index.html")
    open(site, "w").write("const RANKINGS_CSV = `\nplayer,pos,team,rank,pos_rank,tier,value,proj_ppg,games,proj_score,sleeper_id,source\n"
                          "W One,WR,AAA,1,WR1,1,5000,,,,b1,manual\nNobody Projected,TE,BBB,2,TE1,1,4000,,,,b2,manual\n`;\n")
    pp = proj_file(d)
    df = pd.read_csv(pp, dtype={"sleeper_id": str})
    extra = df.iloc[0].copy(); extra["sleeper_id"], extra["player"], extra["pos"] = "q9", "Backup Quarterback", "QB"
    hot = df.iloc[0].copy(); hot["sleeper_id"], hot["player"], hot["role_change"], hot["line4_json"] = "h7", "Hot Receiver", True, json.dumps({"rec_tgt": 9.5, "rec": 6.2})
    pd.concat([df, extra.to_frame().T, hot.to_frame().T]).to_csv(pp, index=False)
    js = os.path.join(d, "projections.json")
    missing = mp.write_json(site, js, pp)
    o = json.load(open(js))
    ok("b1" in o["ppg"] and "w1" not in o["ppg"], "A board player matched by name is written under the board's Sleeper ID")
    ok("q9" in o["ppg"] and "h7" in o["ppg"], "Projected players who aren't on the board are written too (a backup QB keeps his own line)")
    ok(missing == ["TE Nobody Projected"], "Board players without a projection are still reported")
    ok(len(o["f"]["b1"]) == 14 and o["f"]["b1"][11:] == [1.04, 0.98, 7], "f ends with the next game's market factor, matchup factor and week")
    ok(list(o["line4"]) == ["h7"] and o["line4"]["h7"]["rec_tgt"] == 9.5, "line4 only for the player with a role change")

idx = os.path.join(ROOT, "index.html")
h0 = hashlib.sha256(open(idx, "rb").read()).hexdigest()
_ = run(m.PARAMS)
ok(hashlib.sha256(open(idx, "rb").read()).hexdigest() == h0, "A projection run never writes index.html (AM ranks, tiers and values are untouched)")

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
