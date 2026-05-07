"""
pipeline_stage_1.py

Atomic fact extraction pipeline (stage 1).

Takes the structured output from pipeline.py (stage 0) and decomposes
the facts section paragraphs into atomic facts using an LLM call.

Steps:
    1. Load stage 0 output JSON
    2. Slice out fact paragraphs using section_index
    3. Call Claude API (stage 1 atomic fact extraction prompt)
    4. Post-process: replace para_id with paragraph_number + section_path
       from stage 0, and rename text_resolved → text

Usage:
    python pipeline_stage_1.py <stage0_output_json> <output_json>

    e.g.
    python pipeline_stage_1.py output/case_118.json output/case_118_facts.json

Intermediate LLM output is saved to:
    temp/<stem>_stage1_llm_raw.json

The final output is a JSON array:
    [
        {
            "fact_id":        "F001",
            "text":           "...",          // resolved, self-contained fact text
            "source_paragraph": 8,            // printed ECtHR paragraph number (int or null)
            "section_path":   ["I. THE CIRCUMSTANCES OF THE CASE", ...]
        },
        ...
    ]
"""

import argparse
import json
import os
import sys
from pathlib import Path

import anthropic


# ---------------------------------------------------------------------------
# Configuration — edit these as needed
# ---------------------------------------------------------------------------

API_KEY       = os.environ["ANTHROPIC_API_KEY"]
MODEL         = "claude-sonnet-4-6"
MAX_TOKENS    = 64000
TEMPERATURE   = 0.0
PROMPT_PATH   = "prompts/prompt_stage_atomic_facts.md"   # path to the fact extraction prompt file
TEMP_DIR      = "../temps/atomic_facts"                # directory for intermediate LLM outputs


# ---------------------------------------------------------------------------
# JSON schema for structured output (stage 1)
# ---------------------------------------------------------------------------

RESPONSE_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["fact_id", "text_resolved", "para_id"],
        "properties": {
            "fact_id":       {"type": "string"},
            "text_resolved": {"type": "string"},
            "para_id":       {"type": "integer"}
        },
        "additionalProperties": False
    }
}


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------

def load_prompt(prompt_path: str) -> tuple[str, str]:
    """
    Read prompt file and split into system and user sections.
    Expects markers:  ## SYSTEM PROMPT  and  ## USER PROMPT
    (stage 1 prompt uses ## rather than # at the top level)
    """
    text = Path(prompt_path).read_text(encoding="utf-8")

    system_marker = "## SYSTEM PROMPT"
    user_marker   = "## USER PROMPT"

    # Fall back to single-# markers for compatibility with stage 0 format
    if system_marker not in text:
        system_marker = "# SYSTEM PROMPT"
    if user_marker not in text:
        user_marker = "# USER PROMPT"

    if system_marker not in text or user_marker not in text:
        raise ValueError(
            f"Prompt file '{prompt_path}' must contain both a SYSTEM PROMPT "
            f"and a USER PROMPT marker."
        )

    system_prompt = text.split(user_marker)[0].replace(system_marker, "").strip()
    user_prompt   = text.split(user_marker)[1].strip()
    return system_prompt, user_prompt


# ---------------------------------------------------------------------------
# Slice facts paragraphs from stage 0 output
# ---------------------------------------------------------------------------

def get_facts_paragraphs(stage0: dict) -> list[dict]:
    """
    Extract the paragraphs that fall within the facts section span,
    as defined by section_index.facts in the stage 0 output.

    Returns a list of paragraph dicts (para_id, paragraph_number,
    text, section_path), ordered by para_id.
    """
    return stage0['facts']

# ---------------------------------------------------------------------------
# API call (stage 1: atomic fact extraction)
# ---------------------------------------------------------------------------

def call_api(
    fact_paragraphs: list[dict],
    system_prompt: str,
    user_prompt_template: str
) -> list[dict]:
    """
    Inject the facts paragraphs into the user prompt and call the Claude API.
    Returns the parsed JSON response list.
    """
    # The placeholder may appear as {{fact_paras}} or `{{fact_paras}}`
    # (backtick-wrapped in the prompt file). Try both forms.
    placeholder = "`{{fact_paras}}`"

    if placeholder not in user_prompt_template:
        raise ValueError(
            "User prompt template must contain a {{fact_paras}} placeholder."
        )

    # The prompt receives only the fields the LLM needs: para_id,
    # section_path, and text. paragraph_number is irrelevant to the LLM.
    llm_input = [
        {
            "para_id":      p["para_id"],
            "section_path": p["section_path"],
            "text":         p["text"]
        }
        for p in fact_paragraphs
    ]

    injected = json.dumps(llm_input, ensure_ascii=False, indent=2)

    # Replace whichever form is present (ticked form first to avoid
    # partial replacement leaving stray backticks)
    if placeholder in user_prompt_template:
        user_prompt = user_prompt_template.replace(placeholder, injected)

    client = anthropic.Anthropic(api_key=API_KEY, timeout=1200.0)

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

    return json.loads(response.content[0].text)


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------

