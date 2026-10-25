import numpy as np
from motionguard_core.report import failure_markers

def pose():
    return {'size':[768,512],'fps':24,'points':[[[100.,200.]]*14 for _ in range(240)],
            'scores':[[1.]*14 for _ in range(240)]}
def test_long_timeline_marker_uses_generated_joint():
    p=pose();p['points'][210]=[[120.,250.]]*14
    m=failure_markers([{'type':'MISSING_MOTION','frames':[200,220],'joints':[10]}],p,210)
    assert len(m)==1 and m[0]['pixel']==[120.,250.] and m[0]['time_s']==8.75 and m[0]['joint']==10
def test_no_markers_outside_interval_or_without_specific_joint():
    p=pose()
    assert failure_markers([{'type':'WRONG_POSE','frames':[0,239]}],p,210)==[]
    assert failure_markers([{'type':'MISSING_MOTION','frames':[0,100],'joints':[10]}],p,210)==[]
def test_invalid_or_unobserved_coordinates_never_get_a_circle():
    for xy,score in [([float('nan'),10],1),([900,10],1),([-1,10],1),([10,10],.1),([10,10],float('nan'))]:
        p=pose();p['points'][210]=[[100,200] for _ in range(14)];p['points'][210][10]=xy;p['scores'][210][10]=score
        assert failure_markers([{'type':'MISSING_MOTION','frames':[200,220],'joints':[10]}],p,210)==[]

def test_invalid_indices_and_duplicates():
    p=pose()
    m=failure_markers([{'type':'MISSING_MOTION','frames':[200,220],'joints':[10,10,-1,True,100]}],p,210)
    assert len(m)==1 and m[0]['joint']==10
