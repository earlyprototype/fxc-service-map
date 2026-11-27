#!/usr/bin/env python3
"""
FXC Service Map dev server with an optional AI Service Finder.

Serves index.html and _data/entities.json on loopback. POST /api/chat asks a
provider to match a client's need to a service in the catalogue.

The optional provider configuration lives in ~/.config/fxc-service-map/chat_config.json.
The map works without it.

Run python chat_server.py and open http://127.0.0.1:8020/.
"""

import json
import os
import stat
import urllib.request
from contextlib import ExitStack
from datetime import timezone
from email.utils import parsedate_to_datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SITE = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8020


def read_catalogue():
    with open_regular_file(SITE / "_data" / "entities.json", public_asset=True) as stream:
        return json.load(stream)


def build_catalogue():
    data = read_catalogue()
    cat = {c["id"]: c["label"] for c in data["categories"]}
    pil = {p["id"]: p["label"] for p in data["pillars"]}
    par = {p["id"]: p for p in data["partners"]}
    lines = []
    for s in data["services"]:
        p = par[s["partner"]]
        soft = f" / {cat[s['soft']]}" if s.get("soft") else ""
        lines.append(
            f"- {s['label']} | partner: {p['label']} ({p['contact']}) | "
            f"category: {cat[s['category']]}{soft} | pillar: {pil[s['pillar']]} | "
            f"{s['desc']} | {s['url']}"
        )
    return "\n".join(lines)


SYSTEM_PROMPT = (
    "You are the FactoryXChange 2.0 Service Finder. You help a Digital Strategist match a "
    "manufacturing SME's need to the right FXC partner service.\n"
    "Rules:\n"
    "- Recommend ONLY services from the catalogue below. Never invent services, partners, or prices.\n"
    "- Name the exact service and its delivering partner, and include the FXC page link.\n"
    "- Prefer 1-3 strong matches over a long list. Say briefly why each fits.\n"
    "- If nothing fits well, say so plainly and point to the closest category or partner.\n"
    "- Be concise and practical. You are signposting, not selling.\n\n"
    "CATALOGUE (73 live services):\n"
)


def build_focus_block(focus_ids):
    """Full-detail block for the services the user has clicked into (focus).

    Reuses the same entities.json load as build_catalogue(). Returns "" when no
    services are focused. Per focused service: label, partner, duration, service
    lead, and the FULL description. Price is deliberately excluded.
    """
    if not focus_ids:
        return ""
    data = read_catalogue()
    par = {p["id"]: p for p in data["partners"]}
    wanted = set(focus_ids)
    focus = [s for s in data["services"] if s["id"] in wanted]
    if not focus:
        return ""
    lines = ["FOCUSED SERVICES — full detail:"]
    for s in focus:
        p = par[s["partner"]]
        lines.append(
            f"- {s['label']} | partner: {p['label']} | "
            f"duration: {s.get('duration', '')} | service lead: {s.get('service_lead', '')}\n"
            f"  {s.get('full', '')}"
        )
    return "\n".join(lines)


def _gemini_contents(messages):
    """Map the unified {role, text} history to Gemini's contents shape."""
    return [
        {"role": "model" if m.get("role") == "assistant" else "user",
         "parts": [{"text": m.get("text", "")}]}
        for m in messages
    ]


def call_gemini(cfg, system_prompt, messages):
    model = cfg.get("model", "gemini-3.5-flash")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent")
    body = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": _gemini_contents(messages),
    }
    out = _post_json(url, body, {
        "Content-Type": "application/json",
        "x-goog-api-key": cfg["api_key"],
    })
    return out["candidates"][0]["content"]["parts"][0]["text"]


def call_anthropic(cfg, system_prompt, messages):
    body = {
        "model": cfg.get("model", "claude-sonnet-5"),
        "max_tokens": 900,
        "system": system_prompt,
        "messages": [{"role": m.get("role", "user"), "content": m.get("text", "")}
                     for m in messages],
    }
    out = _post_json("https://api.anthropic.com/v1/messages", body, {
        "content-type": "application/json",
        "x-api-key": cfg["api_key"],
        "anthropic-version": "2023-06-01",
    })
    return out["content"][0]["text"]


PROVIDERS = {"gemini": call_gemini, "anthropic": call_anthropic}


def _post_json(url, body, headers):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST")
    for name, value in headers.items():
        req.add_unredirected_header(name, value)
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode("utf-8"))


def _last_user_text(messages):
    """The most recent user turn — used for the empty-input guard only.

    The full `messages` history is what actually goes to the provider (multi-turn).
    """
    for m in reversed(messages or []):
        if m.get("role") == "user":
            return (m.get("text") or "").strip()
    return ""


