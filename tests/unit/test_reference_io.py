import numpy as np
import pytest
from pathlib import Path
from motionguard_core.reference_io import project_world,judgeable_joint,finite,validate_package

def test_projection_axes_and_fov():
    c={'quaternion_xyzw':[0,0,0,1],'position':[0,0,0],'width':800,'height':400,'aspect':2,'fov_y_deg':90}
    assert np.allclose(project_world([0,0,-2],c),[400,200])
    assert np.allclose(project_world([1,1,-2],c),[500,100])
    with pytest.raises(ValueError):project_world([0,0,1],c)

def test_rotated_translated_camera():
    c={'quaternion_xyzw':[0,np.sqrt(.5),0,np.sqrt(.5)],'position':[3,2,1],'width':800,'height':400,'aspect':2,'fov_y_deg':90}
    assert np.allclose(project_world([1,2,1],c),[400,200])

def test_uncertain_is_not_judgeable():
    for v in ['missing','uncertain','occluded','out_of_frame']:
        assert not judgeable_joint({'available':True,'in_frame':True,'visibility':v})
    assert judgeable_joint({'available':True,'in_frame':True,'visibility':'surface_near'})

def test_orthographic_extent_depth_and_rotation():
    c={'projection_type':'orthographic','quaternion_xyzw':[0,0,0,1],'position':[0,0,0],'width':800,'height':400,'ortho_width':4,'ortho_height':2}
    assert np.allclose(project_world([0,0,-2],c),[400,200])
    assert np.allclose(project_world([2,1,-2],c),[800,0])
    assert np.allclose(project_world([2,1,-20],c),[800,0])
    c.update(quaternion_xyzw=[0,np.sqrt(.5),0,np.sqrt(.5)],position=[3,2,1])
    assert np.allclose(project_world([1,2,1],c),[400,200])
    c['ortho_width']=0
    with pytest.raises(ValueError,match='extent'):project_world([1,2,1],c)

def test_nested_nonfinite_rejected():
    assert not finite({'frames':[{'pixel':[2,float('nan')]}]})
    assert not finite({'camera':{'position':[0,0,float('inf')]}})

def test_empty_manifest_rejected(tmp_path):
    package=tmp_path
    source=Path(__file__).resolve().parents[2]/'tests/fixtures/reference-validation/joints.json'
    (package/'joints.json').write_bytes(source.read_bytes())
    for sub in ['pose','ref_textured','ref_shaded']:
        (package/sub).mkdir()
        for i in range(97):(package/sub/f'{i:04d}.png').touch()
    (package/'sha256.json').write_text('{}')
    with pytest.raises(ValueError,match='Incomplete manifest'):validate_package(package)
