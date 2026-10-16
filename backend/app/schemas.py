from datetime import datetime
from pydantic import BaseModel, Field
from .models import DiscussionStatus, ParticipantRole, InsightKind
class CreateDiscussion(BaseModel):
    topic: str = Field(min_length=1, max_length=2000)
    expert_count: int = Field(default=4, ge=2, le=6)
class DiscussionOut(BaseModel):
    id:int; topic:str; expert_count:int; status:DiscussionStatus; is_preset:bool; created_at:datetime
    model_config={"from_attributes":True}
class ParticipantOut(BaseModel):
    id:int; role:ParticipantRole; name:str; title:str; background:str; stance:str; color:str
    model_config={"from_attributes":True}
class MessageOut(BaseModel):
    id:int; speaker_id:int; sequence:int; content:str; created_at:datetime
    action:str|None=None
    model_config={"from_attributes":True}
class InsightOut(BaseModel):
    id:int; kind:InsightKind; content:str; is_active:bool; version:int; evidence_message_ids:list[int]=[]
class DiscussionDetail(DiscussionOut):
    participants:list[ParticipantOut]=[]
    summary:str|None=None
