/**
 * fxc-service-chat — Cloudflare Worker
 *
 * Server-side proxy for the "Service Finder" chat panel on the FactoryXChange
 * 2.0 service map (the static map is hosted on GitHub Pages; this Worker holds
 * the chat brain).
 *
 * Holds the GEMINI_API_KEY secret server-side (added via the Cloudflare
 * dashboard or `wrangler secret put` — never committed to this repo) and calls
 * the Gemini API on the static frontend's behalf, grounded in the full FXC
 * service catalogue so it signposts real services and never hallucinates.
 *
 * No message content is logged anywhere in this file. See README.md.
 */

import { BASE_CATALOGUE, SERVICE_DETAIL } from './fxc-context.generated.mjs';

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const GEMINI_MODEL = 'gemini-3.5-flash';
const GEMINI_URL = `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent`;

// CORS — the static map is served from GitHub Pages. Set this to the deployed
// GitHub Pages origin (e.g. "https://your-org.github.io") BEFORE deploying,
// then redeploy. The scheme+host only, no path.
const ALLOWED_ORIGIN = 'https://earlyprototype.github.io';
const LOCAL_ORIGIN_RE = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/;

// These caps MUST stay consistent, or a long reply riding back as history trips
// MESSAGE validation on the NEXT turn: a reply of up to MAX_OUTPUT_TOKENS
// (~4 chars/token ≈ 4000 chars) must fit under MAX_MESSAGE_CHARS, and
// MAX_HISTORY_MESSAGES of those must fit under MAX_BODY_BYTES.
const MAX_BODY_BYTES = 65536;
const MAX_MESSAGE_CHARS = 6000;
const MAX_HISTORY_MESSAGES = 8;
const MAX_OUTPUT_TOKENS = 1024;
// The frontend sends every in-view service id as "focus". Injecting the full
// detail for all 73 would bloat the prompt, so cap how many full-detail blocks
// we inline per request. The base catalogue still covers every service.
const MAX_FOCUS_SERVICES = 12;

const QUOTA_REPLY =
  "I've hit my daily limit for now — the map itself still works, so feel free to keep exploring the services. Please try the chat again tomorrow.";
const UPSTREAM_ERROR_REPLY =
  "I'm having trouble answering right now — the map itself still works, so feel free to keep exploring the services. Please try again shortly.";

// Grounding rules below are the FXC Service Finder brief (see chat_server.py's
// SYSTEM_PROMPT). The catalogue itself is baked in from
// ../_data/entities.json by build-context.mjs — do not add services,
// partners, or prices that aren't in that data.
const SYSTEM_PROMPT =
  'You are the FactoryXChange 2.0 Service Finder. You help a Digital Strategist match a ' +
  "manufacturing SME's need to the right FXC partner service.\n" +
  'Rules:\n' +
  '- Recommend ONLY services from the catalogue below. Never invent services, partners, or prices.\n' +
  '- Name the exact service and its delivering partner, and include the FXC page link.\n' +
  '- Prefer 1-3 strong matches over a long list. Say briefly why each fits.\n' +
  '- If nothing fits well, say so plainly and point to the closest category or partner.\n' +
  '- Be concise and practical. You are signposting, not selling.\n\n' +
  'CATALOGUE (73 live services):\n' +
  BASE_CATALOGUE;

// ---------------------------------------------------------------------------
// CORS
// ---------------------------------------------------------------------------

function resolveAllowedOrigin(origin) {
  if (!origin) return null;
  if (origin === ALLOWED_ORIGIN) return origin;
  if (LOCAL_ORIGIN_RE.test(origin)) return origin;
  return null;
}

function corsHeaders(origin) {
  const allowed = resolveAllowedOrigin(origin);
  const headers = {
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400',
    Vary: 'Origin',
  };
  if (allowed) {
    headers['Access-Control-Allow-Origin'] = allowed;
  }
  return headers;
}

function jsonResponse(body, status, origin) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'Content-Type': 'application/json',
      ...corsHeaders(origin),
    },
  });
}

// ---------------------------------------------------------------------------
// Input validation
// ---------------------------------------------------------------------------

function validateMessages(messages) {
  if (!Array.isArray(messages) || messages.length === 0) {
    return 'messages must be a non-empty array';
  }
  for (const m of messages) {
    if (!m || (m.role !== 'user' && m.role !== 'assistant')) {
      return 'each message needs role "user" or "assistant"';
    }
    if (typeof m.text !== 'string' || m.text.trim().length === 0) {
      return 'each message needs non-empty text';
    }
    if (m.text.length > MAX_MESSAGE_CHARS) {
      return `each message must be ${MAX_MESSAGE_CHARS} characters or fewer`;
    }
  }
  if (messages[messages.length - 1].role !== 'user') {
    return 'the last message must be from the user';
  }
  return null;
}

