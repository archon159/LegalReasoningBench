"""
postprocess_apply_dependency_chain.py

Apply the doctrinal dependency-chain rule to fill implicit null conclusions,
turning the explicit-only compilation into the canonical gold standard.

Reads ../outputs/explicit_gold_standard/ (only explicitly stated conclusions)
and writes ../compiled_gold_standard/ (at the gold_standard/ root) — the
downstream-evaluation-ready gold standard.

Dependency chain:
    scope -> interference -> prescribed_by_law -> legitimate_aim -> necessity

Rule (applied to all cases):
    If element E has a non-null conclusion, all preceding null elements in the
    chain are implicitly "yes" — iterate the chain in reverse to find the
    deepest non-null element in one pass, then fill its null predecessors.

Filled elements are marked with discussed="implicit" to distinguish them from
the original "explicit", "implied", and "not_discussed" values.

Usage:
    python postprocess_apply_dependency_chain.py
"""

import json
from pathlib import Path

INPUT_DIR  = Path(__file__).parent.parent / "outputs" / "explicit_gold_standard"
OUTPUT_DIR = Path(__file__).parent.parent / "compiled_gold_standard"

CHAIN = [
    "scope",
    "interference",
    "prescribed_by_law",
    "legitimate_aim",
    "necessity",
]


def get_conclusion(elements: dict, el: str):
    return elements.get(el, {}).get("conclusion")


def fill_implicit(data: dict) -> tuple[dict, int]:
    """
    Fill null chain predecessors based on the dependency rule.
    Returns (modified_data, n_filled).
    Modifies a deep copy of data in-place and returns it.
    """
    import copy
    data = copy.deepcopy(data)
    elements = data["conclusion"]["elements"]
    n_filled = 0

    # Iterate the chain in reverse — the first non-null element found is the
    # deepest, so we fill all null predecessors before it and stop.
    for i, el in enumerate(reversed(CHAIN)):
        chain_idx = len(CHAIN) - 1 - i  # index in CHAIN
        if get_conclusion(elements, el) is None:
            continue  # null → keep looking

        # Found the deepest non-null element; fill all null predecessors.
        for pred in CHAIN[:chain_idx]:
            if get_conclusion(elements, pred) is None:
                elements[pred]["conclusion"] = "yes"
                elements[pred]["discussed"]  = "implicit"
                n_filled += 1
        break  # done after the first non-null found from the right

    return data, n_filled


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    case_files = sorted(INPUT_DIR.glob("case_*.json"))
    print(f"Processing {len(case_files)} cases...")

    n_filled_total   = 0
    n_cases_modified = 0  # fills applied
    n_cases_no_fill  = 0  # nothing to fill

    for path in case_files:
        data = json.loads(path.read_text(encoding="utf-8"))
        modified, n_filled = fill_implicit(data)
        (OUTPUT_DIR / path.name).write_text(
            json.dumps(modified, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        if n_filled > 0:
            n_cases_modified += 1
            n_filled_total   += n_filled
        else:
            n_cases_no_fill += 1

    print(f"Done.")
    print(f"  cases with fills applied  : {n_cases_modified}")
    print(f"  cases with nothing to fill: {n_cases_no_fill}")
    print(f"  total elements filled     : {n_filled_total}")
    print(f"  output → {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
