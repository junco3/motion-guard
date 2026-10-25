# Historical verification log

Historical paths below are owner-workspace/user-generated evidence, not bundled files.
Statements describe their recorded version, not the v2 completion state.

# Motion Guard — 3D motion to inspected video

Windows creative app: upload a GLB animation and a character image, choose a camera and prompt, and generate a real LTX MP4. The configured default is Comfy Developer Platform: draft → motion inspection → upscale on PASS. It requires a configured release. The separately selected Cloud mode generates a draft, inspects locally, and offers an explicit paid RealESRGAN 2× button for PASS results. The app never silently switches providers or automatically retries.

## Long timelines, hosted Space hardening — 2026-10-24

Live Space runs (Linux, judge path: open the URL, pick a motion, upload an image, Generate) exposed
Linux-only and length-only problems that the Windows app never hit:

- Input checks read `st_file_attributes`, which Linux lacks (`AttributeError` before any job). A
  portable `reparse_point()` keeps the same Windows behaviour.
- The bundled spend ledger was pinned to the owner's local key; the Space holds its own key of the
  same account. `MG_REBIND_LEDGER=1` rebinds it at start-up with cumulative credits and the ceiling kept.
- Every guarded run had a 600 s deadline. 10 s runs already took 370–600 s (two ended at 600 s) and the
  2026-10-21 30 s attempt failed with "Deployment startup exceeded 600s". Deadlines and credit
  reservations now scale with the timeline (`platform_preflight.guarded_limits`): 4 s 600 s/280,
  10 s 900 s/420, 20–30 s 1800 s/840, 40 s 2400 s/1120 (H100 at 1314.53 credits/hour). The 20000
  cumulative ceiling is unchanged.
- The provider accepts at most 10 MB per job and the reference GT travels inside the workflow (10 s ≈
  8.2 MB, so 30 s would have been rejected). `server/gt_compact.py` drops fields no reader uses and
  rounds joint/hand/camera floats to 1e-5 (frame times stay exact): a 10 s GT goes from 4.78 MB to
  2.09 MB, about 8.3 MB at 40 s. Re-judging saved runs with original vs compact GT gave identical
  reports (PASS `t3-b4f0…`, FAIL `t3-c2ff…`).
- That estimate was low: the first 40 s Space run (`t3-88b4…`) stopped before any spend with
  "Reference data too large for one job". The compactor now also drops hand `surface_evidence` and
  `name` (compare matches hands by index and reads evidence for body joints only), joint `camera`
  (reprojection uses world + frame camera), body evidence for joints `eligible()` already rejects, and
  rounds pixels to 1e-3. The workflow estimate at 961 frames is 8.32–8.85 MB against the 9.5 MB check.
  Re-judging the same two runs again gave identical reports, reprojection still passes and 431 tests pass.
- Space results after that change (Space commit `54f42ccc`, release `37532dab`):
  - 40 s `t3-fd78…`: PASS, upscale complete. Final is 1536×1024, 961 frames, 40.04 s.
  - 30 s `t3-2220…`: PASS, upscale complete. Final is 1536×1024, 721 frames, 30.04 s.
  - Live deployments afterwards: 0.
  - Upscale specks: none in either final. The speck counter flagged one object that the generator drew at the
    frame edge for ~0.3 s (40 s: top-right, frames 849–855; 30 s: right edge, frames 609–616). The same
    object is in the 768×512 draft, so it is generated content, not an upscale artifact.
  - The 40 s output stands hunched with the head bowed while the reference stands upright, and it
    passed. Correction of an earlier note here: the hold is judged. The whole-clip PCK average uses
    the 20 moving frames, but the per-joint sustained-error check (`compare.py` 271–296) covers every
    frame; its longest run was 3 frames (40 s) and 4 frames (30 s) against the 6-frame failure length.
    The miss comes from scope: nose, neck, eyes and ears are excluded (`compare.py` 205, 212), body
    joints are 2D positions, and torso bend is not measured. Both reports are PASS under the
    calibration-candidate visibility policy with strict verdict UNCERTAIN and provisional thresholds.
