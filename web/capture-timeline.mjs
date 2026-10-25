export function captureTimeline(seconds=4){
 if(![4,10,20,30,40].includes(seconds))throw Error('Unsupported video length');
 return {frames:seconds*24+1,fps:24,sample_span_seconds:seconds,encoded_duration_seconds:(seconds*24+1)/24};
}
export function clipTime(index,duration,repeat=false){
 if(!Number.isInteger(index)||index<0||!Number.isFinite(duration)||duration<=0)throw Error('Invalid motion duration');
 return repeat?index/24:Math.min(index/24,Math.max(0,duration-1e-6));
}
