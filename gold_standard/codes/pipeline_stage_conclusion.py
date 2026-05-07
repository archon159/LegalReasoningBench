"""
pipeline_stage_conclusion.py

Article 11 element conclusion identification pipeline.

The model produces a JSON object with two keys:
  - "analysis": free-flowing legal analysis (carries forward to next stages)
  - "results": minimal structured conclusions (for gold standard)

Three output files:
    temp/<stem>_conclusion_llm_raw.json  — raw LLM JSON (full response),
                                           injected as assistant turn in next stages
    output/<stem>_conclusion_analysis.txt — extracted analysis text for human inspection
    output/<stem>_conclusion.json         — post-processed results for gold standard

Usage:
    python pipeline_stage_conclusion.py <case_num>
    python pipeline_stage_conclusion.py --stage_0 output/case_118.json
                                        --output_dir output/
"""

import argparse
import json
import os
import sys
from pathlib import Path

import anthropic


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_KEY     = os.environ["ANTHROPIC_API_KEY"]
MODEL       = "claude-sonnet-4-6"
MAX_TOKENS  = 64000
EFFORT      = "medium"
PROMPT_PATH = "prompts/prompt_stage_conclusion.md"
TEMP_DIR    = "temp"
TEMPERATURE = 0.0

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

VALID_AIMS = [
    "national_security",
    "public_safety",
    "prevention_of_disorder",
    "prevention_of_crime",
    "protection_of_health",
    "protection_of_morals",
    "rights_of_others",
]

PARTY_FAVOURED = {
    "scope":                         {"yes": "pro_app",  "no": "pro_govt"},
    "scope_assembly_exists":         {"yes": "pro_app",  "no": "pro_govt"},
    "scope_participation":           {"yes": "pro_app",  "no": "pro_govt"},
    "scope_peaceful":                {"yes": "pro_app",  "no": "pro_govt"},
    "interference":                  {"yes": "pro_app",  "no": "pro_govt"},
    "prescribed_by_law":             {"yes": "pro_govt", "no": "pro_app"},
    "prescribed_by_law_foreseeable": {"yes": "pro_govt", "no": "pro_app"},
    "prescribed_by_law_accessible":  {"yes": "pro_govt", "no": "pro_app"},
    "prescribed_by_law_safeguards":  {"yes": "pro_govt", "no": "pro_app"},
    "legitimate_aim":                {"yes": "pro_govt", "no": "pro_app"},
    "necessity":                     {"yes": "pro_govt", "no": "pro_app"},
    "positive_obligation":           {"yes": "pro_app",  "no": "pro_govt"},
}


# ---------------------------------------------------------------------------
# JSON schema for structured output
# ---------------------------------------------------------------------------

_STR      = {"type": "string"}
_STR_LIST = {"type": "array", "items": {"type": "string"}}
_CONCL    = {"type": "string", "enum": ["yes", "no", "null"]}
_DISCUSS  = {"type": "string", "enum": ["explicit", "implied", "not_discussed"]}
_VIOLATED = {"type": "string", "enum": ["true", "false", "null"]}

_ELEMENT = {
    "type": "object",
    "required": ["conclusion", "discussed"],
    "additionalProperties": False,
    "properties": {
        "conclusion": _CONCL,
        "discussed":  _DISCUSS,
    },
}

_LEGITIMATE_AIM = {
    "type": "object",
    "required": ["conclusion", "discussed", "aims_found"],
    "additionalProperties": False,
    "properties": {
        "conclusion": _CONCL,
        "discussed":  _DISCUSS,
        "aims_found": _STR_LIST,
    },
}

RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["analysis", "results"],
    "additionalProperties": False,
    "properties": {
        "analysis": _STR,
        "results": {
            "type": "object",
            "required": ["violated", "elements"],
            "additionalProperties": False,
            "properties": {
                "violated": _VIOLATED,
                "elements": {
                    "type": "object",
                    "required": VALID_ELEMENTS,
                    "additionalProperties": False,
                    "properties": {
                        "scope":                         _ELEMENT,
                        "scope_assembly_exists":         _ELEMENT,
                        "scope_participation":           _ELEMENT,
                        "scope_peaceful":                _ELEMENT,
                        "interference":                  _ELEMENT,
                        "prescribed_by_law":             _ELEMENT,
                        "prescribed_by_law_foreseeable": _ELEMENT,
                        "prescribed_by_law_accessible":  _ELEMENT,
                        "prescribed_by_law_safeguards":  _ELEMENT,
                        "legitimate_aim":                _LEGITIMATE_AIM,
                        "necessity":                     _ELEMENT,
                        "positive_obligation":           _ELEMENT,
                    },
                },
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------

def load_prompt(prompt_path: str) -> tuple[str, str]:
    text = Path(prompt_path).read_text(encoding="utf-8")
    if "# SYSTEM PROMPT" not in text or "# USER PROMPT" not in text:
        raise ValueError("Prompt file must contain both section markers.")
    system_prompt = text.split("# USER PROMPT")[0].replace("# SYSTEM PROMPT", "").strip()
    system_prompt = system_prompt.replace("---", "").strip()
    user_prompt   = text.split("# USER PROMPT")[1].strip()
    return system_prompt, user_prompt


# ---------------------------------------------------------------------------
# Extract Art. 11 reasoning text from stage 0 output
# ---------------------------------------------------------------------------

def get_reasoning_text(stage0: dict) -> str:
    paras = stage0['art11']
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
# API call
# ---------------------------------------------------------------------------

def call_api(reasoning_text: str, system_prompt: str, user_prompt_template: str) -> dict:
    user_prompt = user_prompt_template.replace("`{reasoning_text}`", reasoning_text)
    client      = anthropic.Anthropic(api_key=API_KEY, timeout=1200)
    response    = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        # thinking={"type": "adaptive"},
        temperature=TEMPERATURE,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        output_config={
            # "effort": EFFORT,
            "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}
        }
    )
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise ValueError("No text block in API response.")
    return json.loads(text)


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------

def postprocess(results: dict) -> tuple[dict, list[str]]:
    warnings: list[str] = []

    # Normalise violated
    violated_str      = results.get("violated", "null")
    results["violated"] = (
        None if violated_str == "null"
        else violated_str == "true"
    )
    if results["violated"] is None:
        warnings.append("violated is null.")

    # Normalise elements
    elements = results.get("elements", {})
    for el in VALID_ELEMENTS:
        entry = elements.get(el, {})

        # Normalise conclusion
        c = entry.get("conclusion", "null")
        entry["conclusion"] = None if c == "null" else c

        # Validate aims_found for legitimate_aim
        if el == "legitimate_aim":
            aims = entry.get("aims_found", [])
            entry["aims_found"] = [a for a in aims if a in VALID_AIMS]
            invalid = [a for a in aims if a not in VALID_AIMS]
            if invalid:
                warnings.append(f"legitimate_aim: unknown aims filtered out: {invalid}")

        # Derive party_favoured
        conclusion = entry.get("conclusion")
        discussed  = entry.get("discussed", "not_discussed")
        if discussed != "not_discussed" and conclusion not in ("yes", "no"):
            warnings.append(f"{el}: discussed but conclusion is null.")
        entry["party_favoured"] = (
            PARTY_FAVOURED[el].get(conclusion) if conclusion in ("yes", "no") else None
        )

    return results, warnings


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    stage0_json: str, 
    results_json: str, 
    analysis_txt: str,
    temp_json: str, 
    system_prompt: str, 
    user_prompt_template: str
) -> None:
    
    stage0_path  = Path(stage0_json)
    results_path = Path(results_json)
    analysis_path = Path(analysis_txt)
    temp_path    = Path(temp_json)

    if not stage0_path.exists():
        print(f"[ERROR] Stage 0 output not found: {stage0_path}", file=sys.stderr)
        sys.exit(1)

    results_path.parent.mkdir(parents=True, exist_ok=True)
    analysis_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Load stage 0 ─────────────────────────────────────────────────
    print(f"[1/3] Loading stage 0 output: {stage0_path.name}")
    with open(stage0_path, encoding="utf-8") as f:
        stage0 = json.load(f)
    reasoning_text = get_reasoning_text(stage0)
    print(f"      Reasoning text: {len(reasoning_text)} characters")

    # ── Step 2: API call ──────────────────────────────────────────────────────
    print(f"[2/3] Calling Claude API ({MODEL})...")

    if not temp_path.exists():
        raw = call_api(reasoning_text, system_prompt, user_prompt_template)
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
        print(f"      Raw LLM output saved to: {temp_path}")
    else:
        with open(temp_path, encoding="utf-8") as f:
            raw = json.load(f)
        print(f"      Raw LLM output loaded from: {temp_path}")

    # ── Step 3: Split and post-process ────────────────────────────────────────
    print(f"[3/3] Splitting and post-processing...")

    analysis = raw.get("analysis", "")
    results  = raw.get("results", {})

    # Save analysis as plain text
    analysis_path.write_text(analysis, encoding="utf-8")
    print(f"      Analysis saved to: {analysis_path}")

    # Post-process results
    processed_results, warnings = postprocess(results)
    if warnings:
        print(f"\n      WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"        [WARN] {w}")
    else:
        print("      No warnings.")

    active = [
        el for el in VALID_ELEMENTS
        if processed_results.get("elements", {}).get(el, {}).get("discussed", "not_discussed") != "not_discussed"
    ]
    print(f"\n      violated : {processed_results.get('violated')}")
    print(f"      active   : {active}")

    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(processed_results, f, ensure_ascii=False, indent=2)
    print(f"\n✓ Results written to: {results_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def case_paths(case_name: str) -> tuple[str, str]:
    return (
        f"../outputs/preprocessed/{case_name}.json",
        f"../outputs/conclusion_results/{case_name}.json",
        f"../outputs/conclusion_analysis/{case_name}.txt",
        f"../temps/conclusion/{case_name}.json"
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
            input_json, results_json, analysis_txt, temp_json = case_paths(case_name)
            try:
                run_pipeline(input_json, results_json, analysis_txt, temp_json,
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
        input_json, results_json, analysis_txt, temp_json = case_paths(args.case_name)
        run_pipeline(input_json, results_json, analysis_txt, temp_json, system_prompt, user_prompt_template)