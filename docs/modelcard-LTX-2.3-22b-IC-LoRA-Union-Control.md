---
base_model:
- Lightricks/LTX-2.3
datasets:
- Lightricks/Canny-Control-Dataset
language:
- en
license: other
license_name: ltx-2-community-license
license_link: https://github.com/Lightricks/LTX-2/blob/main/LICENSE
pipeline_tag: any-to-any
tags:
- ltx-video
- image-to-video
- text-to-video
pinned: true
---

# LTX-2.3 22B IC-LoRA Union Control

This is a unified control IC-LoRA trained on top of **LTX-2.3-22b**, enabling multiple control signals to be used for video generation from text and reference frames. 
It was trained with downscaled reference latents by a factor of 2.

It is based on the [LTX-2](https://huggingface.co/papers/2601.03233) foundation model.

- **Paper:** [AVControl: Efficient Framework for Training Audio-Visual Controls](https://huggingface.co/papers/2603.24793)
- **Code:** [GitHub Repository](https://github.com/Lightricks/LTX-2)
- **Project Page:** [AVControl project page](https://matanby.github.io/AVControl/)


## What is In-Context LoRA (IC LoRA)?

IC LoRA enables conditioning video generation on reference video frames at inference time, allowing fine-grained video-to-video control on top of a text-to-video, base model.
It allows also the usage of an initial image for image-to-video, and generate audio-visual output.

## What is Reference Downscale Factor?

IC LoRA uses a reference control signal, i.e. a video that is positionally aligned to the generated video and contains the reference for context. 
To allow for added efficiency, the reference video can be smaller, so it consumes less tokens.
The reference downscale factor determines the expected downscaling of the reference video compared to the generated resolution.
To signify the expected reference size, the checkpoint name will have a 'ref' denominator followed by the scale relative to the output resolution.

## Model Files

`ltx-2.3-22b-ic-lora-union-control-ref0.5.safetensors`

## License

See the **LTX-2-community-license** for full terms.

## Model Details

- **Base Model:** LTX-2.3-22b Video
- **Training Type:** IC LoRA
- **Control Type:** Union conditioning - Canny + Depth + Pose
- **Reference Downscale Factor:** 2 (reference resolution is 0.5x the output resolution)

### 🔌 Using in ComfyUI
1. Copy the LoRA weights into `models/loras`.
2. Use the official IC-LoRA workflow from the [LTX-2 ComfyUI repository](https://github.com/Lightricks/ComfyUI-LTXVideo/).
3. Make sure to use the nodes supporting Reference Downscale Factor: LTXICLoRALoaderModelOnly to load the lora and extract the downscale factor, and LTXAddVideoICLoRAGuide to add the small latent as a guide.


## Dataset

The model was trained using the [Lightricks/Canny-Control-Dataset](https://huggingface.co/datasets/Lightricks/Canny-Control-Dataset/) amongst others.

## Citation

```bibtex
@article{hacohen2025ltx2,
  title={LTX-2: Efficient Joint Audio-Visual Foundation Model},
  author={HaCohen, Yoav and Brazowski, Benny and Chiprut, Nisan and Bitterman, Yaki and Kvochko, Andrew and Berkowitz, Avishai and Shalem, Daniel and Lifschitz, Daphna and Moshe, Dudu and Porat, Eitan and others},
  journal={arXiv preprint arXiv:2601.03233},
  year={2025}
}
@misc{LTXVideoTrainer2025,
  title={LTX-Video Community Trainer},
  author={Matan Ben Yosef and Naomi Ken Korem and Tavi Halperin},
  year={2025},
  publisher={GitHub},
}
```

## Acknowledgments

- Base model by **Lightricks**
- Training infrastructure: **LTX-2 Community Trainer**