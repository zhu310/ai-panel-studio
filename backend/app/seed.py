from sqlalchemy import select
from .database import SessionLocal
from .models import Discussion, Participant, ParticipantRole, DiscussionStatus


# Presets are editorial examples, not AI-generated output. Each profile has a
# distinct public background and stance so the roster is useful out of the box.
PRESETS = [
    ("是否应在高校全面推广生成式 AI 助教", [
        ("周岚", "教育政策主持人", "长期主持高校教学改革听证与多方评估", "中立追问推广边界、证据质量与问责机制", "#5B8FF9"),
        ("陈砚秋", "学习科学研究员", "研究智能辅导对知识迁移和元认知的影响", "支持循证试点，反对在缺少学习成效数据时全面铺开", "#61DDAA"),
        ("许明哲", "一线大学教师", "负责大班基础课教学与课程评价改革", "认可备课减负，但坚持教师保留教学判断与最终反馈权", "#F6BD16"),
        ("顾雨桐", "学生权益代表", "参与学生数据使用和算法申诉机制建设", "要求知情同意、可退出和不因拒用 AI 受到不利评价", "#7262FD"),
        ("罗静宜", "数据隐私律师", "专注教育数据合规、跨境传输与供应商审计", "主张先限定数据用途和保存期限，再讨论规模化部署", "#E868A2"),
    ]),
    ("城市应优先发展自动驾驶出租车还是公共交通", [
        ("何川", "城市议题主持人", "主持交通规划与公共预算协商", "要求比较全生命周期成本、覆盖公平与安全责任", "#5B8FF9"),
        ("梁致远", "交通规划师", "参与轨道与公交网络客流建模", "优先投资高运量公共交通，自动驾驶用于接驳补充", "#61DDAA"),
        ("宋亦航", "自动驾驶系统工程师", "负责城区无人车感知与安全冗余", "主张在限定区域扩大车队，以运营数据迭代安全能力", "#F6BD16"),
        ("田若琳", "公交运营负责人", "管理公交线网、班次与财政补贴绩效", "反对技术项目挤压基础公交经费，强调稳定可达性", "#7262FD"),
        ("杜新月", "无障碍出行倡导者", "研究老年人和残障人士的出行障碍", "任何方案都应以无障碍覆盖和人工协助作为硬约束", "#E868A2"),
    ]),
    ("中小企业采用 AI 是否应先从客服场景开始", [
        ("魏宁", "商业科技主持人", "主持中小企业数字化案例复盘", "中立核对收益口径、组织能力和失败成本", "#5B8FF9"),
        ("韩若谷", "企业数字化顾问", "为制造与零售企业设计渐进式 AI 改造", "支持从高频客服试点，但先建立人工兜底和评估指标", "#61DDAA"),
        ("蒋文欣", "客户服务平台主管", "负责投诉处理、质检和坐席培训", "担心复杂投诉被误判，主张只自动化低风险标准问题", "#F6BD16"),
        ("邵立", "中小企业财务负责人", "关注现金流、采购回报与隐性维护成本", "要求三个月内可量化回报，否则优先改造内部流程", "#7262FD"),
        ("叶青禾", "数据安全顾问", "实施客户数据分级、脱敏与供应商审计", "数据最小化和权限治理应先于任何外部模型接入", "#E868A2"),
    ]),
    ("碳中和目标下核电应承担多大比例", [
        ("沈言", "能源议题主持人", "主持电力系统与气候政策公开讨论", "要求同时讨论可靠性、成本、安全和代际责任", "#5B8FF9"),
        ("冯启衡", "能源经济学家", "研究电力市场、容量成本与减排路径", "支持核电承担稳定基荷，但比例应由系统成本优化决定", "#61DDAA"),
        ("秦守正", "核安全工程师", "参与反应堆概率安全评估和应急演练", "可以稳步扩建，但选址、监管独立性和退役资金不可妥协", "#F6BD16"),
        ("章可心", "可再生能源研究员", "研究风光储协同和跨区电网调度", "主张优先降低储能与电网瓶颈，避免核电锁定长期资本", "#7262FD"),
        ("陆岑", "环境组织政策主任", "跟踪核废料治理与公众参与程序", "反对在废料长期方案和社区同意不足时设定过高占比", "#E868A2"),
    ]),
    ("儿童短视频使用应如何监管", [
        ("苏妍", "未成年人议题主持人", "主持家庭、平台与监管部门的公共对话", "中立区分家庭责任、产品责任与公共监管边界", "#5B8FF9"),
        ("温澄", "发展心理学家", "研究注意力、自我控制与亲子媒介使用", "支持按年龄限制时长，并用独立研究持续评估影响", "#61DDAA"),
        ("唐予安", "内容平台产品负责人", "负责青少年模式、推荐策略和内容审核", "主张以默认保护和家长工具改进体验，反对一刀切禁用", "#F6BD16"),
        ("方敏", "家长代表", "参与学校家委会与家庭数字素养活动", "要求关闭诱导连播和付费设计，让家长获得可理解的控制权", "#7262FD"),
        ("姜珩", "未成年人保护律师", "处理儿童隐私、广告和平台责任案件", "主张数据最小化、禁止画像广告并对违规设置可执行处罚", "#E868A2"),
    ]),
]


def seed():
    with SessionLocal() as db:
        for topic, profiles in PRESETS:
            discussion = db.scalar(select(Discussion).where(
                Discussion.topic == topic, Discussion.is_preset.is_(True)))
            if discussion is None:
                discussion = Discussion(topic=topic, expert_count=4,
                                        status=DiscussionStatus.ROSTER_READY, is_preset=True)
                db.add(discussion)
                db.flush()
            participants = db.scalars(select(Participant).where(
                Participant.discussion_id == discussion.id).order_by(Participant.id)).all()
            for index, (name, title, background, stance, color) in enumerate(profiles):
                role = ParticipantRole.HOST if index == 0 else ParticipantRole.EXPERT
                if index < len(participants):
                    person = participants[index]
                    person.role = role
                    person.name = name
                    person.title = title
                    person.background = background
                    person.stance = stance
                    person.color = color
                else:
                    db.add(Participant(discussion_id=discussion.id, role=role, name=name,
                                       title=title, background=background, stance=stance, color=color))
        db.commit()


if __name__ == "__main__":
    from .init_db import init_db
    init_db()
    seed()
