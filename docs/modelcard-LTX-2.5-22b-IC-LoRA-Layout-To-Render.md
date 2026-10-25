---
base_model:
- Lightricks/LTX-2.5
base_model_relation: adapter
license: other
license_name: ltx-2.x-community-license
license_link: https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x
language:
- en
tags:
- lora
- ic-lora
- video-to-video
- ltx-2.5
- layout-to-render
- camera-control
- ltx
pipeline_tag: video-to-video
extra_gated_description: >-
  By clicking "Agree and Access" you acknowledge the [Privacy
  Policy](https://static.lightricks.com/legal/Privacy%20Policy%20-%20LTX%20Platform.pdf) 
  and consent to receive offers and updates. You can unsubscribe at any time.
extra_gated_button_content: Agree and Access
widget:
- text: >-
    A rustic stone well sits in summer grass as the camera slowly pulls back
    from the basin. Hot midday sun, golden-tipped blades, small white
    wildflowers, dry moss on the stone, a wooden bucket hanging over dark water,
    weathered posts and a fence behind. Match the first frame: high summer, dry
    heat, daisies, no snow. Keep the same well, bucket, posts, and camera as the
    driver. Photoreal, real stone and grass.
  output:
    url: examples/summer.mp4
- text: >-
    A grassy shoreline with wildflowers and reeds next to a calm pond, backed by
    a dense forest of vibrant yellow and orange autumn trees under warm
    sunlight.
  output:
    url: examples/forest.mp4
- text: >-
    Two men in dark coats stand with their backs to the camera in a night
    apartment, looking through floor-to-ceiling windows at a city skyline. Warm
    lamps, a wood floor, and a dark wood ceiling.
  output:
    url: examples/blocking.mp4
---

# LTX-2.5 22B IC-LoRA Layout to Render

This is a **Layout to Render** IC-LoRA trained on top of [LTX-2.5-22B](https://huggingface.co/Lightricks/LTX-2.5). It turns a 3D viewport animation into a finished shot. Give it a grey clay viewport, or a blocky playblast of simple shapes, from Blender, Unreal, or a similar 3D tool, carrying the camera move and the objects. Give it a first frame that sets the art direction. It returns a video that moves like the layout and looks like that first frame.

It keeps the camera path and the placement of objects from the layout. It is suited to workflows that value that alignment and that precision.

It is based on the [LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) foundation model.

## Example Outputs

<Gallery />

## Model Files

- `ltx-2.5-22b-ic-lora-layout-to-render-1.0.safetensors`.
- `LTX-2.5_ICLoRA_Layout_To_Render_Two_Stage_Distilled.json` — the ComfyUI workflow for this model.

## Model Details

- **Base Model:** LTX-2.5-22B Video
- **Training Type:** IC-LoRA (video-to-video, reference-conditioned), rank 128, BF16
- **Control Type:** a 3D viewport animation or playblast supplies the camera, the motion, and where objects sit. It can be a detailed clay render or a blocky animation of simple shapes, from Blender, Unreal, or a similar 3D tool. 
                    A first frame and possibly more additional keyframes supply the art direction and details.
- **Pipeline details:** See Pipeline Details at [ic_lora.py](https://github.com/Lightricks/LTX-2/blob/main/packages/ltx-pipelines/src/ltx_pipelines/ic_lora.py).

## Intended Use

Turn a 3D viewport animation into a finished shot without re-lighting or re-texturing the scene. The layout can be a clay viewport render or a blocky playblast of simple shapes. Use it for look development and camera-accurate shot iteration. It is suited to workflows that value alignment and precision.

## Control Signal Requirements

- **Control signal type:** A 3D viewport animation or playblast, for example from Blender or Unreal. This can be a detailed clay render, or a blocking animation built from simple shapes. A detailed clay render is not required.
- **Expected input:** The driving clip. It supplies the camera and the movement. Prefer 24 fps. Width and height must divide by 64. 1920×1088 is a known good size.
- **Keyframes:** The picture (or pictures) that sets the art direction: palette, lighting, and materials. Take the first frame of the clay animation and give it to any image model to generate the visual you want. Those images go in as keyframes. Do not use the grey clay frame itself.
- **Preprocessing:** Frame count is snapped to 8×k+1. A 72-frame, 3-second, 24 fps clip becomes 65 frames. That trim is part of the recipe.
- **Alignment:** The output keeps the camera and where objects sit, including the motion of simple shapes in a blocking animation.

## How It Works

The layout clip sets the camera, the motion, and the framing, and it keeps objects in place. The image sets palette, lighting, and materials.

A clay viewport render works as the layout. A blocky playblast of simple shapes works too, from Blender, Unreal, or a similar 3D tool, and the model keeps that movement and that camera. A detailed clay render is not required.

The camera path and the placement of objects stay aligned through the shot.

Take the first (or more) frame of the clay animation and give it to any image model to generate the visual you want. Do not feed the grey clay frame in as that picture.

## Usage

### ComfyUI

1. Copy the adapter into `models/loras`.
2. Install the [ComfyUI-LTXVideo](https://github.com/Lightricks/ComfyUI-LTXVideo) custom nodes.
3. Open `LTX-2.5_ICLoRA_Layout_To_Render_Two_Stage_Distilled.json`. This is the graph for this model.
4. Load the **LTX-2.5-22B** distilled base weights from [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5): the distilled transformer, the `gemma4-12b-with-proj` text encoder, the video and audio VAEs, and the x2 latent spatial upscaler.
5. Add `ltx-2.5-22b-ic-lora-layout-to-render-1.0.safetensors` as the LoRA at strength **1.0**.
6. Set **Load layout video (Clay Video)** to the grey animation. Set the first frame to the image you made from the clay’s first frame. In the graph that box is still labeled **Load reference image (Look Still)**. That input is the first frame.
7. Write a short prompt that describes the first frame, and run.

## Pipeline Details

This model uses a dedicated two-stage distilled pipeline.

- **Stage 1** — 960×544, 8 steps.
- **Stage 2** — 1920×1088, 3 steps. The latent is upscaled 2×, then a short second pass runs at full resolution.

The first frame is placed at a temporal position of -1, any keyframe provided is used on both stages. CFG is **1**. Sampler is `euler_ancestral`. Seed **42** was used for the published examples.

For example:
```
python -m ltx_pipelines.ic_lora \
  --prompt "..." \
  --output-path out.mp4 \
  --video-conditioning clay.mp4 1.0 \
  --lora lora.safetensors \
  --stage-2-ic-lora \
  --image img.png -1 1.0 \
  --image img2.jpg 36 1.0 \
  --height 1088 --width 1920 \
  --num-frames 81 \
  --frame-rate 24
```

## Recommended Settings

- **LoRA strength / weight:** 1.0. Full strength is the intended default.
- **Seed** 42 · **CFG** 1 · **Sampler** `euler_ancestral`.
- **Inference steps:** Stage 1: 8 steps at 960×544. Stage 2: 3 steps at 1920×1088.
- **Resolution & frames:** Width and height divisible by 64. 1920×1088 is a known good size. Frame count snaps to 8×k+1. A 72-frame, 3-second, 24 fps clip becomes 65 frames. Prefer a 24 fps layout clip. Output fps follows the layout clip.
- **Prompting:** One or two sentences describing the finished shot. Match the first frame. Do not write “clay,” “3D,” or “Unreal.”
- **First frame:** The art direction. Take the first frame of the clay animation and give it to any image model to generate the visual you want. That image goes in as the first frame. Do not use the grey clay frame itself.
- **Blocking animation:** A playblast built from simple shapes works as the layout video, from Blender, Unreal, or a similar 3D tool. The model keeps that movement and that camera. A detailed clay render is not required.
- **Keyframes:** The first frame is the normal recipe. Add a mid frame and a last frame when the picture should hold through the shot.

## References

- **Code:** [GitHub Repository](https://github.com/Lightricks/LTX-2)
- **ComfyUI:** [ComfyUI-LTXVideo](https://github.com/Lightricks/ComfyUI-LTXVideo/)

## Tips & Troubleshooting

- If the video ignores the art direction, the first frame is not the picture you want. A grey clay frame used as the first frame produces a grey result.
- A 72-frame clip coming out as 65 frames is expected. The recipe snaps the length to 8×k+1.
- To hold the picture through the shot, add a mid frame and a last frame.

## Training

- **Technique:** IC-LoRA trained on LTX-2.5 dev, with short simple prompts and a layout video as the control signal. Inference runs on LTX-2.5 distilled.
- **Steps:** 4000

## License

See the **[LTX-2-community-license](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x)** for full terms.

## Acknowledgments

- Base model by **[Lightricks](https://ltx.io/)**
- Training infrastructure: **[LTX-2 Community Trainer](https://github.com/Lightricks/LTX-2/tree/main/packages/ltx-trainer)**