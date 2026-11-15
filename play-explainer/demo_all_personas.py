"""Builds the explanations file for every persona in one go, and prints one moment side by side.

  python demo_all_personas.py                      # template mode (no key)
  python demo_all_personas.py --provider anthropic # real AI, needs ANTHROPIC_API_KEY

Use the side-by-side print to show judges that the same play reads differently per viewer.
"""
import argparse
import subprocess
import sys
import json
import os

from pipeline.personas import PERSONAS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--game", default="2026_02_IND_KC")
    parser.add_argument("--provider", default="template")
    parser.add_argument("--model", default=None)
    parser.add_argument("--moment", type=int, default=5, help="which moment to compare across personas")
    args = parser.parse_args()

    for name in list(PERSONAS.keys()):
        command = [sys.executable, "explain_game.py", "--game", args.game, "--persona", name, "--provider", args.provider]
        if args.model is not None:
            command = command + ["--model", args.model]
        subprocess.run(command, check=True)

    print("")
    print("Same moment, every viewer:")
    for name in list(PERSONAS.keys()):
        path = os.path.join("data", args.game + "_" + name + "_explained.json")
        with open(path) as f:
            item = json.load(f)[args.moment]
        print("")
        print("[" + PERSONAS[name]["label"] + "]  (" + item["source"] + ")")
        print("  " + item["headline"])
        print("  " + item["what_happened"])
        print("  " + item["why_it_matters"])
        if item.get("pop_culture"):
            print("  * " + item["pop_culture"])


if __name__ == "__main__":
    main()