- Background-object warning (`server/background_check.py`, quality only, never the verdict): after the
  check completes the Space compares each draft frame with the draft's own median background, outside
  the reference person region moved by the report's framing alignment, and reports regions that appear
  and disappear inside the clip. On saved runs it flags the 40 s objects at frames 529–536 (bottom
  left, missed by eye at first) and 849–856, the 30 s ones at 513–520 (faint, unconfirmed) and
  609–616, and two in an earlier local 30 s run (`t3-430f…`, 545–552 and 609–616). All 22 other
  flat-background saved runs are clear; 17 textured (real-footage) runs are reported as not checked.
  The difference cut (summed RGB > 90) is the existing speck counter's. The 1 s transient limit, the
  flat-background limit (background spread 12; flat runs measured 0.8–1.6, textured ≥ 40) and
  dropping regions that touch the person were added after seeing false hits on these saved runs, so
  they are not calibrated.
- Every flagged object spans exactly 8 frames starting at frame 16k+1 (513, 529, 545, 609, 849), and
  609–616 recurs in two different 30 s runs. That matches one latent frame of the video model (8 pixel
  frames). It narrows where the object comes from but does not identify the cause.
- 10 s upscale re-check after the Stage2 sigma change (Space commit `6c6d27e1`): the gate must PASS for
  Stage2 to run, and it is not bypassed. PickUp_Table at 10 s on the Space: 1 PASS before the change
  (`t3-9a7c…`, the one with specks), then FAIL `t3-c0e1…`, FAIL `t3-f614…`, FAIL `t3-e87a…`. The live
  background check ran on `t3-f614…` (241 frames, clear). The next attempt `t3-7be8…` passed (third 10 s
  attempt on this build): final 1536×1024, 241 frames, upscale specks 0/241 by the speck counter
  (the earlier 10 s final had 30/241 frames, 56 specks), the excluded centre band checked by eye at
  1, 3, 5, 7 and 9.5 s, background check clear. This is "no recurrence on a new 10 s input", not a
  regression pass on the original latent, which was not stored.
- Where the edge object comes from: local 30 s run `t3-430f…` kept its sampled Stage1 latent
  ([1, 128, 91, 16, 24]). At latent frame 69 (pixel frames 545–552) cell (0, 1) and latent frame 77
  (609–616) cell (0, 17) the latent jumps away from both neighbours and back: 11.3 and 13.3 against a
  frame median of 0.3, and those cells are exactly where the objects appear (top edge, x 32–64 and
  544–576). The pose guide video has nothing there. So the sampler writes a one-latent-frame spike; the
  decoder only shows it. `core/motionguard_core/latent_repair.py` finds cells that jump from both
  neighbours (ratio of jump to the neighbours' own change > 4; this latent: objects 16 and 18, no other
  cell in 91 frames above 4) and replaces them with the neighbours' mean. `MG_BindStage` applies it before
  the draft decode and Stage2 and the report carries the replaced cells under
  `stage_context.latent_repairs`. This changes the generated latent; it is a repair, not a warning. The
  ratio 4 comes from this one stored latent and is not calibrated. It needs a new remote release.
- The bowed head in the 40 s run: nose, neck, eyes and ears are excluded from the verdict, and the
  verdict's per-joint rule (0.1 torso for 6 frames) cannot simply include the nose — on the faceless
  mannequin the nose estimate wanders 0.12–0.19 torso, and that rule warned on 40 of 52 stored runs,
  PASS runs included. The 40 s hold stayed 0.51 torso from the reference head for 930 frames.
  `server/head_check.py` (Space side, warning only) uses the same alignment and lag tolerance with 3× the
  PCK distance held for 1 s: stored runs → 12 PASS clear, 7 UNCERTAIN clear, 13 FAIL clear, 7 FAIL
  warned; 40 s warned at 34–954; 30 s clear. Factor 3 and 1 s were chosen after seeing these stored runs,
  so they are not calibrated. The report now lists `not_evaluated: head and neck direction, torso bend`.
- Release `a85ad587` (2026-10-25) carries the latent repair and the `not_evaluated` report field; the
  Space uses it from commit `67cd11df`. The eight releases no configuration or enabled mode used were
  deleted (b15a95d5, e8b8f457, abe2add0, 42d29d6d, 5eb44525, 7f4b2514, 9b5015bd, ec765a98, 02c54d41);
  the layout mode that named ec765a98 / 9b5015bd was in fact still `enabled: true` in
  `config/layout-runtime.json` (it was only blocked by its readiness check); it is now set to
  `enabled: false`, so the screen shows that path as disabled. Run records that name those
  releases stay as history. The Space now keeps the remote stage context next to the check
  (`guard-*/stage-context.json`), which is where `latent_repairs` is visible.
