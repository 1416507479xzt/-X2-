import unittest

from x2_agent.aimdk_runtime import profile_from_version, verify_audio_interfaces
from x2_agent.agent_config import AgentConfig


class RuntimeProfileTests(unittest.TestCase):
    def test_known_versions_choose_different_builtin_mic(self):
        self.assertEqual(profile_from_version("aimdk v1.0.0-ga424add").built_in_mic_stream_id, 1)
        self.assertEqual(profile_from_version("aimdk v1.1.0-g1234567").built_in_mic_stream_id, 0)

    def test_unknown_version_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "未验证"):
            profile_from_version("aimdk v1.2.0-g1234567")

    def test_missing_ros_audio_field_fails_closed(self):
        def fake_type(name, fields):
            return type(name, (), {"get_fields_and_field_types":
                       classmethod(lambda cls: {key: "type" for key in fields})})
        processed = fake_type("Processed", {"stream_id", "audio_vad_state"})
        playback = fake_type("Playback", {"stamps", "info", "data", "pkg_name", "token_id"})
        request = fake_type("Request", {"request", "focus_requester"})
        response = fake_type("Response", {"reponse", "focus_response"})
        service = type("Service", (), {"Request": request, "Response": response})
        with self.assertRaisesRegex(ValueError, "audio_data"):
            verify_audio_interfaces(processed, playback, service, service)

    def test_default_mic_is_auto(self):
        config = AgentConfig(speech_key="test", ark_key="test")
        self.assertEqual(config.mic_stream_id, "auto")


if __name__ == "__main__":
    unittest.main()
