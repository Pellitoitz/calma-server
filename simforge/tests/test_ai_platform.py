"""LLM path with MockLLM (CI never calls a real provider): retry/repair, audit log without secrets, versioned prompts,
fallback without AI, determinism, controlled tools, productivity metrics."""

from pathlib import Path

import pytest

from simforge.ai.prompts import EDIT_PROMPT_VERSION, PARSE_PROMPT_VERSION, available
from simforge.ai.provider import MockLLMProvider
from simforge.ai.schemas import ProcessDraft
from simforge.ai.tools import ToolRegistry
from simforge.services.app import SimForgeApp
from simforge.services.productivity import productivity, record_engineer_time

from .test_nl_orchestration import MVP_SPEC_TEXT

SECRET = "sk-ant-api03-THIS-IS-A-FAKE-SECRET-0000"


def _draft(component_for_insp: str = "inspection") -> dict:
    return {
        "model_name": "MVP", "horizon_value": 8, "horizon_unit": "h", "supply": "infinite",
        "resources": [{"id": "op", "name": "Operario", "kind": "operator", "quantity": 1}],
        "steps": [
            {"id": "assembly", "name": "Montaje", "component": "manual_assembly", "time": {"value": 60}, "resources": ["op"]},
            {"id": "buf", "name": "Buffer", "component": "buffer", "capacity": 5},
            {"id": "m", "name": "Máquina", "component": "machine", "time": {"value": 45}},
            {"id": "insp", "name": "Inspección", "component": component_for_insp, "time": {"value": 20}, "resources": ["op"]},
        ],
    }


def test_prompts_are_versioned_files():
    assert {PARSE_PROMPT_VERSION, EDIT_PROMPT_VERSION} <= set(available())
    assert PARSE_PROMPT_VERSION == "process_parser_v1" and EDIT_PROMPT_VERSION == "edit_planner_v1"


def test_repair_after_semantic_error_and_audit(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)  # present in the environment; must never be stored anywhere

    def responder(user, schema):
        assert schema is ProcessDraft
        # first answer uses a component that does not exist; the repair prompt carries the validator errors
        return _draft("inspection" if "rejected by the validator" in user else "quality_magic_box")
    mock = MockLLMProvider(responder, model="claude-sonnet-5-5")
    app = SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=mock)
    p = app.create_project("llm")
    pr = app.parse_process(p, MVP_SPEC_TEXT)
    assert len(mock.calls) == 2 and "quality_magic_box" in mock.calls[1]["user"]
    m = pr.outcome.model
    assert [n.component for n in m.nodes][-2] == "inspection"
    assert m.meta.generated_by["prompt_version"] == "process_parser_v1"
    (audit,) = [a for a in p.audit_log() if a["purpose"] == "parse_process"]
    assert audit["accepted"] == 1 and audit["repairs"] == 1 and "quality_magic_box" in audit["validation_errors"]
    assert audit["provider"] == "mock" and audit["model"] == "claude-sonnet-5-5" and audit["prompt_version"] == "process_parser_v1"
    assert audit["input_tokens"] > 0 and audit["est_cost_usd"] > 0 and audit["latency_ms"] >= 0
    assert audit["input_text"] == MVP_SPEC_TEXT and '"insp"' in audit["output_json"]
    # the secret is in no file of the project (db, versions, logs)
    for f in Path(p.root).rglob("*"):
        if f.is_file():
            assert SECRET.encode() not in f.read_bytes(), f


def test_broken_llm_output_falls_back_to_offline_rules(tmp_path):
    mock = MockLLMProvider(lambda user, schema: {"model_name": "x", "steps": [{"id": "a"}]})  # schema-invalid every time
    app = SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=mock)
    p = app.create_project("fallback")
    pr = app.parse_process(p, MVP_SPEC_TEXT)
    assert len(mock.calls) == 3  # 1 + 2 repairs, then never used
    assert pr.interpreter.startswith("offline-rules (fallback")
    assert pr.outcome.reuse_ratio == 1.0 and [n.component for n in pr.outcome.model.nodes][1] == "manual_assembly"
    llm = [a for a in p.audit_log() if a["provider"] == "mock"]
    assert llm and not llm[0]["accepted"] and "schema" in llm[0]["validation_errors"]


