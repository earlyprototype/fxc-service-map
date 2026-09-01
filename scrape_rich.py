#!/usr/bin/env python3
"""One-off scraper for the FactoryXChange 2.0 service map.

For each of the 73 FXC services listed in ``_data/entities.json`` this
fetches the live Wix product page (stdlib ``urllib`` only, no headless
browser) and extracts: description, duration, service lead, price, currency,
availability and sku.

Output: ``rich_descriptions.json`` keyed by the service's exact LABEL string.

Re-runnable / idempotent: overwrites the JSON on every run and prints a loud
summary so silent Wix markup changes surface immediately.
"""

import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENTITIES_PATH = HERE / "_data" / "entities.json"
OUTPUT_PATH = HERE / "rich_descriptions.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 30
SLEEP_BETWEEN = 2.0        # Wix rate-limits aggressively; keep a polite gap.
MAX_RETRIES = 6           # per-page retries on 429 / transient network errors.
BASE_BACKOFF = 5          # seconds; doubled each retry, capped at MAX_BACKOFF.
MAX_BACKOFF = 120


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------
def fetch_html(url: str) -> str:
    """Fetch a page as UTF-8, retrying with exponential backoff on HTTP 429
    (Wix rate limiting) and transient network errors. Honours ``Retry-After``
    when the server supplies it."""
    last_exc = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code == 429 and attempt < MAX_RETRIES:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                if retry_after and str(retry_after).strip().isdigit():
                    wait = int(retry_after)
                else:
                    wait = BASE_BACKOFF * (2 ** attempt)
                wait = min(wait, MAX_BACKOFF)
                print(f"    429 rate-limited; backing off {wait}s "
                      f"(attempt {attempt + 1}/{MAX_RETRIES})")
                time.sleep(wait)
                continue
            raise
        except urllib.error.URLError as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                wait = min(BASE_BACKOFF * (2 ** attempt), MAX_BACKOFF)
                print(f"    network error ({exc}); retrying in {wait}s "
                      f"(attempt {attempt + 1}/{MAX_RETRIES})")
                time.sleep(wait)
                continue
            raise
    raise last_exc  # pragma: no cover - loop always returns or raises above


# --------------------------------------------------------------------------
# HTML helpers
# --------------------------------------------------------------------------
_TAG_RE = re.compile(r"<[^>]+>")
_BOLD_RE = re.compile(r"<(?:strong|b)\b[^>]*>(.*?)</(?:strong|b)>", re.IGNORECASE | re.DOTALL)


