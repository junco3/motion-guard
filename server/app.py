"""Loopback-only Director server. Secrets never leave the server.

One persistent reservation per user job; ambiguous submissions remain blocked.
"""
import base64, hashlib, io, json, os, secrets, subprocess, threading, time, uuid, math
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlsplit,parse_qs
from PIL import Image
import requests
import sys

# Helpers importing app must share this server's lock and session token.
if __name__ == '__main__':
    sys.modules['app'] = sys.modules[__name__]

ROOT=Path(__file__).resolve().parents[1]
RUNS=ROOT/'data/gen'
TOKEN=secrets.token_urlsafe(32)
LOCK=threading.Lock()
REFERENCE_EXPORT=None
BASE='https://cloud.comfy.org'
# Hosted judging Space (Linux): key from a secret, public host, optional access code and run cap. Unset = local app.
PUBLIC_HOST=os.environ.get('MG_PUBLIC_HOST','')
ACCESS_CODE=os.environ.get('MG_ACCESS_CODE','')
MAX_GENERATIONS=int(os.environ.get('MG_MAX_GENERATIONS','0') or 0)
FEATURED_RUN=os.environ.get('MG_FEATURED_RUN','')
GENERATIONS_STARTED=0
LEDGER=ROOT/'config/t1-spend-ledger.json'
TERMINAL={'succeeded','failed','canceled','expired'}

def save(p,v):
    p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_suffix(p.suffix+'.tmp')
    with t.open('w',encoding='utf-8') as f:
        json.dump(v,f,indent=2,ensure_ascii=False,allow_nan=False);f.flush();os.fsync(f.fileno())
    os.replace(t,p)
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(b):return hashlib.sha256(b).hexdigest()

def ui_version():
    files=sorted(p for p in (ROOT/'web').iterdir() if p.suffix in ('.html','.mjs','.css'))
    return sha(b''.join(p.name.encode()+p.read_bytes() for p in files))
def key():
    if os.environ.get('COMFY_CLOUD_API_KEY'):return os.environ['COMFY_CLOUD_API_KEY'].strip()
    script="$s=(Get-Content -LiteralPath (Join-Path $env:LOCALAPPDATA 'MotionGuard/comfy-api-key.dpapi') -Raw).Trim()|ConvertTo-SecureString;$p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s);try{[Console]::Write([Runtime.InteropServices.Marshal]::PtrToStringBSTR($p))}finally{[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($p)}"
    return subprocess.check_output(['pwsh','-NoProfile','-NonInteractive','-Command',script],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).decode().strip()
def api(path,k):
    r=requests.get(BASE+path,headers={'X-API-Key':k},timeout=30,allow_redirects=False);r.raise_for_status();return r.json()

def nonnegative(value,label):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
        raise ValueError('Invalid '+label)
    return value

def authorized_ceiling(budget):
    value=nonnegative(budget.get('max_total_credits'),'authorized ceiling')
    if value<=0:raise ValueError('No positive credit ceiling')
    return value

def cumulative_prior(ledger,balance,credential):
    baseline=nonnegative(ledger.get('billing_baseline_cents'),'billing baseline cents')
    rate=nonnegative(ledger.get('credits_per_cent'),'credit conversion')
    if rate!=2.11:raise ValueError('Unsupported credit conversion')
    if ledger.get('credential_sha256')!=sha(credential.encode()):raise ValueError('Credential changed; preserve and rebind existing ledger explicitly')
    prior=nonnegative(ledger.get('conservative_prior_credits'),'cumulative credits')
    balance=nonnegative(balance,'current balance cents')
    return max(prior,max(0,(baseline-balance)*rate))
def binary(value):
    return base64.b64decode(value.split(',',1)[-1],validate=True)
def png(value,size=None):
    b=binary(value)
    if len(b)>8*1024*1024:raise ValueError('Image too large')
    with Image.open(io.BytesIO(b)) as im:
        if im.format not in ('PNG','JPEG','WEBP') or (size and im.size!=size):raise ValueError('Invalid image dimensions or format')
        if im.width*im.height>16_000_000:raise ValueError('Image too large')
        out=io.BytesIO();im.convert('RGB').save(out,format='PNG');return out.getvalue()
def encode(folder,name):
    subprocess.run(['ffmpeg','-v','error','-y','-framerate','24','-i',str(folder/'%04d.png'),'-c:v','libx264','-crf','12','-pix_fmt','yuv420p',str(name)],check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))

def monitor_job(job,deadline,update,cancel_requested=lambda:False):
    while job.status not in TERMINAL:
        try:job.refresh();update(cloud_status=job.status)
        except Exception as e:update(last_monitor_error=type(e).__name__)
        if job.status in TERMINAL:break
        if time.time()>=deadline or cancel_requested():
            try:job.cancel();update(cancel_requested=True,cloud_status=job.status)
            except Exception as e:update(last_cancel_error=type(e).__name__)
        time.sleep(3)

def prepare(payload,folder):
    if not isinstance(payload.get('prompt'),str) or not 1<=len(payload['prompt'])<=4000:raise ValueError('Prompt required')
    frames=payload['frames']
    layout=payload.get('execution_mode')=='platform_layout'
    size=(960,544) if layout else (768,512)
    if layout and (payload['meta'].get('width'),payload['meta'].get('height'))!=size:
        raise ValueError('Layout reference must be rendered at 960x544')
    from motionguard_core.reference_io import validate_timeline
    validate_timeline({'meta':payload['meta'],'frames':frames})
    model=binary(payload['model'])
    if len(model)>40*1024*1024 or model[:4]!=b'glTF':raise ValueError('Valid GLB required')
    (folder/'model.glb').write_bytes(model)
    (folder/'character.png').write_bytes(png(payload['image']))
    for sub in ('pose','reference'):(folder/sub).mkdir()
    hashes={}
    for i,f in enumerate(frames):
        if f['frame']!=i or not math.isfinite(f['time_s']) or abs(f['time_s']-i/24)>1e-8:raise ValueError('Frame timing mismatch')
        for sub,field in [('pose','pose'),('reference','render')]:
            b=png(f.pop(field),size);name=f'{sub}/{i:04d}.png';(folder/name).write_bytes(b);hashes[name]=sha(b)
    save(folder/'joints.json',{'meta':payload['meta'],'frames':frames})
    save(folder/'input.json',{'prompt':payload['prompt'],'meta':payload['meta'],'generator_mode':'layout' if layout else 'pose','model_sha256':sha(model),'character_sha256':sha((folder/'character.png').read_bytes()),'frame_hashes':hashes})
    encode(folder/'pose',folder/'pose.mp4');encode(folder/'reference',folder/'reference.mp4')

