"""One private deployment, one workflow, a separate 600s cleanup watchdog.

Run only after release readiness and the concrete execution review. The watchdog
is local supervision, not a provider-enforced spending limit.
"""
import json, os, subprocess, sys, threading, time, uuid, re, stat, hashlib, math
from pathlib import Path
from app import ROOT, LEDGER, key, read, save, api, cumulative_prior, authorized_ceiling
from comfy_cli.deploy_api import DeployClient
from comfy_cli.builder_api import BuilderClient
from datetime import datetime
from deployment_reuse import select as select_reuse, remember, confirm_stopped, identify_lost_create
import storage_lease

def capture_deployment_logs(client, did, folder):
    """Diagnostic retrieval must not replace the primary execution failure."""
    try:
        save(folder/'deployment-logs.json', client.get_deployment_logs(did))
    except Exception as error:
        save(folder/'deployment-logs-error.json', {
            'type': type(error).__name__, 'message': str(error)[:1000]})

def storage_price_within_ceiling(value, ceiling):
    return type(value) in (int,float) and math.isfinite(value) and 0<value<=ceiling

def deletion_confirmed(snapshot):
    if not snapshot.get('deletedAt') or snapshot.get('status') not in ('stopped','deleted'):return False
    serving=snapshot.get('serving') or {}
    workers=serving.get('workers')
    return isinstance(workers,dict) and bool(workers) and all(type(v) is int and v==0 for v in workers.values())

def controlplane_evidence_valid(snapshot, events, rows):
    if not snapshot.get('deletedAt') or snapshot.get('status')!='stopped' or snapshot.get('releases')!=[]:return False
    did=snapshot['id']
    stopped=[e for e in events.get('events',[]) if e.get('status')=='stopped' and e.get('releaseId')==snapshot.get('releaseId')]
    matched=events.get('deploymentId')==did and bool(stopped)
    inactive=not any(x.get('id')==did and not x.get('deletedAt') for x in rows)
    if not matched or not inactive:return False
    serving=snapshot.get('serving') or {};workers=serving.get('workers')
    if isinstance(workers,dict) and any(type(v) is int and v>0 for v in workers.values()):
        try:
            def timestamp(value):
                result=datetime.fromisoformat(value.replace('Z','+00:00'))
                if result.tzinfo is None:raise ValueError('Missing timezone')
                return result
            sampled=timestamp(serving['sampledAt']);deleted=timestamp(snapshot['deletedAt'])
            if not any(sampled < timestamp(e['at']) <= deleted for e in stopped):return False
        except (ValueError,KeyError,TypeError,AttributeError):return False
    return True

def controlplane_deletion_confirmed(client,snapshot,folder):
    """Actual API fallback; stale pre-deletion samples are not current counts."""
    if not snapshot.get('deletedAt') or snapshot.get('status')!='stopped' or snapshot.get('releases')!=[]:return False
    did=snapshot['id'];events=client.get_deployment_events(did);rows=client.list_all_deployments()
    if not controlplane_evidence_valid(snapshot,events,rows):return False
    save(folder/'control-plane-deletion.json',{'snapshot':snapshot,'events':events,'deployments':rows,'direct_worker_count_measured':False})
    return True

