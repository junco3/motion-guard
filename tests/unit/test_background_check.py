import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'server'))
from background_check import check  # noqa: E402


def write(path, frames):
    out = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), 24, (192, 128))
    for f in frames:
        out.write(f)
    out.release()


def scene(n, person_x, background=None, extra=None):
    frames = []
    for i in range(n):
        f = np.full((128, 192, 3), 96, np.uint8) if background is None else background.copy()
        x = person_x(i)
        cv2.rectangle(f, (x, 40), (x + 16, 110), (40, 160, 230), -1)
        if extra and extra[0] <= i <= extra[1]:
            cv2.circle(f, (170, 12), 6, (40, 200, 40), -1)
        frames.append(f)
    return frames


def test_transient_background_object_is_a_warning(tmp_path):
    move = lambda i: 60 + i // 4
    write(tmp_path / 'r.mp4', scene(73, move)); write(tmp_path / 'g.mp4', scene(73, move, extra=(33, 40)))
    result = check(tmp_path / 'g.mp4', tmp_path / 'r.mp4', {'scale': 1.0, 'translation_px': [0, 0]})
    assert result['status'] == 'warning' and result['affects_verdict'] is False
    assert [i['frames'] for i in result['intervals']] == [[33, 40]]


def test_person_alone_is_clear(tmp_path):
    move = lambda i: 60 + i // 4
    write(tmp_path / 'r.mp4', scene(73, move)); write(tmp_path / 'g.mp4', scene(73, move))
    assert check(tmp_path / 'g.mp4', tmp_path / 'r.mp4', {'scale': 1.0, 'translation_px': [0, 0]})['status'] == 'clear'


def test_textured_background_is_not_checked(tmp_path):
    rng = np.random.default_rng(0)
    texture = rng.integers(0, 255, (128, 192, 3), dtype=np.uint8)
    move = lambda i: 60
    write(tmp_path / 'r.mp4', scene(41, move)); write(tmp_path / 'g.mp4', scene(41, move, background=texture))
    assert check(tmp_path / 'g.mp4', tmp_path / 'r.mp4', {})['status'] == 'unavailable'
