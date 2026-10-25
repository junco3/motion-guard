"""Real Comfy scheduling and video serialization; numerical LTX delegates are stubs."""
import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(os.environ["MG_PROJECT_ROOT"])
sys.path[:0] = [str(ROOT), str(ROOT / "core")]
from comfy_nodes import stage_audit as audit
from comfy_api.latest import io
from comfy_extras.nodes_lt_upsampler import LTXVLatentUpsampler
from comfy_extras.nodes_custom_sampler import SamplerCustomAdvanced

# Confined to this owned CPU test process; production source is unchanged.
LTXVLatentUpsampler.execute = classmethod(lambda cls, samples, **kw: io.NodeOutput(samples))
SamplerCustomAdvanced.execute = classmethod(
    lambda cls, latent_image, **kw: io.NodeOutput(latent_image, latent_image))


class AuditProbeInputs:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"run_id": ("STRING",), "verdict": ("STRING",)}}
    RETURN_TYPES = ("MG_REPORT", "LATENT", "LATENT_UPSCALE_MODEL", "VAE",
                    "NOISE", "GUIDER", "SAMPLER", "SIGMAS")
    FUNCTION = "run"
    CATEGORY = "test"

    def run(self, run_id, verdict):
        path, _ = audit.manifest(run_id)
        sources = {}
        for role in ("reference", "generated", "gt"):
            target = path / role
            target.write_bytes(role.encode())
            sources[role] = {"path": str(target),
                             "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
        failures = ([{"type": "motion_omission", "frames": [24, 47],
                      "t_start_s": 1, "t_end_s": 2, "evidence": {}}]
                    if verdict == "FAIL" else [])
        report = {"schema_version": "mg-report-2", "verdict": verdict,
                  "failures": failures, "uncertain_reasons": [],
                  "metrics": {"fixture": True}, "sources": sources}
        envelope = {"report": report, "stage_context": {"stage_id": run_id, "sources": sources}}
        return envelope, {"fixture": True}, {}, {}, {}, {}, {}, {}


class AuditProbeVideo:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"latent": ("LATENT",)}}
    RETURN_TYPES = ("VIDEO",)
    FUNCTION = "run"
    CATEGORY = "test"

    def run(self, latent):
        import torch
        from comfy_extras.nodes_video import CreateVideo
        return tuple(CreateVideo.execute(torch.zeros((97, 32, 32, 3)), 24).result)


NODE_CLASS_MAPPINGS = {**audit.NODE_CLASS_MAPPINGS,
                      "AuditProbeInputs": AuditProbeInputs,
                      "AuditProbeVideo": AuditProbeVideo}
