"""Runtime-configurable capabilities.

Dynamic tools provide a safe extension path for the project: users can add
small, deterministic tools through YAML/API without writing Python plugins or
restarting the service. Agents still see them as normal CapabilityBase tools.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .base import CapabilityBase, CapabilitySchema


DEFAULT_TEXT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "text": {
            "type": "string",
            "description": "Text to process",
        },
    },
    "required": ["text"],
}


class DynamicToolCapability(CapabilityBase):
    """A YAML/API defined tool with a small set of safe execution modes."""

    SUPPORTED_MODES = {"template", "checklist", "regex_extract"}

    def __init__(
        self,
        name: str,
        description: str = "",
        mode: str = "template",
        input_schema: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(config=config)
        if mode not in self.SUPPORTED_MODES:
            raise ValueError(f"Unsupported dynamic tool mode: {mode}")

        self._name = name
        self._description = description or f"Dynamic {mode} tool"
        self._mode = mode
        self._input_schema = input_schema or self._default_schema(mode)

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def mode(self) -> str:
        return self._mode

    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name=self.name,
            description=self.description,
            parameters=self._input_schema,
            returns="Structured dynamic tool result",
            is_read_only=True,
            is_concurrency_safe=True,
            max_result_size=8000,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        if self._mode == "template":
            return self._execute_template(kwargs)
        if self._mode == "checklist":
            return self._execute_checklist(kwargs)
        if self._mode == "regex_extract":
            return self._execute_regex_extract(kwargs)
        return {"error": f"Unsupported mode: {self._mode}"}

    @classmethod
    def from_config(cls, capability_def: Mapping[str, Any]) -> "DynamicToolCapability":
        mode = str(capability_def.get("mode") or capability_def.get("type") or "template")
        if mode == "dynamic":
            mode = "template"
        return cls(
            name=str(capability_def["name"]),
            description=str(capability_def.get("description", "")),
            mode=mode,
            input_schema=capability_def.get("input_schema"),
            config=dict(capability_def.get("config") or {}),
        )

    @staticmethod
    def _default_schema(mode: str) -> Dict[str, Any]:
        if mode == "template":
            return {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Primary text passed into the template",
                    }
                },
                "required": ["text"],
            }
        return dict(DEFAULT_TEXT_SCHEMA)

    def _execute_template(self, kwargs: Mapping[str, Any]) -> Dict[str, Any]:
        template = str(self.config.get("template") or "{{text}}")

        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            value = kwargs.get(key, "")
            if isinstance(value, (dict, list)):
                return str(value)
            return "" if value is None else str(value)

        rendered = re.sub(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}", replace, template)
        return {
            "mode": self._mode,
            "text": rendered,
            "inputs": dict(kwargs),
        }

    def _execute_checklist(self, kwargs: Mapping[str, Any]) -> Dict[str, Any]:
        text = self._read_text(kwargs)
        required_terms = self._string_list(self.config.get("required_terms"))
        forbidden_terms = self._string_list(self.config.get("forbidden_terms"))
        case_sensitive = bool(self.config.get("case_sensitive", False))

        haystack = text if case_sensitive else text.lower()

        def normalize(term: str) -> str:
            return term if case_sensitive else term.lower()

        matched_required = [
            term for term in required_terms if normalize(term) in haystack
        ]
        missing_required = [
            term for term in required_terms if term not in matched_required
        ]
        forbidden_hits = [
            term for term in forbidden_terms if normalize(term) in haystack
        ]

        denominator = max(1, len(required_terms) + len(forbidden_terms))
        passed_checks = len(matched_required) + len(forbidden_terms) - len(forbidden_hits)
        score = max(0.0, min(1.0, passed_checks / denominator))

        return {
            "mode": self._mode,
            "passed": not missing_required and not forbidden_hits,
            "score": round(score, 3),
            "matched_required": matched_required,
            "missing_required": missing_required,
            "forbidden_hits": forbidden_hits,
            "summary": {
                "required_total": len(required_terms),
                "forbidden_total": len(forbidden_terms),
                "checks_total": denominator,
            },
        }

    def _execute_regex_extract(self, kwargs: Mapping[str, Any]) -> Dict[str, Any]:
        text = self._read_text(kwargs)
        raw_patterns = self.config.get("patterns") or {}
        if not isinstance(raw_patterns, Mapping):
            return {"mode": self._mode, "error": "config.patterns must be an object"}

        flags = 0
        for item in self._string_list(self.config.get("flags")):
            flags |= getattr(re, item.upper(), 0)

        matches: Dict[str, Any] = {}
        errors: Dict[str, str] = {}
        for label, pattern in raw_patterns.items():
            try:
                compiled = re.compile(str(pattern), flags)
            except re.error as exc:
                errors[str(label)] = str(exc)
                continue

            label_matches: List[Any] = []
            for match in compiled.finditer(text):
                if match.groupdict():
                    label_matches.append(match.groupdict())
                elif match.groups():
                    label_matches.append(list(match.groups()))
                else:
                    label_matches.append(match.group(0))
            matches[str(label)] = label_matches

        return {
            "mode": self._mode,
            "matches": matches,
            "errors": errors,
            "summary": {
                "pattern_count": len(raw_patterns),
                "match_count": sum(len(v) for v in matches.values()),
            },
        }

    @staticmethod
    def _read_text(kwargs: Mapping[str, Any]) -> str:
        for key in ("text", "content", "message", "input"):
            value = kwargs.get(key)
            if value is not None:
                return str(value)
        return ""

    @staticmethod
    def _string_list(value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, Iterable):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value)]


def load_dynamic_capabilities(
    capability_registry: Any,
    capability_defs: Iterable[Mapping[str, Any]],
) -> List[str]:
    """Register all dynamic capability definitions into a registry."""

    loaded: List[str] = []
    for item in capability_defs:
        cap_type = str(item.get("type", ""))
        mode = str(item.get("mode", ""))
        if cap_type != "dynamic" and cap_type not in DynamicToolCapability.SUPPORTED_MODES:
            continue
        if cap_type in DynamicToolCapability.SUPPORTED_MODES and not mode:
            item = dict(item)
            item["mode"] = cap_type

        capability = DynamicToolCapability.from_config(item)
        capability_registry.register_native(capability)
        loaded.append(capability.name)

    return loaded
