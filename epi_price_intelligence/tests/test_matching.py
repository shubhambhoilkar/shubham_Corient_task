from app.services.matching import (
    canonical_key,
    find_best_existing_key,
    normalize_listing_identity,
    normalize_storage,
    parse_title,
)


class _FakeRaw:
    """Minimal stand-in for scrapers.base.RawListing, just the fields matching.py reads."""

    def __init__(self, product_name, brand, model=None, storage=None, colour=None):
        self.product_name = product_name
        self.brand = brand
        self.model = model or product_name
        self.storage = storage
        self.colour = colour


def test_normalize_storage_variants():
    assert normalize_storage("256GB") == "256GB"
    assert normalize_storage("256 GB") == "256GB"
    assert normalize_storage("1TB") == "1024GB"
    assert normalize_storage(None) is None
    assert normalize_storage("no storage here") is None


def test_parse_title_extracts_colour_not_in_any_fixed_wordlist():
    # Regression test: "Lavender" previously fell out of a closed colour vocabulary and
    # came back as None. This must never regress -- colour parsing is positional now.
    model, storage, colour = parse_title("Apple iPhone 17 (256GB) - Lavender", "Apple")
    assert storage == "256GB"
    assert colour == "Lavender"
    assert "iphone 17" in model.lower()


def test_parse_title_handles_comma_separated_parenthetical_format():
    model, storage, colour = parse_title(
        "Apple iPhone 17 Pro (512 GB, Cosmic Orange)", "Apple"
    )
    assert storage == "512GB"
    assert colour == "Cosmic Orange"


def test_parse_title_handles_hyphenated_format():
    model, storage, colour = parse_title("Apple iPhone-17-Pro 512gb Cosmic-Orange", "Apple")
    assert storage == "512GB"
    assert colour == "Cosmic Orange"
    assert "17" in model


def test_three_retailer_titles_for_same_product_collapse_to_one_canonical_key():
    variants = [
        _FakeRaw("Apple iPhone 17 Pro (256GB) - Deep Blue", "Apple"),
        _FakeRaw("Apple iPhone 17 Pro 256 GB Deep Blue", "Apple"),
        _FakeRaw("Apple iPhone 17 Pro (256 GB, Deep Blue)", "Apple"),
    ]
    keys = [normalize_listing_identity(v)["canonical_key"] for v in variants]
    assert len(set(keys)) == 1


def test_different_variants_of_same_model_get_different_keys():
    base = _FakeRaw("Apple iPhone 17 Pro (256GB) - Deep Blue", "Apple")
    other_storage = _FakeRaw("Apple iPhone 17 Pro (512GB) - Deep Blue", "Apple")
    other_colour = _FakeRaw("Apple iPhone 17 Pro (256GB) - Cosmic Orange", "Apple")

    key_base = normalize_listing_identity(base)["canonical_key"]
    key_storage = normalize_listing_identity(other_storage)["canonical_key"]
    key_colour = normalize_listing_identity(other_colour)["canonical_key"]

    assert key_base != key_storage
    assert key_base != key_colour


def test_find_best_existing_key_merges_near_duplicates():
    existing = ["apple:iphone17pro:256gb:deepblue"]
    candidate = "apple:iphone17pro :256gb:deepblue"  # stray space, simulating minor noise
    merged = find_best_existing_key(candidate, existing)
    assert merged == existing[0]


def test_find_best_existing_key_does_not_merge_different_products():
    existing = ["apple:iphone17pro:256gb:deepblue"]
    candidate = "samsung:galaxys25:256gb:titaniumblack"
    assert find_best_existing_key(candidate, existing) is None