- First 30 s Space run on `a85ad587` (`t3-e06fabd1…`, 2026-10-25 01:05–01:29 KST): the report carries
  `not_evaluated`, so the new release ran. Guard FAIL: left shoulder at 0.25–0.54 s (M1_joint_error 0.206)
  and one finger at 2.7–7.3 s (M9 0.607–0.629 against 0.6); upscale held. Background check clear on all
  721 frames; head check warned at 2.4–7.9 s (0.46 torso). The frames at the earlier object positions
  (545–552, 609–616) show no object, but this run used a different seed, and its `latent_repairs` record
  could not be read (no download route then; the deployment endpoint was gone after cleanup), so whether
  the repair fired is unconfirmed for this run. The guard download route now also serves
  `stage-context.json` (Space commit `11de1e89`). Release `37532dab` was deleted after this run; the only
  remaining release of build `549af8e0` is `a85ad587`.
- Second 30 s Space run on `a85ad587` (`t3-31a6b8dd…`, 01:37–01:59 KST): `stage-context.json` was downloaded
  and reads `latent_repairs: {method: single-latent-frame-spike-v1, cells: []}` — the repair found no spike
  and left the latent unchanged. Background check clear (721 frames), no object at the earlier positions.
  Guard FAIL: the generated figure is hunched with the head bowed for most of the clip (neck/shoulder
  M1_joint_error 0.126/0.165 over 15–714, one elbow 11–16, finger 79–229); head check warned 0.25–29.8 s
  (0.69 torso). Because no cell was repaired, this FAIL comes from the generation itself, not from the
  repair. Neither run on `a85ad587` showed the edge object, but neither contained a spike for the repair
  to act on, so the repair's effect on a real object is still verified only on the stored latent of the
  earlier run. Live deployments after both runs: 0.
- Third 30 s Space run on `a85ad587` (`t3-56f3f64c…`, 02:08–02:36 KST, owner-approved): `latent_repairs`
  lists four cells — latent 44 (3,23), 54 (14,21), 68 (0,6, top edge, ratio 17.3) and 72 (0,15) — i.e. the
  repair fired on a real generation. Crops of all four cells before, during and after their eight pixel
  frames show only background; background check clear, head check clear. Guard FAIL on one interval:
  frames 7–14, left shoulder/elbow (M1_pck 0.316). Side by side, the generated figure bends far forward for
  about 0.2–0.7 s while the reference stands; all three runs failed in the first 0.7 s. The second run
  repaired no cell and still failed there, so this comes from the generation, not from the repair.
- Examiner pass (2026-10-25): the source ZIP was unzipped into an empty folder and the README commands run
  in order. Install, 58 node tests, the offline sample reanalysis (FAIL, 5 cards, matches record) and the
  local server (page and sample video HTTP 200) worked, but two Python tests failed to import:
  `server/background_check.py` and `server/head_check.py` were missing from the package list. Added;
  rebuilt (199 files); 439 Python tests pass in the clean folder.
- The seed of the earlier 10 s run (`t3-9a7c…`) cannot be recovered: its execution plan was in the Space
  run folder that the restart removed, and the deployment that ran it was deleted by the sweep. Same-input
  reproduction of that case is therefore not possible.
- Space storage is not persistent: pushing a file restarts the Space and removes earlier run folders.
  The first 30 s result was lost this way before it was downloaded.
- 40 s (961 frames) needs the remote nodes to accept it. The first 30 s Space run generated the draft and
  then stopped in `MG_InspectDraft`: "Report artifact exceeds size limit" (the carrier allowed 4 MB; a 10 s
  report is about 2 MB). Release `37532dab-105c-4a18-8aed-0d383fcabd1a` was cut from build `549af8e0` with
  only `reference_io.py` (721 → 961 frames) and `report_artifact.py` (961 frames, carrier limit 16 MB) changed.
  The oldest unused release `dc0a1bfc` was deleted with the owner's approval to free the slot; the interim
  release `717bfd7b` from the same day was replaced by `37532dab`.
