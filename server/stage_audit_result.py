"""Validate execution-bound Stage2 records; missing records never mean zero work."""
import hashlib
import json
from pathlib import Path
from motionguard_core.report_artifact import read as read_artifact, timeline as artifact_timeline
from stage_audit_graph import digest, validate


def consume(folder, outputs, plan):
    folder = Path(folder).resolve()
    pin = plan["stage_audit"]
    workflow_path = folder / "workflow.api.json"
    if hashlib.sha256(workflow_path.read_bytes()).hexdigest() != plan["input_hashes"]["workflow.api.json"]:
        raise ValueError("Submitted audit workflow changed")
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    if plan.get('generator_mode') == 'layout':
        from layout_graph import validate as validate_layout
        validate_layout(workflow)
    else:
        validate(workflow)
    if digest(workflow) != pin["graph_sha256"]:
        raise ValueError("Submitted audit graph pin mismatch")
    if workflow["mg_bind"]["inputs"]["run_id"] != plan["execution_id"]:
        raise ValueError("Submitted audit execution mismatch")
    rows = [o for o in outputs if o.get("node_id") == "4852"
            and o.get("name") == "stage-audit.png" and o.get("type") == "image"]
    if len(rows) != 1:
        raise ValueError("Missing or ambiguous Stage2 execution audit")
    path = Path(rows[0]["path"]).resolve()
    if path.parent != folder / "outputs" or not path.is_file():
        raise ValueError("Stage audit outside current execution")
    payload = read_artifact(path, plan["execution_id"])
    audit = payload.get("stage_context", {}).get("stage_audit", {})
    if (audit.get("run_id") != plan["execution_id"]
            or audit.get("graph_sha256") != pin["graph_sha256"]
            or audit.get("code_sha256") != pin["code_sha256"]
            or audit.get("initialized") is not True
            or audit.get("guard_verdict") != payload["report"]["verdict"]):
        raise ValueError("Stage audit identity or initialization mismatch")
    verdict = payload["report"]["verdict"]
    expected = ["upsampler", "sampler"] if verdict == "PASS" else []
    if (audit.get("entered") != expected or audit.get("completed") != expected
            or audit.get("held") is not (verdict != "PASS")):
        raise ValueError("Stage2 execution contradicts Guard")
    inspector = [o for o in outputs if o.get("node_id") == "mg_inspect"
                 and o.get("name") == "guard-result.png" and o.get("type") == "image"]
    if len(inspector) != 1:
        raise ValueError("Inspector report missing for audit comparison")
    inspector_path = Path(inspector[0]["path"]).resolve()
    if inspector_path.parent != folder / "outputs":
        raise ValueError("Inspector artifact outside current execution")
    original = read_artifact(inspector_path, plan["execution_id"])
    if original["report_sha256"] != payload["report_sha256"]:
        raise ValueError("Stage audit and Inspector report differ")
    if artifact_timeline(original) != artifact_timeline(payload):
        raise ValueError("Stage audit and Inspector timeline differ")
    return audit