def control_path(folder):
    name=read(folder/'input.json').get('control_video','pose.mp4')
    if name not in ('pose.mp4','depth.mp4'):raise ValueError('Unsupported control video')
    path=folder/name
    if not path.is_file():raise ValueError('Missing selected control video')
    return path

def selected_gt(folder):
    request=read(folder/'input.json') if (folder/'input.json').is_file() else {}
    gt=request.get('gt_file') or ('joints.skin-v2.json' if (folder/'joints.skin-v2.json').is_file() else 'joints.json')
    if not isinstance(gt,str) or Path(gt).name!=gt or gt not in ('joints.json','joints.skin-v2.json','joints.observed.json'):
        raise ValueError('Invalid reference GT selection')
    path=folder/gt
    if path.resolve().parent!=folder.resolve() or not path.is_file():
        raise ValueError('Selected reference GT missing or outside run folder')
    return path

def analysis_inputs(folder):
    from run_paths import run_file
    record=folder/'guard-inputs.json'
    if record.is_file():
        inputs=read(record)
        for item in inputs.values():
            p=run_file(folder,item['path'])
            if p.resolve().parent!=folder.resolve() or not p.is_file() or sha(p.read_bytes())!=item['sha256']:raise ValueError('Analysis input missing or changed')
        return inputs
    state=read(folder/'state.json');old=state.get('guard_directory')
    if old and __import__('re').fullmatch(r'guard-[a-f0-9]{32}',old):
        inputs=read(folder/old/'report.json')['sources']
    else:
        gt=selected_gt(folder).name
        inputs={k:{'path':str((folder/v).resolve()),'sha256':sha((folder/v).read_bytes())} for k,v in [('gt',gt),('reference','reference.mp4'),('generated','generated.mp4')]}
    save(record,inputs)
    return analysis_inputs(folder)

def analyze(folder,release_lock=True):
    """Local-only analysis; never submit generation or change its terminal status."""
    try:
        state=read(folder/'state.json')
        if state.get('output_error'):return
        inputs=analysis_inputs(folder)
        state.update(guard_status='analyzing');save(folder/'state.json',state)
        import sys
        if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
        from comfy_nodes import MG_LoadReference,MG_ExtractPose,MG_Compare,MG_Report
        gt_file=Path(inputs['gt']['path']).name
        output=folder/('guard-'+uuid.uuid4().hex)
        reference=MG_LoadReference().load(str(folder),gt_file)[0]
        poses=MG_ExtractPose().extract(reference,str(folder/'generated.mp4'),str(output))[0]
        result=MG_Compare().compare(poses)[0];MG_Report().render(result)
        analysis_inputs(folder)
        state=read(folder/'state.json')
        # Publish the completed directory through one atomic state update.
        state.update(guard_status='complete',guard_verdict=result['report']['verdict'],guard_directory=output.name,guard_finished_at=time.time())
        state.pop('guard_error',None);save(folder/'state.json',state)
    except Exception as exc:
        try:
            state=read(folder/'state.json');state.update(guard_status='error',guard_verdict='ERROR',guard_error=type(exc).__name__);save(folder/'state.json',state)
        except Exception:pass  # Never turn a local reporting/storage error into a generation failure.
    finally:
        if release_lock:LOCK.release()

