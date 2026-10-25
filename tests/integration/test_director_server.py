import sys,threading,json,http.client
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'server'))
import app

def test_reference_export_auth_binding_and_validation(server,monkeypatch):
    monkeypatch.setattr(app,'REFERENCE_EXPORT',None)
    headers={'Origin':f'http://127.0.0.1:{server}','X-MotionGuard-Token':app.TOKEN,'Content-Type':'application/json'}
    data={'meta':{'frames':9,'fps':24},'frames':[{'frame':i,'time_s':i/24} for i in range(9)]}
    assert call(server,'/api/reference-export',method='POST',body=json.dumps(data))[0]==403
    code,body=call(server,'/api/reference-export',method='POST',headers=headers,body=json.dumps(data))
    assert code==200
    first=json.loads(body)['export_id'];url=f'/api/reference-export?id={first}&token={app.TOKEN}'
    assert call(server,f'/api/reference-export?id={first}')[0]==403
    assert json.loads(call(server,url)[1])==data
    assert call(server,'/api/reference-export',method='POST',headers=headers,body='[]')[0]==400
    data['frames'][0]['frame']=1
    assert call(server,'/api/reference-export',method='POST',headers=headers,body=json.dumps(data))[0]==400
    data['frames'][0]['frame']=0
    assert call(server,'/api/reference-export',method='POST',headers=headers,body=json.dumps(data))[0]==200
    assert call(server,url)[0]==410

@pytest.mark.parametrize('header,code,expected',[
 ('bytes=2-4',206,b'234'),('bytes=7-',206,b'789'),('bytes=-3',206,b'789'),
 ('bytes=8-99',206,b'89'),('bytes=-99',206,b'0123456789'),
 ('bytes=10-',416,b''),('bytes=7-2',416,b''),('bytes=-0',416,b''),('bytes=0-1,4-5',416,b'')])
def test_video_range(server,tmp_path,monkeypatch,header,code,expected):
    monkeypatch.setattr(app,'ROOT',tmp_path)
    run='t3-'+'a'*32;p=tmp_path/'data/gen'/run/'comparison.mp4';p.parent.mkdir(parents=True);p.write_bytes(b'0123456789')
    status,body=call(server,'/results/'+run+'/comparison.mp4',headers={'Range':header})
    assert status==code and body==expected

def test_range_does_not_bypass_protected_results(server):
    run='t3-'+'a'*32
    for suffix in ['final.mp4','guard/overlay.mp4','final.mp4?preview=1','pixel-final.mp4?preview=1']:
        assert call(server,'/results/'+run+'/'+suffix,headers={'Range':'bytes=0-9'})[0]==403

def test_preview_keeps_original_download_and_range(server,tmp_path,monkeypatch):
    import browser_preview
    monkeypatch.setattr(app,'ROOT',tmp_path)
    run='t3-'+'a'*32;p=tmp_path/'data/gen'/run/'generated.mp4'
    p.parent.mkdir(parents=True);p.write_bytes(b'original')
    preview=p.parent/'display.mp4';preview.write_bytes(b'compatible')
    monkeypatch.setattr(browser_preview,'browser_preview',lambda source:preview)
    assert call(server,'/results/'+run+'/generated.mp4')[1]==b'original'
    assert call(server,'/results/'+run+'/generated.mp4?preview=1',headers={'Range':'bytes=0-2'})==(206,b'com')

@pytest.fixture
def server():
    s=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
    t=threading.Thread(target=s.serve_forever);t.start()
    yield s.server_port
    s.shutdown();t.join();s.server_close()

def call(port,path,method='GET',headers=None,body=None):
    c=http.client.HTTPConnection('127.0.0.1',port)
    c.request(method,path,body=body,headers=headers or {});r=c.getresponse();v=(r.status,r.read());c.close();return v

def test_private_paths_and_traversal(server):
    assert call(server,'/')[0]==200
    for p in ['/config/budget.yaml','/web/node_modules/three/../../../../config/budget.yaml','/.env']:
        assert call(server,p)[0]==404

def test_cross_origin_and_token(server):
    assert call(server,'/api/generate','POST',{'Origin':'https://example.com'},'{}')[0]==403
    assert call(server,'/api/generate','POST',{'Origin':f'http://127.0.0.1:{server}'},'{}')[0]==403
    assert call(server,'/api/session',headers={'Host':'attacker.invalid'})[0]==403
    assert call(server,'/api/analyze','POST',{'Origin':'https://example.com'},'{}')[0]==403

