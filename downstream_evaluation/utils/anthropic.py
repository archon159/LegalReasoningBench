import os

import anthropic as _anthropic_sdk


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
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY is not set. Check secret.env.")

    user_prompt = user_prompt_template.replace("{atomic_facts}", atomic_facts_text)
    provider_config = provider_config or {}

    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        output_config={
            "format": {
                "type":   "json_schema",
                "schema": response_schema,
            }
        },
    )

    thinking_type   = provider_config.get("thinking_type")
    thinking_effort = provider_config.get("thinking_effort")
    if thinking_type:
        kwargs["thinking"] = {"type": thinking_type}
    if thinking_effort:
        kwargs["output_config"]["effort"] = thinking_effort

    client = _anthropic_sdk.Anthropic(api_key=api_key)
    with client.messages.stream(**kwargs) as stream:
        message = stream.get_final_message()
    return next(b for b in message.content if b.type == "text").text
