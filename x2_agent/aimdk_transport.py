"""Local AimDK transport exposing the existing Agent's gateway event contract.

The dialogue, ASR, TTS and stage logic stay in DoubaoAgent. This adapter only
converts one completed ROS VAD utterance into start/append/commit frames and
routes the Agent's PCM output to the opt-in ROS player.
"""

import asyncio
import base64
import json
import logging
import uuid

from .aimdk_audio import VadAssembler
from .aimdk_playback import AimdkPcmPlayer
from .aimdk_runtime import verify_audio_interfaces
from .gateway import T

logger = logging.getLogger("x2_agent")


class AimdkLocalTransport:
    def __init__(self, *, stream_id=1):
        try:
            import rclpy
            from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
            from aimdk_msgs.msg import ProcessedAudioOutput, AudioPlayback
            from aimdk_msgs.srv import RequestAudioFocus, AbandonAudioFocus
        except ImportError as exc:
            raise ValueError("AimDK 真机传输需要 PC2 的 rclpy 和机载 aimdk_msgs") from exc
        verify_audio_interfaces(ProcessedAudioOutput, AudioPlayback,
                                RequestAudioFocus, AbandonAudioFocus)
        self.ros = rclpy
        if not rclpy.ok():
            rclpy.init()
        self.node = rclpy.create_node("eldercare_vad_input")
        self.player = AimdkPcmPlayer()
        self.collector = VadAssembler(stream_id=stream_id)
        self.incoming = asyncio.Queue(maxsize=4)
        self._spin_task = None
        self._closed = False
        self._speaking = False
        self._playing = False
        qos = QoSProfile(depth=50, reliability=ReliabilityPolicy.BEST_EFFORT,
                         durability=DurabilityPolicy.VOLATILE)
        self.node.create_subscription(ProcessedAudioOutput,
                                      "/agent/process_audio_output", self._on_audio, qos)

    def _on_audio(self, msg):
        if self._speaking:
            self.collector.reset()
            return
        utterance = self.collector.feed(msg.stream_id, msg.audio_vad_state.value,
                                        msg.audio_data)
        if utterance is None or not utterance.pcm:
            return
        try:
            self.incoming.put_nowait(utterance.pcm)
        except asyncio.QueueFull:
            logger.warning("真机 VAD 队列已满，丢弃一段录音以免旧话延后播报")

    async def _spin(self):
        while not self._closed and self.ros.ok():
            self.ros.spin_once(self.node, timeout_sec=0)
            await asyncio.sleep(0.005)

    async def __aenter__(self):
        self._spin_task = asyncio.create_task(self._spin())
        return self

    async def __aexit__(self, *_):
        self._closed = True
        if self._spin_task is not None:
            await self._spin_task
        try:
            await self.player.end()
        finally:
            self.node.destroy_node()
            self.player.close()

    def __aiter__(self):
        return self._frames()

    async def _frames(self):
        yield json.dumps({"type": T["sync"], "robotCid": "aimdk-local",
                          "state": "online", "callbackType": "audio2tts",
                          "controlActive": True, "audioActive": True})
        while not self._closed:
            pcm = await self.incoming.get()
            if self._speaking:
                continue
            event_id = "aimdk-" + uuid.uuid4().hex[:12]
            yield json.dumps({"type": T["a_start"], "eventId": event_id})
            for offset in range(0, len(pcm), 6400):
                chunk = pcm[offset:offset + 6400]
                yield json.dumps({"type": T["a_append"], "eventId": event_id,
                                  "audio": base64.b64encode(chunk).decode("ascii")})
            yield json.dumps({"type": T["a_commit"], "eventId": event_id})

    async def send(self, raw):
        frame = json.loads(raw)
        ftype = frame.get("type")
        if ftype == T["tts_delta"]:
            if not self._playing:
                await self.player.begin()
                self._playing = True
                self._speaking = True
            await self.player.write(base64.b64decode(frame["audio"], validate=True))
        elif ftype == T["tts_done"]:
            if self._playing:
                try:
                    await self.player.end()
                finally:
                    self._playing = False
                    self._speaking = False
        elif ftype == T["error"]:
            logger.error("真机轮次失败: %s %s", frame.get("errorCode"),
                         frame.get("errorMsg"))
