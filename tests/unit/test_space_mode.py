import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'server'))
import app
import portable_lock


def handler(headers, port=8712):
    h = types.SimpleNamespace(headers=headers, server=types.SimpleNamespace(server_port=port))
    for name in ('host_ok', 'origin_ok', 'access_ok'):
        setattr(h, name, types.MethodType(getattr(app.Handler, name), h))
    return h


def test_local_defaults_accept_only_loopback(monkeypatch):
    monkeypatch.setattr(app, 'PUBLIC_HOST', '')
    monkeypatch.setattr(app, 'ACCESS_CODE', '')
    assert handler({'Host': '127.0.0.1:8712', 'Origin': 'http://127.0.0.1:8712'}).host_ok()
    assert not handler({'Host': 'space.hf.space'}).host_ok()
    assert not handler({'Origin': 'https://space.hf.space'}).origin_ok()
    assert handler({}).access_ok()


def test_public_host_and_access_code(monkeypatch):
    monkeypatch.setattr(app, 'PUBLIC_HOST', 'space.hf.space')
    monkeypatch.setattr(app, 'ACCESS_CODE', 'judge-code')
    assert handler({'Host': 'space.hf.space'}).host_ok()
    assert handler({'Host': 'internal:7860', 'X-Forwarded-Host': 'space.hf.space'}).host_ok()
    assert not handler({'Host': 'other.hf.space'}).host_ok()
    assert handler({'Origin': 'https://space.hf.space'}).origin_ok()
    assert not handler({'Origin': 'http://space.hf.space'}).origin_ok()
    assert handler({'X-MotionGuard-Access': 'judge-code'}).access_ok()
    assert not handler({'X-MotionGuard-Access': 'wrong'}).access_ok()
    assert not handler({}).access_ok()


def test_key_prefers_secret_environment(monkeypatch):
    monkeypatch.setenv('COMFY_CLOUD_API_KEY', ' secret-value \n')
    assert app.key() == 'secret-value'


def test_portable_lock_round_trip(tmp_path):
    with (tmp_path / 'x.lock').open('a+b') as f:
        f.seek(0); f.write(b'0'); f.flush(); f.seek(0)
        portable_lock.lock(f)
        portable_lock.unlock(f)
        portable_lock.lock(f, blocking=False)
        portable_lock.unlock(f)


def test_saved_run_files_found_after_moving_the_run(tmp_path):
    from run_paths import run_file
    folder = tmp_path / ('t3-' + '0' * 32)
    folder.mkdir()
    (folder / 'joints.json').write_text('{}')
    assert run_file(folder, r'C:\Users\someone\data\gen\t3-x\joints.json') == folder / 'joints.json'
    assert run_file(folder, '/old/place/joints.json') == folder / 'joints.json'
    assert run_file(folder, str(folder / 'joints.json')) == folder / 'joints.json'


def test_guarded_limits_grow_with_timeline():
    from platform_preflight import guarded_limits, H100_GUARDED_PROFILES
    assert guarded_limits(97) == (600, 280)
    assert guarded_limits(241) == (900, 420)
    assert guarded_limits(721) == (1800, 840)
    assert guarded_limits(961) == (2400, 1120)
    assert all(r * 3600 / s > 1314.53 for s, r in H100_GUARDED_PROFILES)
    import pytest
    with pytest.raises(ValueError):
        guarded_limits(969)