def recover(folder):
    """Cleanup-only recovery: no create_deployment or workflow submission."""
    attempt=read(folder/'attempt.json');before={x['id'] for x in read(folder/'deployments-before.json')}
    os.environ['COMFY_CLOUD_API_KEY']=key();client=DeployClient.from_credentials()
    known=attempt.get('deployment_id')
    for name in ('deployment-created.json','recovered-deployment.json','deployment-latest.json'):
        if (folder/name).exists():
            record=read(folder/name)
            if record.get('releaseId')==attempt['release_id'] and record.get('id') not in before:
                known=record['id'];break
    while True:
        try:
            if known:did=known
            else:
                if attempt.get('retain_models'):
                    did=identify_lost_create(client.list_all_deployments(),attempt)
                    if not did:
                        save(folder/'cleanup-unresolved.json',{'reason':'Creation identity unavailable; no unowned deployment stopped'})
                        return False
                    known=did;save(folder/'recovered-deployment.json',client.get_deployment(did))
                    attempt['deployment_id']=did;save(folder/'attempt.json',attempt)
                    continue
                matches=[x for x in client.list_all_deployments() if x.get('releaseId')==attempt['release_id'] and x['id'] not in before]
                if len(matches)!=1:raise RuntimeError('Own deployment identity unresolved')
                did=matches[0]['id'];known=did;save(folder/'recovered-deployment.json',matches[0])
            try:client.stop_deployment(did)
            except Exception:pass
            if not attempt.get('retain_models'):
                try:client.delete_deployment(did)
                except Exception:pass
            snapshot=client.get_deployment(did);save(folder/'deployment-final.json',snapshot)
            if (confirm_stopped(client,snapshot,folder,attempt,save) if attempt.get('retain_models') else
                    deletion_confirmed(snapshot) or controlplane_deletion_confirmed(client,snapshot,folder)):return
        except Exception as e:save(folder/'recovery-error.json',{'type':type(e).__name__,'at':time.time()})
        time.sleep(10)

def reparse_point(p):
    # Windows reports junctions/symlinks as reparse points; Linux (the hosted Space) has only symlinks.
    st=p.lstat()
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st,'st_file_attributes',0) & getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0))

def prepared_directory(folder):
    root=(ROOT/'data/gen').resolve();original=Path(folder)
    if reparse_point(original):
        raise ValueError('Reparse run directory')
    folder=original.resolve()
    if folder.parent!=root or not re.fullmatch(r't3-[a-f0-9]{32}',folder.name):
        raise ValueError('Prepared run outside allowed root')
    return folder


def prepared_inputs(folder):
    folder=prepared_directory(folder)
    plan=read(folder/'execution-plan.json');workflow=read(folder/'workflow.api.json')
    gt_name=plan.get('gt_file','joints.json')
    if gt_name not in ('joints.json','joints.skin-v2.json','joints.observed.json'):
        raise ValueError('Invalid prepared reference GT')
    layout=plan.get('generator_mode')=='layout'
    expected_files={'character.png','reference.mp4',gt_name,'workflow.api.json'}
    if not layout: expected_files.add('pose.mp4')
    if set(plan['input_hashes'])!=expected_files:
        raise ValueError('Missing or unexpected prepared input pins')
    for name,digest in plan['input_hashes'].items():
        p=folder/name
        if p.resolve().parent!=folder or reparse_point(p):
            raise ValueError('Prepared input outside run')
        if hashlib.sha256(p.read_bytes()).hexdigest()!=digest:raise ValueError('Prepared input changed')
    run=plan['execution_id'];uuid.UUID(run)
    if layout:
        from app_layout import validate_inputs
        return validate_inputs(folder,plan,workflow,gt_name)
    assert workflow['mg_bind']['inputs']=={'latent':['5549',2],'run_id':run}
    identity=['mg_audit_init',0] if plan.get('stage_audit') else ['mg_bind',1]
    assert workflow['mg_inspect']['inputs']['run_id']==identity
    assert workflow['mg_inspect']['inputs']['images']==['diag_decode',0]
    assert workflow['diag_decode']['inputs']['samples']==workflow['mg_gate']['inputs']['latent']==['mg_bind',0]
    assert workflow['mg_gate']['inputs']['report']==['mg_inspect',0]
    assert workflow['mg_gate']['inputs']['stage_id']==identity
    if plan.get('stage_audit'):
        from stage_audit_graph import validate,digest as graph_digest
        validate(workflow)
        assert workflow['mg_audit_init']['inputs']['run_id']==['mg_bind',1]
        assert graph_digest(workflow)==plan['stage_audit']['graph_sha256']
    assert workflow['5517/4975']['inputs']['samples']==['mg_gate',0]
    assert workflow['mg_inspect']['inputs']['gt_json']==(folder/gt_name).read_text(encoding='utf-8')
    for node,field,name in [('2004','image','character.png'),('5001','file','pose.mp4'),('mg_inspect','reference_video','reference.mp4')]:
        assert Path(workflow[node]['inputs'][field]).resolve()==folder/name
    from comfy_cli.command.deploy_workflow import scan_workflow_inputs
    assets=scan_workflow_inputs(workflow,asset_roots=(folder,)).assets
    if {a.local_path.resolve() for a in assets}!={folder/n for n in ('character.png','pose.mp4','reference.mp4')}:
        raise ValueError('Unexpected workflow assets')
    from timeline_contract import validate as validate_timeline_contract
    validate_timeline_contract(folder, plan, workflow, gt_name)
    return folder,workflow


