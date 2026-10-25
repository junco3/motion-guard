# License inventory

| Model | License metadata | Evidence |
|---|---|---|
| modelcard-gemma-4 | license: apache-2.0 | modelcard-gemma-4.md |
| modelcard-LTX-2.3-22b-IC-LoRA-Union-Control | license: other; license_name: ltx-2-community-license; license_link: https://github.com/Lightricks/LTX-2/blob/main/LICENSE | modelcard-LTX-2.3-22b-IC-LoRA-Union-Control.md |
| modelcard-LTX-2.5-22b-IC-LoRA-Layout-To-Render | license: other; license_name: ltx-2.x-community-license; license_link: https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x | modelcard-LTX-2.5-22b-IC-LoRA-Layout-To-Render.md |
| modelcard-LTX-2.5 | license: other; license_name: ltx-2.x-community-license-agreement; license_link: https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x | modelcard-LTX-2.5.md |

Some weights were privately staged for the recorded T3 Platform run. This does not grant redistribution approval. Revisions/LFS hashes in docs/*.json; use provider URLs rather than repackaging weights.
ComfyUI-LTXVideo workflow source/revision: workflows/upstream/source.json. Its actual license text is saved as [LTXVideo-LICENSE.txt](LTXVideo-LICENSE.txt), LTX-2 Community License dated January5,2026. Retain applicable notices and check terms before public redistribution.
Public sample candidate: Quaternius Universal Base Characters, CC0 per https://quaternius.com/packs/universalbasecharacters.html . The UAL1_Standard.glb animation was acquired and used; its CC0 notice is retained at workflows/T1/inputs/animation-license.txt.
CesiumMan rejected: CC-BY + trademark, conflicts with default CC0/self-created requirement. Evidence sample-cesium-man.md.
The bundled public_samples character is rendered from the CC0 mannequin. This does not describe every historical run. Representative 10-second character image (character-quarter-v1.png, SHA-256 5236d703…): generated with the image generation tool built into OpenAI Codex on 2026-10-21 (12:49 UTC). Its PNG provenance metadata reads ChatGPT / gpt-image; the exact model version is not recorded. OpenAI Terms of Use apply. It is AI-generated, not CC0 or public domain, and is not an open-weights output; see asset-provenance.json. It is excluded from the source ZIP.
RTMPose/rtmlib is installed and used on CPU. The rtmlib and MMPose code repositories declare Apache-2.0 (official LICENSE pages checked 2026-10-19); this does not by itself establish all checkpoint/training-data redistribution rights. Checkpoint redistribution is excluded from the review bundle. The finger check additionally downloads the RTMW whole-body checkpoint rtmw-dw-l-m_simcc-cocktail14_270e-256x192 (OpenMMLab, mmpose project; same code licence, checkpoint terms not separately established) on first local run. Sources: https://github.com/Tau-J/rtmlib/blob/main/LICENSE and https://github.com/open-mmlab/mmpose/blob/main/LICENSE . Original app code: Apache-2.0; see ../LICENSE and ../LICENSE_SCOPE.md. Third-party terms remain unchanged. Nothing published.
