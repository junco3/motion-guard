# Submission draft - not posted

## Why (three sentences)
Generated motion can look plausible while missing the requested action.
MotionGuard connects visible evidence to a decision about further processing.
It makes that decision inspectable in the same workflow that generated the video.

## How (five sentences)
Capture a reference from the 3D director and supply a prompt and character image.
An LTX draft is generated through Comfy.
MotionGuard compares observed pose against the reference and exposes sustained intervals.
On Developer Platform, a lazy gate permits Stage2 only for PASS and records held stages otherwise.
The user can inspect synchronized frames and download the output and report.

## Contribution and prior work
3D-conditioned video generation and pose comparison are existing techniques.
MotionGuard integrates its own 3D reference, valid-observation accounting, time-local evidence cards and a downstream stage gate. This is a workflow integration contribution, not a new video model or pose estimator.

## Social draft
AI video from 3D motion looks right until you check. Motion Guard starts from a 3D
animation, so it has a ground truth: it compares the generated clip with that reference,
names the seconds that drift (and the joints, when clearly observed), and holds the expensive Stage-2 render
when a draft fails. Open source, built on Comfy Developer Platform with LTX-2.5.
#OpenSourceHiggsfield
Demo: <FINAL_PUBLIC_DEMO_URL>
Try it: https://junco33-motion-guard.hf.space
Source: https://github.com/junco3/motion-guard

## Entry selection and owner checklist
Proposed: Most Innovative; LTX Video & VFX bonus where the final entry meets the rules.
Do not select Open Weights Only: the representative character image was generated with
the OpenAI Codex image tool (gpt-image), which is not an open-weights model.
Read the [official competition page](https://comfy.org/open-source-higgsfield/) at submission.
Official deadline (read on the competition page 2026-10-25): October 30, 2026, 9am PT = October 31, 01:00 KST.

Before posting: character provenance is recorded in docs/asset-provenance.json; review latest
demo and captions, replace both URLs with working public downloads, verify required
social wording/tags on the official form, select eligible categories and complete
the submission form. Public posting and submission have not been performed.
No general accuracy, automatic repair, zero-cost generation or measured savings claim.

## Required items on the competition page (checked 2026-10-25)
- GitHub repo with app code, workflow files, open-source license and local run instructions:
  public at https://github.com/junco3/motion-guard (LICENSE Apache-2.0, README, workflows/).
- Demo video, two minutes max: v2 is 115 s; public upload not done yet.
- A link to try it (optional, encouraged): https://junco33-motion-guard.hf.space
- Social post linking the demo video with #OpenSourceHiggsfield: draft above; not posted.
- Other tools and models must be explained in the demo video: v2 names LTX and the OpenAI image
  tool; the pose estimators (RTMPose body, RTMW hands) are not named in the video.
