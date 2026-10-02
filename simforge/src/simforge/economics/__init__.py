"""Economics & decision support (engine >= 0.9.0): post-run, explicit, traceable. Never changes the DES, never
recommends. See docs/economics_and_decision_support.md."""

from .compare import Comparison, compare_evaluations
from .evaluate import EconomicEvaluation, evaluate_run

__all__ = ["EconomicEvaluation", "evaluate_run", "Comparison", "compare_evaluations"]