def test_analyze_rejects_path_and_duplicate(server):
    headers={'Origin':f'http://127.0.0.1:{server}','X-MotionGuard-Token':app.TOKEN}
    assert call(server,'/api/analyze','POST',headers,json.dumps({'run_id':'../config'}))[0]==400
    app.LOCK.acquire()
    try:assert call(server,'/api/analyze','POST',headers,'{}')[0]==409
    finally:app.LOCK.release()

def test_analysis_failure_preserves_generation(tmp_path):
    app.save(tmp_path/'state.json',{'status':'succeeded','job_id':'existing'})
    (tmp_path/'generated.mp4').write_bytes(b'original')
    app.LOCK.acquire();app.analyze(tmp_path)
    state=app.read(tmp_path/'state.json')
    assert state['status']=='succeeded' and state['job_id']=='existing'
    assert state['guard_status']=='error' and (tmp_path/'generated.mp4').read_bytes()==b'original'
    assert not app.LOCK.locked()

def test_control_video_allowlist(tmp_path):
    app.save(tmp_path/'input.json',{'control_video':'depth.mp4'});(tmp_path/'depth.mp4').write_bytes(b'video')
    assert app.control_path(tmp_path)==tmp_path/'depth.mp4'
    app.save(tmp_path/'input.json',{'control_video':'../secret'})
    with pytest.raises(ValueError):app.control_path(tmp_path)

@pytest.mark.parametrize('operation',['read','save'])
def test_analysis_initial_storage_error_never_escapes_or_leaks_lock(tmp_path,monkeypatch,operation):
    app.save(tmp_path/'state.json',{'status':'succeeded','job_id':'existing'})
    for name in ['reference.mp4','generated.mp4','joints.json']:(tmp_path/name).write_bytes(b'original')
    def broken(*args,**kwargs):raise PermissionError('storage unavailable')
    monkeypatch.setattr(app,operation,broken)
    app.LOCK.acquire();app.analyze(tmp_path)
    assert not app.LOCK.locked()
    assert json.loads((tmp_path/'state.json').read_text())['status']=='succeeded'
    assert (tmp_path/'generated.mp4').read_bytes()==b'original'

@pytest.mark.parametrize('mutation',['deleted','changed'])
def test_analysis_pinned_gt_never_falls_back(tmp_path,mutation):
    app.save(tmp_path/'state.json',{'status':'succeeded'})
    for name in ['reference.mp4','generated.mp4','joints.json','joints.skin-v2.json']:(tmp_path/name).write_bytes(name.encode())
    inputs=app.analysis_inputs(tmp_path)
    assert Path(inputs['gt']['path']).name=='joints.skin-v2.json'
    gt=tmp_path/'joints.skin-v2.json'
    if mutation=='deleted':gt.unlink()
    else:gt.write_bytes(b'changed')
    app.LOCK.acquire();app.analyze(tmp_path)
    state=app.read(tmp_path/'state.json')
    assert state['status']=='succeeded' and state['guard_verdict']=='ERROR'
    assert app.read(tmp_path/'guard-inputs.json')==inputs
    assert not app.LOCK.locked()

def test_duplicate_job_lock(server,monkeypatch):
    monkeypatch.setattr(app,"generation_policy",lambda:{"generation_allowed":True,"mode":"cloud_local_guard"})
    app.LOCK.acquire()
    try:
        assert call(server,'/api/generate','POST',{'Origin':f'http://127.0.0.1:{server}','X-MotionGuard-Token':app.TOKEN},'{}')[0]==409
    finally:app.LOCK.release()

def test_saved_report_rejects_changed_inputs_without_analysis(server,tmp_path,monkeypatch):
    monkeypatch.setattr(app,'ROOT',tmp_path);monkeypatch.setattr(app,'RUNS',tmp_path/'data/gen')
    run='t3-'+'a'*32;folder=app.RUNS/run;folder.mkdir(parents=True)
    directory='guard-'+'b'*32
    app.save(folder/'state.json',{'status':'succeeded','guard_status':'complete','guard_directory':directory})
    for name in ['reference.mp4','generated.mp4','joints.json']:(folder/name).write_bytes(name.encode())
    inputs={k:{'path':str(folder/v),'sha256':app.sha((folder/v).read_bytes())} for k,v in [('reference','reference.mp4'),('generated','generated.mp4'),('gt','joints.json')]}
    app.save(folder/'guard-inputs.json',inputs);app.save(folder/directory/'report.json',{'sources':inputs,'verdict':'UNCERTAIN'})
    url='/results/'+run+'/guard/report.json?token='+app.TOKEN
    assert call(server,url)[0]==200
    (folder/'joints.json').write_bytes(b'changed')
    assert call(server,url)[0]==409
    assert app.read(folder/'state.json')['status']=='succeeded'

