"""Stage-four dining feedback: model extraction, confirmed local records."""
from datetime import datetime, timedelta, timezone
import html
import json
import os
from pathlib import Path
import re
import uuid

LOCAL_TIME = timezone(timedelta(hours=8))
DEFAULT_RECORDS = Path(__file__).resolve().parents[1] / "data" / "dining_feedback.jsonl"
PLAN = re.compile(r"^\[\[DINING_(PREPARE|CONFIRM|CANCEL)(?:\|([^\]\n]*))?\]\]$")
KINDS = {"taste": "口味意见", "dish_request": "想吃的菜", "service": "食堂服务", "other": "其他意见"}
CONFIRM = re.compile(r"\s*(?:确认(?:提交)?|提交(?:吧)?|好(?:的)?(?:，?提交吧)?|可以(?:提交)?|是的|没错|对(?:的)?|嗯，?提交吧|(?:要|请|帮我)?(?:记录|记下|记入)(?:吧|一下)?)\s*[，。！!]?\s*")

DINING_PROMPT = """
环节四食堂意见收集：只有用户明确谈社区食堂的口味、饭菜、想吃的菜或服务反馈时，才使用intent=dining/action=continue。
不要把健康问询、药品服法、饮水提醒或普通闲聊误判为食堂意见；涉及用药或急迫健康求助时优先处理健康需求。不要建议具体疾病饮食疗法。
只问“今天食堂有什么菜”等信息、没有表达意见时，使用other；没有菜单资料不要编造菜品。没有pending_dining时，单独说“确认”也不是食堂确认。
reply只输出一个标记；emotion/gesture仍根据语义从capabilities选择或null：
[[DINING_PREPARE|类别|菜品|感受|期望]]：类别只能是taste/dish_request/service/other。
菜品、感受、期望分别从本轮用户原话中逐字摘取短片段；不适用时填-或留空，不得编造或补充用户未说过的原因。
描述程度要照原话：“有点咸”不能升级为“太咸”。
老人只说“今天的菜”时，不要沿用先前记录里的“汤”“青菜”等具体菜名。
“期望”只能填写希望食堂采取的改变（如“少放盐”），不能把“今天的汤有点咸”这样的现状填成期望。
例：用户说“食堂青菜太咸，下次少放盐”→[[DINING_PREPARE|taste|青菜|太咸|少放盐]]。
例：用户说“食堂想吃清蒸鱼”→[[DINING_PREPARE|dish_request|清蒸鱼|-|想吃清蒸鱼]]。
补充或更正待提交的意见时，重新PREPARE；可以保留pending_dining中用户未否定的片段。用户说“不是青菜，是汤太咸”时应改为汤。
若pending_dining.stage=await_item_clarification，说明菜名尚未核准；用户重新说出菜名后用PREPARE，可保留先前未撤回的“少放盐”等期望，不能直接CONFIRM。
[[DINING_CONFIRM]]：仅当pending_dining正在等待确认，且本轮用户明确同意提交。
[[DINING_CANCEL]]：用户明确取消待提交意见。
尚未确认时不能说已经登记；确认后程序负责写本地食堂反馈表并给出答复。不要承诺食堂已采纳、已改菜单或数据已发送到外部系统。
其他任务仍返回原五字段JSON，不输出DINING标记。
"""


def _field(value):
    if value in ("-", ""):
        return ""
    if (not isinstance(value, str) or not 1 <= len(value) <= 50 or
            re.search(r"[|\[\]\r\n\x00-\x1f]", value)):
        raise ValueError("invalid dining field")
    return value.strip()


def _desired_change(request):
    """A complaint alone is not an instruction for the kitchen."""
    return bool(re.search(r"少|减|别|不要|不再|淡|清淡|改|调|注意|增加|想吃|多放|换|改善|适中|加点|更换", request))


def _grounded_observation(observation, utterance):
    """Keep the model's taste topic, but restore the visitor's exact degree."""
    if observation in utterance:
        return observation
    for taste in ("咸", "甜", "辣", "淡", "酸", "苦"):
        if taste in observation:
            found = re.search(r"(?:有点|有些|太|偏|比较|稍微)?" + taste + r"(?:了)?", utterance)
            if found and not re.search(r"(?:不|没)" + taste, utterance):
                return found.group()
    return observation


def _grounded_request(request, utterance):
    if request in utterance:
        return request
    if "少放" in request and "盐" in request:
        found = re.search(r"少放(?:一点|点)?盐", utterance)
        if found:
            return found.group()
    return request


