"""Capability prompt overrides.

Tool prompts are represented as CapabilitySchema.description because that is
the text exposed to LLM function-calling. The wrapper keeps execution logic and
JSON Schema immutable while allowing the prompt text to be configured.
"""

from __future__ import annotations

from typing import Any

from .base import CapabilityBase, CapabilitySchema


class PromptOverrideCapability(CapabilityBase):
    """Wrap a capability and override only its LLM-facing description."""

    def __init__(self, capability: CapabilityBase, prompt: str) -> None:
        super().__init__()
        self._capability = capability
        self._prompt = prompt

    @property
    def name(self) -> str:
        return self._capability.name

    @property
    def description(self) -> str:
        return self._prompt

    @property
    def wrapped(self) -> CapabilityBase:
        return self._capability

    def set_prompt(self, prompt: str) -> None:
        self._prompt = prompt

    def get_schema(self) -> CapabilitySchema:
        schema = self._capability.get_schema()
        return CapabilitySchema(
            name=schema.name,
            description=self._prompt,
            parameters=schema.parameters,
            returns=schema.returns,
        )

    async def execute(self, **kwargs: Any) -> Any:
        return await self._capability.execute(**kwargs)

    def validate_input(self, **kwargs: Any) -> bool:
        return self._capability.validate_input(**kwargs)


def unwrap_capability(capability: CapabilityBase) -> CapabilityBase:
    """Return the underlying capability if it is prompt-wrapped."""

    if isinstance(capability, PromptOverrideCapability):
        return capability.wrapped
    return capability


def apply_prompt_override(
    capability_registry: Any,
    name: str,
    prompt: str,
) -> bool:
    """Apply a prompt override to one registered capability."""

    capability = capability_registry.get(name)
    if capability is None:
        return False

    if isinstance(capability, PromptOverrideCapability):
        capability.set_prompt(prompt)
    else:
        capability_registry.register_native(PromptOverrideCapability(capability, prompt))
    return True


def apply_prompt_overrides(
    capability_registry: Any,
    capability_defs: list[dict[str, Any]],
) -> list[str]:
    """Apply all `prompt` fields from capability config entries."""

    applied: list[str] = []
    for item in capability_defs:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        prompt = item.get("prompt")
        if not name or not isinstance(prompt, str) or not prompt.strip():
            continue
        if apply_prompt_override(capability_registry, str(name), prompt.strip()):
            applied.append(str(name))
    return applied