def execution_limits(folder,budget):
    plan=read(folder/'execution-plan.json') if (folder/'execution-plan.json').exists() else {}
    seconds=plan.get('deadline_seconds',600);reservation=plan.get('max_credits_reservation',202)
    if type(seconds) is not int or type(reservation) is not int:
        raise ValueError('Invalid execution limits')
    gpu=plan.get('gpu_class','rtx-pro-6000-server')
    if gpu=='h100-sxm':
        allowed = (plan.get('purpose') == 'model_reuse_probe' and (seconds,reservation) in ((600,280),(450,210)))
        from platform_preflight import H100_GUARDED_PROFILES
        allowed |= (plan.get('purpose') == 'User-requested guarded generation' and (seconds,reservation) in H100_GUARDED_PROFILES)
        if not allowed:
            raise ValueError('H100 is restricted to bounded approved profiles')
        return seconds,reservation
    if gpu!='rtx-pro-6000-server':raise ValueError('Unsupported GPU policy')
    if (seconds,reservation)==(600,202):return seconds,reservation
    if (seconds,reservation)!=(1200,404):raise ValueError('Unsupported execution limits')
    approval=read(ROOT/'config/guarded-one-run-approval.json')
    if (approval.get('run_id')!=folder.name or approval.get('execution_id')!=plan.get('execution_id')
        or approval.get('plan_sha256')!=hashlib.sha256((folder/'execution-plan.json').read_bytes()).hexdigest()
        or approval.get('deadline_seconds')!=seconds or approval.get('reservation')!=reservation
        or approval.get('cumulative_ceiling')!=authorized_ceiling(budget)
        or not approval.get('user_quote') or approval.get('scope')!='single_guarded_execution'):
        raise ValueError('One-run authorization mismatch')
    return seconds,reservation

def configured_build_id():
    value = read(ROOT/'config/guarded-runtime.json').get('build_id')
    if not isinstance(value, str):
        raise ValueError('Configure your account-owned Platform build_id before execution')
    uuid.UUID(value)
    return value


