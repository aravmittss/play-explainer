"""Step 2: Replay engine. Releases plays on a timer so a past game feels live.

Two modes:
  speed=N   follows the real game clock, N times faster (speed=60 -> one game minute per second)
  fixed=S   one play every S seconds, ignoring the clock (best for a demo)
"""
import time


def replay(plays, speed=None, fixed=None, max_wait=8.0):
    """Yields plays one at a time, sleeping between them. Use in a for loop."""
    previous = None
    for play in plays:
        if previous is not None:
            time.sleep(wait_seconds(previous, play, speed, fixed, max_wait))
        yield play
        previous = play


def wait_seconds(previous, play, speed, fixed, max_wait):
    if fixed is not None:
        return fixed
    if speed is None:
        return 0
    a = previous.get("game_seconds_remaining")
    b = play.get("game_seconds_remaining")
    if a is None or b is None:
        return 0
    gap = max(a - b, 0) / float(speed)
    return min(gap, max_wait)  # never stall the demo on a long timeout or halftime
