"""
compute_benchmark_statistics.py

Computes and reports statistics for the Article 11 ECtHR benchmark.

Statistics reported:
    Case-level:
        - Total cases
        - Violated vs. not violated distribution
        - Distribution of number of active elements per case

    Element-level (6 main elements only):
        - Per element: active vs. not discussed counts
        - Per element: yes vs. no conclusion distribution among active cases
        - Per element: average List 1 and List 2 fact counts among active cases

    Fact-level:
        - Average number of atomic facts per case
        - Average List 1, List 2, List 3 sizes per case
        - Average per-element List 1 and List 2 sizes
        - List compression ratios

    Pipeline quality:
        - Subset constraint satisfaction rate (List 2 ⊆ List 1, List 3 ⊆ List 2)

Hardcoded paths:
    GOLD_DIR       — directory containing gold standard JSONs
    ATOMIC_DIR     — directory containing atomic facts JSONs
    CASE_LIST_FILE — txt file listing all benchmark case names

Usage:
    python compute_benchmark_stats.py
"""

import json
from pathlib import Path
from collections import defaultdict

import numpy as np
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GOLD_DIR       = "../compiled_gold_standard"
ATOMIC_DIR     = "../outputs/atomic_facts"
CASE_LIST_FILE = "../included_all_case_names.txt"

MAIN_ELEMENTS = [
    "scope",
    "interference",
    "prescribed_by_law",
    "legitimate_aim",
    "necessity",
    "positive_obligation",
]

ELEMENT_DISPLAY = {
    "scope":               "Scope",
    "interference":        "Interference",
    "prescribed_by_law":   "Prescribed by law",
    "legitimate_aim":      "Legitimate aim",
    "necessity":           "Necessity",
    "positive_obligation": "Positive obligation",
}

# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def discover_cases() -> list:
    lines = Path(CASE_LIST_FILE).read_text(encoding="utf-8").splitlines()
    return [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]


def load_gold(stem: str) -> dict:
    return json.loads((Path(GOLD_DIR) / f"{stem}.json").read_text(encoding="utf-8"))


def load_atomic(stem: str) -> list:
    path = Path(ATOMIC_DIR) / f"{stem}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))

# ---------------------------------------------------------------------------
# Statistics computation
# ---------------------------------------------------------------------------

