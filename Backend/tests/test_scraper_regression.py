"""
Regression tests for the scraper pipeline's LOGIC, not live scraping. worker/runner.py
is otherwise never touched or even read closely across this whole project -- this
file only imports its pure, synchronous helper functions and pins down their exact
current behavior against fixed inputs. Zero Playwright, zero network calls, matching
the explicit scope agreed for this phase (the scraper was directly observed to be
slow/flaky against real sites during Phase 6/8 manual testing).
"""

from pathlib import Path

import pandas as pd

from worker.runner import (
    _merge_duplicate_businesses,
    _preprocess,
    clean_address,
    clean_email,
    format_phone,
    is_valid_email,
    normalize_website,
    score_email,
    select_best_email,
)


def test_format_phone_normalizes_10_digit_number():
    assert format_phone("305-555-1234") == "+1 305-555-1234"


def test_format_phone_strips_leading_country_code():
    assert format_phone("13055551234") == "+1 305-555-1234"


def test_format_phone_passes_through_unparseable_input():
    assert format_phone("123") == "123"
    assert format_phone("") == ""


def test_clean_address_extracts_first_real_address_and_skips_junk_segments():
    raw = "Closed · 123 Main St, Miami FL 33101 · (305) 555-1234"
    assert clean_address(raw) == "123 Main St, Miami FL 33101"


def test_clean_address_empty_input():
    assert clean_address("") == ""
    assert clean_address(None) == ""


def test_clean_email_strips_trailing_punctuation():
    assert clean_email("info@acme.com.") == "info@acme.com"
    assert clean_email("not-an-email") == ""


def test_is_valid_email_rejects_known_junk_domains():
    assert is_valid_email("someone@example.com") is False


def test_is_valid_email_rejects_image_asset_looking_addresses():
    assert is_valid_email("logo123x@site.com") is False
    assert is_valid_email("photo@2x.site.com") is False


def test_is_valid_email_rejects_noreply_locals():
    assert is_valid_email("noreply@acme.com") is False


def test_is_valid_email_accepts_a_plausible_business_email():
    assert is_valid_email("info@acmeplumbing.com") is True


def test_select_best_email_prefers_domain_match_and_generic_prefix():
    emails = {"randomguy@gmail.com", "info@acme.com"}
    assert select_best_email(emails, "http://acme.com") == "info@acme.com"


def test_score_email_penalizes_free_and_dev_looking_addresses():
    assert score_email("dev@acme.com", "acme.com") < score_email("info@acme.com", "acme.com")


def test_preprocess_merges_dedupes_by_phone_and_splits_by_website(tmp_path: Path):
    (tmp_path / "Miami_FL.csv").write_text(
        "Name,Category,Rating,Reviews,Address,Phone,Email,Website,Maps_URL\n"
        "Acme Plumbing,Plumber,4.5,10,123 Main St,+1 305-555-0100,,http://acme.com,http://maps/acme\n"
        "NoWeb Co,Roofer,4.0,3,456 Oak Ave,+1 305-555-0200,,,http://maps/noweb\n",
        encoding="utf-8",
    )
    (tmp_path / "Orlando_FL.csv").write_text(
        "Name,Category,Rating,Reviews,Address,Phone,Email,Website,Maps_URL\n"
        "Acme Plumbing,Plumber,4.5,10,123 Main St,+1 305-555-0100,,http://acme.com,http://maps/acme\n"
        "Other Biz,Electrician,3.5,5,789 Pine Rd,+1 305-555-0300,,http://otherbiz.com,http://maps/other\n",
        encoding="utf-8",
    )

    with_web, no_web = _preprocess(tmp_path, "FL", "plumbers")

    assert len(no_web) == 1
    assert no_web.iloc[0]["Name"] == "NoWeb Co"
    assert no_web.iloc[0]["Phone 2"] == ""

    # Acme appears in both cities but must be deduped to one row (same phone)
    assert len(with_web) == 2
    acme_row = with_web[with_web["Name"] == "Acme Plumbing"].iloc[0]
    assert acme_row["Times_Found"] == 2
    assert set(acme_row["Found_In_Cities"].split(", ")) == {"Miami", "Orlando"}
    # Only one phone/website involved -- the new " 2" columns stay empty
    assert acme_row["Phone 2"] == ""
    assert acme_row["Website 2"] == ""


def test_preprocess_empty_folder_returns_empty_frames(tmp_path: Path):
    with_web, no_web = _preprocess(tmp_path, "FL", "plumbers")
    assert with_web.empty
    assert no_web.empty


# ── _merge_duplicate_businesses: identity is Phone/Website, not Name ──

def _biz(name, *, phone="", website="", city="Miami"):
    return {"Name": name, "City": city, "Phone": phone, "Website": website,
            "Category": "", "Rating": "", "Reviews": "", "Address": "",
            "Email": "", "Maps_URL": ""}


def test_normalize_website_strips_protocol_www_slash_and_query():
    assert normalize_website("https://WWW.Acme.com/?utm=1") == "acme.com"
    assert normalize_website("http://acme.com/") == "acme.com"
    assert normalize_website("") == ""


def test_merge_same_phone_different_name_collapses_to_one_row():
    """The exact bug being fixed: the old Name+Phone key never merged a business
    re-listed under a different name. Phone alone must now be enough."""
    df = pd.DataFrame([
        _biz("Acme Plumbing", phone="+1 305-555-0100"),
        _biz("Acme Plumbing LLC", phone="+1 305-555-0100"),
    ])
    result = _merge_duplicate_businesses(df)
    assert len(result) == 1
    assert result.iloc[0]["Name"] == "Acme Plumbing"  # first-found wins
    assert result.iloc[0]["Times_Found"] == 2


