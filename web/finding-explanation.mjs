export function localMotionEvidence(f,report){
 const bounds=f.frames, joint=f.joints?.length===1?f.joints[0]:null;
 if(joint===null||!Array.isArray(bounds)||bounds.length!==2||!bounds.every(Number.isInteger)||bounds[1]<bounds[0])return null;
 const windows=(report?.metrics?.M5_energy?.joint_windows||[]).filter(w=>w.joint===joint&&Number.isInteger(w.start)&&Number.isInteger(w.end)&&w.end>=w.start&&w.start>=bounds[0]&&w.end<=bounds[1]&&Number.isFinite(w.ratio));
 if(!windows.length)return null;
 return {count:windows.length,below:windows.filter(w=>w.ratio<f.evidence?.threshold).length,min:Math.min(...windows.map(w=>w.ratio)),max:Math.max(...windows.map(w=>w.ratio))};
}
export function localPoseEvidence(f,report){
 const bounds=f.frames,values=report?.metrics?.M1_pck?.per_frame;
 if(!Array.isArray(values)||!Array.isArray(bounds)||bounds.length!==2||!bounds.every(Number.isInteger)||bounds[0]<0||bounds[1]<bounds[0]||bounds[1]>=values.length)return null;
 const observed=values.slice(bounds[0],bounds[1]+1).filter(v=>Number.isFinite(v)&&v>=0&&v<=1);
 if(!observed.length)return null;
 return {total:bounds[1]-bounds[0]+1,count:observed.length,mean:observed.reduce((a,b)=>a+b,0)/observed.length,min:Math.min(...observed),max:Math.max(...observed)};
}
export function findingBody(f,names){
 return f.joints?.length?f.joints.map(j=>names[j]||String(j)).join(', '):'Body part not identified (insufficient evidence)';
}
export function explainFindingDetails(f, body, report) {
 const e=f.evidence||{};
 const range=`${f.t_start_s.toFixed(2)}–${f.t_end_s.toFixed(2)}s · ${body}`;
 if(f.type==='OBSERVATION_GAP')return `${range}: The joints could not be compared reliably in this segment. It was not confirmed as a motion error. Check occlusion and off-screen movement.`;
 if(e.metric_name==='M1_pck'){
  const pose=localPoseEvidence(f,report),whole=report?.metrics?.M1_pck?.mean;
  const localText=pose?`Selected segment: ${pose.total} frames, of which ${pose.count} have values. Frame average of the share of observed joints that met the position criterion is ${(pose.mean*100).toFixed(1)}%, range ${(pose.min*100).toFixed(1)}–${(pose.max*100).toFixed(1)}%.`:'Local pose values for the selected segment were not confirmed.';
  const reference=Number.isFinite(whole)&&whole>=0&&whole<=1?` Note: The average over all judged frames is ${(whole*100).toFixed(1)}%, which differs from the selected-segment value.`:'';
  return `${range}: ${localText}${reference} Observed joints may vary from frame to frame. ${f.joints?.length?'Listed joints are those with enough valid observations in this segment and a high position mismatch rate.':'Body part not identified (insufficient evidence).'} Check the difference in the joint comparison between the reference and generated videos at the same time. This is not an appearance or finger-quality judgment, nor an accuracy score.`;
 }
 if(e.metric_name==='M9_finger_shape'&&Number.isFinite(e.metric_value)&&Number.isFinite(e.threshold))return `${range}: This finger kept a different shape from the reference for ${f.frames[1]-f.frames[0]+1} frames. Its tip was on average ${e.metric_value.toFixed(2)} hand sizes away from the reference position relative to the wrist; the criterion is ${e.threshold.toFixed(2)}. Fingers are compared using a hand estimate of the reference video, not 3D ground truth, and small hands are less reliable. Compare that hand in both videos at the same time.`;
 if(e.metric_name==='M1_joint_error'&&Number.isFinite(e.metric_value)&&Number.isFinite(e.threshold))return `${range}: This joint stayed away from its reference position for the whole segment (${f.frames[1]-f.frames[0]+1} frames). Its average distance was ${e.metric_value.toFixed(2)} torso lengths; the position criterion is ${e.threshold.toFixed(2)}. The rest of the body may match, so the whole-clip pose average can still look fine. Compare that body part in both videos at the same time. This is not a judgment of appearance quality.`;
 const local=localMotionEvidence(f,report);
 if(e.metric_name==='M5_joint_energy'&&local&&Number.isFinite(e.threshold))return `${range}: In this segment, the ${local.count} observation windows that compared this joint show movement of ${(local.min*100).toFixed(1)}–${(local.max*100).toFixed(1)}% of the reference video. The check criterion for this run is ${(e.threshold*100).toFixed(1)}%. Below the criterion: ${local.below} windows. These are overlapping observation windows, not a segment average, independent samples, or actual travel distance. This compares on-screen movement in observable frames. Check that body part in both videos.`;
 if(e.metric_name==='M5_joint_energy'&&Number.isFinite(e.metric_value)&&Number.isFinite(e.threshold))return `${range}: Less on-screen movement than the reference was detected. Local values for the selected segment were not confirmed. Across all observation windows of this joint, the minimum movement ratio relative to the reference is ${(e.metric_value*100).toFixed(1)}%, and the check criterion is ${(e.threshold*100).toFixed(1)}%. This number is neither an average for the selected segment alone nor an actual travel distance. Compare the movement of that body part in both videos.`;
 if(e.metric_name==='M4_lag_s'&&Number.isFinite(e.metric_value))return `${range}: Detected a timing difference. An individual lag for the selected segment is not provided. Note: the lag estimated from the full observation time series of the joints used in the comparison is ${e.metric_value.toFixed(2)}s. This does not mean every motion in the selected segment is that much late or early. Check which video shows the motion first at the same point in time.`;
 const scopes={M2_swap_ratio:'Average swap-error ratio computed over all left-right error frames of the joint pair',M3_terminal:'Average direction agreement of terminal joint motion, computed over all valid frames including normal observations',M3_root:'Average direction agreement computed over all torso-direction error frames',M3_root_window:'Average direction agreement computed over all torso-direction error observation windows'};
 if(scopes[e.metric_name]&&Number.isFinite(e.metric_value))return `${range}: Detected a difference from the reference motion. Local values for the selected segment are not provided. Note: ${scopes[e.metric_name]} is ${e.metric_value.toFixed(3)}. This is not an average for the selected segment alone.${e.metric_name==='M3_root_window'?' Observation windows overlap and are not independent samples.':''} Compare the reference and generated videos at the same time. This is not a judgment of appearance quality.`;
 return `${range}: Detected a difference from the reference motion. Check that body part at the same time. Measurement basis: ${e.metric_name||'see detailed report'}. The aggregation scope is not confirmed, so no value is shown. Do not interpret it as a selected-segment value before checking the scope in the detailed report. This is not a judgment of appearance quality.`;
}

