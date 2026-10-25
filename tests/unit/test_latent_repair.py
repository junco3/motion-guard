import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'core'))
from motionguard_core.latent_repair import find, repair  # noqa: E402


def smooth(seed=0, shape=(8, 20, 4, 6)):
    rng = np.random.default_rng(seed)
    return np.cumsum(rng.normal(0, 0.05, shape), axis=1).astype(np.float32)


def test_one_frame_spike_is_replaced_by_neighbour_mean():
    x = smooth(); x[:, 9, 0, 1] += 5.0
    y, records = repair(x)
    assert [(r['latent_frame'], r['cell'], r['pixel_frames']) for r in records] == [(9, [0, 1], [65, 72])]
    assert np.allclose(y[:, 9, 0, 1], (x[:, 8, 0, 1] + x[:, 10, 0, 1]) / 2)
    assert np.array_equal(np.delete(y, 9, axis=1), np.delete(x, 9, axis=1))


def test_steady_motion_and_a_held_change_are_kept():
    x = smooth(1)
    x[:, :, 2, 3] += np.linspace(0, 6, x.shape[1])[None]  # moving cell
    x[:, 12:, 1, 1] += 4.0                                  # appears and stays
    assert find(x) == []
    assert np.array_equal(repair(x)[0], x)


def test_stored_space_latent_flags_only_the_two_objects():
    path = Path(__file__).resolve().parents[2] / 'data/gen/t3-430f5e3a35294c7cb2e0d6048f4b7e41/sampled.latent'
    if not path.exists():
        return
    from safetensors.numpy import load_file
    x = load_file(str(path))['latent_tensor'][0]
    assert [(t, h, w) for t, h, w, _ in find(x)] == [(69, 0, 1), (77, 0, 17)]
