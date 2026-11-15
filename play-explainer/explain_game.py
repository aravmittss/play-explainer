"""Runs the whole chain for one game and one viewer profile, and writes the JSON the video player reads.

Examples:
  python explain_game.py                                   # template mode, swiftie, Colts at Chiefs (demo game)
  python explain_game.py --provider gemini --persona swiftie --note "explain penalties too"
  python explain_game.py --provider gemini --persona new_fan --language Korean
  python explain_game.py --provider anthropic --persona cricket_fan_hindi
  python explain_game.py --make-timestamps                 # create the CSV to fill in video times
  python explain_game.py --live --provider anthropic       # explain each moment as it is replayed

Output: data/<game>_<persona>_explained.json, a list of objects like
  {play_id, video_start, video_end, team, verdict, headline, what_happened, who, why_it_matters,
   pop_culture, players, read_more, ...}
"""
import argparse
import json
import os

from pipeline.data import load_game
from pipeline.filter import high_leverage
from pipeline.replay import replay
from pipeline.personas import make_profile
from pipeline.explainer import explain, load_context
from pipeline.video_sync import write_template, load_timestamps


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--game", default="2026_02_IND_KC")
    parser.add_argument("--persona", default="swiftie")
    parser.add_argument("--language", default=None, help="overrides the persona's language")
    parser.add_argument("--note", action="append", default=[], help="what the viewer typed in the chat; repeat for more")
    parser.add_argument("--limit", type=int, default=None, help="only explain the first N moments (quick test)")
    parser.add_argument("--no-cache", action="store_true", help="ask the AI again even if an answer is saved")
    parser.add_argument("--provider", default="template", choices=["template", "gemini", "anthropic", "openai"])
    parser.add_argument("--model", default=None)
    parser.add_argument("--make-timestamps", action="store_true")
    parser.add_argument("--live", action="store_true", help="replay with a 2 second gap and print as it goes")
    args = parser.parse_args()

    moments = high_leverage(load_game(args.game))
    if args.limit is not None:
        moments = moments[:args.limit]

    if args.make_timestamps:
        print("Wrote " + write_template(args.game, moments) + ". Fill in video_start for each play.")
        return

    profile = make_profile(args.persona, language=args.language, notes=args.note)
    context = load_context(args.game)
    times = load_timestamps(args.game)
    feed = replay(moments, fixed=2.0) if args.live else moments

    results = []
    fallbacks = 0
    for play in feed:
        item = explain(play, profile, provider=args.provider, model=args.model, context=context, use_cache=not args.no_cache)
        span = times.get(float(play["play_id"]))
        item["video_start"] = span[0] if span else None
        item["video_end"] = span[1] if span else None
        item["qtr"] = play["qtr"]
        item["clock"] = play["time"]
        item["score"] = play["away_team"] + " " + str(play["total_away_score"]) + " - " + str(play["total_home_score"]) + " " + play["home_team"]
        if item["source"].startswith("template (fallback)"):
            fallbacks = fallbacks + 1
        results.append(item)
        if args.live:
            print("")
            print("Q" + str(item["qtr"]) + " " + item["clock"] + " | " + item["score"] + " | " + item["team"] + " " + item["verdict"])
            print("  " + item["headline"])
            print("  " + item["what_happened"])
            print("  " + item["why_it_matters"])
            if item["pop_culture"]:
                print("  * " + item["pop_culture"])

    path = os.path.join("data", args.game + "_" + args.persona + "_explained.json")
    with open(path, "w") as f:
        json.dump(results, f, indent=1, ensure_ascii=False)
    print("Wrote " + path + " (" + str(len(results)) + " moments, " + str(len(times)) + " with video times, "
          + str(fallbacks) + " AI answers replaced by the template)")


if __name__ == "__main__":
    main()
