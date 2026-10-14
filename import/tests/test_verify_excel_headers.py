"""Tests for verify_excel_headers against small workbooks built in tmp_path.

Each test writes its own .xlsx files with openpyxl, so nothing under data/ is read.
"""

import sys

import pytest
from openpyxl import Workbook

import verify_excel_headers as veh


def _new_workbook():
    """Return an empty workbook with the default sheet removed."""
    wb = Workbook()
    wb.remove(wb.active)
    return wb


def _header_sheet(wb, title, headers):
    """Add a sheet with column headers on row 3, below two title rows."""
    ws = wb.create_sheet(title)
    ws.cell(row=1, column=1, value="Titel")
    for col, name in enumerate(headers, start=1):
        ws.cell(row=3, column=col, value=name)


def _key_sheet(wb, title, keys):
    """Add a metadati-style sheet with one key per row in column A from row 3."""
    ws = wb.create_sheet(title)
    for row, key in enumerate(keys, start=3):
        ws.cell(row=row, column=1, value=key)


def _write_belege(folder, headers, name="belege_2020.xlsx"):
    """Write a belege workbook with one sheet holding the given headers."""
    wb = _new_workbook()
    _header_sheet(wb, "Personen", headers)
    wb.save(folder / name)


def _write_chronotopi(folder, headers, name="chronotopi_stern.xlsx"):
    """Write a chronotopi workbook whose only sheet holds the given headers."""
    wb = _new_workbook()
    _header_sheet(wb, "Ereignisse", headers)
    wb.save(folder / name)


def _write_metadati(folder, keys, second_headers):
    """Write a metadati workbook with keys on its first sheet and headers after."""
    wb = _new_workbook()
    _key_sheet(wb, "Stammdaten", keys)
    _header_sheet(wb, "Zusatz", second_headers)
    wb.save(folder / "metadati_P001.xlsx")


@pytest.fixture
def template_dir(tmp_path):
    """Write one template per prefix and return the template folder."""
    folder = tmp_path / "templates"
    folder.mkdir()
    wb = _new_workbook()
    _header_sheet(wb, "Personen", ["Name", "Vorname", "Geburt"])
    wb.save(folder / "belege_template.xlsx")
    wb = _new_workbook()
    _header_sheet(wb, "Ereignisse", ["event_id", "event_label", "date_start"])
    wb.save(folder / "chronotopoi_template_v4.xlsx")
    wb = _new_workbook()
    _key_sheet(wb, "Stammdaten", ["Titel", "Quelle 1", "L1", "L2"])
    _header_sheet(wb, "Zusatz", ["Feld A", "Feld B"])
    wb.save(folder / "metadati_template.xlsx")
    return folder


@pytest.fixture
def data_dir(tmp_path):
    """Return an empty folder for the workbooks under test."""
    folder = tmp_path / "data"
    folder.mkdir()
    return folder


class TestConformingFiles:
    """Workbooks that match their templates produce no discrepancies."""

    def test_matching_files_have_no_discrepancies(self, template_dir, data_dir):
        """Belege, chronotopi, and metadati files that match report no errors."""
        _write_belege(data_dir, ["Name", "Vorname", "Geburt"])
        _write_chronotopi(data_dir, ["event_id", "event_label", "date_start"])
        _write_metadati(
            data_dir, ["Titel", "Quelle 1", "L1", "L2"], ["Feld A", "Feld B"]
        )
        result = veh.verify_files(data_dir, template_dir)
        assert result.discrepancies_found is False
        assert result.files_checked == 3
        assert all(not file.errors for file in result.files)

    def test_column_names_are_compared_case_insensitively(self, template_dir, data_dir):
        """Header case is ignored, so NAME matches the template's Name."""
        _write_belege(data_dir, ["NAME", "vorname", "geburt"])
        result = veh.verify_files(data_dir, template_dir)
        assert result.discrepancies_found is False

    def test_quelle_keys_count_as_one_group(self, template_dir, data_dir):
        """A different Quelle number still matches, because Quelle keys are grouped."""
        _write_metadati(
            data_dir, ["Titel", "Quelle 7", "L1", "L2"], ["Feld A", "Feld B"]
        )
        result = veh.verify_files(data_dir, template_dir)
        assert result.discrepancies_found is False

    def test_files_without_known_prefix_are_skipped(self, template_dir, data_dir):
        """A workbook whose name has no known prefix is not counted or checked."""
        _write_belege(data_dir, ["Name"], name="notizen.xlsx")
        result = veh.verify_files(data_dir, template_dir)
        assert result.files_checked == 0
        assert result.files == []


class TestColumnDiscrepancies:
    """Columns missing from or added to a sheet are reported by name."""

    def test_missing_column_is_reported(self, template_dir, data_dir):
        """A template column absent from the file is listed as missing."""
        _write_belege(data_dir, ["Name", "Vorname"])
        result = veh.verify_files(data_dir, template_dir)
        assert result.discrepancies_found is True
        (error,) = result.files[0].errors
        assert error.error_type == "column_mismatch"
        assert error.missing == ["geburt"]
        assert error.extra == []

    def test_extra_column_is_reported(self, template_dir, data_dir):
        """A column the template does not have is listed as extra."""
        _write_belege(data_dir, ["Name", "Vorname", "Geburt", "Notiz"])
        result = veh.verify_files(data_dir, template_dir)
        (error,) = result.files[0].errors
        assert error.extra == ["notiz"]
        assert error.missing == []

    def test_chronotopi_file_is_checked_against_v4_template(
        self, template_dir, data_dir
    ):
        """A chronotopi file is matched to the v4 template and its columns checked."""
        _write_chronotopi(data_dir, ["event_id", "event_label"])
        result = veh.verify_files(data_dir, template_dir)
        (file_result,) = result.files
        assert file_result.prefix == "chronotopoi"
        assert file_result.template == "chronotopoi_template_v4.xlsx"
        (error,) = file_result.errors
        assert error.missing == ["date_start"]