- A finished short run kept its deployment and storage lease for 30 minutes, so a longer run right after
  it was refused ("Existing storage lease requires cleanup"). With `MG_NO_RETAIN=1` the Space deletes every
  deployment after its run instead of retaining it.
- A finished run keeps its deployment stopped for 30 minutes for reuse; a Space restart in that window
  lost the supervisor and left it forever. With `MG_SWEEP_ORPHANS=1` the Space stops and deletes live
  deployments of the pinned release at start-up; the first restart deleted one such deployment and
  the account then had none.
- The 10 s Space run passed but its upscaled final had small dark specks in 30/241 frames (draft 0/241);
  the earlier sigma fix had been measured at 4 s only. Stage2 now starts at sigma 0.421875.
- The on-screen 3D playback re-ran the per-joint skinned raycasts on every frame (0.55 s each). Playback
  now skips them; the exported reference still runs them, now with skinned vertex positions computed
  once per frame instead of per ray (558 ms → 34 ms per frame, byte-identical output on 6 sampled frames).
- The judge access code was removed at the owner's request; the per-restart generation cap of 15 stays.

## Hosted judging Space and the PASS demo scene — 2026-10-23

`tools/build_space.py` assembles `dist/space` (about 1.07 GB): the app, the pose models, the T5
release spec and two saved real runs. The PASS run `t3-b4f0…` is upscaled; the FAIL run `t3-c2ff…` has its upscale held.
It was uploaded to the Hugging Face Docker Space `junco33/motion-guard` (protected, CPU Basic).
The Space build reached RUNNING. At https://junco33-motion-guard.hf.space both saved runs open with their
verdicts, error cards and downloads; this needs the moved-run lookup in `server/run_paths.py`.
The Space sets these environment variables:
- `COMFY_CLOUD_API_KEY` (secret, entered by the owner)
- `MG_ACCESS_CODE` (secret; paid actions return 403 without it)
- `MG_PUBLIC_HOST`
- `MG_MAX_GENERATIONS=15`
- `MG_FEATURED_RUN`

Unset, the local app behaves as before. A live generation from the Space has not been run here yet.
Demo scene S8 now shows that PASS run reaching "Upscale complete after check passed" (live app recording, 10 s).
It replaced the 4 s diagnostic re-analysis.

## PASS → Stage2 on release 02c54d41 and the Stage2 speck fix — 2026-10-23

The mannequin PickUp_Table input (front camera, 4 s) produced the release's first PASS → Stage2
runs: `t3-646b…` (PCK 0.95) and `t3-d359…` (PCK 0.92), both 1536x1024 with upsampler and sampler entered.
Their Stage2 outputs showed small dark specks on the flat gray background: 20/97 and 36/97 frames.
The drafts showed none (0/97). Earlier releases' PASS outputs (`t3-03c0…`, `t3-5c65…`, `t3-9a9a…`) had them too (24/97 each).
The Stage2 sigmas matched the bundled LTX-2.5 template, which re-noises from 0.909375.
The guarded template now starts Stage2 at 0.725 (`"0.725, 0.421875, 0.0"`). The template hash in
`config/guarded-runtime.json` is updated. The release itself did not change, because the graph is sent with each request.
Run `t3-b4f0e76d95e7433d9353016525ce911f`: PASS (PCK 0.80), Stage2 complete at 1536x1024, specks 0/97 frames.
Specks were counted outside the central 40% of the frame (blobs of 4–2000 px differing from the per-pixel median).
The cause of the specks is inferred from these counts, not isolated further.
`workflows/T1/pose-stage-diagnostic.api.json` keeps the original sigmas, because the diagnostic evidence pins it.
`tools/build_guarded_graph.py` rebuilds from that file and now sets the Stage2 sigmas itself.

## Platform release with the current Guard — 2026-10-23

