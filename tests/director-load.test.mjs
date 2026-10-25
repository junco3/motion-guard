import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import * as T from '../web/node_modules/three/build/three.module.js';
const code=await readFile(new URL('../web/director.mjs',import.meta.url),'utf8');
const block=code.slice(code.indexOf('let loadEpoch='),code.indexOf('\nfunction frame('));
const boneNames=['neck_01','upperarm_r','lowerarm_r','hand_r','upperarm_l','lowerarm_l','hand_l','thigh_r','calf_r','foot_r','thigh_l','calf_l','foot_l'];
function candidate(valid=true){const scene=new T.Group();scene.add(new T.Mesh(new T.BoxGeometry(1,2,1),new T.MeshStandardMaterial()));if(valid)for(const name of boneNames){const b=new T.Bone();b.name=name;scene.add(b);}return {scene,animations:[new T.AnimationClip('motion',1,[])]};}
function setup(){let resolveSlow;const original=candidate();const revoked=[];const context=vm.createContext({T,Number,Error,Object,Array,URL:{revokeObjectURL:x=>revoked.push(x)},Option:class{},document:{querySelector:()=>({value:'front',replaceChildren(){}})},status(){},angle(){},GLTFLoader:class{async loadAsync(url){if(url==='slow')return new Promise(r=>resolveSlow=r);if(url==='bad')return candidate(false);if(url==='empty'){const c=candidate();c.animations=[];return c;}return candidate();}},scene:new T.Scene(),model:original.scene,mixer:new T.AnimationMixer(original.scene),source:'original',maps:{ual:[null,...boneNames]},names:Array(14).fill(''),camera:new T.PerspectiveCamera(),clips:[],mapping:[],meshes:[],center:new T.Vector3(),height:2,playing:false});vm.runInContext(block,context);return {context,original,revoked,resolve:()=>resolveSlow(candidate())};}
test('invalid GLB mapping and empty animation preserve the current model and source',async()=>{const {context,original}=setup();for(const url of ['bad','empty']){await assert.rejects(context.load(url));assert.equal(context.model,original.scene);assert.equal(context.source,'original');}});
test('late prior GLB load cannot replace a newer selection',async()=>{const h=setup();const slow=h.context.load('slow');await h.context.load('new');const model=h.context.model;h.resolve();await slow;assert.equal(h.context.source,'new');assert.equal(h.context.model,model);});

test('capture waits for pending model load before reading its source',async()=>{const h=setup();const loading=h.context.load('slow');let captured=false;const capture=h.context.ready().then(()=>{captured=true;return h.context.source;});await Promise.resolve();assert.equal(captured,false);h.resolve();await loading;assert.equal(await capture,'slow');});

test('ready follows a newer selection while an earlier load is pending',async()=>{const h=setup();const loading=h.context.load('slow');const capture=h.context.ready().then(()=>h.context.source);await h.context.load('new');h.resolve();await loading;assert.equal(await capture,'new');});

test('failed pending model load prevents submission and preserves previous source',async()=>{const h=setup();const loading=h.context.load('bad');let submitted=0;const capture=h.context.ready().then(()=>{submitted++;});await assert.rejects(loading);await assert.rejects(capture);assert.equal(submitted,0);assert.equal(h.context.source,'original');});
