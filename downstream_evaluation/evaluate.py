"""
evaluate.py

Evaluate inference results against gold standard for Article 11 ECtHR cases.

Computes per-case metrics (up to 43 numbers):
  - 1  : violated correct (bool)
  - 6  : element conclusion correct (bool per element, null gold → excluded → None)
  - 36 : fact mapping P/R/F1 for list1 and list2, per element

Results saved to eval_results/ with same hierarchy as outputs/.

Usage:
    python evaluate.py --model claude-sonnet-4-6 --model_variant thinking_type_disabled --eval_prompt vanilla
"""

import argparse
import json
import sys
from pathlib import Path

from sklearn.metrics import precision_recall_fscore_support

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent))
from utils import get_provider_for_model

GOLD_DIR          = "../gold_standard/compiled_gold_standard"
ATOMIC_FACT_DIR   = "../gold_standard/outputs/atomic_facts"
OUTPUT_DIR        = "./outputs"
EVAL_DIR          = "./eval_results"
BATCH_FILE        = "./batches/included_case_names.txt"

MAIN_ELEMENTS = [
    "scope",
    "interference",
    "prescribed_by_law",
    "legitimate_aim",
    "necessity",
    "positive_obligation",
]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def prf(pred: set, gold: set, all_facts: set) -> dict | None:
    """Macro binary F1 using sklearn (universe = all atomic facts).
    Returns None if gold is empty (excluded from evaluation)."""
    if not gold:
        return None
    y_true = [1 if f in gold else 0 for f in all_facts]
    y_pred = [1 if f in pred else 0 for f in all_facts]

    p, r, f_macro, _ = precision_recall_fscore_support(
        y_true, y_pred, average="macro", zero_division=0
    )
    _, _, f_pos, _ = precision_recall_fscore_support(
        y_true, y_pred, average="binary", zero_division=0
    )
    return {
        "precision": round(float(p),       4),
        "recall":    round(float(r),       4),
        "f1":        round(float(f_pos),   4),
        "macro_f1":  round(float(f_macro), 4),
    }


# ---------------------------------------------------------------------------
# Per-case evaluation
# ---------------------------------------------------------------------------

def evaluate_case(inference: dict, gold: dict, all_facts: set,
                  eval_prompt: str = "") -> dict:
    is_direct        = eval_prompt.startswith("direct_")
    is_direct_violation = eval_prompt == "direct_violation"

    result = {}

    # ── 1) Case-level violated ────────────────────────────────────────────────
    result["violated_gold"] = bool(gold.get("conclusion", {}).get("violated"))
    result["violated_pred"] = bool(inference.get("violated"))

    # ── 2) Element conclusions ────────────────────────────────────────────────
    gold_elements = gold.get("conclusion", {}).get("elements", {})
    # For direct_violation: model outputs no elements → all excluded
    inf_elements  = inference.get("elements", {}) if not is_direct_violation else {}

    element_conclusions = {}
    for el in MAIN_ELEMENTS:
        gold_conc = gold_elements.get(el, {}).get("conclusion")
        if gold_conc is None or is_direct_violation:
            element_conclusions[el] = None  # excluded
        else:
            inf_conc = inf_elements.get(el, {}).get("conclusion")
            element_conclusions[el] = {"gold": gold_conc, "pred": inf_conc}

    result["element_conclusions"] = element_conclusions

    # ── 3) Fact mapping (skipped for direct_ prompts) ─────────────────────────
    if is_direct:
        result["fact_mapping"] = None
        return result

    non_null_els = {
        el for el in MAIN_ELEMENTS
        if gold_elements.get(el, {}).get("conclusion") is not None
    }

    gold_mapping = gold.get("fact_mapping", {})

    fact_mapping_result = {}
    for lst in ("list1", "list2"):
        gold_lst   = gold_mapping.get(lst, {})
        lst_result = {}
        for el in MAIN_ELEMENTS:
            if el not in non_null_els:
                lst_result[el] = None  # excluded
                continue
            gold_facts = set(gold_lst.get(el, []))
            inf_facts  = {
                f["fact_id"]
                for f in inf_elements.get(el, {}).get("facts", [])
                if "fact_id" in f
            }
            lst_result[el] = prf(inf_facts, gold_facts, all_facts)
        fact_mapping_result[lst] = lst_result

    # list3: only include facts from non-null elements
    gold_list3 = set(gold_mapping.get("list3", []))
    inf_all    = {
        f["fact_id"]
        for el in non_null_els
        for f in inf_elements.get(el, {}).get("facts", [])
        if "fact_id" in f
    }
    fact_mapping_result["list3"] = prf(inf_all, gold_list3, all_facts)

    result["fact_mapping"] = fact_mapping_result
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate inference results against gold standard."
    )
    parser.add_argument("--model",         required=True)
    parser.add_argument("--model_variant", required=True)
    parser.add_argument("--eval_prompt",   default="vanilla_questions")
    parser.add_argument("--output_dir",    default=OUTPUT_DIR)
    parser.add_argument("--eval_dir",      default=EVAL_DIR)
    parser.add_argument("--gold_dir",      default=GOLD_DIR)
    parser.add_argument("--atomic_fact_dir", default=ATOMIC_FACT_DIR)
    parser.add_argument("--batch_file",      default=BATCH_FILE)
    args = parser.parse_args()

    provider_name, _ = get_provider_for_model(args.model)
    inf_dir = (
        Path(args.output_dir) / provider_name / args.model
        / args.model_variant / args.eval_prompt
    )
    out_dir = (
        Path(args.eval_dir) / provider_name / args.model
        / args.model_variant / args.eval_prompt
    )

    if not inf_dir.exists():
        print(f"[ERROR] Inference directory not found: {inf_dir}", file=sys.stderr)
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)

    lines = Path(args.batch_file).read_text(encoding="utf-8").splitlines()
    case_stems = [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]

    n_done = n_skip = n_error = 0

    for stem in tqdm(case_stems, desc="Evaluating"):
        inf_path  = inf_dir  / f"{stem}.json"
        gold_path = Path(args.gold_dir) / f"{stem}.json"
        out_path  = out_dir  / f"{stem}.json"

        if not inf_path.exists():
            n_skip += 1
            continue
        if not gold_path.exists():
            print(f"[WARN] Gold standard not found: {gold_path}", file=sys.stderr)
            n_skip += 1
            continue

        try:
            inference = json.loads(inf_path.read_text(encoding="utf-8"))
            gold      = json.loads(gold_path.read_text(encoding="utf-8"))
            af_path   = Path(args.atomic_fact_dir) / f"{stem}.json"
            all_facts = {f["fact_id"] for f in json.loads(af_path.read_text(encoding="utf-8"))} if af_path.exists() else set()
            metrics   = evaluate_case(inference, gold, all_facts, args.eval_prompt)
            metrics["case"] = stem
            out_path.write_text(
                json.dumps(metrics, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            n_done += 1
        except Exception as e:
            print(f"[ERROR] {stem}: {e}", file=sys.stderr)
            n_error += 1

    print(f"Done. evaluated={n_done}, skipped={n_skip}, errors={n_error}")
    print(f"Results → {out_dir}")


if __name__ == "__main__":
    main()
