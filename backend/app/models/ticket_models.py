from pydantic import BaseModel, ConfigDict, Field
from typing import List


class ResolvedTicketSchema(BaseModel):
    """Response schema for a single resolved ticket."""
    model_config = ConfigDict(from_attributes=True)

    ticket_id: str = Field(..., examples=["H-1000"])
    category: str = Field(..., examples=["missing_item"])
    description: str = Field(..., examples=["milk packet missing from my order"])
    action_taken: str = Field(..., examples=["redelivery"])
    resolution_note: str = Field(..., examples=["missing item re-sent"])
    time_to_resolve_min: int = Field(..., examples=[32])
    csat_score: float = Field(..., examples=[5.0])


class NewTicketSchema(BaseModel):
    """Response schema for a single new/incoming ticket."""
    model_config = ConfigDict(from_attributes=True)

    ticket_id: str = Field(..., examples=["N-000"])
    created_at: str = Field(..., examples=["2026-08-07T20:58:00"])
    order_id: str = Field(..., examples=["ORD-9900"])
    description: str = Field(..., examples=["fruits were rotten"])


class OrderContextSchema(BaseModel):
    """Response schema for a single order."""
    model_config = ConfigDict(from_attributes=True)

    order_id: str = Field(..., examples=["ORD-9900"])
    items: str = Field(..., examples=["1"])
    value: float = Field(..., examples=[999.0])
    delivery_time: str = Field(..., examples=["24"])
    status: str = Field(..., examples=["cancelled"])


class PaginatedResponse(BaseModel):
    """Wrapper for paginated list responses."""
    total: int
    skip: int
    limit: int
    items: List


class ResolvedTicketListResponse(PaginatedResponse):
    items: List[ResolvedTicketSchema]


class NewTicketListResponse(PaginatedResponse):
    items: List[NewTicketSchema]


class OrderContextListResponse(PaginatedResponse):
    items: List[OrderContextSchema]


class SeedResponse(BaseModel):
    """Response from the seeding endpoint."""
    resolved_tickets_loaded: int
    new_tickets_loaded: int
    orders_loaded: int
    warnings: List[str]


class HealthResponse(BaseModel):
    """Response from the health check endpoint."""
    status: str
    resolved_tickets_count: int
    new_tickets_count: int
    orders_count: int
