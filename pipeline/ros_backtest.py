"""Backtest for ros_model.py: project from weeks 4, 6, 8 and 10 of 2024 and 2025 and score against what
each player actually averaged in his healthy games over the rest of the fantasy season (weeks cutoff+1..17),
against simple baselines. Opportunity values are fitted on the *other* season, team ratings only on
games through the cutoff and no future betting lines are used, so nothing from after the cutoff leaks in.

    python3 ros_backtest.py <games.csv> [--grid]

Players scored: at least 2 games of evidence before the cutoff and 4 healthy games after it, among the
fantasy-relevant pool (top 32 QB / 50 RB / 70 WR / 24 TE by pre-cutoff healthy PPG). Metrics: mean
absolute error (PPG), and Spearman rank correlation inside each position.
"""
import sys, itertools, json
import numpy as np, pandas as pd
import ros_model as m

SEASONS = [2024, 2025]
CUTOFFS = [4, 6, 8, 10]
POOL = {"QB": 32, "RB": 50, "WR": 70, "TE": 24}

def targets(d, cutoff):
    fut = d[(d.week > cutoff) & (d.week <= m.LAST_WEEK) & (d.f >= 1)]
    t = fut.groupby("id").agg(target=("pts", "mean"), n_after=("pts", "size"))
    return t[t.n_after >= 4]

def baselines(d, cutoff):
    past = d[d.week <= cutoff].sort_values("week")
    g = past.groupby("id")
    last3 = g.apply(lambda s: s.pts.tail(3).mean(), include_groups=False)
    return pd.DataFrame({"season_ppg": g.pts.mean(), "healthy_ppg": past[past.f >= 1].groupby("id").pts.mean(),
                         "last3_ppg": last3})

def old_model(d, ctx_games, cutoff, season):
    """Today's project_players.py, approximately: 0.6 x usage-based xPPG (points per attempt / carry / target
    from totals) + 0.4 x actual PPG, times the team-environment factor with the posted future lines."""
    past = d[d.week <= cutoff]
    s = past.groupby("pos")[["pts", "pass_att", "rush_att", "rec_tgt"]].sum()
    # split points by kind is not in the frame; approximate per-opportunity values from the ridge fit's totals
    ov = m.fit_opportunity_values([past])
    x = sum(past[u] * past.pos.map(lambda p, u=u: ov[p][u]) for u in ("pass_att", "rush_att", "rec_tgt"))
    past = past.assign(x=x)
    g = past.groupby("id").agg(pts=("pts", "sum"), x=("x", "sum"), n=("pts", "size"), team=("team", "last"))
    base = 0.6 * g.x / g.n + 0.4 * g.pts / g.n
    past_imp, ros_imp, _ = m.team_env(ctx_games, season, cutoff, True, m.PARAMS)
    pi = past.assign(imp=[past_imp.get((w, t)) for w, t in zip(past.week, past.team)]).groupby("id").imp.mean()
    env = pd.Series({i: (ros_imp.get(t, np.nan) / pi[i]) ** 0.75 if pi.get(i) else 1.0 for i, t in g.team.items()}).fillna(1)
    return base * env

def spearman(a, b):
    return pd.Series(a).rank().corr(pd.Series(b).rank())

def score(pred, ev):
    """pred: Series by id. ev: eval frame with target, pos. Returns MAE and mean within-position Spearman."""
    j = ev.join(pred.rename("pred"), how="inner").dropna(subset=["pred"])
    mae = (j.pred - j.target).abs().mean()
    rho = np.mean([spearman(s.pred, s.target) for _, s in j.groupby("pos") if len(s) > 5])
    return mae, rho, len(j)

