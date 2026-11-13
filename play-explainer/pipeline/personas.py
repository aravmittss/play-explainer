"""Viewer profiles. Each one changes how the explanation is written, never what the facts are."""

PERSONAS = {
    "new_fan": {
        "label": "Brand new to American football",
        "language": "English",
        "level": "beginner",
        "style": "plain everyday language, no jargon; if a football term is needed, define it in a few words",
    },
    "soccer_fan": {
        "label": "Soccer fan",
        "language": "English",
        "level": "beginner",
        "style": "compare to soccer when it genuinely helps (e.g. a turnover is like losing the ball in your own half)",
    },
    "cricket_fan_hindi": {
        "label": "Cricket fan, Hindi",
        "language": "Hindi",
        "level": "beginner",
        "style": "compare to cricket when it genuinely helps (e.g. a 3rd down is like defending the last over)",
    },
    "spanish_casual": {
        "label": "Casual fan, Spanish",
        "language": "Spanish",
        "level": "casual",
        "style": "knows the basics; focus on why the moment matters for the result",
    },
    "expert": {
        "label": "Knows football well",
        "language": "English",
        "level": "expert",
        "style": "concise, can use football terms; focus on the strategic stakes",
    },
}


def get_persona(name):
    if name not in PERSONAS:
        raise ValueError("Unknown persona " + name + ". Options: " + ", ".join(list(PERSONAS.keys())))
    return PERSONAS[name]
