"""Output-side review triggers, not a symptom classifier or medical decision engine.

The LLM performs the semantic revision. Rules only identify drafts worth checking
and retain verbatim questions with the following user answer (not inferred facts).
"""
import re
from difflib import SequenceMatcher

ADVICE_PATTERNS = (r"规律.{0,4}(?:睡眠|作息)", r"睡前.{0,8}放松",
                   r"(?:安静|昏暗).{0,5}睡眠环境|睡眠环境.{0,8}(?:安静|昏暗)",
                   r"保持同一姿势", r"(?:维持|保持).{0,4}日常活动",
                   r"(?:久卧|长时间卧床)", r"阅读.{0,2}听音乐")

_NECK_BACK_SYMPTOM = re.compile(r"(?:脖子|颈|腰|背)[^，,。！？!?]{0,12}(?:疼|痛|酸|不舒服|难受)")
_INJURY_CLEARED = re.compile(r"(?:没有|没|未曾|并未)(?:摔倒|摔过|跌倒|扭伤|受伤|外伤)|不是(?:摔倒|扭伤|外伤)")
_SELF_CARE_AFTER_INJURY = re.compile(
    r"(?:避免|别|不要).{0,10}保持同一姿势|(?:维持|保持).{0,6}日常活动|"
    r"(?:避免|别|不要).{0,8}(?:久卧|长时间卧床)|(?:枕头|趴睡|扭转颈部)")
_INJURY_CAUTION = re.compile(
    r"(?:若|如果|如有|一旦).{0,24}(?:摔倒|跌倒|扭伤|外伤|受伤).{0,36}(?:医护|就医|医生|医院)")


def unconfirmed_injury_advice(reply, utterance, turns):
    """Flag unqualified routine neck/back advice; never select an answer.

    When injury history is unknown, general advice may be delivered without a
    follow-up question if it also gives an explicit injury-related care boundary.
    """
    recent_user = " ".join(t.get("user", "") for t in turns[-4:]) + " " + utterance
    injury_asserted = bool(re.search(r"摔倒|跌倒|扭伤|受伤|外伤",
                                      _INJURY_CLEARED.sub("", recent_user)))
    return (bool(_NECK_BACK_SYMPTOM.search(recent_user))
            and (injury_asserted or not _INJURY_CLEARED.search(recent_user))
            and bool(_SELF_CARE_AFTER_INJURY.search(reply))
            and (injury_asserted or not _INJURY_CAUTION.search(reply)))


def unwanted_injury_followup(reply, utterance, turns):
    """Do not turn ordinary neck/back discomfort into an injury interview."""
    recent_user = " ".join(t.get("user", "") for t in turns[-4:]) + " " + utterance
    if not _NECK_BACK_SYMPTOM.search(recent_user):
        return False
    return any(re.search(r"(?:摔倒|跌倒|扭伤|受伤|外伤)", question)
               for question in questions(reply))


def questions(text):
    sentences = re.findall(r"[^。！？!?\n]+[。！？!?]?", text)
    # Requests for the same information can be phrased as commands, not only '?'.
    found = []
    for s in sentences:
        if s.endswith(("？", "?")):
            found.append(s.strip())
        else:
            found.extend(m.group().strip() for m in re.finditer(
                r"(?:请|麻烦|建议|先)[^，,。]{0,10}(?:说明|告诉|确认|告知)[^，,。]{0,15}(?:是否|有没有)"
                r"[^，,。！？!?]*(?:[，,]以便[^。！？!?]*)?[。]?", s))
    return found


def question_history(turns, current_user=None):
    rows = []
    for i, turn in enumerate(turns):
        for question in questions(turn.get("assistant", "")):
            rows.append({"question": question,
                         "following_user_quote": turns[i + 1]["user"] if i + 1 < len(turns) else current_user})
    return rows[-8:]


def _normalized(text):
    text = re.split(r"以便|这样才能", text)[0]
    text = re.sub(r"请问|请|麻烦|建议|先|告知|告诉|说明|确认|您|你|近期|最近|呢|呀|哦|一下|情况|有没有|是否|或者|或|有|过|的", "", text)
    return re.sub(r"\W", "", text)


