"""
postprocess_compile_gold_standard.py

Compiles conclusion results and fact mapping into a minimal gold standard
JSON file per case, suitable for downstream model evaluation.

Output schema per case:
{
  "case_name": "case_274",
  "conclusion": {
    "violated": true/false/null,
    "elements": {
      "<element_key>": {
        "conclusion": "yes/no/null",
        "discussed":  "explicit/implied/not_discussed"
      },
      "legitimate_aim": {
        "conclusion": "yes/no/null",
        "discussed":  "explicit/implied/not_discussed",
        "aims":       ["prevention_of_disorder", ...]
      },
      ...
    }
  },
  "fact_mapping": {
    "list1": {
      "<element_key>": ["FXXX", ...],
      ...
    },
    "list2": {
      "<element_key>": ["FXXX", ...],
      ...
    },
    "list3": ["FXXX", ...]
  }
}

Input paths (hard-coded relative to script location):
    ../outputs/conclusion_results/<case_name>.json
    ../outputs/fact_mapping_results/<case_name>.json

Output:
    ../outputs/explicit_gold_standard/<case_name>.json

Usage:
    python postprocess_compile_gold_standard.py case_274
    python postprocess_compile_gold_standard.py --batch cases.txt
"""

import argparse
import json
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

import os
_SCRIPT_DIR = Path(__file__).parent.resolve()
CONCLUSION_DIR  = "../outputs/conclusion_results"
MAPPING_DIR     = "../outputs/fact_mapping_results"
OUTPUT_DIR      = "../outputs/explicit_gold_standard"

VALID_ELEMENTS = [
    "scope",
    "scope_assembly_exists",
    "scope_participation",
    "scope_peaceful",
    "interference",
    "prescribed_by_law",
    "prescribed_by_law_foreseeable",
    "prescribed_by_law_accessible",
    "prescribed_by_law_safeguards",
    "legitimate_aim",
    "necessity",
    "positive_obligation",
]

MAPPING_ELEMENTS = [
    "scope",
    "interference",
    "prescribed_by_law",
    "legitimate_aim",
    "necessity",
    "positive_obligation",
]


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------

def compile_gold_standard(case_name: str) -> dict:
    conclusion_path = Path(CONCLUSION_DIR) / f"{case_name}.json"
    mapping_path    = Path(MAPPING_DIR)    / f"{case_name}.json"

    for p in [conclusion_path, mapping_path]:
        if not p.exists():
            raise FileNotFoundError(f"File not found: {p}")

    with open(conclusion_path, encoding="utf-8") as f:
        conclusion_raw = json.load(f)
    with open(mapping_path, encoding="utf-8") as f:
        mapping_raw = json.load(f)

    # ── Conclusion ────────────────────────────────────────────────────────────
    elements_raw = conclusion_raw.get("elements", {})
    elements_out = {}

    for el in VALID_ELEMENTS:
        el_data = elements_raw.get(el, {})
        entry = {
            "conclusion": el_data.get("conclusion"),
            "discussed":  el_data.get("discussed", "not_discussed"),
        }
        if el == "legitimate_aim":
            entry["aims"] = el_data.get("aims_found", [])
        elements_out[el] = entry

    conclusion_out = {
        "violated": conclusion_raw.get("violated"),
        "elements": elements_out,
    }

    # ── Fact mapping ──────────────────────────────────────────────────────────
    list1_raw = mapping_raw.get("list1", {})
    list2_raw = mapping_raw.get("list2", {})
    list3_raw = mapping_raw.get("list3", [])

    list1_out = {el: list1_raw.get(el, []) for el in MAPPING_ELEMENTS}
    list2_out = {el: list2_raw.get(el, []) for el in MAPPING_ELEMENTS}

    # Enforce List 2 ⊆ List 1 per element
    list2_out = {
        el: [f for f in list2_raw.get(el, []) if f in set(list1_out[el])]
        for el in MAPPING_ELEMENTS
    }

    # Enforce List 3 ⊆ union of List 2 across all elements
    list2_union = set(f for el in MAPPING_ELEMENTS for f in list2_out[el])
    list3_out   = [f for f in list3_raw if f in list2_union]

    fact_mapping_out = {
        "list1": list1_out,
        "list2": list2_out,
        "list3": list3_out,
    }

    return {
        "case_name":    case_name,
        "conclusion":   conclusion_out,
        "fact_mapping": fact_mapping_out,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process_case(case_name: str) -> None:
    output_path = Path(OUTPUT_DIR) / f"{case_name}.json"
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

    gold = compile_gold_standard(case_name)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(gold, f, ensure_ascii=False, indent=2)

    n_active = sum(
        1 for el in VALID_ELEMENTS
        if gold["conclusion"]["elements"].get(el, {}).get("discussed", "not_discussed") != "not_discussed"
    )
    l1_total = sum(len(v) for v in gold["fact_mapping"]["list1"].values())
    l2_total = sum(len(v) for v in gold["fact_mapping"]["list2"].values())
    l3_total = len(gold["fact_mapping"]["list3"])

    print(f"✓ {case_name}")
    print(f"    violated       : {gold['conclusion']['violated']}")
    print(f"    active elements: {n_active}/{len(VALID_ELEMENTS)}")
    print(f"    list1 facts    : {l1_total}")
    print(f"    list2 facts    : {l2_total}")
    print(f"    list3 facts    : {l3_total}")
    print(f"    → {output_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Compile pipeline outputs into minimal gold standard JSON files"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("case_name", nargs="?", default=None,
                       help="Case name to process (e.g. case_274)")
    group.add_argument("--batch",   dest="batch_file", default=None,
                       metavar="BATCH_FILE",
                       help="Path to a .txt file listing case names, one per line")
    args = parser.parse_args()

    if args.batch_file:
        batch_path = Path(args.batch_file)
        if not batch_path.exists():
            print(f"[ERROR] Batch file not found: {batch_path}", file=sys.stderr)
            sys.exit(1)
        case_names = [
            l.strip() for l in batch_path.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.strip().startswith("#")
        ]
        print(f"Batch mode: {len(case_names)} case(s)\n")
        failed = []
        for case_name in case_names:
            try:
                process_case(case_name)
            except Exception as e:
                print(f"[ERROR] {case_name}: {e}", file=sys.stderr)
                failed.append(case_name)
        print(f"\nBatch complete: {len(case_names) - len(failed)}/{len(case_names)} succeeded")
        if failed:
            print(f"Failed: {', '.join(failed)}", file=sys.stderr)
            sys.exit(1)
    else:
        try:
            process_case(args.case_name)
        except Exception as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()