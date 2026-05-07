import os

import openai as _openai_sdk


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
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY is not set. Check secret.env.")

    user_prompt = user_prompt_template.replace("{atomic_facts}", atomic_facts_text)
    provider_config = provider_config or {}

    kwargs = dict(
        model=model,
        max_completion_tokens=max_tokens,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name":   "evaluation_response",
                "schema": response_schema,
                "strict": True,
            },
        },
    )

    reasoning_effort = provider_config.get("reasoning_effort")
    if reasoning_effort and reasoning_effort != "none":
        kwargs["reasoning_effort"] = reasoning_effort

    client = _openai_sdk.OpenAI(api_key=api_key)
    response = client.chat.completions.create(**kwargs)
    choice  = response.choices[0]
    print(f"[OpenAI] finish_reason={choice.finish_reason}, "
          f"content_len={len(choice.message.content or '')}")
    return choice.message.content or ""
