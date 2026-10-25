"""Independent reference-package validation; no Three.js projection code reused."""
import hashlib,json,math
from pathlib import Path
import numpy as np

def project_world(world,camera):
    x,y,z,w=camera['quaternion_xyzw']
    rotation=np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                       [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                       [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])
    point=rotation.T@(np.asarray(world)-camera['position'])
    if point[2]>=0:raise ValueError('Point behind camera')
    if camera.get('projection_type')=='orthographic':
        width=float(camera['ortho_width']);height=float(camera['ortho_height'])
        if not np.isfinite([width,height]).all() or min(width,height)<=0:raise ValueError('Invalid orthographic extent')
        return np.array([camera['width']*(.5+point[0]/width),camera['height']*(.5-point[1]/height)])
    fy=camera['height']/(2*math.tan(math.radians(camera['fov_y_deg'])/2))
    fx=fy*camera['width']/camera['height']/camera['aspect']
    return np.array([camera['width']/2+fx*point[0]/-point[2],camera['height']/2-fy*point[1]/-point[2]])

def judgeable_joint(joint):
    return bool(joint.get('available') and joint.get('in_frame') and joint.get('visibility') in ('surface_near','surface_local_skin'))

def finite(value):
    if isinstance(value,dict):return all(finite(v) for v in value.values())
    if isinstance(value,list):return all(finite(v) for v in value)
    return math.isfinite(value) if isinstance(value,(int,float)) else True

def validate_timeline(data):
    frames=data['frames'];n=len(frames);meta=data.get('meta',{})
    if not 9<=n<=961 or (n-1)%8:raise ValueError("Expected 8n+1 frames between 9 and 961")
    if meta.get('fps',24)!=24 or meta.get('frames',n)!=n:raise ValueError('GT metadata timeline mismatch')
    for i,frame in enumerate(frames):
        if type(frame.get('frame')) is not int or frame['frame']!=i:raise ValueError('GT frame index mismatch')
        seconds=frame.get('time_s')
        if isinstance(seconds,bool) or not isinstance(seconds,(int,float)) or not math.isfinite(seconds) or abs(seconds-i/24)>1e-8:raise ValueError('GT time mismatch')
    return {'frames':n,'fps':24,'sample_span_seconds':(n-1)/24,'encoded_duration_seconds':n/24}

def validate_package(directory):
    root=Path(directory);data=json.loads((root/'joints.json').read_text());frames=data['frames']
    if len(frames)!=97:raise ValueError('Expected97 frames')
    if not finite(frames):raise ValueError('Nonfinite reference values')
    errors=[];visibility={};torso=[]
    for i,f in enumerate(frames):
        if f['frame']!=i or abs(f['time_s']-i/24)>1e-9:raise ValueError('Frame/time desynchronization')
        if len(f['joints'])!=18:raise ValueError('OpenPose18 slots required')
        for j in f['joints']:
            visibility[j['visibility']]=visibility.get(j['visibility'],0)+1
            if not j['available']:
                if j['world'] is not None or j['pixel'] is not None:raise ValueError('Fabricated missing joint')
                continue
            error=float(np.linalg.norm(project_world(j['world'],f['camera'])-j['pixel']));errors.append(error)
        torso.append(f['torso_world'])
    for sub in ['pose','ref_textured','ref_shaded']:
        if sorted(p.name for p in (root/sub).glob('*.png'))!=[f'{i:04d}.png' for i in range(97)]:raise ValueError('Frame image set mismatch')
    hashes=json.loads((root/'sha256.json').read_text())
    required={f'{sub}/{i:04d}.png' for sub in ['pose','ref_textured','ref_shaded'] for i in range(97)}
    required.update(['meta.json','joints.json','ctrl_pose.mp4','ref_textured.mp4','ref_shaded.mp4'])
    if not required.issubset(hashes):raise ValueError('Incomplete manifest')
    for name,expected in hashes.items():
        p=(root/name).resolve()
        if not p.is_relative_to(root.resolve()):raise ValueError('Unsafe manifest path')
        if hashlib.sha256(p.read_bytes()).hexdigest()!=expected:raise ValueError('Hash mismatch '+name)
    maximum=max(errors)
    if not math.isfinite(maximum) or maximum>=1:raise ValueError('Reprojection exceeds1pixel')
    if min(torso)<=0:raise ValueError('Degenerate torso')
    return {'status':'PASS','frames':97,'checked_joints':len(errors),'max_reprojection_error_px':maximum,'visibility_counts':visibility,'visibility_quality':'conservative ray-depth proxy; uncertain bone centres retained','source_sha256':json.loads((root/'meta.json').read_text())['source_sha256']}

if __name__=='__main__':
    import sys
    result=validate_package(sys.argv[1]);(Path(sys.argv[1])/'validation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
