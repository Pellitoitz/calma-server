"""User-facing error taxonomy (1.0). Existing exception classes are mapped to a category; nothing is swallowed and
nothing falls back silently: the CLI shows `CATEGORY: message` and keeps the traceback in a local log for diagnosis.

    MODEL_VALIDATION_ERROR      the model / file is not valid or not executable
    MISSING_INPUT               a required value is MISSING (never replaced by a default)
    ENGINEER_DECISION_REQUIRED  approval or an explicit engineer decision is needed
    UNSUPPORTED_FEATURE         declared but not supported by this version
    SIMULATION_ERROR            the engine stopped (deadlock, invariant, same-instant loop...)
    DATA_ERROR                  measured-data import / validation / fitting
    PERSISTENCE_ERROR           project, workspace, database or file problem
    ECONOMICS_ERROR             economic assumptions / evaluation
    INTERRUPTED                 stopped by the user (Ctrl+C): nothing is stored as completed
    INTERNAL_ERROR              anything else (a bug): report it with the log file
"""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
import traceback
from pathlib import Path

CATEGORIES = ("MODEL_VALIDATION_ERROR", "MISSING_INPUT", "ENGINEER_DECISION_REQUIRED", "UNSUPPORTED_FEATURE",
              "SIMULATION_ERROR", "DATA_ERROR", "PERSISTENCE_ERROR", "ECONOMICS_ERROR", "INTERRUPTED", "INTERNAL_ERROR")
EXIT_CODES = {"INTERNAL_ERROR": 70, "INTERRUPTED": 130}  # everything else: 1


def classify(exc: BaseException) -> str:
    from pydantic import ValidationError

    from .data.store import DatasetError
    from .domain.calendar_edit import CalendarEditError
    from .domain.expressions import ExpressionError, MissingParameter
    from .domain.io import ModelFormatError
    from .domain.paths import PathError
    from .domain.units import UnitError
    from .economics.evaluate import EconomicsError
    from .engine.des.engine import DeadlockError
    from .engine.des.runtime import InvariantViolation, SameInstantLoopError, TravelDataError
    from .engine.production_compile import SetupTransitionMissing
    from .experiments.runner import ExperimentError
    from .persistence.project import ProjectError
    from .validation.verifier import ModelError
    try:
        from .services.app import ApprovalRequired
    except Exception:  # noqa: BLE001 - services import optional pieces
        ApprovalRequired = ()  # type: ignore[assignment]
    try:
        from .data.service import DataDecisionRequired
    except Exception:  # noqa: BLE001
        DataDecisionRequired = ()  # type: ignore[assignment]
    from .data.importers import ImportError_

    if isinstance(exc, KeyboardInterrupt):
        return "INTERRUPTED"
    if isinstance(exc, MissingParameter):
        return "MISSING_INPUT"
    if ApprovalRequired and isinstance(exc, ApprovalRequired) or DataDecisionRequired and isinstance(exc, DataDecisionRequired):
        return "ENGINEER_DECISION_REQUIRED"
    if isinstance(exc, EconomicsError):
        return "ECONOMICS_ERROR"
    if isinstance(exc, (DatasetError, ImportError_)):
        return "DATA_ERROR"
    if isinstance(exc, (DeadlockError, InvariantViolation, SameInstantLoopError, TravelDataError, SetupTransitionMissing)):
        return "SIMULATION_ERROR"
    if isinstance(exc, (ModelError, ModelFormatError, ValidationError, ExpressionError, PathError, UnitError,
                        CalendarEditError, ExperimentError)):
        return "MODEL_VALIDATION_ERROR"
    if isinstance(exc, (ProjectError, sqlite3.Error, FileNotFoundError, PermissionError, IsADirectoryError)):
        return "PERSISTENCE_ERROR"
    if isinstance(exc, NotImplementedError):
        return "UNSUPPORTED_FEATURE"
    return "INTERNAL_ERROR"


def log_dir() -> Path:
    return Path(os.environ.get("SIMFORGE_LOG_DIR") or Path.home() / ".simforge" / "logs")


def write_log(exc: BaseException, argv: list[str]) -> Path | None:
    """Diagnostic log: version, command, traceback. No environment variables, no secrets, no dataset rows."""
    from . import ENGINE_VERSION, __version__
    try:
        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"simforge-error-{dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.log"
        path.write_text(f"simforge {__version__} · engine {ENGINE_VERSION}\ncommand: simforge {' '.join(argv)}\n"
                        f"category: {classify(exc)}\n\n" + "".join(traceback.format_exception(exc)), encoding="utf-8")
        return path
    except OSError:
        return None


def user_message(exc: BaseException) -> str:
    cat = classify(exc)
    text = str(exc).strip() or type(exc).__name__
    if cat == "INTERNAL_ERROR":
        text = f"{type(exc).__name__}: {text}"
    return f"{cat}: {text}"
