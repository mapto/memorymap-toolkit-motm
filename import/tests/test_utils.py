"""Unit tests for the spreadsheet-cell and URL helpers in utils.py."""

import math

import pytest

from utils import (
    clean_str,
    extract_id_from_url,
    extract_url_map,
    extract_urls_from_text,
    is_empty,
)


@pytest.mark.parametrize("value", [None, math.nan, "nan", "None", "   "])
def test_clean_str_returns_empty_text_for_missing_values(value):
    """clean_str() turns None, NaN, and blank placeholders into an empty string."""
    assert clean_str(value) == ""


def test_clean_str_drops_float_suffix_from_whole_numbers():
    """clean_str() reads a whole number stored as 12.0 as the text 12."""
    assert clean_str(12.0) == "12"
    assert clean_str(" 1.5 ") == "1.5"


@pytest.mark.parametrize(
    "value", [None, "", "  ", "nan", "None", "-", "\u2013", "\u2014"]
)
def test_is_empty_accepts_missing_values_and_dash_placeholders(value):
    """is_empty() is True for missing values, blanks, and dash placeholders."""
    assert is_empty(value)


@pytest.mark.parametrize("value", [0, "0", "Berlin"])
def test_is_empty_keeps_zero_and_real_text(value):
    """is_empty() is False for zero and for ordinary text."""
    assert not is_empty(value)


def test_extract_urls_from_text_returns_each_link_in_order():
    """extract_urls_from_text() lists every http and https link in a cell."""
    text = "Wiki https://en.example.org/A and http://de.example.org/B"

    assert extract_urls_from_text(text) == [
        "https://en.example.org/A",
        "http://de.example.org/B",
    ]


def test_extract_urls_from_text_returns_empty_list_for_blank_cells():
    """extract_urls_from_text() returns an empty list for None, blanks, and nan."""
    assert extract_urls_from_text(None) == []
    assert extract_urls_from_text("  ") == []
    assert extract_urls_from_text("nan") == []


def test_extract_url_map_keys_urls_by_hostname_and_keeps_other_text():
    """extract_url_map() maps hostnames to URLs and returns the leftover text."""
    url_map, remaining = extract_url_map(
        "Wiki https://en.example.org/A and https://de.example.org/B more"
    )

    assert url_map == {
        "en.example.org": "https://en.example.org/A",
        "de.example.org": "https://de.example.org/B",
    }
    assert remaining.split() == ["Wiki", "and", "more"]


def test_extract_id_from_url_returns_last_path_segment():
    """extract_id_from_url() returns the Wikidata ID at the end of a link."""
    assert extract_id_from_url("https://www.wikidata.org/wiki/Q1794") == "Q1794"


def test_extract_id_from_url_returns_none_for_blank_values():
    """extract_id_from_url() returns None for None, blanks, and nan."""
    assert extract_id_from_url(None) is None
    assert extract_id_from_url(" ") is None
    assert extract_id_from_url("nan") is None
