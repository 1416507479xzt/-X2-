"""Clock-derived reminder context and optional grounded speech fragments.

No scheduler, implicit completion, persistent writes or patient identification.
"""
import math
import re
from datetime import datetime

REMINDER_PROMPT = """
用户查询、讨论、修改提醒安排时intent=reminder，action=continue，不要用other。
reply必须且只能选择一个标记：[[REMINDER_NEXT]]查下一项，[[REMINDER_REMAINING]]查今天还有什么/接下来做什么，
[[REMINDER_TODAY]]查询今天的安排、全部安排，或答应核对之前的安排，
[[REMINDER_MEDICATION]]查服药时间，[[REMINDER_APPOINTMENT]]查复诊时间，[[REMINDER_WATER]]查喝水时间，[[REMINDER_CHANGE_UNSUPPORTED]]请求修改或创建。
不添加标记以外的文字，程序会生成准确播报；表情动作仍由你选择。
pending_question是上一轮尚待回答的问题，优先结合它理解短答，不跳回旧的健康话题。
pending_question.kind=review_today时，“需要/可以/帮我核对”等接受请求用[[REMINDER_TODAY]]。
pending_question.kind=medication_taken时，明确自述已服用用[[REMINDER_TAKEN]]，
明确未服用用[[REMINDER_NOT_TAKEN]]，记不清用[[REMINDER_UNSURE]]；这些都是reminder/continue，
不是新的用药时间查询或普通acknowledge。只是用户自述，不是已核实服药或医嘱。
pending_question.kind=water_done时，用户明确说“已经喝过了”用[[REMINDER_WATER_DONE]]；
仅承接这次喝水提醒，不重新播报全天安排，不声称已更新外部记录。
用户另提新请求就处理新请求，不能把无关的“吃过饭了”当成已吃药。
单纯确认仍是acknowledge，健康问询仍是health，用药知识仍是other，不要误判为提醒。
健康提醒专项：reminder_summary和各事项的time_label/status/minutes_until由程序计算，不自行猜时间。
今天还有什么→优先今天已到点与未来事项，并顺带补充下一项；没有未来事项时说今天后续没有已配置事项，
不能说今天什么也没有。已过点但unknown的事项不等于完成或漏服。
下一项几点→优先用[[REMINDER_NEXT]]引用准确时间和名称，可加简短自然衔接，不重复整张表。
今天全部安排→可用[[REMINDER_TODAY]]，超过三项会明确尚有几项，不能假称已经全部读完。
due_now仅表示计划时间到了，不表示确认可以服药；upcoming表示未到点。
用户问该吃药了吗，只看kind=medication的安排，不能把喝水或社区活动当成用药安排；没有配置就如实说没有用药时间资料。
问喝水/复诊时同理，不把无记录当成用户没有这个需要。不同事项不要混用日期。
用户说做过了：可承接用户自述，但未写入记录，不能说已更新或永久记录；问还有什么时结合本段对话，
不要再催其自述已完成的同一项。询问明日同名事项不代表重复当天的事项。
简单“好的/知道了”只简短回应；没有新事项、用户主动询问或新风险，不重复追加提醒。
对话时可以主动补充is_soon=true的未来事项；不能在不适求助、拒绝交谈或告别时硬插提醒。
只有query_and_upcoming能力：没有定时器、事项修改、签到或服药确认工具，不能声称以后会到点开口、已登记或修改。
demo=true是后台数据属性，不把“（演示）”或状态字段读出来。这里只解释预设安排，不能声称是真实预约或个人医嘱。
status=unavailable是读取失败，不是没有安排。
表情和讲解动作由你选择，提醒要温和，不催促服药、不机械挥手。
"""


