from sqlalchemy import select
from .database import SessionLocal
from .models import Discussion,Participant,ParticipantRole,DiscussionStatus
TOPICS=[
("是否应在高校全面推广生成式 AI 助教",["教育技术研究者","高校教师","学生权益代表","数据隐私律师"]),
("城市应优先发展自动驾驶出租车还是公共交通",["交通规划师","自动驾驶工程师","公交运营专家","无障碍倡导者"]),
("中小企业采用 AI 是否应先从客服场景开始",["企业数字化顾问","客服平台主管","财务负责人","数据安全专家"]),
("碳中和目标下核电应承担多大比例",["能源经济学家","核安全工程师","可再生能源研究员","环保组织代表"]),
("儿童短视频使用应如何监管",["发展心理学家","平台产品负责人","家长代表","未成年人保护律师"])]
def seed():
  with SessionLocal() as db:
    for topic,titles in TOPICS:
      if db.scalar(select(Discussion.id).where(Discussion.topic==topic,Discussion.is_preset.is_(True))): continue
      d=Discussion(topic=topic,expert_count=4,status=DiscussionStatus.ROSTER_READY,is_preset=True);db.add(d);db.flush()
      people=[("主持人","圆桌主持人","圆桌讨论引导经验","负责追问并平衡不同立场","#5B8FF9")]+[(f"专家{i}",t,"跨领域实践背景",f"从{t}角度审视收益、风险与条件",["#61DDAA","#65789B","#F6BD16","#7262FD"][i-1]) for i,t in enumerate(titles,1)]
      for i,(name,title,bg,stance,color) in enumerate(people):db.add(Participant(discussion_id=d.id,role=ParticipantRole.HOST if i==0 else ParticipantRole.EXPERT,name=name,title=title,background=bg,stance=stance,color=color))
    db.commit()
if __name__=="__main__":
 from .init_db import init_db
 init_db();seed()
