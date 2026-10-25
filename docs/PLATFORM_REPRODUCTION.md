# Cloud first, then Developer Platform

Fresh-account paid execution and quote bootstrap: not automated / not verified on a fresh account.

For Cloud, follow README key/provisioning instructions and select `cloud_local_guard`.
This runs a draft followed by local Guard and needs no custom build or storage quote.
It does not perform the in-graph Stage2 gate. See the provider Cloud API status link
in README before setting up a new account.

## Developer Platform reproduction

This source bundle includes both the Cloud app and the guarded Platform runner,
full API graph, custom nodes, current core and a build recipe. It contains no
account key, private blob, release ID, weights or owner authorization. A second
account live deployment has not been tested. The original same-run PASS →
official Stage2 → app retrieval was verified. Stage audit records also show FAIL
executions with no follow-up stage entered or completed. Billing savings have not
been established by a controlled measurement.

## Install without spending

Follow README for the Python/Node/ffmpeg environment. Then install the Platform CLI:

```powershell
.venv/Scripts/python -m pip install -r requirements-platform.txt
git clone https://github.com/Lightricks/ComfyUI-LTXVideo workflows/T5/custom_nodes/ComfyUI-LTXVideo
git -C workflows/T5/custom_nodes/ComfyUI-LTXVideo checkout 44c8a36b7c31ee00b4271daed11dc2a4aa481140
```

Obtain the licensed LTX2.5 audio/video VAEs using your own access. The template
records exact filenames, sizes and SHA-256 values. Replace the two
`REQUIRED_ACCOUNT_MODEL_SOURCE/...` entries with your own accessible model URL or
your own uploaded blobId (remove sourceUri when using blobId). Do not use another
account's private blobs. Model and upstream node licenses remain separate from
the Apache-2.0 app code.

Copy `workflows/T5/comfy-build.template.yaml` to `comfy-build.yaml` in the same
directory only after those sources are configured. The installed comfy-cli 1.22.0 exposes these commands:

```powershell
.venv/Scripts/comfy.exe build validate workflows/T5
.venv/Scripts/comfy.exe build push workflows/T5 --dry-run
# Only after separately authorizing provider build/storage charges:
.venv/Scripts/comfy.exe build push workflows/T5 --release --target linux/nvidia
.venv/Scripts/comfy.exe build show workflows/T5
```

Read returned build/release IDs and artifact status; never copy another account's IDs.
For Layout substitute workflows/Layout after completing its model sources. This can incur provider build/storage costs:
review the provider's quote and obtain the operator's authorization first. This
bundle performs none of these operations automatically. Check install.py's
encoder/ONNX preflight and a ready Linux/NVIDIA release. Set your actual build_id
and release_id in `config/guarded-runtime.json`. The runner rejects a release
whose owning build differs. A missing build_id fails before credential access.

## Explicit paid app mode

### Optional Layout comparison

The source bundle also includes the owner-approved Layout comparison path:
`workflows/T1/layout-i2v.api.json`,
`workflows/Layout/comfy-build.template.yaml`, and disabled
`config/layout-runtime.json`. This is a separate release from Pose, not a silent
fallback. The original account completed a real Layout draft, Guard PASS and
official Stage2 output; a new account's paid reproduction is not verified.

Reuse the pinned LTXVideo checkout and MotionGuard sources under `workflows/T5/`
described above. The Layout build template references those directories relatively.
Configure its three `REQUIRED_ACCOUNT_MODEL_SOURCE/...` entries (Layout adapter
and both VAEs) from your own licensed access. Preserve all recorded model hashes.
Copy the configured template to `workflows/Layout/comfy-build.yaml` and follow
the same authorized Build/Release procedure. Do not copy an existing account's IDs.
Set your Layout build/release IDs in `config/layout-runtime.json`; retain the
shipped template and stage-audit hashes, `generator_mode:layout`, H100 and
`max_frames:97`. It starts disabled and contains no previous execution claim.

