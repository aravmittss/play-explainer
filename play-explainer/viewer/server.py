#!/usr/bin/env python3
"""Viewer server for the play explainer. Standard library only, no installs.

    python3 viewer/server.py            # then open http://localhost:8080
    PLAY_SOURCE=sample python3 viewer/server.py   # force placeholder data

Endpoints
    GET  /                 viewer screen
    GET  /api/health       {"ok": true, "source": "repo" | "sample"}
    GET  /api/config       game, video, personas, languages
    GET  /api/plays        ?persona=swiftie&language=en&team=KC&notes=...
    POST /api/plays        same fields as a JSON body (use this for long notes)

The Gemini key is read from the environment (GEMINI_API_KEY) or from a .env
file in the repo root or in viewer/. Never commit the key.
"""

from __future__ import annotations

import json
import mimetypes
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
sys.path.insert(0, str(HERE))


def load_dotenv() -> None:
    for path in (HERE.parent / ".env", HERE / ".env"):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.removeprefix("export ").strip()
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


load_dotenv()
import sources  # noqa: E402  (after .env so the explainer sees the key on import)

CONFIG = sources.load_config()
SOURCE, SOURCE_ERROR = sources.make_source()
if SOURCE_ERROR:
    print(f"[viewer] Explainer not connected, using sample data. Reason: {SOURCE_ERROR}", file=sys.stderr)
else:
    print(f"[viewer] Using source: {SOURCE.name}", file=sys.stderr)


def public_config() -> dict:
    # ready: answers are cached, so switching is instant
    # selectable: can be picked at all (sample data only has a couple of personas)
    personas = []
    for p in CONFIG["personas"]:
        if SOURCE.name == "sample":
            has = SOURCE.persona_ready(p["id"])
            personas.append(dict(p, ready=has, selectable=has))
        else:
            personas.append(dict(p, ready=bool(p.get("ready")), selectable=True))
    notices = []  # the sample source adds its own banner text; the terminal shows why the repo didn't load
    return {
        "source": SOURCE.name,
        "game": CONFIG["game"],
        "video": CONFIG["video"],
        "personas": personas,
        "default_persona": CONFIG.get("default_persona", personas[0]["id"]),
        "languages": CONFIG["languages"],
        "notices": notices,
    }


def clean_params(raw: dict) -> dict:
    persona_ids = {p["id"] for p in CONFIG["personas"]}
    language_codes = {l["code"] for l in CONFIG["languages"]}
    teams = {CONFIG["game"]["away"]["abbr"], CONFIG["game"]["home"]["abbr"]}
    persona = str(raw.get("persona") or CONFIG.get("default_persona"))
    language = str(raw.get("language") or "en")
    team = str(raw.get("team") or "").upper() or None
    notes = str(raw.get("notes") or "").strip()[:500]
    if persona not in persona_ids:
        raise ValueError(f"Unknown persona '{persona}'.")
    if language not in language_codes:
        raise ValueError(f"Unknown language '{language}'.")
    if team and team not in teams:
        raise ValueError(f"Unknown team '{team}'. Use {' or '.join(sorted(teams))}.")
    return {"persona": persona, "language": language, "team": team, "notes": notes}


class Handler(BaseHTTPRequestHandler):
    server_version = "PlayExplainerViewer/1.0"

    def log_message(self, fmt, *args):  # quieter logs
        sys.stderr.write(f"[viewer] {self.command} {self.path.split('?')[0]} {args[1] if len(args) > 1 else ''}\n")

    # ---- helpers
    def send_cors(self) -> None:
        # Lets a frontend on another domain (Lovable, Vercel) call this API.
        # Set CORS_ORIGIN=https://your-app.lovable.app to lock it to one site.
        self.send_header("Access-Control-Allow-Origin", os.environ.get("CORS_ORIGIN", "*"))
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")  # https page -> localhost in Chrome
        self.send_header("Access-Control-Max-Age", "600")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def send_json(self, status: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_file(self, path: Path) -> None:
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def plays_response(self, raw: dict) -> None:
        try:
            params = clean_params(raw)
        except ValueError as exc:
            return self.send_json(400, {"error": str(exc)})
        try:
            result = SOURCE.plays(**params)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            return self.send_json(502, {"error": f"The explainer failed: {type(exc).__name__}: {exc}"})
        self.send_json(200, {"source": SOURCE.name, "profile": params, **result})

    # ---- routes
    def do_GET(self) -> None:
        url = urlparse(self.path)
        path = url.path
        if path in ("/", "/index.html"):
            return self.send_file(STATIC / "index.html")
        if path == "/api/health":
            return self.send_json(200, {"ok": True, "source": SOURCE.name, "fallback_reason": SOURCE_ERROR})
        if path == "/api/config":
            return self.send_json(200, public_config())
        if path == "/api/plays":
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            return self.plays_response(q)
        if path.startswith("/static/"):
            target = (STATIC / path.removeprefix("/static/")).resolve()
            if target.is_file() and STATIC.resolve() in target.parents:
                return self.send_file(target)
        self.send_json(404, {"error": f"No page at {path}"})

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/plays":
            return self.send_json(404, {"error": "Only /api/plays accepts POST."})
        length = min(int(self.headers.get("Content-Length") or 0), 10_000)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self.send_json(400, {"error": "Body must be JSON."})
        self.plays_response(body if isinstance(body, dict) else {})


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    host = os.environ.get("HOST", "0.0.0.0")
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"[viewer] Open http://localhost:{port}", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
