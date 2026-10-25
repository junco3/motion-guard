import copy
import uuid
import pytest
from server.layout_graph import build, validate, UP, SAMPLE
from server.stage_audit_graph import digest, ancestors


def graph():
    return build(str(uuid.uuid4()),'character.png','reference.mp4','reference.mp4','{}','A dancer in a studio.',42)


def test_official_stage_guides_and_lazy_boundary():
    g=graph()
    assert validate(g)
    assert g['9002/9042']['inputs']['latent']==['9002/5012',2]
    assert g['9034/9043']['inputs']['latent']==['9034/9039',2]
    assert g['9034/9039']['inputs']['latent']==[UP,0]
    assert not {UP,SAMPLE}&ancestors(g,'diag_save')
    assert not {UP,SAMPLE}&ancestors(g,'mg_inspect')


@pytest.mark.parametrize('change',['bypass','extra_output','first_frame_removed','second_guide_removed','seed','fps'])
def test_rehashed_bypasses_rejected(change):
    g=copy.deepcopy(graph())
    if change=='bypass':g[UP]['inputs']['samples']=['5516/5000',2]
    elif change=='extra_output':g['extra']=copy.deepcopy(g['diag_save']);g['extra']['inputs']['video']=['5518/4849',0]
    elif change=='first_frame_removed':g['5516/4829']['inputs']['latent_image']=['9002/5012',2]
    elif change=='second_guide_removed':g[SAMPLE]['inputs']['latent_image']=[UP,0]
    elif change=='seed':g['9034/9031']['inputs']['noise_seed']=99
    else:g['5518/4849']['inputs']['fps']=30
    g['mg_audit_init']['inputs']['graph_sha256']=digest(g)
    with pytest.raises(ValueError):validate(g)
