import pytest
from motionguard_core.reference_io import validate_timeline

def timeline(n):return {'meta':{'frames':n,'fps':24},'frames':[{'frame':i,'time_s':i/24} for i in range(n)]}
@pytest.mark.parametrize('n',[9,97,289,721,961])
def test_supported_data_timelines(n):
    result=validate_timeline(timeline(n));assert result['frames']==n
    assert result['sample_span_seconds']==(n-1)/24
    assert result['encoded_duration_seconds']==n/24
@pytest.mark.parametrize('n',[0,8,96,720,969])
def test_invalid_lengths(n):
    with pytest.raises(ValueError):validate_timeline(timeline(n))
@pytest.mark.parametrize('change',['fps','count','time','index','nan','bool'])
def test_inconsistent_metadata_and_frames(change):
    data=timeline(721)
    if change=='fps':data['meta']['fps']=30
    if change=='count':data['meta']['frames']=97
    if change=='time':data['frames'][600]['time_s']=4
    if change=='index':data['frames'][600]['frame']=1
    if change=='nan':data['frames'][600]['time_s']=float('nan')
    if change=='bool':data['frames'][0]['frame']=False
    with pytest.raises(ValueError):validate_timeline(data)
