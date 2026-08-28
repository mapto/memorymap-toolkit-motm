#!/usr/bin/env python3
r"""
Excel Column Header Verification Script

Verifies that column titles in Excel files in data/nuove schede
conform to templates in data/template based on file prefix.

POSIX-compliant: works with standard input and output.

Usage:
    verify_excel_headers.py                     # Check all files in data/nuove schede
    verify_excel_headers.py <filepath>          # Check specific file (relative to CWD)
    verify_excel_headers.py <glob_pattern>      # Check files matching glob pattern
    
Examples:
    uv run verify_excel_headers.py
    uv run verify_excel_headers.py metadati_file.xlsx
    uv run verify_excel_headers.py metadati_*.xlsx
"""

import sys
import os
from pathlib import Path
from dataclasses import dataclass, field
import glob
import openpyxl


# ============================================================================
# Type Definitions (Dataclasses)
# ============================================================================

# Type aliases for clarity
SheetHeaders = dict[str, list[str]]  # sheet_name -> column headers
SheetKeys = dict[str, list[str]]     # sheet_name -> keys (for metadati)


@dataclass
class VerificationError:
    """Represents a single verification discrepancy."""
    error_type: str  # 'column_mismatch', 'missing_keys', 'extra_keys', etc.
    sheet: str
    message: str
    missing: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)


@dataclass
class VersionScore:
    """Match score for a single template version."""
    score: int  # 0-100
    errors: list[VerificationError] = field(default_factory=list)


@dataclass
class VersionScores:
    """Container for scores across all template versions."""
    versions: dict[str, VersionScore] = field(default_factory=dict)


@dataclass
class FileResult:
    """Verification results for a single file."""
    name: str
    prefix: str
    template: str
    has_discrepancies: bool
    sheets_checked: int
    errors: list[VerificationError] = field(default_factory=list)
    best_matching_version: str = None  # For chronotopoi files
    version_scores: VersionScores = None  # For chronotopoi files


@dataclass
class VerificationResult:
    """Complete verification results for all files."""
    discrepancies_found: bool
    files_checked: int
    files_with_discrepancies: int
    total_sheets_checked: int
    sheets_with_discrepancies: int
    files: list[FileResult] = field(default_factory=list)
    error: str = None  # Error message if verification failed


# ============================================================================
# Configuration
# ============================================================================

prefix_to_template = {
    'belege': 'belege_template.xlsx',
    'chronotopoi': 'chronotopoi_template_v4.xlsx',  # Consolidated to v4 only
    'metadati': 'metadati_template.xlsx'
}


def get_prefix(filename: str) -> str:
    """Extract prefix from filename (belege_, chronotopi/chronotopoi, metadati_)."""
    name = filename.lower()
    
    if name.startswith('belege_'):
        return 'belege'
    elif name.startswith('chronotopi') or name.startswith('chronotopo'):
        return 'chronotopoi'
    elif name.startswith('metadati_'):
        return 'metadati'
    return None


def get_column_headers(wb: openpyxl.Workbook, header_row: int = 3) -> SheetHeaders:
    """Extract column headers from all sheets in workbook (row 3)."""
    headers: SheetHeaders = {}
    for sheet_name in wb.sheetnames:
        if sheet_name.startswith("_"):
            continue

        ws = wb[sheet_name]
        cols = []
        for cell in ws[header_row]:  # Third row (after 2 title rows)
            if cell.value is not None:
                cols.append(str(cell.value).strip())
        headers[sheet_name] = cols
    return headers


def get_metadati_keys(wb: openpyxl.Workbook, sheet_name: str = None) -> SheetKeys:
    """
    Extract key-value pairs from first column starting at row 3.
    Used for metadati sheets which have key-value format instead of column headers.
    
    Args:
        wb: Workbook to extract keys from
        sheet_name: Specific sheet to extract from (default: first sheet)
    
    Returns:
        Dictionary mapping sheet names to list of keys
    """
    keys: SheetKeys = {}
    sheets_to_process = [sheet_name] if sheet_name else [wb.sheetnames[0]]
    
    for sname in sheets_to_process:
        if sname not in wb.sheetnames:
            continue
        ws = wb[sname]
        key_list = []
        for row_num in range(3, ws.max_row + 1):
            cell = ws.cell(row=row_num, column=1)
            if cell.value is not None:
                key = str(cell.value).strip()
                if key:  # Only add non-empty keys
                    key_list.append(key)
        keys[sname] = key_list
    
    return keys


