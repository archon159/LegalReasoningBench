import os

from google import genai
from google.genai import types


def _strip_unsupported(schema: dict) -> dict:
    """Recursively remove JSON Schema fields unsupported by Gemini."""
    UNSUPPORTED = {"additionalProperties"}
    out = {k: v for k, v in schema.items() if k not in UNSUPPORTED}
    if "properties" in out:
        out["properties"] = {k: _strip_unsupported(v) for k, v in out["properties"].items()}
    if "items" in out:
        out["items"] = _strip_unsupported(out["items"])
    return out


def run_inference(
    atomic_facts_text: str,
    system_prompt: str,
    user_prompt_template: str,
    response_schema: dict,
    model: str,
    max_tokens: int,
    temperature: float,
    provider_config: dict | None = None,
) -> str:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise EnvironmentError("GOOGLE_API_KEY is not set. Check secret.env.")

    user_prompt = user_prompt_template.replace("{atomic_facts}", atomic_facts_text)
    provider_config = provider_config or {}

    thinking_config = None
    thinking_level = provider_config.get("thinking_level")
    if thinking_level:
        thinking_config = types.ThinkingConfig(
            thinking_level=thinking_level,
        )

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=max_tokens,
            temperature=temperature,
            response_mime_type="application/json",
            response_schema=_strip_unsupported(response_schema),
            thinking_config=thinking_config,
        ),
    )
    candidate    = response.candidates[0] if response.candidates else None
    finish_reason = getattr(candidate, "finish_reason", "unknown") if candidate else "unknown"
    print(f"[Gemini] finish_reason={finish_reason}, output_chars={len(response.text or '')}")
    return response.text
