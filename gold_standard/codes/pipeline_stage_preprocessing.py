"""
pipeline_stage_0.py

ECtHR judgment structuring pipeline (stage 0).

Takes a raw .txt file (PDF-extracted, with page markers and contamination)
and produces a structured JSON with the facts section and Art. 11 reasoning
section as lists of cleaned, numbered paragraphs.

Steps:
    1. Read raw .txt file
    2. Call Claude API with the structuring prompt → raw LLM JSON
    3. Post-process: validate and write final output

Final output schema:
    {
      "facts": [
        {
          "para_id":          1,
          "source_paragraph": 7,
          "section_path":     ["THE FACTS", "I. THE CIRCUMSTANCES OF THE CASE"],
          "text":             "The applicants live in Kharkiv."
        },
        ...
      ],
      "art11": [
        {
          "para_id":          1,
          "source_paragraph": 187,
          "section_path":     ["THE LAW", "IV. ALLEGED VIOLATIONS OF ARTICLE 11"],
          "text":             "The applicants complained of a number of violations..."
        },
        ...
      ]
    }

Usage:
    python pipeline_stage_0.py case_118
    python pipeline_stage_0.py --input data/case_118.txt --output output/case_118.json

Intermediate LLM output is saved to:
    temp/<stem>_llm_raw.json
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import anthropic


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_KEY     = os.environ["ANTHROPIC_API_KEY"]
MODEL       = "claude-sonnet-4-6"
MAX_TOKENS  = 64000
TEMPERATURE = 0.0
PROMPT_PATH = "prompts/prompt_stage_preprocessing.md"
TEMP_DIR    = "../temps/preprocessed"


# ---------------------------------------------------------------------------
# JSON schema for LLM structured output
# ---------------------------------------------------------------------------

PARAGRAPH_SCHEMA = {
    "type": "object",
    "required": ["para_id", "source_paragraph", "section_path", "text"],
    "properties": {
        "para_id":          {"type": "integer"},
        "source_paragraph": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "section_path":     {"type": "array", "items": {"type": "string"}},
        "text":             {"type": "string"}
    },
    "additionalProperties": False
}

RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["facts", "art11"],
    "properties": {
        "facts": {"type": "array", "items": PARAGRAPH_SCHEMA},
        "art11": {"type": "array", "items": PARAGRAPH_SCHEMA}
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
# API call
# ---------------------------------------------------------------------------

def call_api(
    document_text: str,
    system_prompt: str,
    user_prompt_template: str
) -> dict:
    if "`{{document}}`" not in user_prompt_template:
        raise ValueError("User prompt template must contain a `{{document}}` placeholder.")

    user_prompt = user_prompt_template.replace("`{{document}}`", document_text)

    client = anthropic.Anthropic(api_key=API_KEY, timeout=1200)
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        temperature=TEMPERATURE,
        thinking={"type": "disabled"},
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


# ---------------------------------------------------------------------------
# Post-processing / validation
# ---------------------------------------------------------------------------

def validate(llm_output: dict) -> tuple[list[str], list[str]]:
    """
    Basic validation of the LLM output.
    Returns (warnings, errors).
    """
    warnings: list[str] = []
    errors:   list[str] = []

    para_pat = re.compile(r"^\d+\.\s")

    for section in ["facts", "art11"]:
        paras = llm_output.get(section, [])

        # Sequential para_ids from 1
        ids = [p["para_id"] for p in paras]
        if ids != list(range(1, len(paras) + 1)):
            errors.append(
                f"{section}: para_ids are not sequential from 1 — "
                f"got {ids[:10]}{'...' if len(ids) > 10 else ''}"
            )

        # source_paragraph should match paragraph number prefix in text
        for p in paras:
            sp = p["source_paragraph"]
            if sp is None:
                continue
            text = p.get("text", "")
            # The text should not start with "NN.  " since headings are stripped,
            # but the source_paragraph number should appear near the start
            m = para_pat.match(text)
            if m:
                found = int(m.group(0).rstrip(". "))
                if found != sp:
                    errors.append(
                        f"{section} para_id={p['para_id']}: source_paragraph={sp} "
                        f"but text starts with {found}: '{text[:60]}'"
                    )

        # Warn on empty text
        for p in paras:
            if not p.get("text", "").strip():
                warnings.append(
                    f"{section} para_id={p['para_id']}: empty text "
                    f"(source_paragraph={p['source_paragraph']})"
                )

        # Warn if section is empty
        if not paras:
            warnings.append(f"{section}: no paragraphs extracted")

    # source_paragraph numbers should increase monotonically within each section
    for section in ["facts", "art11"]:
        paras = llm_output.get(section, [])
        numbered = [p for p in paras if p["source_paragraph"] is not None]
        for i in range(1, len(numbered)):
            prev = numbered[i - 1]["source_paragraph"]
            curr = numbered[i]["source_paragraph"]
            if curr < prev:
                warnings.append(
                    f"{section}: source_paragraph decreased from {prev} to {curr} "
                    f"at para_id={numbered[i]['para_id']} — possible missed paragraphs"
                )

    return warnings, errors


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    input_txt: str,
    output_json: str,
    temp_json: str,
    system_prompt: str,
    user_prompt_template: str
) -> None:
    input_path  = Path(input_txt)
    output_path = Path(output_json)
    temp_path   = Path(temp_json)

    if not input_path.exists():
        print(f"[ERROR] Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Read input ────────────────────────────────────────────────────
    print(f"[1/3] Reading: {input_path.name}")
    document_text = input_path.read_text(encoding="utf-8")
    print(f"      {len(document_text):,} characters, "
          f"{document_text.count('='*10)} page markers")

    # ── Step 2: API call ──────────────────────────────────────────────────────
    print(f"[2/3] Calling Claude API ({MODEL})...")

    if temp_path.exists():
        print(f"      Found cached LLM output at {temp_path}, loading...")
        with open(temp_path, encoding="utf-8") as f:
            llm_output = json.load(f)
    else:
        llm_output = call_api(document_text, system_prompt, user_prompt_template)
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(llm_output, f, ensure_ascii=False, indent=2)
        print(f"      Raw LLM output saved to: {temp_path}")

    print(f"      Facts paragraphs:  {len(llm_output.get('facts', []))}")
    print(f"      Art.11 paragraphs: {len(llm_output.get('art11', []))}")

    # ── Step 3: Validate and save ─────────────────────────────────────────────
    print(f"[3/3] Validating...")
    warnings, errors = validate(llm_output)

    print(f"\n      ERRORS:   {len(errors)}")
    for e in errors:
        print(f"        [ERROR] {e}")
    print(f"      WARNINGS: {len(warnings)}")
    for w in warnings:
        print(f"        [WARN]  {w}")

    for section in ["facts", "art11"]:
        paras = llm_output.get(section, [])
        numbered = [p["source_paragraph"] for p in paras
                    if p["source_paragraph"] is not None]
        if numbered:
            print(f"\n      {section}: paras {min(numbered)}–{max(numbered)} "
                  f"({len(paras)} entries, "
                  f"{len(paras) - len(numbered)} null)")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(llm_output, f, ensure_ascii=False, indent=2)
    print(f"\n✓ Output written to: {output_path}")

    if errors:
        print(f"\n⚠  {len(errors)} error(s) detected — review output carefully.",
              file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def case_paths(case_name: str) -> tuple[str, str]:
    return (
        f"../outputs/pdf2txt/{case_name}.txt",
        f"../outputs/preprocessed/{case_name}.json",
        f"../temps/preprocessed/{case_name}.json"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ECtHR judgment structuring pipeline (stage 0): "
                    "extract facts and Art. 11 reasoning from contaminated PDF text"
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
        failed = []
        for i, case_name in enumerate(case_names, 1):
            print(f"{'='*60}")
            print(f"[{i}/{len(case_names)}] {case_name}")
            print(f"{'='*60}")
            input_txt, output_json, temp_json = case_paths(case_name)
            try:
                run_pipeline(input_txt, output_json, temp_json,
                             system_prompt, user_prompt_template)
            except Exception as e:
                print(f"[ERROR] {case_name} failed: {e}", file=sys.stderr)
                failed.append(case_name)
            print()
        print(f"\nBatch complete: "
              f"{len(case_names) - len(failed)}/{len(case_names)} succeeded")
        if failed:
            print(f"Failed cases: {', '.join(failed)}", file=sys.stderr)
            sys.exit(1)
    else:
        input_txt, output_json, temp_json = case_paths(args.case_name)
        run_pipeline(input_txt, output_json, temp_json, system_prompt, user_prompt_template)