def normalize_metadati_keys(keys: list[str]) -> set:
    """
    Normalize metadati keys for comparison.
    Treats "Quelle *" patterns and "L*" patterns as groups.
    Case-insensitive comparison.
    """
    normalized = set()
    for key in keys:
        key_lower = key.lower()
        if key_lower.startswith('quelle '):
            # Treat all "Quelle X" as a single pattern "Quelle *"
            normalized.add('quelle *')
        elif key_lower.startswith('l'):
            # Treat all keys starting with "L" as a single pattern "L*"
            normalized.add('l*')
        else:
            normalized.add(key_lower)
    return normalized


def to_lowercase_set(items: list[str]) -> set:
    """Convert a list of strings to a lowercase set for case-insensitive comparison."""
    return set(item.lower() for item in items)


def load_workbook(path: Path) -> openpyxl.Workbook:
    """Load workbook from path."""
    try:
        return openpyxl.load_workbook(str(path), data_only=True)
    except Exception as e:
        print(f"ERROR: Failed to load {path}: {e}", file=sys.stderr)
        return None


def load_templates(template_dir: Path) -> tuple[dict, dict[str, SheetKeys]]:
    """
    Load all templates from template directory.
    
    Loads templates for each prefix defined in prefix_to_template.
    Chronotopoi now uses a single consolidated template (v4).
    
    Args:
        template_dir: Path to directory containing template files
    
    Returns:
        Tuple of (templates dict, template_keys dict for metadati)
        templates structure:
        - For each prefix: {'prefix': {'sheet': [headers]}}
    """
    templates = {}
    template_keys: dict[str, SheetKeys] = {}
    
    for prefix, template_file in prefix_to_template.items():
            template_path = template_dir / template_file
            if template_path.exists():
                wb = load_workbook(template_path)
                if wb:
                    templates[prefix] = get_column_headers(wb)
                    # For metadati, also extract keys from the first sheet
                    if prefix == 'metadati' and wb.sheetnames:
                        template_keys[prefix] = get_metadati_keys(wb, wb.sheetnames[0])
            else:
                print(f"WARNING: Template not found: {template_path}", file=sys.stderr)
    
    return templates, template_keys


def get_files_to_verify(data_dir: Path, file_to_check=None) -> list[Path]:
    """
    Get list of Excel files to verify.
    
    Args:
        data_dir: Directory containing data files
        file_to_check: Optional file path or pattern to limit verification
    
    Returns:
        List of file paths to verify
    
    Raises:
        SystemExit: If file_to_check is provided but not found
    """
    if file_to_check:
        if isinstance(file_to_check, list):
            # Multiple arguments passed from shell (glob expansion)
            excel_files = [Path(f).resolve() for f in sorted(file_to_check)]
        else:
            # Single file or glob pattern - try glob first, then literal path
            glob_files = glob.glob(file_to_check)
            if glob_files:
                # Glob matched files
                excel_files = [Path(f).resolve() for f in sorted(glob_files)]
            else:
                # No glob matches - treat as literal file path
                file_path = Path(file_to_check).resolve()
                if not file_path.exists():
                    print(f"ERROR: File not found: {file_path}", file=sys.stderr)
                    sys.exit(1)
                excel_files = [file_path]
    else:
        # All files mode: get all xlsx files (exclude Zone.Identifier files)
        excel_files = [
            f for f in data_dir.glob('*.xlsx')
            if ':zone.identifier' not in f.name.lower()
        ]
        excel_files.sort()
    
    return excel_files


