"""
pipeline_stage_fact_mapping.py

Article 11 atomic fact mapping pipeline.

Simulates a four-turn conversation:
    Turn 1 (user):      conclusion stage user prompt (reasoning text + questions)
    Turn 1 (assistant): conclusion stage raw LLM output (analysis + JSON)
    Turn 2 (user):      grounding stage user prompt
    Turn 2 (assistant): grounding stage raw LLM output (free-flowing text)
    Turn 3 (user):      mapping prompt + atomic facts

The model's response contains:
    - analysis: free-flowing three-list analysis with fact IDs and texts
    - results:  structured JSON with list1/list2/list3 keyed by element

Three output files:
    temp/<stem>_mapping_llm_raw.json   — raw LLM JSON for potential future stages
    output/<stem>_mapping_analysis.txt — free-flowing analysis for human inspection
    output/<stem>_mapping.json         — post-processed structured results

Usage:
    python pipeline_stage_fact_mapping.py <case_num>
    python pipeline_stage_fact_mapping.py --stage_0 path/to/case_N.json
                                          --conclusion_dir path/to/stage_2_conclusion/temp
                                          --grounding_dir  path/to/stage_3_fact_grounding/temp
                                          --output_dir     output/
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

API_KEY      = os.environ["ANTHROPIC_API_KEY"]
MODEL        = "claude-sonnet-4-6"
MAX_TOKENS   = 36000
TEMPERATURE  = 0.0
PROMPT_PATH  = "prompts/prompt_stage_fact_mapping.md"
CONCLUSION_PROMPT_PATH = "prompts/prompt_stage_conclusion.md"
FACT_GROUNDING_PROMPT_PATH = "prompts/prompt_stage_fact_grounding.md"
TEMP_DIR     = "temp"

VALID_ELEMENTS = [
    "scope",
    "interference",
    "prescribed_by_law",
    "legitimate_aim",
    "necessity",
    "positive_obligation",
]


# ---------------------------------------------------------------------------
# JSON schema for structured output
# ---------------------------------------------------------------------------

_ID_LIST = {"type": "array", "items": {"type": "string"}}

_ELEMENT_LISTS = {
    el: _ID_LIST for el in VALID_ELEMENTS
}

RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["analysis", "results"],
    "additionalProperties": False,
    "properties": {
        "analysis": {"type": "string"},
        "results": {
            "type": "object",
            "required": ["list1", "list2", "list3"],
            "additionalProperties": False,
            "properties": {
                "list1": {
                    "type": "object",
                    "required": VALID_ELEMENTS,
                    "additionalProperties": False,
                    "properties": _ELEMENT_LISTS,
                },
                "list2": {
                    "type": "object",
                    "required": VALID_ELEMENTS,
                    "additionalProperties": False,
                    "properties": _ELEMENT_LISTS,
                },
                "list3": _ID_LIST,
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Prompt loading helpers
# ---------------------------------------------------------------------------

def load_prompt(prompt_path: str) -> tuple[str, str]:
    text = Path(prompt_path).read_text(encoding="utf-8")
    if "# SYSTEM PROMPT" not in text or "# USER PROMPT" not in text:
        raise ValueError(f"Prompt file '{prompt_path}' must contain both section markers.")
    system_prompt = text.split("# USER PROMPT")[0].replace("# SYSTEM PROMPT", "").strip()
    system_prompt = system_prompt.replace("---", "").strip()
    user_prompt   = text.split("# USER PROMPT")[1].strip()
    return system_prompt, user_prompt


def strip_output_section(user_prompt: str) -> str:
    """Remove the output format section from a user prompt."""
    for marker in ["---\n\n## Output", "---\n## Output", "## Output"]:
        if marker in user_prompt:
            return user_prompt.split(marker)[0].strip()
    return user_prompt


# ---------------------------------------------------------------------------
# Extract Art. 11 reasoning text from stage 0 output
# ---------------------------------------------------------------------------

def get_reasoning_text(stage0: dict) -> str:
    paras = stage0["art11"]
    lines, last_path = [], None
    for p in paras:
        path = " > ".join(p.get("section_path", []))
        if path != last_path:
            if lines:
                lines.append("")
            lines.append(f"## {path}")
            last_path = path
        lines.append(p["text"])
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Format atomic facts
# ---------------------------------------------------------------------------

def format_atomic_facts(atomic_facts: list[dict]) -> str:
    """Format atomic facts as FXXX: text lines grouped by section."""
    lines, last_path = [], None
    for fact in atomic_facts:
        path = " > ".join(fact.get("section_path", []))
        if path != last_path:
            if lines:
                lines.append("")
            lines.append(f"## {path}")
            last_path = path
        lines.append(f"{fact['fact_id']}: {fact['text']}")
    # print("\n".join(lines))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# API call
# ---------------------------------------------------------------------------

def call_api(
    conclusion_user_prompt: str,
    conclusion_raw: str,
    grounding_user_prompt: str,
    grounding_raw: str,
    mapping_user_prompt: str,
    system_prompt: str,
) -> dict:
    """
    Four-turn message history:
        Turn 1 user:      conclusion prompt (reasoning text + questions, stripped of output section)
        Turn 1 assistant: conclusion raw LLM output (analysis + JSON)
        Turn 2 user:      grounding prompt
        Turn 2 assistant: grounding raw LLM output (free-flowing text)
        Turn 3 user:      mapping prompt + atomic facts
    """
    client   = anthropic.Anthropic(api_key=API_KEY, timeout=1200)
    messages = [
        {"role": "user",      "content": conclusion_user_prompt},
        {"role": "assistant", "content": conclusion_raw},
        {"role": "user",      "content": grounding_user_prompt},
        {"role": "assistant", "content": grounding_raw},
        {"role": "user",      "content": mapping_user_prompt},
    ]
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        system=system_prompt,
        messages=messages,
        output_config={"format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}},
    )
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise ValueError("No text block in API response.")
    return json.loads(text)


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------

def postprocess(results: dict, valid_fact_ids: set) -> tuple[dict, list[str]]:
    warnings: list[str] = []

    for list_name in ("list1", "list2"):
        lst = results.get(list_name, {})
        for el in VALID_ELEMENTS:
            facts = lst.get(el, [])
            unknown = [f for f in facts if f not in valid_fact_ids]
            if unknown:
                warnings.append(f"{list_name}.{el}: unknown fact IDs: {unknown}")
                lst[el] = [f for f in facts if f in valid_fact_ids]

    list3 = results.get("list3", [])
    unknown3 = [f for f in list3 if f not in valid_fact_ids]
    if unknown3:
        warnings.append(f"list3: unknown fact IDs: {unknown3}")
        results["list3"] = [f for f in list3 if f in valid_fact_ids]

    # Check subset constraints
    list2_all = {f for el in VALID_ELEMENTS for f in results.get("list2", {}).get(el, [])}
    list1_all = {f for el in VALID_ELEMENTS for f in results.get("list1", {}).get(el, [])}
    list3_set = set(results.get("list3", []))

    not_in_list1 = list2_all - list1_all
    if not_in_list1:
        warnings.append(f"list2 contains facts not in list1: {not_in_list1}")

    not_in_list2 = list3_set - list2_all
    if not_in_list2:
        warnings.append(f"list3 contains facts not in list2: {not_in_list2}")

    return results, warnings


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    stage0_json: str,
    atomic_facts_json: str,
    conclusion_analysis_txt: str,
    grounding_txt: str,
    results_json: str,
    analysis_txt: str,
    temp_json: str,
    conclusion_user_prompt_template: str,
    grounding_user_prompt: str,
    system_prompt: str,
    user_prompt_template: str
) -> None:
    stage0_path        = Path(stage0_json)
    atomic_facts_path  = Path(atomic_facts_json)
    conclusion_path    = Path(conclusion_analysis_txt)
    grounding_path     = Path(grounding_txt)
    results_path       = Path(results_json)
    analysis_path      = Path(analysis_txt)
    temp_path          = Path(temp_json)

    for p, name in [(stage0_path, "stage 0"), (atomic_facts_path, "atomic facts"),
                    (conclusion_path, "conclusion analysis"), (grounding_path, "grounding output")]:
        if not p.exists():
            print(f"[ERROR] {name} not found: {p}", file=sys.stderr)
            sys.exit(1)

    results_path.parent.mkdir(parents=True, exist_ok=True)
    analysis_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Load inputs ───────────────────────────────────────────────────
    print(f"[1/4] Loading inputs...")

    with open(stage0_path, encoding="utf-8") as f:
        stage0 = json.load(f)
    reasoning_text = get_reasoning_text(stage0)

    with open(atomic_facts_path, encoding="utf-8") as f:
        atomic_facts = json.load(f)
    valid_fact_ids   = {fact["fact_id"] for fact in atomic_facts}
    atomic_facts_txt = format_atomic_facts(atomic_facts)

    with open(conclusion_path, encoding="utf-8") as f:
        conclusion_analysis = f.read().strip()

    grounding_output = grounding_path.read_text(encoding="utf-8").strip()

    print(f"      Reasoning text    : {len(reasoning_text)} chars")
    print(f"      Atomic facts      : {len(atomic_facts)} facts")
    print(f"      Conclusion raw    : {len(conclusion_analysis)} chars")
    print(f"      Grounding raw     : {len(grounding_output)} chars")

    # ── Step 2: Build message history ─────────────────────────────────────────
    print(f"[2/4] Building message history...")

    # Conclusion stage prompts
    conclusion_user_prompt = conclusion_user_prompt_template.replace("`{reasoning_text}`", reasoning_text)

    # Mapping stage user prompt
    mapping_user_prompt = user_prompt_template.replace("`{atomic_facts}`", atomic_facts_txt)

    # ── Step 3: API call ──────────────────────────────────────────────────────
    print(f"[3/4] Calling Claude API ({MODEL})...")

    if not temp_path.exists():
        raw = call_api(
            conclusion_user_prompt,
            conclusion_analysis,
            grounding_user_prompt,
            grounding_output,
            mapping_user_prompt,
            system_prompt,
        )
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
        print(f"      Raw output saved to: {temp_path}")
    else:
        with open(temp_path, encoding="utf-8") as f:
            raw = json.load(f)
        print(f"      Raw output loaded from: {temp_path}")

    # ── Step 4: Split and post-process ────────────────────────────────────────
    print(f"[4/4] Splitting and post-processing...")

    analysis = raw.get("analysis", "")
    results  = raw.get("results", {})

    analysis_path.write_text(analysis, encoding="utf-8")
    print(f"      Analysis saved to: {analysis_path}")

    processed, warnings = postprocess(results, valid_fact_ids)
    if warnings:
        print(f"\n      WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"        [WARN] {w}")
    else:
        print("      No warnings.")

    # Summary
    for lst_name in ("list1", "list2"):
        counts = {el: len(processed.get(lst_name, {}).get(el, [])) for el in VALID_ELEMENTS}
        total  = sum(counts.values())
        print(f"      {lst_name}: {total} facts total — {counts}")
    print(f"      list3: {len(processed.get('list3', []))} facts")

    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(processed, f, ensure_ascii=False, indent=2)
    print(f"\n✓ Results written to: {results_path}")

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def case_paths(case_name: str) -> tuple[str, str]:
    return (
        f"../outputs/preprocessed/{case_name}.json",
        f"../outputs/atomic_facts/{case_name}.json",
        f"../outputs/conclusion_analysis/{case_name}.txt",
        f"../outputs/fact_grounding/{case_name}.txt",
        f"../outputs/fact_mapping_results/{case_name}.json",
        f"../outputs/fact_mapping_analysis/{case_name}.txt",
        f"../temps/fact_mapping/{case_name}.json"
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
    _, conclusion_user_prompt_template = load_prompt(CONCLUSION_PROMPT_PATH)
    _, grounding_user_prompt = load_prompt(FACT_GROUNDING_PROMPT_PATH)

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
            input_json, atomic_facts_json, conclusion_txt, grounding_txt, results_json, analysis_txt, temp_json = case_paths(case_name)
            try:
                run_pipeline(input_json, atomic_facts_json, conclusion_txt, grounding_txt, results_json, analysis_txt, temp_json, conclusion_user_prompt_template, grounding_user_prompt, system_prompt, user_prompt_template)
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
        input_json, atomic_facts_json, conclusion_txt, grounding_txt, results_json, analysis_txt, temp_json = case_paths(args.case_name)
        run_pipeline(input_json, atomic_facts_json, conclusion_txt, grounding_txt, results_json, analysis_txt, temp_json, conclusion_user_prompt_template, grounding_user_prompt, system_prompt, user_prompt_template)