def compute_stats(cases: list) -> dict:
    # Case-level accumulators
    n_violated      = 0
    n_not_violated  = 0
    active_el_counts = []  # number of active elements per case

    # Element-level accumulators
    el_active        = defaultdict(int)   # element -> count of active cases
    el_not_discussed = defaultdict(int)   # element -> count of not_discussed cases
    el_yes           = defaultdict(int)   # element -> count of yes conclusions
    el_no            = defaultdict(int)   # element -> count of no conclusions
    el_list1_sizes   = defaultdict(list)  # element -> list of List 1 sizes (active only)
    el_list2_sizes   = defaultdict(list)  # element -> list of List 2 sizes (active only)

    # Fact-level accumulators
    atomic_counts   = []   # atomic fact count per case
    list1_per_case  = []   # total List 1 facts per case (sum across elements)
    list2_per_case  = []   # total List 2 facts per case
    list3_per_case  = []   # List 3 facts per case

    # Pipeline quality
    l2_subset_l1_ok  = 0   # cases where List 2 ⊆ List 1 for all elements
    l3_subset_l2_ok  = 0   # cases where List 3 ⊆ List 2
    n_valid          = 0   # cases with both gold and atomic facts

    n_missing_atomic = 0
    n_missing_gold   = 0

    for stem in tqdm(cases, desc="Computing statistics"):
        gold_path = Path(GOLD_DIR) / f"{stem}.json"
        if not gold_path.exists():
            n_missing_gold += 1
            continue

        gold   = load_gold(stem)
        atomic = load_atomic(stem)

        if not atomic:
            n_missing_atomic += 1

        # ── Case-level ────────────────────────────────────────────────────────
        violated = gold["conclusion"]["violated"]
        if violated:
            n_violated += 1
        else:
            n_not_violated += 1

        elements = gold["conclusion"]["elements"]
        n_active = sum(
            1 for el in MAIN_ELEMENTS
            if elements.get(el, {}).get("conclusion") is not None
        )
        active_el_counts.append(n_active)

        # ── Element-level ─────────────────────────────────────────────────────
        fm = gold["fact_mapping"]
        list1 = fm.get("list1", {})
        list2 = fm.get("list2", {})
        list3 = set(fm.get("list3", []))

        case_list1_total = 0
        case_list2_total = 0

        for el in MAIN_ELEMENTS:
            conc = elements.get(el, {}).get("conclusion")

            if conc is None:
                el_not_discussed[el] += 1
            else:
                el_active[el] += 1
                if conc == "yes":
                    el_yes[el] += 1
                else:
                    el_no[el] += 1

                l1_facts = set(list1.get(el, []))
                l2_facts = set(list2.get(el, []))

                if l1_facts:
                    el_list1_sizes[el].append(len(l1_facts))
                if l2_facts:
                    el_list2_sizes[el].append(len(l2_facts))

                case_list1_total += len(l1_facts)
                case_list2_total += len(l2_facts)

        list1_per_case.append(case_list1_total)
        list2_per_case.append(case_list2_total)
        list3_per_case.append(len(list3))

        # ── Atomic facts ──────────────────────────────────────────────────────
        if atomic:
            atomic_counts.append(len(atomic))

        # ── Pipeline quality: subset constraints ──────────────────────────────
        l2_in_l1 = all(
            set(list2.get(el, [])) <= set(list1.get(el, []))
            for el in MAIN_ELEMENTS
        )
        # List 3 ⊆ union of List 2 across all elements
        l2_union = set(f for el in MAIN_ELEMENTS for f in list2.get(el, []))
        l3_in_l2 = list3 <= l2_union

        if l2_in_l1:
            l2_subset_l1_ok += 1
        if l3_in_l2:
            l3_subset_l2_ok += 1
        n_valid += 1

    n_total = n_violated + n_not_violated

    return {
        "n_total":           n_total,
        "n_missing_gold":    n_missing_gold,
        "n_missing_atomic":  n_missing_atomic,
        "n_violated":        n_violated,
        "n_not_violated":    n_not_violated,
        "active_el_counts":  active_el_counts,
        "el_active":         dict(el_active),
        "el_not_discussed":  dict(el_not_discussed),
        "el_yes":            dict(el_yes),
        "el_no":             dict(el_no),
        "el_list1_sizes":    dict(el_list1_sizes),
        "el_list2_sizes":    dict(el_list2_sizes),
        "atomic_counts":     atomic_counts,
        "list1_per_case":    list1_per_case,
        "list2_per_case":    list2_per_case,
        "list3_per_case":    list3_per_case,
        "l2_subset_l1_ok":   l2_subset_l1_ok,
        "l3_subset_l2_ok":   l3_subset_l2_ok,
        "n_valid":           n_valid,
    }

# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def safe_mean(lst):
    return float(np.mean(lst)) if lst else float("nan")

def safe_pct(num, denom):
    return 100.0 * num / denom if denom > 0 else float("nan")