def test_merge_same_phone_different_website_populates_website_2():
    df = pd.DataFrame([
        _biz("Acme Plumbing", phone="+1 305-555-0100", website="http://acme.com"),
        _biz("Acme Plumbing", phone="+1 305-555-0100", website="http://acme-plumbing.net"),
    ])
    result = _merge_duplicate_businesses(df)
    assert len(result) == 1
    row = result.iloc[0]
    assert row["Phone 2"] == ""
    assert row["Website"] == "http://acme.com"
    assert row["Website 2"] == "http://acme-plumbing.net"


def test_merge_same_website_different_phone_populates_phone_2():
    df = pd.DataFrame([
        _biz("Acme Plumbing", phone="+1 305-555-0100", website="http://acme.com"),
        _biz("Acme Plumbing", phone="+1 305-555-0200", website="http://acme.com"),
    ])
    result = _merge_duplicate_businesses(df)
    assert len(result) == 1
    row = result.iloc[0]
    assert row["Phone"] == "+1 305-555-0100"
    assert row["Phone 2"] == "+1 305-555-0200"
    assert row["Website 2"] == ""


def test_merge_same_phone_and_website_is_a_trivial_single_row():
    df = pd.DataFrame([
        _biz("Acme Plumbing", phone="+1 305-555-0100", website="http://acme.com"),
        _biz("Acme Plumbing", phone="+1 305-555-0100", website="https://www.acme.com/"),
    ])
    result = _merge_duplicate_businesses(df)
    assert len(result) == 1
    assert result.iloc[0]["Phone 2"] == ""
    assert result.iloc[0]["Website 2"] == ""  # www/protocol variant, not a real 2nd site


def test_merge_transitive_chain_through_shared_phone_and_website():
    """A<->B share a phone, A<->C share a website, B and C share nothing
    directly -- all three must still merge into one business."""
    df = pd.DataFrame([
        _biz("Biz A", phone="+1 305-555-0100", website="http://acme.com"),
        _biz("Biz B", phone="+1 305-555-0100", website="http://other.com"),
        _biz("Biz C", phone="+1 305-555-0300", website="http://acme.com"),
    ])
    result = _merge_duplicate_businesses(df)
    assert len(result) == 1
    row = result.iloc[0]
    assert row["Times_Found"] == 3
    assert {row["Phone"], row["Phone 2"]} == {"+1 305-555-0100", "+1 305-555-0300"}
    assert {row["Website"], row["Website 2"]} == {"http://acme.com", "http://other.com"}


def test_merge_drops_a_third_distinct_phone_beyond_the_first_two():
    df = pd.DataFrame([
        _biz("Biz A", phone="+1 305-555-0100", website="http://acme.com"),
        _biz("Biz B", phone="+1 305-555-0200", website="http://acme.com"),
        _biz("Biz C", phone="+1 305-555-0300", website="http://acme.com"),
    ])
    result = _merge_duplicate_businesses(df)
    assert len(result) == 1
    row = result.iloc[0]
    assert row["Times_Found"] == 3
    assert row["Phone"] == "+1 305-555-0100"
    assert row["Phone 2"] == "+1 305-555-0200"  # the 3rd ("...0300") is dropped


def test_merge_rows_with_neither_phone_nor_website_never_merge():
    df = pd.DataFrame([
        _biz("Mystery Biz 1"),
        _biz("Mystery Biz 2"),
    ])
    result = _merge_duplicate_businesses(df)
    assert len(result) == 2


def test_merge_second_pass_aggregates_times_found_and_cities_from_already_merged_rows():
    """Simulates the real pipeline's two-call-site scenario: pass 1 merges A+B
    and separately C+D (by phone, in different cities); pass 2 discovers X and Y
    actually share a website (e.g. Phase 2 enrichment just found it) and must
    merge them into one row whose Times_Found/Found_In_Cities reflect all 4
    original rows, not just the 2 "indices" being unioned in pass 2 itself."""
    pass1_input = pd.DataFrame([
        _biz("Acme A", phone="+1 305-555-0100", city="Miami"),
        _biz("Acme B", phone="+1 305-555-0100", city="Orlando"),
        _biz("Other C", phone="+1 305-555-0300", city="Tampa"),
        _biz("Other D", phone="+1 305-555-0300", city="Naples"),
    ])
    after_pass1 = _merge_duplicate_businesses(pass1_input)
    assert len(after_pass1) == 2  # two separate businesses so far, no website yet

    # Now both groups turn out to share a website (as if enrichment just found it).
    after_pass1["Website"] = "http://acme.com"
    after_pass2 = _merge_duplicate_businesses(after_pass1)

    assert len(after_pass2) == 1
    row = after_pass2.iloc[0]
    assert row["Times_Found"] == 4
    assert set(row["Found_In_Cities"].split(", ")) == {"Miami", "Orlando", "Tampa", "Naples"}


def test_merge_is_idempotent_on_its_own_output():
    df = pd.DataFrame([
        _biz("Acme Plumbing", phone="+1 305-555-0100", website="http://acme.com"),
        _biz("Acme Plumbing", phone="+1 305-555-0200", website="http://acme.com"),
    ])
    once  = _merge_duplicate_businesses(df)
    twice = _merge_duplicate_businesses(once)
    assert len(twice) == len(once) == 1
    assert twice.iloc[0]["Phone"] == once.iloc[0]["Phone"]
    assert twice.iloc[0]["Phone 2"] == once.iloc[0]["Phone 2"]
