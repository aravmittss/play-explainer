# Step 4 → Steps 5 and 6: how to call the explainer

For Chris (frontend and FastAPI on Cloud Run). From Priya.

## The one function you call

```python
from pipeline.personas import make_profile, PERSONAS
from pipeline.explainer import explain, load_context

context = load_context("2026_02_IND_KC")          # load once at startup

profile = make_profile(
    "swiftie",                                     # value of the "Pre-set personas" dropdown (a key of PERSONAS)
    language="English",                            # value of the language dropdown, or None for the persona's own
    notes=["she also loves tennis"],               # every message the viewer typed in the chat box, in order
)

item = explain(play, profile, provider="gemini", context=context)
```

`play` is one moment from Arav's filter: `high_leverage(load_game(game_id))`, or `data/<game>_feed.json`.

## What comes back

```json
{
  "headline": "Kelce scores for the Chiefs!",
  "what_happened": "One sentence.",
  "who": "One sentence naming the key players.",
  "why_it_matters": "1 to 2 sentences on what it means for winning.",
  "pop_culture": "One sentence, or \"\" when there is none.",
  "players": [{"name": "P.Mahomes", "role": "threw the pass"}, {"name": "T.Kelce", "role": "caught the pass"}],
  "read_more": [{"outlet": "KCTV5", "title": "...", "url": "https://..."}],
  "team": "KC",
  "verdict": "helped | hurt | neutral",
  "language": "English",
  "play_id": 663.0,
  "source": "gemini | gemini (cached) | template | template (fallback)",
  "checks_failed": []
}
```

- `team`, `verdict`, `players` and `read_more` always come from the data, never the AI. Safe to show as-is.
- Show `pop_culture` only when it isn't empty. A pink "Pop culture" line works well.
- `read_more` holds real news links, from 0 to 2 per play. Fill the remaining "3 cards after the play" slots with sample ads.
- `source` tells you where the text came from. Don't show it to viewers; it's for debugging.

## Endpoints I'd suggest

| Endpoint | Does |
|---|---|
| `GET /personas` | returns `PERSONAS` for the dropdown (key + `label`) |
| `GET /stream?game=2026_02_IND_KC&persona=swiftie&language=English&notes=...` | server-sent events: replays Arav's moments and sends one `explain(...)` result per event |
| `POST /explain` with `{play_id, persona, language, notes}` | one explanation, for when the viewer changes persona or types in the chat mid-game and you need to redo what's on screen |

The video: official highlights on YouTube, https://youtu.be/u_6l6aXxKdo (video id `u_6l6aXxKdo`). Embed it with the YouTube IFrame Player API and poll `getCurrentTime()` a few times a second. 10 of the 38 moments appear in it; the other 28 have no `video_start` and can be skipped in video mode.

The video player: each moment has `video_start` / `video_end` once someone fills in `data/2026_02_IND_KC_timestamps.csv` (the second each play starts in our clip). Show the explanation when the video reaches `video_start`.

## Speed and Demo Day

- The free Gemini tier is slow (the code waits 5 seconds per call). Every good answer is saved in `data/cache/`, and the same play + viewer + notes comes back instantly afterwards.
- Before Demo Day, Priya runs `python demo_all_personas.py --provider gemini` to fill the cache for every persona, and we commit `data/cache/`. On stage nothing waits on Gemini.
- If the AI is down or gives a bad answer, `explain` returns the template version. The screen never shows an error or a made-up fact.
- Keys: set `GEMINI_API_KEY` as a Cloud Run secret. Never put it in the code or in GitHub.
