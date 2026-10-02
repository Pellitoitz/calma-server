"""SimForge - AI-assisted industrial discrete-event simulation workbench.

The AI builds, the engine computes, the system checks, the engineer validates.
"""

__version__ = "0.1.0"
ENGINE_NAME = "simforge-des"
ENGINE_VERSION = "0.9.0"  # 0.9.0: economics & decision support as a post-run layer (block `economics` excluded from the physical hash; the DES is unchanged). 0.8.0: maintenance & reliability (failure clocks ELAPSED / OPERATING with explicit exposure, corrective repair with resources, calendar- / usage-based PM AFTER_CURRENT_ACTIVITY, RESET / NO_RESET); legacy failures untouched. 0.7.0: product mix / explicit sequences, product-specific processing and routes, setups / changeovers (constant, target-, sequence-dependent; setup state changes only on completion). 0.6.0: calendars, shifts, breaks, exceptions; FINISH_CURRENT / PAUSE_RESUME / STOP_RESTART; calendar transitions first in an instant. 0.5.0: explicit work_units aggregation (sum_iid | scale_sample | single_sample; undeclared = legacy k*X); truncation bound_type. 0.4.0: gamma/weibull, explicit truncation, negative duration samples raise (no silent resampling). 0.3.0: same-instant fixed-point resolution + explicit tie-break, single carrier state (reserved_for_transport), feed WIP counts distinct units. 0.2.0: physical transport pickup, operator states split, invariants
