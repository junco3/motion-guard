import hashlib
import zipfile
import pytest
from motionguard_core import staged_models


def staged_hand(tmp_path, payload=b'onnx-bytes'):
    archive = tmp_path / 'models' / (staged_models.HAND[0] + '.zip')
    archive.parent.mkdir()
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('rtmw/end2end.onnx', payload)
        z.writestr('rtmw/pipeline.json', '{}')
    return archive, (staged_models.HAND[0], hashlib.sha256(archive.read_bytes()).hexdigest(), hashlib.sha256(payload).hexdigest())


def test_hand_model_unpacked_from_pinned_archive(tmp_path, monkeypatch):
    archive, entry = staged_hand(tmp_path)
    monkeypatch.setattr(staged_models, 'HAND', entry)
    path = staged_models.prepare_hand(archive.parent, tmp_path / 'cache')
    assert path and open(path, 'rb').read() == b'onnx-bytes'
    assert staged_models.prepare_hand(archive.parent, tmp_path / 'cache') == path


def test_release_without_hand_archive_means_not_measured(tmp_path):
    (tmp_path / 'models').mkdir()
    assert staged_models.prepare_hand(tmp_path / 'models', tmp_path / 'cache') is None


def test_hand_archive_hash_is_enforced(tmp_path, monkeypatch):
    archive, entry = staged_hand(tmp_path)
    monkeypatch.setattr(staged_models, 'HAND', (entry[0], '0' * 64, entry[2]))
    with pytest.raises(ValueError):
        staged_models.prepare_hand(archive.parent, tmp_path / 'cache')


def test_pinned_hashes_match_the_official_archive():
    # The release stages the same official RTMW archive the local run downloads.
    from motionguard_core.estimator import HAND_URL
    assert HAND_URL.rsplit('/', 1)[1] == staged_models.HAND[0] + '.zip'
