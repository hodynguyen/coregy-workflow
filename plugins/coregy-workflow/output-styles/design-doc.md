# Design Document: [Feature Name]

> Used by: **architect**
> Copy this template structure when producing design output.

---

## Overview

Brief description of the feature, its purpose, and scope.

## Architecture

### Component Diagram

```
[Component A] → [Component B] → [Component C]
                      ↓
               [Database / Store]
```

### System Design

- **Component A**: Responsibility
- **Component B**: Responsibility
- **Component C**: Responsibility

## API Contracts

### `POST /api/resource`

**Request:**
```json
{
  "field": "type — description"
}
```

**Response (200):**
```json
{
  "id": "string",
  "field": "type"
}
```

**Errors:** 400 (validation), 401 (unauthorized), 409 (conflict)

## Data Model

### Entity: Resource

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | UUID | PK | Unique identifier |
| name | string | NOT NULL | Display name |
| created_at | timestamp | NOT NULL | Creation time |

### Relationships

- Resource has many Items (1:N)
- User has many Resources (1:N)

## Sequence Flows

### Flow: Create Resource

```
User → Frontend → API → Service → Database
  1. User submits form
  2. Frontend validates input, calls POST /api/resource
  3. API validates auth, passes to service
  4. Service applies business rules, persists to DB
  5. Response returned to user
```

## Decision Records

### ADR-XXX: [Decision Title]

- **Status**: Proposed | Accepted | Deprecated
- **Context**: Why this decision is needed
- **Options**: A (chosen), B, C
- **Decision**: Option A because [rationale]
- **Consequences**: [trade-offs and implications]

## Implementation Notes

Guidance for BUILD agents:
- Start with [component/layer]
- Key dependencies: [list]
- Suggested file structure: [outline]
- Known constraints: [list]
