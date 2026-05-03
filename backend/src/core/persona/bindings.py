"""Agent/session persona binding service.

Persona definitions live in :mod:`core.persona.store`.  This thin service keeps
Agent role and session binding semantics separate from persona CRUD routes while
reusing the same file-backed persistence and precedence rules.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Optional

from .store import BASE_PERSONA_ID, PersonaStore

PERSONA_PRECEDENCE = [
    "request_persona_id",
    "session_binding",
    "agent_binding",
    "base_persona",
]

DEFAULT_BINDABLE_AGENT_ROLES = [
    "assistant",
    "tool_creator",
    "agent_creator",
    "planner",
    "coder",
    "reviewer",
]


class PersonaBindingService:
    """Read/write persona bindings without owning persona definition CRUD."""

    def __init__(self, store: Optional[PersonaStore] = None) -> None:
        self.store = store or PersonaStore()

    def get_bindings(self, *, known_agents: Optional[list[str]] = None) -> Dict[str, Any]:
        bindings = self.store.get_bindings()
        roles = list(DEFAULT_BINDABLE_AGENT_ROLES)
        for name in known_agents or []:
            if name and name not in roles:
                roles.append(name)
        return {
            **deepcopy(bindings),
            "precedence": list(PERSONA_PRECEDENCE),
            "base_persona_id": BASE_PERSONA_ID,
            "roles": roles,
        }

    def bind_agent(self, agent_name: str, persona_id: str) -> Dict[str, Any]:
        return self.store.set_agent_persona(agent_name, persona_id)

    def bind_session(self, session_id: str, persona_id: str) -> Dict[str, Any]:
        return self.store.set_session_persona(session_id, persona_id)

    def unbind_agent(self, agent_name: str) -> Dict[str, Any]:
        """Remove an Agent default persona binding so resolution falls back to base."""

        return self.store.unset_agent_persona(agent_name)

    def unbind_session(self, session_id: str) -> Dict[str, Any]:
        """Remove a session persona binding so Agent/default precedence applies."""

        return self.store.unset_session_persona(session_id)

    def resolve(
        self,
        *,
        agent_name: Optional[str] = None,
        session_id: Optional[str] = None,
        persona_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.store.resolve_persona(
            agent_name=agent_name,
            session_id=session_id,
            persona_id=persona_id,
        )