def postprocess(
    raw_facts: list[dict],
    fact_paragraphs: list[dict]
) -> list[dict]:
    """
    Convert the LLM's raw output into the final facts list:

      - Rename text_resolved → text
      - Replace para_id with:
          source_paragraph: the printed ECtHR paragraph_number (int | null)
          section_path:     the section_path from the stage 0 paragraph
      - Drop para_id entirely (it was an internal stage 0 artefact)

    Also validates that every para_id referenced by the LLM exists in
    the facts paragraphs, and reports any orphaned or unknown references.
    """
    # Build lookup: para_id → paragraph dict
    para_lookup: dict[int, dict] = {p["para_id"]: p for p in fact_paragraphs}

    warnings: list[str] = []
    facts:    list[dict] = []

    for raw in raw_facts:
        fact_id       = raw.get("fact_id", "")
        text_resolved = raw.get("text_resolved", "")
        para_id       = raw.get("para_id")

        if para_id not in para_lookup:
            warnings.append(
                f"{fact_id}: para_id {para_id} not found in facts paragraphs — "
                f"skipping fact."
            )
            continue

        para = para_lookup[para_id]

        facts.append({
            "fact_id":          fact_id,
            "text":             text_resolved,
            "source_paragraph": para["source_paragraph"],   # printed ECtHR number or null
            "section_path":     para["section_path"]
        })

    return facts, warnings


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    stage0_json: str, 
    output_json: str, 
    temp_json: str, 
    system_prompt: str, 
    user_prompt_template: str
) -> None:
    
    stage0_path = Path(stage0_json)
    output_path = Path(output_json)
    temp_path   = Path(temp_json)

    if not stage0_path.exists():
        print(f"[ERROR] Stage 0 output not found: {stage0_path}", file=sys.stderr)
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path.parent.mkdir(parents=True, exist_ok=True)


    # ── Step 1: Load stage 0 output and slice fact paragraphs ─────────────────
    print(f"[1/3] Loading stage 0 output: {stage0_path.name}")
    with open(stage0_path, encoding="utf-8") as f:
        stage0 = json.load(f)

    fact_paragraphs = get_facts_paragraphs(stage0)
    print(f"      Total fact paragraphs in document: {len(stage0['facts'])}")

    # ── Step 2: API call ──────────────────────────────────────────────────────
    print(f"[2/3] Calling Claude API ({MODEL})...")
    if temp_path.exists():
        print(f"      Found existing LLM output at {temp_path}, loading...")
        with open(temp_path, "r", encoding="utf-8") as f:
            raw_facts = json.load(f)
    else:
        raw_facts = call_api(fact_paragraphs, system_prompt, user_prompt_template)

        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(raw_facts, f, ensure_ascii=False, indent=2)
        print(f"      Raw LLM output saved to: {temp_path}")
    print(f"      Raw facts returned: {len(raw_facts)}")

    # ── Step 3: Post-process ──────────────────────────────────────────────────
    print(f"[3/3] Post-processing...")
    facts, warnings = postprocess(raw_facts, fact_paragraphs)

    if warnings:
        print(f"\n      WARNINGS: {len(warnings)}")
        for w in warnings:
            print(f"        [WARN]  {w}")
    else:
        print(f"      No warnings.")

    print(f"\n      Facts extracted: {len(facts)}")

    # ── Save final output ─────────────────────────────────────────────────────
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(facts, f, ensure_ascii=False, indent=2)
    print(f"\n✓ Output written to: {output_path}")

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def case_paths(case_name: str) -> tuple[str, str]:
    return (
        f"../outputs/preprocessed/{case_name}.json",
        f"../outputs/atomic_facts/{case_name}.json",
        f"../temps/atomic_facts/{case_name}.json"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ECtHR atomic fact extraction pipeline (stage 1): "
                    "load stage 0 output → slice facts → LLM API → postprocess"
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