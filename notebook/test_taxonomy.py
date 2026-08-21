"""Unit tests for taxonomy.py using MAXQDA_Code_System.mmd."""

import pytest
from pathlib import Path
from datetime import date
from taxonomy import load_taxonomy
from timespan import Timespan


@pytest.fixture
def maxqda_taxonomy():
    """Load taxonomy from MAXQDA Code System."""
    path = Path(__file__).parent.parent / "data" / "maxqda" / "MAXQDA_Code_System.mmd"
    return load_taxonomy(path)


@pytest.fixture
def default_taxonomy():
    """Load default taxonomy from docs."""
    return load_taxonomy()


class TestZeitangaben:
    """Tests for zeitangaben() method."""

    def test_zeitangaben_contains_known_dates(self, maxqda_taxonomy):
        """zeitangaben() should contain specific known dates as Timespan objects."""
        result = maxqda_taxonomy.zeitangaben()
        assert all(isinstance(ts, Timespan) for ts in result)
        
        # Check for specific years (1909, 1933, 1945)
        # Year nodes span the full year
        ts_1909 = next((ts for ts in result if ts.start == date(1909, 1, 1)), None)
        assert ts_1909 is not None
        assert ts_1909.start == date(1909, 1, 1)
        assert ts_1909.end == date(1909, 12, 31)  # Full year range
        
        ts_1933 = next((ts for ts in result if ts.start == date(1933, 1, 1)), None)
        assert ts_1933 is not None
        assert ts_1933.start == date(1933, 1, 1)
        assert ts_1933.end == date(1933, 12, 31)  # Full year range
        
        ts_1945 = next((ts for ts in result if ts.start == date(1945, 1, 1)), None)
        assert ts_1945 is not None
        assert ts_1945.start == date(1945, 1, 1)
        assert ts_1945.end == date(1945, 12, 31)  # Full year range
        
        # Check for month (April 1933) - spans full month
        ts_april_1933 = next((ts for ts in result if ts.start == date(1933, 4, 1) and ts.end == date(1933, 4, 30)), None)
        assert ts_april_1933 is not None
        assert ts_april_1933.start == date(1933, 4, 1)
        assert ts_april_1933.end == date(1933, 4, 30)  # Full month range
        
        # Check for specific date (1. April 1933) - single day
        ts_1april_1933 = next((ts for ts in result if ts.start == date(1933, 4, 1) and ts.end == date(1933, 4, 1)), None)
        assert ts_1april_1933 is not None
        assert ts_1april_1933.start == date(1933, 4, 1)
        assert ts_1april_1933.end == date(1933, 4, 1)  # Single day
        assert ts_1april_1933.is_point is True  # Single point in time

    def test_zeitangaben_returns_timespans(self, maxqda_taxonomy):
        """zeitangaben() should return a list of Timespan objects."""
        result = maxqda_taxonomy.zeitangaben()
        assert isinstance(result, list)
        assert all(isinstance(item, Timespan) for item in result)

    def test_zeitangaben_removes_from_taxonomy(self, maxqda_taxonomy):
        """Zeitangaben category should not be in the regular structures (removed at construction time)."""
        # The three special categories (Zeitangaben, Personae, GO) should not be in categories
        assert "Zeitangaben" not in maxqda_taxonomy.categories
        assert "Personae" not in maxqda_taxonomy.categories
        assert "GO" not in maxqda_taxonomy.categories
        
        # But the data should still be accessible via the methods
        result = maxqda_taxonomy.zeitangaben()
        assert len(result) > 0
        assert all(isinstance(ts, Timespan) for ts in result)


