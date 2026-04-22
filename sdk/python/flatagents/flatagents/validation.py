"""
Schema validation for flatagent configurations.

Uses JSON Schema validation against the bundled schema.
Validation errors are warnings by default to avoid breaking user configs.
"""

import json
import warnings
from importlib.resources import files
from typing import Any, Dict, List, Optional

_ASSETS = files("flatagents.assets")


class ValidationWarning(UserWarning):
    """Warning for schema validation issues."""



def _load_schema(filename: str) -> Optional[Dict[str, Any]]:
    try:
        content = (_ASSETS / filename).read_text()
        return json.loads(content)
    except FileNotFoundError:
        return None


def _validate_with_jsonschema(config: Dict[str, Any], schema: Dict[str, Any]) -> List[str]:
    try:
        import jsonschema
    except ImportError:
        return []

    errors: List[str] = []
    validator = jsonschema.Draft7Validator(schema)
    for error in validator.iter_errors(config):
        path = ".".join(str(p) for p in error.absolute_path) or "(root)"
        errors.append(f"{path}: {error.message}")
    return errors


def _is_prompt_profile_bundle(config: Dict[str, Any]) -> bool:
    data = config.get("data") or {}
    return config.get("spec") == "flatagent" and isinstance(data, dict) and "prompt" in data and "profile" in data


def validate_flatagent_config(
    config: Dict[str, Any],
    warn: bool = True,
    strict: bool = False,
) -> List[str]:
    """Validate a flatagent configuration against the schema."""
    # Bundled prompt+profile configs are ahead of the generated asset schema.
    # Runtime validation treats them as valid and relies on runtime parsing.
    if _is_prompt_profile_bundle(config):
        return []

    schema = _load_schema("flatagent.schema.json")
    if schema is None:
        return []

    errors = _validate_with_jsonschema(config, schema)

    if errors:
        if strict:
            raise ValueError(
                "Flatagent config validation failed:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )
        if warn:
            warnings.warn(
                "Flatagent config has validation issues:\n"
                + "\n".join(f"  - {e}" for e in errors),
                ValidationWarning,
                stacklevel=3,
            )

    return errors


def get_flatagent_schema() -> Optional[Dict[str, Any]]:
    """Get the bundled flatagent JSON schema."""
    return _load_schema("flatagent.schema.json")


def get_asset(filename: str) -> str:
    """Get the contents of a bundled asset file."""
    return (_ASSETS / filename).read_text()