Obtain the matching account-owned storage quote and complete budget setup below
before enabling it. The shared storage quote must match the selected release;
a Pose quote is not a Layout quote. After all preflight checks pass, select the
Layout processing option in the app and use 4 seconds (97 frames, 24 fps).
The app renders the actual 960×544 layout/reference and matching 3D coordinates;
use a character image aligned to the first-frame composition. Expected Stage2
output is 1920×1088. Longer Layout clips are rejected. A PASS continues to Stage2;
FAIL/UNCERTAIN holds it. This is motion transfer and inspection, not automatic
motion repair. Each click uses the existing bounded paid-job policy; installation
and documentation do not authorize a paid run.

First provision your unused copy with your own API key and budget using README.
Never run provisioning on an existing history. For Platform use, additionally
set `max_deployment_active_minutes:10` and `max_storage_charge:2` in the JSON
budget file. Keep600-second cancellation and no additional purchase. The runtime
reserves 202 credits for RTX or 280 for an explicitly configured H100 per attempt,
plus the separate storage reservation. Do not copy the original one-run
1200-second/404-credit approval. Cold startup consumes this time and may prevent
completion. The local timeout is not a provider-enforced billing cap.

Keep `guarded-runtime.enabled=false` until the storage quote prerequisites below,
your release, source manifest and cumulative budget have all been checked.
Only then set it to true and set `config/application-mode.json` mode to
`platform_guarded`.
Start `server/app.py`; the existing Generate button prepares the graph from the
captured 4/10/20/30-second timeline at 24fps, 768×512, and creates a unique execution ID.
The inclusive endpoint produces 97/241/481/721 frames respectively. Longer runs
remain subject to startup time and the same 600-second deadline. It fills the
image, control video, reference video and actual GT JSON; the shipped `{}` GT
placeholder is intentionally not a runnable example. PASS continues to official
Stage2; other verdicts stop at the graph gate. The audit records stage entry and
completion; it does not measure all GPU work or prove billing savings.
No automatic retry or account purchase is implemented.

The server uses `app_guarded.prepare_execution` → `run_guarded_platform.run`.
Do not invoke the legacy run_platform_once entry point without prepared inputs.
Results remain under data/gen. Recover existing executions through app startup;
recovery performs cleanup/accounting/result retrieval, not resubmission.
Preserve ambiguous reservations until cleanup and accounting are confirmed.

The bundled custom node contains the JSON-key digest fix made after the original
integration run. Local tests cover it; its new Build has not been deployed on a
second account. Do not describe source availability as another live deployment.
## Model retention and restart

The guarded runner retains its owned stopped deployment within one fixed 30-minute
storage lease. A later request can restart that same deployment only when at least
its execution deadline plus 60 seconds remains. Starting another request does not
extend the lease. Compute reservations remain per execution; the storage reservation
is counted once in the cumulative ledger before creation. The supervisor verifies
deletion at lease expiry. A local supervisor cannot enforce a remote spending cap
while the PC is off or the network is unavailable.

Retention requires an account-owned, hash-pinned provider storage quote for the
same release (`config/platform-storage-quote.json`). The local owner's quote and
deployment history are deliberately excluded from the review bundle. Model download
bytes are not silently treated as billed storage. A quote above the pinned ceiling,
an invalid or missing quote, unknown ownership,
expired lease, or unavailable supervisor prevents another paid start. No automatic
replacement deployment or video retry is submitted after an ambiguous failure.

Before enabling Platform mode, obtain your own provider deployment/release storage
quote and current compute catalog through your authenticated Platform SDK. Obtaining
the first deployment quote may itself require separately authorized paid preparation;
this bundle does not automate that bootstrap and a fresh-account bootstrap is not
verified. Keep Platform disabled if the quote cannot be obtained. Cloud mode does
not require this Platform file.

Save the unmodified deployment snapshot beneath `data/gen/<your-run>/`, then create:

```json
{
  "release_id": "<your release ID>",
  "evidence": "data/gen/<your-run>/deployment-snapshot.json",
  "sha256": "<SHA-256 of the snapshot bytes>",
  "storage_monthly_cents": "<numeric storageMonthlyCents from the snapshot>",
  "credits_per_cent": 2.11,
  "catalog_credits_per_gb_month": "<numeric current network_standard creditsPerGbMonth>"
}
```

