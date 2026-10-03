# CLAUDE.md: SPAM project handoff

Read this file first. It's the context an AI assistant (or a new developer) needs to keep building SPAM without undoing decisions that were already made. `README.md` has the feature-by-feature reference; this file has the **why**, the **rules**, and the **workflow**.

Owners: **Steven** (GitHub `stevenp36`, repo owner) and **Alan** (co-ranker, collaborator). Both edit the rankings; both may work on the code from their own Claude accounts. Keep this file current: when you make a product decision, add it here in the same commit.

**Git workflow (agreed Oct 3, 2026):** Steven (`stevenp36`) and Alan (`adequate-alan`) **both push straight to `main`**; there's no branch/PR step. Every push to `main` redeploys the live site, so: `git pull --rebase` right before you start and again right before you push, keep commits small and focused, test locally first, and never force-push. If a rebase conflicts in `index.html`, resolve it by keeping both people's changes; never resolve a `RANKINGS_CSV` conflict by taking one side wholesale (that can drop the other person's published ranking edits). Commit as yourself (git `user.name`/`user.email` set to your own GitHub account) so the history shows who changed what. **For Alan**, every session sets this automatically before committing: `git config user.name adequate-alan` and `git config user.email 54249725+adequate-alan@users.noreply.github.com` (GitHub noreply address; "Keep my email addresses private" is on, so use this, not a personal email). The `alan-dev` branch was only an access test and can be deleted.

---

## 1. What SPAM is

- **SPAM** is the product: fantasy football rankings, values and trade tools. Brand mark is the one-word wordmark **`SPAM.`** (the period is part of the logo: burgundy word + warm accent dot in light mode, cream word in dark mode). The old name was SPMetrics. Never bring that name back in the UI, metadata or copy.
- Live site: **https://stevenp36.github.io/spam/** (rankings at `#rankings`). Repo: **`stevenp36/spam`** (renamed from `spmetrics-fantasy`; the old Pages URL no longer resolves).
- Base format: **12-team, Full PPR, Superflex, TE premium (+0.5), redraft.** That's what the SPAM Board means.
- The **SPAM Board** (Steven & Alan's manual rankings, tiers and published values) is the **core source of truth**. Everything else (league-adjusted values, trade verdicts, power rankings, Trade Finder) is *derived* from it.

## 2. Product rules that must not be undone

1. **The base SPAM Board is never overwritten by derived calculations.** League-adjusted values, custom formats, Sleeper data, stats refreshes and projections are separate layers computed in the browser. They must never write back into `RANKINGS_CSV` or change rank/tier/value for anyone.
2. **Manual rankings are locked.** Players with `source=manual` keep the order, tiers and values Steven/Alan set. Automatic processes (projections, Auto players, the weekly job) must never reorder them or push them down.
3. **Auto players sit underneath.** `source=auto` players (70 added Oct 2, 2026) are ranked below every manual player (overall #184+), valued with a gentle tail that never exceeds anyone ranked above them. Moving, re-tiering or re-valuing an Auto player in the editor and saving makes him Manual. Players who only shift because someone else moved stay Auto.
4. **Values follow the overall rank (decided by Alan, Oct 3, 2026).** On the SPAM Board no player is ever valued above someone ranked ahead of him. `keepOverallOrder` enforces it over the whole board (Auto tail included) by adjusting values, never ranks: pool-adjacent-violators toward the tier values with a 0.5% step inside a pooled group. Published values are fixed anchors; the model values between two of them stay between them. (This replaced the old 2% `overallMaxShift` cap, which left 33 inversions.)
5. **Tiers first, then rank order, then format.** Tiers decide where the value gaps are; rank order inside a tier sets small gaps; format (league size, scoring, lineup) adjusts how much each tier is worth. No artificial cliffs just because a player crosses QB12→QB13 or WR36→WR37.
6. **"Custom" means unpublished.** A typed value shows the CUSTOM label, striped bar and an Auto/Reset button only until it's published. Once published it's that player's official SPAM value and looks like every other player. It stays fixed (it doesn't follow the model) until someone edits it again.
7. **Save → Publish workflow.** Before saving = unsaved edit. Save changes = saved (in the browser, and published automatically if the browser has a GitHub token). Publish to live site = committed to `index.html` on GitHub and becomes the master rankings. Tier changes follow the same workflow.
8. **League-specific screens always show league-adjusted values and position ranks** (Trade Finder, My Team, League, Free Agents, the calculator in league mode, player pages opened from those). The SPAM Board / League-adjusted toggle only affects the Rankings board. Never show the base positional rank (e.g. superflex QB3) inside a 1QB league's trade recommendation.
9. **Historical honesty in Trade History.** A trade is "Historical SPAM values" only if every player had a SPAM value on or before the trade date. Trades before SPAM existed are labeled **Pre-SPAM trade** and judged as a retrospective with today's values. Never present today's values as what a player was worth back then.
10. **Stats never change rankings.** Stats refreshes update game logs and fantasy points only.
11. **Design consistency.** Use the theme tokens; no default browser controls (selects, checkboxes, dialogs). No Patreon button or styling. Labels are sentence-case in copy, uppercase with letter spacing for small labels.
12. **The website is the master source of truth for rankings** (from Alan). Don't sync the Excel file unless Alan or Steven asks.
13. **Keep the layers separate** (from Alan). Don't overwrite manual rankings or published values, don't let stats or projection updates change rankings, and keep league calculations derived from the base board.
14. **Stay in scope** (from Alan). Don't change unrelated parts of the site when doing a specific feature. Preserve the SPAM branding and design system.
15. **Don't rename the `spm_` localStorage keys** (from Alan). Renaming them would wipe visitors' saved leagues, edits and tokens.

## 3. How to run it

It's a static site: **one HTML file** plus JSON data. No build step, no framework, no npm.

```bash
git clone https://github.com/stevenp36/spam.git && cd spam
python3 -m http.server 8000          # then open http://localhost:8000/
```

Opening `index.html` straight from disk works for most things, but `fetch()` of `data/*.json` needs a local server.

Pipeline scripts (Python 3.12, pandas, numpy): `cd pipeline && pip install pandas numpy`. They download public nflverse / DynastyProcess data.

### Testing (how changes were verified so far)
There's no committed test suite. Changes were verified with throwaway **Playwright** (Python) scripts:
- Serve the repo locally, open the page with `chromium.launch()`, and read the rankings table from the DOM (`#rank-body tr.player`, `.pl-name`, `.pos-col .pos`, `.val .num` / `.val .num-btn`).
- **Mock Sleeper** by routing `https://api.sleeper.app/**` to fake JSON (users, leagues, rosters, transactions) and connect through the UI (`#sl-connect` → Sleeper → username → pick league).
- **Mock GitHub** by routing `https://api.github.com/**` to test the Save/Publish flow without touching the real repo.
- Key regression checks:
  - Manual players' ranks and values are identical before and after a model change, compared across several `?fmt=` formats.
  - A league in the base format gives exactly the base values: all 253 match.
  - No `pageerror` events.
  - Light and dark screenshots look right.
- `?fmt=` URL form: `t10_qb1_rec0.5_tep0` (keys: `t` teams, `qb` 1/sf/2, `sx` superflex spots, `rec`, `tep`, `ptd`, `pyd`, `int`, `fl` fumble, `fd`, `rb`, `wr`, `te`, `fx` flex, `bn` bench).

Committing these as `tests/` would be a good first improvement.

## 4. Where things are

```
index.html                     the whole site (HTML + CSS + JS, ~8k lines) AND the rankings data
data/rank_history.json         ranking history: {note, version: 2, players: {sleeper_id: [[ts, rank, posRank, tier, value, src]]}}; the browser writes src M, the scheduler S; existing P entries come from older code
data/stats/<season>.json       weekly game stats + team schedules for player pages (2026, 2025, 2024); schedule rows also carry kickoff (ET), team spread, game total, roof, stadium (see `schedule_cols`); `defense` = per-team run/pass EPA, success, explosive rate allowed (play-by-play); `injuries` = latest week's injury report per team (cols include `wed`/`thu`/`fri` practice status)
data/sleeper_players.json      Sleeper ID → [name, pos, team, gsis_id, birthdate]
data/platform_ids.json         ESPN/Yahoo ID → Sleeper ID (for ESPN/Yahoo imports)
data/curve_components.json     points-by-rank curve inputs used to re-score other formats
pipeline/                      Python data jobs (see §8)
.github/workflows/site.yml     the only workflow: deploy on push + scheduled data refreshes
favicon.svg, manifest.webmanifest
README.md                      detailed feature reference
CLAUDE.md                      this file
```

Inside `index.html` (search for these names):
- **Settings at the top** (plain JS constants, meant to be tuned):
  - `SITE`: name, repo, format text.
  - `RANKINGS_CSV`: the data.
  - `VALUE_MODEL`: curves, tiers, `tagTierFrom: 90`, `autoDecay`.
  - Trade model constants, `TEAM_FIT`, `DEPTH_ADJUST`.
  - `TIER_NAMES`: preset tier names.
  - `STATS_SEASONS`.
  - `FORMAT_ADJUST`: margin, maxPosMove, `tierKeep: 0.40`, `floor`.
  - `TRADE_VERDICTS`.
- **Value pipeline:**
  - `loadPlayers` → `modelValue` → `keepRankOrderBySource` → `applyTiers` → `autoValues` (the tail) → `keepOverallOrder` (whole board: values never increase down the overall rank).
  - League layer: `leagueRecalc` → `adjustValues(valueLeague())` → `smoothTiers` → `stickyOrder` → `LG.adj` / `LG.adjPos` / `LG.adjRank`.
  - Display helpers: `dv(p)` = value in the current context, `posLabel(p)` = position rank in the current context, `leagueView()` decides which.
- **Editor:**
  - `editor`, `draft`, `writeOrder`, `moveOverall`, `movePlayer`, `setValue`, `makeManual`.
  - Tier editing: `tierAction`, `shiftTiers`, `materializeTierNames`, `TIER_EMPTY`.
  - Saving and publishing: `saveLocal`, `publishLive`, `mergeInto`.
  - Data columns: `EDIT_COLS`.
- **History:** `recordSave`, `saveHistory`, `addSnapshot`, `normalizeHistory`, `window.SPM` (used by `pipeline/snapshot_history.py`).
- **Sleeper/ESPN/Yahoo:** `SL_KEY`, `slGet`, `leagueTeams`, `espnToLeague`, `parseYahooSettings`, `activeData()`, `syncedLeague()`.
- **Custom format:** `FMT`, `FMT_DEFAULT`, `FMT_FIELDS`, `fmtLeague`, `FMT_SRC` (synced vs custom), `configText`.
- **Tabs:**
  - My Team: `renderMyTeam`.
  - League: `renderLeague`, `powerHtml`, `teamExpand`, `standingsHtml`, `tradeHistoryHtml`, `evalTrade`, `valueAt`.
  - Trade Finder: `renderFinder`, `findTrades`, `findThree`.
  - Free Agents: `renderFA`.
  - Calculator: `renderTrade`, `tradeModel`, `runModel`, `rosterContext`.
  - Player modal: `openPlayer`, `renderPlayer`, `ppSection`, `statsStamp`.
- **UI components:**
  - Dropdowns: `SpamSelect` (end of file), which turns every `<select>` into a themed dropdown.
  - Themed checkboxes and radios: global CSS.
  - Theme: `setTheme`, `spm_theme`.
  - Update prompt: `BUILD_ID` and `checkForUpdate`.

## 5. How the rankings data flows

1. **`RANKINGS_CSV`** (inside `index.html`) is the master data. Columns:
   `player,pos,team,rank,pos_rank,tier,value,proj_ppg,games,proj_score,sleeper_id,source`
   (`tier_name` is not in the current header; the editor's `colOf()` adds it as a 13th column the first time a tier is renamed.)
   - `rank` = overall rank (source of truth for order); `pos_rank` derived from it.
   - `tier` = positional tier number; **90+ are tag tiers** (e.g. 90 = "Hurt"), not part of the ladder.
   - `value` = blank → model value; a number → published official value (fixed).
   - `source` = `manual` / `auto`. `tier_name` = editable tier name (falls back to `TIER_NAMES`).
   - `proj_ppg/games/proj_score` = written weekly by the pipeline (projection blend). `sleeper_id` written by the pipeline.
2. On load, `loadPlayers` builds player objects and values (base SPAM values, scaled so #1 = 10,000).
3. Editor edits change a `draft` copy of the CSV and call `rebuild()`. Save stores the changed fields per player in `localStorage` (`spm_local_edits`); Publish merges only the edited fields onto the latest `index.html` from GitHub and commits it (so the weekly projection refresh is never clobbered).
4. The **league layer** is computed after every rebuild from the base values: never stored.
5. Snapshot as of Oct 3, 2026: 253 players (183 Manual #1–183, 70 Auto #184–253), 4 published values (Bijan Robinson, Kenneth Walker III, Jacorey Croskey-Merritt, Jaxon Smith-Njigba), A.J. Brown in tag tier 90.

## 6. Publishing (rankings) and deploying (code)

**Rankings edits** (no code): in the site's editor (currently open to every visitor, temporarily), make changes → **Save changes**. If that browser has a GitHub token, Save publishes immediately; otherwise click **Publish to live site** once and paste a token:
- **Steven** (owner): a *fine-grained* token for `stevenp36/spam` with **Contents: Read and write** (+ **Actions: Read and write** for the Refresh stats button).
- **Alan** (collaborator): fine-grained tokens can't reach repos owned by another personal account, so use a **classic** token with the **`repo`** scope (`public_repo` is enough for publishing; `repo` is needed to start the stats workflow).
- Tokens live only in that browser's `localStorage` (`spm_editor_token`). **Never put a token in the code or the repo.**

**Code changes**: commit to `main` and push. The `push` trigger in `site.yml` deploys the repo root to GitHub Pages in ~1 minute. **Bump `BUILD_ID`** (top of the main script) in every code change so open browsers get the "new version" prompt. Rankings publishes from the editor don't need it.

Both owners push straight to `main` (see the workflow note at the top). Before pushing a code change, `git pull --rebase` first: the editor and the scheduled jobs commit to `main` too (`Rankings edit by @…`, `Ranking history: N changes`, `Player stats refresh`, `Weekly projections and stats refresh`).

## 7. How to change rankings safely

- Prefer the website editor. If editing `RANKINGS_CSV` by hand:
  - Keep the columns.
  - Keep ranks unique and contiguous.
  - Put every Auto player after every Manual player.
  - Quote any field containing a comma.
  - Leave `proj_*` and `sleeper_id` alone (pipeline-owned).
- After resolving any `RANKINGS_CSV` merge or rebase conflict, check that ranks still run 1–N with no duplicates or gaps and that every Auto player is below every Manual player. Verify by parsing the CSV, not by eye.
- After a model change, verify manual players' values are unchanged (or changed only as intended) in the base format and a few `?fmt=` formats.
- Don't put the draft rankings of one person into the board without saying so: the board is Steven & Alan's combined ranking.
- Ranking History records committed changes (Save/Publish), one entry per changed player, plus scheduled snapshots. Same-day separate publishes are separate entries; unchanged players get no duplicate. Tier changes are included.

## 8. Scheduled jobs and data updates (`.github/workflows/site.yml`)

| Trigger | What runs | Writes |
|---|---|---|
| push to `main` | deploy only | Pages |
| **Tue 14:00 UTC** (weekly) | `project_players.py` → `merge_projections.py` → `build_sleeper_ids.py` → `build_stats.py 2026` → `stamp_date.py` → `snapshot_history.py` (headless browser) | `index.html` (proj columns, sleeper IDs, date), `data/sleeper_players.json`, `data/platform_ids.json`, `data/stats/2026.json`, `data/rank_history.json` |
| **Fri 08:30 & 15:00, Sun 08:30 & 15:00, Mon 08:30 & 15:00, Tue 08:30, Thu 15:00 UTC**, plus **Wed/Thu/Fri 22:00 UTC** for injury/practice reports | **stats only**: `build_stats.py 2026` (stats, schedule lines, defense efficiency, injury report) | `data/stats/2026.json` |
| manual "Run workflow" (`stats_only` true/false) or editor **Refresh stats** button | stats-only or the full weekly job | as above |

- Stats come from nflverse's weekly player stats, which usually appear the night of the games and sometimes the next morning. That's why each game day has a retry.
- The stats file includes `updated` (UTC timestamp) and `through_week`; player pages show "Stats updated … · through Week N".
- The weekly projection refresh changes `proj_*` columns, which feed the model's projection blend for *model-valued* players (not published fixed values). Rank order and tiers are never changed by it.
- Season rollover: add the new season to `STATS_SEASONS` and the workflow's `build_stats.py <year>` and git-add lines.

## 9. Sleeper and league data are separate from SPAM data

- Connected leagues (Sleeper username → leagues; ESPN direct or paste; Yahoo/other paste) are stored in the **visitor's browser** (`spm_sleeper`). Nothing about a visitor's league is committed to the repo.
- Every import becomes a Sleeper-shaped object `{league, users, rosters}`, so all features work the same way.
- Ownership: `LG.ownerOf` maps players to fantasy teams for owner tags, the "Show" filter, Free Agents, rosters.
- Trade History reads Sleeper `transactions` for each week (Sleeper only).
- **League-adjusted values** come from the selected league's settings (Synced league) or the user's **Custom format** (`FMT`, saved per browser, also in `?fmt=`). League size + lineup set replacement levels; scoring re-scores the points-by-rank curves; tiers are re-priced as blocks; `tierKeep` limits tier-to-tier drops in shallow formats; a small `floor` prevents zeros; a per-player scoring-profile nudge (max ±10%) applies; order moves only when a value beats the player above by >3% (max 2 spots per position). **None of this touches the SPAM Board.**
- League depth (`DEPTH_ADJUST`): shallow leagues (e.g. 10 teams × 7 starters) weight bench depth less.

## 10. Features and the decisions behind them

- **Player identity layout (every screen that lists players):** line 1 is the player name (strongest) with the NFL team as a small muted abbreviation right beside it (`nflTag`, `.pl-team`). Line 2 is the fantasy owner as smaller secondary text (`ownPill` / `ownerTag`, `.own-tag`): "Owned by X" muted, **My team** in warm gold (`--mine-accent`), **Free agent** in muted green. Never put the owner on the NFL team's line. A player with no NFL team shows no team (not "FA"), so "Free agent" always means the fantasy league. Screens where the owner is already obvious (My Team, a team's roster board, a Trade History side) show no owner line.
- **Rankings tab:**
  - All / QB / RB / WR / TE.
  - Board view toggle: SPAM Board vs League-adjusted.
  - Column guide (RK / RANK, PLAYER, POS, VALUE): compact and muted, and sticky under the masthead while scrolling (desktop; `--mast-h` is set from JS).
  - Dense rows (~53px). Tier bands: a soft full-width band with the tier name as the focus (normal case, not oversized). A small muted note "N players · high–low" is derived only from the players currently in that tier; never show a formula-style value range as the headline.
  - Typography: big headings (page titles, card titles, verdicts, player name in the modal) and the main tabs use normal case; uppercase with letter spacing is kept for small labels (column guides, tags, badges).
  - Owner "Show" filter when a league is connected.
- **Editor** (top bar, temporary: open to everyone):
  - Drag or arrows to reorder.
  - Click a value to type it.
  - In position tabs, hover a tier header to rename it, add a tier above or below, or delete it (asks whether players move to the tier above or below; never drops players).
  - Drag players onto tier headers or empty tiers.
  - Empty tiers last only until you save.
  - **Sign out** sits at the right of the editor bar whenever this browser has a saved GitHub token (next to `@login`); it removes the token from the browser. Unpublished edits stay saved.
- **Player modal:**
  - Tabs: Overview, Game log, Schedule, Stats, Fantasy performance, Ranking history, Trade value, Practice report (last: useful but secondary), Compare.
  - Header: a compact matchup strip right of the name (week, opponent, kickoff, verdict, spread/total, status); hidden on phones.
  - Game log: every week of the season: result (W/L score), points, weekly position finish (`weeklyFinish`, current scoring), bye week, and upcoming games greyed with kickoff.
  - Schedule: every remaining week with a Matchup verdict and the opponent's ranks vs his position (points allowed, EPA, success, explosive; 1 = softest), a key line above the table and hover explanations on each column.
  - **NFL team identity** comes only from `NFL_TEAMS` (top of the main script: full name, nickname, primary/secondary color, ESPN logo code; from nflverse teams_colors_logos) through `teamMeta`, `teamLogo`, `teamStyle` / `teamAccent`. Team colors are small accents only (header strip, photo ring, matchup-card strip, practice-report section edge, schedule-row edge); `teamAccent` picks a readable shade per theme (`--tc-d` / `--tc-l`, `.tm` chooses). Never hard-code team colors or logos elsewhere.
  - **Status colors** are one system site-wide (`--st-*` tokens, `stBlock` / `stBadge`): FP green, LP amber, DNP red, Out deep red, Questionable amber, Doubtful orange-red, IR muted red.
  - Practice report: sections per team (logo, full name, team-color edge, "Opponent" label), grouped by position, columns Player (with game-status badge) · Wed · Thu · Fri · Injury. Days fill from the Wed/Thu/Fri evening runs (`build_stats.py` records the latest status under the run's ET weekday and carries earlier days; this week before those runs existed only has Friday). By default only what matters for him (`RELEVANT`: e.g. RB = his own status, own RB/QB/OL, opponent DL/LB; WR = own QB/WR/TE, opponent DBs), worst status first; both full team reports behind "View full team reports". Group headers are muted so statuses stand out. Full reports show his team's and the next opponent's latest practice report grouped by position (game status, practice FP/LP/DNP, injury). nflverse keeps only the latest practice status per week, not Wed/Thu/Fri separately.
  - Overview order: identity → rank / value / PPG (header) → **This week** card → Start/sit line (league only) → season grid → season line → weekly chart.
  - This week: opponent, home/away, kickoff, stadium + roof, spread, game total, implied team total (from nflverse `games.csv` via `build_stats.py`), the opponent's rank vs the position and fantasy points allowed per game (computed in the browser from the weekly logs, current scoring: `defenseVsPos`). Matchup verdict Favorable / Neutral / Tough = thirds of a blend of the four Schedule metrics: points allowed per game 40%, EPA 25%, success 20%, explosive 15% (from play-by-play: runs for RBs, dropbacks for QB/WR/TE); it only tints a thin edge and its label. The card also shows the opponent's EPA / success / explosive ranks, his practice status (or "Not on practice report"), a Next line (the 3 weeks after this one with verdict dots) and Practice notes (the relevant players listed Out / Doubtful / Questionable / DNP / LP). Bye weeks show "Week N · Bye". No player props (no keyless source) and no forecast weather yet (nflverse fills temp/wind only after games).
  - Start/sit (league): his slot in his fantasy team's best lineup, "Every-week starter / Flex starter / Bench depth", next player up at the position, and Sleeper's own lineup status.
  - Photos come from `sleepercdn.com`, with an initials fallback.
  - Shows both the league position rank and the SPAM Board rank when they differ.
  - "Stats updated" line.
- **My Team:** the connected user's roster with slots, league ranks and values.
- **League tab:**
  - Sub-tabs: Power Rankings / Trade History / Standings.
  - Power Rankings: compact rows; the whole row expands into a roster board with position ranks vs the league.
  - Gold accent on your own team.
  - "Keep teams open to compare".
  - Clicking a player, Trade With or Find Trades never toggles the row.
  - Team score bar is scaled to the top team.
  - Trade History: per-trade cards with verdict, meter, picks/FAAB, a 3-team layout, Analyze Trade, and labels for historical, pre-SPAM and current-value evaluations.
  - Standings: record vs power rank.
- **Trade Calculator:**
  - 2-team, plus optional 3-team.
  - League mode with roster context (lineup impact, team-specific value, position rooms).
  - Verdict tiers in `TRADE_VERDICTS`.
  - Consolidation bonus and roster-spot cost are small and capped.
  - One compact setup bar: League · Team 1 vs Team 2 (· Team 3) · + Add third team · "League context: <league>" indicator.
  - Each card's head (league mode with a team picked): team avatar, team name + "gets", one short line "Manager: X · Needs QB · Strong RB, TE", and the total it receives.
  - Cards keep "gets" semantics. In a 2-team league trade, each card's main button is "+ Add from <partner>'s roster" (the players it receives come from the other team); "Or search any player (hypothetical)" is secondary. 3-team mode keeps each team's own roster with send-to buttons.
  - Rows read: name on line 1; line 2 = position badge · NFL team · owner (just the partner's team name when he comes from the trade partner, else "Owned by X" / My team / Free agent; 3-team shows the "from" menu instead). Value right-aligned.
  - Verdict card is compact: verdict, adjusted difference, one-line reason, then Balance / Swap / Clear on one row; Why?, Roster impact (lineup changes) and Value breakdown stay collapsed.
  - Universal mode (No league) drops team names, avatars and ownership and goes back to You / They.
- **Trade Finder:**
  - League-wide discovery for one player, or a **2-player package from one roster**.
  - 1-for-1 or packages; 3-team cycles only for single players.
  - Cards read: partner → short verdict ("FAIR + GOOD FIT") → muted numbers → give/get → one-line why. The full analysis expands.
  - Always uses league-adjusted values.
- **Free Agents:** unrostered ranked players in the connected league.
- **Themes:**
  - Light: cream `#F7F2EB`, burgundy `#5A1F32`, coral `#D96B5B`, peach `#F0B18A`, ink `#2E2A28`.
  - Dark: near-black `#1A1314`, burgundy surfaces, cream `#F3EDE4`, gold `#F4B979`.
  - All colors come from tokens at the top of the CSS.
  - Archivo typography.
  - Custom dropdowns, checkboxes and radios; no native controls.

## 11. Known limitations and unfinished work

- **Editor security:** editing is open to every visitor (Steven's temporary choice); only people with a GitHub token can publish. Real authentication is still to do.
- **Tests:** no committed test suite (see §3).
- **IR / taxi spots** aren't format options; they don't change values.
- **Draft picks** are listed in trades but not valued.
- **Trade History:** only for Sleeper leagues; ESPN/Yahoo imports have no transaction feed.
- **Deep tiers in shallow formats:** a 10-team 1QB board values QB13+ at a few hundred by design (tiers keep ≥40% of the value above).
- **Excel master workbook:** Steven & Alan's original Excel file (`StevenAlanRankings`, per-position Steven/Alan/Combined sheets) is **not synced** with the site. The website is now the source of truth. An Oct 2 copy with the 70 Auto players and a "SPAM Board" sheet was produced but isn't in the repo.
- **Old URL:** `stevenp36.github.io/spmetrics-fantasy/` is dead. A redirect page can live in a new `spmetrics-fantasy` repo if wanted.
- **Custom domain:** not set up. Every path is relative; only `canonical`/`og:url` would change.
- **Player data:** some player-name matches use aliases (`pipeline/merge_projections.py` `ALIASES`, `pipeline/build_sleeper_ids.py` `ID_ALIASES`). Add an alias when a new player's projection or Sleeper ID comes up empty.
- **Known issues, not yet fixed (found in an Oct 3 code review):**
  - The publish error and Refresh stats error messages (and the token prompt) only describe fine-grained tokens ("Contents/Actions: Read and write"). They don't fit Alan's classic `repo` token.
  - The README is stale: it says stats refresh weekly only (game-day runs exist), and its token section only mentions fine-grained tokens.
  - `SITE.format` reads "12-Team · Full PPR · Superflex" and leaves out TE premium, even though the model default is +0.5 TEP.
  - The scheduled workflow runs `git push` without pulling first. If someone publishes during the Tuesday job, the job's push is rejected and that run's deploy fails.
  - `mergeInto` merges rank columns per row. If Steven and Alan publish overlapping rank moves from stale pages, the board could end up with duplicate ranks. The 409 retry only catches a changed file.
  - The weekly projection refresh changes values for all model-valued players (all but the 4 with published values). Ranks and tiers stay fixed. This is by design.
  - The `trade-boost-preview` and `alan-dev` branches are already merged or were only tests. Either can be deleted.

## 12. Secrets, services, accounts

- **No API keys or repository secrets.** The workflow uses GitHub's built-in `GITHUB_TOKEN` (`contents: write`, `pages: write`, `id-token: write`).
- External services, all public and keyless:
  - Sleeper API (`api.sleeper.app`), called from the visitor's browser.
  - Sleeper CDN for photos.
  - ESPN's logo CDN (`a.espncdn.com/i/teamlogos/nfl/500/…`) for NFL team logos.
  - ESPN fantasy API for public leagues.
  - nflverse data releases and DynastyProcess player IDs (pipeline).
  - Google Fonts.
- Pages source: **GitHub Actions** (`Build and deploy site` workflow). Custom domain: none.

## 13. Working agreement for AI assistants

- Make the change, test it locally (Playwright if it touches behavior), bump `BUILD_ID`, `git pull --rebase`, commit with a clear message, push.
- Never rewrite or reorder `RANKINGS_CSV` as a side effect. Never commit tokens. Never remove Ranking History entries.
- Ask before anything irreversible (deleting data, renaming the repo, rewriting history).
- When you change a behavior described here, update this file in the same commit.
