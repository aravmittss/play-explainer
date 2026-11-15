"""Viewer profiles. Each one changes how the explanation is written, never what the facts are.

A profile has:
  label      shown in the persona dropdown
  language   language to write in
  level      football knowledge: beginner, casual or expert
  style      how to explain (comparisons, tone)
  interests  what the viewer cares about besides football; "" if nothing special
  roots_for  the team the viewer cheers for, if any (optional)
  pop_culture  True if the viewer wants the pop-culture notes for the game (see data/<game>_context.json)
  notes      anything the viewer typed in the chat box, added with make_profile()

Code style: no f-strings, lists instead of tuples.
"""

PERSONAS = {
    "swiftie": {
        "label": "Swiftie girlfriend",
        "language": "English",
        "level": "beginner",
        "style": "warm and friendly, like a friend sitting next to her; plain words, define any football term in a few words",
        "interests": "Taylor Swift and pop culture; her boyfriend loves the Chiefs and she wants to understand enough to share it with him",
        "roots_for": "KC (Kansas City Chiefs), her boyfriend's team",
        "pop_culture": True,
    },
    "new_fan": {
        "label": "Brand new to American football",
        "language": "English",
        "level": "beginner",
        "style": "plain everyday language, no jargon; if a football term is needed, define it in a few words",
        "interests": "",
        "pop_culture": False,
    },
    "soccer_fan": {
        "label": "Soccer fan",
        "language": "English",
        "level": "beginner",
        "style": "compare to soccer when it genuinely helps (e.g. a turnover is like losing the ball in your own half)",
        "interests": "soccer",
        "pop_culture": False,
    },
    "cricket_fan_hindi": {
        "label": "Cricket fan, Hindi",
        "language": "Hindi",
        "level": "beginner",
        "style": "compare to cricket when it genuinely helps (e.g. a 3rd down is like defending the last over)",
        "interests": "cricket",
        "pop_culture": False,
    },
    "spanish_casual": {
        "label": "Casual fan, Spanish",
        "language": "Spanish",
        "level": "casual",
        "style": "knows the basics; focus on why the moment matters for the result",
        "interests": "",
        "pop_culture": False,
    },
    "expert": {
        "label": "Knows football well",
        "language": "English",
        "level": "expert",
        "style": "concise, can use football terms; focus on the strategic stakes",
        "interests": "",
        "pop_culture": False,
    },
}

POP_WORDS = ["taylor", "swift", "pop culture", "celebrity", "celebrities", "gossip", "music", "concert", "kelce"]


def get_persona(name):
    if name not in PERSONAS:
        raise ValueError("Unknown persona " + name + ". Options: " + ", ".join(list(PERSONAS.keys())))
    return PERSONAS[name]


def make_profile(persona_name, language=None, notes=None):
    """Starts from a preset and layers on what the viewer chose or typed.

    language: from the language dropdown; None keeps the preset's language.
    notes:    list of chat messages describing the viewer ("she also loves tennis", "explain penalties").
    """
    profile = dict(get_persona(persona_name))
    profile["persona"] = persona_name
    if language:
        profile["language"] = language
    profile["notes"] = [str(n).strip()[:300] for n in (notes or []) if str(n).strip()]
    # Typing about Taylor or pop culture in the chat turns the pop-culture notes on for any persona.
    joined = " ".join(profile["notes"]).lower()
    for word in POP_WORDS:
        if word in joined:
            profile["pop_culture"] = True
    return profile