export function explainFinding(f, body, report) {
 const e=f.evidence||{}, names=body.length>24?body.slice(0,23)+'…':body;
 const range=`${f.t_start_s.toFixed(2)}–${f.t_end_s.toFixed(2)}s · ${names}`;
 if(f.type==='OBSERVATION_GAP')return `${range} · insufficient comparison evidence`;
 if(e.metric_name==='M1_pck'){
  const local=e.scope==='interval_mean'&&Number.isFinite(e.metric_value)?e.metric_value:localPoseEvidence(f,report)?.mean;
  return `${range} · Pose match ${Number.isFinite(local)?Math.round(local*100)+'%':'unconfirmed'} (reference ${Number.isFinite(e.threshold)?Math.round(e.threshold*100)+'%':'unconfirmed'})`;
 }
 if(e.metric_name==='M9_finger_shape')return `${range} · Finger shape differs from the reference`;
 if(e.metric_name==='M1_joint_error')return `${range} · One body part off its reference position`;
 const labels={MISSING_MOTION:'Insufficient on-screen movement',TIMING_MISMATCH:'Timing difference',WRONG_DIRECTION:'Motion direction difference',WRONG_SIDE:'Left-right motion difference'};
 return `${range} · ${labels[f.type]||'Check measurement basis'}`;
}

export function poseSummary(report){
 const m=report?.metrics?.M1_pck||{},thr=m.threshold??report?.failures?.find(f=>f.evidence?.metric_name==='M1_pck')?.evidence?.threshold;
 const value=Number.isFinite(m.mean)?m.mean.toFixed(2):'unconfirmed',limit=Number.isFinite(thr)?thr.toFixed(2):'unconfirmed';
 return `Overall pose match ${value} / reference ${limit} · ${report.threshold_status||'threshold status unavailable'} · Whole-clip pose match ${value} / threshold ${limit}`;
}
