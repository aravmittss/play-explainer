"""Checks your Gemini key: lists the models it can use and times a tiny request on each "flash" model.

  python3 check_gemini.py

Then use the fastest one:  export EXPLAINER_MODEL=<model name>

Code style: no f-strings, lists instead of tuples.
"""
import time

from google import genai
from google.genai import types

client = genai.Client(http_options=types.HttpOptions(timeout=45000))  # reads GEMINI_API_KEY

names = []
for m in client.models.list():
    actions = getattr(m, "supported_actions", None) or []
    if "generateContent" in actions and "flash" in m.name and "image" not in m.name and "2.5" not in m.name:
        names.append(m.name.replace("models/", ""))
print("Flash models your key can use: " + ", ".join(names))
print("")

for name in names:
    start = time.time()
    try:
        r = client.models.generate_content(model=name, contents='Reply with JSON only: {"ok": true}',
                                           config=types.GenerateContentConfig(response_mime_type="application/json"))
        print(name + ": " + str(round(time.time() - start, 1)) + "s  " + (r.text or "").strip()[:40])
    except Exception as error:
        print(name + ": failed after " + str(round(time.time() - start, 1)) + "s  " + str(error)[:60])
    time.sleep(2)
