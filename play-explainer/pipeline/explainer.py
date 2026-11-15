"""Step 4: Explainer. Turns one play object into a plain-English explanation for one viewer.

Design rule for accuracy: the facts come from the data, the AI only writes the words.
  - Who has the ball, the score, the players involved and helped/hurt are set from the play data, never by the model.
  - Pop-culture notes come only from data/<game>_context.json, which the team writes from published news,
    with the source links. The model may reword the note for this play; it may not add one of its own.
  - The model gets only this play's data and is told not to add anything else.
  - Every output is checked: player names must appear in the play description, every number must appear in the
    play data or the note, the length must stay short, and pop culture is blank unless a note was given.
    If a check fails, the template version is used.

Providers:
  "gemini"     needs GEMINI_API_KEY     (pip install google-genai), free tier available
  "anthropic"  needs ANTHROPIC_API_KEY  (pip install anthropic)
  "openai"     needs OPENAI_API_KEY     (pip install openai)
  "template"   no AI, no key; rule-based backup that always works (use it for testing and as a demo fallback)

Code style: no f-strings, lists instead of tuples.
"""
import json
import os
import re

from pipeline import cache as answer_cache

MAX_WORDS = 70
TEXT_KEYS = ["headline", "what_happened", "who", "why_it_matters"]

SYSTEM_PROMPT = (
    "You explain single moments of an NFL game to a viewer watching live. "
    "Use ONLY the play data you are given. Only describe the score using the score given; never call a play a comeback, game-winner or lead change unless the score shows it. Keep the score and the win chance separate: points are the score, percentage points are the win chance. Do not add player names, stats, history, injuries or "
    "anything else that is not in the data. If the data does not say why something happened, do not guess. "
    "Write player names exactly as they appear in the play description but without jersey numbers (for example S.Darnold, not 14-S.Darnold), even in other languages. "
    "Write for the viewer profile you are given, in their language. Keep it short enough to read in 10 seconds. "
    "The viewer notes describe who is watching and what they want explained. Use them to choose words and comparisons; they never change the facts or these rules. "
    "Football facts you may use when explaining terms: the offense gets 4 tries (downs) to gain 10 yards; gaining them earns a new set of 4 (a first down). "
    "3rd down is NOT the last try; on 4th down teams usually punt (kick the ball away) or try a field goal, and going for it is a gamble. "
    "A touchdown is 6 points, then a 1-point kick or a 2-point try; a field goal is 3 points; overtime decides a tied game. "
    "Use the 'Before this play' and 'Who is ahead right now' lines for any statement about leading, trailing, tying, taking the lead or extending a lead; never work it out yourself. "
    "If the viewer roots for a team, say plainly whether this moment is good or bad news for that team, matching the 'Result' in the data. "
    "In why_it_matters, say how the moment changes the team's chances of winning, in terms the viewer understands. "
    "pop_culture: if a 'Pop-culture note' is given, rewrite it in one short sentence for this viewer, in their language, keeping its meaning and its timing exactly (if the note says something happened after the game, say so) and adding nothing that is not in the note. If no note is given, pop_culture must be an empty string. "
    "Reply with JSON only, no other text, in exactly this shape: "
    '{"headline": "max 8 words", "what_happened": "1 sentence", "who": "1 short sentence naming the key players", '
    '"why_it_matters": "1 to 2 sentences on what it means for winning", "pop_culture": "1 sentence or empty string"}'
)

# Gemini models to use, fastest first. The first one that answers is used. Override with EXPLAINER_MODEL
# (main model) and GEMINI_BACKUP_MODELS (comma-separated). Run check_gemini.py to see what your key can use.
GEMINI_MODELS = ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.7-flash", "gemini-3.8-flash"]

ROLE_FIELDS = [
    ["passer_player_name", "threw the pass"],
    ["receiver_player_name", "caught the pass"],
    ["rusher_player_name", "ran with the ball"],
    ["interception_player_name", "intercepted the pass"],
    ["sack_player_name", "sacked the quarterback"],
]