def _open_posix(path, flags):
    # Open each component relative to its pinned parent, including the site directory.
    directory_flags = getattr(os, "O_PATH", getattr(os, "O_SEARCH", os.O_RDONLY))
    directory_flags |= os.O_DIRECTORY | os.O_NOFOLLOW
    with ExitStack() as directories:
        parent = None
        path = Path(path)
        for part in path.parts[:-1]:
            parent = os.open(part, directory_flags, dir_fd=parent)
            directories.callback(os.close, parent)
        return os.open(path.name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)


def _windows_handle_matches(stream, path):
    import ctypes
    import msvcrt
    from ctypes.wintypes import HANDLE

    # Ask Windows where this handle landed, including any junctions it traversed.
    handle = HANDLE(msvcrt.get_osfhandle(stream.fileno()))
    name = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetFinalPathNameByHandleW(handle, name, len(name), 0)
    if not 0 < length < len(name):
        return False
    expected = str(path)
    if not expected.startswith("\\\\?\\"):
        if expected.startswith("\\\\"):
            expected = "UNC\\" + expected[2:]
        expected = "\\\\?\\" + expected
    return name.value == expected


def open_regular_file(path, *, public_asset=False):
    """Open an absolute canonical path and verify the file before reading any bytes."""
    opener = None if os.name == "nt" else _open_posix
    with ExitStack() as cleanup:
        stream = cleanup.enter_context(open(path, "rb", opener=opener))
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise OSError("Expected a regular file")
        if public_asset and info.st_nlink != 1:
            raise OSError("Expected a single link to the public asset")
        if os.name == "nt" and not _windows_handle_matches(stream, path):
            raise OSError("Unexpected file location")
        cleanup.pop_all()
        return stream


try:
    CATALOGUE = build_catalogue()
except OSError:
    CATALOGUE = None


def load_config():
    try:
        path = (Path.home() / ".config" / "fxc-service-map" / "chat_config.json").resolve(strict=True)
        if SITE in path.parents:
            return None
        with open_regular_file(path) as stream:
            cfg = json.load(stream)
        return cfg if isinstance(cfg, dict) else None
    except (OSError, RuntimeError, ValueError):
        return None


def answer_question(messages, focus_ids):
    question = _last_user_text(messages)
    if not question:
        return ("Ask me what a client needs — e.g. \"help with NIS2 compliance\", "
                "\"we want to trial AI vision inspection\", or \"funding to buy a machine\".")
    cfg = load_config()
    if cfg is None:
        return ("⚙️ AI chat isn't configured yet. See the local chat setup in README.md. "
                "The map works without it.")
    try:
        fn = PROVIDERS.get(cfg.get("provider", "gemini"))
        if not fn or not cfg.get("api_key") or "PASTE" in cfg.get("api_key", ""):
            return "⚙️ chat_config.json needs a valid \"provider\" (gemini or anthropic) and \"api_key\"."
        try:
            catalogue = CATALOGUE if CATALOGUE is not None else build_catalogue()
            system_prompt = SYSTEM_PROMPT + catalogue + "\n\n" + build_focus_block(focus_ids)
        except OSError:
            return "The service catalogue is unavailable."
        return fn(cfg, system_prompt, messages)
    except Exception:
        return "The AI provider could not complete the request. Check the key and model in chat_config.json."


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SITE), **kwargs)

    def send_head(self):
        path = self.path.partition("?")[0]
        if path == "/":
            path = "/index.html"
        if path not in ("/index.html", "/_data/entities.json"):
            self.send_error(404)
            return None
        with ExitStack() as cleanup:
            try:
                stream = cleanup.enter_context(open_regular_file(SITE / path[1:], public_asset=True))
            except OSError:
                self.send_error(404)
                return None
            info = os.fstat(stream.fileno())
            if self.is_not_modified(info.st_mtime):
                self.send_response(304)
                self.end_headers()
                return None
            self.send_response(200)
            self.send_header("Content-Type", self.guess_type(path))
            self.send_header("Content-Length", str(info.st_size))
            self.send_header("Last-Modified", self.date_time_string(info.st_mtime))
            self.end_headers()
            cleanup.pop_all()  # The inherited GET and HEAD handlers close this stream.
            return stream

    def is_not_modified(self, mtime):
        since = self.headers.get("If-Modified-Since")
        if not since or "If-None-Match" in self.headers:
            return False
        try:
            date = parsedate_to_datetime(since)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            return date.tzinfo is timezone.utc and int(mtime) <= date.timestamp()
        except (TypeError, ValueError, IndexError, OverflowError, OSError):
            return False

    def do_POST(self):
        if self.path != "/api/chat":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload_in = json.loads(self.rfile.read(length) or b"{}")
            messages = payload_in.get("messages", [])
            focus_ids = payload_in.get("focus", [])
        except Exception:
            self.send_error(400)
            return
        payload = json.dumps({"reply": answer_question(messages, focus_ids)}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass  # quiet


if __name__ == "__main__":
    ready = load_config() is not None
    print(f"FXC Service Map on http://{HOST}:{PORT}/index.html")
    print(f"AI chat: {'configured' if ready else 'not configured (see README.md)'}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
