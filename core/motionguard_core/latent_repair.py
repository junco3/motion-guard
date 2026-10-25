"""Single-latent-frame spikes in the Stage1 video latent.

2026-10-24: the objects that flashed at the frame edge of 30 s and 40 s Space runs lasted exactly one latent
frame (8 pixel frames). In the stored latent of local run t3-430f... the two object cells stood 16x and 18x
above their neighbours' own change, while no person cell in its 91 latent frames exceeded 4x. The pose guide
had nothing there, so the sampler made them. A cell that jumps away from both neighbours and back is
replaced by the neighbours' mean before the draft decode and Stage2.

RATIO was set from that one stored latent (largest person ratio < 4, objects 16-18); it is not calibrated."""
import numpy as np

METHOD = 'single-latent-frame-spike-v1'
RATIO = 4.0
FLOOR = 0.5


def find(x):
    """x: float array [C, T, H, W]. Returns [(t, h, w, ratio)] for cells to replace (1 <= t <= T-2)."""
    if x.ndim != 4 or x.shape[1] < 3:
        return []
    mid = (x[:, :-2] + x[:, 2:]) / 2
    spike = np.linalg.norm(x[:, 1:-1] - mid, axis=0)
    base = np.linalg.norm(x[:, 2:] - x[:, :-2], axis=0) / 2
    ratio = spike / (base + FLOOR)
    t, h, w = np.nonzero(ratio > RATIO)
    return [(int(a) + 1, int(b), int(c), float(ratio[a, b, c])) for a, b, c in zip(t, h, w)]


def repair(x):
    """Returns (repaired copy, records). Neighbours are read from the original, so a run of
    consecutive changed frames is not a spike and stays as it is."""
    hits = find(x)
    y = x.copy()
    for t, h, w, _ in hits:
        y[:, t, h, w] = (x[:, t - 1, h, w] + x[:, t + 1, h, w]) / 2
    records = [{'latent_frame': t, 'cell': [h, w], 'pixel_frames': [8 * (t - 1) + 1, 8 * t],
                'ratio': round(r, 2)} for t, h, w, r in hits]
    return y, records