The node bundle `workflows/T5` (time tolerance, per-joint checks, 3D-ground-truth finger
check) was released to the existing build `549af8e0` as release `cb4eb402` (replaced the same day by `02c54d41`, see below)
(linux/nvidia artifact ready). The build now stages the official RTMW archive
(`rtmw-dw-l-m_simcc-cocktail14_270e-256x192_20231122.zip`, sha256 `a6d08a57…139c`), so the
private deployment measures fingers without any download; the staged path was checked locally
with only the pinned archives present. To free the workspace release slot (limit 10), the
never-used release `d6a87ae5` (no config or run references) was deleted with the owner's
approval. `config/guarded-runtime.json` now points at the new release; earlier Platform runs
keep the verdicts of their own releases.

First live attempts on this release: run `t3-183ca31e…` stopped before any deployment because
this PC lacked PowerShell 7, which the storage supervisor uses to read the DPAPI key (a
documented requirement; the supervisor was then given a `pwsh` on PATH). Run `t3-5edf9647…`
reused the build but the provider rejected the submission: the workflow was 21.2 MB against a
10 MB limit, because the exported finger ground truth carried diagnostic fields (world/camera
coordinates, surface evidence) for 42 points per frame. `web/director.mjs` now exports only the
fields the finger check reads (name, available, pixel, in_frame, visibility); the same 10-second
timeline shrinks from 19.7 MB to about 7.6 MB. No job was created in either attempt; the
second attempt did start and stop an H100 deployment, and its conservative 280-credit
reservation stays counted until settlement.
Run `t3-3e9737c3…` then generated on the GPU, but the in-graph inspection stopped at the
report carrier: the comparator writes `schema_version: mg-report-3`, which `stage_gate.py`
already accepted while `report_artifact.validate` still accepted only `mg-report-2` (the local
Compare path does not use the carrier, so this did not show locally). The carrier now accepts
the same versions as the gate, with a test, and the whole `MG_InspectDraft` node from the
release bundle was run on this PC with only the hash-pinned staged archives present: PASS on an
identical clip, fingers `measured`, carrier written without error. Release `cb4eb402` (old
carrier, never produced a result) was deleted and replaced by release
`02c54d41-4dd1-444f-a4dd-9851672286a4`, which `config/guarded-runtime.json` now names.

## Time-shift check — 2026-10-22

Guard now applies one clip-wide time shift (searched within the existing 0.25 s lag tolerance) before frame-by-frame scoring. Re-judging saved poses: the reference video delayed by 3 frames changed from FAIL to PASS (shift 3); scale, position, colour and photo-background variants stay PASS (the photo-background composite measured a 2-frame shift); the blurred/low-quality variant stays UNCERTAIN (ambiguous lag). Four unrelated public clips (dance, squat, talking, walking) stay FAIL or UNCERTAIN. Run t3-2d5a keeps its FAIL with shift 0, so its findings are unchanged. The cached 6b7a sample reproduces its recorded FAIL. Thresholds unchanged.

Per-joint pose check (same day, superseded below): when the whole-clip pose check passes, a body joint that stays beyond the position criterion for 0.5 s (12 frames) or more now fails as WRONG_POSE for that joint. Sustained-deviation lengths: rendered variants of the reference at most 2 frames; a real person's next squat repetition (public squat clip, repetition 1 vs 2, pseudo ground truth from the first repetition's pose estimate) at most 6 frames at 0.14–0.28 torso lengths; wrong motions 23–143 frames. A first 6-frame setting falsely failed that real repetition and was raised to 12 before release. An analytic case with both arms held differently for 1.7 s (71% whole-clip agreement, previously PASS) now FAILS. The real squat repetition is not a PASS either: it returns UNCERTAIN because M5 motion-energy windows need 6 consecutive frames faster than 0.02 torso lengths per frame with every selected joint above the score threshold, which this slow real squat never reached (pose agreement 90%, no failures). Verdicts of the variant and public clips above are unchanged; run t3-2d5a and the cached 6b7a sample already failed the whole-clip check, so their findings are unchanged. Fingers are not measured (18 body points, no hand points).

