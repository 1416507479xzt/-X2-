"""Opt-in AimDK v1.0.0 PCM playback; does not switch robot mode.

Only instantiate on the robot after matching the installed AimDK interfaces.
This module is an output adapter: it knows nothing about competition dialogue.
"""

import asyncio
import time
import uuid

from .aimdk_audio import PCM_BYTES_PER_SECOND


PLAYBACK_TOPIC = "/aima/hal/audio/playback"
REQUEST_FOCUS = "/aimdk_5Fmsgs/srv/RequestAudioFocus"
ABANDON_FOCUS = "/aimdk_5Fmsgs/srv/AbandonAudioFocus"


class AudioFocusError(RuntimeError):
    pass


class AimdkPcmPlayer:
    """Publish 16 kHz mono S16LE PCM after focus is granted.

    Keep one instance for the process lifetime. begin/write/end form one
    spoken turn. A focus denial never publishes audio. This class does not
    call StopAudioPlay, which could interrupt system safety announcements.
    """

    def __init__(self, *, pkg_name="eldercare_agent", priority=4, node=None):
        if not pkg_name or not 1 <= priority <= 10:
            raise ValueError("invalid playback identity or priority")
        try:
            import rclpy
            from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
            from aimdk_msgs.msg import AudioPlayback, FocusResponse
            from aimdk_msgs.srv import RequestAudioFocus, AbandonAudioFocus
        except ImportError as exc:
            raise ValueError("先在真机 PC2 source 机载 AimDK ROS 环境") from exc

        self.ros = rclpy
        self.AudioPlayback = AudioPlayback
        self.RequestAudioFocus = RequestAudioFocus
        self.AbandonAudioFocus = AbandonAudioFocus
        self.owns_node = node is None
        if node is None:
            if not rclpy.ok():
                rclpy.init()
            node = rclpy.create_node("eldercare_pcm_playback")
        self.node = node
        self.pkg_name = pkg_name
        self.priority = priority
        qos = QoSProfile(depth=20, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.VOLATILE)
        self.publisher = node.create_publisher(AudioPlayback, PLAYBACK_TOPIC, qos)
        self.request_client = node.create_client(RequestAudioFocus, REQUEST_FOCUS)
        self.abandon_client = node.create_client(AbandonAudioFocus, ABANDON_FOCUS)
        self._has_focus = False
        self._token = ""
        self._next_publish_time = 0.0
        self._lock = asyncio.Lock()
        node.create_subscription(FocusResponse, "/aima/hal/audio/focus_response",
                                 self._on_focus_response, qos)

    def _on_focus_response(self, msg):
        if msg.pkg_name == self.pkg_name and not msg.focus_gain:
            self._has_focus = False

    async def _call(self, client, request, timeout=2.0):
        if not client.service_is_ready():
            raise AudioFocusError("音频焦点服务未就绪")
        future = client.call_async(request)
        deadline = time.monotonic() + timeout
        while not future.done() and time.monotonic() < deadline:
            self.ros.spin_once(self.node, timeout_sec=0)
            await asyncio.sleep(0.01)
        if not future.done():
            client.remove_pending_request(future)
            future.cancel()
            raise AudioFocusError("音频焦点服务超时，结果未知")
        result = future.result()
        if result is None:
            raise AudioFocusError("音频焦点服务无结果")
        return result

    def _focus_request(self, service_type):
        request = service_type.Request()
        request.focus_requester.pkg_name = self.pkg_name
        request.focus_requester.priority = self.priority
        request.focus_requester.priority_weight = 0
        return request

    async def begin(self):
        await self._lock.acquire()
        try:
            if self._has_focus:
                raise AudioFocusError("上一轮音频焦点尚未释放")
            response = await self._call(
                self.request_client, self._focus_request(self.RequestAudioFocus))
            status = response.reponse.status.value
            gain = response.focus_response.focus_gain
            if status != 1 or not gain:
                raise AudioFocusError("机器人未授予音频焦点：status=%s focus_gain=%s" %
                                      (status, gain))
            self._has_focus = True
            self._token = uuid.uuid4().hex
            self._next_publish_time = time.monotonic()
        except BaseException:
            self._lock.release()
            raise

    async def write(self, pcm):
        if not self._lock.locked() or not self._has_focus:
            raise AudioFocusError("没有音频焦点，禁止播放")
        pcm = bytes(pcm)
        if not pcm:
            return
        if len(pcm) % 2:
            raise ValueError("S16LE PCM 必须有偶数字节")
        # Keep the hardware queue bounded even when cloud TTS emits a burst.
        for offset in range(0, len(pcm), 3200):
            chunk = pcm[offset:offset + 3200]
            delay = self._next_publish_time - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            # This node is otherwise spun only during service calls. Process
            # focus-loss notifications before every publish as well.
            self.ros.spin_once(self.node, timeout_sec=0)
            if not self._has_focus:
                raise AudioFocusError("音频焦点已被其他来源抢占")
            msg = self.AudioPlayback()
            msg.stamps = self.node.get_clock().now().to_msg()
            msg.info.channels = 1
            msg.info.sample_rate = 16000
            msg.info.size = len(chunk)
            msg.info.sample_format = "S16LE"
            msg.info.coding_format = "pcm"
            msg.data.data = list(chunk)
            msg.pkg_name = self.pkg_name
            msg.token_id = self._token
            self.publisher.publish(msg)
            self._next_publish_time = max(time.monotonic(), self._next_publish_time) + len(chunk) / PCM_BYTES_PER_SECOND

    async def end(self):
        if not self._lock.locked() and not self._has_focus:
            return
        acquired_here = not self._lock.locked()
        if acquired_here:
            await self._lock.acquire()
        try:
            if self._has_focus:
                # Wait for the final published chunk's nominal playback time.
                delay = self._next_publish_time - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                response = await self._call(self.abandon_client,
                                            self._focus_request(self.AbandonAudioFocus))
                if (response.reponse.status.value != 1 or
                        response.focus_response.focus_gain):
                    raise AudioFocusError("释放音频焦点失败，结果未确认")
                self._has_focus = False
        finally:
            self._lock.release()

    def close(self):
        if self._has_focus:
            raise AudioFocusError("先调用 end() 释放焦点后再关闭")
        if self.owns_node:
            self.node.destroy_node()
            self.ros.shutdown()
