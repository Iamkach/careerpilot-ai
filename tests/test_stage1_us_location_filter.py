"""
Tests for stage1_scrape.is_us_location() -- the freshness/location pre-filter that keeps a job
unless its location string is clearly non-US. LinkedIn/Indeed listings often carry standardized
"Metropolitan Area"/"Bay Area" geo names or spelled-out state names instead of a two-letter state
code, which the original regex (state abbreviations + "United States"/"Remote" only) missed,
silently dropping real US jobs like "New Jersey" or "San Francisco Bay Area" as [location].
"""
import pytest

from scripts.stage1_scrape import is_us_location


@pytest.mark.parametrize(
    "location",
    [
        "",
        "New York, NY",
        "United States",
        "Remote",
        "New Jersey",
        "Los Angeles Metropolitan Area",
        "New York City Metropolitan Area",
        "San Francisco Bay Area",
        "Memphis Metropolitan Area",
        "SF Office",
        "San Francisco Office",
        "San Francisco",
        "Seattle",
        "Austin",
    ],
)
def test_us_locations_kept(location):
    assert is_us_location(location) is True


@pytest.mark.parametrize(
    "location",
    [
        "London, United Kingdom",
        "Toronto, ON, Canada",
        "Bangalore, India",
        "Berlin, Germany",
        "Brazil",
        "London, UK",
        "Reykjavík",
    ],
)
def test_non_us_locations_dropped(location):
    assert is_us_location(location) is False
