"""Reading a prompt template against the answer format it is answered in."""

import re

from pydantic import BaseModel

_GUIDED = re.compile(r"^- ([a-z_]+(?: / [a-z_]+)*):", re.MULTILINE)
_NAMED = re.compile(r"`([a-z_]+)`")


def named_fields(template: str) -> set[str]:
    """Every field a template's guidance names: a `- field:` bullet, or a field in backticks."""
    bullets = {name for match in _GUIDED.findall(template) for name in match.split(" / ")}
    return bullets | set(_NAMED.findall(template))


def schema_fields(schema: type[BaseModel]) -> set[str]:
    """Every field in `schema`, its nested formats' too: what the model can be told to fill."""
    spec = schema.model_json_schema()
    return set(spec["properties"]) | {
        name for nested in spec.get("$defs", {}).values() for name in nested["properties"]
    }
