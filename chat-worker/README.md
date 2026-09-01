# fxc-service-chat

Cloudflare Worker behind the "Service Finder" chat panel on the FactoryXChange
2.0 service map. The static map is hosted on GitHub Pages; this Worker holds
the Gemini API key server-side so the key is never exposed in the static
frontend.

## What it does

- Accepts a short chat history (`POST` only) from the map page.
- Grounds every reply in a fixed system prompt: the FXC Service Finder rules
  plus the full catalogue of 73 live services (partner, category, pillar,
  short description and FXC link for each). The catalogue is baked in from
  `../_data/entities.json` by `build-context.mjs`.
- Calls the Gemini API (`gemini-3.5-flash` — see note below) and returns the
  reply as `{ "reply": "..." }`.
- If Gemini is out of quota, the key is missing, or any other upstream error
  occurs, it returns the same JSON shape with `limited: true` and a friendly
  "I can't answer right now, but the map still works" message instead of a raw
  error — so the frontend always has something sensible to render.
- CORS is locked to the GitHub Pages origin (see `ALLOWED_ORIGIN`), plus
  `http://localhost:*` / `http://127.0.0.1:*` for local testing. Requests from
  any other origin are rejected.

Model note: uses `gemini-3.5-flash` (set via the `GEMINI_MODEL` constant at the
top of `worker.js`). `gemini-2.0-flash` and `gemini-2.5-flash` are retired — if
Google ships something better later, change that one constant.

## Request / response protocol

```jsonc
// POST body
{
  "messages": [ { "role": "user", "text": "..." }, { "role": "assistant", "text": "..." } ],
  "focus":    [ "<serviceId>", ... ]   // ids of services currently in view; optional
}

// 200 response
{ "reply": "..." }
// 200 response on graceful degradation (no key / quota / upstream error)
{ "reply": "...", "limited": true }
```

`messages` must be non-empty and end with a `user` turn. `role` is `"user"` or
`"assistant"` (mapped to Gemini's `model` internally).

## Focused-service detail injection

When the frontend sends a `focus` array (the ids of the service nodes currently
in view / selected on the map), the Worker appends a `FOCUSED SERVICES — full
detail:` block to the system prompt — each service's label, partner, duration,
service lead and full description — so the chat can discuss those services with
real depth instead of a one-line blurb. An absent or unknown `focus` just falls
back to the base catalogue prompt. **Price is never injected.**

That detail (and the base catalogue) is baked into `fxc-context.generated.mjs`
by `build-context.mjs`. Regenerate it whenever the catalogue changes:

```bash
node build-context.mjs      # reads ../_data/entities.json (no network needed)
npx wrangler deploy         # bakes the refreshed data into the Worker
```

`fxc-context.generated.mjs` is committed to the repo.

## Deploy

From this folder:

1. **Set the CORS origin.** In `worker.js`, change `ALLOWED_ORIGIN` from the
   `https://REPLACE-WITH-YOUR-GITHUB-PAGES-ORIGIN` placeholder to your deployed
   GitHub Pages origin (scheme + host only, e.g. `https://your-org.github.io`).

2. **Regenerate context** (if the catalogue changed):

   ```bash
   node build-context.mjs
   ```

3. **Deploy:**

   ```bash
   npx wrangler login      # once, if not already authenticated
   npx wrangler deploy
   ```

   This publishes to `https://fxc-service-chat.<your-subdomain>.workers.dev`.
   Wrangler prints the exact URL after deploy.

4. **Wire the frontend.** Copy the printed Worker URL into the
   `CHAT_WORKER_URL` constant near the top of the chat script in
   `../index.html`. Leaving it empty keeps the page pointed at the local
   `/api/chat` dev server instead.

## Add the API key (Cloudflare dashboard)

The Worker needs one secret, `GEMINI_API_KEY`. It is never stored in this repo
— add it directly in Cloudflare:

1. Go to the [Cloudflare dashboard](https://dash.cloudflare.com) →
   **Workers & Pages**.
2. Open the **fxc-service-chat** Worker.
3. Go to **Settings → Variables and Secrets**.
4. Click **Add**:
   - Name: `GEMINI_API_KEY`
   - Value: your Gemini API key (free tier at https://aistudio.google.com/apikey)
   - Type: **Secret** (encrypted)
5. Save / Deploy to apply it.

Equivalent CLI, if you'd rather not use the dashboard:

```bash
npx wrangler secret put GEMINI_API_KEY
```

Until the key is set, the Worker responds to every chat request with the same
graceful "unavailable" message (`{ reply, limited: true }`) — it won't error or
crash, and the rest of the map is unaffected either way.

## Privacy

The Worker never logs message content. Cloudflare's own platform-level request
logs (if enabled on the account) may capture standard metadata (IP, timing,
status code), but nothing in this code writes chat text to any log, storage, or
third party other than the single Gemini API call needed to produce the reply.

## Limits enforced here

- Request body capped at 64 KB.
- Individual messages capped at 6000 characters.
- Only the last 8 messages of history are sent to Gemini.
- At most 12 focused-service detail blocks injected per request.
- Replies capped at ~1024 output tokens.
