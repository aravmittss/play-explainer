"""Runs steps 1 to 3 together: load a game, filter to big moments, replay them live.

Examples:
  python run.py                               # NFC Championship, one play every 2 seconds
  python run.py --game 2025_16_LA_SEA --fixed 1
  python run.py --speed 60                    # follow the real clock, 60x faster
  python run.py --export                      # write the filtered feed to data/<game>_feed.json, no replay

Each play printed here is what step 4 (the LLM explainer) receives.
"""
import argparse
import json
import os

from pipeline.data import load_game
from pipeline.filter import high_leverage
from pipeline.replay import replay


def scoreboard(play):
    return play["away_team"] + " " + str(play["total_away_score"]) + " - " + str(play["total_home_score"]) + " " + play["home_team"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--game", default="2025_21_LA_SEA")
    parser.add_argument("--fixed", type=float, default=2.0, help="seconds between plays")
    parser.add_argument("--speed", type=float, default=None, help="follow game clock this many times faster")
    parser.add_argument("--export", action="store_true")
    args = parser.parse_args()

    plays = load_game(args.game)
    moments = high_leverage(plays)
    print(args.game + ": " + str(len(plays)) + " plays, " + str(len(moments)) + " big moments")

    if args.export:
        path = os.path.join("data", args.game + "_feed.json")
        with open(path, "w") as f:
            json.dump(moments, f, indent=1)
        print("Wrote " + path)
        return

    fixed = None if args.speed is not None else args.fixed
    for play in replay(moments, speed=args.speed, fixed=fixed):
        print("")
        print("Q" + str(play["qtr"]) + " " + str(play["time"]) + " | " + scoreboard(play) + " | " + ", ".join(play["reasons"]))
        print("  " + play["desc"])
        print("  " + play["posteam"] + " " + play["helped"])


if __name__ == "__main__":
    main()