class TestPersonae:
    """Tests for personae() method."""

    def test_personae_returns_list(self, maxqda_taxonomy):
        """personae() should return a list of strings."""
        result = maxqda_taxonomy.personae()
        assert isinstance(result, list)
        assert all(isinstance(item, str) for item in result)

    def test_personae_contains_known_people(self, maxqda_taxonomy):
        """personae() should contain specific known people."""
        result = maxqda_taxonomy.personae()
        assert "Burgheim, Hedwig" in result
        assert len(result) > 0

    def test_personae_is_sorted(self, maxqda_taxonomy):
        """personae() should return sorted results."""
        result = maxqda_taxonomy.personae()
        assert result == sorted(result)

    def test_personae_removes_from_taxonomy(self, maxqda_taxonomy):
        """Personae category should not be in the regular structures (removed at construction time)."""
        # The three special categories (Zeitangaben, Personae, GO) should not be in categories
        assert "Personae" not in maxqda_taxonomy.categories
        assert "Zeitangaben" not in maxqda_taxonomy.categories
        assert "GO" not in maxqda_taxonomy.categories
        
        # But the data should still be accessible via the methods
        result = maxqda_taxonomy.personae()
        assert len(result) > 0


class TestGO:
    """Tests for go() method."""

    def test_go_returns_list_of_dicts(self, maxqda_taxonomy):
        """go() should return a list of dictionaries."""
        result = maxqda_taxonomy.go()
        assert isinstance(result, list)
        assert all(isinstance(item, dict) for item in result)

    def test_go_dicts_have_label_and_address(self, maxqda_taxonomy):
        """Each dict from go() should have 'label' and 'address' keys."""
        result = maxqda_taxonomy.go()
        assert all('label' in item and 'address' in item for item in result)

    def test_go_contains_known_locations(self, maxqda_taxonomy):
        """go() should contain specific known leaf locations (with country context)."""
        result = maxqda_taxonomy.go()
        labels = [item['label'] for item in result]
        # Locations are labeled with their parent country context
        assert any('Adlon' in label and 'Deutschland' in label for label in labels)
        assert any('Haifa' in label and 'Palästina' in label for label in labels)
        # Tel Aviv may not have country context if it's a direct child of GO
        assert any('Tel Aviv' in label for label in labels)

    def test_go_addresses_are_hierarchical(self, maxqda_taxonomy):
        """go() addresses should contain hierarchical paths with '/'."""
        result = maxqda_taxonomy.go()
        # Find Adlon entry (a leaf location with Deutschland context)
        adlon = next((item for item in result if 'Adlon' in item['label'] and 'Deutschland' in item['label']), None)
        assert adlon is not None
        assert 'Deutschland' in adlon['address']
        assert '/' in adlon['address']

    def test_go_is_sorted_by_label(self, maxqda_taxonomy):
        """go() should return results sorted by label."""
        result = maxqda_taxonomy.go()
        labels = [item['label'] for item in result]
        assert labels == sorted(labels)

    def test_go_removes_from_taxonomy(self, maxqda_taxonomy):
        """GO category should not be in the regular structures (removed at construction time)."""
        # The three special categories (Zeitangaben, Personae, GO) should not be in categories
        assert "GO" not in maxqda_taxonomy.categories
        assert "Zeitangaben" not in maxqda_taxonomy.categories
        assert "Personae" not in maxqda_taxonomy.categories
        
        # But the data should still be accessible via the methods
        result = maxqda_taxonomy.go()
        assert len(result) > 0
        assert all('label' in item and 'address' in item for item in result)


class TestDefaultTaxonomy:
    """Tests for the default taxonomy from docs."""

    def test_default_taxonomy_has_categories(self, default_taxonomy):
        """Default taxonomy should have various categories (before extraction)."""
        # Check for categories that aren't Zeitangaben, Personae, or GO
        assert "Religion" in default_taxonomy.categories
        assert "Zionismus" in default_taxonomy.categories
        assert "LL" in default_taxonomy.categories  # Lebenslauf

    def test_default_taxonomy_categories_have_icons(self, default_taxonomy):
        """All categories should have icons."""
        for key, info in default_taxonomy.categories.items():
            assert 'icon' in info
            assert 'label' in info
            assert info['icon'] != ""
