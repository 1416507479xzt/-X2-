import asyncio
from types import SimpleNamespace
import unittest

from x2_agent.aimdk_playback import AimdkPcmPlayer, AudioFocusError


class Request:
    def __init__(self):
        self.focus_requester = SimpleNamespace(pkg_name="", priority=0, priority_weight=0)


class Service:
    Request = Request


class Message:
    def __init__(self):
        self.info = SimpleNamespace()
        self.data = SimpleNamespace()


class PlaybackTests(unittest.IsolatedAsyncioTestCase):
    def make_player(self, granted=True, release_confirmed=True):
        player = AimdkPcmPlayer.__new__(AimdkPcmPlayer)
        player.pkg_name = "eldercare_agent"
        player.priority = 4
        player.RequestAudioFocus = Service
        player.AbandonAudioFocus = Service
        player.request_client = "request"
        player.abandon_client = "abandon"
        player.AudioPlayback = Message
        player._has_focus = False
        player._token = ""
        player._next_publish_time = 0
        player._lock = asyncio.Lock()
        published = []
        player.publisher = SimpleNamespace(publish=published.append)
        player.node = SimpleNamespace(get_clock=lambda: SimpleNamespace(
            now=lambda: SimpleNamespace(to_msg=lambda: "stamp")))
        player.ros = SimpleNamespace(spin_once=lambda node, timeout_sec=0: None)
        calls = []

        async def call(client, request):
            calls.append((client, request.focus_requester.pkg_name,
                          request.focus_requester.priority,
                          request.focus_requester.priority_weight))
            return SimpleNamespace(reponse=SimpleNamespace(
                status=SimpleNamespace(value=1)),
                focus_response=SimpleNamespace(focus_gain=(
                    granted if client == "request" else not release_confirmed)))

        player._call = call
        return player, published, calls

    async def test_focus_denial_never_publishes(self):
        player, published, calls = self.make_player(granted=False)
        with self.assertRaises(AudioFocusError):
            await player.begin()
        self.assertFalse(player._lock.locked())
        self.assertEqual(published, [])
        self.assertEqual(calls[0], ("request", "eldercare_agent", 4, 0))

    async def test_pcm_format_and_focus_release_match(self):
        player, published, calls = self.make_player()
        await player.begin()
        await player.write(b"\x01\x00\x02\x00")
        await player.end()
        self.assertEqual(len(published), 1)
        msg = published[0]
        self.assertEqual((msg.info.channels, msg.info.sample_rate,
                          msg.info.sample_format, msg.info.coding_format),
                         (1, 16000, "S16LE", "pcm"))
        self.assertEqual(msg.data.data, [1, 0, 2, 0])
        self.assertEqual(msg.pkg_name, "eldercare_agent")
        self.assertEqual(calls[0][1:], calls[1][1:])
        self.assertFalse(player._has_focus)

    async def test_odd_pcm_rejected_and_focus_still_released(self):
        player, published, _ = self.make_player()
        await player.begin()
        try:
            with self.assertRaises(ValueError):
                await player.write(b"\x01")
        finally:
            await player.end()
        self.assertEqual(published, [])

    async def test_focus_loss_notification_stops_next_pcm_publish(self):
        player, published, _ = self.make_player()
        await player.begin()
        player.ros.spin_once = lambda node, timeout_sec=0: player._on_focus_response(
            SimpleNamespace(pkg_name=player.pkg_name, focus_gain=False))
        with self.assertRaisesRegex(AudioFocusError, "抢占"):
            await player.write(b"\x01\x00")
        await player.end()
        self.assertEqual(published, [])

    async def test_release_must_be_confirmed_by_focus_response(self):
        player, published, _ = self.make_player(release_confirmed=False)
        await player.begin()
        with self.assertRaisesRegex(AudioFocusError, "释放音频焦点失败"):
            await player.end()
        self.assertTrue(player._has_focus)
        self.assertEqual(published, [])


if __name__ == "__main__":
    unittest.main()
