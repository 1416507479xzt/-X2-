import unittest

from x2_agent.aimdk_audio import VadAssembler


class VadAssemblerTests(unittest.TestCase):
    def test_v1_onboard_complete_pcm_including_end_chunk(self):
        collector = VadAssembler()
        self.assertIsNone(collector.feed(1, 1, b"\x00\x01", 0.0))
        self.assertIsNone(collector.feed(1, 2, b"\x02\x03", 0.1))
        utterance = collector.feed(1, 3, b"\x04\x05", 0.2)
        self.assertEqual(utterance.pcm, b"\x00\x01\x02\x03\x04\x05")
        self.assertEqual(utterance.packet_count, 3)
        self.assertEqual(utterance.elapsed_seconds, 0.2)

    def test_ignores_other_stream_and_recovers_missing_begin(self):
        collector = VadAssembler()
        self.assertIsNone(collector.feed(2, 1, b"wrong", 0.0))
        self.assertIsNone(collector.feed(1, 2, b"valid", 1.0))
        self.assertEqual(collector.feed(1, 3, b"", 1.1).pcm, b"valid")

    def test_begin_replaces_interrupted_utterance(self):
        collector = VadAssembler()
        collector.feed(1, 1, b"old", 0.0)
        collector.feed(1, 1, b"new", 0.1)
        self.assertEqual(collector.feed(1, 3, b"", 0.2).pcm, b"new")

    def test_oversize_discards_and_does_not_leak_into_next_turn(self):
        collector = VadAssembler(max_seconds=0.001)
        collector.feed(1, 1, b"a" * 20, 0.0)
        self.assertIsNone(collector.feed(1, 2, b"b" * 20, 0.01))
        self.assertIsNone(collector.feed(1, 2, b"tail", 0.011))
        self.assertIsNone(collector.feed(1, 3, b"", 0.02))
        self.assertEqual(collector.discarded, 1)
        collector.feed(1, 1, b"ok", 1.0)
        self.assertEqual(collector.feed(1, 3, b"", 1.0).pcm, b"ok")


if __name__ == "__main__":
    unittest.main()
