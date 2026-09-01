#!/usr/bin/env python3
"""
FXC Service Map dev server — with an optional, grounded AI "Service Finder" chat.

Serves the repository root (the map) AND answers POST /api/chat by asking an LLM to match a
client's need to a real FXC service. The model is given the FULL service catalogue
(from _data/entities.json) and instructed to recommend only real services and
cite the partner + live FXC page — so it signposts, it doesn't hallucinate.

Why full-catalogue-in-prompt and not a vector DB: 73 services is tiny. Stuffing the
whole catalogue into the system prompt is simpler, cheaper, and more accurate than
retrieval at this scale. Right tool for the size.

Security: the API key lives in chat_config.json (gitignored) and is used server-side
only — it never reaches the browser. No key / no config → the chat returns a friendly
"not configured" note and the rest of the map works untouched.

Run:  python chat_server.py      then open  http://localhost:8020/index.html
Stdlib only — no Flask, no SDKs (calls provider REST APIs via urllib).
"""

import json
import urllib.request
import urllib.error
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
SITE = ROOT
CONFIG = ROOT / "chat_config.json"
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


def answer_question(messages, focus_ids):
    question = _last_user_text(messages)
    if not question:
        return ("Ask me what a client needs — e.g. \"help with NIS2 compliance\", "
                "\"we want to trial AI vision inspection\", or \"funding to buy a machine\".")
    if not CONFIG.exists():
        return ("⚙️ AI chat isn't configured yet. Copy chat_config.template.json to "
                "chat_config.json, add your API key, and restart the server. (The rest of the map "
                "works without it.)")
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
    ready = CONFIG.exists()
    print(f"FXC Service Map on http://localhost:{PORT}/index.html")
    print(f"AI chat: {'configured' if ready else 'NOT configured (map works; see chat_config.template.json)'}")
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
