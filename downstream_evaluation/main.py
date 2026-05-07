"""
main.py

Unified evaluation pipeline for Article 11 ECtHR cases.
Dispatches by --eval_prompt to one of three sub-pipelines:

    direct_violation, direct_conclusion_violation
        Single-turn inference, no fact mapping.
        Output: {"violated": bool}                                      (direct_violation)
                {"elements": {el: {"conclusion": ..., "facts": []}},
                 "violated": bool}                                      (direct_conclusion_violation)

    staging
        Two-turn inference using staging_turn1.md + staging_turn2.md.
        Turn 1 produces fact mappings, Turn 2 produces conclusions.
        Output: {"elements": {el: {"conclusion": ..., "facts": [...]}},
                 "violated": bool}

    anything else (vanilla*, etc.)
        Single-turn inference with full fact mapping per element.
        Output: {"elements": {el: {"conclusion": ..., "facts": [...]}},
                 "violated": bool}

Usage:
    python main.py --case_number 118
    python main.py --case_number 118 --model gemini-3-flash-preview --eval_prompt direct_violation --thinking_level minimal
    python main.py --batch_file batches/included_case_names.txt --model claude-sonnet-4-6 --eval_prompt staging --thinking_type disabled
"""

import argparse
import json
import os
import sys
from pathlib import Path

from utils import get_provider_for_model
from utils.retry import with_retry
from utils.staging import run_staging


# ---------------------------------------------------------------------------
# Common utilities
# ---------------------------------------------------------------------------

def load_env(env_path: str = "secret.env") -> None:
    path = Path(env_path)
    if not path.exists():
        print(f"[WARN] {env_path} not found — relying on existing environment variables.", file=sys.stderr)
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def format_atomic_facts(atomic_facts: list[dict]) -> str:
    return "\n".join(
        f"{f.get('fact_id', '')}: {f.get('text', '')}"
        for f in atomic_facts
    )


def load_prompt(prompt_path: str) -> tuple[str, str]:
    text = Path(prompt_path).read_text(encoding="utf-8")
    system_marker = "# SYSTEM PROMPT"
    user_marker   = "# USER PROMPT"
    if system_marker not in text or user_marker not in text:
        raise ValueError(
            f"Prompt file '{prompt_path}' must contain both "
            f"'# SYSTEM PROMPT' and '# USER PROMPT' markers."
        )
    system_prompt = text.split(user_marker)[0].replace(system_marker, "").strip()
    system_prompt = system_prompt.replace("---", "").strip()
    user_prompt   = text.split(user_marker)[1].strip()
    return system_prompt, user_prompt


def load_staging_prompts(prompt_dir: str) -> tuple[str, str, str]:
    """
    Returns (system_prompt, turn1_user_template, turn2_user).
    turn1_user_template contains {atomic_facts} placeholder.
    """
    def _load(path):
        text = Path(path).read_text(encoding="utf-8")
        sys_part = text.split("# USER PROMPT")[0].replace("# SYSTEM PROMPT", "").replace("---", "").strip()
        user_raw = text.split("# USER PROMPT", 1)[1]
        lines = user_raw.splitlines()
        if lines and not lines[0].strip().startswith(("You", "-", "*", "\n")):
            user_raw = "\n".join(lines[1:])
        return sys_part, user_raw.strip()

    sys1, turn1_user = _load(Path(prompt_dir) / "staging_turn1.md")
    _,    turn2_user = _load(Path(prompt_dir) / "staging_turn2.md")
    return sys1, turn1_user, turn2_user


VALID_ELEMENTS = [
    "scope",
    "interference",
    "prescribed_by_law",
    "legitimate_aim",
    "necessity",
    "positive_obligation",
]


# ---------------------------------------------------------------------------
# Schemas — vanilla
# ---------------------------------------------------------------------------