def verify_metadati_file(wb: openpyxl.Workbook, file_headers: SheetHeaders, 
                         template_headers: SheetHeaders, template_keys_dict: SheetKeys) -> list[VerificationError]:
    """
    Verify a metadati file structure.
    
    For metadati files, the first sheet contains key-value pairs (verified against template keys),
    and additional sheets contain column headers (verified as normal).
    
    Args:
        wb: Workbook to verify
        file_headers: Column headers extracted from file sheets
        template_headers: Column headers from template
        template_keys_dict: Keys from template's first sheet
    
    Returns:
        List of VerificationError objects describing discrepancies
    """
    errors: list[VerificationError] = []
    
    if not wb.sheetnames:
        return errors
    
    first_sheet = wb.sheetnames[0]
    
    # Check first sheet (key-value format)
    file_keys = get_metadati_keys(wb, first_sheet)[first_sheet]
    
    # Normalize keys for comparison
    file_keys_normalized = normalize_metadati_keys(file_keys)
    template_keys_normalized = normalize_metadati_keys(template_keys_dict.get(first_sheet, []))
    
    missing_keys = template_keys_normalized - file_keys_normalized
    extra_keys = file_keys_normalized - template_keys_normalized
    
    if missing_keys:
        errors.append(VerificationError(
            error_type='missing_keys',
            sheet=first_sheet,
            keys=sorted(missing_keys),
            message=f"Missing {len(missing_keys)} key(s): {', '.join(sorted(missing_keys))}"
        ))
    
    if extra_keys:
        errors.append(VerificationError(
            error_type='extra_keys',
            sheet=first_sheet,
            keys=sorted(extra_keys),
            message=f"Extra {len(extra_keys)} key(s): {', '.join(sorted(extra_keys))}"
        ))
    
    # Check other sheets as column headers
    for sheet_name in wb.sheetnames[1:]:
        if sheet_name.startswith('_'):
            continue
        
        if sheet_name not in template_headers or sheet_name not in file_headers:
            continue
        
        template_cols = to_lowercase_set(template_headers[sheet_name])
        file_cols = to_lowercase_set(file_headers[sheet_name])
        
        missing = template_cols - file_cols
        extra = file_cols - template_cols
        
        if missing or extra:
            msg_parts = []
            if missing:
                msg_parts.append(f"Missing {len(missing)} column(s): {', '.join(sorted(missing))}")
            if extra:
                msg_parts.append(f"Added {len(extra)} column(s): {', '.join(sorted(extra))}")
            
            errors.append(VerificationError(
                error_type='column_mismatch',
                sheet=sheet_name,
                missing=sorted(missing) if missing else [],
                extra=sorted(extra) if extra else [],
                message=' | '.join(msg_parts)
            ))
    
    return errors


def calculate_template_match_score(file_headers: SheetHeaders, template_headers: SheetHeaders) -> VersionScore:
    """
    Calculate how well a file matches a template version.
    
    Score is based on column matches across sheets:
    - Perfect match: 100%
    - Missing columns reduce score proportionally
    
    Args:
        file_headers: Column headers extracted from file sheets
        template_headers: Column headers from template version
    
    Returns:
        VersionScore with match_score (0-100) and error_list
    """
    errors: list[VerificationError] = []
    total_columns = 0
    matched_columns = 0
    
    # Check each sheet in template against corresponding file sheet
    for sheet_name, template_cols_list in template_headers.items():
        if sheet_name.startswith('_'):
            continue
        
        template_cols = to_lowercase_set(template_cols_list)
        total_columns += len(template_cols)
        
        if sheet_name not in file_headers:
            # Sheet in template but not in file
            errors.append(VerificationError(
                error_type='missing_sheet',
                sheet=sheet_name,
                message=f"Sheet '{sheet_name}' from template not found in file"
            ))
            continue
        
        file_cols = to_lowercase_set(file_headers[sheet_name])
        missing = template_cols - file_cols
        extra = file_cols - template_cols
        
        # Count matched columns for this sheet
        matched_columns += len(template_cols - missing)
        
        if missing or extra:
            msg_parts = []
            if missing:
                msg_parts.append(f"Missing {len(missing)} column(s): {', '.join(sorted(missing))}")
            if extra:
                msg_parts.append(f"Added {len(extra)} column(s): {', '.join(sorted(extra))}")
            
            errors.append(VerificationError(
                error_type='column_mismatch',
                sheet=sheet_name,
                missing=sorted(missing) if missing else [],
                extra=sorted(extra) if extra else [],
                message=' | '.join(msg_parts)
            ))
    
    # Check for extra sheets in file (not in template)
    for sheet_name in file_headers:
        if sheet_name.startswith('_'):
            continue
        if sheet_name not in template_headers:
            errors.append(VerificationError(
                error_type='extra_sheet',
                sheet=sheet_name,
                message=f"Sheet '{sheet_name}' in file not found in template"
            ))
    
    # Calculate overall score based on matched columns
    overall_score = 100 if total_columns == 0 else int((matched_columns / total_columns) * 100)
    
    return VersionScore(score=overall_score, errors=errors)