class TestMetadatiKeys:
    """Metadati files compare first-sheet keys and later-sheet headers."""

    def test_missing_key_is_reported_under_keys(self, template_dir, data_dir):
        """A template key absent from the first sheet is listed under keys."""
        _write_metadati(data_dir, ["Quelle 1", "L1", "L2"], ["Feld A", "Feld B"])
        result = veh.verify_files(data_dir, template_dir)
        (error,) = result.files[0].errors
        assert error.error_type == "missing_keys"
        assert error.keys == ["titel"]

    def test_extra_key_is_reported_under_keys(self, template_dir, data_dir):
        """A key the template does not have is listed under keys as extra."""
        keys = ["Titel", "Quelle 1", "L1", "L2", "Notizen"]
        _write_metadati(data_dir, keys, ["Feld A", "Feld B"])
        result = veh.verify_files(data_dir, template_dir)
        (error,) = result.files[0].errors
        assert error.error_type == "extra_keys"
        assert error.keys == ["notizen"]

    def test_later_sheet_columns_are_checked(self, template_dir, data_dir):
        """Sheets after the first are compared by column headers."""
        _write_metadati(data_dir, ["Titel", "Quelle 1", "L1", "L2"], ["Feld A"])
        result = veh.verify_files(data_dir, template_dir)
        (error,) = result.files[0].errors
        assert error.error_type == "column_mismatch"
        assert error.sheet == "Zusatz"
        assert error.missing == ["feld b"]


class TestErrorsAndHelpers:
    """A missing folder is returned as an error, and helpers report on stderr."""

    def test_missing_data_dir_returns_error_result(self, template_dir, tmp_path):
        """A data folder that does not exist gives an error result, not an exception."""
        result = veh.verify_files(tmp_path / "absent", template_dir)
        assert result.error is not None
        assert "Data directory not found" in result.error
        assert result.files_checked == 0

    def test_missing_literal_path_exits_with_status_one(
        self, data_dir, monkeypatch, capsys
    ):
        """A literal path that does not exist exits with status 1 and a message."""
        monkeypatch.chdir(data_dir)
        with pytest.raises(SystemExit) as excinfo:
            veh.get_files_to_verify(data_dir, "absent.xlsx")
        assert excinfo.value.code == 1
        assert "File not found" in capsys.readouterr().err

    def test_hidden_sheets_are_skipped_when_reading_headers(self):
        """Sheets whose names start with an underscore are not read."""
        wb = _new_workbook()
        _header_sheet(wb, "Personen", ["Name"])
        _header_sheet(wb, "_intern", ["Geheim"])
        assert veh.get_column_headers(wb) == {"Personen": ["Name"]}

    def test_unreadable_workbook_returns_none(self, tmp_path, capsys):
        """A file that is not a workbook gives None and an error on stderr."""
        path = tmp_path / "belege_broken.xlsx"
        path.write_text("not a workbook")
        assert veh.load_workbook(path) is None
        assert "Failed to load" in capsys.readouterr().err

    def test_missing_template_is_warned_and_left_out(self, tmp_path, capsys):
        """An absent template is reported as a warning and not loaded."""
        templates, template_keys = veh.load_templates(tmp_path)
        assert templates == {}
        assert template_keys == {}
        assert "Template not found" in capsys.readouterr().err


class TestMain:
    """Check that main uses the folder overrides and sets the exit status."""

    def _run_main(self, monkeypatch, data_dir, template_dir):
        """Run main with the folder overrides and return its exit status."""
        monkeypatch.setenv("DATA_DIR", str(data_dir))
        monkeypatch.setenv("TEMPLATE_DIR", str(template_dir))
        monkeypatch.setattr(sys, "argv", ["verify_excel_headers.py"])
        with pytest.raises(SystemExit) as excinfo:
            veh.main()
        return excinfo.value.code

    def test_discrepancy_prints_report_and_exits_one(
        self, template_dir, data_dir, monkeypatch, capsys
    ):
        """A file with a missing column is listed under DISCREPANCIES; exit is 1."""
        _write_belege(data_dir, ["Name"])
        code = self._run_main(monkeypatch, data_dir, template_dir)
        out = capsys.readouterr().out
        assert code == 1
        assert "DISCREPANCIES: belege_2020.xlsx" in out
        assert "Discrepancies found: YES" in out

    def test_conforming_files_exit_zero(
        self, template_dir, data_dir, monkeypatch, capsys
    ):
        """Conforming files are listed as OK and the exit status is 0."""
        _write_belege(data_dir, ["Name", "Vorname", "Geburt"])
        code = self._run_main(monkeypatch, data_dir, template_dir)
        out = capsys.readouterr().out
        assert code == 0
        assert "OK: belege_2020.xlsx" in out
        assert "Discrepancies found: NO" in out