def generate_cloud_legacy(folder, diagnostic_graph=None, output_observer=None):
    state=read(folder/'state.json');job=None
    def update(**kw):state.update(kw);save(folder/'state.json',state)
    try:
        from comfy_sdk import Comfy
        from comfy_sdk.retry import NO_RETRY
        control=control_path(folder)
        from timeline_contract import validate_cloud, validate_cloud_output
        graph=read(diagnostic_graph or ROOT/'workflows/T1/depth-stage1.api.json')
        request=read(folder/'input.json')
        graph['5014/2483']['inputs']['text']=request['prompt']
        if 'seed' in request:
            seed=request['seed']
            if isinstance(seed,bool) or not isinstance(seed,int) or not 0<=seed<2**63:raise ValueError('Invalid seed')
            for node in graph.values():
                if 'noise_seed' in node.get('inputs',{}):node['inputs']['noise_seed']=seed
        expected=validate_cloud(folder,graph,selected_gt(folder).name,control.name)
        save(folder/'timeline-preflight.json',expected)
        save(folder/'workflow.api.json',graph)
        budget=read(ROOT/'config/budget.yaml')
        if not (budget.get('allow_paid_execution') is True and authorized_ceiling(budget)>0 and budget.get('cancel_after_submission_seconds')==600 and budget.get('additional_purchase_allowed') is False):raise ValueError('No active bounded authorization')
        k=key();billing=api('/api/billing/usage/timeseries?months=1',k)
        balance=billing['summary']['balance']['cloud_credit_balance_cents']
        ledger=read(LEDGER);prior=cumulative_prior(ledger,balance,k)
        if ledger['unresolved_jobs'] or prior+179.6>authorized_ceiling(budget):raise ValueError('Unresolved job or insufficient cumulative budget')
        queue=api('/api/queue',k)
        if queue.get('queue_running') or queue.get('queue_pending'):raise ValueError('Cloud queue occupied')
        save(folder/'billing-before.json',billing)
        # Reservation survives process restart and any ambiguous POST response.
        save(folder/'reservation.json',{'prior':prior,'reserved':179.6,'ceiling':authorized_ceiling(budget),'released':False})
        update(status='uploading')
        with Comfy(api_key=k,timeout=30,retry=NO_RETRY) as client:
            wf=client.workflows.from_file(folder/'workflow.api.json')
            wf.set_input('2004','image',client.assets.from_file(folder/'character.png'))
            wf.set_input('5001','file',client.assets.from_file(control))
            # Explicit upload before the submission marker separates upload errors.
            for handle in (wf.json['2004']['inputs']['image'],wf.json['5001']['inputs']['file']):handle.commit()
            if (folder/'cancel-request.json').exists():raise ValueError('Canceled before submission')
            update(status='submitting',submitted_at=time.time(),idempotency_key=str(uuid.uuid4()))
            with (folder/'attempt.json').open('x',encoding='utf-8') as f:
                json.dump(state,f);f.flush();os.fsync(f.fileno())
            job=client.submit(wf,idempotency_key=state['idempotency_key'])
            update(job_id=job.id,status='generating',cloud_status=job.status)
            deadline=state['submitted_at']+600
            monitor_job(job,deadline,update,lambda:(folder/'cancel-request.json').exists())
            update(terminal_status=job.status,status='saving')
            save(folder/'job-result.json',{'job_id':job.id,'status':job.status,'outputs':[{'id':o.id,'content_type':o.content_type,'size_bytes':o.size_bytes} for o in job.outputs]})
            if job.status=='succeeded':
                if output_observer is not None:output_observer(job,folder)
                videos=[o for o in job.outputs if o.content_type=='video/mp4']
                if diagnostic_graph is not None:videos=[o for o in videos if o.node_id=='diag_save']
                if not videos:raise RuntimeError('No MP4 output')
                videos[0].to_file(folder/'generated.mp4')
                save(folder/'timeline-output.json',validate_cloud_output(folder/'generated.mp4',expected))
                subprocess.run(['ffmpeg','-v','error','-y','-i',str(folder/'reference.mp4'),'-i',str(folder/'generated.mp4'),'-filter_complex','[0:v]scale=768:512,setsar=1[a];[1:v]scale=768:512,setsar=1[b];[a][b]hstack=inputs=2','-an','-c:v','libx264','-crf','18',str(folder/'comparison.mp4')],check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            # Conservative reservation is charged in full until billing reconciled.
            ledger=read(LEDGER);ledger['conservative_prior_credits']=prior+179.6
            ledger['known_runs'].append(folder.name);ledger['scope']='All Motion Guard attempts, T1 onward; no reset'
            save(LEDGER,ledger);r=read(folder/'reservation.json');r.update(released=True,charged_conservatively=179.6);save(folder/'reservation.json',r)
            update(status=job.status,finished_at=time.time())
            if job.status=='succeeded':analyze(folder,release_lock=False)
    except Exception as e:
        # Never expose request/credential-bearing exception strings to clients.
        remote_terminal=state.get('terminal_status') in TERMINAL
        invalid_output=getattr(e,'evidence',None)
        if invalid_output is not None:
            save(folder/'output-validation.json',invalid_output)
            state.update(guard_status='not_started',guard_verdict='ERROR',
                         output_error=invalid_output.get('reason'))
        update(status='failed' if remote_terminal else 'unresolved' if (folder/'attempt.json').exists() else 'preflight_failed',
               error_type=type(e).__name__,
               failure_stage='output_validation' if invalid_output is not None else 'output_processing' if remote_terminal else 'submission_or_preflight')
        if remote_terminal and (folder/'reservation.json').exists():
            reservation=read(folder/'reservation.json')
            if not reservation.get('released'):
                ledger=read(LEDGER)
                if folder.name not in ledger['known_runs']:
                    ledger['conservative_prior_credits']=max(ledger['conservative_prior_credits'],reservation['prior'])+reservation['reserved']
                    ledger['known_runs'].append(folder.name)
                    save(LEDGER,ledger)
                reservation.update(released=True,charged_conservatively=reservation['reserved'],reason='Remote terminal; local output processing failed')
                save(folder/'reservation.json',reservation)
        save(folder/'error.json',{'type':type(e).__name__,'message':str(e)[:1500]})
        if not (folder/'attempt.json').exists() and (folder/'reservation.json').exists():
            r=read(folder/'reservation.json');r.update(released=True,reason='No submission attempted');save(folder/'reservation.json',r)
    finally:LOCK.release()

def technical_view(folder):
    import yaml
    state=read(folder/'state.json')
    plan=read(folder/'execution-plan.json') if (folder/'execution-plan.json').is_file() else {}
    mode=plan.get('generator_mode')
    configuration=None
    if state.get('source_type')=='platform_guarded':
        build_path=ROOT/'workflows'/('Layout' if mode=='layout' else 'T5')/'comfy-build.yaml'
        if not build_path.is_file():build_path=build_path.with_name('comfy-build.template.yaml')
        build=yaml.safe_load(build_path.read_text(encoding='utf-8'))
        definition=build.get('definition',{})
        configuration={'notice':'This is the currently saved configuration. It is not a guarantee that it matches the remote environment of past runs.',
          'build_id':build.get('id'),'configuration_sha256':sha(build_path.read_bytes()),
          'comfy_commit':definition.get('baseComfyVersion'),
          'models':[{'filename':m.get('filename'),'sha256':m.get('sha256'),'type':m.get('type')} for m in definition.get('models',[])]}
    audit={}
    if (folder/'downstream-result.json').is_file():
        source=read(folder/'downstream-result.json').get('stage_audit',{})
        audit={k:source.get(k) for k in ('entered','completed','held','guard_verdict','graph_sha256','code_sha256') if k in source}
    return {'run_id':folder.name,'execution_record':{k:state.get(k) for k in ('status','job_id','guard_status','guard_verdict','downstream_status','error_type')},
      'recorded_plan':{k:plan.get(k) for k in ('generator_mode','approved_release_id','execution_id','stage_audit') if k in plan},
      'workflow_sha256':sha((folder/'workflow.api.json').read_bytes()) if (folder/'workflow.api.json').is_file() else None,
      'stage_audit':audit,'current_configuration':configuration,
      'limits':'Safe run record summary. Not the full raw log. The exact version of unrecorded configurations or Cloud-provided models is unconfirmed.'}

BACKGROUND_RUNNING=set();BACKGROUND_LOCK=threading.Lock()

def quality_view(folder,state,name):
    """Quality warnings (never the verdict): 'background-check' on the draft video, 'head-check' on the
    poses the check already estimated. Each is computed once in the background and cached in the run folder."""
    path=folder/(name+'.json')
    if path.is_file():
        try:return read(path)
        except (OSError,ValueError):return None
    directory=state.get('guard_directory','')
    if state.get('guard_status')!='complete' or not __import__('re').fullmatch(r'guard-[a-f0-9]{32}',directory):return None
    guard=folder/directory
    needed=[folder/'generated.mp4',folder/'reference.mp4'] if name=='background-check' else [guard/'reference-pose.json',guard/'generated-pose.json']
    if not all(p.is_file() for p in needed+[guard/'report.json']):return None
    key=(folder.name,name)
    with BACKGROUND_LOCK:
        if key in BACKGROUND_RUNNING:return {'status':'pending'}
        BACKGROUND_RUNNING.add(key)
    def worker():
        try:
            if name=='background-check':
                from background_check import check
                result=check(folder/'generated.mp4',folder/'reference.mp4',read(guard/'report.json').get('metrics',{}).get('M8_framing') or {})
            else:
                from head_check import check_folder
                result=check_folder(guard,ROOT/'config/thresholds.yaml')
        except Exception as exc:
            result={'status':'unavailable','reason':type(exc).__name__,'affects_verdict':False}
        save(path,result)
        with BACKGROUND_LOCK:BACKGROUND_RUNNING.discard(key)
    threading.Thread(target=worker,daemon=True).start()
    return {'status':'pending'}

def job_view(folder):
    state=read(folder/'state.json')
    state['cancel_requested']=(folder/'cancel-request.json').exists()
    state['pixel_cancel_requested']=(folder/'pixel-cancel-request.json').exists()
    from pixel_followup import view as pixel_view
    state=pixel_view(folder,state)
    state['draft_available']=False
    if state.get('source_type')=='platform_guarded' and (folder/'draft-result.json').is_file():
        try:
            draft=read(folder/'draft-result.json');plan=read(folder/'execution-plan.json')
            if (draft['execution_id']==plan['execution_id'] and
                draft['generated_sha256']==sha((folder/'generated.mp4').read_bytes()) and
                draft['reference_sha256']==sha((folder/'reference.mp4').read_bytes())):
                state['draft_available']=True
                state['draft_comparison_available']=(folder/'comparison.mp4').is_file()
                return state
        except (OSError,ValueError,KeyError,TypeError):
            pass
    if state.get('source_type')=='platform_guarded' and state.get('guard_status')=='complete':
        try:
            pins=read(folder/'guard-inputs.json')
            for role,name in [('reference','reference.mp4'),('generated','generated.mp4')]:
                path=folder/name
                from run_paths import run_file
                if run_file(folder,pins[role]['path']).resolve()!=path.resolve() or sha(path.read_bytes())!=pins[role]['sha256']:
                    raise ValueError('Recovered draft changed')
            state['draft_available']=True
            state['draft_comparison_available']=(folder/'comparison.mp4').is_file()
        except (OSError,ValueError,KeyError,TypeError):
            pass
    return state

BILLING_LOCK=threading.Lock()
BILLING_NEXT_REFRESH=0.0

def refresh_billing():
    """Read-only background refresh, with failure cooldown and account binding."""
    global BILLING_NEXT_REFRESH
    if time.monotonic()<BILLING_NEXT_REFRESH or not BILLING_LOCK.acquire(blocking=False):return
    BILLING_NEXT_REFRESH=time.monotonic()+60
    def worker():
        try:
            pinned=read(LEDGER)
            identity={k:pinned[k] for k in ('credential_sha256','billing_baseline_cents','credits_per_cent')}
            credential=key()
            if sha(credential.encode())!=identity['credential_sha256']:return
            response=api('/api/billing/usage/timeseries?months=1',credential)
            balance=nonnegative(response['summary']['balance']['cloud_credit_balance_cents'],'balance')
            current=read(LEDGER)
            if any(current[k]!=v for k,v in identity.items()):return
            save(ROOT/'data/billing-display.json',{'as_of':response['as_of'],
                'credential_sha256':identity['credential_sha256'],
                'baseline_cents':identity['billing_baseline_cents'],
                'credits_per_cent':identity['credits_per_cent'],'balance_cents':balance,
                'source':'Comfy billing usage timeseries; shared account balance difference'})
        except (OSError,ValueError,KeyError,TypeError,requests.RequestException,subprocess.SubprocessError):
            pass
        finally:BILLING_LOCK.release()
    threading.Thread(target=worker,daemon=True).start()

def billing_display():
    """Last verified shared-account debit; reservations are never expenditure."""
    try:
        ledger=read(LEDGER);snapshot=read(ROOT/'data/billing-display.json')
        if snapshot['credential_sha256']!=ledger['credential_sha256']:raise ValueError('Account binding changed')
        baseline=nonnegative(snapshot['baseline_cents'],'baseline')
        balance=nonnegative(snapshot['balance_cents'],'balance')
        rate=nonnegative(snapshot['credits_per_cent'],'rate')
        if baseline!=ledger['billing_baseline_cents'] or rate!=ledger['credits_per_cent'] or rate!=2.11:raise ValueError('Baseline changed')
        ceiling=authorized_ceiling(read(ROOT/'config/budget.yaml'))
        debit=(baseline-balance)*rate if balance<=baseline else None
        return {'status':'last_verified','as_of':snapshot['as_of'],
                'account_balance_credits':balance*rate,'account_decrease_credits':debit,
                'authorized_remaining_after_verified_debit':max(0,ceiling-debit) if debit is not None else None,
                'reconciliation_required':debit is None,'scope':'shared_account','reservation_is_spending':False}
    except (OSError,ValueError,KeyError,TypeError):
        return {'status':'unavailable','account_balance_credits':None,'account_decrease_credits':None,
                'authorized_remaining_after_verified_debit':None,'reservation_is_spending':False}

def generation_policy(selected_mode=None):
    try:
        mode=selected_mode if selected_mode is not None else read(ROOT/'config/application-mode.json')['mode']
        if mode not in ('cloud_local_guard','platform_guarded','platform_layout'):raise ValueError('Unknown generation mode')
        ledger=read(LEDGER);required=179.6 if mode=='cloud_local_guard' else 202
        budget=read(ROOT/'config/budget.yaml');ceiling=authorized_ceiling(budget)
        remaining=max(0,ceiling-nonnegative(ledger['conservative_prior_credits'],'cumulative credits'))
        config_path=ROOT/('config/layout-runtime.json' if mode=='platform_layout' else 'config/guarded-runtime.json')
        config=read(config_path) if config_path.exists() else {}
        configured=mode=='cloud_local_guard' or config.get('enabled') is True
        readiness={'ready':True}
        if mode in ('platform_guarded','platform_layout') and configured:
            from comfy_cli.deploy_api import DeployClient
            from platform_preflight import preview
            readiness=preview(ROOT,config)
            if mode=='platform_layout':
                from layout_claim import completed_claim
                if not completed_claim(ROOT,config,ledger):
                    readiness={'ready':False,'reason':'Checking previous Layout job run, settlement, and resource cleanup','required_reservation':None}
            required=readiness.get('required_reservation')
        authorized=read(ROOT/'config/budget.yaml').get('allow_paid_execution') is True
        allowed=authorized and configured and readiness['ready'] and not ledger['unresolved_jobs'] and remaining>=required
        reason='' if allowed else ('Follow-up processing path disabled' if not configured else 'Paid run disabled' if not authorized else 'Run readiness check required: '+readiness['reason'] if not readiness['ready'] else 'Waiting for previous job settlement' if ledger['unresolved_jobs'] else 'Insufficient reserved budget')
        return {'ceiling':ceiling,'prior':ledger['conservative_prior_credits'],'mode':mode,'remaining_reserved_budget':remaining,'required_reservation':required,'generation_allowed':allowed,'unavailable_reason':reason}
    except (OSError,ValueError,KeyError,TypeError,ImportError) as exc:
        return {'prior':None,'mode':'unavailable','generation_allowed':False,'policy_error':type(exc).__name__}

def generate(folder,mode):
    if mode=='cloud_local_guard':
        return generate_cloud_legacy(folder)
    try:
        if mode not in ('platform_guarded','platform_layout'):raise ValueError('Unknown pinned generation mode')
        if (folder/'cancel-request.json').exists():raise ValueError('Canceled before execution preparation')
        if mode=='platform_layout':
            from app_layout import generate as guarded_generate
        else:
            from app_guarded import generate as guarded_generate
        guarded_generate(folder)
    except Exception as exc:
        import traceback;traceback.print_exc()  # server log only; the run record keeps just the type
        state=read(folder/'state.json')
        if state.get('status') not in TERMINAL:
            state.update(status='unresolved' if (folder/'attempt.json').exists() else 'preflight_failed',error_type=type(exc).__name__)
            save(folder/'state.json',state)
    finally:LOCK.release()

def recover_platform(folder):
    try:
        from app_guarded import resume
        resume(folder)
    except Exception as exc:
        state=read(folder/'state.json');state.update(status='unresolved',recovery_error_type=type(exc).__name__);save(folder/'state.json',state)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def reply(self,code,value):
        b=json.dumps(value).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(b)
    def host_ok(self):
        host=self.headers.get('Host')
        return host==f'127.0.0.1:{self.server.server_port}' or bool(PUBLIC_HOST) and PUBLIC_HOST in (host,self.headers.get('X-Forwarded-Host'))
    def origin_ok(self):
        origin=self.headers.get('Origin')
        return origin==f'http://127.0.0.1:{self.server.server_port}' or bool(PUBLIC_HOST) and origin==f'https://{PUBLIC_HOST}'
    def access_ok(self):
        return not ACCESS_CODE or secrets.compare_digest(self.headers.get('X-MotionGuard-Access',''),ACCESS_CODE)
    def do_POST(self):
        global REFERENCE_EXPORT
        if not self.host_ok() or not self.origin_ok() or not secrets.compare_digest(self.headers.get('X-MotionGuard-Token',''),TOKEN):return self.reply(403,{'error':'Forbidden'})
        if self.path=='/api/reference-export':
            try:
                n=int(self.headers.get('Content-Length',0))
                if n>32*1024*1024:return self.reply(413,{'error':'Reference exceeds 32 MiB'})
                if n<=0:raise ValueError('Empty reference')
                value=json.loads(self.rfile.read(n))
                if not isinstance(value,dict) or not isinstance(value.get('meta'),dict) or not isinstance(value.get('frames'),list) or not all(isinstance(f,dict) for f in value['frames']):raise ValueError('Invalid structure')
                from motionguard_core.reference_io import validate_timeline
                validate_timeline(value)
                content=json.dumps(value,allow_nan=False).encode()
                export_id=uuid.uuid4().hex
                REFERENCE_EXPORT=(export_id,content)
                return self.reply(200,{'export_id':export_id})
            except (ValueError,TypeError,KeyError):return self.reply(400,{'error':'Invalid reference'})
        if self.path=='/api/cancel':
            try:
                n=int(self.headers.get('Content-Length',0))
                if not 0<n<=4096:raise ValueError('Invalid request')
                run=json.loads(self.rfile.read(n)).get('run_id','')
                if not __import__('re').fullmatch(r't3-[a-f0-9]{32}',run):raise ValueError('Invalid run')
                folder=RUNS/run
                state=job_view(folder)
                pixel=state.get('pixel_followup',{}).get('status') in ('ready','submitting','running')
                if state.get('status') in TERMINAL|{'preflight_failed','input_rejected','unresolved'} and not pixel:return self.reply(409,{'error':'No cancellable remote execution'})
                marker=folder/('pixel-cancel-request.json' if pixel else 'cancel-request.json')
                if not marker.exists():save(marker,{'run_id':run,'requested_at':time.time()})
                return self.reply(202,{'run_id':run,'cancel_requested':True,'terminal_confirmed':False})
            except (OSError,ValueError,TypeError,KeyError):return self.reply(400,{'error':'Invalid cancellation request'})
        if self.path in ('/api/finalize','/api/generate') and not self.access_ok():return self.reply(403,{'error':'Access code required'})
        if self.path=='/api/finalize':
            if not LOCK.acquire(blocking=False):return self.reply(409,{'error':'Job already active'})
            started=False
            try:
                n=int(self.headers.get('Content-Length',0))
                if not 0<n<=4096:raise ValueError('Invalid finalization request')
                run=json.loads(self.rfile.read(n)).get('run_id','')
                if not __import__('re').fullmatch(r't3-[a-f0-9]{32}',run):raise ValueError('Invalid run')
                folder=(RUNS/run).resolve()
                if folder.parent!=RUNS.resolve() or not (folder/'state.json').is_file():raise ValueError('Unknown run')
                from pixel_followup import begin, run as pixel_run
                decision,launch=begin(folder)
                if launch:
                    threading.Thread(target=pixel_run,args=(folder,),daemon=False).start()
                    started=True
                self.reply(202 if launch else 200,{'run_id':run,'pixel_followup':decision})
            except Exception as exc:
                if not started:self.reply(400,{'error':type(exc).__name__})
            finally:
                if not started:LOCK.release()
            return
        if self.path=='/api/analyze':
            if not LOCK.acquire(blocking=False):return self.reply(409,{'error':'Job already active'})
            started=False
            try:
                n=int(self.headers.get('Content-Length',0))
                if not 0<n<=4096:raise ValueError('Invalid analysis request')
                run=json.loads(self.rfile.read(n)).get('run_id','')
                if not __import__('re').fullmatch(r't3-[a-f0-9]{32}',run):raise ValueError('Invalid run')
                folder=(RUNS/run).resolve()
                if folder.parent!=RUNS.resolve() or not (folder/'state.json').is_file():raise ValueError('Unknown run')
                state=read(folder/'state.json')
                if state.get('output_error'):
                    LOCK.release();started=True
                    return self.reply(422,{'error':'Invalid generated video','reason':state['output_error']})
                if state.get('source_type')=='platform_guarded':
                    analysis_inputs(folder)
                    if state.get('guard_status')!='complete':raise ValueError('Remote Guard result unavailable')
                    report=read(folder/state['guard_directory']/'report.json')
                    if report['sources']!=read(folder/'guard-inputs.json'):raise ValueError('Remote Guard source binding changed')
                    LOCK.release();started=True
                    return self.reply(200,{'run_id':run,'guard_status':'complete','reused_remote_result':True})
                if state.get('status')!='succeeded' or not (folder/'generated.mp4').is_file():raise ValueError('Generated result unavailable')
                state.update(guard_status='analyzing');save(folder/'state.json',state)
                threading.Thread(target=analyze,args=(folder,),daemon=False).start();started=True
                self.reply(202,{'run_id':run,'guard_status':'analyzing'})
            except Exception as exc:
                if not started:LOCK.release();self.reply(400,{'error':type(exc).__name__})
            return
        if self.path!='/api/generate':return self.reply(404,{})
        global GENERATIONS_STARTED
        if MAX_GENERATIONS and GENERATIONS_STARTED>=MAX_GENERATIONS:return self.reply(429,{'error':'Generation limit for this hosted demo reached'})
        n=int(self.headers.get('Content-Length',0))
        if not 0<n<=120*1024*1024:return self.reply(413,{'error':'Payload size'})
        if not LOCK.acquire(blocking=False):return self.reply(409,{'error':'Job already active'})
        folder=None;worker_started=False
        try:
            for p in RUNS.glob('t3-*/reservation.json'):
                if not read(p).get('released'):raise ValueError('Unresolved reservation; no new submission')
            for p in RUNS.glob('t3-*/state.json'):
                if read(p)['status'] in ('submitting','unresolved','uploading','saving'):raise ValueError('Unresolved previous run')
            payload=json.loads(self.rfile.read(n),parse_constant=lambda x:(_ for _ in ()).throw(ValueError('Nonfinite input')))
            if not isinstance(payload,dict):raise ValueError('Invalid request')
            request_id=payload.get('request_id')
            if request_id is not None and not __import__('re').fullmatch(r'[a-f0-9-]{36}',request_id):raise ValueError('Invalid request id')
            selected=payload.get('execution_mode')
            if selected is not None and selected not in ('cloud_local_guard','platform_guarded','platform_layout'):raise ValueError('Unknown generation mode')
            policy=generation_policy(selected) if selected is not None else generation_policy()
            if not policy['generation_allowed']:
                LOCK.release();worker_started=True
                return self.reply(409,{'error':'The selected generation path cannot be run.','policy':policy})
            folder=RUNS/('t3-'+uuid.uuid4().hex);folder.mkdir(parents=True)
            save(folder/'state.json',{'run_id':folder.name,'status':'preparing','execution_mode':policy['mode'],'source_type':policy['mode']})
            if request_id:save(folder/'request.json',{'request_id':request_id})
            prepare(payload,folder)
            threading.Thread(target=generate,args=(folder,policy['mode']),daemon=False).start()
            worker_started=True;GENERATIONS_STARTED+=1
            self.reply(202,{'run_id':folder.name})
        except Exception as e:
            if worker_started:return  # Worker retains state and lock after client disconnect.
            if folder:save(folder/'state.json',{'run_id':folder.name,'status':'input_rejected','error_type':type(e).__name__})
            LOCK.release();self.reply(400,{'error':str(e)[:200]})
    def do_GET(self):
        if not self.host_ok():return self.reply(403,{})
        name=urlsplit(self.path).path
        if name=='/api/version':return self.reply(200,{'version':ui_version()})
        if name.startswith('/api/technical/'):
            run=name.rsplit('/',1)[-1]
            if not __import__('re').fullmatch(r't3-[a-f0-9]{32}',run):return self.reply(404,{})
            folder=(RUNS/run).resolve()
            if folder.parent!=RUNS.resolve() or not (folder/'state.json').is_file():return self.reply(404,{})
            try:return self.reply(200,technical_view(folder))
            except (OSError,ValueError,KeyError,TypeError):return self.reply(409,{'error':'Cannot verify the technical record.'})
        if name=='/api/reference-export':
            query=parse_qs(urlsplit(self.path).query)
            if not secrets.compare_digest(query.get('token',[''])[0],TOKEN):return self.reply(403,{})
            snapshot=REFERENCE_EXPORT
            if snapshot is None or query.get('id',[''])[0]!=snapshot[0]:return self.reply(410,{'error':'Prepare this reference again'})
            content=snapshot[1]
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Disposition','attachment; filename="motion-reference.json"');self.send_header('Content-Length',str(len(content)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(content);return
        if name=='/api/billing':
            refresh_billing()
            return self.reply(200,{**billing_display(),'refreshing':BILLING_LOCK.locked()})
        if name=='/api/session':return self.reply(200,{'token':TOKEN,'access_required':bool(ACCESS_CODE),'billing':billing_display(),**generation_policy(),'modes':{m:generation_policy(m) for m in ('cloud_local_guard','platform_guarded','platform_layout')}})
        if name=='/api/active-runs' or name.startswith('/api/requests/'):
            request_id=name.split('/')[-1] if name.startswith('/api/requests/') else None
            if request_id and not __import__('re').fullmatch(r'[a-f0-9-]{36}',request_id):return self.reply(404,{})
            rows=[]
            for p in RUNS.glob('t3-*/state.json'):
                if not __import__('re').fullmatch(r't3-[a-f0-9]{32}',p.parent.name):continue
                try:
                    state=job_view(p.parent)
                    active=state.get('status') not in TERMINAL|{'preflight_failed','input_rejected'} or state.get('guard_status')=='analyzing' or state.get('pixel_followup',{}).get('status') in ('ready','submitting','running','unresolved')
                    matches=(p.parent/'request.json').is_file() and read(p.parent/'request.json').get('request_id')==request_id
                    if matches if request_id else active:rows.append({'run_id':p.parent.name,**state})
                except (OSError,ValueError,KeyError):continue
            return self.reply(200,rows)
        if name=='/api/completed-runs':
            rows=[]
            for p in RUNS.glob('t3-*/state.json'):
                try:state=read(p)
                except (OSError,ValueError):continue
                failed_request=state.get('status') in ('failed','preflight_failed','input_rejected','canceled','expired') and ((p.parent/'attempt.json').is_file() or (p.parent/'request.json').is_file())
                submitted_error = state.get('source_type')=='platform_guarded' and state.get('guard_status')=='error' and bool(state.get('job_id')) and (p.parent/'attempt.json').exists()
                if __import__('re').fullmatch(r't3-[a-f0-9]{32}',p.parent.name) and (state.get('status')=='succeeded' or state.get('guard_status')=='complete' or submitted_error or failed_request or (state.get('output_error') and state.get('job_id') and (p.parent/'attempt.json').is_file())):
                    finished=state.get('finished_at')
                    valid_time=isinstance(finished,(int,float)) and not isinstance(finished,bool) and __import__('math').isfinite(finished)
                    try:clip=read(p.parent/'joints.json').get('meta',{}).get('clip','unknown')
                    except (OSError,ValueError,AttributeError):clip='unknown'
                    rows.append({'run_id':p.parent.name,'clip':clip,'status':state.get('status'),'generation_status':state.get('generation_status'),'stage2_status':state.get('stage2_status'),'draft_available':job_view(p.parent).get('draft_available',False),
                                 'source_type':state.get('source_type','unknown'),'guard_verdict':state.get('guard_verdict'),
                                 'guard_status':state.get('guard_status'),'output_error':state.get('output_error'),
                                 'finished_at':finished if valid_time else None,'sort_time':finished if valid_time else p.stat().st_mtime})
            rows.sort(key=lambda row:(row['run_id']==FEATURED_RUN,row['sort_time'],row['run_id']),reverse=True)
            return self.reply(200,rows)
        if name.startswith('/api/jobs/'):
            run=name.split('/')[-1]
            if not __import__('re').fullmatch(r't3-[a-f0-9]{32}',run):return self.reply(404,{})
            p=RUNS/run/'state.json'
            if not p.exists():return self.reply(404,{})
            state=job_view(p.parent)
            state['background_check']=quality_view(p.parent,state,'background-check')
            state['head_check']=quality_view(p.parent,state,'head-check')
            return self.reply(200,state)
        allowed={'/':'web/index.html','/web/director.mjs':'web/director.mjs','/web/generate.mjs':'web/generate.mjs','/workflows/T1/inputs/UAL1_Standard.glb':'workflows/T1/inputs/UAL1_Standard.glb','/data/public_samples/CesiumMan.glb':'data/public_samples/CesiumMan.glb'}
        allowed['/web/failure-timeline.mjs']='web/failure-timeline.mjs'
        allowed['/web/finding-explanation.mjs']='web/finding-explanation.mjs'
        allowed['/web/result-comparison.mjs']='web/result-comparison.mjs'
        allowed['/web/capture-timeline.mjs']='web/capture-timeline.mjs'
        allowed['/web/studio.css']='web/studio.css'
        allowed['/web/studio.mjs']='web/studio.mjs'
        allowed['/web/form-state.mjs']='web/form-state.mjs'
        allowed.update({'/info/install':'README.md','/info/licenses':'docs/licenses.md','/info/license-scope':'LICENSE_SCOPE.md'})
        allowed.update({f'/public_samples/{n}':f'public_samples/{n}' for n in ('reference.mp4','generated.mp4','character.png')})
        rel=allowed.get(name)
        if name.startswith('/web/node_modules/three/'):rel=name[1:]
        if __import__('re').fullmatch(r'/results/t3-[a-f0-9]{32}/(reference|generated|comparison)\.mp4',name):rel='data/gen/'+name[len('/results/'):]
        pixel_match=__import__('re').fullmatch(r'/results/(t3-[a-f0-9]{32})/pixel-final\.mp4',name)
        if pixel_match:
            supplied=parse_qs(urlsplit(self.path).query).get('token',[''])[0]
            if not secrets.compare_digest(supplied,TOKEN):return self.reply(403,{})
            folder=(RUNS/pixel_match[1]).resolve()
            if folder.parent!=RUNS.resolve():return self.reply(404,{})
            try:
                from pixel_followup import verified_report
                pixel=read(folder/'pixel-state.json');p=folder/'pixel-final.mp4'
                if pixel.get('status')!='complete' or pixel.get('allowed') is not True:return self.reply(404,{})
                if verified_report(folder)[1]!=read(folder/'pixel-request.json'):return self.reply(409,{'error':'Draft binding changed'})
                if sha(p.read_bytes())!=pixel['final_sha256']:return self.reply(409,{'error':'Final video changed'})
            except (OSError,ValueError,KeyError):return self.reply(404,{})
            rel=str(p.relative_to(ROOT))
        final_match=__import__('re').fullmatch(r'/results/(t3-[a-f0-9]{32})/final\.mp4',name)
        if final_match:
            supplied=parse_qs(urlsplit(self.path).query).get('token',[''])[0]
            if not secrets.compare_digest(supplied,TOKEN):return self.reply(403,{})
            folder=(RUNS/final_match[1]).resolve()
            if folder.parent!=RUNS.resolve():return self.reply(404,{})
            try:
                state=read(folder/'state.json');result=read(folder/'downstream-result.json');p=folder/'final.mp4'
                if (state.get('status')!='succeeded' or state.get('downstream_status')!='complete'
                    or state.get('final_available') is not True or result.get('guard_verdict')!='PASS'):return self.reply(404,{})
                if sha(p.read_bytes())!=result['final_sha256']:return self.reply(409,{'error':'Final video changed'})
            except (OSError,ValueError,KeyError):return self.reply(404,{})
            rel=str(p.relative_to(ROOT))
        match=__import__('re').fullmatch(r'/results/(t3-[a-f0-9]{32})/guard/(report\.json|overlay\.mp4|observation-gaps\.json|stage-context\.json)',name)
        if match:
            supplied=parse_qs(urlsplit(self.path).query).get('token',[''])[0]
            if not secrets.compare_digest(supplied,TOKEN):return self.reply(403,{})
            folder=(RUNS/match[1]).resolve()
            if folder.parent!=RUNS.resolve() or not (folder/'state.json').is_file():return self.reply(404,{})
            state=read(folder/'state.json');directory=state.get('guard_directory','')
            if state.get('guard_status')!='complete' or not __import__('re').fullmatch(r'guard-[a-f0-9]{32}',directory):return self.reply(404,{})
            target=(folder/directory/match[2]).resolve()
            if target.parent.parent!=folder:return self.reply(404,{})
            try:
                report=read(folder/directory/'report.json');pinned=read(folder/'guard-inputs.json')
                if report['sources']!=pinned:raise ValueError('Report source mismatch')
                for item in pinned.values():
                    from run_paths import run_file
                    source=run_file(folder,item['path'])
                    if source.resolve().parent!=folder or not source.is_file() or sha(source.read_bytes())!=item['sha256']:raise ValueError('Changed source')
            except (OSError,ValueError,KeyError):return self.reply(409,{'error':'Stored analysis inputs changed or missing'})
            if match[2]=='observation-gaps.json':
                try:
                    from observation_display import build, validate
                    if not target.exists():build(folder/directory)
                    return self.reply(200,validate(folder/directory))
                except (OSError,ValueError,KeyError,TypeError):
                    return self.reply(409,{'status':'unavailable','reason':'Observation supplement could not be verified'})
            rel=str(target.relative_to(ROOT))
        if not rel:return self.reply(404,{})
        p=(ROOT/rel).resolve()
        if name.startswith('/web/node_modules/three/') and not p.is_relative_to(ROOT/'web/node_modules/three'):return self.reply(404,{})
        if not p.is_relative_to(ROOT) or not p.is_file():return self.reply(404,{})
        if p.suffix=='.mp4' and parse_qs(urlsplit(self.path).query).get('preview')==['1']:
            try:
                from browser_preview import browser_preview
                p=browser_preview(p)
            except (OSError,ValueError,KeyError,IndexError,subprocess.SubprocessError):
                return self.reply(503,{'error':'Browser preview unavailable; original download is preserved'})
        b=p.read_bytes()
        if name=='/':b=b.replace(b'<body>',('<body data-ui-version="'+ui_version()+'">').encode())
        size=len(b);code=200;content_range=None
        if p.suffix=='.mp4' and self.headers.get('Range'):
            match=__import__('re').fullmatch(r'bytes=(\d*)-(\d*)',self.headers['Range'])
            try:
                if not match or not size or not any(match.groups()):raise ValueError('Invalid range')
                first,last=match.groups()
                if first:
                    start=int(first);end=min(int(last),size-1) if last else size-1
                else:
                    suffix=int(last)
                    if suffix<=0:raise ValueError('Invalid suffix')
                    start=max(0,size-suffix);end=size-1
                if start>=size or end<start:raise ValueError('Unsatisfiable range')
            except ValueError:
                self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.send_header('Content-Length','0');self.end_headers();return
            code=206;content_range=f'bytes {start}-{end}/{size}';b=b[start:end+1]
        self.send_response(code)
        if p.suffix in {'.html','.mjs','.js','.css'}:self.send_header('Cache-Control','no-store')
        self.send_header('Content-Type',{'.md':'text/plain; charset=utf-8','.css':'text/css','.mjs':'text/javascript','.js':'text/javascript','.html':'text/html','.mp4':'video/mp4','.json':'application/json','.glb':'model/gltf-binary'}.get(p.suffix,'application/octet-stream'))
        if p.suffix=='.mp4':self.send_header('Accept-Ranges','bytes')
        if content_range:self.send_header('Content-Range',content_range)
        self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)

