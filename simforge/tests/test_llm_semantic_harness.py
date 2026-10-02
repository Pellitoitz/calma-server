"""LLM semantic benchmark harness (benchmarks/llm_semantic). Runs in CI WITHOUT any LLM provider:
validates the measuring instrument (evaluator, gold consistency, runner paths) with synthetic, known-answer outputs."""

import sys
from pathlib import Path

import yaml

BENCH = Path(__file__).parents[1] / "benchmarks" / "llm_semantic"
sys.path.insert(0, str(BENCH))
import run_benchmark as RB  # noqa: E402
from evaluator import POSITIVE, Outcome, evaluate  # noqa: E402

from simforge.ai.compiler import compile_draft  # noqa: E402
from simforge.ai.schemas import ProcessDraft  # noqa: E402
from simforge.library.registry import ComponentRegistry  # noqa: E402
from simforge.validation.verifier import verify  # noqa: E402

REG = ComponentRegistry.load_default()
KINDS = {"flow", "component", "value", "basis", "shared_resource", "no_resource", "carrier", "strategy", "missing", "ambiguity",
         "conflict", "unsupported", "routing", "distribution", "supply"}


def case(cid):
    return RB.load_cases()[cid]


def outcome_for(cid: str, draft: dict, tamper=None) -> tuple:
    c, g = case(cid)
    d = ProcessDraft.model_validate(draft)
    o = compile_draft(d, REG, c["text"])
    model = o.model if tamper is None else tamper(o.model)
    rep, _ = verify(model, REG)
    out = Outcome(c["text"], True, True, rep.readiness.value, model.model_dump(mode="json"), d.model_dump(mode="json"),
                  o.questions() + [m.question for m in model.missing if not m.required], [a.text for a in model.assumptions],
                  [x.description for x in model.custom_rule_candidates], list(d.unparsed),
                  llm_questions=[q.question for q in d.missing_information])
    ev = evaluate(cid, g, out)
    return {r.req: r for r in ev.results}, ev


def b1_draft(asm=30, asm_basis="per_item", sel=20, sel_basis="per_entity", questions=(), customs=()):
    return {"model_name": "B1", "horizon_value": 8, "horizon_unit": "h", "supply": "infinite",
            "resources": [{"id": "op", "name": "Operario", "kind": "operator", "quantity": 1},
                          {"id": "racks", "name": "bastidores", "kind": "carrier", "quantity": 3}],
            "items": {"item_name": "circuitos", "per_entity": 4},
            "steps": [{"id": "asm", "name": "Montaje", "component": "manual_assembly", "time": {"value": asm},
                       "resources": ["op"], "time_basis": asm_basis},
                      {"id": "buf", "name": "Buffer", "component": "buffer", "capacity": 3},
                      {"id": "sel", "name": "Selectiva", "component": "selective_soldering", "time": {"value": sel}, "time_basis": sel_basis},
                      {"id": "rev", "name": "Revisión", "component": "inspection", "time": {"value": 15}, "resources": ["op"],
                       "time_basis": "per_item"}],
            "carrier_loops": [{"resource": "racks", "seize_at": "asm", "release_at": "rev", "return_mode": "immediate"}],
            "missing_information": [{"question": q} for q in questions], "custom_rules": [{"description": c} for c in customs]}


def test_cases_and_gold_are_consistent():
    cases = RB.load_cases()
    fams = {}
    for cid, (c, g) in cases.items():
        fams.setdefault(c["family"], []).append(cid)
        roles = {r["role"] for r in g["roles"]}
        assert g["gold_source"] and g["requirements"]
        for r in g["requirements"]:
            assert r["kind"] in KINDS, r
            for key in ("role", "operator_of", "seize", "release", "from", "protected"):
                if r.get(key):
                    assert r[key] in roles, (cid, r)
            for rr in r.get("roles", []) + r.get("between", []) + r.get("feeders", []) + list(r.get("to", {})):
                assert rr in roles, (cid, rr)
    assert {f: len(v) for f, v in fams.items()} == {"A_PARAPHRASE": 4, "B_UNITS_BASIS": 4, "C_MISSING_AMBIGUITY": 4,
                                                    "D_CONTRADICTION": 4, "E_UNSUPPORTED_RULE": 4, "F_REALISTIC": 4, "PERTURBATION": 3}


def test_correct_interpretation_scores_all_positive():
    res, ev = outcome_for("B1", b1_draft())
    bad = {k: (r.status, r.detail) for k, r in res.items() if r.evaluated and r.status not in POSITIVE}
    assert bad == {}
    assert ev.semantically_correct


def test_basis_errors_are_detected_with_correct_severity():
    # B1-R06 = assembly time (physical, per rack), B1-R07 = assembly basis
    res, _ = outcome_for("B1", b1_draft(asm=30, asm_basis="per_entity"))  # 30 s per RACK: physical time wrong (x4)
    assert (res["B1-R06"].status, res["B1-R06"].error_type, res["B1-R06"].severity) == ("WRONG", "SEMANTIC_BASIS_ERROR", "CRITICAL")
    assert (res["B1-R07"].error_type, res["B1-R07"].severity) == ("SEMANTIC_BASIS_ERROR", "CRITICAL")
    res, _ = outcome_for("B1", b1_draft(asm=120, asm_basis="per_entity"))  # 120 s per rack: physical time right, basis lost
    # physical time right; the compiler marks the converted 120 (not in the text) as ASSUMED instead of CALCULATED -> MINOR
    assert res["B1-R06"].error_type != "SEMANTIC_BASIS_ERROR" and res["B1-R06"].severity == "MINOR"
    assert (res["B1-R07"].error_type, res["B1-R07"].severity) == ("SEMANTIC_BASIS_ERROR", "MAJOR")


