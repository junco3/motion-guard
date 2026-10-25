export const formKey='motion-guard-form-v1';
const choices={sample:['ual','cesium'],angle:['front','quarter','side'],duration:['4','10','20','30'],'execution-mode':['cloud_local_guard','platform_guarded','platform_layout']};
export function cleanForm(value){
 if(!value||value.version!==1)return null;
 const result={version:1};
 for(const [key,options] of Object.entries(choices))if(options.includes(value[key]))result[key]=value[key];
 for(const key of ['prompt','clip'])if(typeof value[key]==='string')result[key]=value[key].slice(0,key==='prompt'?4000:200);
 for(const key of ['repeat-clip','customFile','hadImage'])result[key]=value[key]===true;
 for(const [key,min,max] of [['framing-scale',.7,1.6],['framing-y',-.2,.2]])if(Number.isFinite(Number(value[key])))result[key]=String(Math.min(max,Math.max(min,Number(value[key]))));
 return result;
}
export function loadForm(storage){try{return cleanForm(JSON.parse(storage.getItem(formKey)));}catch{return null;}}
export function saveForm(storage,value){try{storage.setItem(formKey,JSON.stringify(cleanForm(value)));return true;}catch{return false;}}
export function imageProblem(file){
 if(!file)return 'Select a character image';
 if(!['image/png','image/jpeg','image/webp'].includes(file.type))return 'Select a PNG, JPEG or WebP image';
 if(file.size>8*1024*1024)return 'Choose a character image of 8MiB or less';
 return '';
}
