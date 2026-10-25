import test from 'node:test';
import assert from 'node:assert/strict';
import {cleanForm,loadForm,saveForm,imageProblem} from '../web/form-state.mjs';
test('stored input accepts only known values and bounded controls',()=>{
 const result=cleanForm({version:1,sample:'unknown',duration:'999',prompt:'x'.repeat(5000),'framing-scale':99,'framing-y':-9,customFile:true,hadImage:true,url:'file:///secret'});
 assert.equal(result.sample,undefined);assert.equal(result.duration,undefined);assert.equal(result.prompt.length,4000);assert.equal(result['framing-scale'],'1.6');assert.equal(result['framing-y'],'-0.2');assert.equal(result.url,undefined);assert.equal(result.customFile,true);
 assert.equal(cleanForm({version:2}),null);
});
test('unavailable or corrupt storage cannot break product input',()=>{
 assert.equal(loadForm({getItem(){throw Error('disabled');}}),null);
 assert.equal(loadForm({getItem(){return '{';}}),null);
 assert.equal(saveForm({setItem(){throw Error('quota');}},{version:1}),false);
});
test('image admission matches server byte and format limits',()=>{
 assert.ok(imageProblem(null));assert.ok(imageProblem({type:'image/gif',size:20}));
 assert.ok(imageProblem({type:'image/png',size:8*1024*1024+1}));
 assert.equal(imageProblem({type:'image/png',size:8*1024*1024}),'');
});
