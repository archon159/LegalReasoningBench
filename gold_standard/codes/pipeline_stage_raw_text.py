"""
pipeline_stage_pdf_to_text.py

ECtHR judgment PDF-to-text conversion (pre-exclusion stage).

Extracts raw text from each page of a PDF judgment, preserving page
boundaries with separators. Output is intentionally unclean — headers,
footers, and footnotes are retained for the downstream exclusion and
preprocessing stages to handle.

Usage:
    python pipeline_stage_pdf_to_text.py case_118
    python pipeline_stage_pdf_to_text.py --batch cases.txt
"""

import argparse
import sys
from pathlib import Path

import fitz


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------

def run_pipeline(input_pdf: str, output_txt: str) -> None:
    input_path  = Path(input_pdf)
    output_path = Path(output_txt)

    if not input_path.exists():
        print(f"[ERROR] Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Open PDF ──────────────────────────────────────────────────────
    print(f"[1/2] Reading: {input_path.name}")
    doc = fitz.open(input_path)
    print(f"      {doc.page_count} page(s)")

    # ── Step 2: Extract text ──────────────────────────────────────────────────
    print(f"[2/2] Extracting text...")
    page_texts = ""
    for page in doc:
        page_texts += "\n" + "=" * 40 + "\n\n"
        for block in page.get_text("blocks"):
            page_texts += block[4] + "\n"
    doc.close()

    # ── Save ──────────────────────────────────────────────────────────────────
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(page_texts)
    print(f"\n✓ Output written to: {output_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def case_paths(case_name: str) -> tuple[str, str]:
    return (
        f"../pdfs/{case_name}.pdf",
        f"../outputs/pdf2txt/{case_name}.txt"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ECtHR judgment PDF-to-text conversion: "
                    "extract raw text from PDF judgment"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "case_name", nargs="?", default=None,
        help="Case name to process (e.g. case_118)"
    )
    group.add_argument(
        "--batch", dest="batch_file", default=None,
        metavar="BATCH_FILE",
        help="Path to a .txt file listing case names to process, one per line"
    )
    args = parser.parse_args()

    if args.batch_file:
        batch_path = Path(args.batch_file)
        if not batch_path.exists():
            print(f"[ERROR] Batch file not found: {batch_path}", file=sys.stderr)
            sys.exit(1)
        case_names = [
            line.strip()
            for line in batch_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        print(f"Batch mode: {len(case_names)} case(s) to process\n")
        failed = []
        for i, case_name in enumerate(case_names, 1):
            print(f"{'='*60}")
            print(f"[{i}/{len(case_names)}] {case_name}")
            print(f"{'='*60}")
            input_pdf, output_txt = case_paths(case_name)
            try:
                run_pipeline(input_pdf, output_txt)
            except Exception as e:
                print(f"[ERROR] {case_name} failed: {e}", file=sys.stderr)
                failed.append(case_name)
            print()
        print(f"\nBatch complete: {len(case_names) - len(failed)}/{len(case_names)} succeeded")
        if failed:
            print(f"Failed cases: {', '.join(failed)}", file=sys.stderr)
            sys.exit(1)
    else:
        input_pdf, output_txt = case_paths(args.case_name)
        run_pipeline(input_pdf, output_txt)