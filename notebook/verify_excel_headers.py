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
from typing import Dict, List
import glob
import openpyxl

# Map prefixes to template files
prefix_to_template = {
    'belege': 'belege_template.xlsx',
    'chronotopoi': 'chronotopoi_template_v1.xlsx',
    # 'chronotopoi': 'chronotopoi_template_v4.xlsx',
    # 'chronotopoi': 'chronotopoi_template_v5.xlsx',
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


def get_column_headers(wb: openpyxl.Workbook, header_row:int = 3) -> Dict[str, List[str]]:
    """Extract column headers from all sheets in workbook (row 3)."""
    headers = {}
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


def get_metadati_keys(wb: openpyxl.Workbook, sheet_name: str = None) -> Dict[str, List[str]]:
    """
    Extract key-value pairs from first column starting at row 3.
    Used for metadati sheets which have key-value format instead of column headers.
    
    Args:
        wb: Workbook to extract keys from
        sheet_name: Specific sheet to extract from (default: first sheet)
    
    Returns:
        Dictionary mapping sheet names to list of keys
    """
    keys = {}
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


def normalize_metadati_keys(keys: List[str]) -> set:
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


def to_lowercase_set(items: List[str]) -> set:
    """Convert a list of strings to a lowercase set for case-insensitive comparison."""
    return set(item.lower() for item in items)


def load_workbook(path: Path) -> openpyxl.Workbook:
    """Load workbook from path."""
    try:
        return openpyxl.load_workbook(str(path), data_only=True)
    except Exception as e:
        print(f"ERROR: Failed to load {path}: {e}", file=sys.stderr)
        return None


def load_templates(template_dir: Path) -> tuple[Dict[str, Dict[str, List[str]]], Dict[str, Dict[str, List[str]]]]:
    """
    Load all templates from template directory.
    
    Args:
        template_dir: Path to directory containing template files
    
    Returns:
        Tuple of (templates dict, template_keys dict for metadati)
    """
    templates: Dict[str, Dict[str, List[str]]] = {}
    template_keys: Dict[str, Dict[str, List[str]]] = {}
    
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


def verify_metadati_file(wb: openpyxl.Workbook, file_headers: Dict[str, List[str]], 
                         template_headers: Dict[str, List[str]], template_keys_dict: Dict[str, List[str]]) -> list:
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
        List of error dictionaries describing discrepancies
    """
    errors = []
    
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
        errors.append({
            'type': 'missing_keys',
            'sheet': first_sheet,
            'keys': sorted(missing_keys),
            'message': f"Missing {len(missing_keys)} key(s): {', '.join(sorted(missing_keys))}"
        })
    
    if extra_keys:
        errors.append({
            'type': 'extra_keys',
            'sheet': first_sheet,
            'keys': sorted(extra_keys),
            'message': f"Extra {len(extra_keys)} key(s): {', '.join(sorted(extra_keys))}"
        })
    
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
                msg_parts.append(f"Extra {len(extra)} column(s): {', '.join(sorted(extra))}")
            
            errors.append({
                'type': 'column_mismatch',
                'sheet': sheet_name,
                'missing': sorted(missing) if missing else [],
                'extra': sorted(extra) if extra else [],
                'message': ' | '.join(msg_parts)
            })
    
    return errors


def verify_chronotopoi_file(file_headers: Dict[str, List[str]], template_headers: Dict[str, List[str]]) -> list:
    """
    Verify a chronotopoi file structure.
    
    For chronotopoi files, all non-hidden sheets are verified against the "Hauptperson" template.
    
    Args:
        file_headers: Column headers extracted from file sheets
        template_headers: Column headers from template (must include 'Hauptperson')
    
    Returns:
        List of error dictionaries describing discrepancies
    """
    errors = []
    
    if 'Hauptperson' not in template_headers:
        errors.append({
            'type': 'missing_reference_sheet',
            'sheet': 'Hauptperson',
            'message': "Reference sheet 'Hauptperson' not found in template"
        })
        return errors
    
    template_cols = to_lowercase_set(template_headers['Hauptperson'])
    
    # Check all non-hidden sheets (those not starting with "_")
    for sheet_name, headers in file_headers.items():
        if sheet_name.startswith('_'):
            continue  # Skip hidden sheets
        
        file_cols = to_lowercase_set(headers)
        missing = template_cols - file_cols
        extra = file_cols - template_cols
        
        if missing or extra:
            msg_parts = []
            if missing:
                msg_parts.append(f"Missing {len(missing)} column(s): {', '.join(sorted(missing))}")
            if extra:
                msg_parts.append(f"Extra {len(extra)} column(s): {', '.join(sorted(extra))}")
            
            errors.append({
                'type': 'column_mismatch',
                'sheet': sheet_name,
                'missing': sorted(missing) if missing else [],
                'extra': sorted(extra) if extra else [],
                'message': ' | '.join(msg_parts)
            })
    
    return errors


def verify_other_prefix_file(file_headers: Dict[str, List[str]], template_headers: Dict[str, List[str]]) -> list:
    """
    Verify a file with prefix like 'belege' (non-metadati, non-chronotopoi).
    
    Checks each sheet against its corresponding template with prefix matching support.
    
    Args:
        file_headers: Column headers extracted from file sheets
        template_headers: Column headers from template
    
    Returns:
        List of error dictionaries describing discrepancies
    """
    errors = []
    
    # Check each sheet in the file
    for sheet_name, headers in file_headers.items():
        if sheet_name.startswith('_'):
            continue
        
        if sheet_name not in template_headers:
            continue
        
        template_cols_original = template_headers[sheet_name]
        template_cols = to_lowercase_set(template_cols_original)
        file_cols = to_lowercase_set(headers)
        
        # Check for missing and extra columns using prefix matching (case-insensitive)
        missing = []
        for tcol in template_cols:
            if tcol not in file_cols:
                if not any(fcol.startswith(tcol) for fcol in file_cols):
                    missing.append(tcol)
        
        extra = []
        for fcol in file_cols:
            if fcol not in template_cols:
                if not any(fcol.startswith(tcol) for tcol in template_cols):
                    extra.append(fcol)
        
        if missing:
            errors.append({
                'type': 'missing_columns',
                'sheet': sheet_name,
                'columns': sorted(missing),
                'message': f"Missing {len(missing)} column(s): {', '.join(sorted(missing))}"
            })
        
        if extra:
            errors.append({
                'type': 'extra_columns',
                'sheet': sheet_name,
                'columns': sorted(extra),
                'message': f"Extra {len(extra)} column(s): {', '.join(sorted(extra))}"
            })
    
    # Check for sheets in template but not in file
    for sheet_name in template_headers:
        if sheet_name.startswith('_'):
            continue
        if sheet_name not in file_headers:
            errors.append({
                'type': 'missing_sheet_in_file',
                'sheet': sheet_name,
                'message': f"Sheet '{sheet_name}' from template not found in file"
            })
    
    return errors


def verify_files(data_dir: Path, template_dir: Path, file_to_check=None) -> dict:
    """
    Verify Excel files in data_dir against templates in template_dir.
    
    Orchestrates the verification process by loading templates, getting files to check,
    and calling appropriate verification methods for each file type (metadati, chronotopoi, belege).
    
    Returns verification statistics suitable for programmatic use.
    
    Args:
        data_dir: Directory containing data files to verify
        template_dir: Directory containing template files
        file_to_check: If provided, only check this specific file/pattern, or a list of files
    
    Returns:
        Dictionary with structure:
        {
            'discrepancies_found': bool,
            'files_checked': int,
            'files_with_discrepancies': int,
            'total_sheets_checked': int,
            'sheets_with_discrepancies': int,
            'files': [
                {
                    'name': str,
                    'prefix': str,
                    'template': str,
                    'has_discrepancies': bool,
                    'sheets_checked': int,
                    'errors': [error dicts]
                }
            ]
        }
    """
    
    # Check directories exist
    if not data_dir.exists():
        return {
            'error': f"Data directory not found: {data_dir}",
            'discrepancies_found': False,
            'files_checked': 0,
            'files_with_discrepancies': 0,
            'total_sheets_checked': 0,
            'sheets_with_discrepancies': 0,
            'files': []
        }
    if not template_dir.exists():
        return {
            'error': f"Template directory not found: {template_dir}",
            'discrepancies_found': False,
            'files_checked': 0,
            'files_with_discrepancies': 0,
            'total_sheets_checked': 0,
            'sheets_with_discrepancies': 0,
            'files': []
        }
    
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
        
        # Collect file result
        file_results.append({
            'name': file_path.name,
            'prefix': prefix,
            'template': prefix_to_template[prefix],
            'has_discrepancies': has_discrepancies,
            'sheets_checked': sheets_in_file,
            'errors': sheet_errors
        })
    
    return {
        'discrepancies_found': discrepancies_found,
        'files_checked': files_checked,
        'files_with_discrepancies': files_with_discrepancies,
        'total_sheets_checked': total_sheets_checked,
        'sheets_with_discrepancies': sheets_with_discrepancies,
        'files': file_results
    }


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
        if 'error' in results:
            print(f"ERROR: {results['error']}", file=sys.stderr)
            sys.exit(1)
        
        # Print report header
        print("=" * 80)
        print("EXCEL COLUMN HEADER VERIFICATION REPORT")
        print("=" * 80)
        print()
        
        # Print results for each file
        for file_info in results['files']:
            if file_info['has_discrepancies']:
                print(f"❌ DISCREPANCIES: {file_info['name']}")
            else:
                print(f"✓ OK: {file_info['name']}")
            
            print(f"   Template: {file_info['template']}")
            
            if file_info['errors']:
                for error in file_info['errors']:
                    print(f"   [{error['sheet']}] {error['message']}")
            
            print()
        
        # Print summary
        print("=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"Files checked: {results['files_checked']}")
        if results['files_checked'] > 0:
            print(f"Files with discrepancies: {results['files_with_discrepancies']} out of {results['files_checked']}")
            print(f"Total sheets checked: {results['total_sheets_checked']}")
            print(f"Sheets with discrepancies: {results['sheets_with_discrepancies']} out of {results['total_sheets_checked']}")
        print(f"Discrepancies found: {'YES' if results['discrepancies_found'] else 'NO'}")
        print()
        
        # Exit with appropriate code
        exit_code = 1 if results['discrepancies_found'] else 0
        sys.exit(exit_code)
    
    except KeyboardInterrupt:
        print("\nInterrupted by user", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
