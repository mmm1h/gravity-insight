"""Lazy Agent Runtime service properties for the unified SDK facade."""

from __future__ import annotations

import threading
from typing import Any


class AgentRuntimeSdkMixin:
    def _initialize_agent_runtime_services(
        self, scope_bound: bool, runtime_factory: Any | None = None
    ) -> None:
        self._runtime_scope_bound = bool(scope_bound)
        self._journey_lock = threading.Lock()
        self._capability_trust_lock = threading.Lock()
        self._skill_runtime_lock = threading.Lock()
        self._prepared_plans_lock = threading.Lock()
        self._actions_lock = threading.Lock()
        self._experiments_lock = threading.Lock()
        self._analysis_artifacts_lock = threading.Lock()
        self._governor_lock = threading.Lock()
        self._execution_variants_lock = threading.Lock()
        self._journey_service: Any | None = None
        self._capability_trust_service: Any | None = None
        self._skill_runtime_service: Any | None = None
        self._prepared_plans_service: Any | None = None
        self._actions_service: Any | None = None
        self._experiments_service: Any | None = None
        self._analysis_artifacts_service: Any | None = None
        self._governor_service: Any | None = None
        self._execution_variants_service: Any | None = None
        self._governor_runtime_factory = runtime_factory

    @property
    def execution_variants(self) -> Any:
        """Offline fixed Variant evidence and Trust-gated selection."""

        if self._execution_variants_service is None:
            with self._execution_variants_lock:
                if self._execution_variants_service is None:
                    from .execution_variant import ExecutionVariantService

                    self._execution_variants_service = ExecutionVariantService(
                        lambda: self.capability_trust
                    )
        return self._execution_variants_service

    @property
    def governor(self) -> Any:
        """Value-free policy and observations for the shared Runtime scope."""

        if self._governor_service is None:
            with self._governor_lock:
                if self._governor_service is None:
                    from .governor_observation import GovernorObservationService

                    self._governor_service = GovernorObservationService(
                        self._governor_runtime_factory
                    )
        return self._governor_service

    @property
    def analysis_artifacts(self) -> Any:
        """Offline Analysis Artifact compiler and deterministic renderer."""

        if self._analysis_artifacts_service is None:
            with self._analysis_artifacts_lock:
                if self._analysis_artifacts_service is None:
                    from .analysis_artifact import AnalysisArtifactService

                    self._analysis_artifacts_service = AnalysisArtifactService()
        return self._analysis_artifacts_service

    @property
    def experiments(self) -> Any:
        """Offline Experiment Proposal and independent Outcome Handoff service."""

        if self._experiments_service is None:
            with self._experiments_lock:
                if self._experiments_service is None:
                    from .experiment_handoff import ExperimentHandoffService

                    self._experiments_service = ExperimentHandoffService()
        return self._experiments_service

    @property
    def actions(self) -> Any:
        """Explicit Action Plan service with a closed governed connector set."""

        if self._actions_service is None:
            with self._actions_lock:
                if self._actions_service is None:
                    from .action_plan import ActionPlanService

                    self._actions_service = ActionPlanService(self)
        return self._actions_service

    @property
    def prepared_plans(self) -> Any:
        """Optional private PAP pilot for scoped read-only host Plans."""

        if self._prepared_plans_service is None:
            with self._prepared_plans_lock:
                if self._prepared_plans_service is None:
                    from .prepared_analysis_plan import PreparedAnalysisPlanService

                    self._prepared_plans_service = PreparedAnalysisPlanService(self)
        return self._prepared_plans_service

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
        """The offline Built-in or exact locked Team Skill runtime."""

        if self._skill_runtime_service is None:
            with self._skill_runtime_lock:
                if self._skill_runtime_service is None:
                    from .core_skill_runtime import CoreSkillRuntime

                    self._skill_runtime_service = CoreSkillRuntime(
                        workspace=self._workspace,
                        capability_trust=self.capability_trust,
                        external_context_providers=self._external_context_providers,
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
