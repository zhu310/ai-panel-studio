from fastapi.testclient import TestClient
from sqlalchemy import text
from backend.app.main import app
from backend.app.database import Base,engine,SessionLocal
from backend.app.seed import seed
from backend.app.models import Discussion,Participant,ParticipantRole,Message,DiscussionEvent,DiscussionInsight,InsightKind
client=TestClient(app)
def setup_function():
 Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
def test_health_and_create_defaults():
 assert client.get("/health").status_code==200
 r=client.post("/api/v1/discussions",json={"topic":"测试议题"});assert r.status_code==201
 assert r.json()["expert_count"]==4
 assert client.get("/api/v1/discussions/"+str(r.json()["id"])).status_code==200
def test_validation_and_missing():
 for payload in [{"topic":""},{"topic":"x","expert_count":1},{"topic":"x","expert_count":7}]: assert client.post("/api/v1/discussions",json=payload).status_code==422
 assert client.get("/api/v1/discussions/999").status_code==404
def test_seed_idempotent():
 seed();seed(); rows=client.get("/api/v1/discussions").json();assert len(rows)==5
 rosters=[client.get("/api/v1/discussions/"+str(x["id"])+"/participants").json() for x in rows]
 assert all(len(roster)==5 for roster in rosters)
 assert all(len({person["name"] for person in roster})==5 for roster in rosters)
 assert all(len({person["stance"] for person in roster if person["role"]=="expert"})==4 for roster in rosters)
 assert all(all(person["background"]!="跨领域实践背景" for person in roster) for roster in rosters)
def test_isolation_order_and_foreign_key():
 with SessionLocal() as db:
  a=Discussion(topic="A",expert_count=2);b=Discussion(topic="B",expert_count=2);db.add_all([a,b]);db.flush()
  pa=Participant(discussion_id=a.id,role=ParticipantRole.HOST,name="A",title="t",background="b",stance="s",color="#000");pb=Participant(discussion_id=b.id,role=ParticipantRole.HOST,name="B",title="t",background="b",stance="s",color="#000");db.add_all([pa,pb]);db.flush()
  db.add_all([Message(discussion_id=a.id,speaker_id=pa.id,sequence=2,content="two"),Message(discussion_id=a.id,speaker_id=pa.id,sequence=1,content="one"),Message(discussion_id=b.id,speaker_id=pb.id,sequence=1,content="other"),DiscussionEvent(discussion_id=a.id,sequence=1,event_type="x",payload={}),DiscussionEvent(discussion_id=b.id,sequence=1,event_type="x",payload={}),DiscussionInsight(discussion_id=a.id,kind=InsightKind.CONSENSUS,content="c")]);db.commit();aid=a.id;bid=b.id
 assert [x["content"] for x in client.get("/api/v1/discussions/"+str(aid)+"/transcript").json()]==["one","two"]
 assert client.get("/api/v1/discussions/"+str(bid)+"/transcript").json()[0]["content"]=="other"
 with engine.connect() as c: assert c.execute(text("PRAGMA foreign_keys")).scalar()==1