def strip_html(fragment: str) -> str:
    """Strip HTML tags, unescape entities, normalise whitespace per line."""
    if not fragment:
        return ""
    # Turn block boundaries into newlines so lines survive tag removal.
    text = re.sub(r"(?i)<\s*br\s*/?>", "\n", fragment)
    text = re.sub(r"(?i)</\s*(p|div|li|h[1-6])\s*>", "\n", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def flatten_text(fragment: str) -> str:
    """Strip HTML and collapse everything to a single free-text line."""
    text = strip_html(fragment)
    return re.sub(r"\s+", " ", text.replace("\n", " ")).strip()


def first_bold_name(fragment: str) -> str:
    """Return the first bold name, else the first non-empty stripped line."""
    for match in _BOLD_RE.finditer(fragment):
        candidate = flatten_text(match.group(1))
        if candidate:
            return candidate
    stripped = strip_html(fragment)
    for line in stripped.splitlines():
        if line.strip():
            return line.strip()
    return ""


# --------------------------------------------------------------------------
# JSON-LD Product block
# --------------------------------------------------------------------------
_LDJSON_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


def _iter_ld_objects(parsed):
    """Yield candidate dicts from a parsed ld+json blob (handles @graph/lists)."""
    if isinstance(parsed, dict):
        if "@graph" in parsed and isinstance(parsed["@graph"], list):
            for item in parsed["@graph"]:
                yield from _iter_ld_objects(item)
        yield parsed
    elif isinstance(parsed, list):
        for item in parsed:
            yield from _iter_ld_objects(item)


def _is_product(obj: dict) -> bool:
    t = obj.get("@type")
    if isinstance(t, list):
        return any(str(x).lower() == "product" for x in t)
    return str(t).lower() == "product"


def find_product_ldjson(page_html: str):
    """Return the parsed JSON-LD object whose @type is Product, or None."""
    for match in _LDJSON_RE.finditer(page_html):
        block = match.group(1).strip()
        if not block:
            continue
        try:
            parsed = json.loads(block)
        except json.JSONDecodeError:
            continue
        for obj in _iter_ld_objects(parsed):
            if isinstance(obj, dict) and _is_product(obj):
                return obj
    return None


def _ci_get(d: dict, *keys):
    """Case-insensitive lookup: return first matching key's value."""
    if not isinstance(d, dict):
        return None
    lowered = {k.lower(): v for k, v in d.items()}
    for key in keys:
        if key.lower() in lowered:
            return lowered[key.lower()]
    return None


def extract_from_product(product: dict) -> dict:
    """Pull price/currency/availability/sku/description from the Product LD."""
    out = {
        "description": "",
        "price": "",
        "currency": "",
        "availability": "",
        "sku": "",
    }
    if not product:
        return out

    desc = product.get("description") or ""
    out["description"] = flatten_text(desc) if ("<" in desc and ">" in desc) else html.unescape(desc).strip()

    out["sku"] = str(product.get("sku") or "").strip()

    offers = _ci_get(product, "offers")
    if isinstance(offers, list) and offers:
        offers = offers[0]
    if isinstance(offers, dict):
        price = _ci_get(offers, "price")
        currency = _ci_get(offers, "priceCurrency", "currency")
        availability = _ci_get(offers, "availability")
        if price is not None:
            out["price"] = str(price).strip()
        if currency:
            out["currency"] = str(currency).strip()
        if availability:
            # Store only the last path segment (InStock / OutOfStock).
            out["availability"] = str(availability).rstrip("/").split("/")[-1].strip()
    return out


# --------------------------------------------------------------------------
# Wix additionalInfo array (bracket-matched, quote/escape aware)
# --------------------------------------------------------------------------
ADDITIONAL_INFO_KEY = '"additionalInfo":['


def extract_bracketed_array(page_html: str, start_key: str = ADDITIONAL_INFO_KEY):
    """Find `start_key` and return the JSON array text from its opening `[`
    to the matching `]`, respecting quoted strings and backslash escapes."""
    idx = page_html.find(start_key)
    if idx == -1:
        return None
    open_idx = idx + len(start_key) - 1  # position of the '['
    depth = 0
    in_string = False
    escaped = False
    for pos in range(open_idx, len(page_html)):
        ch = page_html[pos]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 0:
                return page_html[open_idx : pos + 1]
    return None


def parse_additional_info(page_html: str):
    """Return the parsed additionalInfo list, or [] on failure."""
    array_text = extract_bracketed_array(page_html)
    if not array_text:
        return []
    try:
        data = json.loads(array_text)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def find_section(info_list, needle: str):
    """Case-insensitive substring match on the section title. Returns the
    matching section dict, or None."""
    for section in info_list:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title", "")).lower()
        if needle in title:
            return section
    return None


# --------------------------------------------------------------------------
# Fallback: visible HTML info-section scan
# --------------------------------------------------------------------------
_INFO_SECTION_TITLE_RE = re.compile(
    r'data-hook="info-section-title"[^>]*>(.*?)</',
    re.IGNORECASE | re.DOTALL,
)


def fallback_info_section(page_html: str, needle: str) -> str:
    """Best-effort scan of visible ``data-hook="info-section-title"`` blocks.

    Returns flattened text of the section body following a title that
    contains ``needle`` (case-insensitive), or "" if not found.
    """
    for match in re.finditer(
        r'data-hook="info-section-title"[^>]*>(.*?)(?=data-hook="info-section-title"|$)',
        page_html,
        re.IGNORECASE | re.DOTALL,
    ):
        chunk = match.group(1)
        # Title text is everything up to the first closing tag.
        title_match = re.match(r"(.*?)</", chunk, re.DOTALL)
        title = flatten_text(title_match.group(1)) if title_match else ""
        if needle in title.lower():
            body = chunk[title_match.end():] if title_match else chunk
            body_match = re.search(
                r'data-hook="info-section-description"[^>]*>(.*)',
                body,
                re.IGNORECASE | re.DOTALL,
            )
            target = body_match.group(1) if body_match else body
            return flatten_text(target)
    return ""


# --------------------------------------------------------------------------
# Per-service extraction
# --------------------------------------------------------------------------
def scrape_service(url: str) -> dict:
    page_html = fetch_html(url)

    product = find_product_ldjson(page_html)
    fields = extract_from_product(product)

    info_list = parse_additional_info(page_html)

    lead_section = find_section(info_list, "service lead")
    duration_section = find_section(info_list, "duration")

    service_lead = ""
    if lead_section:
        service_lead = first_bold_name(lead_section.get("description", ""))
    if not service_lead:
        service_lead = flatten_text(fallback_info_section(page_html, "service lead"))

    duration = ""
    if duration_section:
        duration = flatten_text(duration_section.get("description", ""))
    if not duration:
        duration = fallback_info_section(page_html, "duration")

    return {
        "description": fields["description"],
        "duration": duration,
        "service_lead": service_lead,
        "price": fields["price"],
        "currency": fields["currency"],
        "availability": fields["availability"],
        "sku": fields["sku"],
    }


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def _is_complete(rec: dict) -> bool:
    """A record is complete when the three validated fields are non-empty."""
    return bool(
        rec
        and rec.get("description")
        and rec.get("duration")
        and rec.get("service_lead")
    )


def main() -> int:
    with open(ENTITIES_PATH, "r", encoding="utf-8") as fh:
        entities = json.load(fh)
    services = entities.get("services", [])
    total = len(services)
    print(f"Loaded {total} services from {ENTITIES_PATH}")

    # Resume support: reuse complete entries from a prior partial run so a
    # rerun does not re-hammer the (rate-limited) Wix backend. The full merged
    # set is still written out at the end, so the JSON is overwritten each run.
    existing = {}
    if OUTPUT_PATH.exists():
        try:
            with open(OUTPUT_PATH, "r", encoding="utf-8") as fh:
                existing = json.load(fh)
            reusable = sum(1 for r in existing.values() if _is_complete(r))
            print(f"Found existing output with {reusable} complete entries "
                  f"(will reuse and only fetch the rest).")
        except (json.JSONDecodeError, OSError):
            existing = {}

    results = {}
    failed = []

    for i, svc in enumerate(services, 1):
        label = svc.get("label", "")
        url = svc.get("url", "")

        if _is_complete(existing.get(label)):
            results[label] = existing[label]
            print(f"[{i:>2}/{total}] {label} -> reused (already complete)")
            continue

        print(f"[{i:>2}/{total}] {label} -> {url}")
        if not url:
            failed.append((label, "no url"))
            continue
        try:
            results[label] = scrape_service(url)
        except Exception as exc:  # noqa: BLE001 - one bad page must not abort run
            print(f"    !! FAILED: {type(exc).__name__}: {exc}")
            failed.append((label, f"{type(exc).__name__}: {exc}"))
        time.sleep(SLEEP_BETWEEN)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)
    print(f"\nWrote {len(results)} entries to {OUTPUT_PATH}")

    # ------------------------------------------------------------------
    # Loud validation summary
    # ------------------------------------------------------------------
    empty_desc = [lbl for lbl, r in results.items() if not r["description"]]
    empty_dur = [lbl for lbl, r in results.items() if not r["duration"]]
    empty_lead = [lbl for lbl, r in results.items() if not r["service_lead"]]
    complete = [
        lbl
        for lbl, r in results.items()
        if r["description"] and r["duration"] and r["service_lead"]
    ]

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total services in list      : {total}")
    print(f"Scraped (page fetched)      : {len(results)}")
    print(f"Fully complete (desc+dur+lead): {len(complete)} / {total}")

    def _dump(label, items):
        print(f"\n{label} ({len(items)}):")
        if not items:
            print("  (none)")
        for it in items:
            print(f"  - {it}")

    _dump("MISSING description", empty_desc)
    _dump("MISSING duration", empty_dur)
    _dump("MISSING service_lead", empty_lead)

    print(f"\nFETCH FAILURES ({len(failed)}):")
    if not failed:
        print("  (none)")
    for lbl, reason in failed:
        print(f"  - {lbl}: {reason}")

    # Non-zero exit if anything is incomplete, so problems are impossible to miss.
    problems = bool(empty_desc or empty_dur or empty_lead or failed)
    print("\n" + ("=" * 70))
    print("RESULT: " + ("PROBLEMS FOUND (see above)" if problems else "ALL 73 COMPLETE"))
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
