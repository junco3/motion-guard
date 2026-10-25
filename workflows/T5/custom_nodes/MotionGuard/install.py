import shutil, subprocess, onnxruntime
import imageio_ffmpeg
binary = shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()
encoders = subprocess.check_output([binary, "-hide_banner", "-encoders"], stderr=subprocess.STDOUT, timeout=20).decode()
assert "libx264rgb" in encoders, "Missing lossless RGB encoder"
assert "CPUExecutionProvider" in onnxruntime.get_available_providers()
print("MotionGuard preflight: libx264rgb and ORT CPU available; model inference not yet tested.")