Method revision and fingers (2026-10-23): the 12-frame setting was a threshold patch, so the measurement itself was changed instead. Joints are compared with the nearest reference position within +/-0.25 s (edges excluded) and fail after six frames; missing motion uses 0.25 s window displacement against the best generated window within +/-0.25 s, counting only windows whose ground-truth movement exceeds 3x the clip's estimator noise; fingertips are compared as wrist-relative shapes in palm sizes (RTMW whole-body hand estimate, fail above 0.6 palm sizes for six frames). Results: the real person's next squat repetition (3.7 s, public squat clip, pseudo ground truth) now PASSES (pose agreement 90%) and its 2.0 s window is UNCERTAIN (periodic lag); squat versus walking FAILS; all rendered variants PASS except blur/low quality (UNCERTAIN, ambiguous lag); public clips stay FAIL/UNCERTAIN; run t3-2d5a FAILS including left thumb/index/middle finger findings; the cached 6b7a sample (no hand points) reproduces its recorded FAIL. Finger calibration on palms of ~14 px: correct variants stayed above 0.6 palm sizes for at most 2 consecutive frames and the real repetition for 1, wrong motions for 24-111. Analytic tests: both arms held differently for 1.7 s FAILS; one finger moved for 1.7 s FAILS on that finger only; a frozen clip with 2 px estimator jitter still FAILS as missing motion. After an independent review the per-joint missing-motion windows also received the +/-0.25 s tolerance. Effect on recorded runs: the cached 6b7a sample keeps FAIL and its five WRONG_POSE cards but loses one 7-frame left-shoulder missing-motion interval, so its expected-report.json was regenerated; run t3-2d5a keeps FAIL and its three WRONG_POSE cards, its left-shoulder missing-motion card shortens from frames 62-79 to 62-77 and the left-elbow card (121-126) disappears. The demo video records the earlier card set.

Finger check correction (2026-10-23): re-recording found false finger FAILs where both reference and AI hands were fists (estimator fingertip guesses inside the fist differ between renders; fingertip-to-wrist distances of fists 0.86-1.62 and open hands 1.63-2.06 palm sizes overlap at ~14 px palms). Fingers are now judged only where 3D finger ground truth shows the tip visible and the reference estimate agrees within 0.6 palm sizes. Finger ground truth for Cloud runs t3-15659207 and t3-a9bb7c50 was regenerated in Blender from the same authored scene (body joints reproduce the stored joints.json with 0.0 px difference) and stored as joints.hands.json. Results: t3-a9bb7c50 (earlier PASS) is PASS again; t3-15659207 FAILS on a sustained left-wrist offset (generated arms held away from the body), with no finger findings. Platform runs keep the verdict of the deployed node until it is redeployed.

## Latest direct demo — 2026-10-23 (Platform release 02c54d41)

Run `t3-c2ff085845604265b9af9412f823137b` (Comfy Developer Platform job `d5d3311d-c768-4ca9-a959-13cb0df0adc8`, release `02c54d41`): same GLB, motion `Walk_Pause_PickUp_Kneel_Gesture_10s`, 3/4 camera, 10 s, character image and prompt; Generate clicked once. The job succeeded; the in-graph Guard (current checks, staged hand model) returned FAIL with joint-named cards (left wrist / right knee, right wrist / left shoulder, left shoulder / right knee) and fingertip cards on both hands (fingers `measured`), and the stage audit proves the upscale stage was not entered (held). Scenes S2-S5 and S7 of the demo are recordings of this run; generation waiting and prompt typing are cut. The app server had been started before the report-carrier fix, so it first rejected the retrieved carrier; after a restart the same retrieved outputs were restored with `finish_outputs` (no new generation).

## Previous direct demo — 2026-10-22 (English UI)

Run `t3-2d5a1d5d28f745a380d4e4905c2c0b47` (Comfy Developer Platform job `b1d722ab-59eb-44e1-a043-def04b6769ff`): the app UI is now English (recorded with browser locale en-US). One continuous browser session loaded the GLB, picked `Walk_Pause_PickUp_Kneel_Gesture_10s` (3/4 camera, 10 s), added the character image and prompt, and clicked Generate once. The job succeeded after about 11 minutes; Guard returned FAIL (pose match 50% against a 60% threshold on the selected 0.67–0.71 s segment), the upscale was held, and the draft was downloaded and played. Scenes S2-S5 and S7 of the 115-second demo (`reports/v2-remediation/demo-v2/`) were recordings of this run until 2026-10-23; generation waiting and prompt typing are cut. S6 (Cloud run `t3-15659207`, FAIL) and S8 (4-second diagnostic Cloud run `t3-a9bb7c50`, PASS) were re-recorded on 2026-10-23 by pressing Compare on those saved runs in the app with the current local Guard; the analysis wait is cut.

