"""How much last season counts in ROS projections (Alan, Oct 13; Kenneth Walker III audit).

Before Oct 13 every opportunity stat blended this season with last season's per-game average at one fixed weight
(K_PRIOR = 2 games), at face value, whether or not the player had changed teams. Now (ros_model.prior_weights) the
weight is estimated per position and stat from two complete seasons (empirical Bayes: per-game noise over
season-to-season change), last season is regressed toward what such a role becomes a year later, and a team change
(a structural break the data can see) makes last season's workload count less. Efficiency keeps its own, slower prior.
No browser; synthetic seasons, plus the repo's 2024 -> 2025 files for the estimated weights.

  A. prior_weights() on synthetic seasons with a known answer: a stat whose role never changes gets a heavy prior, a
     stat that changes a lot a light one; players who changed teams get a lighter prior; red-zone work follows its
     parent stat; weights stay inside KW_BOUNDS.
  B. project_from() on a synthetic Walker: a committee back last season (13 carries, 47% snaps) who changed teams
     and has 4 workhorse games (22 carries, 75% snaps). His projected workload follows the new role more than the old
     model's and more than the same player who stayed on his team; one 3-TD game doesn't move his projected carries;
     his efficiency still carries last season (yards per carry well under his hot 4-game rate); confidence is lower
     than for the same player on his old team; the old fixed weight (K_PRIOR 2) reproduces the old numbers.
  TE: tight ends keep the old weighting (KW_OLD_POS, Alan, Oct 13) until the TE efficiency bias is understood.
  C. The repo's data: the estimated 2024 -> 2025 weights are finite and inside the bounds, RB carries react faster
     than WR targets (the backtest's finding), a team change divides K, the projection code never touches the
     rankings (index.html's RANKINGS_CSV is unchanged by a projection run).

    python3 tests/ros_prior_check.py
"""
import copy, os, sys, hashlib
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import ros_model as m

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

rng = np.random.default_rng(13)
COLS = m.STATS + ["w", "tm", "opp", "snap"]

def season(year, players):
    """players: {sid: (pos, [game dicts])} -> a stats file shaped like data/stats/<season>.json."""
    out = {"season": year, "through_week": 17, "cols": COLS, "players": {}, "short": {}}
    for sid, (pos, games) in players.items():
        out["players"][sid] = {"n": sid, "p": pos, "g": [[g.get(c, 0) for c in COLS] for g in games]}
    return out

def rb_game(w, team, car, tgt, snap, rz=None, td=0, ypc=4.4):
    rz = round(car * 0.15) if rz is None else rz
    return dict(w=w, tm=team, opp="X", rush_att=car, rush_yd=round(car * ypc), rush_td=td, rz_rush=min(rz, car), rec_tgt=tgt,
                rec=round(tgt * 0.75), rec_yd=tgt * 6, snap=snap)

# ---------------------------------------------------------------- A. prior_weights on synthetic seasons
def synth_pair(n=120, stable_sd=0.3, move_sd=3.0, change_sd=3.0):
    """RBs whose true carries change between seasons with sd change_sd (sd move_sd on a new team), targets almost never
    change (sd stable_sd); per-game Poisson noise."""
    p0, p1 = {}, {}
    for i in range(n):
        sid = f"s{i}"; moved = i % 4 == 0
        car0 = rng.uniform(6, 20); tgt0 = rng.uniform(1, 5)
        car1 = max(1.0, car0 + rng.normal(0, move_sd if moved else change_sd)); tgt1 = max(0.3, tgt0 + rng.normal(0, stable_sd))
        t0, t1 = "AAA", ("BBB" if moved else "AAA")
        p0[sid] = ("RB", [rb_game(w, t0, int(rng.poisson(car0)), int(rng.poisson(tgt0)), 0.6) for w in range(1, 17)])
        p1[sid] = ("RB", [rb_game(w, t1, int(rng.poisson(car1)), int(rng.poisson(tgt1)), 0.6) for w in range(1, 17)])
    sc = m.scoring()
    return m.frame(season(2024, p0), sc), m.frame(season(2025, p1), sc)