ELEMENT_SCHEMA = {
    "type": "object",
    "required": ["conclusion", "facts"],
    "properties": {
        "conclusion": {"type": "string", "enum": ["yes", "no"]},
        "facts":      {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}

RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["elements", "violated"],
    "properties": {
        "elements": {
            "type": "object",
            "required": VALID_ELEMENTS,
            "properties": {el: ELEMENT_SCHEMA for el in VALID_ELEMENTS},
            "additionalProperties": False,
        },
        "violated": {"type": "boolean"},
    },
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Schemas — direct
# ---------------------------------------------------------------------------

DIRECT_VIOLATION_SCHEMA = {
    "type": "object",
    "required": ["violated"],
    "properties": {"violated": {"type": "boolean"}},
    "additionalProperties": False,
}

_CONCLUSION_ONLY_ELEMENT = {
    "type": "object",
    "required": ["conclusion"],
    "properties": {"conclusion": {"type": "string", "enum": ["yes", "no"]}},
    "additionalProperties": False,
}
DIRECT_CONCLUSION_SCHEMA = {
    "type": "object",
    "required": ["elements", "violated"],
    "properties": {
        "elements": {
            "type": "object",
            "required": VALID_ELEMENTS,
            "properties": {el: _CONCLUSION_ONLY_ELEMENT for el in VALID_ELEMENTS},
            "additionalProperties": False,
        },
        "violated": {"type": "boolean"},
    },
    "additionalProperties": False,
}


def get_schema(eval_prompt: str) -> dict:
    if eval_prompt == "direct_violation":
        return DIRECT_VIOLATION_SCHEMA
    return DIRECT_CONCLUSION_SCHEMA


# ---------------------------------------------------------------------------
# Schemas — staging
# ---------------------------------------------------------------------------

_FACT_LIST = {"type": "array", "items": {"type": "string"}}

TURN1_ELEMENT_SCHEMA = {
    "type": "object",
    "required": ["facts"],
    "properties": {"facts": _FACT_LIST},
    "additionalProperties": False,
}
TURN1_RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["elements"],
    "properties": {
        "elements": {
            "type": "object",
            "required": VALID_ELEMENTS,
            "properties": {el: TURN1_ELEMENT_SCHEMA for el in VALID_ELEMENTS},
            "additionalProperties": False,
        }
    },
    "additionalProperties": False,
}

TURN2_ELEMENT_SCHEMA = {
    "type": "object",
    "required": ["conclusion"],
    "properties": {"conclusion": {"type": "string", "enum": ["yes", "no"]}},
    "additionalProperties": False,
}
TURN2_RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["elements", "violated"],
    "properties": {
        "elements": {
            "type": "object",
            "required": VALID_ELEMENTS,
            "properties": {el: TURN2_ELEMENT_SCHEMA for el in VALID_ELEMENTS},
            "additionalProperties": False,
        },
        "violated": {"type": "boolean"},
    },
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Vanilla pipeline
# ---------------------------------------------------------------------------

def postprocess(
    raw: dict,
    atomic_facts: list[dict],
) -> tuple[dict, list[str]]:
    warnings: list[str] = []

    fact_lookup    = {f["fact_id"]: f["text"] for f in atomic_facts}
    valid_fact_ids = set(fact_lookup.keys())

    elements_out = {}
    for el in VALID_ELEMENTS:
        el_data    = raw.get("elements", {}).get(el, {})
        conclusion = el_data.get("conclusion")
        fact_ids   = el_data.get("facts", [])

        if conclusion not in ("yes", "no"):
            warnings.append(f"{el}: invalid conclusion value '{conclusion}'")

        unknown = [fid for fid in fact_ids if fid not in valid_fact_ids]
        if unknown:
            warnings.append(f"{el}: unknown fact ID(s): {unknown}")

        enriched_facts = [
            {"fact_id": fid, "fact_text": fact_lookup.get(fid, "")}
            for fid in fact_ids
            if fid in valid_fact_ids
        ]

        elements_out[el] = {
            "conclusion": conclusion,
            "facts":      enriched_facts,
        }

    return {"elements": elements_out, "violated": raw.get("violated")}, warnings


def run_pipeline_vanilla(
    atomic_facts_json: str,
    output_json: str,
    provider_name: str,
    provider: object,
    model: str,
    prompt_path: str,
    max_tokens: int,
    temperature: float,
    force_inference: bool = False,
    model_state=None,
    hf_template_kwargs: dict | None = None,
    provider_config: dict | None = None,
) -> None:
    atomic_facts_path = Path(atomic_facts_json)
    output_path       = Path(output_json)
    output_dir        = output_path.parent

    if not atomic_facts_path.exists():
        print(f"[ERROR] Atomic facts file not found: {atomic_facts_path}", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    stem         = atomic_facts_path.stem
    llm_raw_path = output_dir / f"{stem}_llm_raw"

    # ── Step 1: Load inputs ───────────────────────────────────────────────────
    print(f"[1/3] Loading inputs...")
    with open(atomic_facts_path, encoding="utf-8") as f:
        atomic_facts = json.load(f)

    if not atomic_facts:
        print("[ERROR] Atomic facts file is empty.", file=sys.stderr)
        sys.exit(1)

    print(f"      Atomic facts: {len(atomic_facts)}")

    # ── Step 2: Format and call API ───────────────────────────────────────────
    print(f"[2/3] Calling {provider_name} ({model})...")

    system_prompt, user_prompt_template = load_prompt(prompt_path)
    atomic_facts_text = format_atomic_facts(atomic_facts)

    if not llm_raw_path.exists() or force_inference:
        inference_args = (
            atomic_facts_text, system_prompt, user_prompt_template,
            RESPONSE_SCHEMA, model, max_tokens, temperature,
        )
        if provider_name == "huggingface":
            raw_text = provider.run_inference(
                *inference_args,
                model_state=model_state,
                hf_template_kwargs=hf_template_kwargs or {},
            )
        else:
            raw_text = with_retry(
                provider.run_inference,
                *inference_args,
                provider_config=provider_config or {},
            )
        with open(llm_raw_path, "w", encoding="utf-8") as f:
            f.write(raw_text)
        print(f"      Raw LLM output saved to: {llm_raw_path}")
    else:
        with open(llm_raw_path, encoding="utf-8") as f:
            raw_text = f.read()
        print(f"      Raw LLM output loaded from: {llm_raw_path}")

    parse_text = provider.extract_answer(raw_text) if hasattr(provider, "extract_answer") else raw_text
    raw = json.loads(parse_text)

    # ── Step 3: Post-process ──────────────────────────────────────────────────
    print(f"[3/3] Post-processing...")
    result, warnings = postprocess(raw, atomic_facts)

    if warnings:
        print(f"\n      WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"        [WARN] {w}")
    else:
        print(f"      No warnings.")

    print(f"\n      Final conclusion — violated: {result['violated']}")
    for el, data in result["elements"].items():
        n = len(data["facts"])
        print(f"      [{el}] conclusion={data['conclusion']}, {n} fact(s)")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n✓ Output written to: {output_path}")


# ---------------------------------------------------------------------------
# Direct pipeline
# ---------------------------------------------------------------------------

def build_result(raw: dict, eval_prompt: str) -> dict:
    """Convert raw model output to the final case JSON."""
    violated = raw.get("violated")
    if eval_prompt == "direct_violation":
        return {"violated": violated}

    # direct_conclusion_* : elements with conclusions, empty facts
    elements_out = {}
    for el in VALID_ELEMENTS:
        conclusion = raw.get("elements", {}).get(el, {}).get("conclusion")
        elements_out[el] = {"conclusion": conclusion, "facts": []}
    return {"elements": elements_out, "violated": violated}


def run_pipeline_direct(
    atomic_facts_json: str,
    output_json: str,
    provider_name: str,
    provider: object,
    model: str,
    prompt_path: str,
    eval_prompt: str,
    max_tokens: int,
    temperature: float,
    force_inference: bool = False,
    model_state=None,
    hf_template_kwargs: dict | None = None,
    provider_config: dict | None = None,
) -> None:
    atomic_facts_path = Path(atomic_facts_json)
    output_path       = Path(output_json)
    output_dir        = output_path.parent

    if not atomic_facts_path.exists():
        print(f"[ERROR] Atomic facts not found: {atomic_facts_path}", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)
    llm_raw_path = output_dir / f"{atomic_facts_path.stem}_llm_raw"

    print(f"[1/3] Loading inputs...")
    atomic_facts = json.loads(atomic_facts_path.read_text(encoding="utf-8"))
    if not atomic_facts:
        print("[ERROR] Atomic facts file is empty.", file=sys.stderr)
        sys.exit(1)
    print(f"      Atomic facts: {len(atomic_facts)}")

    print(f"[2/3] Calling {provider_name} ({model})...")
    system_prompt, user_prompt_template = load_prompt(prompt_path)
    atomic_facts_text = format_atomic_facts(atomic_facts)
    schema = get_schema(eval_prompt)

    if not llm_raw_path.exists() or force_inference:
        inference_args = (
            atomic_facts_text, system_prompt, user_prompt_template,
            schema, model, max_tokens, temperature,
        )
        if provider_name == "huggingface":
            raw_text = provider.run_inference(
                *inference_args,
                model_state=model_state,
                hf_template_kwargs=hf_template_kwargs or {},
            )
        else:
            raw_text = with_retry(
                provider.run_inference, *inference_args,
                provider_config=provider_config or {},
            )
        llm_raw_path.write_text(raw_text, encoding="utf-8")
        print(f"      Raw LLM output saved to: {llm_raw_path}")
    else:
        raw_text = llm_raw_path.read_text(encoding="utf-8")
        print(f"      Raw LLM output loaded from: {llm_raw_path}")

    parse_text = provider.extract_answer(raw_text) if hasattr(provider, "extract_answer") else raw_text
    raw = json.loads(parse_text)

    print(f"[3/3] Building result...")
    result = build_result(raw, eval_prompt)
    print(f"      violated: {result['violated']}")

    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✓ Output written: {output_path}")


# ---------------------------------------------------------------------------
# Staging pipeline
# ---------------------------------------------------------------------------

def postprocess_staging(
    turn1_data: dict,
    turn2_data: dict,
    atomic_facts: list[dict],
) -> tuple[dict, list[str]]:
    """Merge turn1 (facts) + turn2 (conclusions) and enrich fact IDs with text."""
    warnings: list[str] = []
    fact_lookup = {f["fact_id"]: f["text"] for f in atomic_facts}
    valid_ids   = set(fact_lookup.keys())

    elements_out = {}
    for el in VALID_ELEMENTS:
        conclusion = turn2_data.get("elements", {}).get(el, {}).get("conclusion")
        fact_ids   = turn1_data.get("elements", {}).get(el, {}).get("facts", [])

        if conclusion not in ("yes", "no"):
            warnings.append(f"{el}: invalid conclusion '{conclusion}'")

        unknown = [f for f in fact_ids if f not in valid_ids]
        if unknown:
            warnings.append(f"{el}: unknown fact IDs {unknown}")

        elements_out[el] = {
            "conclusion": conclusion,
            "facts": [
                {"fact_id": fid, "fact_text": fact_lookup.get(fid, "")}
                for fid in fact_ids
                if fid in valid_ids
            ],
        }

    return {"elements": elements_out, "violated": turn2_data.get("violated")}, warnings


def run_case_staging(
    stem: str,
    output_dir: Path,
    atomic_fact_dir: str,
    system_prompt: str,
    turn1_user_template: str,
    turn2_user: str,
    provider_name: str,
    model: str,
    max_tokens: int,
    temperature: float,
    force_inference: bool,
    provider_config: dict,
    model_state,
    hf_template_kwargs: dict,
) -> None:
    af_path = Path(atomic_fact_dir) / f"{stem}.json"
    if not af_path.exists():
        print(f"[ERROR] Atomic facts not found: {af_path}", file=sys.stderr)
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    stage1_path = output_dir / f"{stem}_stage1_llm_raw"
    stage2_path = output_dir / f"{stem}_stage2_llm_raw"
    result_path = output_dir / f"{stem}.json"

    # ── Load atomic facts ─────────────────────────────────────────────────────
    atomic_facts = json.loads(af_path.read_text(encoding="utf-8"))
    if not atomic_facts:
        print(f"[ERROR] Empty atomic facts: {af_path}", file=sys.stderr)
        return
    print(f"      Atomic facts: {len(atomic_facts)}")

    atomic_facts_text = format_atomic_facts(atomic_facts)
    turn1_user = turn1_user_template.replace("{atomic_facts}", atomic_facts_text)

    # ── Run / load staging inference ──────────────────────────────────────────
    need_run = force_inference or not stage1_path.exists() or not stage2_path.exists()
    if need_run:
        print(f"      Calling {provider_name} ({model}) — 2 turns...")
        staging_kwargs = dict(
            provider_name=provider_name,
            system_prompt=system_prompt,
            turn1_user=turn1_user,
            turn2_user=turn2_user,
            turn1_schema=TURN1_RESPONSE_SCHEMA,
            turn2_schema=TURN2_RESPONSE_SCHEMA,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            provider_config=provider_config,
            model_state=model_state,
            hf_template_kwargs=hf_template_kwargs,
        )
        if provider_name == "huggingface":
            turn1_raw, turn2_raw = run_staging(**staging_kwargs)
        else:
            turn1_raw, turn2_raw = with_retry(run_staging, **staging_kwargs)

        stage1_path.write_text(turn1_raw, encoding="utf-8")
        stage2_path.write_text(turn2_raw, encoding="utf-8")
        print(f"      Stage 1 saved: {stage1_path}")
        print(f"      Stage 2 saved: {stage2_path}")
    else:
        turn1_raw = stage1_path.read_text(encoding="utf-8")
        turn2_raw = stage2_path.read_text(encoding="utf-8")
        print(f"      Loaded from cache.")

    # ── Parse outputs ─────────────────────────────────────────────────────────
    # For HF models, strip thinking prefix before parsing
    from utils.huggingface import extract_answer as _hf_extract
    parse1 = _hf_extract(turn1_raw) if provider_name == "huggingface" else turn1_raw
    parse2 = _hf_extract(turn2_raw) if provider_name == "huggingface" else turn2_raw

    turn1_data = json.loads(parse1)
    turn2_data = json.loads(parse2)

    # ── Postprocess ───────────────────────────────────────────────────────────
    result, warnings = postprocess_staging(turn1_data, turn2_data, atomic_facts)
    if warnings:
        for w in warnings:
            print(f"      [WARN] {w}")
    else:
        print(f"      No warnings.")

    print(f"      violated: {result['violated']}")
    for el, data in result["elements"].items():
        print(f"      [{el}] conclusion={data['conclusion']}, {len(data['facts'])} fact(s)")

    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✓ Output written: {result_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "ECtHR Art. 11 evaluation pipeline. Dispatches by --eval_prompt: "
            "direct_* → no fact mapping; staging → 2-turn; else → vanilla single-turn."
        )
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--case_number",
        help="Single case number (e.g. case_118)",
    )
    input_group.add_argument(
        "--batch_file",
        help="Path to a file listing case numbers, one per line (# for comments)",
    )
    parser.add_argument(
        "--model", default="claude-sonnet-4-6",
        help="Model to use — provider is inferred from prefix (default: claude-sonnet-4-6)",
    )
    parser.add_argument(
        "--max_tokens", type=int, default=8000,
        help="Max tokens for generation (default: 8000)",
    )
    parser.add_argument(
        "--temperature", type=float, default=0.0,
        help="Sampling temperature (default: 0.0)",
    )
    parser.add_argument(
        "--eval_prompt", default="vanilla",
        help=(
            "Prompt name. Loads <prompt_dir>/<eval_prompt>.md for vanilla/direct_*. "
            "For 'staging', loads staging_turn1.md + staging_turn2.md instead. "
            "(default: vanilla)"
        ),
    )
    parser.add_argument(
        "--atomic_fact_dir",
        default="../gold_standard/outputs/atomic_facts",
        help="Directory containing atomic facts JSON files",
    )
    parser.add_argument(
        "--output_dir", default="./outputs",
        help="Directory for evaluation output JSON files",
    )
    parser.add_argument(
        "--prompt_dir", default="evaluation_prompts",
        help="Directory containing evaluation prompt files (default: evaluation_prompts)",
    )
    parser.add_argument(
        "--force-inference", action="store_true",
        help="Ignore cached llm_raw file and re-run inference",
    )
    parser.add_argument(
        "--reasoning_effort", choices=["none", "low", "medium", "high", "xhigh"], default=None,
        help="Reasoning effort for models that support it (e.g. openai/gpt-oss-120b)",
    )
    parser.add_argument(
        "--enable_thinking", choices=["true", "false"], default=None,
        help="Enable/disable thinking mode for models that support it (e.g. Qwen3)",
    )
    parser.add_argument(
        "--thinking_type", default=None,
        help="Thinking type label for path (e.g. adaptive) → thinking_type_adaptive",
    )
    parser.add_argument(
        "--thinking_effort", default=None,
        help="Thinking effort for Claude (e.g. max) — combined with thinking_type in path",
    )
    parser.add_argument(
        "--thinking_level", default=None,
        help="Thinking level label for path (e.g. high) → thinking_level_high",
    )
    args = parser.parse_args()

    load_env()

    # ── Build model variant tag for path ──────────────────────────────────────
    if args.reasoning_effort:
        model_variant = f"reasoning_effort_{args.reasoning_effort}"
    elif args.enable_thinking is not None:
        model_variant = f"enable_thinking_{args.enable_thinking}"
    elif args.thinking_type is not None:
        model_variant = f"thinking_type_{args.thinking_type}"
        if args.thinking_effort is not None:
            model_variant += f"_effort_{args.thinking_effort}"
    elif args.thinking_level is not None:
        model_variant = f"thinking_level_{args.thinking_level}"
    else:
        model_variant = "default"

    # ── Build HF template kwargs ──────────────────────────────────────────────
    hf_template_kwargs: dict = {}
    if args.reasoning_effort:
        hf_template_kwargs["reasoning_effort"] = args.reasoning_effort
    if args.enable_thinking is not None:
        hf_template_kwargs["enable_thinking"] = args.enable_thinking == "true"

    # ── Build API provider config ─────────────────────────────────────────────
    provider_config: dict = {}
    if args.thinking_type is not None:
        provider_config["thinking_type"] = args.thinking_type
    if args.thinking_effort is not None:
        provider_config["thinking_effort"] = args.thinking_effort
    if args.thinking_level is not None:
        provider_config["thinking_level"] = args.thinking_level
    if args.reasoning_effort:
        provider_config["reasoning_effort"] = args.reasoning_effort

    # ── Collect case stems ────────────────────────────────────────────────────
    if args.batch_file:
        lines = Path(args.batch_file).read_text(encoding="utf-8").splitlines()
        case_stems = [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]
    else:
        case_stems = [args.case_number]

    # ── Resolve provider once + pre-load HF model ─────────────────────────────
    provider_name, provider = get_provider_for_model(args.model)
    model_state = provider.load_model(args.model) if provider_name == "huggingface" else None

    eval_prompt = args.eval_prompt

    # ── Dispatch on eval_prompt ───────────────────────────────────────────────
    if eval_prompt == "staging":
        # ── Staging (2-turn) ──────────────────────────────────────────────────
        system_prompt, turn1_template, turn2_user = load_staging_prompts(args.prompt_dir)
        staging_dir = (
            Path(args.output_dir) / provider_name / args.model / model_variant / "staging"
        )
        for stem in case_stems:
            result_path = staging_dir / f"{stem}.json"
            if result_path.exists() and not args.force_inference:
                print(f"[SKIP] {stem}")
                continue

            print(f"\n{'='*60}\n{stem}\n{'='*60}")
            try:
                run_case_staging(
                    stem=stem,
                    output_dir=staging_dir,
                    atomic_fact_dir=args.atomic_fact_dir,
                    system_prompt=system_prompt,
                    turn1_user_template=turn1_template,
                    turn2_user=turn2_user,
                    provider_name=provider_name,
                    model=args.model,
                    max_tokens=args.max_tokens,
                    temperature=args.temperature,
                    force_inference=args.force_inference,
                    provider_config=provider_config,
                    model_state=model_state,
                    hf_template_kwargs=hf_template_kwargs,
                )
            except Exception as e:
                print(f"[ERROR] {stem} failed: {e}", file=sys.stderr)
                continue

    elif eval_prompt.startswith("direct_"):
        # ── Direct (single-turn, no fact mapping) ─────────────────────────────
        prompt_path = f"{args.prompt_dir}/{eval_prompt}.md"
        for stem in case_stems:
            output = str(
                Path(args.output_dir) / provider_name / args.model
                / model_variant / eval_prompt / f"{stem}.json"
            )
            if Path(output).exists() and not args.force_inference:
                print(f"[SKIP] {stem}")
                continue

            print(f"\n{'='*60}\n{stem}\n{'='*60}")
            try:
                run_pipeline_direct(
                    f"{args.atomic_fact_dir}/{stem}.json", output,
                    provider_name, provider,
                    args.model, prompt_path, eval_prompt,
                    args.max_tokens, args.temperature,
                    args.force_inference, model_state,
                    hf_template_kwargs, provider_config,
                )
            except Exception as e:
                print(f"[ERROR] {stem} failed: {e}", file=sys.stderr)
                continue

    else:
        # ── Vanilla (single-turn, full fact mapping) ──────────────────────────
        prompt_path = f"{args.prompt_dir}/{eval_prompt}.md"
        for stem in case_stems:
            output = str(
                Path(args.output_dir) / provider_name / args.model
                / model_variant / eval_prompt / f"{stem}.json"
            )
            if Path(output).exists() and not args.force_inference:
                print(f"[SKIP] {stem} — output already exists.")
                continue

            atomic_facts = f"{args.atomic_fact_dir}/{stem}.json"
            print(f"\n{'='*60}\n{stem}\n{'='*60}")
            try:
                run_pipeline_vanilla(
                    atomic_facts, output,
                    provider_name, provider,
                    args.model, prompt_path,
                    args.max_tokens, args.temperature,
                    args.force_inference, model_state,
                    hf_template_kwargs,
                    provider_config,
                )
            except Exception as e:
                print(f"[ERROR] {stem} failed: {e}", file=sys.stderr)
                continue