## Earlier direct demo — 2026-10-22

Run `t3-6b7ab1a54e0448f6ad1e493daca04523`: actual GLB/image/prompt input, one Generate click, 241-frame output, FAIL finding selection at 2.92–3.21 seconds, synchronized comparison, held upscale, framing navigation and downloaded browser-compatible draft verified against the same run's preview/source hashes. See [evidence](reports/studio-delivery/final-demo-20261022/verification.json) and [110-second edited demo](reports/studio-delivery/final-demo-20261022/motion-guard-final-demo.mp4). The demo edits actual UI captures and output; generation waiting is omitted. User quality acceptance and publication remain pending.

Clean review-package installation passed 160 Python and 46 JavaScript tests and a local HTTP startup smoke check with paid generation disabled. This does not verify a new account's paid deployment.

## Earlier app verification — 2026-10-21

Use http://127.0.0.1:8712 on this PC while the server is running. The saved-result list places recent results first and distinguishes real generation, calibration material, and controlled defects.

- Continuous30second real generated video:721frames analyzed; FAIL with8overlapping joint-specific events. Playback marks left elbow/wrist in red and allows seeking each event. [Actual result](reports/long-continuous-result.json), [marker image](reports/long-error-markers.jpg).
- Actual app finalize requests on this FAIL returned held twice, with no pixel job submission or reservation. This is Cloud two-job follow-up prevention, not a claim about native LTX Stage2 internals.
- Existing real PASS returned a1536×1024,97frame RealESRGAN_x2plus final through the app. This optional paid2x button is explicit; it does not automatically retry generation or correct motion. [Evidence](reports/pixel-live-complete.json).
- 10second real generation passed; a separately labeled controlled freeze was detected after full video re-estimation. These limited examples are not general accuracy or all-error detection claims. Physical foot contact, faces, clothing and image artifacts are outside motion grading.
- The two30second diagnostic decoders both produced nonblack output. The previous all-black cause is not isolated, and the default decoder has not been changed on this evidence.

## Install and start
Requires Windows, Python 3.11, PowerShell 7 (`pwsh`), Node.js/npm and ffmpeg on PATH. Cloud generation needs no local GPU. Local motion analysis requires CPU RTMPose/ONNX checkpoints, downloaded on first use and cached. Tested here with Node 24.18. Other OSes and a clean second machine have not been verified.

From this directory in PowerShell:
```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r server/requirements.txt
.venv/Scripts/python -m pip install -e ".[pose]"
.venv/Scripts/python -m pip install comfy-cli==1.22.0 PyYAML==6.0.3
npm ci --prefix web
.venv/Scripts/python server/app.py
```
Open http://127.0.0.1:8712 yourself. The server does not open or focus a browser. Supported rig mappings: UAL and Cesium. Unknown GLB rigs need mapping; FBX/BVH is not supported. Select a moving animation and camera, upload a matching character image, enter a prompt, then Generate. Choose 4, 10, 20 or 30 seconds; capture uses 24fps with one inclusive endpoint frame. Results, comparison and download appear after completion. Draft output is 768x512. A short source action stops at its end unless Repeat is selected; choosing 30 seconds does not invent 30 seconds of source motion.

Motion Guard analysis runs locally on CPU. The `pose` extra installs the core and RTMPose/ONNX dependencies. The first analysis downloads the estimator checkpoints; allow network access and review the model licenses in `docs/licenses.md`. Cached models are kept in `data/models/rtmpose/hub/checkpoints`. Generation and analysis have separate statuses: analysis errors preserve the generated MP4. `UNCERTAIN` means insufficient evidence, not motion success. Existing successful runs can be analyzed without another paid generation.