// Keep only the string ids we recognise, capped. Unknown/bogus ids are simply
// dropped — see buildSystemInstruction for why that's safe.
function normaliseFocus(focus) {
  if (!Array.isArray(focus)) return [];
  const ids = [];
  for (const id of focus) {
    if (typeof id === 'string' && SERVICE_DETAIL[id]) ids.push(id);
    if (ids.length >= MAX_FOCUS_SERVICES) break;
  }
  return ids;
}

// ---------------------------------------------------------------------------
// Gemini call
// ---------------------------------------------------------------------------

// Base Service Finder prompt, optionally enriched with the full detail of the
// service(s) the visitor currently has in focus on the map. `focus` is an
// array of service ids from the frontend. We only ever interpolate our OWN
// generated SERVICE_DETAIL data (never the raw focus strings), so a bogus focus
// id can't inject anything — it just misses the lookup. Price is never
// included: SERVICE_DETAIL doesn't carry it.
function buildSystemInstruction(focus) {
  const ids = normaliseFocus(focus);
  if (!ids.length) return SYSTEM_PROMPT;

  const blocks = ids.map((id) => {
    const d = SERVICE_DETAIL[id];
    return (
      `- ${d.label} | partner: ${d.partner} | ` +
      `duration: ${d.duration} | service lead: ${d.service_lead}\n` +
      `  ${d.full}`
    );
  });

  return `${SYSTEM_PROMPT}

FOCUSED SERVICES — full detail:
${blocks.join('\n')}`;
}

function toGeminiContents(messages) {
  return messages.map((m) => ({
    role: m.role === 'assistant' ? 'model' : 'user',
    parts: [{ text: m.text }],
  }));
}

async function callGemini(apiKey, messages, focus) {
  const payload = {
    systemInstruction: { parts: [{ text: buildSystemInstruction(focus) }] },
    contents: toGeminiContents(messages),
    generationConfig: {
      maxOutputTokens: MAX_OUTPUT_TOKENS,
      // gemini flash "thinks" by default and its thinking tokens eat into
      // maxOutputTokens, truncating replies mid-sentence. This is a short-
      // answer signposting chat — spend the whole budget on the reply.
      thinkingConfig: { thinkingBudget: 0 },
    },
  };

  const response = await fetch(GEMINI_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-goog-api-key': apiKey,
    },
    body: JSON.stringify(payload),
  });

  const data = await response.json().catch(() => null);

  if (!response.ok) {
    const status = data?.error?.status;
    const code = data?.error?.code ?? response.status;
    const isQuota = code === 429 || status === 'RESOURCE_EXHAUSTED';
    return { ok: false, quota: isQuota };
  }

  const cand = data?.candidates?.[0];
  const text = (cand?.content?.parts || [])
    .map((p) => p.text || '')
    .join('')
    .trim();

  if (!text) {
    return { ok: false, quota: false };
  }
  return { ok: true, text };
}

// ---------------------------------------------------------------------------
// Request handling
// ---------------------------------------------------------------------------

export default {
  async fetch(request, env) {
    const origin = request.headers.get('Origin');

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders(origin) });
    }

    if (request.method !== 'POST') {
      return jsonResponse({ error: 'POST only' }, 405, origin);
    }

    if (!resolveAllowedOrigin(origin)) {
      return jsonResponse({ error: 'origin not allowed' }, 403, origin);
    }

    const rawBody = await request.text();
    const bodyByteLength = new TextEncoder().encode(rawBody).length;
    if (bodyByteLength > MAX_BODY_BYTES) {
      return jsonResponse({ error: 'request body too large' }, 413, origin);
    }

    let body;
    try {
      body = JSON.parse(rawBody);
    } catch {
      return jsonResponse({ error: 'invalid JSON' }, 400, origin);
    }

    const validationError = validateMessages(body && body.messages);
    if (validationError) {
      return jsonResponse({ error: validationError }, 400, origin);
    }

    const history = body.messages.slice(-MAX_HISTORY_MESSAGES);
    const focus = normaliseFocus(body.focus);

    // Accept either name so the deployed secret works whether it was set as
    // GEMINI_API_KEY or GEMINI_API_SECRET.
    const apiKey = env.GEMINI_API_KEY || env.GEMINI_API_SECRET;
    if (!apiKey) {
      // Secret not configured yet — graceful, not a crash.
      return jsonResponse({ reply: UPSTREAM_ERROR_REPLY, limited: true }, 200, origin);
    }

    try {
      const result = await callGemini(apiKey, history, focus);
      if (!result.ok) {
        return jsonResponse(
          { reply: result.quota ? QUOTA_REPLY : UPSTREAM_ERROR_REPLY, limited: true },
          200,
          origin
        );
      }
      return jsonResponse({ reply: result.text }, 200, origin);
    } catch {
      return jsonResponse({ reply: UPSTREAM_ERROR_REPLY, limited: true }, 200, origin);
    }
  },
};
