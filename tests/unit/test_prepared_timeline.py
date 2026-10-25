import copy,json,pathlib,sys,unittest
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'server'),str(ROOT/'core')]
import timeline_contract as c
class Prepared(unittest.TestCase):
 def setUp(self):
  self.root=ROOT/'tests/fixtures/prepared-short'
  self.w=json.loads((self.root/'workflow.api.json').read_text(encoding='utf-8'))
  self.p=json.loads((self.root/'execution-plan.json').read_text(encoding='utf-8'));self.gt=self.p.get('gt_file','joints.json')
 def test_actual_short(self):self.assertEqual(c.validate(self.root,self.p,self.w,self.gt)['frames'],97)
 def test_actual_long(self):self.assertEqual(c.validate(ROOT/'tests/fixtures/long-reference',dict(self.p,expected_frames=721,expected_fps=24),self.w,'joints.json')['frames'],721)
 def test_video_mismatch(self):
  with patch.object(c,'decoded_video',return_value={'frames':96,'fps':24}),self.assertRaisesRegex(ValueError,'video timeline'):c.validate(self.root,self.p,self.w,self.gt)
 def test_plan_mismatch(self):
  with self.assertRaisesRegex(ValueError,'plan timeline'):c.validate(self.root,dict(self.p,expected_frames=721),self.w,self.gt)
 def test_graph_mismatch(self):
  for node,field in [('9002/3059','length'),('diag_video','fps'),('5518/4849','fps'),('5014/1241','frame_rate'),('9002/9005','frame_rate'),('9002/3980','frame_rate')]:
   w=copy.deepcopy(self.w);w[node]['inputs'][field]=30
   with self.subTest(node=node),patch.object(c,'decoded_video',return_value={'frames':97,'fps':24}),self.assertRaisesRegex(ValueError,'graph timeline disconnected'):c.validate(self.root,self.p,w,self.gt)
if __name__=='__main__':unittest.main(verbosity=2)