## Authentication and cost authorization
Use your own Comfy API account/key, not the browser login alone. Store the key privately for the current Windows user (PowerShell; input is hidden):
```powershell
$credentialDir = Join-Path $env:LOCALAPPDATA 'MotionGuard'
New-Item -ItemType Directory -Force -Path $credentialDir | Out-Null
$credentialFile = Join-Path $credentialDir 'comfy-api-key.dpapi'
if (Test-Path -LiteralPath $credentialFile) { throw 'Existing key preserved; provision only when needed.' }
Read-Host 'Comfy API key' -AsSecureString | ConvertFrom-SecureString | Set-Content -LiteralPath $credentialFile
```
Never publish this file or print the key. DPAPI ties it to this Windows user. Generation is paid: this workspace has the owner's cumulative 10,000-credit authorization in `config/budget.yaml` (JSON syntax) and history in `config/t1-spend-ledger.json`. Do not reset or copy this authorization to a new account. A new operator must explicitly establish their own authorization and initial account balance/ledger before enabling generation. Existing pending or ambiguous jobs block new jobs. There is no purchase endpoint. The 600-second cancellation/watchdog is local protection, not a provider-enforced spending cap. Account billing can be delayed/shared.

For a **new unused review bundle only**, after storing your own key, explicitly authorize its cumulative 1,000-credit limit:
```powershell
.venv/Scripts/python server/provision.py --authorize-credits 1000
```
This reads billing and records the initial balance; it submits no generation. It refuses existing jobs/history, partial setup or enabled budgets. The key fingerprint detects credential changes, not account identity. Key rotation or a partial setup requires preserving and explicitly reviewing the existing ledger; rerunning this command never resets it. This workspace is already provisioned: do not run it here. The 2.11 credits-per-cent conversion is the existing accounting convention, not a guarantee of future provider pricing.

## Workflows and models
`workflows/T3/comfy-build.yaml` pins ComfyUI and the LTX custom-node source and records five model hashes. Transformer/text encoder public mirrors are byte-identical BF16 safetensors, not GGUF substitutions; two VAE blobs are private to the original account. Other accounts must acquire licensed originals and upload their own blobs/Build. See `docs/T3-model-license.txt`, `docs/licenses.md`, `reports/T3-model-resolution.json` and `reports/T3-exact-public-mirrors.json`. Cloud UI uses the provider's installed models. Developer Platform additionally uses comfy-cli 1.22.0 and PyYAML; it is a separate paid deployment lifecycle, not an installation smoke test. Do not blindly rerun the task-specific `server/run_platform_once.py` or staging/upload scripts.

## Verified product flow — 2026-10-21

The current in-app Motion Guard UI was operated through image upload, animation/camera/prompt selection, one actual Developer Platform generation, result inspection and download. Run `t3-7c5dc76a7b104b45a671ab88f411447e` generated a real draft; its Guard returned UNCERTAIN and its stage audit recorded no downstream stage entry. The downloaded draft matches the generated file by SHA-256. This is not a PASS or a completed upscale.

Separate saved cases verify the other branches: the 30-second real FAIL has eight clickable joint/time findings and blocks pixel finalization; the existing PASS has a real RealESRGAN 2x final, synchronized three-video playback/seek/restart, and a downloaded file matching the server output. These cases are explicitly distinguished in the [100-second narrated product demo](reports/studio-delivery/motion-guard-studio-demo.mp4). It is an edit of actual app screenshots and actual generated videos, not a continuous recording or a claim that all branches occurred in one run. See [verification record](reports/studio-delivery/verification.json).

The comparison player now waits for seek readiness before playing and cancels stale starts. Twenty-two related JavaScript checks passed. Installation and server checks from the preceding UI revision remain valid for unchanged components; a clean second-account paid deployment has not been performed.

The app is a motion inspection tool, not automatic motion repair. It identifies observable deviations, distinguishes insufficient evidence from failure, and returns usable draft/final files. General accuracy, every-error detection, physical foot contact and measured cost savings are not established. Faces, clothing and image artifacts are outside grading; fingers are graded only from the hand estimate (no finger ground truth). Current billing is shown from the provider; reservations are not actual spending.

## License and delivery

Original app code is Apache-2.0 ([LICENSE](../LICENSE)); models and assets retain [their own terms](licenses.md). The local review source archive includes UI, server, custom nodes, workflows, tests and account-neutral setup instructions. Paid execution is disabled in the unused distribution template; it contains no private credentials or active ledger. Public repository publication and competition submission remain the owner's actions.

Public sample inputs/outputs: [public_samples/README.md](../public_samples/README.md). Current plan: [PLAN_RECONVERGED_2026-10-19.md](PLAN_RECONVERGED_2026-10-19.md). Older experimental records remain in reports and PLAN.md; they are not the current product status.
