"""
Product matching/normalization.

Retailers describe the same physical product differently:
  "Apple iPhone 17 Pro (256GB) - Deep Blue"
  "Apple iPhone 17 Pro 256 GB Deep Blue"
  "Apple iPhone-17-Pro 512gb Cosmic-Orange"
  "Apple iPhone 17 Pro (512 GB, Cosmic Orange)"

We normalize brand/model/storage/colour into a canonical key so listings from different
sources land on the same Product row.

Design note (v2): the first version of this module matched colour against a fixed
vocabulary (COLOUR_WORDS). That silently dropped any colour not on the list -- "Lavender"
being a concrete example that shipped in our own fixture data and came back as None. A fixed
word list can never keep up with retailer naming (seasonal colourways, region-specific names,
marketing names like "Natural Titanium"). This version instead parses colour and model
*positionally*, using storage as an anchor: whatever sits before storage (after the brand)
is the model, whatever sits after storage is the colour, following the fact that every
observed retailer format puts colour and storage adjacent to each other with the model name
before them. This generalizes to any colour name without needing a dictionary at all.

Matching itself is still deliberately rule-based (regex + normalization) rather than
ML/embedding-based: transparent, debuggable, fast, and sufficient for a bounded catalogue.
A difflib-based fuzzy fallback catches near-duplicates the exact key misses.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

STORAGE_RE = re.compile(r"(\d+)\s*(gb|tb)\b", re.IGNORECASE)
JUNK_EDGE_RE = re.compile(r"^[\s,\-|()]+|[\s,\-|()]+$")
SEPARATORS_RE = re.compile(r"[\-_/]")
STRIP_CHARS_RE = re.compile(r"[()\-,|]")


def normalize_storage(text: str | None) -> str | None:
    if not text:
        return None
    match = STORAGE_RE.search(text)
    if not match:
        return None
    value, unit = match.groups()
    unit = unit.upper()
    if unit == "TB":
        return f"{int(value) * 1024}GB"
    return f"{value}GB"


def _clean_fragment(text: str) -> str:
    """Normalize separators, strip bracket/punctuation noise from both ends, collapse
    whitespace. Used for both the pre-storage (model) and post-storage (colour) fragments."""
    text = SEPARATORS_RE.sub(" ", text)
    text = JUNK_EDGE_RE.sub("", text)
    text = STRIP_CHARS_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_title(product_name: str, brand: str) -> tuple[str, str | None, str | None]:
    """Split a raw retailer title into (model, storage, colour) using storage as an anchor
    point: model is whatever precedes it (after removing brand), colour is whatever follows
    it. Returns (model, None, None) if no storage token is found at all -- callers should
    treat storage/colour as genuinely unknown in that case, not guess."""
    text = product_name or ""

    match = STORAGE_RE.search(text)
    if not match:
        model = _clean_fragment(re.sub(re.escape(brand), "", text, flags=re.IGNORECASE))
        return (model or text.strip(), None, None)

    storage = normalize_storage(match.group(0))
    before = text[: match.start()]
    after = text[match.end() :]

    before = re.sub(re.escape(brand), "", before, flags=re.IGNORECASE)
    model = _clean_fragment(before)
    colour_raw = _clean_fragment(after)

    colour = colour_raw.title() if colour_raw else None
    return (model or text.strip(), storage, colour)


def normalize_colour(text: str | None) -> str | None:
    """Direct colour normalization when a source gives colour as its own field (rather than
    embedded in the title) -- just tidy casing/separators, no vocabulary lookup needed."""
    if not text:
        return None
    cleaned = _clean_fragment(text)
    return cleaned.title() if cleaned else None


def normalize_model(product_name: str, brand: str) -> str:
    """Isolate the model name from a raw title. Thin wrapper over parse_title for callers
    that only need the model (e.g. when storage/colour are already known from other fields)."""
    model, _, _ = parse_title(product_name, brand)
    return model


def canonical_key(brand: str, model: str, storage: str | None, colour: str | None) -> str:
    parts = [
        re.sub(r"[^a-z0-9]", "", brand.lower()),
        re.sub(r"[^a-z0-9]", "", model.lower()),
        (storage or "any").lower(),
        re.sub(r"[^a-z0-9]", "", (colour or "any").lower()),
    ]
    return ":".join(parts)


def normalize_listing_identity(raw) -> dict:
    """Given a RawListing, derive the fields used to build its canonical Product key.

    Prefers fields the adapter already parsed out explicitly (raw.storage, raw.colour) and
    falls back to positional parsing of the raw title when those are missing -- this is what
    lets fixture data (which supplies storage/colour directly) and live-scraped titles (which
    usually don't) both resolve to the same canonical key."""
    brand = (raw.brand or "").strip() or "Unknown"
    title_model, title_storage, title_colour = parse_title(raw.model or raw.product_name, brand)

    storage = normalize_storage(raw.storage) or title_storage
    colour = normalize_colour(raw.colour) or title_colour
    model = title_model

    return {
        "brand": brand,
        "model": model,
        "storage": storage,
        "colour": colour,
        "canonical_key": canonical_key(brand, model, storage, colour),
    }


def fuzzy_match(a: str, b: str) -> float:
    """0..1 similarity, used as a fallback when exact canonical keys don't collide
    (e.g. one source omits colour). Not used for the primary grouping path."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def find_best_existing_key(candidate_key: str, existing_keys: list[str], threshold: float = 0.88):
    """Given a new canonical_key and the keys already seen in this crawl, return an existing
    key to merge into if one is a near-exact fuzzy match, else None (create a new Product)."""
    best_key, best_score = None, 0.0
    for key in existing_keys:
        score = fuzzy_match(candidate_key, key)
        if score > best_score:
            best_key, best_score = key, score
    if best_score >= threshold:
        return best_key
    return None