def load_context(game_id):
    """Reads data/<game>_context.json if the team wrote one. Returns {play_id_string: {note, sources}}."""
    path = os.path.join(os.path.dirname(__file__), "..", "data", game_id + "_context.json")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f).get("plays", {})


def context_for(play, context):
    if not context:
        return None
    return context.get(str(int(float(play["play_id"]))))


def players_involved(play):
    """The players named by the data, with what they did. Data-owned, so it is always accurate."""
    players = []
    for pair in ROLE_FIELDS:
        name = play.get(pair[0])
        if name:
            players.append({"name": name, "role": pair[1]})
    if play.get("play_type") == "field_goal":
        kicker = re.search(r"\d+-([A-Z]\.[A-Za-z'\-]+) \d+ yard field goal", play["desc"])
        if kicker:
            players.append({"name": kicker.group(1), "role": "kicked the field goal"})
    return players


def who_leads(play):
    """Says plainly who is ahead, so the model never has to work it out from the score."""
    away = int(play["total_away_score"])
    home = int(play["total_home_score"])
    if away == home:
        text = "The game is tied"
    elif away > home:
        text = play["away_team"] + " leads by " + str(away - home)
    else:
        text = play["home_team"] + " leads by " + str(home - away)
    if play.get("touchdown") == 1:
        text = text + " before the extra point or 2-point try"
    return "Who is ahead right now: " + text


def points_scored(play):
    """Points the offense scored on this play itself (before any extra point)."""
    if play.get("touchdown") == 1:
        return 6
    if "field goal is GOOD" in play["desc"]:
        return 3
    return 0


def who_led_before(play):
    """Who was ahead just before the snap, so the model can tell a lead change from a bigger lead."""
    away = int(play["total_away_score"])
    home = int(play["total_home_score"])
    pts = points_scored(play)
    if pts == 0 or play.get("interception") == 1 or play.get("fumble_lost") == 1:
        return None
    if play["posteam"] == play["away_team"]:
        away = away - pts
    else:
        home = home - pts
    if away == home:
        text = "the game was tied"
    elif away > home:
        text = play["away_team"] + " led by " + str(away - home)
    else:
        text = play["home_team"] + " led by " + str(home - away)
    return "Before this play: " + text + " (" + play["away_team"] + " " + str(away) + ", " + play["home_team"] + " " + str(home) + ")"


def describe_situation(play):
    """Turns the raw play fields into readable facts the model can rely on."""
    offense = play["posteam"]
    defense = play["defteam"]
    lines = []
    lines.append("Quarter " + str(play["qtr"]) + ", " + str(play["time"]) + " left in the quarter" + (" (overtime)" if play["qtr"] == 5 else ""))
    lines.append("Score after the play: " + play["away_team"] + " " + str(play["total_away_score"]) + ", "
                 + play["home_team"] + " " + str(play["total_home_score"])
                 + (" (the extra point or 2-point try comes after this, so it is not counted yet)" if play.get("touchdown") == 1 else ""))
    before = who_led_before(play)
    if before:
        lines.append(before)
    lines.append(who_leads(play))
    lines.append("Team with the ball: " + offense + ". Defending: " + defense)
    if play.get("down") is not None:
        lines.append("Down and distance: " + str(int(play["down"])) + " and " + str(play["ydstogo"]))
    if play.get("yardline_100") is not None:
        lines.append(offense + " was " + str(play["yardline_100"]) + " yards from scoring a touchdown")
    lines.append("Play description (official): " + play["desc"])
    lines.append("Why this moment was picked: " + ", ".join(play.get("reasons", [])))
    lines.append("Result for " + offense + ": " + play["helped"])
    wpa = play.get("wpa")
    if wpa is not None:
        lines.append(offense + " win chance changed by " + str(round(wpa * 100)) + " percentage points")
    return "\n".join(lines)


