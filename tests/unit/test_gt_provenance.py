import importlib.util,json,sys
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('mg_nodes',ROOT/'comfy_nodes/__init__.py')
nodes=importlib.util.module_from_spec(spec);sys.modules[spec.name]=nodes;spec.loader.exec_module(nodes)

def test_explicit_missing_gt_never_falls_back(tmp_path):
 (tmp_path/'joints.json').write_text('{"frames": []}')
 with pytest.raises(FileNotFoundError):nodes.MG_LoadReference().load(str(tmp_path),'missing.json')

def test_overlay_rejects_changed_explicit_gt_before_reading_video(tmp_path):
 from motionguard_core.report import render
 gt=tmp_path/'gt.json';gt.write_text('{}')
 (tmp_path/'report.json').write_text(json.dumps({'sources':{'gt':{'path':str(gt),'sha256':'incorrect'}}}))
 for file in ['reference-pose.json','generated-pose.json']:(tmp_path/file).write_text('{}')
 with pytest.raises(ValueError,match='hash mismatch'):render('absent.mp4','absent.mp4',tmp_path)

def test_reference_rejects_bad_timeline(tmp_path):
 (tmp_path/'joints.json').write_text(json.dumps({'frames':[{'frame':0,'time_s':1,'joints':[]}]}))
 with pytest.raises(ValueError,match='timeline'):nodes.MG_LoadReference().load(str(tmp_path))
