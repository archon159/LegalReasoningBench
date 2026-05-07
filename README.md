# LegalReasoningBench

This is the **LegalReasoningBench** benchmark introduced in the paper
*"Can an LLM Reason Like a Lawyer?"* (NeurIPS 2026 submission). It provides
structured gold-standard annotations for European Court of Human Rights
(ECtHR) Article 11 (freedom of assembly) cases — covering case-level
conclusions, six doctrinal element conclusions, and fact-to-element mappings
(List 1 / List 2 / List 3).

The canonical, downstream-evaluation-ready gold standard is in
[`gold_standard/compiled_gold_standard/`](gold_standard/compiled_gold_standard).

## Repository structure

```
LegalReasoningBench/
├── secret.env.example
├── gold_standard/
│   ├── pdfs/                       1161 ECtHR judgment PDFs (renamed case_N.pdf)
│   ├── codes/                      pipeline + postprocess scripts, prompts
│   ├── outputs/                    intermediate per-stage outputs
│   └── compiled_gold_standard/     375 cases — FINAL canonical gold standard
└── downstream_evaluation/
    ├── main.py, evaluate.py        inference + per-case scoring
    ├── evaluation_prompts/         7 evaluation prompts
    ├── utils/                      provider routing + per-provider modules
    ├── outputs/                    model inference outputs
    └── eval_results/               per-case metric JSONs
```

## Requirements

Python 3.12. Versions used in our experiments are listed below. The two
sections can be installed into separate environments (as we did) or unioned
into one — every shared package uses the same version across both.

**`gold_standard/` pipeline:**

```
anthropic==0.97.0
pymupdf==1.27.2
scikit-learn==1.8.0
tqdm==4.67.3
numpy==2.2.6
```

**`downstream_evaluation/`:**

```
anthropic==0.97.0
openai==2.32.0
google-genai==1.73.1
scikit-learn==1.8.0
tqdm==4.67.3
vllm==0.19.1     # only needed for HuggingFace model inference (CUDA GPU)
```

## Setup

### API keys

