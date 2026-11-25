"""Video sync. Links each big moment to the second it happens in the game video.

Workflow (about an hour for one game, done once):
  1. python explain_game.py --make-timestamps   -> writes data/<game>_timestamps.csv with one row per big moment
  2. Open the video, find each play, fill in video_start (seconds) for each row. video_end is optional.
  3. explain_game.py reads the CSV and puts the times into every explanation.
"""
import csv
import os


def timestamps_path(game_id):
    return os.path.join(os.path.dirname(__file__), "..", "data", game_id + "_timestamps.csv")


def write_template(game_id, moments):
    path = timestamps_path(game_id)
    if os.path.exists(path):
        raise FileExistsError(path + " already exists; delete it first if you want a fresh one")
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["play_id", "qtr", "clock", "description", "video_start", "video_end"])
        for play in moments:
            writer.writerow([play["play_id"], play["qtr"], play["time"], play["desc"][:90], "", ""])
    return path


def load_timestamps(game_id):
    """Returns {play_id: [start, end]}. Rows without a start time are skipped."""
    path = timestamps_path(game_id)
    times = {}
    if not os.path.exists(path):
        return times
    with open(path) as f:
        for row in csv.DictReader(f):
            if row["video_start"].strip() == "":
                continue
            start = float(row["video_start"])
            end = float(row["video_end"]) if row["video_end"].strip() != "" else start + 12.0
            times[float(row["play_id"])] = [start, end]
    return times
