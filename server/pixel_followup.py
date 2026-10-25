"""Server two-job gate. Pixel RealESRGAN is not the LTX latent Stage2."""
import json
import re
import time
import uuid
from pathlib import Path

METHOD = "RealESRGAN_x2plus_framewise"
MODEL = "RealESRGAN_x2plus.pth"


def verified_report(folder):
    import app
    import sys
    if str(app.ROOT) not in sys.path:
        sys.path.insert(0, str(app.ROOT))
    from comfy_nodes.stage_gate import permitted
    state = app.read(folder / "state.json")
    if state.get("source_type") == "platform_guarded":
        raise ValueError("Native Platform results retain their original follow-up path")
    if state.get("output_error") or state.get("status") != "succeeded" or state.get("guard_status") != "complete":
        raise ValueError("No valid completed draft inspection")
    directory = state.get("guard_directory", "")
    if not re.fullmatch(r"guard-[a-f0-9]{32}", directory):
        raise ValueError("Invalid report directory")
    path = folder / directory / "report.json"
    report = app.read(path)
    pins = app.analysis_inputs(folder)
    if report.get("sources") != pins or report.get("verdict") != state.get("guard_verdict"):
        raise ValueError("Inspection binding changed")
    envelope = {"report": report, "stage_context": {"stage_id": folder.name, "sources": pins}}
    allow = permitted(envelope, folder.name)
    if report.get("verdict") == "PASS" and not allow:
        raise ValueError("Malformed PASS report")
    return report, {"method": METHOD, "run_id": folder.name,
                    "report_sha256": app.sha(path.read_bytes()), "sources": pins,
                    "guard_verdict": report["verdict"], "allowed": allow}


def begin(folder):
    """Called while the app lock is held; even restart cannot resubmit a marker."""
    import app
    marker = folder / "pixel-request.json"
    if marker.exists():
        return app.read(folder / "pixel-state.json"), False
    report, pin = verified_report(folder)
    state = {**pin, "status": "ready" if pin["allowed"] else "held",
             "submitted": False, "provider_contact_started": False, "created_at": time.time(),
             "automatic_retry": False, "deadline_seconds": 600}
    # The exclusive durable marker precedes every possible provider operation.
    with marker.open("x", encoding="utf-8") as stream:
        json.dump(pin, stream)
        stream.flush()
        __import__("os").fsync(stream.fileno())
    app.save(folder / "pixel-state.json", state)
    return state, pin["allowed"]


def workflow():
    return {
        "load": {"class_type": "LoadVideo", "inputs": {"file": ""}},
        "components": {"class_type": "GetVideoComponents", "inputs": {"video": ["load", 0]}},
        "model": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": MODEL}},
        "upscale": {"class_type": "ImageUpscaleWithModel",
                    "inputs": {"upscale_model": ["model", 0], "image": ["components", 0]}},
        "video": {"class_type": "CreateVideo",
                  "inputs": {"images": ["upscale", 0], "fps": ["components", 2],
                             "audio": ["components", 1]}},
        "save": {"class_type": "SaveVideo",
                 "inputs": {"video": ["video", 0], "filename_prefix": "motion_guard_pixel_x2",
                            "format": "auto", "format.codec": "auto"}},
    }


def view(folder, state):
    import app
    if (folder / "pixel-state.json").exists():
        pixel = app.read(folder / "pixel-state.json")
        state["pixel_followup"] = pixel
    return state


def run(folder, recover=False):
    import app
    try:
        _run(folder, recover)
    except Exception as exc:
        app.save(folder / "pixel-worker-error.json", {"error_type": type(exc).__name__, "at": time.time()})
    finally:
        app.LOCK.release()


def recover_known(folder):
    """Recover an existing remote job without uploading or submitting again."""
    import app
    app.LOCK.acquire()
    run(folder, recover=True)


