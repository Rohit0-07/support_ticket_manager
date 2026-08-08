from sqlalchemy import Boolean, Column, String, Integer, Float
from app.core.database import Base


class ResolvedTicket(Base):
    __tablename__ = "resolved_tickets"

    ticket_id = Column(String, primary_key=True, index=True)
    category = Column(String, nullable=False)
    description = Column(String, nullable=False)
    action_taken = Column(String, nullable=False)
    resolution_note = Column(String, nullable=False)
    time_to_resolve_min = Column(Integer, nullable=False)
    csat_score = Column(Float, nullable=False)


class NewTicket(Base):
    __tablename__ = "new_tickets"

    ticket_id = Column(String, primary_key=True, index=True)
    created_at = Column(String, nullable=False)
    order_id = Column(String, nullable=False)
    description = Column(String, nullable=False)


class OrderContext(Base):
    __tablename__ = "orders_context"

    order_id = Column(String, primary_key=True, index=True)
    items = Column(String, nullable=False)
    value = Column(Float, nullable=False)
    delivery_time = Column(String, nullable=False)
    status = Column(String, nullable=False)


class ResolutionDecisionLog(Base):
    __tablename__ = "decision_log"

    ticket_id = Column(String, primary_key=True, index=True)
    order_id = Column(String, nullable=False)
    action = Column(String, nullable=True)
    confidence = Column(Float, nullable=False)
    auto_resolved = Column(Boolean, nullable=False)
    escalation_reason = Column(String, nullable=True)
    similar_ticket_ids = Column(String, nullable=False)
    reasoning = Column(String, nullable=False)
    refund_amount = Column(Float, nullable=True)
    created_at = Column(String, nullable=False)
