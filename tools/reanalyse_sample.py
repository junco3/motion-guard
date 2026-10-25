"""Offline cached 6b7a pose reanalysis. No video inference or paid calls."""
import json
from pathlib import Path
from motionguard_core.observation_candidate import compare_candidate

ROOT=Path(__file__).resolve().parents[1]
def main():
    folder=ROOT/'public_samples/cached-6b7a'
    read=lambda name:json.loads((folder/name).read_text(encoding='utf-8'))
    report=compare_candidate(read('reference-pose.json'),read('generated-pose.json'),read('joints.json'))
    expected=read('expected-report.json')
    for key in ('verdict','thresholds_sha256','failures','display_failures'):
        assert report[key]==expected[key],key+' changed'
    assert report['observation_policy']['method']==expected['observation_policy']['method']
    assert report['observation_policy']['strict_report']['verdict']==expected['observation_policy']['strict_report']['verdict']
    out=ROOT/'data/sample-reanalysis';out.mkdir(parents=True,exist_ok=True)
    (out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'verdict':report['verdict'],'wrong_pose_cards':sum(f['type']=='WRONG_POSE' for f in report['display_failures']),
                      'matches_recorded_evidence':True,'method':'cached poses; no new video inference','output':'data/sample-reanalysis/report.json'}))
if __name__=='__main__':main()
