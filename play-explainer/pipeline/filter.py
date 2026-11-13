"""Step 3: Filter. Keeps only high-leverage plays and says why each one made the cut.

Scope from the team: 3rd and 4th downs, scores, turnovers, and big win-probability swings.
"""

BIG_SWING = 0.10  # a play that moves win probability by 10 points or more


def leverage_reasons(play):
    """Returns the list of reasons this play matters. Empty list = skip it."""
    reasons = []
    if play.get("touchdown") == 1:
        reasons.append("touchdown")
    if play.get("field_goal_result") == "made":
        reasons.append("field goal")
    if play.get("safety") == 1:
        reasons.append("safety")
    if play.get("interception") == 1:
        reasons.append("interception")
    if play.get("fumble_lost") == 1:
        reasons.append("fumble lost")
    if play.get("down") in [3, 4] and play.get("play_type") in ["pass", "run"]:
        label = "3rd down" if int(play["down"]) == 3 else "4th down"
        converted = play.get("third_down_converted") == 1 or play.get("fourth_down_converted") == 1
        stopped = play.get("third_down_failed") == 1 or play.get("fourth_down_failed") == 1
        if converted:
            reasons.append(label + " converted")
        elif stopped and (int(play["down"]) == 4 or is_crunch_time(play)):
            # A failed 3rd down is routine; keep it only late in a close game. Failed 4th downs always count.
            reasons.append(label + " stopped")
    wpa = play.get("wpa")
    if wpa is not None and abs(wpa) >= BIG_SWING:
        reasons.append("big swing (" + str(round(wpa * 100)) + " pts win prob)")
    return reasons


def is_crunch_time(play):
    """4th quarter or overtime, with the game within 8 points (one score)."""
    margin = abs(play.get("total_home_score", 0) - play.get("total_away_score", 0))
    return play.get("qtr", 0) >= 4 and margin <= 8


def high_leverage(plays):
    """Returns only the plays worth explaining, each with a 'reasons' list attached."""
    kept = []
    for play in plays:
        reasons = leverage_reasons(play)
        if len(reasons) > 0:
            play = dict(play)
            play["reasons"] = reasons
            kept.append(play)
    return kept
