"""Bounded presentation adapters. No model-supplied numeric SDK parameters.

AimDK 1.1 docs: Interface/interactor/screen.html and
Interface/control_mod/preset_motion.html. Unity's love is only a visual
approximation of X2 sympathy, not an assertion that SDK has a 'love' enum.
"""
import asyncio
import time

EMOJI_IDS = {"blink": 1, "neutral": 10, "calm_alternate": 11,
             "playful": 20, "cute": 30, "eyes_closed": 40, "eyes_open": 50,
             "bored": 60, "sleepy": 80, "happy": 90, "delighted": 100,
             "sad": 110, "sympathy": 120, "confused": 130, "surprised": 140,
             "coquettish": 150, "serious": 160, "thinking": 170,
             "angry": 180, "admiration": 200}
MOTIONS = {"wave_hands": (1002, 2), "wave_left": (1002, 1),
           "raise_right": (1001, 2), "raise_left": (1001, 1),
           "clap": (3017, 11), "salute_right": (1013, 2),
           "salute_left": (1013, 1), "heart_both": (1007, 3),
           "heart_right": (1007, 2), "heart_left": (1007, 1),
           "open_arms": (3008, 11), "encourage": (3011, 11),
           "arms_level": (1010, 3), "arm_level_right": (1010, 2),
           "arm_level_left": (1010, 1), "bye": (3031, 11),
           "cross_arms": (3009, 11), "wave_chest": (1011, 2),
           "bow": (3001, 11), "scratch_head": (3024, 11)}
EMOTION_MEANINGS = dict(zip(EMOJI_IDS, [
    "眨眼", "平静和自然倾听，可主动恢复", "平静眼睛变化2", "游戏",
    "卖萌", "闭眼", "睁眼", "无聊，不用于对长者表达不耐烦",
    "睡着，不用于正在倾听", "快乐和友好", "加倍开心，避免夸张",
    "悲伤，仅在语境确实合适时，不能把身体疲劳等同悲伤", "同情和关怀，不应每轮重复",
    "疑惑", "震惊，不夸大健康风险", "撒娇，谨慎使用", "严肃", "思考",
    "愤怒，不对长者发怒", "崇拜和赞赏，不等于同情"]))
GESTURE_MEANINGS = dict(zip(MOTIONS, [
    "右手挥手，问候或告别", "左手挥手", "右手举手", "左手举手",
    "鼓掌，祝贺或鼓励", "右手敬礼", "左手敬礼", "双手比心，表达关怀",
    "右手比心", "左手比心",
    "拥抱姿态；Unity仅张开双臂的近似展示，无接触；真机须保持安全距离",
    "加油，鼓励", "双手平举", "右手平举", "左手平举", "拜拜",
    "双手打叉", "胸前右手挥手", "鞠躬", "挠头"]))
UNITY_EMOTIONS = {"neutral": "neutral", "happy": "happy", "sad": "sad",
                  "sympathy": "love", "surprised": "surprised",
                  "angry": "angry", "admiration": "love"}
UNITY_GESTURES = {"wave_hands", "open_arms"}
SERVICES = {
    "emoji": "/aimdk_5Fmsgs/srv/PlayEmoji",
    "motion": "/aimdk_5Fmsgs/srv/SetMcPresetMotion",
    "mode": "/aimdk_5Fmsgs/srv/GetMcAction",
}


def capabilities(control=True, backend="unity"):
    if backend == "none":
        return {"emotions": [], "gestures": [], "explanation_gestures": [],
                "explanation_note": "当前只测试语音链路，不执行表情和动作。",
                "emotion_meanings": {}, "gesture_meanings": {},
                "backend": "none", "visual_limit": ""}
    emotions = list(EMOJI_IDS if backend == "aimdk" else UNITY_EMOTIONS) if control else []
    gestures = list(MOTIONS if backend == "aimdk" else
                    [name for name in MOTIONS if name in UNITY_GESTURES]) if control else []
    explanation_candidates = (["raise_right", "raise_left"] if backend == "aimdk" else ["open_arms"])
    return {"emotions": emotions, "gestures": gestures,
            "explanation_gestures": [name for name in explanation_candidates if name in gestures],
            "explanation_note": (
                "可用举手作一次讲解强调，不是指点、摊掌或治疗示范；不保证小幅度动作，需保持安全距离。"
                if backend == "aimdk" else
                "open_arms是已有的双臂展开动画，可近似配合一次友善说明，不是专门的摊掌讲解动画。"
                "wave_hands只用于招呼/告别，不用来反复解释健康建议。"),
            "emotion_meanings": {k: EMOTION_MEANINGS[k] for k in emotions},
            "gesture_meanings": {k: GESTURE_MEANINGS[k] for k in gestures},
            "backend": backend,
            "visual_limit": "Unity的sympathy和admiration都近似显示爱心；不同于真机素材" if backend == "unity" else ""}


