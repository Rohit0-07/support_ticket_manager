# F1 · Data Ingestion & Storage — Context Capsule

> **Feature ID**: F1  
> **Status**: Completed & Validated  
> **Dependencies**: None  
> **Downstream Consumers**: F2 (Similarity Engine), F3 (Resolution Engine), F5 (Dashboard)

---

## Exported Interfaces & Contracts

### 1. Data Models & ORM Entities
- **ORM Models** (`backend/app/models/db_models.py`):
  - `ResolvedTicket`: `ticket_id` (PK, str), `category`, `description`, `action_taken`, `resolution_note`, `time_to_resolve_min`, `csat_score`.
  - `NewTicket`: `ticket_id` (PK, str), `created_at`, `order_id`, `description`.
  - `OrderContext`: `order_id` (PK, str), `items`, `value`, `delivery_time`, `status`.

- **Pydantic Schemas** (`backend/app/models/ticket_models.py`):
  - `ResolvedTicketSchema`, `NewTicketSchema`, `OrderContextSchema`
  - `ResolvedTicketListResponse`, `NewTicketListResponse`, `OrderContextListResponse` (offset-paginated wrappers: `total`, `skip`, `limit`, `items`).

---

### 2. Service Functions

#### Ingestion Service (`backend/app/services/ingestion_service.py`)
- `seed_resolved_tickets(csv_path: Path, db=None) -> SeedResult`
- `seed_new_tickets(csv_path: Path, db=None) -> SeedResult`
- `seed_orders(csv_path: Path, db=None) -> SeedResult`
- `seed_all(csv_dir: Path, db=None) -> Dict[str, SeedResult]`

#### Ticket Query Service (`backend/app/services/ticket_service.py`)
- `list_resolved_tickets(db: AsyncSession, skip: int = 0, limit: int = 50) -> Tuple[List[ResolvedTicket], int]`
- `get_resolved_ticket(db: AsyncSession, ticket_id: str) -> Optional[ResolvedTicket]`
- `list_new_tickets(db: AsyncSession, skip: int = 0, limit: int = 50) -> Tuple[List[NewTicket], int]`
- `get_new_ticket(db: AsyncSession, ticket_id: str) -> Optional[NewTicket]`
- `list_orders(db: AsyncSession, skip: int = 0, limit: int = 50) -> Tuple[List[OrderContext], int]`
- `get_order(db: AsyncSession, order_id: str) -> Optional[OrderContext]`

---

### 3. REST API Endpoints
- `GET /api/v1/resolved-tickets` & `GET /api/v1/resolved-tickets/{ticket_id}`
- `GET /api/v1/new-tickets` & `GET /api/v1/new-tickets/{ticket_id}`
- `GET /api/v1/orders` & `GET /api/v1/orders/{order_id}`
- `POST /api/v1/seed` (re-trigger CSV seeding)
- `GET /api/v1/health` (liveness & record count summary)
