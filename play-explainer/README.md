# Play Explainer: data, replay and filter (steps 1 to 3)

Replays a past NFL game as if it were live and sends only the big moments to the explainer.

## Setup

```bash
pip install nflreadpy polars
```

## Run it

```bash
python run.py                        # NFC Championship (Rams at Seahawks), one moment every 2 seconds
python run.py --fixed 1              # faster
python run.py --speed 60             # follow the real game clock, 60x faster
python run.py --game 2025_16_LA_SEA  # any other game
python run.py --export               # save the filtered moments to data/<game>_feed.json
```

The first run downloads the season (about a minute). After that the game is cached in `data/`.

## What each file does

| File | Step | Job |
|---|---|---|
| `pipeline/data.py` | 1. Data | Pulls one game from nflverse, keeps ~35 useful columns, adds `helped` / `hurt` / `neutral` from win probability |
| `pipeline/replay.py` | 2. Replay | Releases plays on a timer: fixed gap for demos, or following the game clock |
| `pipeline/filter.py` | 3. Filter | Keeps 3rd and 4th downs, touchdowns, field goals, turnovers and swings of 10+ win-probability points, and records why |
| `run.py` | | Runs all three; each printed play is what the LLM explainer (step 4) receives |

## Good demo games (2025 season, biggest win-probability swings)

| game_id | Game | Score |
|---|---|---|
| `2025_21_LA_SEA` | NFC Championship, Rams at Seahawks (default) | SEA 31, LA 27 |
| `2025_16_LA_SEA` | Rams at Seahawks, week 16 | SEA 38, LA 37 |
| `2025_02_NYG_DAL` | Giants at Cowboys, week 2 (most swings all season) | DAL 40, NYG 37 |
| `2025_04_GB_DAL` | Packers at Cowboys, week 4 (tie) | 40-40 |
| `2025_20_BUF_DEN` | Divisional round, Bills at Broncos | DEN 33, BUF 30 |

## Step 4: the explainer and video

```bash
pip install anthropic                     # or openai
export ANTHROPIC_API_KEY=...              # your key; never commit it
python explain_game.py --provider anthropic --persona soccer_fan
python explain_game.py --live --provider anthropic --persona cricket_fan_hindi   # watch it explain as it replays
python explain_game.py                    # no key needed: template mode, for testing and as a demo backup
```

Personas: `new_fan`, `soccer_fan`, `cricket_fan_hindi`, `spanish_casual`, `expert` (edit `pipeline/personas.py`).

**Video:**
1. `python explain_game.py --make-timestamps` writes `data/<game>_timestamps.csv`, one row per big moment.
2. Watch the game video and type the second each play starts into `video_start`.
3. Re-run `explain_game.py`. Each explanation now carries `video_start` / `video_end`.
4. Open `viewer/index.html` in a browser, load the video and `data/<game>_<persona>_explained.json`. Explanations appear as the video reaches each play.

**How accuracy is protected:** the team, score and helped/hurt come from the data, never the model. The model only sees this one play and is told not to add anything. Every answer is checked (valid JSON, all fields present, short, no player names that aren't in the official description). If a check fails, the template version is shown instead, so the screen never shows a made-up fact.

## Handing off to the explainer (step 4)

Each moment is a dict with the play description (`desc`), players, down and distance, score, `reasons` (why it made the cut) and `helped` (good or bad for the team with the ball). Pass that to the LLM prompt with the user profile.

Swap point for real time: replace `load_game` + `replay` with a live data feed that yields the same dicts. Nothing after it changes.

Code style: no f-strings, lists instead of tuples.
