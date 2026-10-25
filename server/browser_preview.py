"""Compatible display and download copies; analysis retains the original bytes."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading

_LOCK = threading.Lock()

def browser_preview(source):
    source = Path(source)
    original = source.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    with _LOCK:
        cache = source.parent / '.browser-preview'
        if cache.is_symlink():
            raise ValueError('Linked preview directory')
        cache.mkdir(exist_ok=True)
        target = cache / (source.stem + '.mp4')
        receipt = cache / (source.stem + '.json')
        if target.is_symlink() or receipt.is_symlink():
            raise ValueError('Linked preview file')
        if receipt.exists():
            saved = json.loads(receipt.read_text())
            if saved.get('source_sha256') == digest:
                if saved.get('original_compatible'):
                    return source
                if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == saved.get('preview_sha256'):
                    return target
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=codec_name,pix_fmt', '-of', 'json', str(source)],
            capture_output=True, check=True, timeout=30, creationflags=flags)
        stream = json.loads(probe.stdout)['streams'][0]
        compatible = stream.get('codec_name') == 'h264' and stream.get('pix_fmt') == 'yuv420p'
        saved = {'source_sha256': digest, 'original_compatible': compatible}
        if not compatible:
            temporary = cache / (source.stem + '.tmp.mp4')
            if temporary.is_symlink():
                raise ValueError('Linked temporary preview')
            try:
                subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(source),
                    '-map', '0:v:0', '-map', '0:a?', '-c:v', 'libx264', '-crf', '18',
                    '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart', str(temporary)],
                    capture_output=True, check=True, timeout=120, creationflags=flags)
                if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
                    raise ValueError('Source changed during preview')
                os.replace(temporary, target)
                saved['preview_sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
            finally:
                temporary.unlink(missing_ok=True)
        receipt.write_text(json.dumps(saved), encoding='utf-8')
        return source if compatible else target
