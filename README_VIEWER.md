# Viewer screen (Chris)

This folder is step 5: the viewer screen and the endpoints behind it. It shows the game video with a live feed of play cards beside it. A card pops up when the video reaches that play.

## Run it

No installs. Python 3.9 or newer.

```bash
python3 viewer/server.py
# open http://localhost:8080
```

If `explain_game.py` is not found, the server falls back to placeholder plays and says so in a banner. Those plays are invented for testing. Never show them on Demo Day.

## Connect it to Priya's explainer

1. Put this `viewer/` folder in the root of `play-explainer`, next to `explain_game.py`.
2. Add the Gemini key to a `.env` file in the repo root (copy `.env.example`). Add `.env` to the repo's root `.gitignore` if it isn't there. Never paste the key into code or a commit.
3. Open `HANDOFF_CHRIS.md` and check the function name. If it is not `explain_game`, start the server like this:
   ```bash
   EXPLAIN_FUNCTION=the_real_name python3 viewer/server.py
   ```
4. Load the page. The banner should be gone and the status line should say "38 big moments, 10 synced to the video."

If a field shows up empty, the JSON uses a key name the viewer doesn't know yet. Add it to `FIELD_ALIASES` at the top of `sources.py`. That is the only place that should need edits.

## Check against HANDOFF_CHRIS.md

I wrote this before seeing the handoff file, so confirm these:

- [ ] Function name and arguments. The adapter passes `persona`, `language`, `team`, `notes` and `provider` if the function accepts them.
- [ ] JSON shape. A list of plays, or an object with a `plays` / `cards` / `moments` list. Nested `play` and `explanation` objects are flattened.
- [ ] Video time key and format. Seconds or `m:ss` both work.
- [ ] Which team helped/hurt is measured for. The viewer assumes it is the viewer's team when one is picked, otherwise the team with the ball. If it is always the home team, set `impact_team` in the output.
- [ ] Win-chance scale. `0.07` and `7` both read as 7 points.
- [ ] Endpoint names. If Priya suggested different ones, rename the routes in `server.py`. The frontend only calls `/api/config` and `/api/plays`.
- [ ] YouTube ID in `viewer_config.json`. It is `u_6l6aXxKdo` from the chat. Check whether the third character is a lowercase L or a capital I.

## Endpoints

Cross-site requests are allowed, so a frontend on another domain (Lovable, Vercel) can call these. Set `CORS_ORIGIN=https://your-app.lovable.app` to allow only that site.


| Method | Path | What it returns |
| --- | --- | --- |
| GET | `/api/health` | `{"ok": true, "source": "repo"}` or `"sample"` and why |
| GET | `/api/config` | Game, video, personas, languages |
| GET or POST | `/api/plays` | Cards for one viewer. Fields: `persona`, `language`, `team` (`IND` / `KC` / empty), `notes` |

The server remembers each profile's cards, so switching back to a persona is instant and repeat viewers don't trigger new Gemini calls.

## Card shape the screen reads

```json
{
  "play_id": "...", "order": 1, "quarter": 1, "clock": "12:10",
  "situation": "3rd and 6 at IND 34",
  "video_time": 35.0,
  "score": {"away": 0, "home": 0},
  "headline": "...", "what_happened": "...", "who": "...", "why_it_matters": "...",
  "impact": "helped", "impact_team": "IND", "wp_change": 0.03,
  "pop_note": "...",
  "read_more": [{"title": "...", "url": "https://...", "source": "..."}]
}
```

## What the screen does

- **Sync to video:** each of the 10 timed plays pops at its video time with a lower-third on the video and a full card in the feed. Plays without a video time join the feed, collapsed, once the video passes a later timed play. Scrubbing back removes cards.
- **Replay without video:** releases every play on a timer (5, 10 or 20 seconds), the way it would look live. This is the backup if the video fails on Demo Day.
- **Stand-in clock:** if YouTube is blocked, a clock runs instead and cards still appear at the same moments.
- **Rooting for:** flips helped/hurt and the win-chance number to the viewer's side right away, then fetches wording written for that team.
- **Persona, language and notes:** each change asks the explainer for new wording. The old cards stay up until the new ones arrive.
- **Timeline:** yard-line strip under the video. Click a tick to jump to that play.

## Computer-vision lines

A YouTube embed doesn't expose its frames, so lines can't be drawn on it. With an .mp4:

1. Set `"mp4_url": "/static/game.mp4"` in `viewer_config.json` and put the file in `viewer/static/`.
2. Define `window.drawOverlay = ({ctx, time, play, width, height}) => { ... }` in a separate script. It runs on every tick with a canvas over the video.

## Deploy (for Priya)

`viewer/Dockerfile` builds from the repo root and listens on `$PORT`, which suits Cloud Run:

```bash
docker build -f viewer/Dockerfile -t play-explainer .
```

`viewer/Dockerfile.dockerignore` keeps `.env` out of the image. Pass `GEMINI_API_KEY` as a Cloud Run secret instead.
