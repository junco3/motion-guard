import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import * as T from '../web/node_modules/three/build/three.module.js';
const source=await readFile(new URL('../web/director.mjs',import.meta.url),'utf8');
function setup(scale=1,vertical=0){
 const camera=new T.PerspectiveCamera(40,1.5,.02,60),center=new T.Vector3(0,1,0),height=2;
 const context=vm.createContext({T,Math,Number,camera,center,height,document:{querySelector:id=>({value:id==='#framing-scale'?scale:vertical})}});
 vm.runInContext(source.slice(source.indexOf('function framing('),source.indexOf('function selectClip(')),context);
 return {camera,center,height,angle:context.angle};
}
test('default framing preserves original camera for all supported angles',()=>{
 for(const [name,a] of Object.entries({front:0,quarter:Math.PI/4,side:Math.PI/2})){
  const h=setup();h.angle(name);const old=new T.PerspectiveCamera(40,1.5,.02,60);
  old.position.copy(h.center).add(new T.Vector3(Math.sin(a)*h.height*2.4,h.height*.08,Math.cos(a)*h.height*2.4));old.lookAt(h.center);old.updateMatrixWorld(true);
  assert.deepEqual(h.camera.matrixWorld.toArray(),old.matrixWorld.toArray());
 }
});
test('changed framing reconstructs from existing GT camera contract without zoom',()=>{
 const h=setup(1.4,.06);h.angle('quarter');const restored=new T.PerspectiveCamera(h.camera.fov,h.camera.aspect,h.camera.near,h.camera.far);
 restored.position.copy(h.camera.position);restored.quaternion.copy(h.camera.quaternion);restored.updateMatrixWorld(true);
 for(const p of [new T.Vector3(0,.2,0),new T.Vector3(.3,1.5,.1)])assert.ok(p.clone().project(h.camera).distanceTo(p.clone().project(restored))<1e-12);
 assert.equal(h.camera.zoom,1);
});
test('vertical framing translates camera and target without tilting',()=>{
 const a=setup(1.4,0),b=setup(1.4,.1);a.angle('front');b.angle('front');
 assert.ok(a.camera.quaternion.angleTo(b.camera.quaternion)<1e-7);
 assert.ok(Math.abs(b.camera.position.y-a.camera.position.y+.2)<1e-12);
});
