"""
Regression tests for the scraper pipeline's LOGIC, not live scraping. worker/runner.py
is otherwise never touched or even read closely across this whole project -- this
file only imports its pure, synchronous helper functions and pins down their exact
current behavior against fixed inputs. Zero Playwright, zero network calls, matching
the explicit scope agreed for this phase (the scraper was directly observed to be
slow/flaky against real sites during Phase 6/8 manual testing).
"""

from pathlib import Path

from worker.runner import (
    _preprocess,
    clean_address,
    clean_email,
    format_phone,
    is_valid_email,
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

    # Acme appears in both cities but must be deduped to one row (same Name+Phone)
    assert len(with_web) == 2
    acme_row = with_web[with_web["Name"] == "Acme Plumbing"].iloc[0]
    assert acme_row["Times_Found"] == 2
    assert set(acme_row["Found_In_Cities"].split(", ")) == {"Miami", "Orlando"}


def test_preprocess_empty_folder_returns_empty_frames(tmp_path: Path):
    with_web, no_web = _preprocess(tmp_path, "FL", "plumbers")
    assert with_web.empty
    assert no_web.empty