def recover_monitor(folder):
    """Restart safety: monitor/cancel the known job; never submit another job."""
    from comfy_sdk import Comfy
    from comfy_sdk.retry import NO_RETRY
    state=read(folder/'state.json')
    with Comfy(api_key=key(),timeout=30,retry=NO_RETRY) as client:
        while True:
            try:
                job=client.jobs.get(state['job_id'])
                if job.status in TERMINAL:
                    save(folder/'recovered-terminal.json',{'job_id':job.id,'status':job.status,'at':time.time(),'reservation':'Retained until output and cost reconciliation'})
                    return
                if time.time()>=state['submitted_at']+600 or (folder/'cancel-request.json').exists():job.cancel()
            except Exception as e:save(folder/'recovery-error.json',{'type':type(e).__name__,'at':time.time()})
            time.sleep(5)

def rebind_space_ledger():
    """Hosted Space only (MG_REBIND_LEDGER=1): the bundled ledger is pinned to the owner's local key, while the
    Space holds a separate key of the same account. Rebind to it explicitly; spent credits and the ceiling stay."""
    if os.environ.get('MG_REBIND_LEDGER')!='1' or not os.environ.get('COMFY_CLOUD_API_KEY'):return
    ledger=read(LEDGER);new=sha(key().encode())
    if ledger.get('credential_sha256')==new:return
    ledger.setdefault('rebinds',[]).append({'from':ledger.get('credential_sha256'),'to':new,'at':time.time(),'reason':'hosted Space key'})
    ledger['credential_sha256']=new;save(LEDGER,ledger)
    print('Ledger rebound to the Space key; cumulative credits kept',flush=True)