def repeated_question(reply, turns):
    old = [r["question"] for r in question_history(turns)]
    return any(SequenceMatcher(None, _normalized(q), _normalized(p)).ratio() >= .60
               or (len(_normalized(p)) >= 4 and _normalized(p) in _normalized(q))
               for q in questions(reply) for p in old if _normalized(q) and _normalized(p))


def review_flags(result, turns, utterance=""):
    if result["intent"] not in {"health", "other", "correction", "recall"}:
        return []
    reply = result["reply"]
    if "[[" in reply:
        return []
    flags = []
    if ("疲惫" in utterance or "累" in utterance) and result["intent"] in {"health", "other"}:
        spoken = reply.strip()
        if spoken.endswith(("？", "?")) and not re.search(r"[。！!]", spoken):
            flags.append("fatigue_question_without_practical_tip")
    if (re.search(r"[一二两三四五六七八九十0-9]+\s*(?:天|周|星期|个月)", utterance)
            and turns and "疲惫" in reply and re.search(r"腰|脖子|颈", turns[-1].get("user", ""))
            and not re.search(r"疲惫|累", turns[-1].get("user", ""))
            and not re.search(r"疲惫|累", utterance)):
        flags.append("duration_spread_to_older_symptom")
    if repeated_question(reply, turns):
        flags.append("possibly_repeated_question")
    # Only review asserted severity. Conditional warnings and questions must not
    # consume the sole retry slot: a failed review used to produce an apology.
    severity_clauses = re.split(r"[。！？!?；;]", reply)
    if any(re.search(r"突然|迅速|剧烈|严重|急剧|快速|加重|更疼|更痛", clause)
           and not re.search(r"如果|若|一旦|是否|有没有|会不会|不|没|尚未", clause)
           for clause in severity_clauses):
        flags.append("check_severity_against_user_quotes")
    # The model remains responsible for rephrasing; this only spots near-verbatim
    # re-delivery of multiple advice points when the visitor added new facts.
    if turns and not re.search(r"再说|重复|怎么缓解|给.*建议|怎么办", utterance):
        previous = " ".join(t.get("assistant", "") for t in turns[-2:])
        overlap = sum(bool(re.search(pattern, previous) and re.search(pattern, reply))
                      for pattern in ADVICE_PATTERNS)
        if overlap >= 2:
            flags.append("repeated_advice_ignores_new_information")
    return flags


def suppress_repeated_question(result, turns, utterance):
    """Last-resort output guard after generation; never invents health advice.

    An explicit request to repeat is allowed. Safety advice outside the repeated
    question is preserved. This is not a clinical/semantic proof of correctness.
    """
    if result["intent"] not in {"health", "other", "correction", "recall"}:
        return result
    if re.search(r"没听清|没听到|再(?:说|问)一遍|重复.{0,6}(?:问题|问一遍|说一遍)", utterance):
        return result
    reply = result["reply"]
    # Remove a complete sentence, never leave a dangling '或者/以便' clause.
    for sentence in re.findall(r"[^。！？!?\n]+[。！？!?]?", reply):
        if repeated_question(sentence, turns):
            reply = reply.replace(sentence, "")
    if reply == result["reply"]:
        return result
    reply = re.sub(r"[，,]+(?=[，,。])|^[，,]+", "", reply).strip()
    if not reply:
        reply = "目前的信息还不够，我不能贸然推荐具体处理办法，可以请现场医护帮您确认适合的方式。"
    return {**result, "reply": reply, "intent": "other", "action": "continue", "gesture": None}