def verify_chronotopoi_file(file_headers: SheetHeaders, template_headers: SheetHeaders) -> list[VerificationError]:
    """
    Verify a chronotopoi file structure against the template (v4).
    
    Chronotopoi files may have different sheet names but all sheets must conform
    to the same column structure. Uses the first non-hidden template sheet as reference.
    
    Args:
        file_headers: Column headers extracted from file sheets
        template_headers: Column headers from template
    
    Returns:
        List of VerificationError objects describing discrepancies
    """
    errors: list[VerificationError] = []
    
    # Get reference columns from first non-hidden template sheet
    reference_cols = None
    reference_sheet = None
    for sheet_name, columns in template_headers.items():
        if not sheet_name.startswith('_'):
            reference_cols = to_lowercase_set(columns)
            reference_sheet = sheet_name
            break
    
    if reference_cols is None:
        # No valid template sheet found
        return errors
    
    # Check each non-hidden sheet in file against reference columns
    for sheet_name, headers in file_headers.items():
        if sheet_name.startswith('_'):
            continue
        
        file_cols = to_lowercase_set(headers)
        missing = reference_cols - file_cols
        extra = file_cols - reference_cols
        
        if missing or extra:
            msg_parts = []
            if missing:
                msg_parts.append(f"Missing {len(missing)} column(s): {', '.join(sorted(missing))}")
            if extra:
                msg_parts.append(f"Added {len(extra)} column(s): {', '.join(sorted(extra))}")
            
            errors.append(VerificationError(
                error_type='column_mismatch',
                sheet=sheet_name,
                missing=sorted(missing) if missing else [],
                extra=sorted(extra) if extra else [],
                message=' | '.join(msg_parts)
            ))
    
    return errors


def verify_other_prefix_file(file_headers: SheetHeaders, template_headers: SheetHeaders) -> list[VerificationError]:
    """
    Verify a file with prefix like 'belege' (non-metadati, non-chronotopoi).
    
    Checks each sheet against its corresponding template sheet by name.
    
    Args:
        file_headers: Column headers extracted from file sheets
        template_headers: Column headers from template
    
    Returns:
        List of VerificationError objects describing discrepancies
    """
    errors: list[VerificationError] = []
    
    # Check each sheet in the file
    for sheet_name, headers in file_headers.items():
        if sheet_name.startswith('_'):
            continue
        
        if sheet_name not in template_headers:
            continue
        
        template_cols = to_lowercase_set(template_headers[sheet_name])
        file_cols = to_lowercase_set(headers)
        
        missing = template_cols - file_cols
        extra = file_cols - template_cols
        
        if missing or extra:
            msg_parts = []
            if missing:
                msg_parts.append(f"Missing {len(missing)} column(s): {', '.join(sorted(missing))}")
            if extra:
                msg_parts.append(f"Added {len(extra)} column(s): {', '.join(sorted(extra))}")
            
            errors.append(VerificationError(
                error_type='column_mismatch',
                sheet=sheet_name,
                missing=sorted(missing) if missing else [],
                extra=sorted(extra) if extra else [],
                message=' | '.join(msg_parts)
            ))
    
    # Check for sheets in template but not in file
    for sheet_name in template_headers:
        if sheet_name.startswith('_'):
            continue
        if sheet_name not in file_headers:
            errors.append(VerificationError(
                error_type='missing_sheet_in_file',
                sheet=sheet_name,
                message=f"Sheet '{sheet_name}' from template not found in file"
            ))
    
    return errors


