import * as T from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {captureTimeline,clipTime} from './capture-timeline.mjs';
const selectedTimeline=()=>captureTimeline(Number(document.querySelector('#duration').value));
let W=768,H=512;
const renderer=new T.WebGLRenderer({canvas:document.querySelector('#view'),antialias:true,preserveDrawingBuffer:true});renderer.setSize(W,H);renderer.setPixelRatio(1);
const scene=new T.Scene();scene.background=new T.Color(0x59616a);
scene.add(new T.HemisphereLight(0xffffff,0x48516a,2));const light=new T.DirectionalLight(0xffffff,3);light.position.set(3,5,4);scene.add(light);
const camera=new T.PerspectiveCamera(40,W/H,.01,1000),ctx=document.querySelector('#pose').getContext('2d');
let model,mixer,clips=[],active,height=2,center=new T.Vector3(),mapping=[],handBones=[],meshes=[],source='',playing=false;
const names=['nose','neck','right_shoulder','right_elbow','right_wrist','left_shoulder','left_elbow','left_wrist','right_hip','right_knee','right_ankle','left_hip','left_knee','left_ankle','right_eye','left_eye','right_ear','left_ear'];
const maps={ual:[null,'neck_01','upperarm_r','lowerarm_r','hand_r','upperarm_l','lowerarm_l','hand_l','thigh_r','calf_r','foot_r','thigh_l','calf_l','foot_l'],cesium:[null,'Skeleton_neck_joint_1','Skeleton_arm_joint_R','Skeleton_arm_joint_R__2_','Skeleton_arm_joint_R__3_','Skeleton_arm_joint_L__4_','Skeleton_arm_joint_L__3_','Skeleton_arm_joint_L__2_','leg_joint_R_1','leg_joint_R_2','leg_joint_R_3','leg_joint_L_1','leg_joint_L_2','leg_joint_L_3']};
const colors=['#ff0000','#ff5500','#ffaa00','#ffff00','#aaff00','#55ff00','#00ff00','#00ff55','#00ffaa','#00ffff','#00aaff','#0055ff','#0000ff','#5500ff','#aa00ff','#ff00ff','#ff00aa','#ff0055'];
const limbs=[[1,2],[1,5],[2,3],[3,4],[5,6],[6,7],[1,8],[8,9],[9,10],[1,11],[11,12],[12,13],[1,0],[0,14],[14,16],[0,15],[15,17]];
const status=s=>document.querySelector('#status').textContent=s;
function framing(){return {scale:Math.max(.7,Math.min(1.6,Number(document.querySelector('#framing-scale')?.value)||1)),vertical:Math.max(-.2,Math.min(.2,Number(document.querySelector('#framing-y')?.value)||0))};}
function angle(value){const a={front:0,quarter:Math.PI/4,side:Math.PI/2}[value],f=framing();const target=center.clone().add(new T.Vector3(0,-height*f.vertical,0));camera.position.copy(target).add(new T.Vector3(Math.sin(a)*height*2.4/f.scale,height*.08/f.scale,Math.cos(a)*height*2.4/f.scale));camera.lookAt(target);camera.updateMatrixWorld(true);}
function selectClip(name){if(active)active.stop();const clip=clips.find(x=>x.name===name)||clips[0];if(!clip)throw Error('No animation clip');active=mixer.clipAction(clip);active.play();mixer.setTime(0);model.updateMatrixWorld(true);return clip.name;}
// Local skin v2: ownership/distance validated; unsupported geometry keeps legacy uncertainty.
function surfaceOwnership(hit,bone,world,inspectVoronoi=false){
 if(!hit?.object?.isSkinnedMesh||!hit.face)return {status:'unsupported'};
 const mesh=hit.object,indices=mesh.geometry.attributes.skinIndex,weights=mesh.geometry.attributes.skinWeight;
 const material=Array.isArray(mesh.material)?mesh.material[hit.face.materialIndex]:mesh.material;
 let hierarchyVisible=true;for(let o=mesh;o;o=o.parent)hierarchyVisible&&=o.visible;
 const renderSurface=hierarchyVisible&&mesh.layers.test(camera.layers)&&material?.visible===true;
 const opaque=material?.isMeshStandardMaterial===true && material.transparent===false &&
  material.opacity===1 && material.alphaTest===0 && !material.alphaMap && !material.alphaHash;
 if(!indices||!weights)return {status:'unsupported'};
 const vertices=[hit.face.a,hit.face.b,hit.face.c].map(i=>mesh.getVertexPosition(i,new T.Vector3()).applyMatrix4(mesh.matrixWorld));
 const bary=T.Triangle.getBarycoord(hit.point,...vertices,new T.Vector3());
 if(!bary||!bary.toArray().every(Number.isFinite))return {status:'degenerate'};
 const influence=new Map();
 [hit.face.a,hit.face.b,hit.face.c].forEach((index,k)=>{
  for(let s=0;s<4;s++){const bi=indices.getComponent(index,s),w=weights.getComponent(index,s)*bary.getComponent(k);influence.set(bi,(influence.get(bi)||0)+w);}
 });
 const sorted=[...influence].sort((a,b)=>b[1]-a[1]);
 // A joint surface can blend parent/self weights. Distance support stays self/child.
 const eligible=b=>b===bone||b.parent===bone;
 const owned=sorted.reduce((v,[i,w])=>v+((eligible(mesh.skeleton.bones[i])||mesh.skeleton.bones[i]===bone.parent)?w:0),0);
 let nearest=Infinity;
 for(let i=0;i<indices.count;i++){
  let w=0;for(let s=0;s<4;s++)if(eligible(mesh.skeleton.bones[indices.getComponent(i,s)]))w+=weights.getComponent(i,s);
  if(w>=.7){const v=mesh.getVertexPosition(i,new T.Vector3()).applyMatrix4(mesh.matrixWorld);nearest=Math.min(nearest,v.distanceTo(world));}
 }
 const distance=hit.point.distanceTo(world);
 // Diagnostic only. Include fingers/toes; never substitute for the v2 decision.
 let voronoi;
 if(inspectVoronoi){
  const competitors=mesh.skeleton.bones.filter(b=>b!==bone).map(b=>({name:b.name,distance:b.getWorldPosition(new T.Vector3()).distanceTo(hit.point)})).sort((a,b)=>a.distance-b.distance);
  const closest=competitors[0];
  voronoi={method:'full-skeleton-nearest-joint-diagnostic',target:bone.name,competitor_count:competitors.length,closest_competitor:closest,
   candidate:Number.isFinite(distance)&&owned>=.7&&!!closest&&distance<=closest.distance+1e-8};
 }
 return {status:'diagnostic',owned_weight:owned,dominant_bone:mesh.skeleton.bones[sorted[0]?.[0]]?.name,
  opaque,first_hit_render_surface:renderSurface,material_index:hit.face.materialIndex,
  motion_observable_proxy:renderSurface&&opaque&&Number.isFinite(owned)&&owned>=.7&&Number.isFinite(distance),
  ...(voronoi?{voronoi_diagnostic:voronoi}:{}),
  dominant_weight:sorted[0]?.[1],nearest_owned_surface_distance:Number.isFinite(nearest)?nearest:null,
  hit_joint_distance:distance,distance_ratio:nearest>1e-8&&Number.isFinite(nearest)?distance/nearest:null,
  local_surface_candidate:Number.isFinite(owned)&&Number.isFinite(distance)&&owned>=.7&&Number.isFinite(nearest)&&nearest>1e-8&&distance<=nearest*1.5,
  rejection_reason:!Number.isFinite(owned)||!Number.isFinite(distance)?'nonfinite_geometry':owned<.7?'other_surface_owner':!Number.isFinite(nearest)||nearest<=1e-8?'invalid_local_radius':distance>nearest*1.5?'surface_not_local_to_joint':null,
  barycentric:bary.toArray(),method:'first-hit-local-parent-self-child-with-self-child-radius-v2'};
}
let loadEpoch=0,pendingLoad=null;
function load(...args){
 const task=loadCandidate(...args);pendingLoad=task;
 task.then(()=>{if(pendingLoad===task)pendingLoad=null;},()=>{if(pendingLoad===task)pendingLoad=null;});
 return task;
}
async function ready(){while(pendingLoad){const task=pendingLoad;await task;if(pendingLoad===task)return;}}
function disposeModel(root){
 root?.traverse(o=>{if(o.isMesh){o.geometry?.dispose();for(const material of Array.isArray(o.material)?o.material:[o.material]){if(!material)continue;for(const value of Object.values(material))if(value?.isTexture)value.dispose();material.dispose();}}});
}
async function loadCandidate(url,kind='ual',clipName){
 const epoch=++loadEpoch;let candidate;
 try{
  const gltf=await new GLTFLoader().loadAsync(url);candidate=gltf.scene;
  if(epoch!==loadEpoch){disposeModel(candidate);if(url.startsWith('blob:'))URL.revokeObjectURL(url);return null;}
  const nextClips=gltf.animations.filter(c=>Number.isFinite(c.duration)&&c.duration>0);
  if(!nextClips.length)throw Error('No playable animation. Keeping the previous scene.');
  nextClips.forEach((c,i)=>{if(!c.name)c.name='Animation '+i;});
  const nodes={},nextMeshes=[];candidate.traverse(o=>{nodes[o.name]=o;if(o.isMesh){nextMeshes.push(o);o.frustumCulled=false;}});
  const selected=maps[nodes.neck_01?'ual':nodes.Skeleton_neck_joint_1?'cesium':null];
  const nextMapping=names.map((_,i)=>nodes[selected?.[i]]||null);
  // 42 hand points in whole-body order (left then right): wrist, then thumb/index/middle/ring/pinky base->tip. UAL rigs only.
  const handNames=['l','r'].flatMap(s=>['hand_'+s,...['thumb','index','middle','ring','pinky'].flatMap(f=>[f+'_01_'+s,f+'_02_'+s,f+'_03_'+s,f+'_04_leaf_'+s])]);
  const nextHands=handNames.every(n=>nodes[n])?handNames.map(n=>nodes[n]):[];
  if(nextMapping.filter(Boolean).length<13)throw Error('Unsupported joint structure. Use a UAL or Cesium Man rig GLB. Keeping the previous scene.');
  const nextMixer=new T.AnimationMixer(candidate),clip=nextClips.find(c=>c.name===clipName)||nextClips[0];
  const nextAction=nextMixer.clipAction(clip);nextAction.play();nextMixer.setTime(0);candidate.updateMatrixWorld(true);
  const box=new T.Box3().setFromObject(candidate,true),nextCenter=box.getCenter(new T.Vector3()),nextHeight=box.getSize(new T.Vector3()).y;
  if(![...box.min.toArray(),...box.max.toArray(),nextHeight].every(Number.isFinite)||nextHeight<=0)throw Error('No valid model size. Keeping the previous scene.');
  const previous=model,previousSource=source;
  playing=false;mixer?.stopAllAction();if(previous)scene.remove(previous);
  model=candidate;scene.add(model);source=url;clips=nextClips;mixer=nextMixer;active=nextAction;mapping=nextMapping;handBones=nextHands;meshes=nextMeshes;center=nextCenter;height=nextHeight;
  disposeModel(previous);if(previousSource.startsWith('blob:'))URL.revokeObjectURL(previousSource);
  camera.near=height*.01;camera.far=height*30;camera.updateProjectionMatrix();angle(document.querySelector('#angle').value);
  document.querySelector('#clip').replaceChildren(...clips.map(c=>new Option(c.name,c.name,c.name===active.getClip().name,c.name===active.getClip().name)));
  status('Model loaded · '+clips.length+' motions');return {clips:clips.map(c=>c.name),mapped:mapping.filter(Boolean).length};
 }catch(error){if(candidate&&candidate!==model)disposeModel(candidate);if(url.startsWith('blob:')&&url!==source)URL.revokeObjectURL(url);if(epoch===loadEpoch)throw error;return null;}
}