def run(games_path, grid=False):
    games = pd.read_csv(games_path)
    sc = m.scoring()
    stats = {y: m.load_stats(f"../data/stats/{y}.json") for y in SEASONS}
    frames = {y: m.frame(stats[y], sc) for y in SEASONS}
    ov = {y: m.fit_opportunity_values([frames[o] for o in SEASONS if o != y]) for y in SEASONS}
    cases = []
    for y in SEASONS:
        for c in CUTOFFS:
            d = frames[y]
            ctx = m.prepare(stats[y], games, c, ov=ov[y], use_future_lines=False, sc=sc)
            ev = targets(d, c).join(baselines(d, c)).join(d.groupby("id").pos.first())
            ev = ev[ev.index.isin(set(g["sid"] for g in ctx["groups"] if g["f"].sum() >= 2))]
            ev["pool_rank"] = ev.groupby("pos").healthy_ppg.rank(ascending=False)
            ev = ev[ev.pool_rank <= ev.pos.map(POOL)]
            ev["old_model"] = old_model(d, games, c, y)
            cases.append((y, c, ctx, ev))

    def evaluate(params):
        maes, rhos, ns = [], [], []
        for y, c, ctx, ev in cases:
            out = m.project_from(ctx, params).set_index("sleeper_id").proj_ppg
            mae, rho, n = score(out, ev); maes.append(mae); rhos.append(rho); ns.append(n)
        return np.mean(maes), np.mean(rhos), sum(ns)

    print("baselines (mean over 8 season/cutoff cases):")
    for b in ("season_ppg", "healthy_ppg", "last3_ppg", "old_model"):
        r = [score(ev[b], ev) for _, _, _, ev in cases]
        print(f"  {b:12s} MAE {np.mean([x[0] for x in r]):.3f}  rho {np.mean([x[1] for x in r]):.3f}  n {sum(x[2] for x in r)}")
    base_mae, base_rho, n = evaluate(m.PARAMS)
    print(f"ros_model (PARAMS) MAE {base_mae:.3f}  rho {base_rho:.3f}  n {n}")

    if grid:
        space = dict(HALF_LIFE=[3, 5, 8, 100], EFF_K=[60, 120, 240], EFF_W=[0, 0.5, 1.0], ENV_EL=[0, 0.5, 0.75, 1.0],
                     SCHED_EL=[0, 0.5, 1.0], PRIOR_GAMES=[0.5, 1, 2, 3], ACT_W=[0, 0.2, 0.4, 0.6])
        best = dict(m.PARAMS); best_mae = base_mae
        for _ in range(3):   # coordinate descent, three passes
            for k, vals in space.items():
                for v in vals:
                    p = dict(best); p[k] = v
                    mae, rho, _ = evaluate(p)
                    print(f"  {k}={v:<5} MAE {mae:.3f} rho {rho:.3f}")
                    if mae < best_mae - 1e-4: best_mae, best = mae, p
            print("best so far", {k: best[k] for k in space}, round(best_mae, 3))
        mae, rho, _ = evaluate(best)
        print("BEST", json.dumps({k: best[k] for k in space}), f"MAE {mae:.3f} rho {rho:.3f}")
        # per-position breakdown for the best parameters, pooled over cases
        rows = []
        for y, c, ctx, ev in cases:
            out = m.project_from(ctx, best).set_index("sleeper_id").proj_ppg
            j = ev.join(out.rename("pred"), how="inner")
            rows.append(j.assign(season=y, cutoff=c))
        j = pd.concat(rows)
        for pos, s in j.groupby("pos"):
            print(f"  {pos}: n {len(s)}  model MAE {(s.pred-s.target).abs().mean():.2f}  healthy {(s.healthy_ppg-s.target).abs().mean():.2f}"
                  f"  season {(s.season_ppg-s.target).abs().mean():.2f}  last3 {(s.last3_ppg-s.target).abs().mean():.2f}  old {(s.old_model-s.target).abs().mean():.2f}")
        for c, s in j.groupby("cutoff"):
            print(f"  week {c}: n {len(s)}  model MAE {(s.pred-s.target).abs().mean():.2f}  healthy {(s.healthy_ppg-s.target).abs().mean():.2f}  old {(s.old_model-s.target).abs().mean():.2f}")

if __name__ == "__main__":
    run(sys.argv[1], grid="--grid" in sys.argv)