The pipeline scripts read provider API keys from environment variables
(`ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `OPENAI_API_KEY`).

A template is provided at `secret.env.example`. To use it:

```bash
cp secret.env.example secret.env
# Edit secret.env and fill in your keys
```

`secret.env` is git-ignored, so your real keys will not be committed.

Before running any pipeline script, load the keys into your shell environment:

```bash
set -a
source secret.env
set +a
```

(`set -a` causes every variable assigned by `source` to be exported; `set +a`
turns that off afterwards.)

You can verify the variables are set with:

```bash
echo $ANTHROPIC_API_KEY
```

## Reproducing the gold standard pipeline

All scripts use paths relative to `gold_standard/codes/`, so **always `cd`
into that directory first**:

```bash
cd gold_standard/codes
```

The pipeline runs in three phases.

### Phase 1 — Pre-pipeline (manual, run once for all 1161 cases)

```bash
# Stage 0: PDF → raw text (PyMuPDF, no LLM)
python pipeline_stage_raw_text.py --batch ../all_case_names.txt

# Stage 1: inclusion criteria check (Claude → outputs/sample_selection/*.json)
python pipeline_stage_sample_selection.py --batch ../all_case_names.txt
```

After Stage 1, the `include=true` verdicts in
`../outputs/sample_selection/` were manually curated into
`../included_case_names.txt` (385 cases that passed the criteria).

### Phase 2 — Main pipeline (5 stages, orchestrated)

```bash
python run_full_pipeline.py --batch ../included_case_names.txt
```

This runs `preprocessing → atomic_facts → conclusion → fact_grounding →
fact_mapping` for each case. The orchestrator:

- Skips already-completed stages (resumable; use `--force` to re-run all).
- Skips downstream stages if a prior stage failed for a case.
- Writes per-case status to `../status/<case>.json` and per-stage logs to
  `../logs/<stage>/<case>.log`.
- Emits a summary report at `../logs/summary_<timestamp>.txt`.

`../included_all_case_names.txt` (375 cases) lists those for which all 5
stages succeeded.

### Phase 3 — Postprocess

```bash
# Merge per-stage outputs into a per-case gold standard JSON
python postprocess_compile_gold_standard.py --batch ../included_all_case_names.txt

# Apply the doctrinal dependency-chain rule to fill implicit conclusions
python postprocess_apply_dependency_chain.py
```

The first script writes `../outputs/explicit_gold_standard/`. The second
reads it and writes the canonical `../compiled_gold_standard/` (at the
`gold_standard/` root).

## Computing benchmark statistics

```bash
cd gold_standard/codes
python compute_benchmark_statistics.py
```

Reports case-level distributions, per-element conclusion stats, fact-list
sizes/compression ratios, and pipeline subset-constraint satisfaction
(`List 3 ⊆ List 2 ⊆ List 1`). Output is printed to stdout.

## Using the gold standard

Each `gold_standard/compiled_gold_standard/case_N.json` has the schema:

```json
{
  "case_name": "case_274",
  "conclusion": {
    "violated": true,
    "elements": {
      "scope":             {"conclusion": "yes", "discussed": "explicit"},
      "interference":      {"conclusion": "yes", "discussed": "explicit"},
      "prescribed_by_law": {"conclusion": "yes", "discussed": "implicit"},
      "legitimate_aim":    {"conclusion": "yes", "discussed": "explicit",
                            "aims": ["prevention_of_disorder", ...]},
      "necessity":         {"conclusion": "no",  "discussed": "explicit"},
      "positive_obligation": {"conclusion": null, "discussed": "not_discussed"}
    }
  },
  "fact_mapping": {
    "list1": {"scope": ["F003", "F012", ...], "interference": [...], ...},
    "list2": {"scope": [...], ...},
    "list3": ["F005", "F012", ...]
  }
}
```

- `conclusion.violated` — case-level Article 11 violation finding.
- `conclusion.elements[el].conclusion` — `"yes"` / `"no"` / `null` (not discussed).
- `conclusion.elements[el].discussed` — `"explicit"` / `"implied"` /
  `"implicit"` / `"not_discussed"`.
- `fact_mapping.listN` — fact IDs (`F<XXX>`) referencing
  `outputs/atomic_facts/case_N.json`. Subset constraint:
  `List 3 ⊆ List 2 ⊆ List 1`.

## Downstream evaluation

The `downstream_evaluation/` directory provides scripts for running LLM
inference on the 375 benchmark cases and scoring the outputs against the
gold standard.

### Workflow

```bash
cd downstream_evaluation

# 1. Inference — single (model, variant, eval_prompt) cell at a time
python main.py \
    --model claude-sonnet-4-6 \
    --thinking_type disabled \
    --eval_prompt vanilla_questions_chain \
    --batch_file batches/included_case_names.txt

# 2. Score the inference outputs against the gold standard
python evaluate.py \
    --model claude-sonnet-4-6 \
    --model_variant thinking_type_disabled \
    --eval_prompt vanilla_questions_chain
```

`main.py` dispatches internally based on `--eval_prompt`:

| eval_prompt | Pipeline | Output schema |
|---|---|---|
| `vanilla_questions_chain` / `vanilla_questions` / `vanilla_minimal` | single-turn, full fact mapping | `{elements: {el: {conclusion, facts}}, violated}` |
| `direct_violation` | single-turn, no fact mapping | `{violated}` |
| `direct_conclusion_violation` | single-turn, no fact mapping | `{elements: {el: {conclusion, facts: []}}, violated}` |
| `staging` | two-turn (Turn 1: facts, Turn 2: conclusions) | same as vanilla |

**Provider routing** is automatic via the model-name prefix
([`utils/__init__.py`](downstream_evaluation/utils/__init__.py)):
`claude-*` → Anthropic, `gpt-*` → OpenAI, `gemini-*` → Google,
`openai/`, `Qwen/`, `meta-llama/`, `google/gemma` → HuggingFace (vLLM).

`evaluate.py` reads inference outputs from
`outputs/{provider}/{model}/{variant}/{eval_prompt}/` and the gold standard
from `../gold_standard/compiled_gold_standard/`, then writes per-case metric
JSONs to `eval_results/` mirroring the same hierarchy.

### Experiments included in this release

The shipped `outputs/` and `eval_results/` cover the following 66 cells
(model × variant × eval_prompt). Each cell has 375 case JSONs.

**Basic experiment** — 10 (model, lowest-effort variant) × 6 prompts = 60 cells

| Family | Model | Variant |
|---|---|---|
| API (Anthropic) | `claude-sonnet-4-6` | `thinking_type_disabled` |
| API (OpenAI) | `gpt-5.4` | `reasoning_effort_none` |
| API (Google) | `gemini-3-flash-preview` | `thinking_level_minimal` |
| HF / OpenAI | `openai/gpt-oss-20b` | `reasoning_effort_low` |
| HF / OpenAI | `openai/gpt-oss-120b` | `reasoning_effort_low` |
| HF / Qwen | `Qwen/Qwen3.5-9B` | `enable_thinking_false` |
| HF / Qwen | `Qwen/Qwen3.5-35B-A3B` | `enable_thinking_false` |
| HF / Qwen | `Qwen/Qwen3.5-122B-A10B` | `enable_thinking_false` |
| HF / Google | `google/gemma-4-E4B-it` | `enable_thinking_false` |
| HF / Google | `google/gemma-4-31B-it` | `enable_thinking_false` |

Each of the 10 (model, variant) combinations is evaluated on all 6 prompts:
`vanilla_minimal`, `vanilla_questions`, `vanilla_questions_chain`, `staging`,
`direct_violation`, `direct_conclusion_violation`.

**Thinking experiment** — 6 (largest-model, highest-effort variant) × 1 prompt = 6 cells

| Family | Model | Variant |
|---|---|---|
| API (Anthropic) | `claude-sonnet-4-6` | `thinking_type_adaptive_effort_max` |
| API (OpenAI) | `gpt-5.4` | `reasoning_effort_xhigh` |
| API (Google) | `gemini-3-flash-preview` | `thinking_level_high` |
| HF / OpenAI | `openai/gpt-oss-120b` | `reasoning_effort_high` |
| HF / Qwen | `Qwen/Qwen3.5-122B-A10B` | `enable_thinking_true` |
| HF / Google | `google/gemma-4-31B-it` | `enable_thinking_true` |

All thinking-experiment cells use the single prompt `vanilla_questions_chain`.
The corresponding low-effort baselines for these largest models are already
covered by the basic experiment, enabling direct low-vs-high comparison
under the same prompt.

### HuggingFace models

For HuggingFace models (`openai/`, `Qwen/`, `meta-llama/`, `google/gemma*`),
[`utils/huggingface.py`](downstream_evaluation/utils/huggingface.py) loads
weights from a local directory via vLLM. By default it looks at `~/hf_models/`;
override with the `HF_MODELS_DIR` environment variable:

```bash
export HF_MODELS_DIR=/path/to/your/hf_models
```

Models are expected at `$HF_MODELS_DIR/<org>/<model_name>/`, matching
the `--model` argument exactly.