def main(release_id,prepared_folder=None,lifecycle_probe=False):
    uuid.UUID(release_id)
    expected_build_id = configured_build_id()
    if not isinstance(prepared_folder,(str,Path)) or not str(prepared_folder).strip():
        raise ValueError('Explicit prepared input directory required; no owner-run fallback')
    if lifecycle_probe:
        folder=prepared_directory(prepared_folder);prepared_workflow={}
        if read(folder/'execution-plan.json').get('purpose')!='model_reuse_probe':raise ValueError('Missing lifecycle probe purpose')
    else:
        folder,prepared_workflow=prepared_inputs(prepared_folder)
    if prepared_workflow is not None and read(folder/'execution-plan.json').get('approved_release_id')!=release_id:
        raise ValueError('Prepared release mismatch')
    if prepared_workflow is not None and read(folder/'execution-plan.json').get('generator_mode')=='layout':
        config=read(ROOT/'config/layout-runtime.json')
        if (config.get('enabled') is not True or config.get('release_id')!=release_id
                or config.get('build_id')!=expected_build_id or config.get('claimed_run')!=folder.name
                or config.get('claimed_execution_id')!=read(folder/'execution-plan.json')['execution_id']
                or config.get('claimed_plan_sha256')!=hashlib.sha256((folder/'execution-plan.json').read_bytes()).hexdigest()):
            raise ValueError('Layout single-run authorization mismatch')
    gpu=read(folder/'execution-plan.json').get('gpu_class','rtx-pro-6000-server') if prepared_folder else 'rtx-pro-6000-server'
    if gpu!='rtx-pro-6000-server' and not lifecycle_probe and read(folder/'execution-plan.json').get('purpose') != 'User-requested guarded generation':
        raise ValueError('Alternative GPU requires lifecycle probe execution')
    folder.mkdir(exist_ok=True)
    if (folder/'attempt.json').exists(): raise RuntimeError('Existing attempt; inspect and recover, never resubmit')
    budget=read(ROOT/'config/budget.yaml');ledger=read(LEDGER)
    seconds,reservation=execution_limits(folder,budget);ceiling=authorized_ceiling(budget)
    if not budget['allow_paid_execution'] or ledger['unresolved_jobs'] or ledger['conservative_prior_credits']+reservation>ceiling:
        raise RuntimeError('Budget or unresolved job gate')
    if budget['max_deployment_active_minutes']*60<seconds or budget['max_storage_charge']<2:
        raise RuntimeError('Deployment reservation not configured')
    env=os.environ.copy();env.update(COMFY_CLOUD_API_KEY=key(),PYTHONUTF8='1',PYTHONIOENCODING='utf-8',DO_NOT_TRACK='1')
    billing=api('/api/billing/usage/timeseries?months=1',env['COMFY_CLOUD_API_KEY']);save(folder/'billing-before.json',billing)
    balance=billing['summary']['balance']['cloud_credit_balance_cents']
    prior=cumulative_prior(ledger,balance,env['COMFY_CLOUD_API_KEY'])
    if prior+reservation>ceiling:raise RuntimeError('Latest account usage exceeds reservation budget')
    for reservation_path in (ROOT/'data/gen').glob('*/reservation.json'):
        if not read(reservation_path).get('released',False):raise RuntimeError('Existing unreleased generation reservation')
    os.environ['COMFY_CLOUD_API_KEY']=env['COMFY_CLOUD_API_KEY']
    client=DeployClient.from_credentials()
    builder=BuilderClient.from_credentials('https://platformapi.comfy.org/builder')
    release=builder.get_release(release_id);save(folder/'release.json',release)
    if release.get('id')!=release_id or release.get('buildId')!=expected_build_id or release.get('deployable') is not True:
        raise RuntimeError('Wrong or non-deployable release')
    if not any(a.get('os')=='linux' and a.get('gpu')=='nvidia' and a.get('status')=='ready' for a in release.get('artifacts',[])):
        raise RuntimeError('Linux NVIDIA artifact not ready')
    if prepared_folder is not None:storage_lease.ensure_existing(env['COMFY_CLOUD_API_KEY'])
    existing=client.list_all_deployments();save(folder/'deployments-before.json',existing)
    compute={'gpuClass':gpu,'region':'anywhere','min':0,'max':1}
    # Hosted Space (MG_NO_RETAIN=1): delete every deployment after its run. A retained one blocks a longer
    # next run until its lease expires and is orphaned by a Space restart.
    retain_models=prepared_folder is not None and os.environ.get('MG_NO_RETAIN')!='1'
    reuse=select_reuse(ROOT,existing,release_id,expected_build_id,compute,env['COMFY_CLOUD_API_KEY'],read) if retain_models else None
    if not retain_models and any(not x.get('deletedAt') for x in existing):raise RuntimeError('Existing deployment must be resolved')
    catalog=client.get_compute_catalog();save(folder/'compute-catalog.json',catalog)
    rates=[g['creditsPerHour'] for r in catalog['regions'] if r['region']=='anywhere' for g in r['gpus'] if g['gpuClass']==compute['gpuClass']]
    if len(rates)!=1 or rates[0]>{'rtx-pro-6000-server':957.94,'h100-sxm':1314.53}[gpu]:
        raise RuntimeError('Compute quote changed; review required')
    estimate=client.get_deploy_estimate(release_id,compute['gpuClass'],compute['region']);save(folder/'estimate.json',estimate)
    lease=None
    if retain_models:
        lease=storage_lease.reserve(folder,env['COMFY_CLOUD_API_KEY'],catalog,release_id,reservation,prior,seconds)
        try:
            storage_lease.launch(lease)
            save(folder/'storage-lease.json',lease)
            if lease['expires_at']-time.time()<seconds+storage_lease.CLEANUP_MARGIN:
                raise RuntimeError('Storage lease no longer has an execution window')
        except Exception:
            if lease['origin_run']==folder.name:storage_lease.cancel_uncreated(lease,folder)
            raise
    started=time.time();deadline=started+seconds
    attempt={'release_id':release_id,'compute':compute,'started_at':started,'deadline':deadline,'idempotency_key':str(uuid.uuid4()),'reserved_credits':reservation,'prior_credits':prior,
             'retain_models':retain_models,'deployment_id':reuse['deployment_id'] if reuse else None,'reused_deployment':bool(reuse)}
    if lease:attempt['storage_lease_id']=lease['id']
    with (folder/'attempt.json').open('x',encoding='utf-8') as f:
        json.dump(attempt,f,indent=2);f.flush();os.fsync(f.fileno())
    try:
        with storage_lease.accounting_lock():
            ledger=read(LEDGER)
            if ledger['unresolved_jobs']:raise RuntimeError('Another execution reserved concurrently')
            if max(prior,ledger['conservative_prior_credits'])+reservation>ceiling:
                raise RuntimeError('Latest locked ledger exceeds execution budget')
            ledger['unresolved_jobs'].append(folder.name);save(LEDGER,ledger)
    except Exception:
        # This boundary precedes every create/start call; never infer this from disk later.
        if lease and lease['origin_run']==folder.name:
            storage_lease.cancel_uncreated(lease,folder,before_submission=True)
        raise
    stop=threading.Event();cleanup_lock=threading.Lock();state={'deployment_id':attempt['deployment_id']};proc=None
    def locate():
        if state['deployment_id']:return state['deployment_id']
        if retain_models:
            did=identify_lost_create(client.list_all_deployments(),attempt)
            if did:
                state['deployment_id']=did;save(folder/'recovered-deployment.json',client.get_deployment(did))
                attempt['deployment_id']=did;save(folder/'attempt.json',attempt)
            return did
        matches=[x for x in client.list_all_deployments() if x.get('releaseId')==release_id and x.get('id') not in {b['id'] for b in existing}]
        if len(matches)==1:
            state['deployment_id']=matches[0]['id'];save(folder/'recovered-deployment.json',matches[0]);return state['deployment_id']
        return None
    def cleanup():
        with cleanup_lock:
            try:did=locate()
            except Exception as e:
                save(folder/'cleanup-locate-error.json',{'type':type(e).__name__});return False
            if not did:return False
            errors=[]
            try:save(folder/'stop-response.json',client.stop_deployment(did))
            except Exception as e:errors.append({'action':'stop','type':type(e).__name__})
            if not retain_models:
                try:client.delete_deployment(did)
                except Exception as e:errors.append({'action':'delete','type':type(e).__name__})
            save(folder/'cleanup-requests.json',{'deployment_id':did,'errors':errors,'at':time.time()})
            return True
    def watchdog():
        if not stop.wait(max(0,deadline-time.time())):
            while not stop.is_set():
                try:cleanup()
                except Exception as e:save(folder/'watchdog-error.json',{'type':type(e).__name__,'at':time.time()})
                stop.wait(10)
    watch=threading.Thread(target=watchdog,daemon=True);watch.start()
    try:
        if reuse:
            save(folder/'deployment-reuse.json',reuse)
            did=reuse['deployment_id']
            save(folder/'start-response.json',client.start_deployment(did))
        else:
            created=client.create_deployment(release_id,compute,idempotency_key=attempt['idempotency_key'])
            state['deployment_id']=created['id'];save(folder/'deployment-created.json',created)
            did=created['id']
            if retain_models:
                try:
                    from platform_preflight import storage_policy
                    _, policy = storage_policy(ROOT,release_id)
                    if policy.get('provisional'):
                        initial=client.get_deployment(did)
                        save(folder/'bootstrap-storage-snapshot.json',initial)
                        rows=[r for r in initial.get('releases',[]) if r.get('current') and r.get('releaseId')==release_id]
                        price=rows[0].get('storageMonthlyCents') if len(rows)==1 else None
                        if (initial.get('id')!=did or initial.get('releaseId')!=release_id
                                or not storage_price_within_ceiling(price,policy['storage_monthly_cents'])):
                            raise ValueError('Bootstrap storage price missing or exceeds allowance')
                        save(folder/'bootstrap-storage-verified.json',{'deployment_id':did,'release_id':release_id,
                             'monthly_cents':price,'reserved_credits':lease['reserved_credits'],
                             'snapshot_sha256':hashlib.sha256((folder/'bootstrap-storage-snapshot.json').read_bytes()).hexdigest()})
                except Exception:
                    retain_models=False;attempt['retain_models']=False
                    attempt['deployment_id']=did;save(folder/'attempt.json',attempt)
                    raise
            if retain_models:remember(ROOT,folder,client.get_deployment(did),attempt,expected_build_id,env['COMFY_CLOUD_API_KEY'],save)
        attempt['deployment_id']=did;save(folder/'attempt.json',attempt)
        if (folder/'cancel-request.json').exists():raise RuntimeError('User cancellation requested')
        while time.time()<deadline:
            if (folder/'cancel-request.json').exists():raise RuntimeError('User cancellation requested')
            snapshot=client.get_deployment(did);save(folder/'deployment-latest.json',snapshot)
            if snapshot['status']=='ready':
                actual_compute=snapshot.get('computeConfig') or {}
                if gpu=='h100-sxm' and any(actual_compute.get(k)!=v for k,v in compute.items()):
                    raise RuntimeError('Actual deployment compute differs from approved probe')
                if retain_models:
                    from platform_preflight import storage_policy
                    _,storage_quote=storage_policy(ROOT,release_id)
                    priced=[r for r in snapshot.get('releases',[]) if r.get('current') and r.get('releaseId')==release_id]
                    actual_storage=priced[0].get('storageMonthlyCents') if len(priced)==1 else None
                    if not storage_price_within_ceiling(actual_storage,storage_quote['storage_monthly_cents']):
                        retain_models=False;attempt['retain_models']=False;save(folder/'attempt.json',attempt)
                        raise RuntimeError('Actual storage quote changed; deleting deployment')
                break
            if snapshot['status'] in ('failed','stop_failed','unhealthy') or (snapshot['status']=='stopped' and not reuse):raise RuntimeError('Deployment did not become ready')
            time.sleep(3)
        else:raise TimeoutError(f'Deployment startup exceeded{seconds}s')
        if lifecycle_probe:
            save(folder/'first-ready.json',snapshot)
            if time.time()+150>=deadline:raise TimeoutError('No bounded restart verification window')
            restart_start=time.time()
            client.stop_deployment(did)
            while time.time()<deadline-120:
                stopped=client.get_deployment(did)
                if confirm_stopped(client,stopped,folder,{**attempt,'started_at':restart_start},save):break
                time.sleep(3)
            else:raise TimeoutError('Initial stop not confirmed in restart window')
            save(folder/'probe-stopped.json',stopped)
            save(folder/'restart-estimate.json',client.get_deploy_estimate(release_id,compute['gpuClass'],compute['region']))
            save(folder/'probe-start-response.json',client.start_deployment(did))
            observations=[]
            while time.time()<deadline-15:
                resumed=client.get_deployment(did);observations.append({'at':time.time(),'snapshot':resumed})
                save(folder/'restart-observations.json',observations)
                if resumed.get('status')=='ready':break
                if resumed.get('status') in ('failed','unhealthy','stop_failed'):raise RuntimeError('Restart failed')
                time.sleep(3)
            else:raise TimeoutError('Restart did not become ready before cleanup')
            save(folder/'restart-result.json',{'deployment_id':did,'same_deployment':True,'restart_seconds':time.time()-restart_start,'ready':resumed})
            capture_deployment_logs(client,did,folder)
            return
        if time.time()+15>=deadline:raise TimeoutError('No remaining generation window')
        if prepared_workflow is not None:
            source,workflow=prepared_inputs(folder)
        else:
            raise ValueError('Explicit prepared workflow required')
        args=[str(ROOT/'.venv/Scripts/python.exe') if (ROOT/'.venv/Scripts/python.exe').exists() else sys.executable,'-X','utf8','-u',str(ROOT/'server/platform_cli.py'),str(folder),'--json','deploy','run',str(ROOT/('workflows/T5' if prepared_workflow is not None else 'workflows/T3')),'--deployment',did,'--workflow',str(folder/'workflow.api.json'),'--asset-root',str(source),'--timeout',str(max(1,deadline-time.time()-10)),'--output-dir',str(folder/'outputs')]
        with (folder/'cli-stdout.txt').open('w',encoding='utf-8') as out,(folder/'cli-stderr.txt').open('w',encoding='utf-8') as err:
            if (folder/'cancel-request.json').exists():raise RuntimeError('User cancellation requested')
            proc=subprocess.Popen(args,env=env,stdout=out,stderr=err,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            while proc.poll() is None and time.time()<deadline:
                if (folder/'cancel-request.json').exists():raise RuntimeError('User cancellation requested')
                time.sleep(1)
            deadline_terminated = proc.poll() is None
            if deadline_terminated:
                proc.terminate();proc.wait(timeout=20)
                save(folder/'execution-error.json',{'type':'TimeoutError','message':'Execution deadline exceeded; CLI terminated; remote outcome unconfirmed'})
            save(folder/'cli-exit.json',{'returncode':proc.returncode,'deadline_terminated':deadline_terminated})
        if proc.returncode!=0:
            # Server log only: the run folder is not reachable on the hosted Space.
            for name in ('cli-stdout.txt','cli-stderr.txt'):
                print(folder.name,name,'tail:',(folder/name).read_text(encoding='utf-8',errors='replace')[-3000:],flush=True)
        capture_deployment_logs(client,did,folder)
    except Exception as e:
        save(folder/'execution-error.json',{'type':type(e).__name__,'message':str(e)[:1000]})
    finally:
        if proc and proc.poll() is None:proc.terminate()
        # Keep monitoring on cleanup failure. Never clear the reservation here.
        # A second stop in a lifecycle probe must not reuse the first stop event.
        if lifecycle_probe:
            attempt['stop_not_before']=time.time();save(folder/'attempt.json',attempt)
        cleanup()
        if retain_models and not state['deployment_id']:
            save(folder/'cleanup-unresolved.json',{'reason':'Creation identity unavailable; reservation retained; no unowned deployment stopped'})
            return
        for _ in range(60):
            try:did=locate()
            except Exception:did=None
            if did:
                try:
                    snapshot=client.get_deployment(did);save(folder/'deployment-final.json',snapshot)
                    if (confirm_stopped(client,snapshot,folder,attempt,save) if retain_models else deletion_confirmed(snapshot) or controlplane_deletion_confirmed(client,snapshot,folder)):
                        stop.set();break
                except Exception as e:save(folder/'cleanup-monitor-error.json',{'type':type(e).__name__})
            time.sleep(5)
        if not stop.is_set():
            # No new work is allowed; caller must continue inspecting this record.
            save(folder/'cleanup-unresolved.json',{'deployment_id':state['deployment_id'],'at':time.time()})
            while not stop.is_set():
                try:
                    cleanup();snapshot=client.get_deployment(state['deployment_id']);save(folder/'deployment-final.json',snapshot)
                    if (confirm_stopped(client,snapshot,folder,attempt,save) if retain_models else deletion_confirmed(snapshot) or controlplane_deletion_confirmed(client,snapshot,folder)):stop.set()
                except Exception:pass
                stop.wait(10)
        watch.join(timeout=5)
        save(folder/'finished.json',{'at':time.time(),'reservation_retained_for_reconciliation':True})

if __name__=='__main__':
    if sys.argv[1]=='--recover':recover(ROOT/'data/gen/t3-platform-once')
    elif sys.argv[1]=='--guarded':main(sys.argv[2],ROOT/'data/gen'/sys.argv[3])
    elif sys.argv[1]=='--reuse-probe':main(sys.argv[2],ROOT/'data/gen'/sys.argv[3],True)
    elif sys.argv[1]=='--recover-guarded':recover(prepared_directory(ROOT/'data/gen'/sys.argv[2]))
    else:main(sys.argv[1])