def verify_files(data_dir: Path, template_dir: Path, file_to_check=None) -> VerificationResult:
    """
    Verify Excel files in data_dir against templates in template_dir.
    
    Orchestrates the verification process by loading templates, getting files to check,
    and calling appropriate verification methods for each file type (metadati, chronotopoi, belege).
    
    Args:
        data_dir: Directory containing data files to verify
        template_dir: Directory containing template files
        file_to_check: If provided, only check this specific file/pattern, or a list of files
    
    Returns:
        VerificationResult containing all verification statistics and per-file results
    """
    
    # Check directories exist
    if not data_dir.exists():
        return VerificationResult(
            discrepancies_found=False,
            files_checked=0,
            files_with_discrepancies=0,
            total_sheets_checked=0,
            sheets_with_discrepancies=0,
            error=f"Data directory not found: {data_dir}"
        )
    if not template_dir.exists():
        return VerificationResult(
            discrepancies_found=False,
            files_checked=0,
            files_with_discrepancies=0,
            total_sheets_checked=0,
            sheets_with_discrepancies=0,
            error=f"Template directory not found: {template_dir}"
        )
    
    # Load templates and get files to verify
    templates, template_keys = load_templates(template_dir)
    excel_files = get_files_to_verify(data_dir, file_to_check)
    
    # Initialize counters and results
    discrepancies_found = False
    files_checked = 0
    files_with_discrepancies = 0
    total_sheets_checked = 0
    sheets_with_discrepancies = 0
    file_results = []
    
    # Process each file
    for file_path in excel_files:
        prefix = get_prefix(file_path.name)
        
        if prefix is None:
            continue  # Skip files without recognized prefix
        
        if prefix not in templates:
            continue  # Skip files without templates
        
        files_checked += 1
        wb = load_workbook(file_path)
        if not wb:
            continue
        
        # Extract file headers and select appropriate verification method
        file_headers = get_column_headers(wb)
        template_headers = templates[prefix]
        
        # Verify based on file type
        if prefix == 'metadati' and wb.sheetnames and prefix in template_keys:
            sheet_errors = verify_metadati_file(wb, file_headers, template_headers, template_keys[prefix])
        elif prefix == 'chronotopoi':
            sheet_errors = verify_chronotopoi_file(file_headers, template_headers)
        else:
            sheet_errors = verify_other_prefix_file(file_headers, template_headers)
        
        # Track discrepancies
        has_discrepancies = len(sheet_errors) > 0
        if has_discrepancies:
            discrepancies_found = True
            files_with_discrepancies += 1
            sheets_with_discrepancies += len(sheet_errors)
        
        # Count total sheets in this file (excluding hidden ones)
        sheets_in_file = sum(1 for sheet in wb.sheetnames if not sheet.startswith('_'))
        total_sheets_checked += sheets_in_file
        
        # Build template info
        template_info = prefix_to_template[prefix]
        
        # Collect file result
        file_result = FileResult(
            name=file_path.name,
            prefix=prefix,
            template=template_info,
            has_discrepancies=has_discrepancies,
            sheets_checked=sheets_in_file,
            errors=sheet_errors
        )
        
        file_results.append(file_result)
    
    return VerificationResult(
        discrepancies_found=discrepancies_found,
        files_checked=files_checked,
        files_with_discrepancies=files_with_discrepancies,
        total_sheets_checked=total_sheets_checked,
        sheets_with_discrepancies=sheets_with_discrepancies,
        files=file_results
    )


def main():
    """Main entry point. Handles CLI interaction and report formatting."""
    # Parse command-line arguments
    file_to_check = None
    if len(sys.argv) > 1:
        # Combine all arguments after script name as a single pattern or list
        if len(sys.argv) == 2:
            file_to_check = sys.argv[1]
        else:
            # Multiple arguments - treat as expanded glob results
            file_to_check = sys.argv[1:]
    
    # Use workspace relative paths
    workspace_root = Path(__file__).parent
    data_dir = workspace_root.parent / 'data' / 'nuove schede'
    template_dir = workspace_root.parent / 'data' / 'template'
    
    # Allow override via environment variables
    if 'DATA_DIR' in os.environ:
        data_dir = Path(os.environ['DATA_DIR'])
    if 'TEMPLATE_DIR' in os.environ:
        template_dir = Path(os.environ['TEMPLATE_DIR'])
    
    try:
        # Run verification
        results = verify_files(data_dir, template_dir, file_to_check)
        
        # Handle errors
        if results.error:
            print(f"ERROR: {results.error}", file=sys.stderr)
            sys.exit(1)
        
        # Print report header
        print("=" * 80)
        print("EXCEL COLUMN HEADER VERIFICATION REPORT")
        print("=" * 80)
        print()
        
        # Print results for each file
        for file_info in results.files:
            if file_info.has_discrepancies:
                print(f"❌ DISCREPANCIES: {file_info.name}")
            else:
                print(f"✓ OK: {file_info.name}")
            
            print(f"   Template: {file_info.template}")
            
            # Show chronotopoi version matching details
            if file_info.best_matching_version:
                # print(f"   Best match: chronotopoi_template_{file_info.best_matching_version}.xlsx")
                if file_info.version_scores and file_info.best_matching_version in file_info.version_scores.versions:
                    score = file_info.version_scores.versions[file_info.best_matching_version].score
                    print(f"   Score: {score}%")
            
            if file_info.errors:
                for error in file_info.errors:
                    print(f"   [{error.sheet}] {error.message}")
            
            print()
        
        # Print summary
        print("=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"Files checked: {results.files_checked}")
        if results.files_checked > 0:
            print(f"Files with discrepancies: {results.files_with_discrepancies} out of {results.files_checked}")
            print(f"Total sheets checked: {results.total_sheets_checked}")
            print(f"Sheets with discrepancies: {results.sheets_with_discrepancies} out of {results.total_sheets_checked}")
        print(f"Discrepancies found: {'YES' if results.discrepancies_found else 'NO'}")
        print()
        
        # Exit with appropriate code
        exit_code = 1 if results.discrepancies_found else 0
        sys.exit(exit_code)
    
    except KeyboardInterrupt:
        print("\nInterrupted by user", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
