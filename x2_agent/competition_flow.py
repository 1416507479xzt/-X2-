"""Transport-independent, session-only health interview with bounded clarification.

The deterministic path is intentionally conservative. Ambiguous answers may be
interpreted by an optional external classifier, but this module performs no I/O.
"""
from dataclasses import dataclass
import re
from typing import Mapping, Optional
from .health_memory import SessionHealthMemory
from .model_dialogue import ModelDialogue


GREETING = "您好，我是灵犀。见到您真好！您今天感觉怎么样？"


@dataclass(frozen=True)
class HealthReply:
    text: str
    emotion: Optional[str] = None


# empathy, follow-up, closing, expression. Never substitute an expression's
# canned acknowledgment for an answer to a person's health concern.
_STATES = {
    "感到疲惫": (
        "今天有些累呀，先别勉强自己。",
        "昨晚休息得怎么样？", "您注意休息，有需要随时叫我。", "love"),
    "心情低落": (
        "心情不太好呀，我在这儿陪您。",
        "愿意说说遇到什么事了吗？",
        "有需要随时叫我，也可以和家人或照护人员聊聊。", "love"),
    "腰部不适": (
        "听起来您的腰有些不舒服，先别勉强自己。",
        "这是今天才开始的吗？", "您今天多留意身体，有需要随时叫我。", "love"),
    "状态良好": (
        "那就好。", "今天有什么想做的事吗？",
        "祝您今天过得愉快，有需要随时叫我。", "happy"),
    "休息欠佳": (
        "听起来您没休息好，辛苦了。", "今天精神怎么样？",
        "您注意休息，有需要随时叫我。", "love"),
}
_SPOKEN_STATES = {
    "感到疲惫": "您说今天有些累", "心情低落": "您说今天心情不太好",
    "腰部不适": "您说今天腰有些不舒服", "状态良好": "您说今天状态还不错",
    "休息欠佳": "您提到没休息好",
}
_SPOKEN_DETAILS = {
    "昨晚休息欠佳": "昨晚休息得不太好", "昨晚休息良好": "昨晚休息得还不错",
    "休息欠佳（时间未说明）": "休息得不太好，但没有说明具体时间",
    "休息不足（时间未说明）": "没有睡够，但没有说明具体时间",
    "想念家人": "有些想念家人", "腰部不适已持续多日": "这种不适已经有几天了",
    "腰部不适今天出现": "是今天才开始不舒服的",
    **{f"想{x}": f"想{x}" for x in ("散步", "听音乐", "下棋", "聊天", "看书")},
}
_SLEEP_POOR = re.compile(
    r"没(?:有|怎么)?睡好|睡不(?:好|着|踏实)|睡得不(?:太)?好|没(?:有)?休息好|"
    r"休息不(?:太)?好|休息得不(?:太)?好|失眠|没睡够|睡不够|睡得少|没怎么睡|半夜醒")
_SLEEP_GOOD = re.compile(r"(?:睡|休息)(?:得)?(?:很|挺|还|蛮)?好|(?:睡|休息)得(?:不错|还行)")
_ACTIVITIES = ("散步", "听音乐", "下棋", "聊天", "看书")
_TOPIC = re.compile(
    r"吃药|服药|用药|药怎么|什么药|降压药|药量|药名|提醒|复诊|报名|"
    r"(?:什么|哪些|推荐|参加|社区).{0,5}活动|天气|下雨|气温|几点|现在时间|"
    r"今天(?:星期|几号)|跳舞|舞蹈|播放|放(?:首|一首)|唱歌|挥(?:挥)?手|握(?:握)?手|转身|"
    r"往前|走一步|讲(?:个|一个)|笑话|你(?:是谁|叫什么|多大)|"
    r"(?:显示|切换|换个|做个|来个).{0,8}表情|张开(?:双臂|手臂)|展开(?:双臂|手臂)|"
    r"停止(?:动作|运动|移动|播放|说话)?|停下来|停一下|别动")