The two numeric placeholders must be JSON numbers, not strings. The evidence must
contain exactly one `releases` entry with `current:true` and the matching `releaseId`.
Its `storageMonthlyCents` must match the pinned value. The current catalog must
contain exactly one `network_standard` storage rate matching the pinned rate.
Use `Get-FileHash -Algorithm SHA256` to obtain the evidence hash. Do not substitute
another account's quote or estimate model file sizes as billed storage. The runner
reserves a full hour of storage before creation while retaining models for at most
30 minutes; this reservation is separate from compute and must fit the same budget.

`server/run_reuse_probe.py` is an explicitly paid, one-shot lifecycle diagnostic,
not a demo launcher: create, ready, stop, restart the same deployment, and verify
cleanup. It records restart transfer estimates separately from readiness, and does
not submit a video workflow. Do not run it without an existing cumulative budget,
release configuration, and storage quote.

The diagnostic supports `--gpu h100-sxm` with a 600-second/280-credit reservation,
or `--gpu h100-sxm --deadline-seconds 450` with 450 seconds/210 credits.
Storage is reserved separately. These alternatives are restricted to the lifecycle
diagnostic. Ordinary generation separately supports its configured RTX or H100
policy with a fixed 600-second deadline. These examples do not authorize
a new paid run or promise GPU availability.

On 2026-10-20 the owner verified the 450-second H100 path: the same stopped
deployment returned to ready, the restart estimate reported 71,914,405,655 bytes
held and zero bytes to fetch, and stop/estimate/start-to-ready took 93.759 seconds.
The deployment was subsequently deleted. Staging states were still observed;
zero estimated fetch is not a measurement of all network traffic. This test
submitted no video workflow and does not validate every GPU or account.


## Storage example and cost interpretation

Copy `config/platform-storage-quote.example.json` to `config/platform-storage-quote.json`
only after obtaining your own snapshot. Nulls are deliberately invalid; fill them
with numeric provider values and the exact snapshot SHA-256. Keep the original
snapshot under `data/gen`. No first-account quote acquisition is automated.

The code reserves `ceil(storageMonthlyCents * 2.11 / (28 * 24))` credits for one hour,
not merely the 30-minute retention lease. This is an accounting reservation, not a
provider-enforced cap. Compute adds 202 credits for RTX or 280 for H100 per ordinary
600-second attempt under the pinned policy. These are implementation ceilings,
not a promise of future provider pricing. A changed quote is rejected.

Model source URLs, byte sizes and SHA-256 values are in each build template.
The transformer is BF16, not a GGUF substitute. The text encoder, transformer,
control/optional Layout adapter, upscaler and audio/video VAEs collectively account
for roughly 72 GB before runtime overhead. Download permission is not permission
to redistribute; consult docs/licenses.md. Missing VAE/adapter sources must
be supplied by the operator, never replaced with the original owner's blob IDs.

## Exact model sources

| Component | Decimal GB | Provider source and terms |
|---|---:|---|
| LTX-2.5 BF16 transformer | 42.018 | [Lightricks LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5); LTX-2.x community license |
| Gemma 4 with LTX projection | 26.264 | Pinned BF16 mirror URL in template; [Gemma model card](modelcard-gemma-4.md) |
| LTX latent x2 upscaler | 0.996 | LTX-2.5 model card and pinned template URL |
| Union Control adapter | 0.654 | [Lightricks Union Control](https://huggingface.co/Lightricks/LTX-2.3-22b-IC-LoRA-Union-Control); LTX-2 community license |
| Audio VAE (required own source) | 0.365 | [Lightricks LTX-2.5 files](https://huggingface.co/Lightricks/LTX-2.5/tree/main); LTX-2.x community license |
| Video VAE (required own source) | 1.472 | Same Lightricks LTX-2.5 provider; LTX-2.x community license |
| Layout adapter (Layout only, required own source) | 1.309 | [Layout-to-Render](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render); LTX-2.x community license |
| RTMPose + detector | Additional checkpoint bytes | Pinned Tau-J URLs in template; code Apache-2.0, checkpoint rights separate |

The three required source placeholders are audio VAE, video VAE and Layout adapter.
Provider packaging can differ from the split files in the build: provide files with
matching filenames, sizes and SHA-256 values. An arbitrary similarly named model is
not interchangeable. The exact pinned mirror paths are reproducible download
references, not a claim that the mirror is the original publisher.
