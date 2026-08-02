# Database Schema & Entity-Relationship Documentation

This document outlines the database schema, primary tables, fields, and foreign key relationships.

---

## Entity-Relationship (ER) Diagram

```mermaid
erDiagram
    users ||--o{ broker_accounts : "owns"
    signals ||--o{ signal_execution_targets : "spawns"
    users ||--o{ signal_execution_targets : "targets client"
    signal_execution_targets ||--o| trades : "executes"
    signal_execution_targets ||--o{ orders : "contains"
    orders ||--o{ orders : "parent/child (ENTRY -> SL/TP)"

    users {
        int id PK
        string email
        string password_hash
        string role "MASTER | CLIENT"
        datetime created_at
    }

    broker_accounts {
        int id PK
        int user_id FK
        string broker "ZERODHA"
        string api_key
        string access_token
        boolean is_connected
        date last_login_trading_day
        datetime created_at
    }

    signals {
        int id PK
        string symbol
        string action "BUY | SELL"
        decimal entry
        decimal stoploss
        decimal t1
        decimal t2
        decimal t3
        string status "VALIDATED | REJECTED"
        datetime created_at
    }

    signal_execution_targets {
        int id PK
        int signal_id FK
        int client_id FK
        string status "READY | EXECUTING | COMPLETED | SKIPPED"
        datetime claimed_at
        datetime created_at
    }

    trades {
        int id PK
        int execution_target_id FK
        string status "OPEN | CLOSED"
        string position_state "BROKER_PROTECTED | SOFTWARE_TRAILING_ACTIVE | CLOSED"
        decimal active_trailing_sl
        boolean trailing_sl_activated
        datetime closed_at
        datetime created_at
    }

    orders {
        int id PK
        int execution_target_id FK
        int parent_order_id FK
        string broker_order_id
        string order_role "ENTRY | STOPLOSS | TARGET_1 | TARGET_2 | TARGET_3 | EXIT_ALL"
        string symbol
        string exchange
        string action "BUY | SELL"
        string order_type "LIMIT | MARKET | SL"
        int quantity
        decimal price
        decimal trigger_price
        string status "PLACED | COMPLETE | CANCELLED | REJECTED"
        datetime placed_at
        datetime created_at
    }
```

---

## Table Schemas & Foreign Key Relationships

### 1. `users`
* **Primary Key**: `id`
* **Fields**: `email`, `password_hash`, `role` (`MASTER` | `CLIENT`), `created_at`
* **Relationships**: Has many `broker_accounts` and `signal_execution_targets`.

### 2. `broker_accounts`
* **Primary Key**: `id`
* **Foreign Keys**: `user_id` $\rightarrow$ `users.id`
* **Fields**: `broker`, `api_key`, `access_token`, `is_connected`, `last_login_trading_day`, `created_at`
* **Relationships**: Belongs to a `users` record.

### 3. `signals`
* **Primary Key**: `id`
* **Fields**: `symbol`, `action` (`BUY` | `SELL`), `entry`, `stoploss`, `t1`, `t2`, `t3`, `status`, `created_at`
* **Relationships**: Spawns multiple `signal_execution_targets`.

### 4. `signal_execution_targets`
* **Primary Key**: `id`
* **Foreign Keys**: 
  * `signal_id` $\rightarrow$ `signals.id`
  * `client_id` $\rightarrow$ `users.id`
* **Fields**: `status` (`READY` | `EXECUTING` | `COMPLETED` | `SKIPPED`), `claimed_at`, `created_at`
* **Relationships**: Links a `signal` to a client `user`. Has one `trade` and many `orders`.

### 5. `trades`
* **Primary Key**: `id`
* **Foreign Keys**: `execution_target_id` $\rightarrow$ `signal_execution_targets.id`
* **Fields**: `status` (`OPEN` | `CLOSED`), `position_state`, `active_trailing_sl`, `trailing_sl_activated`, `closed_at`, `created_at`
* **Relationships**: Maps 1:1 to a `signal_execution_target`.

### 6. `orders`
* **Primary Key**: `id`
* **Foreign Keys**: 
  * `execution_target_id` $\rightarrow$ `signal_execution_targets.id`
  * `parent_order_id` $\rightarrow$ `orders.id` (Self-referential for parent ENTRY order $\rightarrow$ child SL/TP orders)
* **Fields**: `broker_order_id`, `order_role`, `symbol`, `exchange`, `action`, `order_type`, `quantity`, `price`, `trigger_price`, `status`, `placed_at`, `created_at`
* **Relationships**: Belongs to a `signal_execution_target`. Self-referencing hierarchy for child exit orders.
