"""Public education summaries reviewed through 2026-10-22, not individual medical advice.

The complete set goes to the LLM; there is no keyword-based answer selection.
UK emergency numbers are not copied into the Chinese deployment.
"""
CARE_REFERENCE = {
    "reviewed_on": "2026-10-23",
    "scope": "一般健康教育，不能替代个人医嘱；不是完整分诊指南，未出现列举信号不保证安全",
    "cards": [
        {"topic": "疲惫", "source": "https://www.nhs.uk/symptoms/tiredness-and-fatigue/",
         "general": "可尝试保持规律睡眠时间，睡前安排放松活动如阅读或听音乐，营造不过亮、不过吵、不过热的睡眠环境。选择一项适合当前情况的提示，不将疲惫归因于睡眠，也不承诺疗效。",
         "seek_help": "疲惫已影响日常生活、持续数周且原因不明，或伴其他症状时咨询医护；不自行诊断。",
         "limits": "不编造每小时活动、深呼吸治疗或具体运动强度；出现疼痛或加重时优先处理新情况，不反复谈睡眠。"},
        {"topic": "颈部不适", "source": "https://www.nhs.uk/symptoms/neck-pain-and-stiff-neck/",
         "possible_factors": "一般颈部不适可能与久持一个姿势、睡姿或受伤等有关；不能仅凭一句话认定用户是哪种原因。",
         "general": "一般姿势提示：避免长时间让颈部保持同一姿势；一般颈部不适可考虑较低、较结实的枕头，睡觉时让头部与身体保持同一高度，不趴睡、不在床上扭转颈部。根据当前问题选择适用项，不一次罗列，不保证缓解；不能仅凭疼痛诊断为姿势问题。",
         "seek_help": "持续不缓解、令人担忧，或伴手臂发冷/针刺感时，应咨询医护。",
         "limits": "本项目不据此给出药物、热敷参数或拉伸动作；外伤背景未知不等于没有外伤。可直接给一般姿势提示，但不能说已适用于具体伤情；若近期摔倒或扭伤，或出现手臂发冷/针刺感，应联系医护，不用追问外伤。"},
        {"topic": "腰背不适", "source": "https://www.nhs.uk/conditions/back-pain/",
         "possible_factors": "一般腰背不适可能与肌肉拉伤、劳累等有关，也可能有其他原因；不能仅凭酸痛确定病因。",
         "general": "一般腰背不适在没有受伤、能够活动且活动不加重疼痛时，可在可承受范围内维持日常活动、避免长时间卧床；不等于要求带痛锻炼。",
         "seek_help": "突然剧烈或迅速加重、伴发热或明显不适应及时就医；双腿无力或麻木、会阴感觉异常、大小便功能改变、胸痛或严重事故后疼痛应立即求助。影响日常生活、持续不缓解或担忧也应咨询医护。",
         "limits": "外伤和危险信号未知时不能默认已排除；可直接给上述有条件的一般生活提示，并提醒若近期摔倒或扭伤、疼痛迅速加重或出现危险信号需联系医护，不追问外伤；不指导弯腰、扭腰、拉伸、按摩或用药，不把腰痛诊断为劳损。"},
        {"topic": "睡眠困扰", "source": "https://www.nhs.uk/conditions/insomnia/",
         "general": "可选择一项适合的生活提示：保持规律起床时间；营造安静、昏暗的睡眠环境；睡前留时间放松。",
         "seek_help": "睡眠问题持续、生活习惯调整无效或影响日常生活时，咨询医护。",
         "limits": "不能从一次没睡好诊断失眠；用户已说明疼痛影响睡眠时先回应疼痛问题，不反复泛讲睡眠习惯。"},
        {"topic": "腹部不适", "source": "https://www.nhs.uk/symptoms/stomach-ache/",
         "general": "不能自行判断腹痛原因；需结合持续时间、程度与伴随情况了解需求。",
         "seek_help": "突然发生或剧烈腹痛、呕血、黑便、呼吸困难或胸痛等应立即寻求急救；加重、持续或反复腹痛应及时就医。",
         "limits": "不推荐自行揉腹、拉伸、用药或把腹痛归因于劳累。没有危险信号信息不等于排除风险。"}
    ]
}