def _run(folder, recover=False):
    import app
    import cv2
    from comfy_sdk import Comfy
    from comfy_sdk.retry import NO_RETRY
    from timeline_contract import validate_cloud_output
    state = app.read(folder / "pixel-state.json")
    reservation = folder / "pixel-reservation.json"
    accounting_id = folder.name + ":pixel"
    job = None

    def update(**values):
        state.update(values)
        app.save(folder / "pixel-state.json", state)

    def settle():
        ledger = app.read(app.LEDGER)
        if accounting_id not in ledger["known_runs"]:
            held = app.read(reservation)
            ledger["conservative_prior_credits"] = max(ledger["conservative_prior_credits"], held["prior"]) + held["reserved"]
            ledger["known_runs"].append(accounting_id)
        ledger["unresolved_jobs"] = [x for x in ledger["unresolved_jobs"] if x != accounting_id]
        app.save(app.LEDGER, ledger)
        app.save(reservation, {"released": True, "reserved": 179.6,
                              "actual_spend": None, "reason": "Remote terminal"})

    try:
        # Cancellation recovery must not depend on unchanged local inputs.
        if recover:
            if not state.get("job_id") or not state.get("submitted_at"):
                raise ValueError("Cannot recover an unknown submission")
            with Comfy(api_key=app.key(), timeout=30, retry=NO_RETRY) as client:
                job = client.jobs.get(state["job_id"])
                app.monitor_job(job, state["submitted_at"] + 600, update,lambda:(folder/'pixel-cancel-request.json').exists())
                update(remote_terminal=job.status)
                settle()
        _, pin = verified_report(folder)
        if pin != app.read(folder / "pixel-request.json") or not pin["allowed"]:
            raise ValueError("Draft changed after decision")
        from motionguard_core.reference_io import validate_timeline
        timeline = validate_timeline(app.read(app.selected_gt(folder)))
        expected = {"frames": timeline["frames"], "fps": timeline["fps"]}
        validate_cloud_output(folder / "generated.mp4", expected)
        cap = cv2.VideoCapture(str(folder / "generated.mp4"))
        width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        budget = app.read(app.ROOT / "config/budget.yaml")
        if (budget.get("allow_paid_execution") is not True or budget.get("additional_purchase_allowed") is not False
                or budget.get("cancel_after_submission_seconds") != 600):
            raise ValueError("No bounded paid authorization")
        key = app.key()
        update(provider_contact_started=True)
        if not recover:
            info = app.api("/api/object_info", key)
            graph = workflow()
            if any(node["class_type"] not in info for node in graph.values()):
                raise ValueError("Pixel workflow node unavailable")
            choices = info["UpscaleModelLoader"]["input"]["required"]["model_name"]
            options = choices[1]["options"] if choices[0] == "COMBO" else choices[0]
            if MODEL not in options:
                raise ValueError("Pixel model unavailable")
            billing = app.api("/api/billing/usage/timeseries?months=1", key)
            ledger = app.read(app.LEDGER)
            prior = app.cumulative_prior(ledger, billing["summary"]["balance"]["cloud_credit_balance_cents"], key)
            if ledger["unresolved_jobs"] or prior + 179.6 > app.authorized_ceiling(budget):
                raise ValueError("Budget or unsettled execution")
            queue = app.api("/api/queue", key)
            if queue.get("queue_running") or queue.get("queue_pending"):
                raise ValueError("Cloud queue occupied")
            app.save(folder / "pixel-billing-before.json", billing)
            app.save(folder / "pixel-workflow.json", graph)
            app.save(reservation, {"released": False, "reserved": 179.6, "prior": prior})
        with Comfy(api_key=key, timeout=30, retry=NO_RETRY) as client:
            if recover:
                if not state.get("job_id") or not state.get("submitted_at"):
                    raise ValueError("Cannot recover an unknown submission")
                job = client.jobs.get(state["job_id"])
            else:
                wf = client.workflows.from_file(folder / "pixel-workflow.json")
                wf.set_input("load", "file", client.assets.from_file(folder / "generated.mp4"))
                wf.json["load"]["inputs"]["file"].commit()
                # Recheck source/report after upload and before the irreversible POST.
                if verified_report(folder)[1] != pin:
                    raise ValueError("Draft changed during upload")
                if (folder/'pixel-cancel-request.json').exists():
                    raise ValueError('Canceled before submission')
                update(status="submitting", submitted_at=time.time(), idempotency_key=str(uuid.uuid4()))
                with (folder / "pixel-attempt.json").open("x", encoding="utf-8") as stream:
                    json.dump(state, stream)
                    stream.flush()
                    __import__("os").fsync(stream.fileno())
                ledger = app.read(app.LEDGER)
                ledger["unresolved_jobs"].append(accounting_id)
                app.save(app.LEDGER, ledger)
                job = client.submit(wf, idempotency_key=state["idempotency_key"])
                update(status="running", submitted=True, job_id=job.id)
            app.monitor_job(job, state["submitted_at"] + 600, update,lambda:(folder/'pixel-cancel-request.json').exists())
            update(remote_terminal=job.status)
            settle()
            if job.status != "succeeded":
                raise ValueError("Pixel follow-up did not succeed")
            videos = [o for o in job.outputs if o.content_type == "video/mp4"]
            if len(videos) != 1:
                raise ValueError("Unexpected final output count")
            output = folder / "pixel-final.mp4"
            videos[0].to_file(output)
            validate_cloud_output(output, expected)
            cap = cv2.VideoCapture(str(output))
            size = [int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))]
            cap.release()
            if size != [width * 2, height * 2]:
                raise ValueError("Pixel final size mismatch")
            if verified_report(folder)[1] != pin:
                raise ValueError("Draft changed before publication")
            update(status="complete", final_sha256=app.sha(output.read_bytes()),
                   final_size=size, timeline=expected, finished_at=time.time())
    except Exception as exc:
        attempted = (folder / "pixel-attempt.json").exists()
        terminal = state.get("remote_terminal") in app.TERMINAL
        update(status="unresolved" if attempted and not terminal else "error", error_type=type(exc).__name__)
        if not attempted and reservation.exists():
            app.save(reservation, {"released": True, "reserved": 179.6, "reason": "No submission attempted"})

