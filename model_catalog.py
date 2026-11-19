"""Model aliases and OpenAI catalogue helpers."""


# Compatibility aliases for older bridge clients. They route to the closest
# currently available France Student agent and are documented as deprecated.
DEPRECATED_MODEL_ALIASES = {
    "gpt-5.5": "gpt-5.6-sol",
    "gpt-5.4": "gpt-5.6-luna",
    "gpt-5.4-mini": "gpt-5.6-luna",
    "gpt-5.4-nano": "gpt-5.6-luna",
    "claude-sonnet-4-6": "claude-sonnet-5",
    "claude-opus-4-8": "claude-opus-5",
    "claude-haiku-4-5": "claude-haiku-4-5",
}

IMAGE_MODEL_ALIASES = {
    "dall-e-2",
    "dall-e-3",
    "gpt-image-1",
    "gpt-image-1-mini",
    "image",
}


def canonical_model_name(value):
    if not isinstance(value, str):
        return value
    normalized = value.strip()
    return DEPRECATED_MODEL_ALIASES.get(normalized, normalized)


def resolve_agent(model_value, models):
    """Resolve an agent ID, model ID, display name or deprecated alias."""
    if isinstance(model_value, bool):
        return None
    if isinstance(model_value, int):
        return model_value
    if isinstance(model_value, str) and model_value.strip().lstrip("-").isdigit():
        return int(model_value.strip())

    requested = canonical_model_name(model_value)
    if not isinstance(requested, str):
        return None
    requested_lower = requested.lower()
    for model in models:
        candidates = {
            str(model.get("id", "")).lower(),
            str(model.get("name", "")).lower(),
            str(model.get("model", "")).lower(),
        }
        if requested_lower in candidates:
            return model["id"]
    return None


def default_agent(models):
    for model in models:
        if model.get("isDefault"):
            return model["id"]
    return models[0]["id"] if models else None


def openai_model_entry(model):
    canonical = model.get("model") or model.get("name")
    aliases = []
    if model.get("name") and model["name"] != canonical:
        aliases.append(model["name"])
    for alias, target in DEPRECATED_MODEL_ALIASES.items():
        if target == canonical:
            aliases.append(alias)
    return {
        "id": canonical,
        "object": "model",
        "created": 0,
        "owned_by": model.get("modelProvider", "unknown"),
        "fs_agent_id": model["id"],
        "fs_name": model.get("name"),
        "status": "active" if model.get("isActive") else "inactive",
        "aliases": aliases,
    }
