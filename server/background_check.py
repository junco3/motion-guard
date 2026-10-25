"""Background-object warning for a generated draft. Quality warning only: it never changes the motion verdict.

The motion gate compares body joints, so an object the generator draws into the empty background passes it
(2026-10-24 Space runs: 30 s and 40 s drafts each showed one ~0.3 s object at the frame edge). This finds
pixels that differ from the draft's own temporal median background, outside the person region taken from the
reference render and moved by the report's framing alignment. The difference cut (summed RGB > 90) is the one
already used to count upscale specks; it was not chosen from these runs."""
import cv2
import numpy as np

METHOD = 'background-transient-v1'
DIFF = 90          # summed |RGB| difference, same cut as the speck counter
MIN_AREA = 8       # pixels at half resolution (32 at 768x512)
MARGIN = 0.06      # person-region dilation, fraction of frame width
GAP = 2            # frames merged into one interval
TRANSIENT_S = 1.0  # longest appearance still reported as a transient object
FLAT_STD = 12.0    # grey-level spread of the median background above which the check does not run


def _frames(path, scale=0.5):
    cap = cv2.VideoCapture(str(path)); out = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        out.append(cv2.resize(f, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA))
    cap.release()
    return out


def _person_masks(reference, framing, size, margin_px):
    h, w = size
    s = float(framing.get('scale', 1.0)); tx, ty = (float(v) / 2 for v in framing.get('translation_px', [0, 0]))
    m = np.float32([[s, 0, tx], [0, s, ty]])
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * margin_px + 1, 2 * margin_px + 1))
    masks = []
    for f in reference:
        border = np.concatenate([f[0], f[-1], f[:, 0], f[:, -1]]).astype(np.int16)
        bg = np.median(border, 0)
        person = (np.abs(f.astype(np.int16) - bg).sum(2) > DIFF).astype(np.uint8)
        person = cv2.warpAffine(person, m, (w, h), flags=cv2.INTER_NEAREST)
        masks.append(cv2.dilate(person, kernel).astype(bool))
    return masks


def check(generated, reference, framing):
    gen = _frames(generated); ref = _frames(reference)
    if not gen or len(gen) != len(ref):
        return {'status': 'unavailable', 'method': METHOD, 'reason': 'draft and reference frame counts differ'}
    h, w = gen[0].shape[:2]
    masks = _person_masks(ref, framing or {}, (h, w), max(1, int(MARGIN * w)))
    # median of each pixel over frames where the person is elsewhere, so a long hold leaves no ghost
    step = max(1, len(gen) // 120)
    stack = np.stack(gen[::step]).astype(np.float32)
    stack[np.stack(masks[::step])] = np.nan
    background = np.nanmedian(stack, 0) if np.isfinite(stack).any() else np.zeros((h, w, 3), np.float32)
    fill = np.isnan(background)
    if fill.any():
        background[fill] = np.broadcast_to(np.nanmedian(background.reshape(-1, 3), 0), background.shape)[fill]
    outside = ~np.logical_or.reduce(masks)
    if not outside.any() or float(np.std(background[outside].astype(np.float32).mean(1))) > FLAT_STD:
        return {'status': 'unavailable', 'method': METHOD, 'reason': 'background is not a flat colour',
                'frames_checked': len(gen), 'affects_verdict': False}
    hits = []
    for i, (f, person) in enumerate(zip(gen, masks)):
        d = (np.abs(f.astype(np.int16) - background).sum(2) > DIFF).astype(np.uint8)
        n, labels, stats, cent = cv2.connectedComponentsWithStats(d)
        # a region touching the person area (an arm swung out of the shifted mask) belongs to the person
        touching = set(np.unique(labels[person & (labels > 0)]).tolist())
        blobs = [(int(stats[k, 4]), cent[k]) for k in range(1, n) if stats[k, 4] >= MIN_AREA and k not in touching]
        if blobs:
            area, (x, y) = max(blobs, key=lambda b: b[0])
            hits.append((i, area, x * 2, y * 2))
    intervals = []
    for i, area, x, y in hits:
        if intervals and i - intervals[-1]['frames'][1] <= GAP + 1:
            last = intervals[-1]; last['frames'][1] = i
            if area * 4 > last['max_area_px']:
                last.update(max_area_px=area * 4, x=round(x), y=round(y))
        else:
            intervals.append({'frames': [i, i], 'max_area_px': area * 4, 'x': round(x), 'y': round(y)})
    fps = 24.0
    # Only something that appears and disappears inside the clip is reported: a region present from the first
    # or to the last frame, or for longer than TRANSIENT_S, is usually the person outside the shifted mask.
    # TRANSIENT_S was set after seeing such whole-clip false hits on stored runs, so it is not calibrated.
    last = len(gen) - 1
    intervals = [it for it in intervals if it['frames'][0] > 0 and it['frames'][1] < last
                 and it['frames'][1] - it['frames'][0] + 1 <= TRANSIENT_S * fps]
    for it in intervals:
        it['t_start_s'] = it['frames'][0] / fps; it['t_end_s'] = (it['frames'][1] + 1) / fps
    return {'status': 'warning' if intervals else 'clear', 'method': METHOD, 'intervals': intervals,
            'frames_checked': len(gen), 'affects_verdict': False,
            'scope': 'draft background outside the person region; quality warning only, motion verdict unchanged'}
