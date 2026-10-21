"""Score the stored pre-game projections (data/projections/<season>/wk*.json) against what happened, so every change to
the weekly, Next 4 and ROS forecasts is measured on results that weren't used to build it.

    python3 eval_projections.py [../data/stats/2026.json] [../data/projections] [--from WEEK] [--c5 injuries.csv]

Metrics (Alan, Oct 21): RMSE is the primary accuracy measure (a projection is an expected value), MAE and the
within-week rank correlation (Spearman, per week and position) are guardrails, bias = mean(forecast - actual). Each is
printed overall and by position.

Forecasts scored, each beside the baseline it replaced (both stored before the games by snapshot_projections.py):
  next game   n1 = the site's weekly projection from Oct 21 (the model's line x that game's market and matchup)
              n1_legacy = the site's weekly projection before Oct 21 (ROS PPG x the browser's own Vegas and matchup)
              plus the model's components (base alone, + market, + matchup) for weeks stored before then
              targets: full games he played (conditional), and everyone with a stored role (expected; 0 when he didn't play)
  next 4      n4 (no market or matchup, faster line after a snap-share jump) vs n4_legacy (market^0.5 x matchup^0.25)
              target: his healthy PPG over those four weeks, at least 3 games
  ROS         ros vs base alone; target: healthy PPG over the rest of the season so far, at least 3 games
Injury-shortened games are left out of the conditional targets (the forecast is for a full game). Pool: players with a
stored ROS forecast of at least 5 PPG. The ten biggest next-game misses are listed so they can be read, not just counted.

--c5 runs the pre-registered prospective test of the teammate-absence adjustment (reports/projection-audit-2026-10-21/
c5-prospective.md in the project files): it is computed from the stored lines and that week's final injury report
(nflverse injuries_<season>.csv) with parameters frozen on Oct 21, and is never part of the site's projection.
"""
import json, os, sys, glob
import numpy as np, pandas as pd
import ros_model as m
import roles

# C5, frozen Oct 21 before any week it is tested on (c5-prospective.md): share of a ruled-out teammate's projected
# targets (non-QBs) and carries (RBs) that goes to the teammates who play, split by their own projected shares
C5_RT, C5_RC = 0.25, 0.5
C5_FROM_WEEK = 7

def spearman(a, b):
    return pd.Series(a).rank().corr(pd.Series(b).rank())

def metrics(j, pred, truth):
    e = j[pred] - j[truth]
    rho = [spearman(s[pred], s[truth]) for _, s in j.groupby(["week", "pos"]) if len(s) > 5]
    return dict(rmse=float(np.sqrt((e ** 2).mean())), mae=float(e.abs().mean()), bias=float(e.mean()),
                rho=float(np.mean(rho)) if rho else float("nan"), n=len(j))

def line_txt(label, r):
    return f"  {label:38s} RMSE {r['rmse']:.3f}  MAE {r['mae']:.3f}  bias {r['bias']:+.2f}  rho {r['rho']:.3f}  n {r['n']}"

def report(d, preds, truth, title, by_pos=True):
    """preds = [(column, label)]; scored on the rows where every forecast and the target exist (a fair comparison)."""
    cols = [p for p, _ in preds if p in d and d[p].notna().any()]
    if not cols: return
    j = d.dropna(subset=[truth] + cols)
    if len(j) < 20: return
    print(title)
    for p, label in preds:
        if p in cols: print(line_txt(label, metrics(j, p, truth)))
    if by_pos and len(cols) >= 1:
        for pos, s in j.groupby("pos"):
            if len(s) < 20: continue
            print(f"    {pos}: " + "  |  ".join(f"{p} RMSE {metrics(s, p, truth)['rmse']:.3f} MAE {metrics(s, p, truth)['mae']:.3f}" for p in cols))

def gsis_map(players_path):
    try: sp = json.load(open(players_path))
    except (OSError, ValueError): return {}
    sp = sp.get("players", sp)
    return {v[3]: sid for sid, v in sp.items() if isinstance(v, list) and len(v) > 3 and v[3]}

