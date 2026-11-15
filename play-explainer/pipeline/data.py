"""Step 1: Data. Pulls one past NFL game from nflverse and cleans each play.

Code style: no f-strings, lists instead of tuples.
"""
import json
import os

# Columns we keep from nflverse's ~370. Everything the explainer needs, nothing else.
KEEP = [
    "play_id", "game_id", "home_team", "away_team", "posteam", "defteam",
    "qtr", "game_seconds_remaining", "time", "down", "ydstogo", "yardline_100",
    "play_type", "desc", "yards_gained",
    "passer_player_name", "receiver_player_name", "rusher_player_name",
    "interception_player_name", "sack_player_name",
    "touchdown", "interception", "fumble_lost", "sack",
    "first_down", "third_down_converted", "third_down_failed",
    "fourth_down_converted", "fourth_down_failed",
    "field_goal_result", "safety",
    "total_home_score", "total_away_score",
    "epa", "wpa", "home_wp",
]

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def load_game(game_id, season=None):
    """Returns the game as a list of play dicts, in order. Caches to data/<game_id>.json."""
    cache_path = os.path.join(CACHE_DIR, game_id + ".json")
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            return json.load(f)

    if season is None:
        season = int(game_id.split("_")[0])
    # Loaded only when a game has to be downloaded; a saved game in data/ needs neither library.
    import nflreadpy as nfl
    import polars as pl
    pbp = nfl.load_pbp([season])
    game = (
        pbp.filter(pl.col("game_id") == game_id)
        .filter(pl.col("play_type").is_in(["pass", "run", "field_goal", "punt", "extra_point", "qb_kneel", "qb_spike"]))
        .select(KEEP)
        .sort("play_id")
    )
    if game.height == 0:
        raise ValueError("No plays found for game_id " + game_id)

    plays = game.to_dicts()
    whole_numbers = ["qtr", "down", "ydstogo", "yardline_100", "yards_gained", "total_home_score",
                     "total_away_score", "touchdown", "interception", "fumble_lost", "sack", "first_down",
                     "third_down_converted", "third_down_failed", "fourth_down_converted",
                     "fourth_down_failed", "safety", "game_seconds_remaining"]
    for play in plays:
        for key in whole_numbers:
            if play.get(key) is not None:
                play[key] = int(play[key])
        play["helped"] = helped_or_hurt(play)

    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(plays, f, indent=1)
    return plays


def helped_or_hurt(play):
    """Did this play help or hurt the team with the ball? Uses win probability added (wpa)."""
    wpa = play.get("wpa")
    if wpa is None:
        return "neutral"
    if wpa >= 0.02:
        return "helped"
    if wpa <= -0.02:
        return "hurt"
    return "neutral"


if __name__ == "__main__":
    import sys
    game_id = sys.argv[1] if len(sys.argv) > 1 else "2025_21_LA_SEA"
    plays = load_game(game_id)
    print("Loaded " + str(len(plays)) + " plays for " + game_id)
