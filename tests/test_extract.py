"""Extraction tests -- pure HTML parsing, no network."""
from __future__ import annotations

from veil.extract import (
    css_listings,
    extract_jsonld,
    find_by_type,
    flatten_listing,
    parse_listings,
)

_JSONLD_PAGE = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"2 BHK Flat",
 "url":"https://x.com/p/123",
 "offers":{"@type":"Offer","price":"4500000","priceCurrency":"INR"},
 "address":{"@type":"PostalAddress","addressLocality":"Andheri","addressRegion":"Mumbai"}}
</script>
<script type="application/ld+json">
{"@graph":[{"@type":"BreadcrumbList"},
 {"@type":"Apartment","name":"3 BHK","url":"https://x.com/p/456",
  "floorSize":{"@type":"QuantitativeValue","value":1200,"unitText":"sqft"}}]}
</script>
</head><body></body></html>
"""


def test_extract_jsonld_flattens_graph():
    objs = extract_jsonld(_JSONLD_PAGE)
    types = {o.get("@type") for o in objs}
    assert "Product" in types
    assert "Apartment" in types  # pulled out of @graph
    assert "BreadcrumbList" in types


def test_find_by_type_is_recursive_and_case_insensitive():
    objs = extract_jsonld(_JSONLD_PAGE)
    found = find_by_type(objs, {"product", "apartment"})
    assert len(found) == 2


def test_flatten_listing_pulls_common_fields():
    objs = extract_jsonld(_JSONLD_PAGE)
    product = find_by_type(objs, {"Product"})[0]
    row = flatten_listing(product)
    assert row["price"] == "4500000"
    assert row["currency"] == "INR"
    assert row["locality"] == "Andheri"
    assert row["url"] == "https://x.com/p/123"


def test_parse_listings_drops_noise_keeps_real():
    rows = parse_listings(_JSONLD_PAGE)
    urls = {r["url"] for r in rows}
    assert urls == {"https://x.com/p/123", "https://x.com/p/456"}


def test_css_listings_extracts_per_card():
    html = """
    <div class="card"><a href="/a">A</a><span class="price">100</span></div>
    <div class="card"><a href="/b">B</a><span class="price">200</span></div>
    """
    rows = css_listings(html, card="div.card", fields={"price": "span.price"})
    assert [r["price"] for r in rows] == ["100", "200"]
    assert [r["url"] for r in rows] == ["/a", "/b"]
