import argparse, hashlib, json
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description='Motion Guard provisional fixed-frame comparison')
    parser.add_argument('--version',action='version',version='0.0.1')
    commands=parser.add_subparsers(dest='command',required=True);c=commands.add_parser('compare')
    for name in ['ref','gen','out']:c.add_argument('--'+name,type=Path,required=True)
    c.add_argument('--gt',type=Path,help='Explicit versioned GT; missing input is an error')
    a=parser.parse_args()
    from .observation_candidate import compare_candidate as compare
    from .estimator import extract,make_estimator
    a.out.mkdir(parents=True,exist_ok=True)
    def find(root,names):
        if root.is_file():return root
        for name in names:
            if (root/name).is_file():return root/name
        raise FileNotFoundError('No supported video in '+str(root))
    try:
        rv=find(a.ref,['reference.mp4','ref_textured.mp4']);gv=find(a.gen,['generated.mp4','outputs/stage1_00001_.mp4']);gp=a.gt or a.ref/'joints.json'
        raw=gp.read_bytes();gt=json.loads(raw);m=make_estimator()
        r=extract(rv,a.out/'reference-pose.json',m);g=extract(gv,a.out/'generated-pose.json',m);result=compare(r,g,gt)
        result['sources']={label:{'path':str(p.resolve()),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for label,p in [('reference',rv),('generated',gv),('gt',gp)]}
        if result['sources']['gt']['sha256']!=hashlib.sha256(raw).hexdigest():raise ValueError('GT changed after loading')
        result['versions']={'primary_estimator':r['estimator'],'settings':r['settings'],'gt_visibility':gt.get('meta',{}).get('visibility_method')}
    except Exception as exc:result={'schema_version':'mg-report-2','verdict':'ERROR','error':str(exc),'failures':[]}
    (a.out/'report.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'verdict':result['verdict'],'report':str((a.out/'report.json').resolve())}))
    return 2 if result['verdict']=='ERROR' else 0

if __name__=='__main__':raise SystemExit(main())
