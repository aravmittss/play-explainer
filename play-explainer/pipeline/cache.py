"""Saved AI answers, so a demo never waits on (or depends on) the AI.

One file per answer in data/cache/<game_id>/<key>.json. The key covers everything that changes the answer:
the play, the viewer profile, the chat notes, the provider and model, the pop-culture note and the AI instructions.
Delete the folder to start fresh.

Code style: no f-strings, lists instead of tuples.
"""
import hashlib
import json
import os

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "cache")
PROFILE_KEYS = ["language", "level", "style", "interests", "roots_for", "pop_culture", "notes"]


def make_key(play, profile, provider, model, note, instructions=""):
    parts = {
        "play_id": play["play_id"],
        "profile": dict([[k, profile.get(k)] for k in PROFILE_KEYS]),
        "provider": provider,
        "model": model or os.environ.get("EXPLAINER_MODEL", ""),
        "note": note,
        "instructions": instructions,   # changing the AI instructions makes fresh answers
    }
    raw = json.dumps(parts, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _path(game_id, key):
    return os.path.join(CACHE_DIR, str(game_id), key + ".json")


def get(game_id, key):
    path = _path(game_id, key)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def put(game_id, key, explanation):
    path = _path(game_id, key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(explanation, f, ensure_ascii=False, indent=1)