// Skinned positions for this frame, computed once with the same three.js routine. Bounding volumes,
// every joint ray and the ownership check read them instead of re-skinning per vertex per ray.
function cacheSkin(m){
 const n=m.geometry.attributes.position.count,c=new Float64Array(n*3),v=new T.Vector3();
 delete m.getVertexPosition;
 for(let i=0;i<n;i++){m.getVertexPosition(i,v);c[3*i]=v.x;c[3*i+1]=v.y;c[3*i+2]=v.z;}
 m.getVertexPosition=(i,target)=>target.set(c[3*i],c[3*i+1],c[3*i+2]);
}
// quick: on-screen playback only. Skips the per-joint skinned raycasts and image encoding
// (~0.5 s a frame); exports and generation always call without it.
function frame(index,mode='textured',images=true,synthetic=null,quick=false){
 const savedPosition=model.position.clone(),savedScale=model.scale.clone();let blocker=null;
 let sampleIndex=index;
 if(synthetic?.variant==='shift')sampleIndex=Math.max(0,index-12);
 if(synthetic?.variant==='freeze')sampleIndex=Math.min(index,24);
 if(synthetic?.variant==='reverse')sampleIndex=96-index;
 mixer.setTime(synthetic?.singleAction ? Math.min(Math.max((sampleIndex-16)/64,0),.999)*active.getClip().duration : synthetic ? sampleIndex/24 : clipTime(sampleIndex,active.getClip().duration,document.querySelector('#repeat-clip').checked));
 if(synthetic?.locomotion)model.position.x=savedPosition.x+height*.5*(index/96)*(synthetic.variant==='root_reverse'?-1:1);
 if(synthetic?.rootOffset)model.position.add(new T.Vector3().fromArray(synthetic.rootOffset));
 if(synthetic?.variant==='mirrored_action')model.scale.x=-savedScale.x;
 if(synthetic?.variant==='wrong_side')for(const [a,b] of [[2,5],[3,6],[4,7]]){const q=mapping[a].quaternion.clone();mapping[a].quaternion.copy(mapping[b].quaternion);mapping[b].quaternion.copy(q);}
 if(synthetic?.variant==='occlude'){
  blocker=new T.Mesh(new T.BoxGeometry(height*.8,height*.85,height*.08),new T.MeshBasicMaterial({color:0x59616a}));
  blocker.position.copy(center).lerp(camera.position,.15);scene.add(blocker);blocker.updateMatrixWorld(true);
 }
 model.updateMatrixWorld(true);if(!quick)for(const m of meshes){if(m.isSkinnedMesh){m.skeleton.update();cacheSkin(m);m.computeBoundingBox();m.computeBoundingSphere();}}
 camera.updateMatrixWorld(true);
 const ray=new T.Raycaster();const observe=(o,name)=>{
  if(!o)return {name,available:false,world:null,pixel:null,visibility:'missing'};
  const world=o.getWorldPosition(new T.Vector3()),ndc=world.clone().project(camera),cv=world.clone().applyMatrix4(camera.matrixWorldInverse),inFrame=Math.abs(ndc.x)<=1&&Math.abs(ndc.y)<=1&&ndc.z>=-1&&ndc.z<=1;
  if(quick)return {name,available:true,world:world.toArray(),pixel:[(ndc.x+1)*W/2,(1-ndc.y)*H/2],in_frame:inFrame};
  ray.setFromCamera(new T.Vector2(ndc.x,ndc.y),camera);const hit=ray.intersectObjects(blocker?[...meshes,blocker]:meshes,false)[0];const distance=world.distanceTo(ray.ray.origin);const gap=hit?distance-hit.distance:null;
  // Bone centres lie inside a body surface. Preserve depth gap and uncertainty,
  // rather than asserting a binary visibility label from an arbitrary radius.
  const legacyVisibility=!inFrame?'out_of_frame':!hit?'uncertain':gap>height*.08?'occluded':gap<height*.025?'surface_near':'uncertain';
  const useSkin=synthetic?.skinVisibility!==false;
  const evidence=synthetic?.inspectOwnership||useSkin?surfaceOwnership(hit,o,world,synthetic?.inspectVoronoi===true):null;
  const visibility=useSkin&&inFrame&&evidence?.local_surface_candidate?'surface_local_skin':legacyVisibility;
  return {name,available:true,world:world.toArray(),camera:cv.toArray(),pixel:[(ndc.x+1)*W/2,(1-ndc.y)*H/2],in_frame:inFrame,visibility,surface_gap:gap,...(evidence?{surface_evidence:evidence,legacy_visibility:legacyVisibility}:{})};
 };
 const joints=mapping.map((o,i)=>observe(o,names[i]));
 // Finger tips get the same projection and visibility as body joints; only the fields the
 // finger check reads are kept, so a 10-second timeline stays under the Platform request limit.
 const hands=handBones.length?handBones.map(o=>{const h=observe(o,o.name);return {name:h.name,available:h.available,pixel:h.pixel,in_frame:h.in_frame,visibility:h.visibility};}):null;
 ctx.fillStyle='black';ctx.fillRect(0,0,W,H);
 limbs.forEach(([a,b],i)=>{if(!joints[a].pixel||!joints[b].pixel)return;const p=joints[a].pixel,q=joints[b].pixel;const rgb=colors[i].slice(1).match(/../g).map(v=>Math.floor(parseInt(v,16)*.6));ctx.fillStyle=`rgb(${rgb.join(',')})`;ctx.beginPath();ctx.ellipse(Math.floor((p[0]+q[0])/2),Math.floor((p[1]+q[1])/2),Math.hypot(p[0]-q[0],p[1]-q[1])/2,4,Math.atan2(p[1]-q[1],p[0]-q[0]),0,2*Math.PI);ctx.fill();});
 joints.forEach((j,i)=>{if(j.pixel&&j.in_frame){ctx.fillStyle=colors[i];ctx.beginPath();ctx.arc(...j.pixel,4,0,2*Math.PI);ctx.fill();}});
 const shoulders=new T.Vector3().fromArray(joints[2].world).add(new T.Vector3().fromArray(joints[5].world)).multiplyScalar(.5),hips=new T.Vector3().fromArray(joints[8].world).add(new T.Vector3().fromArray(joints[11].world)).multiplyScalar(.5);
 const sp=shoulders.clone().project(camera),hp=hips.clone().project(camera);
 const result={frame:index,time_s:index/24,joints,torso_world:shoulders.distanceTo(hips),torso_pixels:Math.hypot((sp.x-hp.x)*W/2,(sp.y-hp.y)*H/2),camera:{position:camera.position.toArray(),quaternion_xyzw:camera.quaternion.toArray(),fov_y_deg:camera.fov,aspect:camera.aspect,near:camera.near,far:camera.far,width:W,height:H,matrix_world:camera.matrixWorld.toArray()}};
 if(hands)result.hands=hands;
 if(synthetic?.footDiagnostic){result.foot_contacts={};for(const name of ['foot_l','foot_r','ball_l','ball_r','ball_leaf_l','ball_leaf_r','root']){const bone=model.getObjectByName(name);if(bone)result.foot_contacts[name]={world:bone.getWorldPosition(new T.Vector3()).toArray(),rotation:bone.getWorldQuaternion(new T.Quaternion()).toArray()};}result.clip_duration=active.getClip().duration;}
 if(images){const savedBackground=scene.background;if(mode==='depth')scene.background=new T.Color(0x000000);scene.overrideMaterial=mode==='shaded'?new T.MeshStandardMaterial({color:0xaab4c0,roughness:.8}):mode==='depth'?new T.MeshDepthMaterial({depthPacking:T.BasicDepthPacking}):null;renderer.render(scene,camera);if(!quick){result.render=mode==='depth'?renderer.domElement.toDataURL('image/png'):renderer.domElement.toDataURL('image/jpeg',.9);result.render_encoding=mode==='depth'?'PNG':'browser JPEG quality .9; decoded to PNG and encoded into submitted reference video';result.pose=ctx.canvas.toDataURL('image/png');}if(scene.overrideMaterial)scene.overrideMaterial.dispose();scene.overrideMaterial=null;scene.background=savedBackground;}
 if(blocker){scene.remove(blocker);blocker.geometry.dispose();blocker.material.dispose();}
 model.position.copy(savedPosition);model.scale.copy(savedScale);
 for(const m of meshes)delete m.getVertexPosition;
 return result;
}
function footStage(){
 const floor=new T.Mesh(new T.PlaneGeometry(14,14),new T.MeshStandardMaterial({color:0x899399,roughness:1}));floor.rotation.x=-Math.PI/2;floor.receiveShadow=true;scene.add(floor);
 const grid=new T.GridHelper(14,28,0x667077,0x79858c);grid.position.y=.001;scene.add(grid);
 renderer.shadowMap.enabled=true;renderer.shadowMap.type=T.PCFSoftShadowMap;light.castShadow=true;light.shadow.normalBias=.02;light.shadow.mapSize.set(2048,2048);Object.assign(light.shadow.camera,{left:-5,right:5,top:5,bottom:-5,near:.1,far:20});meshes.forEach(m=>{m.castShadow=true;m.receiveShadow=true;});
 camera.position.set(6,2.8,4.8);camera.lookAt(0,.8,1.95);camera.near=2;camera.far=13;camera.updateProjectionMatrix();camera.updateMatrixWorld(true);
 return {ground_y:0,camera_mode:'fixed side-three-quarter',root_kind:'reconstructed'};
}
function setLayoutMode(enabled){
 const next=enabled?[960,544]:[768,512];if(W===next[0]&&H===next[1])return;
 playing=false;[W,H]=next;renderer.setSize(W,H);ctx.canvas.width=W;ctx.canvas.height=H;
 camera.aspect=W/H;camera.updateProjectionMatrix();if(active)frame(+document.querySelector('#frame').value);
}
window.director={load,ready,frame,angle,footStage,setLayoutMode,stop:()=>{playing=false;},metadata:()=>({source,framing:framing(),clip:active.getClip().name,clip_duration_seconds:active.getClip().duration,repeat_clip:document.querySelector('#repeat-clip').checked,three:T.REVISION,joint_names:names,missing_face_points:true,visibility_method:'first-hit-local-parent-self-child-with-self-child-radius-v2',motion_observation_policy:'owned-first-hit-v1',...selectedTimeline(),width:W,height:H})};
function updateTimeline(){
 const axis=selectedTimeline();playing=false;
 document.querySelector('#frame').max=axis.frames-1;document.querySelector('#frame').value=0;
 document.querySelector('#timeline-info').textContent=`${axis.sample_span_seconds}s span · ${axis.frames} frames · 24fps · Video length ${axis.encoded_duration_seconds.toFixed(2)}s. Source motion ${active.getClip().duration.toFixed(2)}s · ${document.querySelector('#repeat-clip').checked?'Loop motion':`Hold at motion end · last ${Math.max(0,axis.sample_span_seconds-active.getClip().duration).toFixed(2)}s is a hold segment`}. Videos up to 40 s (961 frames) run on the hosted Space.`;
 frame(0);
}
document.querySelector('#duration').onchange=updateTimeline;
document.querySelector('#repeat-clip').onchange=updateTimeline;
const samples={ual:'/workflows/T1/inputs/UAL1_Standard.glb',cesium:'/data/public_samples/CesiumMan.glb'};
document.querySelector('#sample').onchange=async e=>{window.dispatchEvent(new Event('motion-loading'));try{if(await load(samples[e.target.value],e.target.value,e.target.value==='ual'?'Dance_Loop':undefined)){updateTimeline();window.dispatchEvent(new CustomEvent('motion-loaded',{detail:{custom:false}}));}}catch(err){status(err.message);}};
document.querySelector('#file').onchange=async e=>{try{const file=e.target.files[0];if(!file)return;if(!/\.glb$/i.test(file.name)){e.target.value='';status('Select an animation GLB file. Keeping the previous scene.');return;}window.dispatchEvent(new Event('motion-loading'));if(await load(URL.createObjectURL(file),'ual')){updateTimeline();window.dispatchEvent(new CustomEvent('motion-loaded',{detail:{custom:true}}));}}catch(err){e.target.value='';console.warn('GLB load failed',err);status(err.message.includes('Keeping the previous scene.')?err.message:'Could not load the 3D file. Check the animation GLB file. Keeping the previous scene.');}};
document.querySelector('#clip').onchange=e=>{selectClip(e.target.value);updateTimeline();};document.querySelector('#angle').onchange=e=>{angle(e.target.value);frame(+document.querySelector('#frame').value);};
document.querySelector('#frame').oninput=e=>{playing=false;frame(+e.target.value,'textured',true,null,true);};
document.querySelector('#play').onclick=()=>{playing=!playing;document.querySelector('#play').textContent=playing?'Pause':'Play';};
let exporting=false,exportUrl=null;
const stillButton=document.createElement('button');stillButton.textContent='Prepare first-frame image';stillButton.id='prepare-look-frame';
const stillLink=document.createElement('a');stillLink.textContent='Download first-frame PNG';stillLink.download='layout-first-frame.png';stillLink.hidden=true;
document.querySelector('#export').before(stillButton,stillLink);
stillButton.onclick=async()=>{
 await ready();playing=false;document.querySelector('#play').textContent='Play';
 document.querySelector('#frame').value=0;frame(0);stillLink.href=renderer.domElement.toDataURL('image/png');stillLink.hidden=false;
 status(`First frame ${W}×${H} ready · Use a character image that keeps this framing and pose.`);
};
const exportLink=document.createElement('a');exportLink.hidden=true;exportLink.download='motion-reference.json';exportLink.textContent='Download joint JSON';document.querySelector('#export').after(exportLink);
document.querySelector('#export').textContent='Prepare joint JSON';
document.querySelector('#export').onclick=async()=>{
 if(exporting||document.querySelector('#export').disabled)return;
 exporting=true;let saved=[],originalFrame=+document.querySelector('#frame').value;
 try{
  await ready();
  if(document.querySelector('#export').disabled)return;
  exportLink.hidden=true;exportLink.removeAttribute('href');exportUrl=null;
  playing=false;document.querySelector('#play').textContent='Play';
  saved=[...document.querySelectorAll('#studio input,#studio select,#studio textarea,#studio button')].map(el=>[el,el.disabled]);
  for(const [el] of saved)el.disabled=true;
  const meta=window.director.metadata(),frames=[];
  status(`Preparing joint save · 0/${meta.frames}`);
  await new Promise(requestAnimationFrame);
  for(let i=0;i<meta.frames;i++){
   frames.push(frame(i,'textured',false));
   status(`Saving joints · ${i+1}/${meta.frames}`);
   await new Promise(requestAnimationFrame);
  }
  const session=await fetch('/api/session').then(r=>r.json());
  const response=await fetch('/api/reference-export',{method:'POST',headers:{'Content-Type':'application/json','X-MotionGuard-Token':session.token},body:JSON.stringify({meta,frames})});
  if(!response.ok)throw Error('File preparation server error '+response.status);
  const result=await response.json();
  exportUrl='/api/reference-export?id='+encodeURIComponent(result.export_id)+'&token='+encodeURIComponent(session.token);
  exportLink.href=exportUrl;exportLink.hidden=false;
  status(`Joints ${frames.length} frames · Framing ${meta.framing.scale}/${meta.framing.vertical} · Download motion-reference.json from the link below.`);
 }catch(e){status('Joint save failed · '+e.message);}
 finally{try{if(saved.length)frame(originalFrame);}finally{for(const [el,disabled] of saved)el.disabled=disabled;exporting=false;}}
};
let last=0;function tick(now){if(playing&&now-last>=1000/24){const f=(+document.querySelector('#frame').value+1)%selectedTimeline().frames;document.querySelector('#frame').value=f;frame(f,'textured',true,null,true);last=now;}requestAnimationFrame(tick);}requestAnimationFrame(tick);
await load(samples.ual,'ual','Dance_Loop');updateTimeline();window.ready=true;

