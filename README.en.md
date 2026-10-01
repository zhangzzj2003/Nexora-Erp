# Nexora ERP

[简体中文](README.md) · [Website source](docs/site/) · [Development guide](docs/development.en.md)

A desktop ERP for internal operations, connecting purchasing, warehousing, sales, production and operational finance through traceable documents and stock movements. The desktop uses Electron, Vue 3, TypeScript and Pinia; the server uses FastAPI, SQLAlchemy and SQLite.

The project is in an **internal trial phase for one company, multiple warehouses and online LAN clients**. Windows and macOS clients access centralized server data over HTTPS. Disconnected clients cannot submit changes. Documentation and the website are bilingual; the application UI remains Chinese. Website code is prepared; GitHub Pages is not enabled yet.

## Project features

| Area | Current functionality |
| --- | --- |
| Accounts and permissions | Users, built-in/custom roles, document action permissions, account activation, password resets, permission trees and navigation icon settings. |
| Master data | Materials, suppliers, private customer profiles, warehouses and supplier-material relationships; server pagination for saved business tables and remote search for selectors. |
| Purchasing | Versioned department/amount approval chains, audited delegation and split orders, partial receiving, warehouse-confirmed receipts, returns and reversals. |
| Warehousing | Multi-warehouse stock, movements, adjustments and stock ledgers; linked documents and inferred FIFO system lots. |
| Sales | Shared orders with independently authorized amounts, partial shipments, linked returns and reversals; confirmation checks remaining quantities and stock. |
| Production | BOM versions, frozen requirements, material issues/returns, completion and inspection; material planning, manual scheduling, scrap and rework handling. |
| Cost and operational finance | Moving-average valuation, unknown-cost valuation, production and quality costs, receivable/payable sources, RMB tax/discount terms, subsidiary openings, bank matching and auxiliary dimensions. |
| General ledger | Accounts, periods, independently reviewed/confirmed opening balances, independently reviewed/posted/reversed manual and business-source journals, posted account ledgers and trial balance; ordered closing, reverse-order reopening and archived balances/cost evidence. |
| Reports and operations | Basic purchasing/inventory reports and CSV; LAN discovery, certificate fingerprint trust, OS services, backup/restore and upgrade backups. |

Stock and financial changes retain sources, operators and correction records. Confirmation and movements commit together. Unknown prices remain unknown instead of becoming zero. Manual payments and basic inspection do not prove bank settlement or physical verification.

## Development progress

Snapshot: **2026-10-01, retained ERP improvement batch**. Work in progress is not delivered mainline functionality. Progress describes capabilities rather than an undefined percentage.

| Stage | Status | Delivered / next steps |
| --- | --- | --- |
| Purchasing–inventory–sales–production flow | Basic flows implemented | Partial receipts/shipments, returns, corrections and tracing; complex cases remain. |
| Backend data access | Migration complete | Existing business access uses ORM; migrations, SQLite configuration and online backup retain necessary low-level operations. |
| Inventory and finished-goods costs | Foundation implemented | Moving-average valuation, batch allocations, quality costs and cutoff-date work in progress; physical and complex cross-period acceptance remain. |
| Ledger master data | Merged | Accounts, periods and auditing; period closing is provided separately. |
| Formal opening balances | Implemented | First setup before any posted journal, independent review/confirmation, versions and audit, reversal before posting; excluded from current activity. |
| Manual journals | Merged | Balanced entries, independent review, posting, linked reversals and auditing; business-source journals are provided separately; formal statements remain. |
| Posted ledger reports | Merged | Account ledgers, trial balance, journal drill-down and CSV; formal openings and management balance/income reports are available. Statutory report templates remain planned. |
| Period closing | Implemented | Check and close ended periods in order, lock historical valuations/allocations, reopen in reverse order, retain every archive and audit. |
| Business-source journals | Implemented | Configurable accounts, source recomputation, purchase variances and sales-cost entries, atomic deduplication, source snapshots and posted-source protection; independent review remains required. |
| Profit transfer | Implemented | Company account scope, period-end drafts, independent review, source protection, reverse-order corrections and zero-balance closing checks. |
| Financial completion | Foundation on retained branches | Subsidiary opening reconciliation, auxiliary accounting, bank matching and management statements; statutory templates and multiple currencies remain planned. |
| Business expansion | Foundation on retained branches / further work planned | Material planning, manual scheduling, scrap/rework and document tracing are available; complete after-sales, CRM, equipment, HR and multiple organizations remain planned. |
| Data and devices | Planned / acceptance pending | MySQL and offline sync are not implemented; cross-platform devices, unattended startup and recovery drills need acceptance. |

Candidate sequencing and entry conditions are in the [expansion assessment (Chinese)](docs/erp-expansion-assessment.md). Build success does not replace device or business acceptance.

## Development entry points

Requires Node.js 22.12+ and Python 3.11+. Setup, architecture, business constraints, testing, **build instructions**, backup/restore and website publishing now live in the detailed guide:

- [English development guide](docs/development.en.md)
- [中文开发文档](docs/development.zh-CN.md)

Run `npm run docs:build` to generate a local HTML website and bilingual guide. GitHub Pages configuration is included, with hosting intentionally not enabled yet. Installer artifacts go to `release/` and remain unsigned/unnotarized; see the guide for commands.

The 2026-10-01 customer ownership, server pagination, RMB finance tools, document traceability, production/quality and purchasing approval batch is implemented and validated on retained branches. It has not been merged or deployed to the installed host. See [batch acceptance (Chinese)](docs/erp-batch-acceptance.md) for the current feature boundaries and validation evidence.
