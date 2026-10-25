import contextlib
import json
import pytest
import lease_watchdog as watchdog


@pytest.fixture
def setup(tmp_path, monkeypatch):
    (tmp_path/'data').mkdir()
    monkeypatch.setattr(watchdog, 'ROOT', tmp_path)
    monkeypatch.setattr(watchdog, 'key', lambda: 'test')
    monkeypatch.setattr(watchdog, 'account_digest', lambda _: 'account')
    monkeypatch.setattr(watchdog, 'accounting_lock', contextlib.nullcontext)
    monkeypatch.setattr(watchdog.time, 'time', lambda: 1000)
    lease = dict(id='a'*32, account_sha256='account', status='reserved', expires_at=1100)
    path = tmp_path/'data/platform-storage-lease.json'
    watchdog.save(path, lease)
    calls=[]
    monkeypatch.setattr(watchdog, 'launch', lambda item: calls.append(item.copy()))
    return tmp_path, path, lease, calls


@pytest.mark.parametrize('expiry', [900, 1100])
def test_stale_supervisor_restarts_without_changing_lease_or_expiry(setup, expiry):
    root,path,lease,calls=setup
    lease['expires_at']=expiry
    watchdog.save(path,lease)
    before=path.read_bytes()
    watchdog.tick()
    assert calls == [lease]
    assert path.read_bytes() == before
    assert not (root/'data/platform-budget-ledger.json').exists()


def test_fresh_heartbeat_and_deleted_lease_do_not_launch(setup):
    root,path,lease,calls=setup
    heartbeat=root/'data'/f"lease-{lease['id']}.heartbeat.json"
    watchdog.save(heartbeat, {'at':995})
    watchdog.tick()
    heartbeat.unlink()
    lease['status']='deleted';watchdog.save(path,lease)
    watchdog.tick()
    assert calls == []


def test_account_mismatch_is_fail_closed(setup):
    root,path,lease,calls=setup
    lease['account_sha256']='other';watchdog.save(path,lease)
    with pytest.raises(ValueError): watchdog.tick()
    assert calls == []


def test_replaced_lease_is_not_launched(setup, monkeypatch):
    root,path,lease,calls=setup
    @contextlib.contextmanager
    def replace():
        watchdog.save(path, {**lease,'id':'b'*32})
        yield
    monkeypatch.setattr(watchdog,'accounting_lock',replace)
    watchdog.tick()
    assert calls == []


def test_failed_restarts_have_persistent_limit_and_sanitized_errors(setup, monkeypatch):
    root,path,lease,calls=setup
    def fail(item):
        calls.append(item)
        raise RuntimeError('private credential and URL')
    monkeypatch.setattr(watchdog,'launch',fail)
    for _ in range(5): watchdog.tick()
    assert len(calls)==3
    record=(root/'data'/f"lease-{lease['id']}.restarts.json").read_text()
    assert 'private' not in record
    assert all(a['status']=='failed' for a in json.loads(record)['attempts'])


def test_overlapping_attempts_completing_in_reverse_preserve_limit(setup, monkeypatch):
    root,path,lease,calls=setup
    def overlap(item):
        calls.append(item)
        if len(calls)<3: watchdog.tick()
    monkeypatch.setattr(watchdog,'launch',overlap)
    watchdog.tick();watchdog.tick()
    record=watchdog.read(root/'data'/f"lease-{lease['id']}.restarts.json")
    assert len(calls)==3
    assert len({a['id'] for a in record['attempts']})==3
    assert all(a['status']=='heartbeat_verified' for a in record['attempts'])


def test_launch_requires_heartbeat_after_launch(setup, monkeypatch):
    import storage_lease
    root,path,lease,calls=setup
    monkeypatch.setattr(storage_lease,'ROOT',root)
    monkeypatch.setattr(storage_lease.subprocess,'Popen',lambda *a,**k: None)
    heartbeat=root/'data'/f"lease-{lease['id']}.heartbeat.json"
    watchdog.save(heartbeat,{'at':999})
    sleeps=[]
    def fresh(_):
        sleeps.append(True)
        watchdog.save(heartbeat,{'at':1000})
    monkeypatch.setattr(storage_lease.time,'sleep',fresh)
    storage_lease.launch(lease)
    assert len(sleeps)==1