def sweep_space_deployments():
    """Hosted Space only (MG_SWEEP_ORPHANS=1): a restart loses the run folders, the cleanup watchdog and the
    storage-lease supervisor, so any live deployment of the pinned release is orphaned. Stop and delete it."""
    if os.environ.get('MG_SWEEP_ORPHANS')!='1' or not os.environ.get('COMFY_CLOUD_API_KEY'):return
    try:
        from comfy_cli.deploy_api import DeployClient
        from comfy_cli.builder_api import BuilderClient
        build=read(ROOT/'config/guarded-runtime.json')['build_id']
        # Every release of the build, not only the pinned one: a run on a replaced release can be orphaned too.
        releases={r['id'] for r in BuilderClient.from_credentials('https://platformapi.comfy.org/builder').list_releases(build)}
        client=DeployClient.from_credentials()
        for d in client.list_all_deployments():
            if d.get('deletedAt') or d.get('releaseId') not in releases:continue
            if d.get('status')!='stopped':
                try:client.stop_deployment(d['id'])
                except Exception as e:print('Orphan stop',type(e).__name__,flush=True)
                for _ in range(60):
                    if client.get_deployment(d['id']).get('status')=='stopped':break
                    time.sleep(5)
            client.delete_deployment(d['id'])
            print('Orphan deployment deleted',d['id'],d.get('status'),flush=True)
    except Exception:
        import traceback;traceback.print_exc()