def test_nonfinite_rejected_before_files(server,monkeypatch):
    monkeypatch.setattr(app,"generation_policy",lambda:{"generation_allowed":True,"mode":"cloud_local_guard"})
    before=set(app.RUNS.glob('t3-*'))
    assert call(server,'/api/generate','POST',{'Origin':f'http://127.0.0.1:{server}','X-MotionGuard-Token':app.TOKEN},'{"time":NaN}')[0]==400
    assert set(app.RUNS.glob('t3-*'))==before

def test_closed_budget_never_reads_key(tmp_path,monkeypatch):
    app.save(tmp_path/'state.json',{'status':'prepared'})
    original=app.read
    monkeypatch.setattr(app,'read',lambda p:{'allow_paid_execution':False} if p.name=='budget.yaml' else original(p))
    monkeypatch.setattr(app,'key',lambda:pytest.fail('Credential access before authorization'))
    app.LOCK.acquire();app.generate(tmp_path,"cloud_local_guard")
    assert original(tmp_path/'state.json')['status']=='preflight_failed'

def test_cancel_failure_still_polls_and_no_early_ui_success(monkeypatch):
    class Job:
        status='running';polls=0;cancel_calls=0
        def refresh(self):
            self.polls+=1
            if self.polls==2:self.status='succeeded'
        def cancel(self):self.cancel_calls+=1;raise RuntimeError('already ending')
    job=Job();events=[]
    monkeypatch.setattr(app.time,'sleep',lambda _:None)
    app.monitor_job(job,0,lambda **kw:events.append(kw))
    assert job.polls==2 and job.cancel_calls==1
    assert all('status' not in e for e in events)
    assert events[-1]['cloud_status']=='succeeded'

def test_response_disconnect_keeps_worker_lock(server,tmp_path,monkeypatch):
    monkeypatch.setattr(app,"generation_policy",lambda:{"generation_allowed":True,"mode":"cloud_local_guard"})
    entered=threading.Event();release=threading.Event();finished=threading.Event()
    monkeypatch.setattr(app,'RUNS',tmp_path)
    monkeypatch.setattr(app,'prepare',lambda *a:None)
    def worker(*a):
        entered.set();release.wait(5);app.LOCK.release();finished.set()
    monkeypatch.setattr(app,'generate',worker)
    original=app.Handler.reply
    def reply(self,code,value):
        if code==202:raise BrokenPipeError('client left')
        original(self,code,value)
    monkeypatch.setattr(app.Handler,'reply',reply)
    try:
        with pytest.raises(http.client.RemoteDisconnected):call(server,'/api/generate','POST',{'Origin':f'http://127.0.0.1:{server}','X-MotionGuard-Token':app.TOKEN},'{}')
        assert entered.wait(2) and app.LOCK.locked()
        state=app.read(next(tmp_path.glob('t3-*/state.json')))
        assert state['status']=='preparing'
    finally:release.set();assert finished.wait(3)

@pytest.mark.parametrize('missing',[False,True])
def test_unprovisioned_or_missing_config_returns_closed_policy(server,tmp_path,monkeypatch,missing):
    monkeypatch.setattr(app,'ROOT',tmp_path)
    monkeypatch.setattr(app,'LEDGER',tmp_path/'config/t1-spend-ledger.json')
    app.save(app.LEDGER,{'conservative_prior_credits':0,'unresolved_jobs':[]})
    if not missing:
        app.save(tmp_path/'config/application-mode.json',{'mode':'cloud_local_guard'})
        app.save(tmp_path/'config/budget.yaml',{'allow_paid_execution':False})
    monkeypatch.setattr(app,'key',lambda:pytest.fail('Must not access credentials'))
    status,body=call(server,'/api/session')
    assert status==200 and json.loads(body)['generation_allowed'] is False
    assert call(server,'/api/generate','POST',{'Origin':f'http://127.0.0.1:{server}','X-MotionGuard-Token':app.TOKEN},'{}')[0]==409

