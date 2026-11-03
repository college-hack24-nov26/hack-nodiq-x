"""services/gray_cast_iron/ — Gray Cast Iron Graphite Flake Analysis Package."""
from . import s_metalseg_adapter
# Backwards compatibility alias
graphite_flake_adapter = s_metalseg_adapter

from .pipeline import (
    analyze_image,
    engines_availability,
    SUPPORTED_ANALYSIS_TYPES,
    ANALYSIS_ARTIFACT_LABELS,
    ANALYSIS_METHODS,
    METHOD_LABELS,
)

__all__ = [
    "analyze_image",
    "engines_availability",
    "SUPPORTED_ANALYSIS_TYPES",
    "ANALYSIS_ARTIFACT_LABELS",
    "ANALYSIS_METHODS",
    "METHOD_LABELS",
    "s_metalseg_adapter",
    "graphite_flake_adapter",
]
