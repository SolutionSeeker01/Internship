# Backend Architectural Reference

> Generated from live code analysis on 2026-07-02. Reflects only files currently on disk — no planned/future features.

---

## Repository Tree

```
Backend/
├── main.py                          # FastAPI app entrypoint, lifespan, router registration
├── test.py                          # Minimal test stub
├── universe_cache.json              # Persisted symbol→metadata JSON (~5.8 MB)
├── __init__.py
│
├── database/
│   ├── __init__.py
│   ├── db.py                        # SQLAlchemy engine, session factory, get_db dependency
│   ├── defaults.py                  # Hardcoded default stock/index symbol lists
│   ├── instrument_repository.py     # Raw SQL CRUD for instruments table
│   ├── signal_repository.py         # Raw SQL CRUD for signals table
│   └── watchlist_repository.py      # Raw SQL CRUD for watchlists + watchlist_items tables
│
├── dependencies/
│   └── auth.py                      # FastAPI Depends() for JWT→User resolution
│
├── market_data/
│   ├── __init__.py
│   ├── connection.py                # KiteConnect/KiteTicker singleton factory
│   ├── kite_client.py               # Market data service lifecycle (start/stop/restart)
│   ├── lookup.py                    # LTP price lookup with TTL cache + broker fallback
│   ├── store.py                     # In-memory thread-safe latest-tick store
│   ├── subscriptions.py             # Subscription universe builder (DB → RAM cache)
│   └── universe.py                  # universe_cache.json file I/O + in-memory symbol registry
│
├── models/
│   ├── __init__.py                  # Re-exports User, UserRole, BrokerAccount
│   ├── user.py                      # SQLAlchemy ORM: users table
│   └── broker_account.py            # SQLAlchemy ORM: broker_accounts table
│
├── routers/
│   ├── __init__.py
│   ├── auth.py                      # /auth/* – Login, bootstrap, broker setup/connect/callback
│   ├── candles.py                   # /candles/* – Historical OHLCV data
│   ├── dashboard.py                 # /dashboard/* – Dashboard watchlist data
│   ├── instruments.py               # /instruments/* – CRUD, search, sync, bulk-delete
│   ├── user_management.py           # /users/* – MASTER-only user CRUD
│   ├── watchlist.py                 # /watchlists/* – Watchlist + item CRUD
│   ├── webhook.py                   # /webhook – Signal ingestion
│   └── websocket.py                 # /ws – Real-time tick streaming to browser
│
├── schemas/
│   ├── auth.py                      # LoginRequest, LoginResponse, UserResponse
│   ├── bootstrap.py                 # BootstrapState enum, BootstrapResponse
│   ├── broker.py                    # BrokerSetupRequest/Response
│   ├── callback.py                  # BrokerCallbackRequest/Response
│   ├── instrument_delete.py         # BulkDeleteRequest
│   ├── oauth.py                     # BrokerConnectResponse
│   ├── user_management.py           # UserCreate/Update/PasswordReset/Status schemas
│   └── watchlist.py                 # Watchlist CRUD schemas
│
├── security/
│   ├── encryption.py                # Fernet decrypt/encrypt logic
│   ├── jwt_handler.py               # JWT encode/decode logic
│   └── password.py                  # Passlib bcrypt helpers
│
├── services/
│   └── auth_service.py              # User authentication logic
│
├── signals/
│   ├── __init__.py
│   ├── constants.py                 # Signal status values
│   ├── schemas.py                   # Webhook schemas
│   ├── tracker.py                   # Placeholder tracking module
│   └── validator.py                 # 7-layer validation engine
│
└── utils/
    └── logger.py                    # Central logging service
```

For the full detailed document including Layer Responsibilities, Detailed request flows, Sequence diagrams, Database mappings, Schemas, Constraints, and Business validation details, refer to the generated artifact [backend_architecture.md](file:///C:/Users/rajee/.gemini/antigravity/brain/02aba008-b271-4961-820d-c4b1e252f6db/backend_architecture.md).