def print_stats(s: dict) -> None:
    n = s["n_total"]
    sep = "=" * 70

    print(f"\n{sep}")
    print("BENCHMARK STATISTICS")
    print(sep)

    # ── Case-level ────────────────────────────────────────────────────────────
    print(f"\n{'CASE-LEVEL':}")
    print(f"  Total cases                    : {n}")
    if s["n_missing_gold"] > 0:
        print(f"  Missing gold standards         : {s['n_missing_gold']}")
    if s["n_missing_atomic"] > 0:
        print(f"  Missing atomic facts           : {s['n_missing_atomic']}")
    print(f"  Violated                       : {s['n_violated']} ({safe_pct(s['n_violated'], n):.1f}%)")
    print(f"  Not violated                   : {s['n_not_violated']} ({safe_pct(s['n_not_violated'], n):.1f}%)")

    ac = s["active_el_counts"]
    print(f"\n  Active elements per case:")
    print(f"    Mean   : {safe_mean(ac):.2f}")
    print(f"    Min    : {min(ac)}")
    print(f"    Max    : {max(ac)}")
    from collections import Counter
    dist = Counter(ac)
    for k in sorted(dist):
        print(f"    {k} active elements : {dist[k]} cases ({safe_pct(dist[k], n):.1f}%)")

    # ── Element-level ─────────────────────────────────────────────────────────
    print(f"\n{'ELEMENT-LEVEL':}")
    print(f"\n  {'Element':<28} {'Active':>7} {'Not disc.':>10} {'Yes':>6} {'No':>6} {'%Yes':>7} {'Avg L1':>8} {'Avg L2':>8}")
    print("  " + "-" * 82)

    for el in MAIN_ELEMENTS:
        active   = s["el_active"].get(el, 0)
        nd       = s["el_not_discussed"].get(el, 0)
        yes      = s["el_yes"].get(el, 0)
        no       = s["el_no"].get(el, 0)
        pct_yes  = safe_pct(yes, active)
        avg_l1   = safe_mean(s["el_list1_sizes"].get(el, []))
        avg_l2   = safe_mean(s["el_list2_sizes"].get(el, []))
        label    = ELEMENT_DISPLAY[el]
        print(f"  {label:<28} {active:>7} {nd:>10} {yes:>6} {no:>6} {pct_yes:>6.1f}% {avg_l1:>8.2f} {avg_l2:>8.2f}")

    # ── Fact-level ────────────────────────────────────────────────────────────
    print(f"\n{'FACT-LEVEL':}")
    print(f"  Atomic facts per case:")
    print(f"    Mean   : {safe_mean(s['atomic_counts']):.2f}")
    print(f"    Min    : {min(s['atomic_counts']) if s['atomic_counts'] else 'n/a'}")
    print(f"    Max    : {max(s['atomic_counts']) if s['atomic_counts'] else 'n/a'}")

    avg_l1 = safe_mean(s["list1_per_case"])
    avg_l2 = safe_mean(s["list2_per_case"])
    avg_l3 = safe_mean(s["list3_per_case"])
    print(f"\n  Total mapped facts per case (sum across elements):")
    print(f"    Avg List 1 : {avg_l1:.2f}")
    print(f"    Avg List 2 : {avg_l2:.2f}")
    print(f"    Avg List 3 : {avg_l3:.2f}")

    if avg_l1 > 0:
        print(f"\n  Compression ratios (averaged across cases):")
        r21 = safe_mean([l2/l1 if l1 > 0 else float("nan")
                         for l1, l2 in zip(s["list1_per_case"], s["list2_per_case"])])
        r32 = safe_mean([l3/l2 if l2 > 0 else float("nan")
                         for l2, l3 in zip(s["list2_per_case"], s["list3_per_case"])])
        r31 = safe_mean([l3/l1 if l1 > 0 else float("nan")
                         for l1, l3 in zip(s["list1_per_case"], s["list3_per_case"])])
        print(f"    List 2 / List 1 : {r21:.3f}")
        print(f"    List 3 / List 2 : {r32:.3f}")
        print(f"    List 3 / List 1 : {r31:.3f}")

    print(f"\n  Per-element average fact counts (active cases only):")
    print(f"  {'Element':<28} {'Avg List 1':>12} {'Avg List 2':>12} {'Ratio L2/L1':>13}")
    print("  " + "-" * 68)
    for el in MAIN_ELEMENTS:
        avg_l1_el = safe_mean(s["el_list1_sizes"].get(el, []))
        avg_l2_el = safe_mean(s["el_list2_sizes"].get(el, []))
        ratio = avg_l2_el / avg_l1_el if avg_l1_el > 0 else float("nan")
        label = ELEMENT_DISPLAY[el]
        print(f"  {label:<28} {avg_l1_el:>12.2f} {avg_l2_el:>12.2f} {ratio:>13.3f}")

    # ── Pipeline quality ──────────────────────────────────────────────────────
    print(f"\n{'PIPELINE QUALITY':}")
    nv = s["n_valid"]
    print(f"  Cases with valid gold standard : {nv}")
    print(f"  List 2 ⊆ List 1 satisfied      : {s['l2_subset_l1_ok']} / {nv} ({safe_pct(s['l2_subset_l1_ok'], nv):.1f}%)")
    print(f"  List 3 ⊆ List 2 satisfied      : {s['l3_subset_l2_ok']} / {nv} ({safe_pct(s['l3_subset_l2_ok'], nv):.1f}%)")

    print(f"\n{sep}\n")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Discovering cases...")
    cases = discover_cases()
    print(f"Found {len(cases)} cases in case list.\n")

    stats = compute_stats(cases)
    print_stats(stats)


if __name__ == "__main__":
    main()