import os

from vllm import LLM, SamplingParams
from vllm.sampling_params import StructuredOutputsParams

HF_MODELS_DIR = os.environ.get("HF_MODELS_DIR", os.path.expanduser("~/hf_models"))

_THINKING_SEPARATORS = [
    "assistantfinal",   # openai/gpt-oss
    "</think>",         # Qwen3, DeepSeek-R1, Llama-4 thinking variants
    "<channel|>",       # google/gemma-4
]


def load_model(model: str) -> tuple:
    model_path = os.path.join(HF_MODELS_DIR, model)
    tp_size    = int(os.environ.get("TENSOR_PARALLEL_SIZE", "1"))
    max_model_len = 65536
    llm = LLM(
        model=model_path,
        max_model_len=max_model_len,
        tensor_parallel_size=tp_size,
        gpu_memory_utilization=0.9,
        trust_remote_code=True,
        seed=0,
    )
    return llm, llm.get_tokenizer(), max_model_len


def run_inference(
    atomic_facts_text: str,
    system_prompt: str,
    user_prompt_template: str,
    response_schema: dict,
    model: str,
    max_tokens: int,
    temperature: float,
    model_state: tuple | None = None,
    hf_template_kwargs: dict | None = None,
) -> str:
    llm, tokenizer, max_model_len = model_state if model_state is not None else load_model(model)

    user_prompt = user_prompt_template.replace("{atomic_facts}", atomic_facts_text)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_prompt},
    ]
    prompt = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True,
        **(hf_template_kwargs or {}),
    )

    sampling_params = SamplingParams(
        temperature=temperature,
        max_tokens=max_model_len,
        top_p=1.0,
        repetition_penalty=1.1,
        structured_outputs=StructuredOutputsParams(json=response_schema),
    )

    outputs = llm.generate([prompt], sampling_params)
    return outputs[0].outputs[0].text


def extract_answer(text: str) -> str:
    for sep in _THINKING_SEPARATORS:
        if sep in text:
            after = text.split(sep, 1)[1]
            # Skip any non-JSON prefix (e.g. "assistantfinal JSON{..." → "{...")
            brace = after.find("{")
            return after[brace:].strip() if brace >= 0 else after.strip()
    return text
