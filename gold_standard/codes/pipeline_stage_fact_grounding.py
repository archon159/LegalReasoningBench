"""
pipeline_stage_fact_grounding.py

Article 11 factual grounding pipeline.

Simulates multi-turn conversation by injecting the conclusion stage
exchange as prior turns, then asks the grounding question as a new
user turn. The model's response is free-flowing text — no schema
enforcement. The full response is saved to temp/ for injection into
the mapping stage.

Multi-turn message history:
    Turn 1 (user):      conclusion stage user prompt (reasoning text + questions)
    Turn 1 (assistant): conclusion stage analysis text (from temp/)
    Turn 2 (user):      grounding prompt

Two output files:
    temp/<stem>_grounding_llm_raw.txt  — full model response, injected as
                                         assistant turn in mapping stage
    output/<stem>_grounding.txt        — same content, for human inspection

Usage:
    python pipeline_stage_fact_grounding.py <case_num>
    python pipeline_stage_fact_grounding.py --stage_0 output/case_118.json
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

API_KEY              = os.environ["ANTHROPIC_API_KEY"]
MODEL                = "claude-sonnet-4-6"
MAX_TOKENS           = 36000
TEMPERATURE          = 0.0
PROMPT_PATH          = "prompts/prompt_stage_fact_grounding.md"
CONCLUSION_PROMPT_PATH    = "prompts/prompt_stage_conclusion.md"
TEMP_DIR             = "temp"


# ---------------------------------------------------------------------------
# Prompt loading
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
    """
    Remove the output format specification from the conclusion stage
    user prompt. We only want the questions, not the JSON schema,
    since the assistant turn already contains the model's response.
    The output section starts at '## Output' or '---\n## Output'.
    """
    markers = ["---\n\n## Output", "---\n## Output", "## Output"]
    for marker in markers:
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
# API call
# ---------------------------------------------------------------------------

def call_api(
    conclusion_user_prompt: str,
    conclusion_analysis: str,
    grounding_user_prompt: str,
    system_prompt: str,
) -> str:
    """
    Constructs a two-turn message history simulating the multi-turn chat:
        Turn 1 user:      conclusion stage user prompt (questions + reasoning text)
        Turn 1 assistant: conclusion stage analysis (free-flowing text only)
        Turn 2 user:      grounding question

    Returns the full model response text.
    """
    client   = anthropic.Anthropic(api_key=API_KEY, timeout=1200)
    messages = [
        {"role": "user",      "content": conclusion_user_prompt},
        {"role": "assistant", "content": conclusion_analysis},
        {"role": "user",      "content": grounding_user_prompt},
    ]
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        system=system_prompt,
        messages=messages,
    )
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise ValueError("No text block in API response.")
    return text


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    stage0_json: str,
    conclusion_analysis_txt: str,
    output_txt: str,
    temp_txt: str,
    conclusion_user_prompt_template: str,
    system_prompt: str,
    grounding_user_prompt: str
) -> None:
    stage0_path      = Path(stage0_json)
    output_path      = Path(output_txt)
    temp_path        = Path(temp_txt)
    conclusion_path  = Path(conclusion_analysis_txt)

    if not stage0_path.exists():
        print(f"[ERROR] Stage 0 output not found: {stage0_path}", file=sys.stderr)
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path.parent.mkdir(parents=True, exist_ok=True)


    # ── Step 1: Load inputs ───────────────────────────────────────────────────
    print(f"[1/3] Loading inputs...")

    if not conclusion_path.exists():
        print(f"[ERROR] Conclusion analysis not found: {conclusion_path}", file=sys.stderr)
        print(f"        Run pipeline_stage_conclusion.py first.", file=sys.stderr)
        sys.exit(1)

    with open(stage0_path, encoding="utf-8") as f:
        stage0 = json.load(f)
    reasoning_text = get_reasoning_text(stage0)

    with open(conclusion_path, encoding="utf-8") as f:
        conclusion_analysis = f.read().strip()

    if not conclusion_analysis:
        print("[ERROR] Conclusion analysis is empty.", file=sys.stderr)
        sys.exit(1)

    print(f"      Reasoning text    : {len(reasoning_text)} characters")
    print(f"      Conclusion analysis: {len(conclusion_analysis)} characters")

    # ── Step 2: Build prompts ─────────────────────────────────────────────────
    print(f"[2/3] Building message history...")

    conclusion_user_prompt_template = strip_output_section(conclusion_user_prompt_template)
    conclusion_user_prompt   = conclusion_user_prompt_template.replace("`{reasoning_text}`", reasoning_text)

    # ── Step 3: API call ──────────────────────────────────────────────────────
    print(f"[3/3] Calling Claude API ({MODEL})...")

    if not temp_path.exists():
        raw_text = call_api(
            conclusion_user_prompt,
            conclusion_analysis,
            grounding_user_prompt,
            system_prompt,
        )
        temp_path.write_text(raw_text, encoding="utf-8")
        print(f"      Raw output saved to: {temp_path}")
    else:
        raw_text = temp_path.read_text(encoding="utf-8")
        print(f"      Raw output loaded from: {temp_path}")

    # Save to output dir for human inspection
    output_path.write_text(raw_text, encoding="utf-8")
    print(f"\n✓ Grounding analysis written to: {output_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def case_paths(case_name: str) -> tuple[str, str]:
    return (
        f"../outputs/preprocessed/{case_name}.json",
        f"../outputs/conclusion_analysis/{case_name}.txt",
        f"../outputs/fact_grounding/{case_name}.txt",
        f"../temps/fact_grounding/{case_name}.txt"
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
            input_json, conclusion_txt, output_txt, temp_txt = case_paths(case_name)
            try:
                run_pipeline(input_json, conclusion_txt, output_txt, temp_txt,
                             conclusion_user_prompt_template, system_prompt, user_prompt_template)
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
        input_json, conclusion_txt, output_txt, temp_txt = case_paths(args.case_name)
        run_pipeline(input_json, conclusion_txt, output_txt, temp_txt, conclusion_user_prompt_template, system_prompt, user_prompt_template)