def prepare_transition(reply, pending, utterance):
    """Model selects an operation; all recorded fragments must be user-evidenced."""
    match = PLAN.fullmatch(reply.strip())
    if not match:
        return None, "dining_invalid_token"
    op, args = match.groups()
    pending = pending if isinstance(pending, dict) else {}
    if op in {"CONFIRM", "CANCEL"} and args is not None:
        return None, "dining_invalid_arguments"
    if op == "CANCEL":
        return {"reply": "好的，这条食堂意见先不提交。", "pending": None}, None
    if op == "CONFIRM":
        if pending.get("stage") != "await_confirm" or not pending.get("request_id"):
            return None, "dining_confirmation_without_pending"
        if not CONFIRM.fullmatch(utterance):
            return None, "dining_confirmation_not_explicit"
        record = {"id": pending["request_id"], "category": pending["category"],
                  "item": pending["item"], "observation": pending["observation"],
                  "request": pending["request"], "source": "voice_confirmed",
                  "status": "new", "demo": True}
        return {"reply": "好的，已经记入食堂反馈表了。",
                "pending": None, "save": record}, None
    if op != "PREPARE" or args is None:
        return None, "dining_invalid_arguments"
    parts = args.split("|")
    if len(parts) != 4 or parts[0] not in KINDS:
        return None, "dining_invalid_arguments"
    try:
        fields = [_field(part) for part in parts[1:]]
    except ValueError:
        return None, "dining_invalid_field"
    item, observation, request = fields
    if item and item not in utterance and item != pending.get("item") and parts[0] == "taste":
        generic_item = re.search(r"今天的菜|食堂的菜|饭菜", utterance)
        if generic_item:
            item = generic_item.group()
    if observation:
        observation = _grounded_observation(observation, utterance)
    if request:
        request = _grounded_request(request, utterance)
    fields = [item, observation, request]
    if not any(fields):
        return None, "dining_empty_feedback"
    for field in fields:
        if field and field not in utterance and field not in (pending.get("item"), pending.get("observation"), pending.get("request")):
            return None, "dining_unsupported_detail"
    corrected_to = utterance.rsplit("是", 1)[-1] if "不是" in utterance else ""
    for contradicted in re.findall(r"不是(.{1,25}?)(?:，|,|。|是|而是)", utterance):
        if any(field and field in contradicted and field not in corrected_to for field in fields):
            return None, "dining_correction_not_applied"
    if parts[0] == "taste" and item == "糖" and "咸" in observation and "汤" not in utterance:
        clarification = {**pending, "stage": "await_item_clarification", "item": ""}
        return {"reply": "菜名可能听错了。您说的是‘汤’吗？请再说一遍菜名。",
                "pending": clarification}, None
    if parts[0] in {"taste", "service", "other"} and request and not _desired_change(request):
        request = ""
    new_pending = {"stage": "await_confirm", "request_id": pending.get("request_id") or uuid.uuid4().hex,
                   "category": parts[0], "item": item, "observation": observation, "request": request}
    if parts[0] == "dish_request":
        summary = f"您希望食堂考虑增加{item or request}。"
    elif item and observation:
        summary = f"您觉得{item}{observation}。"
    elif observation:
        summary = f"您反馈食堂{observation}。"
    elif item:
        summary = f"您对{item}提出了意见。"
    else:
        summary = f"您提出了食堂{KINDS[parts[0]]}。"
    if request and parts[0] != "dish_request":
        summary += f"希望{request}。"
    return {"reply": summary + "要记入食堂反馈表吗？", "pending": new_pending}, None


def save_feedback(record, path=None):
    """Persist only after confirmation; retry with the same request ID is safe."""
    path = Path(path) if path else DEFAULT_RECORDS
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.stat().st_size > 2_000_000:
            raise ValueError("feedback register full")
        for line in path.read_text(encoding="utf-8").splitlines():
            if json.loads(line).get("id") == record["id"]:
                return
    saved = {**record, "submitted_at": datetime.now(LOCAL_TIME).isoformat()}
    with path.open("a", encoding="utf-8", newline="\n") as out:
        out.write(json.dumps(saved, ensure_ascii=False) + "\n")
        out.flush()
        os.fsync(out.fileno())


def load_feedback(path=None):
    path = Path(path) if path else DEFAULT_RECORDS
    if not path.exists():
        return []
    if path.stat().st_size > 2_000_000:
        raise ValueError("feedback register full")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def render_dashboard(records):
    """Read-only, escaped local table for showing the data-flow result."""
    columns = (("submitted_at", "提交时间"), ("category", "类别"), ("item", "菜品/对象"),
               ("observation", "感受/问题"), ("request", "期望"), ("status", "状态"))
    rows = []
    for record in reversed(records[-200:]):
        cells = []
        for key, _ in columns:
            value = KINDS.get(record.get(key), record.get(key, "")) if key == "category" else record.get(key, "")
            cells.append("<td>" + html.escape(str(value)) + "</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    head = "".join("<th>" + label + "</th>" for _, label in columns)
    return ("<!doctype html><html lang=zh-CN><meta charset=utf-8><title>社区食堂反馈表</title>"
            "<style>body{font:18px sans-serif;margin:32px;background:#f7f8fa;color:#203040}"
            "table{border-collapse:collapse;width:100%;background:white}td,th{padding:14px;border:1px solid #ccd3dd;text-align:left}"
            "th{background:#e5eef9}caption{text-align:left;font-size:28px;font-weight:bold;margin-bottom:18px}</style>"
            "<table><caption>社区食堂反馈表（本地演示记录）</caption><thead><tr>" + head + "</tr></thead><tbody>" +
            ("".join(rows) if rows else "<tr><td colspan=6>尚无已确认的意见</td></tr>") +
            "</tbody></table></html>")