def c5_adjust(snap, rep, played_before):
    """sid -> C5-adjusted conditional next-game forecast. rep: sid -> (report_status, practice_status) from the final
    report; played_before: sids who played their team's previous game (only a new absence moves opportunity: one that
    started earlier is already in his teammates' recent usage, so it isn't counted twice)."""
    sc = m.scoring(); rows = []
    for sid, p in snap["players"].items():
        l = p.get("line") or {}
        if not l: continue
        a = roles.availability(*rep[sid]) if sid in rep else 1.0
        tgt, car = l.get("rec_tgt", 0) or 0, l.get("rush_att", 0) or 0
        te = sc.get("bonus_rec_te", 0) if p["pos"] == "TE" else 0
        recp = (sc["rec"] + te) * l.get("rec", 0) + sc["rec_yd"] * l.get("rec_yd", 0) + sc["rec_td"] * l.get("rec_td", 0)
        rushp = sc["rush_yd"] * l.get("rush_yd", 0) + sc["rush_td"] * l.get("rush_td", 0)
        scale = p["n1"] / p["base"] if p.get("base", 0) > 0.1 else 1.0
        rows.append(dict(sid=sid, team=p["team"], pos=p["pos"], a=a, tgt=tgt, car=car, n1=p["n1"], scale=scale,
                         ppt=recp / tgt if tgt > 0.05 else 0.0, ppc=rushp / car if car > 0.05 else 0.0, new=sid in played_before))
    t = pd.DataFrame(rows)
    if t.empty: return {}
    t["adj"] = t.n1
    for _, g in t.groupby("team"):
        gone = (1 - g.a) * g.new
        vt = float((gone * g.tgt)[g.pos != "QB"].sum()); vc = float((gone * g.car)[g.pos == "RB"].sum())
        play = g[(g.a >= 0.5) & (g.pos != "QB")]
        if vt > 0 and play.tgt.sum() > 0:
            t.loc[play.index, "adj"] += C5_RT * vt * play.tgt / play.tgt.sum() * play.ppt * play.scale
        prb = g[(g.a >= 0.5) & (g.pos == "RB")]
        if vc > 0 and prb.car.sum() > 0:
            t.loc[prb.index, "adj"] += C5_RC * vc * prb.car / prb.car.sum() * prb.ppc * prb.scale
    return dict(zip(t.sid, t.adj))