@pytest.mark.parametrize('bad_ledger',['missing','invalid','missing_field'])
def test_invalid_ledger_session_returns_unavailable(server,tmp_path,monkeypatch,bad_ledger):
    monkeypatch.setattr(app,'ROOT',tmp_path)
    monkeypatch.setattr(app,'LEDGER',tmp_path/'config/t1-spend-ledger.json')
    app.save(tmp_path/'config/application-mode.json',{'mode':'cloud_local_guard'})
    if bad_ledger=='invalid':app.LEDGER.write_text('broken')
    if bad_ledger=='missing_field':app.save(app.LEDGER,{})
    status,body=call(server,'/api/session')
    state=json.loads(body)
    assert status==200 and state['generation_allowed'] is False and state['prior'] is None

@pytest.mark.parametrize('ceiling,allowed',[(1000,False),(2000,True)])
def test_cumulative_authorized_ceiling(server,tmp_path,monkeypatch,ceiling,allowed):
    monkeypatch.setattr(app,'ROOT',tmp_path);monkeypatch.setattr(app,'LEDGER',tmp_path/'config/t1-spend-ledger.json')
    app.save(app.LEDGER,{'conservative_prior_credits':863.067958,'unresolved_jobs':[]})
    app.save(tmp_path/'config/application-mode.json',{'mode':'cloud_local_guard'})
    app.save(tmp_path/'config/budget.yaml',{'allow_paid_execution':True,'max_total_credits':ceiling})
    policy=app.generation_policy()
    assert policy['generation_allowed'] is allowed and policy['ceiling']==ceiling
    assert policy['prior']==863.067958

@pytest.mark.parametrize('ceiling',[float('nan'),float('inf'),-1,0,True,None])
def test_invalid_authorized_ceiling(ceiling):
    with pytest.raises(ValueError):app.authorized_ceiling({'max_total_credits':ceiling})

def test_explicit_observed_gt_selected_and_bound(tmp_path):
    app.save(tmp_path/'state.json',{'status':'succeeded'})
    app.save(tmp_path/'input.json',{'gt_file':'joints.observed.json'})
    for name in ['reference.mp4','generated.mp4','joints.json','joints.skin-v2.json','joints.observed.json']:(tmp_path/name).write_bytes(name.encode())
    result=app.analysis_inputs(tmp_path)
    assert result['gt']['path']==str((tmp_path/'joints.observed.json').resolve())
    assert result['gt']['sha256']==app.sha(b'joints.observed.json')


@pytest.mark.parametrize('mode,enabled,prior,expected',[
 ('cloud_local_guard',False,1626.267958,202),
 ('platform_guarded',True,1626.267958,202),
 ('platform_guarded',False,1626.267958,409),
 ('platform_guarded',True,1900,409),
 ('unknown',True,0,400),
])
def test_explicit_mode_pinned_or_rejected(server,tmp_path,monkeypatch,mode,enabled,prior,expected):
    import platform_preflight
    monkeypatch.setattr(platform_preflight,'preview',lambda *a:{'ready':True,'required_reservation':207})
    monkeypatch.setattr(app,'ROOT',tmp_path)
    monkeypatch.setattr(app,'RUNS',tmp_path/'runs');app.RUNS.mkdir()
    monkeypatch.setattr(app,'LEDGER',tmp_path/'config/ledger.json')
    app.save(app.LEDGER,{'conservative_prior_credits':prior,'unresolved_jobs':[]})
    app.save(tmp_path/'config/application-mode.json',{'mode':'cloud_local_guard'})
    app.save(tmp_path/'config/guarded-runtime.json',{'enabled':enabled})
    app.save(tmp_path/'config/budget.yaml',{'allow_paid_execution':True,'max_total_credits':2000})
    monkeypatch.setattr(app,'prepare',lambda *args:None)
    observed=[];finished=threading.Event()
    def worker(folder,selected):
        observed.append((selected,app.read(folder/'state.json')['execution_mode']))
        app.LOCK.release();finished.set()
    monkeypatch.setattr(app,'generate',worker)
    code,body=call(server,'/api/generate','POST',{'Origin':f'http://127.0.0.1:{server}','X-MotionGuard-Token':app.TOKEN},json.dumps({'execution_mode':mode}))
    assert code==expected
    if expected==202:
        assert finished.wait(2) and observed==[(mode,mode)]
    else:
        assert not observed and not list(app.RUNS.iterdir()) and not app.LOCK.locked()
    policy=json.loads(call(server,'/api/session')[1])
    assert policy['modes']['platform_guarded']['required_reservation']==(207 if enabled else 202)
    assert policy['modes']['cloud_local_guard']['required_reservation']==179.6