_DECLINE = re.compile(r"不想说|不愿说|不想聊|不愿聊|别问|不问了|不说了|先不聊|暂时不聊|不用问|不用了|再见|先这样")
_THANKS = re.compile(r"^(?:谢谢(?:您|你)?|好的?|知道了|我知道了|明白了|嗯嗯|不用担心|没事了)+[。！!，,]*$")
_RESUME = re.compile(r"继续刚才|继续问|接着聊|刚才的问题")
_CORRECTION = re.compile(r"说错|更正|其实|不是.{0,12}(?:而是|只是|是)")
_CONTEXTUAL = re.compile(
    # A keyword in these contexts is not proof of the current speaker's state.
    r"我(?:的)?(?:儿子|女儿|老伴|孙子|孙女|朋友|邻居|妈妈|爸爸|母亲|父亲)|"
    r"(?:^|[，,。；;])(?:他|她|他们|她们|爷爷|奶奶)|"
    r"昨天|前天|以前|过去|上周|去年|曾经|当时|小时候|"
    r"[\"“”‘’「」]|如果|假如|要是|比如|假设|听说|他说|她说|老人说|"
    r"不是不(?:累|疲惫|难过|伤心)|不能说|谁说|怎么会|"
    r"(?:不是|不算|不太|并不)(?:很|特别|那么|太)?(?:开心|舒服|精神|累|疲惫)|"
    r"(?:不是|不算|并不)(?:很|特别|那么|太)好")


def _clean(text: str) -> str:
    return "".join((text or "").split())


def _declines(text: str) -> bool:
    # "不是不想说" is not consent to terminate the interview. An uncertain
    # double negative goes to semantic interpretation/clarification instead.
    text = re.sub(r"(?:不是|并非)(?:不想说|不愿说|不想聊|不愿聊)", "", text)
    return bool(_DECLINE.search(text))


def _affirmed(text: str):
    """Remove explicit denial spans, keeping concerns after 但/只是/而是."""
    denied = set()
    patterns = (
        ("心情低落", r"(?:不是|并非|没有)(?:心情不太好|心情不好|心情有点差|不开心|不高兴|很难过|难过|郁闷|伤心)|不(?:怎么|太|很)?(?:难过|伤心|郁闷)"),
        ("感到疲惫", r"(?:不是|并非|没有|没|不)(?:觉得|感觉|感到)?(?:很|太|那么|特别|有点|有些)?(?:累|疲惫|乏力|疲劳)|(?:不是|并非)(?:没精神)"),
        ("腰部不适", r"腰(?:没有|没|不)(?:很|太|那么|怎么)?(?:疼|痛|酸|不舒服)|(?:不是|并非)(?:腰|腰部)(?:有点|有些|很)?(?:疼|痛|酸|不舒服)"),
        ("休息欠佳", r"(?:不是|并非)(?:昨晚)?(?:没睡好|没睡够|睡不好|休息不好|没休息好|失眠)"),
    )
    for state, pattern in patterns:
        if re.search(pattern, text):
            denied.add(state)
            text = re.sub(pattern, "", text)
    return text, denied


