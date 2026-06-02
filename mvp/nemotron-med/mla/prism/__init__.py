"""Prism-MLA validator + invariants + adversarial battery + gaming checks."""

from prism.adversarial import build_adversarial_battery
from prism.gaming_patterns import (
    GamingCheckResult,
    check_init_robustness,
    check_no_trivial_delegation,
    check_output_range,
    check_output_std,
    check_per_axis_variation,
    check_shape_generalization,
    run_all_gaming_checks,
)
from prism.invariants import (
    DEFAULT_INVARIANTS,
    InvariantCheck,
    NO_EXTREME_VALUES,
    OUTPUT_ROW_NORMS_BOUNDED,
    SOFTMAX_ROWS_SUM_TO_ONE,
    TOPK_AGREEMENT,
)
from prism.validator import ValidationResult, validate

__all__ = [
    "build_adversarial_battery",
    "DEFAULT_INVARIANTS",
    "GamingCheckResult",
    "InvariantCheck",
    "NO_EXTREME_VALUES",
    "OUTPUT_ROW_NORMS_BOUNDED",
    "SOFTMAX_ROWS_SUM_TO_ONE",
    "TOPK_AGREEMENT",
    "ValidationResult",
    "check_init_robustness",
    "check_no_trivial_delegation",
    "check_output_range",
    "check_output_std",
    "check_per_axis_variation",
    "check_shape_generalization",
    "run_all_gaming_checks",
    "validate",
]