def test_recovery_finds_finished_request_and_active_analysis(server,tmp_path,monkeypatch):
    monkeypatch.setattr(app,'RUNS',tmp_path)
    monkeypatch.setattr(app,'job_view',lambda folder:app.read(folder/'state.json'))
    run='t3-'+'b'*32
    request_id='12345678-1234-1234-1234-123456789abc'
    folder=tmp_path/run
    app.save(folder/'state.json',{'status':'succeeded','guard_status':'complete'})
    app.save(folder/'request.json',{'request_id':request_id})
    assert json.loads(call(server,'/api/active-runs')[1])==[]
    rows=json.loads(call(server,'/api/requests/'+request_id)[1])
    assert len(rows)==1 and rows[0]['run_id']==run
    for state in [{'status':'running'},{'status':'unresolved'},{'status':'succeeded','guard_status':'analyzing'},{'status':'succeeded','pixel_followup':{'status':'submitting'}}]:
        app.save(folder/'state.json',state)
        assert json.loads(call(server,'/api/active-runs')[1])[0]['run_id']==run
    assert call(server,'/api/requests/not-valid')[0]==404

def test_cancel_auth_idempotence_and_terminal(server,tmp_path,monkeypatch):
    monkeypatch.setattr(app,'RUNS',tmp_path)
    monkeypatch.setattr(app,'job_view',lambda folder:app.read(folder/'state.json'))
    run='t3-'+'c'*32;folder=tmp_path/run
    app.save(folder/'state.json',{'status':'running'})
    payload=json.dumps({'run_id':run})
    headers={'Origin':f'http://127.0.0.1:{server}','X-MotionGuard-Token':app.TOKEN}
    assert call(server,'/api/cancel','POST',{},payload)[0]==403
    for _ in range(2):
        code,body=call(server,'/api/cancel','POST',headers,payload)
        assert code==202 and json.loads(body)['terminal_confirmed'] is False
    assert app.read(folder/'state.json')['status']=='running'
    assert (folder/'cancel-request.json').is_file()
    app.save(folder/'state.json',{'status':'succeeded','guard_status':'analyzing'})
    assert call(server,'/api/cancel','POST',headers,payload)[0]==409
    app.save(folder/'state.json',{'status':'succeeded','pixel_followup':{'status':'running'}})
    assert call(server,'/api/cancel','POST',headers,payload)[0]==202
    assert (folder/'pixel-cancel-request.json').is_file()

def test_cancel_response_loss_keeps_monitoring(monkeypatch):
    monkeypatch.setattr(app.time,'sleep',lambda _:None)
    class Job:
        status='running'
        refreshes=0
        cancels=0
        def refresh(self):
            self.refreshes+=1
            if self.refreshes==3:self.status='canceled'
        def cancel(self):
            self.cancels+=1
            raise OSError('response lost')
    job=Job();updates=[]
    app.monitor_job(job,float('inf'),lambda **x:updates.append(x),lambda:True)
    assert job.status=='canceled' and job.cancels==2 and job.refreshes==3
    assert any('last_cancel_error' in x for x in updates)

def test_restart_recovery_honors_cancel_marker(tmp_path,monkeypatch):
    import comfy_sdk
    folder=tmp_path/'run'
    app.save(folder/'state.json',{'job_id':'owned','submitted_at':app.time.time()})
    app.save(folder/'cancel-request.json',{'requested':True})
    class Job:
        id='owned';status='running';cancels=0
        def cancel(self):self.cancels+=1;self.status='canceled'
    job=Job()
    class Client:
        def __init__(self,**kwargs):self.jobs=self
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,job_id):assert job_id=='owned';return job
    monkeypatch.setattr(comfy_sdk,'Comfy',Client)
    monkeypatch.setattr(app,'key',lambda:'test')
    monkeypatch.setattr(app.time,'sleep',lambda _:None)
    app.recover_monitor(folder)
    assert job.cancels==1
    assert app.read(folder/'recovered-terminal.json')['status']=='canceled'
    assert app.read(folder/'state.json')['job_id']=='owned'