def annotate_reminders(today, future, now, lead_minutes=30):
    def annotate(row):
        due = datetime.fromisoformat(row["due_at"])
        days = (due.date() - now.date()).days
        day_label = "今天" if days == 0 else "明天" if days == 1 else due.strftime("%Y年%m月%d日")
        row["time_label"] = f"{day_label}{due.hour}点" + (f"{due.minute:02d}分" if due.minute else "整")
        row["minutes_until"] = math.ceil((due - now).total_seconds() / 60)
        row["is_soon"] = 0 < row["minutes_until"] <= lead_minutes
        row["completion"] = "unknown"
        row["occurrence_id"] = row["id"] + "@" + due.date().isoformat()
        return row
    today = [annotate(dict(r)) for r in today]
    future = [annotate(dict(r)) for r in future]
    remaining = [r for r in today if r["status"] in {"upcoming", "due_now"}]
    return {"today_reminders": today, "next_reminder": future[0] if future else None,
            "remaining_today": remaining, "upcoming_reminders": future,
            "reminder_summary": {"today_count": len(today), "remaining_today_count": len(remaining),
                "passed_unknown_count": sum(r["status"] == "passed_unknown" for r in today),
                "due_now_count": sum(r["status"] == "due_now" for r in today),
                "lead_minutes": lead_minutes, "completion_tracking": "not_supported"}}


def spoken_title(row):
    title = re.sub(r"[（(]演示[）)]", "", row["title"]).strip()
    return {"用药安排核对": "核对用药安排", "喝水提醒": "喝水", "复诊提醒": "复诊",
            "社区活动安排确认": "确认社区活动安排"}.get(title, title)


def medication_row(service):
    rows = [r for r in service.get("today_reminders", []) if r["kind"] == "medication"]
    active = [r for r in rows if r["status"] != "passed_unknown"]
    return active[0] if active else rows[-1] if rows else None


def category_row(service, kind):
    rows = [r for r in service.get("today_reminders", []) if r["kind"] == kind]
    active = [r for r in rows if r["status"] != "passed_unknown"]
    return active[0] if active else rows[-1] if rows else None


def reminder_transition(token, service, context):
    """Trusted session metadata; never an external medication record or instruction."""
    pending = context.get("pending_question") or {}
    if token == "[[REMINDER_WATER_DONE]]":
        rows = service.get("today_reminders", [])
        if (service.get("status") != "ready" or pending.get("kind") != "water_done"
                or not any(r["occurrence_id"] == pending.get("occurrence_id") and r["kind"] == "water" for r in rows)):
            return None, "reminder_confirmation_without_current_question"
        return {"pending_question": None,
                "self_report": {"occurrence_id": pending["occurrence_id"], "status": "done"}}, None
    if token in {"[[REMINDER_TAKEN]]", "[[REMINDER_NOT_TAKEN]]", "[[REMINDER_UNSURE]]"}:
        rows = service.get("today_reminders", [])
        if (service.get("status") != "ready" or pending.get("kind") != "medication_taken"
                or not any(r["occurrence_id"] == pending.get("occurrence_id") and r["kind"] == "medication" for r in rows)):
            return None, "reminder_confirmation_without_current_question"
        status = {"[[REMINDER_TAKEN]]": "taken", "[[REMINDER_NOT_TAKEN]]": "not_taken",
                  "[[REMINDER_UNSURE]]": "unsure"}[token]
        return {"pending_question": None, "self_report": {"occurrence_id": pending["occurrence_id"], "status": status}}, None
    next_question = None
    if token == "[[REMINDER_REMAINING]]" and service.get("status") == "ready" and not service.get("remaining_today"):
        next_question = {"kind": "review_today"}
    if token == "[[REMINDER_MEDICATION]]" and service.get("status") == "ready":
        row = medication_row(service)
        if row and row["status"] == "passed_unknown" and row["occurrence_id"] not in context.get("reminder_self_reports", {}):
            next_question = {"kind": "medication_taken", "occurrence_id": row["occurrence_id"]}
    if token == "[[REMINDER_WATER]]" and service.get("status") == "ready":
        row = category_row(service, "water")
        if row and row["status"] == "passed_unknown" and row["occurrence_id"] not in context.get("reminder_self_reports", {}):
            next_question = {"kind": "water_done", "occurrence_id": row["occurrence_id"]}
    return {"pending_question": next_question}, None