f0, f1 = synth_pair()
kw = m.prior_weights(f0, f1)
K = kw["K"]["RB"]
ok(K["rec_tgt"] > 2 * K["rush_att"], f"A stat that barely changes year to year gets a heavier prior than one that changes a lot: targets K {K['rec_tgt']:.2f} vs carries K {K['rush_att']:.2f}")
ok(K["rz_rush"] == K["rush_att"] and K["rz_tgt"] == K["rec_tgt"], "Red-zone carries and targets take their parent stat's weight")
ok(all(m.KW_BOUNDS[0] <= v <= m.KW_BOUNDS[1] for v in K.values()), f"Every weight inside {m.KW_BOUNDS} games")
ok(abs(kw["b"]["RB"]["rec_tgt"] - 1) < 0.15 and 0 <= kw["b"]["RB"]["rush_att"] <= 1, f"Regression toward the position: targets b {kw['b']['RB']['rec_tgt']:.2f} (near 1: nothing to regress), carries b {kw['b']['RB']['rush_att']:.2f}")
f0m, f1m = synth_pair(move_sd=7.0)
kwm = m.prior_weights(f0m, f1m)
ok(kwm["move"] > 1.5, f"Players who changed teams (true change sd 7 vs 3 carries) get a lighter prior: K / {kwm['move']:.2f}")
f0s, f1s = synth_pair(move_sd=3.0)
ok(m.prior_weights(f0s, f1s)["move"] < kwm["move"], "...and when changing teams doesn't change roles more, the factor is smaller")

# ---------------------------------------------------------------- B. a synthetic Walker
def walker_seasons(new_team=True, td_game=False, n_others=40, pos="RB"):
    prev, cur = {}, {}
    prev["kw3"] = (pos, [rb_game(w, "SEA", 13, 2, 0.47, rz=2, td=int(w % 4 == 0), ypc=4.6) for w in range(1, 17)])
    team = "KC" if new_team else "SEA"
    games = [rb_game(w, team, c, t, s, rz=r, td=1, ypc=6.2) for w, c, t, s, r in [(1, 23, 6, 0.68, 3), (2, 24, 10, 0.82, 5), (3, 18, 2, 0.73, 7), (4, 22, 1, 0.75, 4)]]
    if td_game: games[3] = dict(games[3], rush_td=4)
    cur["kw3"] = (pos, games)
    for i in range(n_others):   # a background league so league rates exist
        sid = f"o{i}"; c = int(8 + i % 12)
        prev[sid] = (pos, [rb_game(w, "ZZZ", c, 3, 0.55, td=int(w % 3 == 0)) for w in range(1, 17)])
        cur[sid] = (pos, [rb_game(w, "ZZZ", c, 3, 0.55, td=int(w % 3 == 0)) for w in range(1, 5)])
    s0, s1 = season(2025, prev), season(2026, cur); s1["through_week"] = 4
    return s0, s1

def run(s0, s1, params=m.PARAMS, kw_=None):
    sc = m.scoring()
    rates = m.league_rates([m.frame(s0, sc), m.frame(s1, sc)])
    orig = m.team_env; m.team_env = lambda *a, **k: ({}, {})
    try:
        ctx = m.prepare(s1, None, 4, prior_stats=s0, rates=rates, sc=sc, kw=kw_)
        return m.project_from(ctx, params).set_index("sleeper_id").loc["kw3"]
    finally:
        m.team_env = orig