class HealthGreetingFlow:
    """Two answer turns; recall and unrelated requests do not count as answers.

    Memory belongs to this object only. ``begin`` preserves it on a reconnect
    for the same named person, and clears it when the configured person changes.
    """

    def __init__(self):
        self.awaiting_health = False
        self.awaiting_followup = False
        self.clarifications = 0
        self.health_state: Optional[str] = None
        self.health_detail: Optional[str] = None
        self._elder_name = ""
        self._other_states = ()
        self._closing = ""
        self._handoff = ""
        self._suspended = None
        self._reported_denial = False
        self._current_followup = ""
        self.body_memory = SessionHealthMemory()
        self.model_dialogue = ModelDialogue()

    def begin(self, elder_name: str = "") -> str:
        name = elder_name.strip()[:12]
        if name != self._elder_name:
            self.health_state = self.health_detail = None
            self._other_states = ()
            self._reported_denial = False
            self.body_memory = SessionHealthMemory()
            self.model_dialogue = ModelDialogue()
        self._elder_name = name
        self.awaiting_health = True
        self.awaiting_followup = False
        self.clarifications = 0
        self._closing = self._handoff = self._current_followup = ""
        self._suspended = None
        self.model_dialogue.begin()
        return f"{name}，{GREETING}" if name else GREETING

    @staticmethod
    def _is_recall_question(text: str) -> bool:
        if any(word in text for word in ("说错", "更正", "不是", "其实")):
            return False
        if any(word in text for word in ("药", "活动", "报名", "提醒")):
            return False
        return any(word in text for word in (
            "刚才说", "刚刚说", "之前说", "记得我说", "我说了什么",
            "我今天感觉怎么样", "今天感觉怎么样", "我今天状态怎么样", "记得我的状态",
        ))

    def _observation(self, text: str):
        # Short answers refer to the question we actually asked. In particular,
        # "还行" about sleep must not erase the person's reported fatigue.
        if self.awaiting_followup and "昨晚休息得怎么样" in self._current_followup:
            answer = re.sub(r"[，,。！!？?]", "", text)
            if re.fullmatch(r"(?:嗯|哦)?(?:还行|还好|挺好|很好|不错|还不错|好|好的|可以)(?:吧|啊|呀)?", answer):
                return self.health_state, "昨晚休息良好", (), set()
            if re.fullmatch(r"(?:嗯|唉)?(?:不好|不太好|不怎么好|很差|很不好)(?:啊|呀)?", answer):
                return self.health_state, "昨晚休息欠佳", (), set()
        if _CONTEXTUAL.search(text):
            return None, None, (), set()
        positive, denied = _affirmed(text)
        states = []
        if re.search(r"腰(?:部)?(?:还)?(?:有点|有些|有一点|有点儿|很|好|特别|不太)?(?:酸|疼|痛|不舒服)", positive):
            states.append("腰部不适")
        if re.search(r"心情(?:不太好|不好|有点差|很差|低落)|难过|不开心|不高兴|郁闷|心里难受|伤心", positive):
            states.append("心情低落")
        if re.search(r"(?:有点|有些|有一点|有点儿|很|太|好|特别)累|累了|疲惫|疲劳|乏力|没精神|有点乏", positive):
            states.append("感到疲惫")
        poor_sleep = _SLEEP_POOR.search(positive)
        if poor_sleep and not states:
            states.append("休息欠佳")
        status_text = _SLEEP_GOOD.sub("", positive)
        if not states and (re.search(r"还行|挺好|很好|不错|精神好|感觉好|心情还好|开心", status_text) or denied):
            states.append("状态良好")
        state = states[0] if states else None
        # Denying poor sleep does not deny an already reported tired feeling.
        if state == "状态良好" and denied == {"休息欠佳"} and self.health_state == "感到疲惫":
            state = None
        detail = self._detail(text, state or self.health_state)
        if poor_sleep and state in ("感到疲惫", "休息欠佳"):
            contextual_last_night = self.awaiting_followup and self.health_state == "感到疲惫" and "昨晚" in self._current_followup
            if "昨晚" in positive or contextual_last_night:
                detail = "昨晚休息欠佳"
            else:
                detail = "休息不足（时间未说明）" if "睡够" in positive or "睡得少" in positive else "休息欠佳（时间未说明）"
        return state, detail, tuple(states[1:]), denied

    def _detail(self, text: str, state: Optional[str]) -> Optional[str]:
        positive, _ = _affirmed(text)
        if state in ("感到疲惫", "休息欠佳"):
            contextual_last_night = self.awaiting_followup and "昨晚" in self._current_followup
            if "昨晚" in positive or contextual_last_night:
                if _SLEEP_POOR.search(positive):
                    return "昨晚休息欠佳"
                if _SLEEP_GOOD.search(positive) and not re.search(r"不(?:是|算|太)?(?:睡|休息)|没(?:有)?(?:睡|休息)", positive):
                    return "昨晚休息良好"
        elif state == "心情低落":
            positive = re.sub(r"(?:不是|没有|不)(?:想家|想孩子|想孙[子女]?|想念家人)", "", positive)
            if any(word in positive for word in ("想家", "想孩子", "想孙", "想念家人")):
                return "想念家人"
        elif state == "腰部不适":
            positive = re.sub(r"(?:不是|没有|没)(?:好几天|几天了|一直|很久|今天)", "", positive)
            if any(word in positive for word in ("好几天", "几天了", "一直", "很久")):
                return "腰部不适已持续多日"
            today_answer = self.awaiting_followup and "今天才开始" in self._current_followup
            if ("今天" in positive and today_answer) or re.search(r"今天(?:才|刚)|刚刚|刚开始|从今天", positive):
                return "腰部不适今天出现"
            if self.awaiting_followup and "今天才开始" in self._current_followup and re.fullmatch(r"(?:是|是的|对|对的|嗯)[。！!，,]*", positive):
                return "腰部不适今天出现"
        elif state == "状态良好":
            positive = re.sub(r"(?:不想|不愿|不喜欢|不要|不去)(?:去)?(?:散步|听音乐|下棋|聊天|看书)", "", positive)
            activity = next((word for word in _ACTIVITIES if word in positive), None)
            if activity:
                return f"想{activity}"
        return None

    def _choice_reply(self, text: str) -> Optional[str]:
        """Acknowledge our own explicit choice without inventing a health fact."""
        if not self.awaiting_followup or _CONTEXTUAL.search(text):
            return None
        if "休息一会" in self._current_followup or "歇一会" in self._current_followup:
            if re.search(r"(?:想|要|先|准备|去)(?:先)?(?:休息|歇)", text) and not re.search(r"不(?:想|要)(?:先)?(?:休息|歇)", text):
                return "好的，您先安心歇一会儿，我就不多打扰了。"
            if re.search(r"(?:想|要|愿意|陪我)(?:先|和你)?聊", text) and not re.search(r"不(?:想|愿意|要).*聊", text):
                return "好呀，我陪您聊。您想聊点什么？"
            if "歇一会" in self._current_followup and re.fullmatch(r"(?:是|是的|对|好|好的|想)[。！!]*", text):
                return "好的，您先安心歇一会儿，我就不多打扰了。"
        if "聊聊家人" in self._current_followup and re.fullmatch(r"(?:愿意|可以|好|好的|想聊)[。！!]*", text):
            return "好呀，您想先说说哪位家人？"
        return None

    def needs_semantic(self, utterance: str) -> bool:
        """Read-only gate: use a bounded classifier only for ambiguous turns."""
        text = _clean(utterance)
        if not self.awaiting_health or not text:
            return False
        if self._is_recall_question(text) or self.body_memory.is_recall(text) or _TOPIC.search(text) or _declines(text) or _THANKS.fullmatch(re.sub(r"[，,。！!]", "", text)) or _RESUME.search(text) or self._choice_reply(text):
            return False
        state, detail, _, _ = self._observation(text)
        return state is None and detail is None

    def _close(self, text: str, emotion: Optional[str] = None, *, farewell: bool = True) -> HealthReply:
        self.awaiting_health = self.awaiting_followup = False
        self._suspended = None
        closing = (self._closing or "有需要随时叫我。") if farewell else ""
        if emotion is None and self.health_state:
            emotion = _STATES[self.health_state][3]
        return HealthReply(text + closing, emotion)

    def _decline(self) -> HealthReply:
        return self._close("没关系，不想说也可以，等您愿意聊时我都在。", "love")

    def _handoff_to_general(self) -> None:
        if self.awaiting_health:
            self._suspended = (self.awaiting_followup, self.clarifications)
        self.awaiting_health = self.awaiting_followup = False
        self._handoff = (
            "\n长者当前提出了新的请求，健康问询已暂停。请优先处理这条请求，"
            "不要把它当作上一轮健康问题的回答，不要重复开场或擅自补写健康信息。"
            "未实际完成的提醒、报名或操作，不得声称已完成。")
        return None

    def _handoff_followup(self) -> None:
        """Let free-form explanations be answered using the dialogue history.

        Preserve confirmed facts and the pending question for an explicit resume;
        an unclassified answer is not a failure to hear the person's audio.
        """
        question = self._current_followup
        self._handoff_to_general()
        self._handoff = (
            "\n当前是健康问询的第二轮补充交流，上一句机器人问：" + question +
            "\n请结合对话历史，先回应长者这次具体说的内容。短回答要结合上一问理解。"
            "这是已识别的文字，不要用‘没听清’代替理解，不要说‘我按您的情况记录了’。"
            "如果确实不明确，只问一个贴近上一问的简短澄清问题；"
            "若长者已经解释清楚，就温和回应并自然收尾，不要重新问今天感觉如何。"
            "若长者愿意继续聊或主动提问，继续接话，不要强行告别。"
            "不要猜测未说出的经历、健康状态或病因，也不要承诺未执行的服务。")
        return None

    def _set_observation(self, state: str, detail: Optional[str], others=(), denied=False):
        self.health_state = state
        self.health_detail = detail
        self._other_states = others
        self._reported_denial = denied and state == "状态良好"
        self._closing = _STATES[state][2]

    def _remembered_reply(self, utterance="") -> HealthReply:
        area = self.body_memory.requested_area(utterance)
        if area:
            note = self.body_memory.spoken(area=area)
            return HealthReply((note + "。") if note else "我当前保存的记录里没有这部分的明确描述，您可以再告诉我一下吗？")
        covered = ("腰",) if "腰部不适" in (self.health_state, *self._other_states) else ()
        notes = self.body_memory.spoken(exclude=covered)
        if self.health_state is None:
            if notes:
                return HealthReply(notes + "。")
            return HealthReply("您还没有告诉我今天感觉如何；如果愿意，现在可以和我说说。")
        state_text = _SPOKEN_STATES[self.health_state]
        if self._reported_denial:
            state_text = "您说明刚才提到的不适并不存在，我不会把否定的话当作症状"
        others = "".join("；" + _SPOKEN_STATES[state] for state in self._other_states)
        detail = "，" + _SPOKEN_DETAILS[self.health_detail] if self.health_detail else ""
        return HealthReply("我记得，" + state_text + others + detail + "。" + (notes + "。" if notes else ""))

    def respond(self, utterance: str, interpretation: Optional[Mapping] = None) -> Optional[HealthReply]:
        text = _clean(utterance)
        self._handoff = ""
        if not text:
            return None
        if self._is_recall_question(text) or self.body_memory.is_recall(text):
            return self._remembered_reply(text)
        self.body_memory.observe(text)
        if _RESUME.search(text) and self._suspended is not None:
            self.awaiting_followup, self.clarifications = self._suspended
            self.awaiting_health = True
            self._suspended = None
            question = self._current_followup if self.awaiting_followup and self.health_state else "您今天感觉怎么样？"
            return HealthReply("好的，我们接着聊。" + question)
        if _TOPIC.search(text):
            return self._handoff_to_general()
        if _declines(text):
            return self._decline() if self.awaiting_health else None

        state, detail, others, denied = self._observation(text)
        if interpretation:
            intent = interpretation.get("intent")
            if intent == "other":
                return self._handoff_to_general()
            if intent == "recall":
                return self._remembered_reply(text)
            if intent == "decline":
                return self._decline() if self.awaiting_health else None
            if intent == "health" and interpretation.get("state") in _STATES:
                state = interpretation["state"]
                detail = interpretation.get("detail")
                if detail not in _SPOKEN_DETAILS:
                    detail = None
                others = ()
            elif intent == "unknown":
                # A conservative classifier result must never fall through to
                # a keyword guess that the caller asked it to disambiguate.
                state, detail, others, denied = None, None, (), set()

        if (_CORRECTION.search(text) and self.health_state and detail and
                (state is None or state == self.health_state or
                 (state == "休息欠佳" and self.health_state == "感到疲惫"))):
            self.health_detail = detail
            self._closing = _STATES[self.health_state][2]
            return self._close("谢谢您更正，是" + _SPOKEN_DETAILS[detail] + "。")

        if not self.awaiting_health:
            if not state:
                return None
            self.awaiting_health = True
            self.awaiting_followup = False
            self.clarifications = 0
            self._suspended = None
        if _THANKS.fullmatch(re.sub(r"[，,。！!]", "", text)) and state is None and detail is None and not self._choice_reply(text):
            return self._close("不客气，您愿意的时候我们再聊。")

        if self.awaiting_followup:
            choice_reply = self._choice_reply(text)
            if choice_reply:
                return self._close(choice_reply, farewell=not choice_reply.endswith("？"))
            previous = self.health_state
            # A sleep answer to the tired question explains the existing state,
            # rather than incorrectly replacing fatigue with a different state.
            if state == "休息欠佳" and previous == "感到疲惫" and detail:
                state = previous
            # A secondary symptom can be corrected without replacing the
            # primary one. Keep only explicitly affirmed, non-denied concerns.
            if denied:
                self._other_states = tuple(x for x in self._other_states if x not in denied)
            if state == previous and others:
                self._other_states = tuple(dict.fromkeys(self._other_states + others))
            if state and state != previous:
                if (previous not in denied and not _CORRECTION.search(text)
                        and previous != "状态良好" and state != "状态良好"):
                    others = tuple(dict.fromkeys((previous,) + self._other_states + others))
                    others = tuple(x for x in others if x != state and x not in denied)
                self._set_observation(state, detail, others, bool(denied))
                empathy = _STATES[state][0]
                return self._close(empathy, _STATES[state][3])
            if detail:
                self.health_detail = detail
                lead = {
                    "昨晚休息欠佳": "原来昨晚没休息好。今天累的话，就先歇一会儿。",
                    "昨晚休息良好": ("昨晚休息得还不错，不过您今天还是觉得累，就先放慢节奏吧。"
                                 if self.health_state == "感到疲惫" else "知道了，您昨晚休息得还不错。"),
                    "想念家人": "想念家人时，心里可能会难受。我愿意陪您聊聊。",
                    "腰部不适已持续多日": "已经不舒服几天了，建议让医护人员了解一下。",
                    "腰部不适今天出现": "我知道了，是今天才开始不舒服。",
                    "想散步": "想去散散步呀，按您舒服的节奏就好。",
                    "想听音乐": "听听喜欢的音乐也挺好。",
                    "想下棋": "找人下下棋，聊聊天，挺有意思的。",
                    "想聊天": "好呀，我陪您聊。您想从什么说起？",
                    "想看书": "好呀，您慢慢看，累了就歇一会儿。",
                }.get(detail, "您说休息得不太好，今天就先别太赶了。")
                if detail == "想聊天":
                    return self._close(lead, "happy", farewell=False)
                return self._close(lead)
            if state:
                if interpretation:
                    return self._handoff_followup()
                return self._close(_STATES[state][0], _STATES[state][3])
            return self._handoff_followup()

        if state:
            self._set_observation(state, detail, others, bool(denied))
            empathy, followup, _, emotion = _STATES[state]
            if detail in ("昨晚休息欠佳", "昨晚休息良好") and state == "感到疲惫":
                followup = "您现在想先休息一会儿，还是想和我聊聊天？"
            elif detail and state == "腰部不适":
                if detail == "腰部不适已持续多日":
                    empathy += "已经不舒服几天了，建议让医护人员了解一下。"
                followup = "现在您想先歇一会儿吗？"
            elif detail == "想念家人" and state == "心情低落":
                followup = "您愿意和我聊聊家人吗？"
            if self.clarifications:
                return self._close(empathy, emotion)
            self.awaiting_followup = True
            self._current_followup = followup
            return HealthReply(empathy + followup, emotion)
        if self.clarifications == 0:
            self.clarifications = 1
            return HealthReply("我想多关心一下您：今天是身体有些不舒服，还是心情不太好？您也可以说暂时不想聊。")
        return self._close("我还没听清您的状态，就先不追问了。之后您愿意时可以再告诉我。")

    def memory_context(self) -> str:
        if not self.health_state:
            return self.body_memory.context()
        states = "、".join((self.health_state,) + self._other_states)
        detail = f"补充信息：{self.health_detail}。" if self.health_detail else ""
        denial = "此状态来自长者否认不适，不能推断其他身体情况。" if self._reported_denial else ""
        return ("\n本次会话迎宾问询记录的长者状态：" + states + "。" + detail + denial +
                "这是长者自述，不是诊断；不要推断药物、原因或未说明的时间。" + self.body_memory.context())

    def handoff_context(self) -> str:
        return self._handoff

    def semantic_context(self) -> str:
        question = "您今天感觉怎么样？"
        if self.awaiting_followup and self.health_state:
            question = self._current_followup or _STATES[self.health_state][1]
        return f"当前机器人问题：{question}\n健康问询是否进行中：{self.awaiting_health}" + self.memory_context()
