"""Where the viewer gets its play cards.

Two sources, same output shape:

  SampleSource  placeholder plays in sample_data/, works offline, for UI testing only
  RepoSource    calls Priya's explainer function (see HANDOFF_CHRIS.md)

Every card the frontend receives looks like this:

  {
    "play_id": "...", "order": 1, "quarter": 1, "clock": "12:10",
    "situation": "3rd and 6 at IND 34",
    "video_time": 35.0 or null,          # seconds into the YouTube video
    "score": {"away": 0, "home": 0},     # score after the play
    "headline": "...", "what_happened": "...", "who": "...", "why_it_matters": "...",
    "impact": "helped" | "hurt" | "neutral",
    "impact_team": "KC" or null,         # team the helped/hurt tag is measured for
    "wp_change": 0.07 or null,           # win-chance change for impact_team, 0-1 scale
    "pop_note": "..." or null,
    "read_more": [{"title": "...", "url": "...", "source": "..."}],
    "source": "sample" | "repo"
  }

If Priya's JSON uses different key names, add them to FIELD_ALIASES below.
That is the only place that should need editing.
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
import re
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

CARD_FIELDS = [
    "play_id", "order", "quarter", "clock", "situation", "video_time", "score",
    "headline", "what_happened", "who", "why_it_matters", "impact",
    "impact_team", "wp_change", "pop_note", "read_more",
]

# First match wins. Checked against the play dict after flattening any nested
# "play" / "explanation" / "card" objects into it.
FIELD_ALIASES = {
    "play_id": ["play_id", "playId", "id", "play_key"],
    "order": ["order", "index", "seq", "sequence", "play_index"],
    "quarter": ["quarter", "qtr", "period"],
    "clock": ["clock", "game_clock", "time_remaining"],
    "situation": ["situation", "down_distance", "down_and_distance", "down_text"],
    "video_time": ["video_time", "video_seconds", "video_ts", "video_t", "youtube_time",
                   "video_start", "timestamp_seconds", "t"],
    "headline": ["headline", "title", "summary_title"],
    "what_happened": ["what_happened", "whatHappened", "what", "summary", "description", "desc"],
    "who": ["who", "players", "key_players", "player"],
    "why_it_matters": ["why_it_matters", "whyItMatters", "why", "why_matters", "impact_explanation"],
    "impact": ["impact", "helped_hurt", "helpedHurt", "tag", "verdict", "effect"],
    "impact_team": ["impact_team", "for_team", "perspective_team", "viewer_team"],
    "wp_change": ["wp_change", "wpa", "win_prob_change", "win_probability_change", "wp_delta"],
    "pop_note": ["pop_note", "pop_culture", "pop_culture_note", "popNote", "fun_fact"],
    "read_more": ["read_more", "readMore", "sources", "links", "articles", "citations"],
}
SCORE_ALIASES = {
    "away": ["away_score", "awayScore", "away"],
    "home": ["home_score", "homeScore", "home"],
}
LIST_KEYS = ["plays", "cards", "moments", "explanations", "results", "items"]
FN_CANDIDATES = ["explain_game", "explain_plays", "explain_moments", "explain", "run", "main_api"]


def load_config() -> dict:
    return json.loads((HERE / "viewer_config.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- sample

class SampleSource:
    name = "sample"

    def __init__(self) -> None:
        self.data = json.loads((HERE / "sample_data" / "demo_game.json").read_text(encoding="utf-8"))
        self.available = set(self.data.get("personas_in_sample", []))

    def persona_ready(self, persona_id: str) -> bool:
        return persona_id in self.available

    def plays(self, persona: str, language: str, team: str | None, notes: str) -> dict:
        fallback = next(iter(sorted(self.available)), None)
        cards = []
        for raw in self.data["plays"]:
            exp = raw["explanations"].get(persona) or raw["explanations"].get(fallback, {})
            card = {k: raw.get(k) for k in CARD_FIELDS}
            card.update({k: exp.get(k) for k in ("headline", "what_happened", "who", "why_it_matters") if exp.get(k)})
            card["read_more"] = raw.get("read_more") or []
            card["source"] = "sample"
            cards.append(card)
        notices = ["Sample plays, not the real game. Real cards replace these once the viewer is connected to the explainer."]
        if language != "en":
            notices.append("Sample cards are English only. The connected explainer writes in the chosen language.")
        if notes:
            notices.append("Notes change the wording once the explainer is connected.")
        return {"plays": cards, "notices": notices}


# --------------------------------------------------------------------------- repo

class RepoSource:
    """Calls the explainer function from Priya's branch.

    Set these if the defaults don't match HANDOFF_CHRIS.md:
      EXPLAIN_MODULE    module name, default "explain_game"
      EXPLAIN_FUNCTION  function name, default: first of FN_CANDIDATES that exists
      EXPLAIN_PROVIDER  passed as provider=..., default "gemini"
    """

    name = "repo"

    def __init__(self) -> None:
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        module_name = os.environ.get("EXPLAIN_MODULE", "explain_game")
        self.module = importlib.import_module(module_name)
        fn_name = os.environ.get("EXPLAIN_FUNCTION")
        if not fn_name:
            fn_name = next((n for n in FN_CANDIDATES if callable(getattr(self.module, n, None))), None)
        if not fn_name or not callable(getattr(self.module, fn_name, None)):
            raise ImportError(
                f"No explainer function found in {module_name}.py. "
                f"Set EXPLAIN_FUNCTION to the function named in HANDOFF_CHRIS.md."
            )
        self.fn_name = fn_name
        self.fn = getattr(self.module, fn_name)
        self.provider = os.environ.get("EXPLAIN_PROVIDER", "gemini")
        self._memo: dict[tuple, dict] = {}
        self._locks: dict[tuple, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def persona_ready(self, persona_id: str) -> bool:
        return True  # any persona can be generated live; uncached ones are just slower

    def _kwargs(self, profile: dict) -> tuple[list, dict]:
        """Pass only the arguments the function actually accepts."""
        names = {
            "persona": profile["persona"], "persona_id": profile["persona"],
            "language": profile["language"], "lang": profile["language"],
            "team": profile["team"], "favorite_team": profile["team"], "viewer_team": profile["team"],
            "notes": profile["notes"], "chat_notes": profile["notes"],
            "profile": profile, "viewer": profile, "viewer_profile": profile,
            "provider": self.provider,
        }
        try:
            params = inspect.signature(self.fn).parameters
        except (TypeError, ValueError):
            return [profile], {}
        if any(p.kind == p.VAR_KEYWORD for p in params.values()):
            return [], {k: names[k] for k in ("persona", "language", "team", "notes", "provider")}
        kwargs = {n: names[n] for n in params if n in names}
        required = [p for p in params.values()
                    if p.default is p.empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                    and p.name not in kwargs]
        args = [profile] if len(required) == 1 else []
        return args, kwargs

    def plays(self, persona: str, language: str, team: str | None, notes: str) -> dict:
        key = (persona, language, team or "", notes or "")
        with self._locks_guard:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:  # two viewers asking for the same profile share one model call
            if key in self._memo:
                return self._memo[key]
            profile = {"persona": persona, "language": language, "team": team, "notes": notes}
            args, kwargs = self._kwargs(profile)
            raw = self.fn(*args, **kwargs)
            items = extract_list(raw)
            cards = [normalize(item, i, team) for i, item in enumerate(items)]
            cards.sort(key=lambda c: (c["order"] is None, c["order"]))
            result = {"plays": cards, "notices": []}
            if not any(c["video_time"] is not None for c in cards):
                result["notices"].append(
                    "No video times found in the explainer output. Add the key name to FIELD_ALIASES['video_time'] in sources.py."
                )
            self._memo[key] = result
            return result


# --------------------------------------------------------------------------- normalizing

def extract_list(raw) -> list:
    if isinstance(raw, (str, bytes)):
        raw = json.loads(raw)
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for k in LIST_KEYS:
            if isinstance(raw.get(k), list):
                return raw[k]
        if all(isinstance(v, dict) for v in raw.values()):  # {play_id: {...}}
            return [{"play_id": k, **v} for k, v in raw.items()]
    raise ValueError("Explainer output is not a list of plays. Check the JSON shape in HANDOFF_CHRIS.md.")


def _flatten(item: dict) -> dict:
    flat = dict(item)
    for nest in ("play", "explanation", "card", "data", "output"):
        if isinstance(item.get(nest), dict):
            for k, v in item[nest].items():
                flat.setdefault(k, v)
    return flat


def _pick(d: dict, names: list):
    for n in names:
        if n in d and d[n] not in (None, ""):
            return d[n]
    return None


def parse_seconds(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return float(s)
    if re.fullmatch(r"\d+(:\d{1,2}){1,2}", s):
        secs = 0
        for part in s.split(":"):
            secs = secs * 60 + int(part)
        return float(secs)
    return None


def parse_impact(v) -> str:
    s = str(v or "").lower()
    if "help" in s or s in ("good", "positive", "+"):
        return "helped"
    if "hurt" in s or s in ("bad", "negative", "-"):
        return "hurt"
    return "neutral"


def parse_wp(v):
    try:
        x = float(str(v).replace("%", ""))
    except (TypeError, ValueError):
        return None
    return x / 100 if abs(x) > 1 else x


def parse_links(v) -> list:
    if not v:
        return []
    if isinstance(v, (str, dict)):
        v = [v]
    links = []
    for x in v:
        if isinstance(x, str):
            links.append({"title": x, "url": x, "source": _domain(x)})
        elif isinstance(x, dict):
            url = x.get("url") or x.get("link") or x.get("href")
            if url:
                links.append({
                    "title": x.get("title") or x.get("headline") or url,
                    "url": url,
                    "source": x.get("source") or x.get("publisher") or _domain(url),
                })
    return [l for l in links if str(l["url"]).startswith(("http://", "https://"))]


def _domain(url: str) -> str:
    m = re.match(r"https?://(www\.)?([^/]+)", str(url))
    return m.group(2) if m else ""


def normalize(item: dict, index: int, viewer_team: str | None) -> dict:
    d = _flatten(item) if isinstance(item, dict) else {"what_happened": str(item)}
    card = {f: _pick(d, FIELD_ALIASES[f]) for f in FIELD_ALIASES}
    score = d.get("score") if isinstance(d.get("score"), dict) else {}
    card["score"] = {
        side: _pick(score, names) if score else _pick(d, names[:2])
        for side, names in SCORE_ALIASES.items()
    }
    card["play_id"] = str(card["play_id"] if card["play_id"] is not None else f"play-{index + 1}")
    try:
        card["order"] = int(card["order"]) if card["order"] is not None else index
    except (TypeError, ValueError):
        card["order"] = index
    card["video_time"] = parse_seconds(card["video_time"])
    card["impact"] = parse_impact(card["impact"])
    card["wp_change"] = parse_wp(card["wp_change"])
    card["read_more"] = parse_links(card["read_more"])
    if isinstance(card["who"], list):
        card["who"] = ", ".join(map(str, card["who"]))
    if not card["impact_team"]:
        # helped/hurt is written for the viewer's team when one is set,
        # otherwise assume it is measured for the team with the ball
        card["impact_team"] = viewer_team or d.get("posteam") or d.get("offense")
    card["source"] = "repo"
    return card


# --------------------------------------------------------------------------- choose

def make_source():
    """PLAY_SOURCE=auto (default) tries the repo first, then sample data."""
    mode = os.environ.get("PLAY_SOURCE", "auto").lower()
    if mode == "sample":
        return SampleSource(), None
    try:
        return RepoSource(), None
    except Exception as exc:  # noqa: BLE001 - any import problem means "not wired yet"
        if mode == "repo":
            raise
        return SampleSource(), f"{type(exc).__name__}: {exc}"