def expand_reminder_reply(reply, service, context=None):
    context = context or {}
    if reply == "[[REMINDER_WATER_DONE]]":
        return "好的，您说这次已经喝过水了。后续饮水按您的安排即可。"
    if reply == "[[REMINDER_TAKEN]]":
        return "既然您说已经服过这次药，就不要因为这条提醒再重复服用。"
    if reply == "[[REMINDER_NOT_TAKEN]]":
        return "您说这次还没服用，是否需要补服要看具体药品和医嘱，不能只凭提醒时间决定。请先让医护人员或药师帮您核对。"
    if reply == "[[REMINDER_UNSURE]]":
        return "记不清的话，先核对药盒、服药记录，或请照护人员帮忙确认，不要凭猜测再服一次。"
    if reply == "[[REMINDER_CHANGE_UNSUPPORTED]]":
        return "目前还不能通过语音新增或修改提醒，安排没有改变。请让服务人员修改提醒配置。"
    if reply in {"[[REMINDER_APPOINTMENT]]", "[[REMINDER_WATER]]"}:
        if service.get("status") != "ready":
            return "提醒资料暂时读取不到，现在不能确认安排，请联系服务人员核对。"
        kind = "appointment" if reply == "[[REMINDER_APPOINTMENT]]" else "water"
        row = category_row(service, kind)
        label = "复诊" if kind == "appointment" else "喝水"
        if not row:
            return f"我这里没有今天的{label}提醒时间，请向服务人员核对。"
        if kind == "water" and context.get("reminder_self_reports", {}).get(row["occurrence_id"]) == "done":
            return "您刚才说这次已经喝过水了，不用因为同一条提醒再喝一次。"
        text = f"今天的{label}提醒时间是{row['time_label']}。"
        if row["status"] == "passed_unknown":
            text += "这个时间已经过了，是否完成还需要您确认。"
        elif row["status"] == "due_now":
            text += "现在到提醒时间了。"
        else:
            text += "还没到这个时间。"
        if kind == "appointment" and service.get("demo"):
            text += "这只是预设提醒，具体复诊日期请以医院安排为准。"
        return text
    if reply == "[[REMINDER_MEDICATION]]":
        if service.get("status") != "ready":
            return "提醒资料暂时读取不到，现在不能确认服药安排，请联系服务人员核对。"
        row = medication_row(service)
        if not row:
            return "我这里没有您今天的用药时间，不能据此判断是否该服药，请核对医嘱和用药记录。"
        reported = context.get("reminder_self_reports", {}).get(row["occurrence_id"])
        if reported:
            return {"taken": "您刚才说今天这次药已经服过，不要因为提醒重复服用。",
                    "not_taken": "您刚才说这次还没服用，补服方法需要核对具体药品和医嘱，请让医护人员或药师确认。",
                    "unsure": "您刚才说记不清是否服过，请先核对服药记录或请照护人员确认，不要凭猜测重复服药。"}[reported]
        text = "今天的用药提醒时间是" + row["time_label"] + "。"
        if service.get("demo"):
            text += "这只是预设时间，实际服药请按医嘱。"
        if row["status"] == "passed_unknown":
            return text + "现在已经过了这个时间，您今天已经吃过药了吗？"
        if row["status"] == "due_now":
            return text + "现在到这个时间了，请先核对是否已经服用，避免重复。"
        return text + "现在还没到这个时间。"
    if not any(t in reply for t in ("[[REMINDER_NEXT]]", "[[REMINDER_TODAY]]", "[[REMINDER_REMAINING]]")):
        return reply
    if service.get("status") != "ready":
        return "提醒资料暂时读取不到，现在不能确认安排，请联系服务人员核对。"
    if "[[REMINDER_REMAINING]]" in reply:
        rows = service.get("remaining_today", [])
        if not rows:
            text = "今天接下来没有其他预设安排了。之前的事项有没有需要我帮您再核对一下的？"
        else:
            text = "接下来是" + "，然后".join(r["time_label"].removeprefix("今天") + spoken_title(r)
                                               for r in rows[:2]) + "。"
            if len(rows) > 2:
                text += f"后面还有{len(rows) - 2}项，您可以继续问我。"
            if rows[0].get("is_soon"):
                text += f"最近一项还有{rows[0]['minutes_until']}分钟。"
            if any(r["kind"] == "medication" for r in rows[:2]):
                text += "用药时间仅供核对，实际服药请按医嘱。"
        reply = reply.replace("[[REMINDER_REMAINING]]", text)
    if "[[REMINDER_NEXT]]" in reply:
        row = service.get("next_reminder")
        if not row:
            text = "我这里暂时没有后续安排，您可以请服务人员帮忙确认。"
        else:
            text = "下一项是" + row["time_label"] + spoken_title(row) + "。"
            if row.get("status") == "due_now":
                text += "现在已到计划时间。"
            elif row.get("is_soon"):
                text += f"还有{row['minutes_until']}分钟。"
            if row.get("kind") == "medication":
                text += "这只是时间安排，服药请核对医嘱和实际服用情况。"
        reply = reply.replace("[[REMINDER_NEXT]]", text)
    if "[[REMINDER_TODAY]]" in reply:
        rows = service.get("today_reminders", [])
        texts = [r["time_label"].removeprefix("今天") + spoken_title(r) for r in rows[:4]]
        text = "您今天有这些提醒：" + "，".join(texts) + "。" if texts else "今天暂时没有事项。"
        if any(r["status"] == "passed_unknown" for r in rows[:3]):
            text += "有些时间已经过了，您是否做过还需要确认。"
        if len(rows) > 4:
            text += f"另有{len(rows) - 4}项尚未展开。"
        next_row = service.get("next_reminder")
        if next_row and next_row.get("is_soon"):
            text += f"最近一项还有{next_row['minutes_until']}分钟。"
        elif next_row and not service.get("remaining_today"):
            text += "下一项预设提醒是" + next_row["time_label"] + spoken_title(next_row) + "。"
            if next_row["kind"] == "medication":
                text += "用药仍请按医嘱核对。"
        reply = reply.replace("[[REMINDER_TODAY]]", text)
    return re.sub(r"。{2,}", "。", reply)


