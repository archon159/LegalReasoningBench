import importlib

_PREFIX_TO_PROVIDER = {
    # Anthropic API
    "claude-":      "anthropic",
    # OpenAI API
    "gpt-":         "openai",
    "o1-":          "openai",
    "o3-":          "openai",
    "o4-":          "openai",
    # Google API
    "gemini-":      "google",
    # HuggingFace (org/repo format)
    "openai/":      "huggingface",
    "Qwen/":        "huggingface",
    "meta-llama/":  "huggingface",
    "google/gemma": "huggingface",   # distinct from "gemini-"
}

# Sort by prefix length descending for longest-prefix-match semantics
_SORTED_PREFIXES = sorted(_PREFIX_TO_PROVIDER.items(), key=lambda x: len(x[0]), reverse=True)


def get_provider_for_model(model: str) -> tuple[str, object]:
    for prefix, provider_name in _SORTED_PREFIXES:
        if model.startswith(prefix):
            return provider_name, importlib.import_module(f".{provider_name}", package=__name__)
    raise ValueError(
        f"Cannot infer provider for model '{model}'. "
        f"Add its prefix to _PREFIX_TO_PROVIDER in utils/__init__.py."
    )
