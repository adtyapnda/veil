"""HTML extraction helpers, anchored on JSON-LD / schema.org.

Real-estate sites' CSS class names churn constantly, but most embed
``<script type="application/ld+json">`` blocks (schema.org) that are far more
stable. Parse those first; fall back to CSS selectors you capture yourself.
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable, Optional

try:
    from bs4 import BeautifulSoup

    _HAS_BS4 = True
except ImportError:  # pragma: no cover - optional dependency
    _HAS_BS4 = False

# Heuristic grab of embedded SPA state blobs (Next.js / Redux / custom).
_STATE_RE = re.compile(
    r"(?:window\.)?__(?:INITIAL_STATE|PRELOADED_STATE|NEXT_DATA|DATA|APP_DATA)__"
    r"\s*=\s*(\{.*?\})\s*;?\s*(?:</script>|window\.)",
    re.DOTALL,
)


def _require_bs4() -> None:
    if not _HAS_BS4:
        raise RuntimeError(
            "Parsing extras not installed. Run: pip install 'veil-scraper[parse]'"
        )


def soup(html: str) -> "BeautifulSoup":
    _require_bs4()
    return BeautifulSoup(html, "lxml")


def extract_jsonld(html: str) -> list[Any]:
    """Return every JSON-LD object on the page (``@graph`` flattened)."""
    results: list[Any] = []
    for tag in soup(html).find_all("script", type="application/ld+json"):
        raw = (tag.string or tag.get_text() or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            results.extend(data)
        elif isinstance(data, dict) and isinstance(data.get("@graph"), list):
            results.extend(data["@graph"])
        else:
            results.append(data)
    return results


def find_by_type(objects: Iterable[Any], types: set[str]) -> list[dict]:
    """Recursively collect dicts whose ``@type`` matches any of ``types``."""
    wanted = {t.lower() for t in types}
    found: list[dict] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            t = node.get("@type")
            tset: set[str] = set()
            if isinstance(t, str):
                tset = {t.lower()}
            elif isinstance(t, list):
                tset = {str(x).lower() for x in t}
            if tset & wanted:
                # A matched listing's internals (e.g. its nested Offer) are not
                # separate listings -- record it and stop descending.
                found.append(node)
                return
            for v in node.values():
                visit(v)
        elif isinstance(node, list):
            for v in node:
                visit(v)

    for obj in objects:
        visit(obj)
    return found


def extract_state_json(html: str) -> Optional[dict]:
    """Best-effort grab of an embedded SPA state blob, or None."""
    m = _STATE_RE.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _first(*values: Any) -> Any:
    for v in values:
        if v not in (None, "", [], {}):
            return v
    return None


def flatten_listing(obj: dict) -> dict:
    """Pull common real-estate fields out of a schema.org-ish object.

    Handles the usual shapes: ``offers``/``priceSpecification`` for price,
    ``address`` for locality, ``floorSize`` for area, ``numberOfRooms`` for BHK.
    Unknown/extra fields are ignored -- customize for your target as needed.
    """
    offers = obj.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    price_spec = offers.get("priceSpecification") or obj.get("priceSpecification") or {}
    address = obj.get("address") or {}
    if isinstance(address, list):
        address = address[0] if address else {}
    floor = obj.get("floorSize") or {}

    return {
        "name": _first(obj.get("name"), obj.get("headline")),
        "url": _first(obj.get("url"), obj.get("@id"), offers.get("url")),
        "price": _first(offers.get("price"), price_spec.get("price"), obj.get("price")),
        "currency": _first(
            offers.get("priceCurrency"), price_spec.get("priceCurrency")
        ),
        "locality": _first(
            address.get("addressLocality"),
            address.get("streetAddress"),
            obj.get("location"),
        ),
        "city": address.get("addressRegion") or address.get("addressCountry"),
        "rooms": obj.get("numberOfRooms"),
        "area": floor.get("value") if isinstance(floor, dict) else floor,
        "area_unit": floor.get("unitText") or floor.get("unitCode")
        if isinstance(floor, dict)
        else None,
    }


# Property-ish schema.org types real-estate listings commonly use.
LISTING_TYPES = {
    "Product",
    "Residence",
    "Apartment",
    "House",
    "SingleFamilyResidence",
    "RealEstateListing",
    "Offer",
    "Place",
}


def parse_listings(html: str) -> list[dict]:
    """Default extractor: JSON-LD listing objects, flattened.

    Returns [] if nothing matched -- that's your cue to add CSS selectors
    (see ``css_listings`` below) tailored to the page you captured.
    """
    ld = extract_jsonld(html)
    objs = find_by_type(ld, LISTING_TYPES)
    listings = [flatten_listing(o) for o in objs]
    # Keep only rows that actually carry a price or url -- drops org/breadcrumb noise.
    return [row for row in listings if row.get("url") or row.get("price")]


def css_listings(html: str, *, card: str, fields: dict[str, str]) -> list[dict]:
    """Fallback extractor driven by CSS selectors you capture from DevTools.

    Example::

        css_listings(
            html,
            card="div.srpTuple__tupleDetails",          # repeats per listing
            fields={
                "title": "h2.srpTuple__propertyTitle",
                "price": "div.srpTuple__price",
                "area":  "div.srpTuple__area",
            },
        )

    Inspect a real search-results page (DevTools > Elements), find the selector
    that repeats once per listing card, and fill these in.
    """
    rows: list[dict] = []
    for el in soup(html).select(card):
        row: dict[str, Any] = {}
        for key, sel in fields.items():
            node = el.select_one(sel)
            row[key] = node.get_text(strip=True) if node else None
        link = el.select_one("a[href]")
        if link:
            row["url"] = link.get("href")
        rows.append(row)
    return rows
