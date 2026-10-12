# Rankings stat columns: sources, definitions, coverage

Alan, Oct 12, 2026. The Rankings board's **Week** menu (Week N and **Season stats**) shows production and
opportunity side by side. This page records what each column means, where it comes from and what it can't do.
None of it touches AM ranks, tiers, values, league adjustments, ROS projections or fantasy scoring.

## How every number is built

- **One game** = his nflverse stat line for that week plus his team's totals that week (`team_week` in
  `data/stats/<season>.json`, written by `pipeline/build_stats.py`).
- **Season stats** = the same components summed over the games he played (a stat line or offensive snaps:
  `enteredGame`). Byes, DNPs and games he never entered are not games. Projections never enter a total.
- **Shares** are summed numerator ÷ summed denominator over his games, **never an average of weekly
  percentages**. Each week uses the team he played for that week, so a mid-season trade is handled.
- **Missing data shows N/A**, never 0 and never another measure in its place.
- Fantasy points and xFP are scored in the browser with the selected league's scoring (`gamePoints`).

## Available

| Column | Definition | Source | Notes |
|---|---|---|---|
| FPTS | Fantasy points in this league's scoring | nflverse weekly player stats | Unchanged |
| TGT | Targets | nflverse | |
| TGT% | His targets ÷ his team's targets | nflverse | Team targets = targets credited to every player on the team that week; equals nflverse's own `target_share` week by week (checked on every 2026 row) |
| REC, REC YDS, REC TD | Receptions, receiving yards, receiving TDs | nflverse | |
| AY | Air yards on his targets | nflverse `receiving_air_yards` | |
| AY% | His air yards ÷ air yards on all the team's targeted passes | nflverse | Same population as TGT%. nflverse's `air_yards_share` divides by all passing air yards incl. throwaways, so it can read a little lower than ours |
| ATT | Carries, as in the official stats | nflverse `carries` | Includes scrambles and kneel-downs |
| RUSH YDS, RUSH TD | Rushing yards, rushing TDs | nflverse | |
| RUSH% | His carries ÷ team carries | nflverse + play-by-play | **QB kneel-downs left out of both sides**; scrambles count as carries on both sides |
| RZ | Carries + receptions inside the opponent's 20 | nflverse play-by-play | Two-point tries excluded |
| PASS ATT, CMP, CMP%, PASS YDS, PASS TD, INT | Passing line; CMP% = completions ÷ attempts | nflverse | |
| SNAPS | Offensive snaps | nflverse snap counts (Pro Football Reference) | |
| SNAP% | His offensive snaps ÷ team offensive snaps | nflverse snap counts | Team snaps solved from PFR's own shares (see below) |
| TOUCH | Carries + receptions | nflverse | Ball actually in his hands |
| OPP | Carries + targets | nflverse | Caught or not |
| xFP | Expected fantasy points | ffverse **ffopportunity** (MIT), built on nflverse play-by-play | See below |
| TD, SCRIM | Total TDs; rushing + receiving yards | nflverse | Kept from the first Week view |

Coverage, 2026 through Week 5: 1,659 games played by QB/RB/WR/TE with a Sleeper ID. Team totals 1,659 (100%),
snap counts 1,654 (5 missing: players without a PFR ID match; they read N/A), expected points 1,515 of the 1,515
games with a target, carry or pass attempt.

### Team offensive snaps (verified after Alan's review, Oct 12)

PFR's snap counts have one row per player (offensive snaps and `offense_pct`, his share rounded to two decimals) and
no team row. The first version took the most snaps any player played as the team total. Checked against every
regular-season team-game in 2024–26 (1,244): that equals the total implied by the shares in 1,239; in the other five
nobody played every snap and it was 1–2 low (BAL 2025 Wk 4 54 → 55, MIA 2025 Wk 6 57 → 59, SF 2025 Wk 11 53 → 55,
DEN 2026 Wk 4 65 → 66, DET 2024 Wk 2 85 → 86), which inflated those teams' SNAP% by 2–3%. Now the team total
(`team_snaps` in `pipeline/build_stats.py`) is the smallest whole number, at least the most any player took, that
every player's published share agrees with; 1,241 of 1,244 have exactly one such number, and in three 2024 games where
a few PFR rows contradict each other the number most shares agree with is used. It's PFR's own team total, not an
estimate from another measure.

### xFP (the "Weighted Opportunity" request)

Alan asked for Weighted Opportunity only if the data supports a defensible expected-points model. It does:
ffopportunity publishes, for every target, carry and pass attempt, the **expected** catch, yards, first down,
touchdown and interception from a model trained on nflverse play-by-play (down, distance, field position, air
yards, …). We keep that expected stat line (`data/opportunity/<season>.json`, `pipeline/build_opportunity.py`) and
score it with the league's own scoring, so PPR level, TE premium and first-down scoring apply exactly as they do to
real points. Targets, carries and attempts are his real counts. Left out: fumbles and sacks (no expected value in
the source) and yardage bonuses (not applied to expected yards). It is not a hand-weighted count, and **not a projection**: it describes opportunities he already had. FPTS above xFP
= he scored more than that opportunity usually brings.

The data lags the stats by a day or so after games; until it catches up the new week reads N/A and the count line
says "xFP through Week N".

## Not available

| Column | Why |
|---|---|
| RR (routes run) | No free, documented source. nflverse's participation data names only the targeted receiver's route; route counts come from paid charting (PFF and similar). |
| RR% (route participation) | Needs routes run. Snap share or pass-play snaps would be a different measure, so it isn't substituted. |
| YPRR | Needs routes run. |

They're listed, disabled, in the Columns menu so the gap is visible. Possible paths (each needs Alan's call):
a paid charting feed with a key held as a repository secret in a pipeline job, or a clearly labeled proxy such as
"pass-play snaps" built from participation data (only exists for past seasons; nflverse doesn't publish 2026 yet).
