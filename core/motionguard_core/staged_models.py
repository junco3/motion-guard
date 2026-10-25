"""Hash-pinned local archives; no network fallback on private deployments."""
import hashlib
import os
import tempfile
import zipfile
from pathlib import Path

REVISION = 'cd4d7095f5cfc9cfc4f46289bee91ea4a1e1d9fd'
MODELS = {
    'det': ('yolox_m_8xb8-300e_humanart-c2c7a14a',
            'a000224fd8ba283202bc62d4a5fcdfe353adb9f468777dbac1ea2ada2093adde',
            '3dea6513388889f0fff4b77bf7a26013600321b9eb9ceb0e9a400a82572f5f23'),
    'pose': ('rtmpose-m_simcc-body7_pt-body7_420e-256x192-e48f03d0_20230504',
             'f7fbb6c5c11a1bb70f3d445e4ddec5d144ea89ad5649c081ef976f9b24a0b741',
             '5c0a4bf67953e6d2ac43ce15e77dc9d5d354ae18430a47d2c5963a7bc5683e3c'),
}
# Whole-body RTMW, used only for its 42 hand points; optional, so a release without it reports fingers as not measured.
HAND = ('rtmw-dw-l-m_simcc-cocktail14_270e-256x192_20231122',
        'a6d08a575c9d8b8da7ce6c13e1c7341047fca35594a6d35de04b739eba51139c',
        '68db326c5c6f3273456f803eae0faf5440478369f2c3ee67258d2f36512e8d76')


def digest(p):
    with Path(p).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def resolve_directory(registered, override=None):
    """Use the actual Comfy registry, never assume models_dir owns remote mounts."""
    if override is not None and not override.strip():
        raise ValueError('MG_MODEL_DIR was specified but is empty')
    candidates = [override] if override is not None else registered
    for candidate in candidates:
        directory = Path(candidate)
        valid = True
        for name, archive_hash, _ in MODELS.values():
            archive = directory/(name+'.zip')
            if not archive.is_file() or digest(archive) != archive_hash:
                valid = False
                break
        if valid:
            return directory.resolve()
    raise ValueError('No registered directory contains both verified Motion Guard model archives')


def unpack(role, entry, directory, cache):
    name, archive_hash, model_hash = entry
    archive, dest = Path(directory) / (name + '.zip'), Path(cache) / (name + '.onnx')
    if digest(archive) != archive_hash:
        raise ValueError(f'Staged model archive hash mismatch: {role}')
    if dest.exists():
        if digest(dest) != model_hash:
            raise ValueError(f'Staged model cache hash mismatch: {role}')
        return str(dest)
    with zipfile.ZipFile(archive) as z:
        members = [i for i in z.infolist() if not i.is_dir() and i.filename.endswith('.onnx')]
        if len(members) != 1 or members[0].file_size > 200_000_000:
            raise ValueError(f'Unexpected ONNX archive contents: {role}')
        data = z.read(members[0])
    if hashlib.sha256(data).hexdigest() != model_hash:
        raise ValueError(f'ONNX content hash mismatch: {role}')
    # Concurrent writers can only publish the same verified bytes.
    fd, temporary = tempfile.mkstemp(dir=cache, prefix=name + '-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(temporary, dest)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return str(dest)


def prepare_hand(directory, cache):
    """Verified hand model path, or None when the release does not stage it."""
    if not (Path(directory) / (HAND[0] + '.zip')).is_file():
        return None
    Path(cache).mkdir(parents=True, exist_ok=True)
    return unpack('hand', HAND, directory, cache)


def prepare(directory, cache):
    directory, cache = Path(directory), Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    paths = {role: unpack(role, entry, directory, cache) for role, entry in MODELS.items()}
    print('MotionGuard verified model source:', str(directory), {role: entry[1] for role, entry in MODELS.items()}, flush=True)
    return paths