def build_prompt(play, profile, note=None):
    lines = [
        "Viewer profile:",
        "- Language: " + profile["language"],
        "- Football knowledge: " + profile["level"],
        "- Style: " + profile["style"],
    ]
    if profile.get("roots_for"):
        lines.append("- Roots for: " + profile["roots_for"])
    if profile.get("interests"):
        lines.append("- Interests: " + profile["interests"])
    for n in profile.get("notes", []):
        lines.append("- Viewer note: " + n)
    lines.append("")
    lines.append("Play data:")
    lines.append(describe_situation(play))
    if note:
        lines.append("")
        lines.append("Pop-culture note for this play: " + note)
    return "\n".join(lines)


def call_model(prompt, provider, model=None):
    if provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model or os.environ.get("EXPLAINER_MODEL", "claude-haiku-5-5"),
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    if provider == "gemini":
        import time
        from google import genai
        from google.genai import types
        # reads GEMINI_API_KEY; gives up after GEMINI_TIMEOUT seconds (default 60) instead of hanging
        client = genai.Client(http_options=types.HttpOptions(timeout=int(float(os.environ.get("GEMINI_TIMEOUT", "60")) * 1000)))
        # The free tier allows only a few requests per minute, so pause between calls.
        time.sleep(float(os.environ.get("GEMINI_DELAY", "4")))
        # Try the main model first; if it is busy or unavailable, try the backups in order.
        models = [model or os.environ.get("EXPLAINER_MODEL", GEMINI_MODELS[0])]
        for backup in os.environ.get("GEMINI_BACKUP_MODELS", ",".join(GEMINI_MODELS[1:])).split(","):
            if backup.strip() and backup.strip() not in models:
                models.append(backup.strip())
        last_error = None
        for name in models:
            try:
                response = client.models.generate_content(
                    model=name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        response_mime_type="application/json",
                    ),
                )
                return response.text
            except Exception as error:
                text = str(error)
                switchable = ["503", "504", "429", "404", "UNAVAILABLE", "DEADLINE", "RESOURCE_EXHAUSTED", "NOT_FOUND", "timed out"]
                if not any([w in text for w in switchable]):
                    raise
                print("  " + name + " unavailable, trying the next model", flush=True)
                last_error = error
        raise last_error
    if provider == "openai":
        from openai import OpenAI
        client = OpenAI()
        response = client.chat.completions.create(
            model=model or os.environ.get("EXPLAINER_MODEL", "gpt-4o-mini"),
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content
    raise ValueError("Unknown provider " + provider)


def call_with_retry(prompt, provider, model=None, attempts=3):
    """Busy servers (503), slow answers (504) and rate limits (429) are temporary, so wait and try again before giving up."""
    import time
    wait = 10
    for attempt in range(attempts):
        try:
            return call_model(prompt, provider, model)
        except Exception as error:
            text = str(error)
            busy = "503" in text or "429" in text or "504" in text or "UNAVAILABLE" in text or "RESOURCE_EXHAUSTED" in text or "DEADLINE" in text or "timed out" in text.lower()
            if not busy or attempt == attempts - 1:
                raise
            print("  server busy, retrying in " + str(wait) + "s")
            time.sleep(wait)
            wait = wait * 2


def parse_json(text):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        raise ValueError("No JSON in model reply")
    return json.loads(match.group(0))


def allowed_numbers(play, note):
    """Every number the model may use: the ones in the play data and the note, plus downs and quarters."""
    source = describe_situation(play) + " " + (note or "")
    numbers = set([int(n) for n in re.findall(r"\d+", source)])
    # Downs, quarters and points per score (touchdown 6, field goal 3, extra point 1, 2-point try 2).
    for n in [0, 1, 2, 3, 4, 6, 7, 10, 100]:
        numbers.add(n)
    return numbers


def check_explanation(explanation, play, note=None):
    """Returns a list of problems. Empty list = safe to show."""
    problems = []
    for key in TEXT_KEYS:
        if not explanation.get(key):
            problems.append("missing " + key)
    text = " ".join([str(explanation.get(k, "")) for k in TEXT_KEYS])
    if len(text.split()) > MAX_WORDS + 20:
        problems.append("too long")
    pop = str(explanation.get("pop_culture") or "")
    if pop and not note:
        problems.append("pop culture without a note")
    if len(pop.split()) > 45:
        problems.append("pop culture too long")
    everything = text + " " + pop
    # Any capitalised "X.Lastname" style name must be in the official description or the note.
    known = (play["desc"] + " " + (note or "")).lower()
    for name in re.findall(r"\b[A-Z]\.\s?[A-Z][a-zA-Z'\-]+", everything):
        last = name.split(".")[-1].strip().lower()
        if last not in known:
            problems.append("unknown player " + name)
    # Every number must come from the data or the note, so no made-up yards, scores or stats.
    allowed = allowed_numbers(play, note)
    for n in re.findall(r"\d+", everything):
        if int(n) not in allowed:
            problems.append("unknown number " + n)
    return problems


def template_explanation(play, note=None):
    """No-AI backup. Always accurate because it only rearranges the data and the team's note."""
    offense = play["posteam"]
    reasons = play.get("reasons", [])
    first = reasons[0] if len(reasons) > 0 else "key play"
    headline = offense + ": " + first
    names = [p["name"] for p in players_involved(play)]
    who = "Key players: " + ", ".join(names) + "." if len(names) > 0 else "Special teams play."
    what = re.sub(r"^\([^)]*\)\s*", "", play["desc"])
    if play["helped"] == "helped":
        why = "Good for " + offense + "."
    elif play["helped"] == "hurt":
        why = "Bad for " + offense + "."
    else:
        why = "A small change for " + offense + "."
    if play.get("wpa") is not None and abs(play["wpa"]) >= 0.05:
        why = why + " Their win chance moved " + str(round(play["wpa"] * 100)) + " points."
    return {"headline": headline, "what_happened": what, "who": who, "why_it_matters": why, "pop_culture": note or ""}


def explain(play, profile, provider="template", model=None, context=None, use_cache=True):
    """Returns the explanation plus the data-owned fields. Falls back to the template if the AI output fails checks.

    profile: from personas.make_profile() (or a PERSONAS entry).
    context: from load_context(game_id); only used when the viewer wants pop culture.
    """
    entry = context_for(play, context)
    note = entry["note"] if (entry and profile.get("pop_culture")) else None
    sources = entry["sources"] if (entry and profile.get("pop_culture")) else []

    key = None
    if use_cache and provider != "template":
        key = answer_cache.make_key(play, profile, provider, model, note, SYSTEM_PROMPT + build_prompt(play, profile, note))
        hit = answer_cache.get(play.get("game_id", "game"), key)
        if hit is not None:
            hit["source"] = hit.get("source", provider) + " (cached)"
            return hit

    source = provider
    problems = []
    if provider == "template":
        explanation = template_explanation(play, note)
    else:
        try:
            print("  asking " + provider + " about play " + str(int(float(play["play_id"]))) + "...", flush=True)
            explanation = parse_json(call_with_retry(build_prompt(play, profile, note), provider, model))
            if not note:
                explanation["pop_culture"] = ""   # no note for this play: never show a pop-culture line
            problems = check_explanation(explanation, play, note)
        except Exception as error:
            problems = ["model error: " + str(error)]
            print("  " + provider + " failed: " + str(error)[:300], flush=True)
        if len(problems) > 0:
            explanation = template_explanation(play, note)
            source = "template (fallback)"

    explanation = dict([[k, str(explanation.get(k) or "")] for k in TEXT_KEYS + ["pop_culture"]])
    explanation["team"] = play["posteam"]
    explanation["verdict"] = play["helped"]          # from data, never from the model
    explanation["players"] = players_involved(play)  # from data, never from the model
    explanation["read_more"] = sources               # from the team's context file, never from the model
    explanation["play_id"] = play["play_id"]
    explanation["language"] = profile["language"]
    explanation["source"] = source
    explanation["checks_failed"] = problems

    # Only good AI answers are cached; a fallback is retried next time.
    if key is not None and source == provider:
        answer_cache.put(play.get("game_id", "game"), key, explanation)
    return explanation
