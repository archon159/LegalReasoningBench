"""
run_pipeline.py

Orchestrator for the ECtHR Article 11 gold-standard pipeline.

Runs five stages in sequence for each case:
    0. preprocessing        (pipeline_stage_preprocessing.py)
    1. atomic_facts         (pipeline_stage_atomic_facts.py)
    2. conclusion           (pipeline_stage_conclusion.py)
    3. fact_grounding       (pipeline_stage_fact_grounding.py)
    4. fact_mapping         (pipeline_stage_fact_mapping.py)

Each stage is run as a subprocess. Status is tracked per case in
status/<case_name>.json, enabling safe resumption after interruption.
Logs are written to logs/<stage>/<case_name>.log.

Usage:
    python run_pipeline.py --batch cases.txt
    python run_pipeline.py case_118
    python run_pipeline.py case_118 case_133 case_311
    python run_pipeline.py --batch cases.txt --dry-run
    python run_pipeline.py --batch cases.txt --force   # re-run all stages
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

STAGES = [
    ("preprocessing",  "pipeline_stage_preprocessing.py"),
    ("atomic_facts",   "pipeline_stage_atomic_facts.py"),
    ("conclusion",     "pipeline_stage_conclusion.py"),
    ("fact_grounding", "pipeline_stage_fact_grounding.py"),
    ("fact_mapping",   "pipeline_stage_fact_mapping.py"),
]

STATUS_DIR = Path("../status")
LOG_DIR    = Path("../logs")
SUMMARY_DIR = Path("../logs")


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------

def load_status(case_name: str) -> dict:
    path = STATUS_DIR / f"{case_name}.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {
        "case_name": case_name,
        "stages": {
            stage: {
                "status":    "not_run",
                "start":     None,
                "end":       None,
                "elapsed_s": None,
                "error":     None,
            }
            for stage, _ in STAGES
        }
    }


def save_status(case_name: str, status: dict) -> None:
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    path = STATUS_DIR / f"{case_name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)


def is_complete(stage_status: dict) -> bool:
    return stage_status["status"] == "completed"


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def get_log_path(stage: str, case_name: str) -> Path:
    log_dir = LOG_DIR / stage
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"{case_name}.log"


def write_log(path: Path, stdout: str, stderr: str, returncode: int) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"Return code: {returncode}\n")
        f.write("=" * 60 + "\n")
        f.write("STDOUT:\n")
        f.write(stdout or "(empty)\n")
        f.write("=" * 60 + "\n")
        f.write("STDERR:\n")
        f.write(stderr or "(empty)\n")


# ---------------------------------------------------------------------------
# Run a single stage
# ---------------------------------------------------------------------------

def run_stage(
    stage_name: str,
    script: str,
    case_name: str,
    dry_run: bool = False,
) -> tuple[bool, float, str | None]:
    """
    Run a single pipeline stage for a case.
    Returns (success, elapsed_seconds, error_message).
    """
    log_path = get_log_path(stage_name, case_name)
    cmd = [sys.executable, script, case_name]

    if dry_run:
        print(f"    [DRY-RUN] Would run: {' '.join(cmd)}")
        return True, 0.0, None

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        elapsed = time.time() - start
        write_log(log_path, result.stdout, result.stderr, result.returncode)

        if result.returncode != 0:
            # Extract last non-empty line from stderr as error message
            err_lines = [l.strip() for l in result.stderr.splitlines() if l.strip()]
            error_msg = err_lines[-1] if err_lines else f"Exit code {result.returncode}"
            return False, elapsed, error_msg

        return True, elapsed, None

    except Exception as e:
        elapsed = time.time() - start
        error_msg = str(e)
        write_log(log_path, "", error_msg, -1)
        return False, elapsed, error_msg


# ---------------------------------------------------------------------------
# Process a single case
# ---------------------------------------------------------------------------

def process_case(
    case_name: str,
    dry_run: bool = False,
    force: bool = False,
) -> dict:
    """
    Run all pipeline stages for a case, respecting cached status.
    Returns the final status dict for this case.
    """
    status = load_status(case_name)

    print(f"\n  Case: {case_name}")

    for stage_name, script in STAGES:
        stage_status = status["stages"][stage_name]

        # Skip if already completed and not forcing
        if is_complete(stage_status) and not force:
            elapsed = stage_status.get("elapsed_s", 0) or 0
            print(f"    [{stage_name}] SKIPPED (already completed in {elapsed:.1f}s)")
            continue

        # Skip if a prior stage failed
        prior_stages = [s for s, _ in STAGES[:STAGES.index((stage_name, script))]]
        prior_failed = any(
            status["stages"][s]["status"] == "failed"
            for s in prior_stages
        )
        if prior_failed:
            print(f"    [{stage_name}] SKIPPED (prior stage failed)")
            status["stages"][stage_name]["status"] = "skipped"
            save_status(case_name, status)
            continue

        # Run stage
        print(f"    [{stage_name}] Running...", end="", flush=True)
        start_ts = datetime.now().isoformat()
        stage_status["start"] = start_ts
        stage_status["status"] = "running"
        save_status(case_name, status)

        success, elapsed, error = run_stage(stage_name, script, case_name, dry_run)
        end_ts = datetime.now().isoformat()

        stage_status["end"]       = end_ts
        stage_status["elapsed_s"] = round(elapsed, 2)
        stage_status["error"]     = error

        if success:
            stage_status["status"] = "completed"
            print(f" ✓  ({elapsed:.1f}s)")
        else:
            stage_status["status"] = "failed"
            print(f" ✗  ({elapsed:.1f}s)")
            print(f"      Error: {error}")
            print(f"      Log: {get_log_path(stage_name, case_name)}")

        save_status(case_name, status)

    return status


# ---------------------------------------------------------------------------
# Summary report
# ---------------------------------------------------------------------------

def generate_summary(
    all_statuses: list[dict],
    total_elapsed: float,
    dry_run: bool,
) -> str:
    lines = []
    lines.append("=" * 70)
    lines.append("PIPELINE RUN SUMMARY")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if dry_run:
        lines.append("MODE: DRY RUN")
    lines.append(f"Total wall-clock time: {total_elapsed:.1f}s")
    lines.append("=" * 70)

    n_total     = len(all_statuses)
    n_completed = 0
    n_partial   = 0
    n_failed    = 0

    case_summaries = []

    for status in all_statuses:
        case_name = status["case_name"]
        stages    = status["stages"]

        stage_results = []
        any_failed    = False
        any_not_run   = False
        all_completed = True

        for stage_name, _ in STAGES:
            s = stages[stage_name]
            st = s["status"]
            elapsed = s.get("elapsed_s")
            elapsed_str = f"{elapsed:.1f}s" if elapsed is not None else "-"

            if st == "completed":
                stage_results.append(f"✓ {stage_name} ({elapsed_str})")
            elif st == "failed":
                stage_results.append(f"✗ {stage_name} ({elapsed_str}): {s.get('error', '')}")
                any_failed    = True
                all_completed = False
            elif st == "skipped":
                stage_results.append(f"- {stage_name} (skipped)")
                all_completed = False
            else:
                stage_results.append(f"? {stage_name} (not run)")
                any_not_run   = True
                all_completed = False

        if all_completed:
            n_completed += 1
            case_label = "COMPLETE"
        elif any_failed:
            n_failed += 1
            case_label = "FAILED"
        else:
            n_partial += 1
            case_label = "PARTIAL"

        case_summaries.append((case_name, case_label, stage_results))

    lines.append(f"\nTotal cases : {n_total}")
    lines.append(f"  Completed : {n_completed}")
    lines.append(f"  Partial   : {n_partial}")
    lines.append(f"  Failed    : {n_failed}")
    lines.append("")
    lines.append("-" * 70)
    lines.append("PER-CASE BREAKDOWN")
    lines.append("-" * 70)

    for case_name, label, stage_results in case_summaries:
        lines.append(f"\n{case_name}  [{label}]")
        for sr in stage_results:
            lines.append(f"  {sr}")

    lines.append("\n" + "=" * 70)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="ECtHR Article 11 pipeline orchestrator"
    )
    parser.add_argument(
        "case_names", nargs="*", default=[],
        help="One or more case names to process (e.g. case_118 case_133)"
    )
    parser.add_argument(
        "--batch", dest="batch_file", default=None,
        metavar="BATCH_FILE",
        help="Path to a .txt file listing case names to process, one per line"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be run without executing anything"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-run all stages even if already completed"
    )
    args = parser.parse_args()

    # Collect case names
    case_names = list(args.case_names)
    if args.batch_file:
        batch_path = Path(args.batch_file)
        if not batch_path.exists():
            print(f"[ERROR] Batch file not found: {batch_path}", file=sys.stderr)
            sys.exit(1)
        batch_cases = [
            line.strip()
            for line in batch_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        case_names.extend(batch_cases)

    if not case_names:
        parser.print_help()
        sys.exit(1)

    # Deduplicate while preserving order
    seen = set()
    case_names = [c for c in case_names if not (c in seen or seen.add(c))]

    print(f"Pipeline orchestrator")
    print(f"Cases to process: {len(case_names)}")
    print(f"Stages: {', '.join(s for s, _ in STAGES)}")
    if args.dry_run:
        print("Mode: DRY RUN")
    if args.force:
        print("Mode: FORCE (re-running all stages)")
    print()

    # Run all cases
    wall_start   = time.time()
    all_statuses = []

    for i, case_name in enumerate(case_names, 1):
        print(f"[{i}/{len(case_names)}] Processing {case_name}")
        status = process_case(case_name, dry_run=args.dry_run, force=args.force)
        all_statuses.append(status)

    total_elapsed = time.time() - wall_start

    # Generate and write summary
    summary = generate_summary(all_statuses, total_elapsed, args.dry_run)
    print("\n" + summary)

    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_path = SUMMARY_DIR / f"summary_{ts}.txt"
    summary_path.write_text(summary, encoding="utf-8")
    print(f"\nSummary written to: {summary_path}")

    # Exit with error code if any case failed
    any_failed = any(
        any(
            s["stages"][stage]["status"] == "failed"
            for stage, _ in STAGES
        )
        for s in all_statuses
    )
    if any_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()