def test_invented_user_provided_value_is_a_critical_failure():
    def tamper(m):  # a value that is NOT in the text presented as USER_PROVIDED
        params = [p.model_copy(update={"value": 25.0, "provenance": p.provenance.model_copy(update={"status": "provided_by_client"})})
                  if p.id == "sel_time" else p for p in m.parameters]
        return m.model_copy(update={"parameters": params})
    res, ev = outcome_for("B1", b1_draft(), tamper)
    inv = [r for r in res.values() if r.status == "INVENTED"]
    assert inv and inv[0].severity == "CRITICAL" and inv[0].error_type == "INVENTED_VALUE"
    assert not ev.semantically_correct


def test_grounding_downgrade_is_not_invention():
    res, ev = outcome_for("B1", b1_draft(sel=25))  # compiler downgrades the ungrounded 25 to ASSUMED -> value error, not invention
    assert res["B1-R10"].error_type == "PARAMETER_VALUE_ERROR"  # B1-R10 = selective time
    assert not any(r.status == "INVENTED" for r in res.values())


def test_conflict_detection_requires_a_question():
    d = b1_draft()
    d["steps"][1]["capacity"] = 5
    for r in d["resources"]:
        if r["kind"] == "carrier":
            r["quantity"] = 4
    res, _ = outcome_for("D1", d)
    conflict = next(r for r in res.values() if r.kind == "conflict")
    assert conflict.status == "WRONG" and conflict.error_type == "CONTRADICTION_NOT_DETECTED" and conflict.severity == "CRITICAL"
    d["missing_information"] = [{"question": "El buffer admite 5 o 3 bastidores? El texto da los dos valores."}]
    res, _ = outcome_for("D1", d)
    assert next(r for r in res.values() if r.kind == "conflict").status == "CONFLICT_DETECTED"


def test_unsupported_rule_approximated_vs_flagged():
    d = b1_draft()
    d["policies"] = [{"resource": "op", "rule": "wip_target", "protected_step": "sel", "feeder_steps": ["asm"], "target": 1}]
    res, _ = outcome_for("E1", d)
    u = next(r for r in res.values() if r.kind == "unsupported")
    assert (u.status, u.error_type, u.severity) == ("WRONG", "UNSUPPORTED_RULE_APPROXIMATED", "CRITICAL")
    d["custom_rules"] = [{"description": "Cuando solo quede un bastidor esperando, el operario termina y vuelve a montaje, "
                                         "excepto con más de tres esperando revisión"}]
    res, _ = outcome_for("E1", d)
    assert next(r for r in res.values() if r.kind == "unsupported").status == "UNSUPPORTED_CORRECTLY_DETECTED"


def test_runner_llm_path_end_to_end_with_mock(tmp_path, monkeypatch):
    """The real-LLM code path (LLMInterpreter + audit + evaluation + aggregation) with MockLLMProvider."""
    monkeypatch.setattr(RB, "MOCK_RESPONDER", lambda user, schema: b1_draft())
    assert RB.main(["--provider", "mock", "--cases", "B1,P2", "--no-stability", "--label", "mock_test",
                    "--out-root", str(tmp_path)]) == 0
    import json
    summary = json.loads((tmp_path / "results" / "mock_test" / "semantic_results.json").read_text())
    assert summary["usage"]["calls"] == 2 and summary["usage"]["input_tokens"] > 0
    rec = json.loads((tmp_path / "runs" / "mock_test" / "B1__run1.json").read_text())
    assert rec["schema_valid"] and rec["semantically_correct"] and rec["llm_calls"][0]["prompt_version"] == "process_parser_v1"
    meta = json.loads((tmp_path / "runs" / "mock_test" / "META.json").read_text())
    assert meta["frozen"] and meta["process_parser_version"] == "process_parser_v1" and meta["engine_version"]
    assert (tmp_path / "results" / "mock_test" / "semantic_results.csv").exists()


def test_runner_records_schema_failures_without_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(RB, "MOCK_RESPONDER", lambda user, schema: {"model_name": "x", "steps": [{"id": "a"}]})
    assert RB.main(["--provider", "mock", "--cases", "A1", "--no-stability", "--label", "broken", "--out-root", str(tmp_path)]) == 0
    import json
    rec = json.loads((tmp_path / "runs" / "broken" / "A1__run1.json").read_text())
    assert rec["schema_valid"] is False and "offline" not in rec["interpreter"]
    assert all(r["status"] == "NOT_EVALUABLE" for r in rec["evaluation"]["results"])


def test_runner_blocks_without_api_key_and_refuses_unfrozen(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert RB.main(["--provider", "anthropic", "--out-root", str(tmp_path)]) == 2
    assert yaml.safe_load((tmp_path / "results" / "STATUS.json").read_text())["REAL_LLM_TEST"] == "BLOCKED_NO_API_KEY"
    monkeypatch.setattr(RB, "check_freeze", lambda: ["src/simforge/ai/compiler.py"])
    assert RB.main(["--provider", "offline", "--out-root", str(tmp_path)]) == 3


def test_freeze_matches_current_system():
    """The committed FREEZE.json describes the system under test (prompts, compiler, schemas, library, rules, verifier)."""
    assert RB.check_freeze() == []
