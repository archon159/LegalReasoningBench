"""
pipeline_stage_sample_selection.py

ECtHR judgment exclusion filter (pre-pipeline stage).

Steps:
    1. Read raw .txt judgment
    2. Call Claude API with exclusion criteria prompt
    3. Save structured JSON verdict

Final output schema:
    {
      "criteria": {
        "is_assembly_case":   true,
        "is_coherent_merits": true,
        "facts_are_settled":  true,
        "is_genuine_merits":  true
      },
      "include":       true,
      "justification": "..."
    }

Timings file (output/timings.json) — keyed by case name:
    {
      "CASE OF GALSTYAN v. ARMENIA": {
        "status":           "success",
        "timestamp":        "2026-04-13T10:23:00",
        "duration_seconds": 8.4,
        "verdict":          "INCLUDE"
      },
      "CASE OF CHERNEGA v. UKRAINE": {
        "status":           "failed",
        "timestamp":        "2026-04-13T10:24:15",
        "duration_seconds": 3.1,
        "error":            "Output truncated at MAX_TOKENS"
      }
    }

Usage:
    python pipeline_stage_sample_selection.py "CASE OF GALSTYAN v. ARMENIA"
    python pipeline_stage_sample_selection.py --batch cases.txt
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import anthropic


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_KEY      = os.environ["ANTHROPIC_API_KEY"]
MODEL        = "claude-sonnet-4-6"
MAX_TOKENS   = 4096
TEMPERATURE  = 0.0
PROMPT_PATH  = "prompts/prompt_stage_sample_selection.md"
TIMINGS_PATH = "timings/sample_selection.json"

MAX_RETRIES  = 2          # retries for transient API errors
RETRY_DELAY  = 5          # seconds between retries

# Exceptions considered transient (worth retrying)
TRANSIENT_EXCEPTIONS = (
    anthropic.APITimeoutError,
    anthropic.APIConnectionError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)

# Exceptions that are fatal — no retry, abort entire batch immediately.
# PermissionDeniedError (403) covers exhausted balance.
# AuthenticationError (401) covers invalid API key.
FATAL_EXCEPTIONS = (
    anthropic.PermissionDeniedError,
    anthropic.AuthenticationError,
)


# ---------------------------------------------------------------------------
# JSON schema for structured output
# ---------------------------------------------------------------------------

RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["criteria", "include", "justification"],
    "properties": {
        "criteria": {
            "type": "object",
            "required": [
                "is_assembly_case",
                "is_coherent_merits",
                "facts_are_settled",
                "is_genuine_merits"
            ],
            "properties": {
                "is_assembly_case":   {"type": "boolean"},
                "is_coherent_merits": {"type": "boolean"},
                "facts_are_settled":  {"type": "boolean"},
                "is_genuine_merits":  {"type": "boolean"}
            },
            "additionalProperties": False
        },
        "include":       {"type": "boolean"},
        "justification": {"type": "string"}
    },
    "additionalProperties": False
}


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------

def load_prompt(prompt_path: str) -> tuple[str, str]:
    text = Path(prompt_path).read_text(encoding="utf-8")
    system_marker = "# SYSTEM PROMPT"
    user_marker   = "# USER PROMPT"
    if system_marker not in text or user_marker not in text:
        raise ValueError(
            f"Prompt file '{prompt_path}' must contain "
            f"'# SYSTEM PROMPT' and '# USER PROMPT' markers."
        )
    system_prompt = text.split(user_marker)[0].replace(system_marker, "").strip()
    user_prompt   = text.split(user_marker)[1].strip()
    return system_prompt, user_prompt


# ---------------------------------------------------------------------------
# Timings file helpers
# ---------------------------------------------------------------------------

def load_timings() -> dict:
    path = Path(TIMINGS_PATH)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_timings(timings: dict) -> None:
    path = Path(TIMINGS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(timings, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def is_already_processed(case_name: str, output_json: str) -> bool:
    """
    Returns True only if both conditions hold:
      1. timings.json records a 'success' entry for this case
      2. The output JSON file exists and is parseable
    """
    timings = load_timings()
    entry = timings.get(case_name, {})
    if entry.get("status") != "success":
        return False
    output_path = Path(output_json)
    if not output_path.exists():
        return False
    try:
        json.loads(output_path.read_text(encoding="utf-8"))
        return True
    except Exception:
        return False


def record_timing(case_name: str, entry: dict) -> None:
    timings = load_timings()
    timings[case_name] = entry
    save_timings(timings)


# ---------------------------------------------------------------------------
# API call (with retry for transient errors)
# ---------------------------------------------------------------------------

def call_api(
    judgment_text: str,
    system_prompt: str,
    user_prompt_template: str
) -> dict:
    if "{case_document}" not in user_prompt_template:
        raise ValueError(
            "User prompt template must contain a {case_document} placeholder."
        )

    user_prompt = user_prompt_template.replace("{case_document}", judgment_text)
    client      = anthropic.Anthropic(api_key=API_KEY)

    last_error = None
    for attempt in range(1, MAX_RETRIES + 2):  # attempts = retries + 1
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                output_config={
                    "format": {
                        "type": "json_schema",
                        "schema": RESPONSE_SCHEMA
                    }
                }
            )
            if response.stop_reason == "max_tokens":
                raise RuntimeError(
                    f"Output truncated at MAX_TOKENS ({MAX_TOKENS}). "
                    f"Increase MAX_TOKENS and retry."
                )
            return json.loads(response.content[0].text)

        except FATAL_EXCEPTIONS as e:
            # Balance exhausted or invalid key — no point retrying any case.
            # Re-raise immediately so the batch loop can abort.
            raise

        except TRANSIENT_EXCEPTIONS as e:
            last_error = e
            if attempt <= MAX_RETRIES:
                print(f"  [WARN] Transient error (attempt {attempt}): {e}. "
                      f"Retrying in {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)
            else:
                raise RuntimeError(
                    f"API call failed after {MAX_RETRIES + 1} attempts: {e}"
                ) from e


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate(result: dict) -> list[str]:
    """
    Consistency check: include must be True iff all criteria are True.
    Returns a list of error strings (empty if clean).
    """
    errors   = []
    criteria = result["criteria"]
    all_met  = all([
        criteria["is_assembly_case"],
        criteria["is_coherent_merits"],
        criteria["facts_are_settled"],
        criteria["is_genuine_merits"]
    ])
    if result["include"] != all_met:
        errors.append(
            f"Inconsistent output: include={result['include']} but "
            f"criteria imply include={all_met}"
        )
    return errors


# ---------------------------------------------------------------------------
# Main pipeline  (returns True on success, False on failure)
# ---------------------------------------------------------------------------

def run_pipeline(
    case_name: str,
    input_txt: str,
    output_json: str,
    system_prompt: str,
    user_prompt_template: str
) -> bool:
    input_path  = Path(input_txt)
    output_path = Path(output_json)

    # ── Resumability check ────────────────────────────────────────────────────
    if is_already_processed(case_name, output_json):
        timings = load_timings()
        prev    = timings[case_name]
        print(f"  [SKIP] Already processed on {prev['timestamp']} "
              f"({prev['duration_seconds']:.1f}s) — verdict: {prev.get('verdict', '?')}")
        return True

    if not input_path.exists():
        error_msg = f"Input file not found: {input_path}"
        print(f"  [ERROR] {error_msg}", file=sys.stderr)
        record_timing(case_name, {
            "status":           "failed",
            "timestamp":        datetime.now(timezone.utc).isoformat(),
            "duration_seconds": 0.0,
            "error":            error_msg
        })
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    start_time = time.monotonic()
    timestamp  = datetime.now(timezone.utc).isoformat()

    try:
        # ── Step 1: Read ──────────────────────────────────────────────────────
        print(f"  [1/2] Reading: {input_path.name} "
              f"({len(input_path.read_text(encoding='utf-8').splitlines())} lines)")

        judgment_text = input_path.read_text(encoding="utf-8")

        # ── Step 2: API call ──────────────────────────────────────────────────
        print(f"  [2/2] Calling Claude API ({MODEL})...")
        result = call_api(judgment_text, system_prompt, user_prompt_template)

        # ── Validate ──────────────────────────────────────────────────────────
        errors = validate(result)
        if errors:
            raise ValueError(f"Validation failed: {'; '.join(errors)}")

        # ── Report ────────────────────────────────────────────────────────────
        duration = time.monotonic() - start_time
        verdict  = "INCLUDE" if result["include"] else "EXCLUDE"
        criteria = result["criteria"]
        print(f"\n  Verdict:            {verdict}")
        print(f"  is_assembly_case:   {criteria['is_assembly_case']}")
        print(f"  is_coherent_merits: {criteria['is_coherent_merits']}")
        print(f"  facts_are_settled:  {criteria['facts_are_settled']}")
        print(f"  is_genuine_merits:  {criteria['is_genuine_merits']}")
        print(f"  Justification:      {result['justification']}")
        print(f"  Duration:           {duration:.1f}s")

        # ── Save output ───────────────────────────────────────────────────────
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print(f"\n  ✓ Output written to: {output_path}")

        # ── Record success ────────────────────────────────────────────────────
        record_timing(case_name, {
            "status":           "success",
            "timestamp":        timestamp,
            "duration_seconds": round(duration, 2),
            "verdict":          verdict
        })
        return True

    except Exception as e:
        duration  = time.monotonic() - start_time
        error_msg = str(e)
        print(f"\n  [ERROR] {error_msg}", file=sys.stderr)
        record_timing(case_name, {
            "status":           "failed",
            "timestamp":        timestamp,
            "duration_seconds": round(duration, 2),
            "error":            error_msg
        })
        return False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def case_paths(case_name: str) -> tuple[str, str]:
    return (
        f"../outputs/pdf2txt/{case_name}.txt",
        f"../outputs/sample_selection/{case_name}.json"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ECtHR judgment sample selection: "
                    "read raw text → LLM API → sample selection verdict"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "case_name", nargs="?", default=None,
        help="Case name to process (e.g. 'CASE OF GALSTYAN v. ARMENIA')"
    )
    group.add_argument(
        "--batch", dest="batch_file", default=None,
        metavar="BATCH_FILE",
        help="Path to a .txt file listing case names to process, one per line"
    )
    args = parser.parse_args()

    system_prompt, user_prompt_template = load_prompt(PROMPT_PATH)

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

        succeeded, failed, skipped = [], [], []
        for i, case_name in enumerate(case_names, 1):
            print(f"{'='*60}")
            print(f"[{i}/{len(case_names)}] {case_name}")
            print(f"{'='*60}")
            input_txt, output_json = case_paths(case_name)

            # Check skip before calling run_pipeline to track skipped count
            if is_already_processed(case_name, output_json):
                timings = load_timings()
                prev    = timings[case_name]
                print(f"  [SKIP] Already processed on {prev['timestamp']} "
                      f"({prev['duration_seconds']:.1f}s) "
                      f"— verdict: {prev.get('verdict', '?')}")
                skipped.append(case_name)
            else:
                try:
                    ok = run_pipeline(
                        case_name, input_txt, output_json,
                        system_prompt, user_prompt_template
                    )
                except FATAL_EXCEPTIONS as e:
                    print(f"\n[FATAL] {e}", file=sys.stderr)
                    print("Aborting batch — check API key or account balance.",
                          file=sys.stderr)
                    record_timing(case_name, {
                        "status":           "failed",
                        "timestamp":        datetime.now(timezone.utc).isoformat(),
                        "duration_seconds": 0.0,
                        "error":            f"FATAL: {e}"
                    })
                    sys.exit(1)
                (succeeded if ok else failed).append(case_name)
            print()

        print(f"\n{'='*60}")
        print(f"Batch complete:")
        print(f"  Succeeded: {len(succeeded)}")
        print(f"  Skipped:   {len(skipped)}")
        print(f"  Failed:    {len(failed)}")
        if failed:
            print(f"\nFailed cases:", file=sys.stderr)
            for name in failed:
                print(f"  - {name}", file=sys.stderr)
            sys.exit(1)

    else:
        case_name            = args.case_name
        input_txt, output_json = case_paths(case_name)
        ok = run_pipeline(
            case_name, input_txt, output_json,
            system_prompt, user_prompt_template
        )
        sys.exit(0 if ok else 1)