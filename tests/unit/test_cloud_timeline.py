import copy
import json
import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'server'), str(ROOT/'core')]
import timeline_contract as c


class CloudTimeline(unittest.TestCase):
    def setUp(self):
        self.folder = ROOT/'tests/fixtures/cloud-long'
        self.graph = json.loads((ROOT/'workflows/T1/depth-stage1.api.json').read_text())

    def test_actual_721(self):
        self.assertEqual(c.validate_cloud(self.folder, self.graph, 'joints.json', 'pose.mp4'),
                         {'frames': 721, 'fps': 24})

    def test_selected_control_is_checked(self):
        with patch.object(c, 'decoded_video', side_effect=[{'frames':721,'fps':24},
                                                          {'frames':97,'fps':24}]) as probe:
            with self.assertRaisesRegex(ValueError, 'depth.mp4'):
                c.validate_cloud(self.folder, self.graph, 'joints.json', 'depth.mp4')
            self.assertEqual(probe.call_args.args[0].name, 'depth.mp4')

    def test_disconnected_length(self):
        for node, field in [('9002/3059','length'), ('9002/5066','a'),
                            ('9002/3980','frame_rate')]:
            graph = copy.deepcopy(self.graph)
            graph[node]['inputs'][field] = 97
            with self.subTest(node=node), patch.object(c, 'decoded_video', return_value={'frames':721,'fps':24}):
                with self.assertRaisesRegex(ValueError, 'disconnected'):
                    c.validate_cloud(self.folder, graph, 'joints.json', 'pose.mp4')

    def test_short_output_rejected(self):
        with patch.object(c, 'decoded_video', return_value={'frames':97,'fps':24}):
            with self.assertRaisesRegex(ValueError, 'Generated video timeline'):
                c.validate_cloud_output('generated.mp4', {'frames':721,'fps':24})


if __name__ == '__main__':
    unittest.main()