def unity_plan(emotion, gesture, text):
    if emotion not in (None, *UNITY_EMOTIONS) or gesture not in (None, *UNITY_GESTURES):
        raise ValueError("Unsupported presentation")
    plan = []
    if emotion:
        plan.append(("emotion", UNITY_EMOTIONS[emotion],
                     {} if emotion == "neutral" else
                     {"durationMs": min(12000, max(3000, len(text) * 230))}))
    if gesture:
        plan.append(("gesture", gesture, {}))
    return plan


class AimdkPresentation:
    """One persistent ROS node. No service writes until dispatch.

    Explicit deployment opt-in is required. Check stable stand immediately
    before motion, never switch robot mode. No retries of uncertain writes:
    timeout is NOT evidence that an action failed to execute.
    """
    def __init__(self):
        try:
            import rclpy
            from rclpy.context import Context
            from rclpy.node import Node
            from aimdk_msgs.srv import PlayEmoji, SetMcPresetMotion, GetMcAction
        except ImportError as exc:
            raise ValueError("AimDK表现后端需要PC2上的rclpy及匹配固件的aimdk_msgs") from exc
        self.ros = rclpy
        self.context = Context()
        rclpy.init(context=self.context)
        self.node = Node("eldercare_presentation", context=self.context)
        self.types = {"emoji": PlayEmoji, "motion": SetMcPresetMotion, "mode": GetMcAction}
        self.clients = {k: self.node.create_client(v, SERVICES[k]) for k, v in self.types.items()}
        self.lock = asyncio.Lock()
        self.last_motion = float("-inf")

    async def _call(self, kind, req, timeout=.6):
        client = self.clients[kind]
        if not client.service_is_ready():
            return None
        future = client.call_async(req)
        deadline = time.monotonic() + timeout
        try:
            while not future.done() and time.monotonic() < deadline:
                self.ros.spin_once(self.node, timeout_sec=0)
                await asyncio.sleep(.005)
            return future.result() if future.done() else None
        finally:
            if not future.done():
                client.remove_pending_request(future)
                future.cancel()

    async def dispatch(self, emotion, gesture, allowed):
        if emotion not in (None, *EMOJI_IDS) or gesture not in (None, *MOTIONS):
            raise ValueError("Unsupported presentation")
        results = []
        async with self.lock:
            if emotion and allowed():
                req = self.types["emoji"].Request()
                req.emotion_id = EMOJI_IDS[emotion]
                req.mode = 1  # once, never indefinite loop
                req.priority = 1  # must not mask system fault indications (8/10)
                response = await self._call("emoji", req)
                results.append({"kind": "emotion", "name": emotion,
                                "status": "unknown" if response is None else
                                ("accepted" if response.success else "rejected")})
            if gesture:
                status = "blocked"
                if allowed() and time.monotonic() - self.last_motion >= 8:
                    state = await self._call("mode", self.types["mode"].Request())
                    if (state is not None and state.header.code == 0
                            and state.info.action_desc == "STAND_DEFAULT"
                            and state.info.status.value == 100 and allowed()):
                        req = self.types["motion"].Request()
                        req.motion.value, req.area.value = MOTIONS[gesture]
                        req.interrupt = False
                        # Default zero stamp means immediate; do not set future timestamps.
                        self.last_motion = time.monotonic()
                        response = await self._call("motion", req)
                        status = "unknown" if response is None else (
                            "accepted" if response.response.header.code == 0 else "rejected")
                results.append({"kind": "gesture", "name": gesture, "status": status})
        return results

    def close(self):
        self.node.destroy_node()
        self.ros.shutdown(context=self.context)