def suppress_repeated_advice(result, turns, utterance):
    """Drop only previously spoken advice clauses, retaining new user facts."""
    if "repeated_advice_ignores_new_information" not in review_flags(result, turns, utterance):
        return result
    previous = " ".join(t.get("assistant", "") for t in turns[-2:])
    repeated = [pattern for pattern in ADVICE_PATTERNS
                if re.search(pattern, previous) and re.search(pattern, result["reply"])]
    clauses = re.findall(r"[^，。；]+[，。；]?", result["reply"])
    cleaned = "".join(part for part in clauses if not any(re.search(pattern, part) for pattern in repeated))
    cleaned = re.sub(r"^[，。；]+|，[，。；]+", "", cleaned).strip().rstrip("，；")
    cleaned = cleaned.replace("，若", "。若").replace("，如果", "。如果")
    if len(cleaned) < 18 or cleaned.endswith(("的话", "的话。", "比如", "例如")):
        prior_user = " ".join(t.get("user", "") for t in turns[-2:])
        duration = re.search(r"[一二两三四五六七八九十0-9]+\s*(?:天|周|星期|个月)", utterance)
        if (result.get("intent") == "health" and result.get("action") == "close"
                and duration and turns and re.search(r"疲惫|累", turns[-1].get("user", ""))
                and "多久" in turns[-1].get("assistant", "")):
            return {**result, "reply": "听您说这种疲惫持续了" + duration.group() + "。今天先照顾好自己，有需要再叫我。"}
        if (result.get("intent") == "health" and result.get("action") == "close"
                and "疲惫" in prior_user and "影响日常活动" in utterance):
            return {**result, "reply": "听您说疲惫已经有一点影响日常活动。如果继续影响生活，建议和医护聊聊。今天先照顾好自己，有需要再叫我。"}
        return result
    if not cleaned:
        return result
    if cleaned[-1] not in "。！？?":
        cleaned += "。"
    return {**result, "reply": cleaned}


REVIEW_PROMPT = """
现在执行一次语义复核并重新输出完整五字段JSON，重新依据用户原话回答。
若只说“一两天”且最近谈的是腰颈不适，不要把这个时长也加到更早的疲惫；只承接最近明确的话题，必要时用一句话确认时长指什么。
如果quality_review包含repeated_advice_ignores_new_information：上一轮已经给过的做法不要再念一遍。先回应本轮新增事实（如“有一点影响日常活动”“持续一两天”），再用一句新的、适用的提醒或一个尚未问过的重点问题推进。
recent_assistant_replies仅用来检查措辞重复，绝不能作为用户自述或已核实病情。
如果用户只说疲惫，先从care_reference给一项不依赖病因的生活提示，再问一个相关问题；不要只有问句。若用户新提腰颈酸痛，优先回应新不适。
question_history是已问问题与紧随其后的用户原话，问题提到的症状或外伤不等于用户已经回答了它。
只以当前及历史用户原话支持事实；机器人的旧回答、资料中的危险信号、假设、否认不是用户肯定自述。
逐项区分部位、强度、速度、时间：只说“加重”只能概括为加重，速度和程度仍未知；
不能添加突然/迅速/剧烈/严重，也不能把某一个部位加重扩展成所有部位一起加重。
用户说“不是突然，只是比刚才酸一点”时采用纠正，不能继续称突然剧痛。
“脖子没变”表示之前的脖子不适仍在，不等于脖子好了或没有不适。
只否认突然/剧烈不等于否认双腿麻木无力等其他危险信号；未提到的保持未知。
禁止笼统声称“没有危险信号”“没有其他不适”，也不要替用户确认没有受伤。
条件句“如果突然剧痛”是风险提示，不代表已发生；若本轮没有必要，不重复这些条件句。
用户已明确突然剧痛等资料要求求助的情况，保留及时求助提示，不能为避免夸大而删掉真正的风险。

检查是否已问过相同信息，语义相同的换词仍算重复：
- 已回答：承接答案，不再问一遍，必要时提供适用资料提示。
- 未回答而继续问怎么缓解：本轮不再问同一个问题，也不改成命令要求其回答；
  用一句说明尚缺哪些信息、为何暂不能给特定方法。可提供不依赖这些未知条件的适用提示，
  没有适用提示则如实说明并建议现场医护协助，不能假设排除了危险或编造新疗法。
- 明确要求复述/没听清，或真正新的症状需要重新确认时，可以必要地重问，但说明缘由。
不要用“您已经加重了吗”重问已确定的事实。未知程度若首次询问可只问一个重点。
不要为了复核增加与当前需求无关的症状追问。实际紧急求助时gesture=null。
表情动作仍由你选择。返回完整五字段JSON，不输出审查说明、分析、额外字段或舞台旁白。
"""
