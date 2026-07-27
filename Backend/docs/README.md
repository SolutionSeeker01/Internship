# Software-Managed Trailing Stop-Loss: Architecture & Operational Runbook

Welcome to the comprehensive technical documentation suite for the **Software-Managed Trailing Stop-Loss** system migration. This documentation covers system architecture, formal state machine definitions, recovery runbooks, database schemas, order lifecycles, operational guides, and extension standards.

---

## 📚 Documentation Modules

| # | Document | Overview & Contents |
|---|----------|---------------------|
| 1 | [01_architecture_overview.md](file:///e:/Internship/Backend/docs/01_architecture_overview.md) | High-level system architecture, trade lifecycle, stop-loss ownership model, component interactions. |
| 2 | [02_state_machine_documentation.md](file:///e:/Internship/Backend/docs/02_state_machine_documentation.md) | Exhaustive state machine specification (`BROKER_PROTECTED`, `SL_CANCEL_PENDING`, `SOFTWARE_TRAILING_ACTIVE`, `PARTIALLY_PROTECTED`, `TARGET_ORDER_PENDING`, `EXIT_PENDING`, `CLOSED`). |
| 3 | [03_recovery_runbook.md](file:///e:/Internship/Backend/docs/03_recovery_runbook.md) | Startup recovery sequence, broker state reconciliation, decision trees, callback handling, idempotency guarantees. |
| 4 | [04_order_lifecycle.md](file:///e:/Internship/Backend/docs/04_order_lifecycle.md) | Detailed order flow from entry signals, protective broker SL, target limit orders, software exit market orders, and mapping. |
| 5 | [05_database_documentation.md](file:///e:/Internship/Backend/docs/05_database_documentation.md) | Data dictionary, state ownership rules, field invariants (`position_state`, `active_trailing_sl`, `trailing_sl_activated`, `remaining_quantity`). |
| 6 | [06_operational_runbook.md](file:///e:/Internship/Backend/docs/06_operational_runbook.md) | Day-2 operational operations: service restarts, broker outages, stuck trade diagnostics, log analysis, manual interventions. |
| 7 | [07_invariant_catalogue.md](file:///e:/Internship/Backend/docs/07_invariant_catalogue.md) | Complete catalogue of all 10 core architectural invariants, enforcement locations, and safety rationale. |
| 8 | [08_sequence_diagrams.md](file:///e:/Internship/Backend/docs/08_sequence_diagrams.md) | Mermaid sequence diagrams detailing 9 core execution paths (normal trade, handover, trailing, TP1/TP2, exit, crash recovery). |
| 9 | [09_test_coverage_report.md](file:///e:/Internship/Backend/docs/09_test_coverage_report.md) | Test suite breakdown across Phase 1–7 unit/integration suites and the 53-check Production Validation Suite. |
| 10 | [10_future_extension_guide.md](file:///e:/Internship/Backend/docs/10_future_extension_guide.md) | Guidelines for adding multi-broker adapters (Upstox, Angel One), custom exit strategies, additional targets, and strict extension rules. |

---

## 🏛️ System Summary

The **Software-Managed Trailing Stop-Loss** architecture shifts trailing stop logic from broker-side trigger orders to an in-memory, deterministic software engine with full persistence and crash recovery.

- **Phase 1 Handover**: Initial entry orders are protected by a traditional broker SL order. When price reaches 70% of Target 1, the broker SL is cancelled (`SL_CANCEL_PENDING`).
- **Software Trailing**: Upon cancellation confirmation, trailing stop management transfers entirely to software (`SOFTWARE_TRAILING_ACTIVE`). High-frequency ticks adjust the software trailing threshold in memory without placing disruptive broker modification calls.
- **Software SL Breach**: When market price breaches the active trailing stop price, a software-managed market exit order (`EXIT_ALL`) is submitted to the broker immediately.
- **Fail-Safe Recovery**: On restart, `StartupRecoveryService` inspects the DB and queries broker state to deterministically reconstruct position states and resume software trailing seamlessly.
