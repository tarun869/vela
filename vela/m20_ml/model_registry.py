"""
ML model versioning and registry for VPP forecasting and optimization models.

Manages model lifecycle: training, validation, staging, production deployment,
and retirement with full lineage tracking.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class ModelStage(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    ARCHIVED = "archived"
    FAILED = "failed"


@dataclass
class ModelMetrics:
    mae: float = 0.0
    rmse: float = 0.0
    mape: float = 0.0
    r2: float = 0.0
    sharpe_ratio: float = 0.0
    custom: Dict[str, float] = field(default_factory=dict)


@dataclass
class ModelVersion:
    model_id: str
    model_name: str
    version: str
    stage: ModelStage
    algorithm: str           # "xgboost", "lstm", "random_forest", etc.
    framework: str           # "scikit-learn", "tensorflow", "pytorch"
    target_variable: str     # What the model predicts
    feature_names: List[str]
    training_start: str
    training_end: str
    training_data_hash: str
    metrics: ModelMetrics
    hyperparameters: Dict[str, Any]
    created_at: str
    deployed_at: Optional[str] = None
    retired_at: Optional[str] = None
    artifact_path: Optional[str] = None  # Path to serialized model
    parent_model_id: Optional[str] = None
    tags: Dict[str, str] = field(default_factory=dict)


class ModelRegistry:
    """
    Centralized model registry with versioning and stage management.
    """

    def __init__(self) -> None:
        self._models: Dict[str, ModelVersion] = {}  # model_id -> ModelVersion
        self._production_models: Dict[str, str] = {}  # model_name -> model_id

    def register(self, model: ModelVersion) -> str:
        """Register a new model version. Returns model_id."""
        self._models[model.model_id] = model
        return model.model_id

    def create_version(
        self,
        model_name: str,
        algorithm: str,
        framework: str,
        target_variable: str,
        feature_names: List[str],
        hyperparameters: Dict[str, Any],
        training_start: str,
        training_end: str,
        metrics: ModelMetrics,
        parent_model_id: Optional[str] = None,
    ) -> ModelVersion:
        """Create and register a new model version."""
        # Auto-version based on existing models for this name
        existing = [m for m in self._models.values() if m.model_name == model_name]
        version_num = len(existing) + 1

        model = ModelVersion(
            model_id=str(uuid.uuid4()),
            model_name=model_name,
            version=f"v{version_num}.0",
            stage=ModelStage.DEVELOPMENT,
            algorithm=algorithm,
            framework=framework,
            target_variable=target_variable,
            feature_names=feature_names,
            training_start=training_start,
            training_end=training_end,
            training_data_hash=hex(hash(training_start + training_end))[:12],
            metrics=metrics,
            hyperparameters=hyperparameters,
            created_at=datetime.now(timezone.utc).isoformat(),
            parent_model_id=parent_model_id,
        )
        self.register(model)
        return model

    def transition_stage(self, model_id: str, new_stage: ModelStage) -> bool:
        """Move a model to a new stage."""
        model = self._models.get(model_id)
        if not model:
            return False

        # Stage transition validation
        valid_transitions = {
            ModelStage.DEVELOPMENT: [ModelStage.STAGING, ModelStage.FAILED],
            ModelStage.STAGING: [ModelStage.PRODUCTION, ModelStage.DEVELOPMENT, ModelStage.FAILED],
            ModelStage.PRODUCTION: [ModelStage.ARCHIVED],
            ModelStage.ARCHIVED: [],
            ModelStage.FAILED: [ModelStage.DEVELOPMENT],
        }
        if new_stage not in valid_transitions.get(model.stage, []):
            return False

        if new_stage == ModelStage.PRODUCTION:
            # Archive existing production model
            if model.model_name in self._production_models:
                old_id = self._production_models[model.model_name]
                if old_id in self._models:
                    self._models[old_id].stage = ModelStage.ARCHIVED
                    self._models[old_id].retired_at = datetime.now(timezone.utc).isoformat()

            self._production_models[model.model_name] = model_id
            model.deployed_at = datetime.now(timezone.utc).isoformat()

        model.stage = new_stage
        return True

    def get_production_model(self, model_name: str) -> Optional[ModelVersion]:
        """Get the currently deployed production model for a given name."""
        model_id = self._production_models.get(model_name)
        return self._models.get(model_id) if model_id else None

    def list_models(
        self,
        name: Optional[str] = None,
        stage: Optional[ModelStage] = None,
    ) -> List[ModelVersion]:
        models = list(self._models.values())
        if name:
            models = [m for m in models if m.model_name == name]
        if stage:
            models = [m for m in models if m.stage == stage]
        return sorted(models, key=lambda m: m.created_at, reverse=True)

    def compare_versions(self, model_id_a: str, model_id_b: str) -> Dict[str, Any]:
        """Compare two model versions by metrics."""
        a = self._models.get(model_id_a)
        b = self._models.get(model_id_b)
        if not a or not b:
            return {}
        return {
            "model_a": {"id": model_id_a, "version": a.version, "rmse": a.metrics.rmse},
            "model_b": {"id": model_id_b, "version": b.version, "rmse": b.metrics.rmse},
            "winner": model_id_a if a.metrics.rmse < b.metrics.rmse else model_id_b,
            "improvement_pct": abs(a.metrics.rmse - b.metrics.rmse) / max(b.metrics.rmse, 1e-9) * 100,
        }
