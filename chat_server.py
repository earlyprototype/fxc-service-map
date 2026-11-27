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
import urllib.request
import urllib.error
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SITE = Path(__file__).resolve().parent
CONFIG = Path.home() / ".config" / "fxc-service-map" / "chat_config.json"
HOST = "127.0.0.1"
PORT = 8020


def build_catalogue():
    data = json.loads((SITE / "_data" / "entities.json").read_text(encoding="utf-8"))
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
    "CATALOGUE (73 live services):\n" + build_catalogue()
)


def build_focus_block(focus_ids):
    """Full-detail block for the services the user has clicked into (focus).

    Reuses the same entities.json load as build_catalogue(). Returns "" when no
    services are focused. Per focused service: label, partner, duration, service
    lead, and the FULL description. Price is deliberately excluded.
    """
    if not focus_ids:
        return ""
    data = json.loads((SITE / "_data" / "entities.json").read_text(encoding="utf-8"))
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
           f"{model}:generateContent?key={cfg['api_key']}")
    body = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": _gemini_contents(messages),
    }
    out = _post_json(url, body, {"Content-Type": "application/json"})
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
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers=headers, method="POST")
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


def config_available():
    return CONFIG.is_file() and SITE not in CONFIG.resolve().parents


def answer_question(messages, focus_ids):
    question = _last_user_text(messages)
    if not question:
        return ("Ask me what a client needs — e.g. \"help with NIS2 compliance\", "
                "\"we want to trial AI vision inspection\", or \"funding to buy a machine\".")
    if not config_available():
        return ("⚙️ AI chat isn't configured yet. See the local chat setup in README.md. "
                "The map works without it.")
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        fn = PROVIDERS.get(cfg.get("provider", "gemini"))
        if not fn or not cfg.get("api_key") or "PASTE" in cfg.get("api_key", ""):
            return "⚙️ chat_config.json needs a valid \"provider\" (gemini or anthropic) and \"api_key\"."
        system_prompt = SYSTEM_PROMPT + "\n\n" + build_focus_block(focus_ids)
        return fn(cfg, system_prompt, messages)
    except urllib.error.HTTPError as e:
        return f"The AI provider returned an error ({e.code}). Check the key and model in chat_config.json."
    except Exception as e:
        return f"Chat error: {e}"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SITE), **kwargs)

    def send_head(self):
        # GET and HEAD share this check. Only literal map routes reach the file handler.
        path = self.path.partition("?")[0]
        if path == "/":
            path = "/index.html"
        if path not in ("/index.html", "/_data/entities.json"):
            self.send_error(404)
            return None
        asset = SITE / path[1:]
        if not asset.is_file() or asset.resolve() != asset:
            self.send_error(404)
            return None
        self.path = path
        return super().send_head()

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
    ready = config_available()
    print(f"FXC Service Map on http://{HOST}:{PORT}/index.html")
    print(f"AI chat: {'configured' if ready else 'not configured (see README.md)'}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