REMINDER_TOKENS = {"[[REMINDER_NEXT]]", "[[REMINDER_TODAY]]", "[[REMINDER_REMAINING]]", "[[REMINDER_MEDICATION]]", "[[REMINDER_APPOINTMENT]]", "[[REMINDER_WATER]]", "[[REMINDER_WATER_DONE]]", "[[REMINDER_CHANGE_UNSUPPORTED]]"}
REMINDER_TOKENS.update({"[[REMINDER_TAKEN]]", "[[REMINDER_NOT_TAKEN]]", "[[REMINDER_UNSURE]]"})


def reminder_reply_error(result, utterance=""):
    if result["intent"] == "reminder" and result["reply"] not in REMINDER_TOKENS:
        return "reminder_unstructured_reply"
    if (result["intent"] == "reminder" and result["reply"] == "[[REMINDER_TODAY]]"
            and re.search(r"(?:还有什么|什么要做|接下来.{0,4}做|还要做)", utterance)):
        return "reminder_remaining_misclassified"
    if result["intent"] == "reminder" and result["reply"] in REMINDER_TOKENS and result["reply"] != "[[REMINDER_CHANGE_UNSUPPORTED]]" and not ("复诊" in utterance and "喝水" in utterance):
        if "复诊" in utterance and result["reply"] != "[[REMINDER_APPOINTMENT]]":
            return "reminder_wrong_topic_appointment"
        if "喝水" in utterance and result["reply"] not in {"[[REMINDER_WATER]]", "[[REMINDER_WATER_DONE]]"}:
            return "reminder_wrong_topic_water"
    # Also catch false write promises if the model mislabels the intent.
    if re.search(r"(?:我会|我已|已经|已为您|帮您|给您).{0,15}(?:提醒.{0,8}(?:调整|改到|改为|设置)|(?:修改|设置|调整|登记|保存).{0,8}提醒)", result["reply"]):
        return "reminder_false_write_claim"
    return None