# the weights a live run would use: the repo's two complete seasons
sc = m.scoring()
real = {y: m.frame(m.load_stats(os.path.join(ROOT, "data", "stats", f"{y}.json")), sc) for y in (2024, 2025)}
KW = m.prior_weights(real[2024], real[2025])
s0, s1 = walker_seasons()
old = run(s0, s1, dict(m.PARAMS, K_PRIOR=2.0), KW)
new = run(s0, s1, m.PARAMS, KW)
stay = run(*walker_seasons(new_team=False), m.PARAMS, KW)
nokw = run(s0, s1, m.PARAMS, None)
ok(new.moved and not stay.moved, "A team change is detected from last season's last team vs this season's")
cur_car = (23 + 24 + 18 + 22) / 4
ok(new.line["rush_att"] > old.line["rush_att"], f"New team, workhorse role: projected carries follow the new role more than with the old fixed weight ({old.line['rush_att']:.1f} -> {new.line['rush_att']:.1f}; this season {cur_car:.1f}, last season 13)")
ok(new.line["rush_att"] > stay.line["rush_att"], f"...and more than the same back who stayed on his team ({stay.line['rush_att']:.1f})")
ok(new.line["rush_att"] < cur_car, "...without taking four games at face value")
ok(new.cur_share > 0.75 and new.cur_share > stay.cur_share, f"Share of his projected workload from this season's games: {new.cur_share:.0%} on a new team vs {stay.cur_share:.0%} on his old one")
ok(new.conf < stay.conf, f"Confidence is lower when last season was on another team ({new.conf:.2f} vs {stay.conf:.2f}): that season says less about this one")
td = run(*walker_seasons(td_game=True), m.PARAMS, KW)
ok(abs(td.line["rush_att"] - new.line["rush_att"]) < 1e-9 and abs(td.line["rec_tgt"] - new.line["rec_tgt"]) < 1e-9, "A game with 3 extra touchdowns changes no projected opportunity (carries, targets)")
ok(td.line["rush_td"] - new.line["rush_td"] < 0.25, f"...and moves his projected rushing TDs only a little ({new.line['rush_td']:.2f} -> {td.line['rush_td']:.2f} a game, not 0.75 more)")
ypc = new.line["rush_yd"] / new.line["rush_att"]
ok(4.4 < ypc < 5.6, f"Efficiency keeps its slower prior: projected {ypc:.2f} yards per carry from 6.2 in his four games and 4.6 last season")
ok(abs(nokw.line["rush_att"] - old.line["rush_att"]) < 1e-9, "Without fitted weights the model falls back to the old fixed weight (K_PRIOR_FALLBACK 2)")
g_eff = 4.0
ok(abs(old.line["rush_att"] - (g_eff * cur_car + 2 * 13) / (g_eff + 2)) < 0.05, f"The old path (K_PRIOR 2) reproduces the old blend: {old.line['rush_att']:.2f} carries")

# TEs keep the weighting from before Oct 13 (Alan, Oct 13: KW_OLD_POS, until the TE efficiency bias is understood)
te_s = walker_seasons(pos="TE")
te_new, te_old = run(*te_s, m.PARAMS, KW), run(*te_s, dict(m.PARAMS, K_PRIOR=2.0), KW)
ok("TE" in m.KW_OLD_POS and all(abs(te_new.line[k] - te_old.line[k]) < 1e-9 for k in te_new.line) and abs(te_new.proj_ppg - te_old.proj_ppg) < 1e-9,
   f"A TE who changed teams gets exactly the old projection ({te_old.proj_ppg:.2f} PPG): raw last season, 2 games, no team-change factor")
ok(not te_new.moved and abs(te_new.conf - te_old.conf) < 1e-9, "...his team change isn't reported as counting less, and his confidence is the old one")
te_on = run(*te_s, dict(m.PARAMS, KW_OLD_POS=frozenset()), KW)
ok(te_on.moved and abs(te_on.proj_ppg - te_old.proj_ppg) > 1e-6, "Taking TE out of KW_OLD_POS switches the new weighting back on for TEs")

# ---------------------------------------------------------------- C. the repo's data
Kr = KW["K"]
finite = all(np.isfinite(v) and m.KW_BOUNDS[0] <= v <= m.KW_BOUNDS[1] for d in Kr.values() for v in d.values())
ok(finite, "2024 -> 2025 weights are finite and inside the bounds")
ok(Kr["RB"]["rush_att"] < Kr["WR"]["rec_tgt"], f"RB carries react faster than WR targets (K {Kr['RB']['rush_att']:.2f} vs {Kr['WR']['rec_tgt']:.2f}): RB workload changes stick, WR target swings mostly don't")
ok(1.0 <= KW["move"] <= 6.0 and KW["move"] > 1.2, f"A team change divides K by {KW['move']:.2f}")
ok(0.7 <= KW["lvl"] <= 1.0, f"Players who changed teams keep {KW['lvl']:.0%} of the workload their last season predicts")
idx = os.path.join(ROOT, "index.html")
h0 = hashlib.sha256(open(idx, "rb").read()).hexdigest()
_ = run(s0, s1, m.PARAMS, KW)
ok(hashlib.sha256(open(idx, "rb").read()).hexdigest() == h0, "A projection run never writes index.html (AM ranks, tiers and values are untouched)")

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