function updateFraming(){playing=false;angle(document.querySelector("#angle").value);document.querySelector("#framing-scale-value").textContent=framing().scale.toFixed(2)+"×";document.querySelector("#framing-y-value").textContent=framing().vertical.toFixed(2);if(active)frame(+document.querySelector("#frame").value);}
for(const id of ["#framing-scale","#framing-y"])document.querySelector(id).oninput=updateFraming;
document.querySelector("#framing-reset").onclick=()=>{document.querySelector("#framing-scale").value=1;document.querySelector("#framing-y").value=0;updateFraming();};

window.director.restore=async (settings,skipModel=false)=>{
 if(!skipModel&&settings.sample){document.querySelector('#sample').value=settings.sample;await load(samples[settings.sample],settings.sample,settings.clip);}
 if(!skipModel&&settings.clip&&[...document.querySelector('#clip').options].some(o=>o.value===settings.clip)){document.querySelector('#clip').value=settings.clip;selectClip(settings.clip);}
 for(const id of ['angle','duration','framing-scale','framing-y'])if(settings[id]!==undefined)document.querySelector('#'+id).value=settings[id];
 document.querySelector('#repeat-clip').checked=settings['repeat-clip']===true;
 updateTimeline();updateFraming();
};
window.dispatchEvent(new Event('motion-ready'));
