import copy
import hashlib
import json
import sys
import uuid
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from stage_audit_graph import upgrade, digest
from stage_audit_result import consume
from motionguard_core.report_artifact import write


@pytest.fixture
def case(tmp_path):
    run = str(uuid.uuid4())
    graph = json.loads((ROOT / "workflows/T5/guarded-ltx-local-template.api.json").read_text())
    graph["mg_bind"]["inputs"]["run_id"] = run
    graph = upgrade(graph)
    workflow = tmp_path / "workflow.api.json"
    workflow.write_text(json.dumps(graph))
    pin = {"graph_sha256": digest(graph), "code_sha256": "b" * 64}
    plan = {"execution_id": run, "stage_audit": pin, "input_hashes": {
        "workflow.api.json": hashlib.sha256(workflow.read_bytes()).hexdigest()}}
    report = {"schema_version": "mg-report-2", "verdict": "FAIL", "failures": [{
        "type": "motion_omission", "frames": [24, 47], "t_start_s": 1,
        "t_end_s": 2, "evidence": {}}]}
    audit = {**pin, "run_id": run, "initialized": True, "guard_verdict": "FAIL",
             "held": True, "entered": [], "completed": []}
    out = tmp_path / "outputs"
    out.mkdir()
    outputs = [{"node_id": node, "name": name, "type": "image", "path": str(out / name)}
               for node, name in (("4852", "stage-audit.png"), ("mg_inspect", "guard-result.png"))]
    def emit(value=audit, checked_report=report):
        write(out / "stage-audit.png", checked_report, {"stage_audit": value, "timeline":{"frames":97,"fps":24}}, run)
        write(out / "guard-result.png", report, {"timeline":{"frames":97,"fps":24}}, run)
    emit()
    return tmp_path, outputs, plan, audit, emit


def test_verified_hold(case):
    folder, outputs, plan, audit, _ = case
    assert consume(folder, outputs, plan) == audit


def test_different_timeline_cannot_confirm_hold(case):
    from motionguard_core.report_artifact import read
    folder, outputs, plan, audit, _ = case
    path = folder / "outputs/stage-audit.png"
    payload = read(path, plan["execution_id"])
    context = payload["stage_context"]
    context["timeline"] = {"frames":721,"fps":24}
    write(path,payload["report"],context,plan["execution_id"])
    with pytest.raises(ValueError,match="timeline differ"):
        consume(folder,outputs,plan)


@pytest.mark.parametrize("field,value", [
    ("run_id", str(uuid.uuid4())), ("code_sha256", "c" * 64),
    ("graph_sha256", "d" * 64), ("initialized", False),
    ("entered", ["upsampler"]), ("completed", ["sampler"]),
    ("held", False), ("guard_verdict", "PASS")])
def test_identity_and_execution_corruption_rejected(case, field, value):
    folder, outputs, plan, audit, emit = case
    bad = copy.deepcopy(audit)
    bad[field] = value
    emit(bad)
    with pytest.raises(ValueError):
        consume(folder, outputs, plan)


def test_missing_duplicate_or_outside_carrier_rejected(case):
    folder, outputs, plan, _, _ = case
    for candidate in (outputs[1:], outputs + outputs[:1],
                      [{**outputs[0], "path": str(folder / "outside.png")}, outputs[1]]):
        with pytest.raises(ValueError):
            consume(folder, candidate, plan)


def test_mutated_submitted_workflow_rejected(case):
    folder, outputs, plan, _, _ = case
    with (folder / "workflow.api.json").open("a") as stream:
        stream.write(" ")
    with pytest.raises(ValueError):
        consume(folder, outputs, plan)


def test_report_difference_rejected(case):
    folder, outputs, plan, audit, emit = case
    changed = {"schema_version": "mg-report-2", "verdict": "FAIL", "failures": [{
        "type": "pose", "frames": [24, 47], "t_start_s": 1, "t_end_s": 2, "evidence": {}}]}
    emit(audit, changed)
    with pytest.raises(ValueError):
        consume(folder, outputs, plan)


@pytest.mark.parametrize("missing_carrier", [False, True])
def test_finish_outputs_requires_execution_audit(case, monkeypatch, missing_carrier):
    import run_guarded_platform as runner
    from motionguard_core.report_artifact import read as read_artifact
    folder, outputs, plan, audit, _ = case
    reference = folder / "reference.mp4"
    reference.write_bytes(b"reference-fixture")
    gt = folder / "joints.observed.json"
    gt.write_text('{"observed":true}')
    plan["gt_file"] = gt.name
    for path in (reference, gt):
        plan["input_hashes"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    runner.save(folder / "execution-plan.json", plan)
    report = read_artifact(folder / "outputs/guard-result.png", plan["execution_id"])["report"]
    monkeypatch.setattr(runner, "restore", lambda *args, **kwargs: report)
    runner.save(folder / "cli-stdout.txt", {"ok": True, "data": {
        "job": {"id": plan["execution_id"], "status": "succeeded"},
        "outputs": outputs[1:] if missing_carrier else outputs}})
    runner.save(folder / "cli-exit.json", {"returncode": 0})
    if missing_carrier:
        with pytest.raises(ValueError, match="Missing or ambiguous"):
            runner.finish_outputs(folder)
        assert not (folder / "verified-stage-audit.json").exists()
        assert not (folder / "downstream-result.json").exists()
        assert runner.read(folder / "state.json").get("downstream_status") not in ("held", "complete")
    else:
        result = runner.finish_outputs(folder)
        assert result["stage2_execution_absence_proven"] is True
        assert result["stage_audit"] == audit
        assert runner.read(folder / "verified-stage-audit.json") == audit
        state = runner.read(folder / "state.json")
        assert state["downstream_status"] == "held"
        assert state["final_available"] is False