def main(stats_path="../data/stats/2026.json", proj_dir="../data/projections", from_week=None, c5=None):
    stats = json.load(open(stats_path)); sc = m.scoring(); through = stats["through_week"]
    fr = m.frame(stats, sc); act = fr[fr.f >= 1][["id", "week", "pts"]]
    act_any = fr[["id", "week", "pts"]]
    files = sorted(glob.glob(os.path.join(proj_dir, str(stats["season"]), "wk*.json")))
    if not files: print("no stored forecasts yet"); return
    inj = None
    if c5:
        ids = gsis_map(os.path.join(os.path.dirname(stats_path), "..", "sleeper_players.json"))
        i = pd.read_csv(c5, low_memory=False)
        if "game_type" in i: i = i[i.game_type == "REG"]
        i["sid"] = i.gsis_id.map(ids)
        inj = i.dropna(subset=["sid"])
    rows = []
    for fn in files:
        snap = json.load(open(fn)); wk = snap["week"]
        if wk > through or (from_week and wk < from_week): continue
        a1 = act[act.week == wk].set_index("id").pts
        a1_any = act_any[act_any.week == wk].groupby("id").pts.sum()   # any game he played, cut short or not
        a4 = act[(act.week >= wk) & (act.week < wk + m.NEXT_N)].groupby("id").pts.agg(["mean", "size"])
        aros = act[act.week >= wk].groupby("id").pts.agg(["mean", "size"])
        adj = {}
        if inj is not None and wk >= C5_FROM_WEEK:
            w = inj[inj.week == wk]
            rep = {r.sid: (r.report_status if isinstance(r.report_status, str) else None, r.practice_status if isinstance(r.practice_status, str) else None)
                   for r in w.itertuples()}
            past = fr[fr.week < wk]   # played his team's latest game before this week: an absence that starts now
            team_last = past.groupby("team").week.max(); last = past.sort_values("week").groupby("id").tail(1)
            before = {r.id for r in last.itertuples() if team_last.get(r.team) == r.week}
            adj = c5_adjust(snap, rep, before)
        for sid, p in snap["players"].items():
            if p["ros"] < 5: continue
            rows.append(dict(week=wk, sid=sid, pos=p["pos"], team=p["team"], conf=p["conf"], ros=p["ros"], n4=p["n4"], n1=p["n1"],
                             n1_legacy=p.get("n1_legacy"), n4_legacy=p.get("n4_legacy"),
                             v_base=p["base"], v_market=p["base"] * p["env1"], v_matchup=p["base"] * p["sched1"],
                             c5=adj.get(sid) if adj else None,
                             act1=a1.get(sid), act4=a4["mean"].get(sid) if a4["size"].get(sid, 0) >= 3 else None,
                             actros=aros["mean"].get(sid) if aros["size"].get(sid, 0) >= 3 else None,
                             # role layer (stored from Oct 12): the expected forecast against what he scored, 0 when he didn't play
                             n1_exp=p.get("n1_exp"), role=p.get("role"),
                             act1_dnp0=float(a1_any.get(sid, 0.0)) if "n1_exp" in p else None))
    if not rows: print(f"no stored week has been played yet (stats through week {through})"); return
    d = pd.DataFrame(rows)
    d["n1_legacy_exp"] = d.n1_legacy * d.role
    print(f"stored weeks scored: {sorted(d.week.unique().tolist())} (stats through week {through}); RMSE primary, MAE and rho guardrails")
    report(d, [("n1", "weekly from Oct 21 (n1)"), ("n1_legacy", "weekly before Oct 21 (baseline)")], "act1", "next game, full games he played:")
    report(d, [("v_base", "model line alone"), ("v_market", "line + team market"), ("v_matchup", "line + matchup"), ("n1", "line + both (n1)")],
           "act1", "next game, model components:", by_pos=False)
    report(d, [("n1_exp", "expected weekly from Oct 21 (n1 x role)"), ("n1_legacy_exp", "expected weekly before Oct 21")],
           "act1_dnp0", "next game, everyone with a stored role (didn't play = 0):")
    report(d, [("n4", "Next 4 from Oct 21"), ("n4_legacy", "Next 4 before Oct 21 (baseline)")], "act4", "next 4:")
    report(d, [("ros", "ROS forecast"), ("v_base", "model line alone")], "actros", "rest of season so far:", by_pos=False)
    if d.c5.notna().any():
        report(d, [("n1", "n1 (as shipped)"), ("c5", "n1 + C5 teammate absences")], "act1", "C5 prospective test (c5-prospective.md), full games:")
        moved = d[(d.c5 - d.n1).abs() > 0.05]
        if len(moved) >= 20: report(moved, [("n1", "n1, affected rows"), ("c5", "C5, affected rows")], "act1", "C5, rows it changes:", by_pos=False)
    j = d.dropna(subset=["act1"]).assign(err=lambda x: x.n1 - x.act1)
    if len(j):
        print("biggest next-game misses (n1 - actual):")
        for r in j.reindex(j.err.abs().sort_values(ascending=False).index).head(10).itertuples():
            name = (stats["players"].get(r.sid) or {}).get("n", r.sid)
            print(f"  wk {r.week} {r.pos} {name} {r.team}: forecast {r.n1:.1f}, scored {r.act1:.1f} ({r.err:+.1f})")
    print("by confidence (next game, n1):")
    for lo, hi, lab in ((0, 0.4, "low"), (0.4, 0.7, "moderate"), (0.7, 1.01, "high")):
        s = j[(j.conf >= lo) & (j.conf < hi)]
        if len(s) >= 20: print(f"  {lab:10s} RMSE {np.sqrt((s.err ** 2).mean()):.2f}  MAE {s.err.abs().mean():.2f}  n {len(s)}")
    return d

if __name__ == "__main__":
    a = sys.argv[1:]; kw = {}
    if "--from" in a: i = a.index("--from"); kw["from_week"] = int(a[i + 1]); del a[i:i + 2]
    if "--c5" in a: i = a.index("--c5"); kw["c5"] = a[i + 1]; del a[i:i + 2]
    main(*a, **kw)