def test_offline_generation_is_deterministic(tmp_path):
    app = SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)
    a = app.parse_process(app.create_project("a"), MVP_SPEC_TEXT)
    b = app.parse_process(app.create_project("b"), MVP_SPEC_TEXT)
    assert a.outcome.draft == b.outcome.draft
    strip = {"meta"}
    assert a.outcome.model.model_dump(exclude=strip) == b.outcome.model.model_dump(exclude=strip)


def test_controlled_tools(tmp_path):
    app = SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)
    p = app.create_project("tools")
    tools = ToolRegistry(app, p)
    names = {d["name"] for d in tools.definitions()}
    assert names == {"search_components", "inspect_component", "create_model_spec", "update_model_spec", "validate_model",
                     "compare_models", "run_simulation", "run_experiment", "get_results"}
    assert not any(k in n for n in names for k in ("approve", "exec", "code", "file", "library_update"))
    assert all(d["input_schema"]["type"] == "object" for d in tools.definitions())

    hits = tools.call("search_components", {"query": "almacén intermedio"})
    assert hits["ok"] and hits["components"][0]["id"] == "buffer"
    assert tools.call("search_components", {"query": "wip objetivo"})["rules"][0]["id"] == "wip_target_priority"
    assert tools.call("inspect_component", {"component_id": "buffer"})["validation_status"]
    created = tools.call("create_model_spec", {"description": MVP_SPEC_TEXT})
    assert created["ok"] and created["readiness"] == "EXECUTABLE" and "REUSE RATIO: 100%" in created["matching_report"]
    # the AI cannot run an unapproved model, and cannot approve it
    run = tools.call("run_simulation", {})
    assert not run["ok"] and "ApprovalRequired" in run["error"]
    app.approve_model(p, by="engineer")
    run = tools.call("run_simulation", {})
    assert run["ok"] and run["kpis"]["units_completed"] == 359
    assert tools.call("get_results", {})["kpis"]["units_completed"] == 359
    upd = tools.call("update_model_spec", {"request": "buffer a 6", "confirm": True,
                                            "changes": [{"path": "parameters.buffer_1_capacity.value", "value": 6, "expected": 5}]})
    assert upd["ok"] and upd["new_version"]
    cmp = tools.call("compare_models", {"version_a": 1, "version_b": upd["new_version"], "run": False})
    assert cmp["ok"] and not cmp["structurally_equivalent"] and "buffer_1.capacity" in cmp["report"]
    exp = tools.call("run_experiment", {"factor_path": "parameters.buffer_1_capacity.value", "values": [1, 2, 3]})
    assert exp["ok"] and len(exp["table"]) == 3
    assert tools.call("validate_model", {})["readiness"] == "EXECUTABLE"
    # strict arguments, unknown tools
    assert not tools.call("run_experiment", {"factor_path": "x", "values": [1], "code": "import os"})["ok"]
    assert not tools.call("execute_python", {"code": "1"})["ok"]


def test_productivity_metrics(tmp_path):
    app = SimForgeApp(workspace=tmp_path / "ws", library_dir=tmp_path / "lib", provider=None)
    p = app.create_project("prod")
    app.parse_process(p, MVP_SPEC_TEXT)
    rep = productivity(p)
    assert rep.item("manual_model_build_time").source == "MISSING" and rep.time_saved_min is None
    assert rep.item("engineer_review_time").source == "MISSING"  # not approved yet
    app.approve_model(p, by="engineer")
    rep = productivity(p)
    assert rep.item("AI_initial_generation_time").source == "MEASURED"
    assert rep.item("engineer_review_time").source == "MEASURED"
    record_engineer_time(p, "manual_model_build_min", 240)
    record_engineer_time(p, "engineer_review_min", 22)
    record_engineer_time(p, "correction_min", 10)
    rep = productivity(p)
    gen = rep.item("AI_initial_generation_time").minutes
    assert rep.total_ai_assisted_min == pytest.approx(gen + 32)
    assert rep.time_saved_min == pytest.approx(240 - gen - 32)
    assert rep.time_saved_pct == pytest.approx((240 - gen - 32) / 240)
    assert "TIME SAVED" in rep.to_text() and "REUSE RATIO: 100%" in rep.to_text()
