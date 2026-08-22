"""Lazy Agent Runtime service properties for the unified SDK facade."""

from __future__ import annotations

import threading
from typing import Any


class AgentRuntimeSdkMixin:
    def _initialize_agent_runtime_services(self, scope_bound: bool) -> None:
        self._runtime_scope_bound = bool(scope_bound)
        self._journey_lock = threading.Lock()
        self._capability_trust_lock = threading.Lock()
        self._skill_runtime_lock = threading.Lock()
        self._journey_service: Any | None = None
        self._capability_trust_service: Any | None = None
        self._skill_runtime_service: Any | None = None

    @property
    def journeys(self) -> Any:
        """The reusable Journey service; constructing it performs no target I/O."""

        if self._journey_service is None:
            with self._journey_lock:
                if self._journey_service is None:
                    from .journey_service import JourneyService

                    self._journey_service = JourneyService(
                        self,
                        workspace=self._workspace,
                        capability_trust=self.capability_trust,
                        skill_runtime=self.skill_runtime,
                    )
        return self._journey_service

    @property
    def skill_runtime(self) -> Any:
        """The offline Built-in Core Skill resolver for this workspace."""

        if self._skill_runtime_service is None:
            with self._skill_runtime_lock:
                if self._skill_runtime_service is None:
                    from .core_skill_runtime import CoreSkillRuntime

                    self._skill_runtime_service = CoreSkillRuntime(
                        workspace=self._workspace,
                        capability_trust=self.capability_trust,
                    )
        return self._skill_runtime_service

    @property
    def capability_trust(self) -> Any:
        """Current same-layer Capability Trust, scoped only for from_env()."""

        if self._capability_trust_service is None:
            with self._capability_trust_lock:
                if self._capability_trust_service is None:
                    from .capability_trust import CapabilityTrustService
                    from .capability_validation import CapabilityValidationStore

                    store = CapabilityValidationStore(
                        self._workspace.state_root,
                        scope_bound=self._runtime_scope_bound,
                    )
                    self._capability_trust_service = CapabilityTrustService(store)
        return self._capability_trust_service


__all__ = ["AgentRuntimeSdkMixin"]
