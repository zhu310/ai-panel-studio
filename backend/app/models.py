import enum
from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

class DiscussionStatus(str, enum.Enum):
    DRAFT="draft"; ROSTER_READY="roster_ready"; RUNNING="running"; COMPLETED="completed"; STOPPED="stopped"; FAILED="failed"
class ParticipantRole(str, enum.Enum):
    HOST="host"; EXPERT="expert"
class InsightKind(str, enum.Enum):
    CONSENSUS="consensus"; DISAGREEMENT="disagreement"

class Discussion(Base):
    __tablename__="discussions"
    id: Mapped[int]=mapped_column(primary_key=True)
    topic: Mapped[str]=mapped_column(Text, nullable=False)
    expert_count: Mapped[int]=mapped_column(Integer, nullable=False, default=4)
    status: Mapped[DiscussionStatus]=mapped_column(Enum(DiscussionStatus), default=DiscussionStatus.DRAFT, nullable=False)
    is_preset: Mapped[bool]=mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    participants=relationship("Participant", back_populates="discussion", cascade="all, delete-orphan")
    messages=relationship("Message", back_populates="discussion", cascade="all, delete-orphan")
    events=relationship("DiscussionEvent", back_populates="discussion", cascade="all, delete-orphan")
    insights=relationship("DiscussionInsight", back_populates="discussion", cascade="all, delete-orphan")
    __table_args__=(CheckConstraint("expert_count BETWEEN 2 AND 6", name="ck_discussion_expert_count"),)

class Participant(Base):
    __tablename__="participants"
    id: Mapped[int]=mapped_column(primary_key=True)
    discussion_id: Mapped[int]=mapped_column(ForeignKey("discussions.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[ParticipantRole]=mapped_column(Enum(ParticipantRole), nullable=False)
    name: Mapped[str]=mapped_column(String(100), nullable=False)
    title: Mapped[str]=mapped_column(String(160), nullable=False)
    background: Mapped[str]=mapped_column(Text, nullable=False)
    stance: Mapped[str]=mapped_column(Text, nullable=False)
    color: Mapped[str]=mapped_column(String(20), nullable=False)
    discussion=relationship("Discussion", back_populates="participants")
    messages=relationship("Message", back_populates="speaker")

class Message(Base):
    __tablename__="messages"
    id: Mapped[int]=mapped_column(primary_key=True)
    discussion_id: Mapped[int]=mapped_column(ForeignKey("discussions.id", ondelete="CASCADE"), nullable=False, index=True)
    speaker_id: Mapped[int]=mapped_column(ForeignKey("participants.id", ondelete="RESTRICT"), nullable=False)
    sequence: Mapped[int]=mapped_column(Integer, nullable=False)
    content: Mapped[str]=mapped_column(Text, nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    discussion=relationship("Discussion", back_populates="messages"); speaker=relationship("Participant", back_populates="messages")
    __table_args__=(UniqueConstraint("discussion_id","sequence",name="uq_message_sequence"),)

class DiscussionEvent(Base):
    __tablename__="discussion_events"
    id: Mapped[int]=mapped_column(primary_key=True)
    discussion_id: Mapped[int]=mapped_column(ForeignKey("discussions.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence: Mapped[int]=mapped_column(Integer, nullable=False)
    event_type: Mapped[str]=mapped_column(String(80), nullable=False)
    payload: Mapped[dict]=mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    discussion=relationship("Discussion", back_populates="events")
    __table_args__=(UniqueConstraint("discussion_id","sequence",name="uq_event_sequence"),)

class DiscussionInsight(Base):
    __tablename__="discussion_insights"
    id: Mapped[int]=mapped_column(primary_key=True)
    discussion_id: Mapped[int]=mapped_column(ForeignKey("discussions.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[InsightKind]=mapped_column(Enum(InsightKind), nullable=False)
    content: Mapped[str]=mapped_column(Text, nullable=False)
    is_active: Mapped[bool]=mapped_column(default=True, nullable=False)
    version: Mapped[int]=mapped_column(Integer, default=1, nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    discussion=relationship("Discussion", back_populates="insights")
    evidence=relationship("InsightEvidence", back_populates="insight", cascade="all, delete-orphan")

class InsightEvidence(Base):
    __tablename__="insight_evidence"
    insight_id: Mapped[int]=mapped_column(ForeignKey("discussion_insights.id",ondelete="CASCADE"),primary_key=True)
    message_id: Mapped[int]=mapped_column(ForeignKey("messages.id",ondelete="RESTRICT"),primary_key=True)
    insight=relationship("DiscussionInsight", back_populates="evidence")