if __name__=='__main__':
    rebind_space_ledger()
    threading.Thread(target=sweep_space_deployments,daemon=True).start()
    bind=(os.environ.get('MG_BIND_HOST','127.0.0.1'),int(os.environ.get('MG_PORT','8712')))
    server=ThreadingHTTPServer(bind,Handler)
    from lease_watchdog import monitor as monitor_lease
    threading.Thread(target=monitor_lease,daemon=True).start()
    from pixel_followup import recover_known
    for pixel_path in RUNS.glob('t3-*/pixel-state.json'):
        pixel_state=read(pixel_path)
        if pixel_state.get('job_id') and pixel_state.get('status') not in {'complete','held','error'}:
            threading.Thread(target=recover_known,args=(pixel_path.parent,),daemon=False).start()
    for p in RUNS.glob('t3-*/state.json'):
        state=read(p)
        if state.get('source_type')=='platform_guarded':
            from app_guarded import needs_recovery
            if needs_recovery(p.parent,state,read(LEDGER)):
                threading.Thread(target=recover_platform,args=(p.parent,),daemon=False).start()
            continue
        if state.get('job_id') and state.get('status') not in TERMINAL:
            threading.Thread(target=recover_monitor,args=(p.parent,),daemon=False).start()
    print(f'Motion Guard http://{bind[0]}:{bind[1]}',flush=True);server.serve_forever()
