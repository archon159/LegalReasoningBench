"""
utils/staging.py

Multi-turn staging inference for all providers.
Each function runs two consecutive turns and returns (turn1_raw_text, turn2_raw_text).
"""

import json
import os

from . import get_provider_for_model


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------

def _staging_anthropic(
    system_prompt: str,
    turn1_user: str,
    turn2_user: str,
    turn1_schema: dict,
    turn2_schema: dict,
    model: str,
    max_tokens: int,
    temperature: float,
    provider_config: dict,
) -> tuple[str, str]:
    import anthropic as _sdk

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set. Check secret.env.")

    client = _sdk.Anthropic(api_key=api_key)

    def _call(messages, schema):
        kwargs = dict(
            model=model, max_tokens=max_tokens, temperature=temperature,
            system=system_prompt, messages=messages,
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        thinking_type   = provider_config.get("thinking_type")
        thinking_effort = provider_config.get("thinking_effort")
        if thinking_type:
            kwargs["thinking"] = {"type": thinking_type}
        if thinking_effort:
            kwargs["output_config"]["effort"] = thinking_effort
        with client.messages.stream(**kwargs) as stream:
            message = stream.get_final_message()
        return next(b for b in message.content if b.type == "text").text

    turn1_raw = _call([{"role": "user", "content": turn1_user}], turn1_schema)
    turn2_raw = _call([
        {"role": "user",      "content": turn1_user},
        {"role": "assistant", "content": turn1_raw},
        {"role": "user",      "content": turn2_user},
    ], turn2_schema)

    return turn1_raw, turn2_raw


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

def _staging_openai(
    system_prompt: str,
    turn1_user: str,
    turn2_user: str,
    turn1_schema: dict,
    turn2_schema: dict,
    model: str,
    max_tokens: int,
    temperature: float,
    provider_config: dict,
) -> tuple[str, str]:
    import openai as _sdk

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY is not set. Check secret.env.")

    client = _sdk.OpenAI(api_key=api_key)
    sys_msg = {"role": "system", "content": system_prompt}

    def _call(messages, schema_name, schema):
        kwargs = dict(
            model=model, max_completion_tokens=max_tokens, temperature=temperature,
            messages=messages,
            response_format={"type": "json_schema", "json_schema": {
                "name": schema_name, "schema": schema, "strict": True,
            }},
        )
        reasoning_effort = provider_config.get("reasoning_effort")
        if reasoning_effort and reasoning_effort != "none":
            kwargs["reasoning_effort"] = reasoning_effort
        return client.chat.completions.create(**kwargs).choices[0].message.content

    turn1_raw = _call(
        [sys_msg, {"role": "user", "content": turn1_user}],
        "staging_turn1", turn1_schema,
    )
    turn2_raw = _call([
        sys_msg,
        {"role": "user",      "content": turn1_user},
        {"role": "assistant", "content": turn1_raw},
        {"role": "user",      "content": turn2_user},
    ], "staging_turn2", turn2_schema)

    return turn1_raw, turn2_raw


# ---------------------------------------------------------------------------
# Google
# ---------------------------------------------------------------------------

def _staging_google(
    system_prompt: str,
    turn1_user: str,
    turn2_user: str,
    turn1_schema: dict,
    turn2_schema: dict,
    model: str,
    max_tokens: int,
    temperature: float,
    provider_config: dict,
) -> tuple[str, str]:
    from google import genai
    from google.genai import types

    from .google import _strip_unsupported

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise EnvironmentError("GOOGLE_API_KEY is not set. Check secret.env.")

    client = genai.Client(api_key=api_key)

    def _base_config(schema):
        thinking_cfg = None
        level = provider_config.get("thinking_level")
        if level:
            thinking_cfg = types.ThinkingConfig(thinking_level=level)
        return types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=max_tokens,
            temperature=temperature,
            response_mime_type="application/json",
            response_schema=_strip_unsupported(schema),
            thinking_config=thinking_cfg,
        )

    def _content(role, text):
        return types.Content(role=role, parts=[types.Part(text=text)])

    # Turn 1
    resp1 = client.models.generate_content(
        model=model, contents=turn1_user, config=_base_config(turn1_schema),
    )
    turn1_raw = resp1.text

    # Turn 2 (multi-turn)
    contents2 = [
        _content("user",  turn1_user),
        _content("model", turn1_raw),
        _content("user",  turn2_user),
    ]
    resp2 = client.models.generate_content(
        model=model, contents=contents2, config=_base_config(turn2_schema),
    )
    turn2_raw = resp2.text

    return turn1_raw, turn2_raw


# ---------------------------------------------------------------------------
# HuggingFace
# ---------------------------------------------------------------------------

def _staging_huggingface(
    system_prompt: str,
    turn1_user: str,
    turn2_user: str,
    turn1_schema: dict,
    turn2_schema: dict,
    model: str,
    max_tokens: int,
    temperature: float,
    model_state: tuple,
    hf_template_kwargs: dict,
) -> tuple[str, str]:
    from vllm import SamplingParams
    from vllm.sampling_params import StructuredOutputsParams
    from .huggingface import extract_answer

    llm, tokenizer, max_model_len = model_state

    def _generate(messages, schema):
        prompt = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True,
            **hf_template_kwargs,
        )
        params = SamplingParams(
            temperature=temperature,
            max_tokens=max_model_len,
            top_p=1.0,
            repetition_penalty=1.1001,
            structured_outputs=StructuredOutputsParams(json=schema),
        )
        return llm.generate([prompt], params)[0].outputs[0].text

    t1_messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": turn1_user},
    ]
    turn1_raw = _generate(t1_messages, turn1_schema)

    # Use extracted (thinking-stripped) turn1 as assistant content in turn2
    turn1_clean = extract_answer(turn1_raw)

    t2_messages = [
        {"role": "system",    "content": system_prompt},
        {"role": "user",      "content": turn1_user},
        {"role": "assistant", "content": turn1_clean},
        {"role": "user",      "content": turn2_user},
    ]
    turn2_raw = _generate(t2_messages, turn2_schema)

    return turn1_raw, turn2_raw


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def run_staging(
    provider_name: str,
    system_prompt: str,
    turn1_user: str,
    turn2_user: str,
    turn1_schema: dict,
    turn2_schema: dict,
    model: str,
    max_tokens: int,
    temperature: float,
    provider_config: dict | None = None,
    model_state=None,
    hf_template_kwargs: dict | None = None,
) -> tuple[str, str]:
    provider_config = provider_config or {}
    hf_template_kwargs = hf_template_kwargs or {}

    common = dict(
        system_prompt=system_prompt,
        turn1_user=turn1_user,
        turn2_user=turn2_user,
        turn1_schema=turn1_schema,
        turn2_schema=turn2_schema,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    if provider_name == "anthropic":
        return _staging_anthropic(**common, provider_config=provider_config)
    if provider_name == "openai":
        return _staging_openai(**common, provider_config=provider_config)
    if provider_name == "google":
        return _staging_google(**common, provider_config=provider_config)
    if provider_name == "huggingface":
        return _staging_huggingface(
            **common,
            model_state=model_state,
            hf_template_kwargs=hf_template_kwargs,
        )
    raise ValueError(f"Staging not implemented for provider '{provider_name}'.")
