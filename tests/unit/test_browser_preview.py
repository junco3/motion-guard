import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'server'))
from browser_preview import browser_preview

def test_rgb_preview_preserves_source_timeline_and_reuses_cache(tmp_path):
    source = tmp_path / 'generated.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc=size=64x64:rate=24',
        '-frames:v','12','-c:v','libx264rgb',str(source)],check=True)
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    preview = browser_preview(source)
    assert preview != source
    probe = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries',
        'stream=pix_fmt,nb_frames,duration','-of','json',str(preview)]))['streams'][0]
    assert probe['pix_fmt'] == 'yuv420p' and probe['nb_frames'] == '12'
    assert float(probe['duration']) == .5
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original
    stamp = preview.stat().st_mtime_ns
    assert browser_preview(source) == preview and preview.stat().st_mtime_ns == stamp
    assert browser_preview(preview) == preview
