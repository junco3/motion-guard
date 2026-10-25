---
license: apache-2.0
tags:
- comfyui
- diffusion-single-file
base_model:
- google/gemma-4-12B-it
- google/gemma-4-E2B-it
- google/gemma-4-E4B-it
---

# Gemma 4

Repackaged model files for ComfyUI.

Original model repository:

- https://huggingface.co/google/gemma-4-E2B-it
- https://huggingface.co/google/gemma-4-E4B-it

Place the files in the following folders:

```
📂 ComfyUI/
├── 📂 models/
│   ├── 📂 text_encoders/
│   │   ├── gemma4_e2b_it_bf16.safetensors
│   │   ├── gemma4_e2b_it_int8_convrot.safetensors
│   │   ├── gemma4_e4b_it_bf16.safetensors
│   │   ├── gemma4_e4b_it_int8_convrot.safetensors
│   │   ├── gemma4_e4b_it_fp8_scaled.safetensors
│   │   ├── gemma4_12b_bf16.safetensors
│   │   └── gemma4_12b_int8_convrot.safetensors
```
