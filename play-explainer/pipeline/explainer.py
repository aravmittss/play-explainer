"""Step 4: Explainer. Turns one play object into a plain-English explanation.

Design rule for accuracy: the facts come from the data, the AI only writes the words.
  - Who has the ball, the score, and helped/hurt are set from the play data, never by the model.
  - The model gets only this play's data and is told not to add anything else.
  - Every output is checked: player names must appear in the play description, the verdict must
    match the data, and the length must stay short. If a check fails, the template version is used.

Providers:
  "anthropic"  needs ANTHROPIC_API_KEY  (pip install anthropic)
  "gemini"     needs GEMINI_API_KEY     (pip install google-genai), free tier available
  "openai"     needs OPENAI_API_KEY     (pip install openai)
  "template"   no AI, no key; rule-based backup that always works (use it for testing and as a demo fallback)

Code style: no f-strings, lists instead of tuples.
"""
import json
import os
import re

MAX_WORDS = 70

SYSTEM_PROMPT = (
    "You explain single moments of an NFL game to a viewer watching live. "
    "Use ONLY the play data you are given. Only describe the score using the score given; never call a play a comeback, game-winner or lead change unless the score shows it. Keep the score and the win chance separate: points are the score, percentage points are the win chance. Do not add player names, stats, history, injuries or "
    "anything else that is not in the data. If the data does not say why something happened, do not guess. "
    "Write player names exactly as they appear in the play description but without jersey numbers (for example S.Darnold, not 14-S.Darnold), even in other languages. "
    "Write for the viewer profile you are given, in their language. Keep it short enough to read in 10 seconds. "
    "Reply with JSON only, no other text, in exactly this shape: "
    '{"headline": "max 8 words", "what_happened": "1 sentence", "who": "1 short sentence naming the key players", '
    '"why_it_matters": "1 to 2 sentences on what it means for the game"}'
)


def describe_situation(play):
    """Turns the raw play fields into readable facts the model can rely on."""
    offense = play["posteam"]
    defense = play["defteam"]
    lines = []
    lines.append("Quarter " + str(play["qtr"]) + ", " + str(play["time"]) + " left in the quarter")
    lines.append("Score after the play: " + play["away_team"] + " " + str(play["total_away_score"]) + ", "
                 + play["home_team"] + " " + str(play["total_home_score"]))
    lines.append("Team with the ball: " + offense + ". Defending: " + defense)
    if play.get("down") is not None:
        lines.append("Down and distance: " + str(play["down"]) + " and " + str(play["ydstogo"]))
    if play.get("yardline_100") is not None:
        lines.append(offense + " was " + str(play["yardline_100"]) + " yards from scoring a touchdown")
    lines.append("Play description (official): " + play["desc"])
    lines.append("Why this moment was picked: " + ", ".join(play.get("reasons", [])))
    lines.append("Result for " + offense + ": " + play["helped"])
    wpa = play.get("wpa")
    if wpa is not None:
        lines.append(offense + " win chance changed by " + str(round(wpa * 100)) + " percentage points")
    return "\n".join(lines)


def build_prompt(play, persona):
    return (
        "Viewer profile:\n"
        + "- Language: " + persona["language"] + "\n"
        + "- Football knowledge: " + persona["level"] + "\n"
        + "- Style: " + persona["style"] + "\n\n"
        + "Play data:\n" + describe_situation(play)
    )


def call_model(prompt, provider, model=None):
    if provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model or os.environ.get("EXPLAINER_MODEL", "claude-haiku-5-5"),
            max_tokens=400,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    if provider == "gemini":
        import time
        from google import genai
        from google.genai import types
        client = genai.Client()  # reads GEMINI_API_KEY
        # The free tier allows only a few requests per minute, so pause between calls.
        time.sleep(float(os.environ.get("GEMINI_DELAY", "5")))
        response = client.models.generate_content(
            model=model or os.environ.get("EXPLAINER_MODEL", "gemini-3.8-flash"),
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
            ),
        )
        return response.text
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


def call_with_retry(prompt, provider, model=None, attempts=4):
    """Busy servers (503) and rate limits (429) are temporary, so wait and try again before giving up."""
    import time
    wait = 10
    for attempt in range(attempts):
        try:
            return call_model(prompt, provider, model)
        except Exception as error:
            text = str(error)
            busy = "503" in text or "429" in text or "UNAVAILABLE" in text or "RESOURCE_EXHAUSTED" in text
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


def check_explanation(explanation, play):
    """Returns a list of problems. Empty list = safe to show."""
    problems = []
    for key in ["headline", "what_happened", "who", "why_it_matters"]:
        if not explanation.get(key):
            problems.append("missing " + key)
    text = " ".join([str(explanation.get(k, "")) for k in ["headline", "what_happened", "who", "why_it_matters"]])
    if len(text.split()) > MAX_WORDS + 20:
        problems.append("too long")
    # Any capitalised "X.Lastname" style name must be in the official description.
    known = play["desc"].lower()
    for name in re.findall(r"\b[A-Z]\.\s?[A-Z][a-zA-Z'\-]+", text):
        last = name.split(".")[-1].strip().lower()
        if last not in known:
            problems.append("unknown player " + name)
    return problems


def template_explanation(play):
    """No-AI backup. Always accurate because it only rearranges the data."""
    offense = play["posteam"]
    reasons = play.get("reasons", [])
    first = reasons[0] if len(reasons) > 0 else "key play"
    headline = offense + ": " + first
    players = [p for p in [play.get("passer_player_name"), play.get("receiver_player_name"),
                           play.get("rusher_player_name"), play.get("interception_player_name"),
                           play.get("sack_player_name")] if p]
    who = "Key players: " + ", ".join(players) + "." if len(players) > 0 else "Special teams play."
    what = re.sub(r"^\([^)]*\)\s*", "", play["desc"])
    if play["helped"] == "helped":
        why = "Good for " + offense + "."
    elif play["helped"] == "hurt":
        why = "Bad for " + offense + "."
    else:
        why = "A small change for " + offense + "."
    if play.get("wpa") is not None and abs(play["wpa"]) >= 0.05:
        why = why + " Their win chance moved " + str(round(play["wpa"] * 100)) + " points."
    return {"headline": headline, "what_happened": what, "who": who, "why_it_matters": why}


def explain(play, persona, provider="template", model=None):
    """Returns the explanation plus the data-owned fields. Falls back to the template if the AI output fails checks."""
    source = provider
    problems = []
    if provider == "template":
        explanation = template_explanation(play)
    else:
        try:
            explanation = parse_json(call_with_retry(build_prompt(play, persona), provider, model))
            problems = check_explanation(explanation, play)
        except Exception as error:
            problems = ["model error: " + str(error)]
        if len(problems) > 0:
            explanation = template_explanation(play)
            source = "template (fallback)"

    explanation["team"] = play["posteam"]
    explanation["verdict"] = play["helped"]          # from data, never from the model
    explanation["play_id"] = play["play_id"]
    explanation["source"] = source
    explanation["checks_failed"] = problems
    return explanation
