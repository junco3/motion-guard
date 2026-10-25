# MotionGuard

**See where generated motion diverges, then decide whether expensive follow-up should run.**

Capture a 3D motion reference, enter a prompt and character image, generate with LTX,
inspect synchronized reference/result frames, and download the video and evidence.
The guarded Developer Platform graph places a motion check before Stage2:
PASS permits follow-up; FAIL or UNCERTAIN holds it. This is inspection and routing,
not automatic motion repair or a general video-quality score.

Try it: https://junco33-motion-guard.hf.space (hosted build; saved runs open without
charge, live generation runs on the owner's Comfy account).

Demo: <FINAL_PUBLIC_DEMO_URL> (115-second v2 with live app recordings and English narration;
public upload by the owner pending).

## Why
A plausible-looking clip can miss the requested action. A 3D reference makes the
comparison inspectable, and the gate connects evidence to a processing decision.

## Start locally, without generation charges

Use Windows, Python 3.11, Node.js 24, PowerShell and ffmpeg on PATH. Pose analysis
runs on CPU; this local setup does not require a local generation GPU. Model
weights are excluded. The optional Platform recipe uses about 72 GB of remote
weights; allow additional storage for the environment and outputs.

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r server/requirements.txt -r requirements-lock.txt
.venv/Scripts/python -m pip install -e ".[pose]"
.venv/Scripts/python -m pip install -r requirements-platform.txt
npm ci --prefix web
.venv/Scripts/python -m pytest tests -q
node --test --test-isolation=none tests/*.test.mjs
.venv/Scripts/python server/app.py
```

Open http://127.0.0.1:8712. The 3D viewer and bundled CC0 sample need no API key.
Run these commands from the extracted project root. OpenCV is included in the
pose extra. First pose inference may download checkpoints; cached-pose reanalysis
is a separate, offline check.

## Cloud first: your own account

Select the Cloud draft processing option (`cloud_local_guard`) for a draft followed
by local inspection. This avoids configuring a custom Platform build; it does not
provide the in-graph Stage2 gate. The source ZIP defaults to this option with paid
execution disabled. Save your own key in Windows DPAPI:

```powershell
$credentialDir = Join-Path $env:LOCALAPPDATA 'MotionGuard'
New-Item -ItemType Directory -Force -Path $credentialDir | Out-Null
$credentialFile = Join-Path $credentialDir 'comfy-api-key.dpapi'
if (Test-Path -LiteralPath $credentialFile) { throw 'Existing key preserved.' }
Read-Host 'Comfy API key' -AsSecureString | ConvertFrom-SecureString | Set-Content -LiteralPath $credentialFile
```

Only when you authorize paid use of your unused copy, run:
`.venv/Scripts/python server/provision.py --authorize-credits 1000`.
Provisioning records a baseline and does not generate a video. Never reset an
existing ledger. Generation requires an explicit button click and consumes credits.
The current Cloud integration predates the provider's v2 API recommendation;
existing-account operation does not certify fresh-account compatibility.
See [Cloud API status](https://docs.comfy.org/development/cloud/overview).

## Developer Platform: guarded Stage2

Follow [Platform reproduction](docs/PLATFORM_REPRODUCTION.md) for the pinned graph,
custom nodes, model sources, build/release commands, quote and budget configuration.
Use your own account and model access. Installation does not authorize a build,
deployment or generation. FAIL stage audit demonstrates held follow-up, not zero
GPU cost. Fresh-account paid deployment has not been verified.

## What the result means

The top summary shows whole-clip pose agreement and the configured threshold.
Cards show their own interval agreement and up to two sufficiently observed joints.
Intervals shorter than six frames are hidden from cards but retained in raw evidence
and in the verdict. `mg-report-3` adds display evidence; StageGate also accepts mg2.
A low-motion PASS is provisional: the strict observation policy says UNCERTAIN, and
the visibility policy that produced the PASS is a calibration candidate with
uncalibrated thresholds. It is not proof of accuracy on large movements. Head and
neck direction (nose, neck, eyes and ears are excluded), torso bend, facial detail,
props, background objects, physical contact and appearance are outside this motion
gate; body joints are compared as 2D positions.

Before scoring, Guard tries one clip-wide time shift of up to 0.25 s (the existing
lag tolerance) and keeps the shift with the smallest pose error, so a correct motion
that starts a few frames late is not failed frame by frame. The chosen shift is in
the report (`alignment`, `metrics.time_shift`) and is added back into M4's lag, so a
delay beyond 0.25 s is still a timing mismatch. This is one global shift, not DTW:
local speed changes inside the clip are still compared frame by frame.

The whole-clip pose average can hide one wrong body part (for example both arms
moving differently while the rest matches). So when the whole-clip check passes,
every body joint is also checked on its own: a joint that stays farther than the
PCK criterion from every reference position within +/-0.25 s (the existing lag
tolerance) for six frames is a WRONG_POSE finding for that joint. The time tolerance
absorbs the small early/late drift of a person who follows correctly; the first and
last 0.25 s, where only one side of it exists, are not judged by this check; a clip
too short to leave six judged frames is UNCERTAIN (`joint_check_clip_too_short`).

Missing motion (M5) is measured as displacement across each 0.25 s window, again
against the best-matching generated window within +/-0.25 s, using the selected
joints visible at both window ends. A window counts only when the ground-truth
movement exceeds three times the clip's estimator noise (median reference-vs-GT
error). This replaced per-frame speed, which gave a slow real squat no evidence.
The per-joint missing-motion windows use the same +/-0.25 s tolerance.

Fingers: a whole-body RTMW hand estimate (42 points, downloaded on first local run
like the body model) is compared per fingertip as a wrist-relative shape in palm
sizes, with the same time tolerance. A fingertip is judged only where the 3D ground
truth shows it visible and the reference estimate agrees with that truth within 0.6
palm sizes; tips hidden in a fist are estimator guesses and are not judged. A judged
tip off by more than 0.6 palm sizes for six frames is a WRONG_POSE finding for that
finger. The 3D exporter now records 42 hand points (UAL rigs); older runs use a
frame-aligned `joints.hands.json` regenerated from the same scene, whose body joints
reproduce the original ground truth exactly. Without finger ground truth the report
says fingers were not measured. Limit: with ~14 px palms, a reference fist against
an open AI hand cannot be told apart reliably and is not claimed. When hands are
hidden or too small for six judged frames, the report says
`insufficient_hand_evidence` and the verdict rests on the body checks.
The staged platform node never downloads: the build stages the official RTMW archive
(hash-pinned in `staged_models.py` and `comfy-build.yaml`) beside the body models. A
release without that archive reports fingers as not measured.

Developer Platform mode runs Guard inside the deployed custom node, so it uses the
Guard version of that deployment; the app's Compare button reuses the remote result.
The current node bundle (`workflows/T5`, release `a85ad587`, set in
`config/guarded-runtime.json`) carries the time-tolerance, per-joint and finger checks,
the staged hand model, timelines up to 961 frames (40 s), a repair of single-latent-frame
spikes in the Stage1 latent (reported as `latent_repairs`), and a `not_evaluated` list in
the report. Platform runs made on earlier releases keep their verdicts. Cloud mode
analyzes locally with the current code.

The saved FAIL run (`t3-c2ff…`, earlier release `02c54d41`) shows joint-named pose cards
and fingertip cards on both hands; its stage audit shows the upscale stage was never entered.

Two warnings sit beside the verdict and never change it: a background-object warning
(things that appear and disappear in the draft's empty background, outside the person)
and a head-position warning (the nose stays far from the reference for over a second).
Both are uncalibrated; see [verification log](docs/VERIFICATION_LOG.md).

An earlier recorded 10-second run shows a FAIL with five sustained pose intervals plus
one missing-motion interval. Three visible differences concern transition timing,
upper-body/hand placement, and the kneel/squat transition. M4's lag estimate is
ambiguous; a visually estimated 0.5-second delay is not a measured claim.
No general accuracy or billing-savings percentage is claimed.

## Costs and storage

| Path | Local reservation per attempt | Storage |
|---|---:|---|
| Cloud draft | 179.6 credits under the current app policy | Provider-managed |
| Platform RTX | 202 credits / 600 seconds | Own quote; one-hour storage reservation |
| Platform H100 | 280 credits / 600 seconds | Same quote policy; about 72 GB weights |

Cumulative ceiling is the amount explicitly provisioned by the operator. Storage
adds `ceil(monthly cents * 2.11 / 672)` credits; timeout and lease are local controls,
not provider-enforced billing caps. See Platform reproduction for bootstrap limits.

## Offline representative reanalysis

```powershell
.venv/Scripts/python tools/reanalyse_sample.py
```

This reads bundled 6b7a pose/GT arrays and verifies FAIL, five pose cards and exact
raw/display evidence against the recorded result. Output is user-generated:
`data/sample-reanalysis/report.json`. It does not rerun pose inference or include
the representative character video. The separate CC0 sample videos can be played
from public_samples or through `/public_samples/reference.mp4` and
`/public_samples/generated.mp4` on the local server.

## Source, samples and rights

- [CC0 input/output sample](public_samples/README.md)
- [License inventory](docs/licenses.md), [NOTICE](NOTICE), [code license](LICENSE)
- [Representative character provenance](docs/asset-provenance.json): AI-generated with the
  OpenAI Codex image tool (PNG metadata: ChatGPT / gpt-image, version not recorded; OpenAI
  terms apply). That character/video is not included in the source ZIP.
- [Submission notes](docs/SUBMISSION_DRAFT.md): competition entry notes and required-item checklist.

Source: https://github.com/junco3/motion-guard (this repository). Credentials, account IDs,
model weights and private result history are excluded.
