# Nexora ERP

[简体中文](README.md) · [Website source](docs/site/) · [Development guide](docs/development.en.md)

A desktop ERP for internal operations, connecting purchasing, warehousing, sales, production and operational finance through traceable documents and stock movements. The desktop uses Electron, Vue 3, TypeScript and Pinia; the server uses FastAPI, SQLAlchemy and SQLite.

The desktop uses an integrated title bar across onboarding, login and the workspace. macOS retains native traffic lights at the upper left; Windows retains native window controls at the upper right. Branding, refresh, home, the current category/page directory and theme switching share the top row; page tabs occupy a separate fixed row below it, to the right of the sidebar. Empty title bar areas drag the window and Windows controls follow the app theme. Browser previews and Linux retain their native window frame, and closing a window retains the existing tray behavior.

Theme buttons morph between moon and sun and use a 450 ms circular transition: entering dark mode contracts the old light snapshot; entering light mode reveals the new snapshot from the click position. Keyboard activation uses the button center. The theme entry is consolidated at the top and removed from the lower-left sidebar; rapid clicks preserve the last choice. Unsupported snapshots, reduced motion and capture failures fall back to a direct theme update. The motion is adapted from Vben; see [third-party notices](docs/third-party-notices.md).

The project is in an **internal trial phase for one company, multiple warehouses and online LAN clients**. Windows and macOS clients access centralized server data over HTTPS. Disconnected clients cannot submit changes. Documentation and the website are bilingual; the application UI remains Chinese. Website code is prepared; GitHub Pages is not enabled yet.

The directory follows the active route and offers permitted pages in the same category. Refresh reads authorized data before remounting the current page, retaining the login session and opened tabs. Independent pagination and dashboard queries reload as well. Repeated refresh and business submission are blocked during the operation; failures show a shared error message and can be retried. Browser and Linux workspaces provide the same controls above the content.

## Project features

| Area | Current functionality |
| --- | --- |
| Accounts and permissions | Users, built-in/custom roles, document action permissions, account activation, password resets, permission trees and navigation icon settings. |
| Master data | Materials, suppliers, customers, warehouses and supplier-material relationships; server-side pagination for suppliers. |
| Purchasing | Request approval and split orders, orders, partial receiving, warehouse-confirmed receipts, returns awaiting shipment confirmation, and reversals. |
| Warehousing | Multi-warehouse stock, other inbounds/outbounds, transfers, stocktakes, independently approved adjustments, source movements and stock ledgers. |
| Sales | [Customer relations and quotations (Chinese)](docs/customer-relations.md) add contacts, follow-ups, opportunities and independently approved quotation conversion; orders, partial shipments, linked returns and reversals; confirmation checks remaining order quantities and stock. |
| Production | BOM versions, frozen work-order requirements, partial material issues/returns, completion reports, basic inspection and accepted-goods receipts; [MRP (Chinese)](docs/material-planning.md) adds dated net requirements, fixed evidence, independent approval and draft conversion; [equipment maintenance (Chinese)](docs/equipment-maintenance.md) adds calendar plans, independent execution/acceptance, downtime and material sources. |
| Cost and operational finance | Moving-average valuation, manual valuation of unknown costs, material/labor/overhead collection, finished-goods cost allocation, receivable/payable sources, manual payments and reversals. |
| General ledger | Accounts, periods, independently reviewed/confirmed opening balances, independently reviewed/posted/reversed manual and business-source journals, posted account ledgers and trial balance; ordered closing, reverse-order reopening and archived balances/cost evidence. |
| Reports and operations | Basic purchasing/inventory reports and CSV; [live home statistics (Chinese)](docs/home-statistics.md) show authorized business net amounts, trends and current pending documents/stock; LAN discovery, certificate fingerprint trust, OS services, backup/restore and upgrade backups. |

Stock and financial changes retain sources, operators and correction records. Confirmation and movements commit together. Unknown prices remain unknown instead of becoming zero. Manual payments and basic inspection do not prove bank settlement or physical verification.

## Development progress

Snapshot: **2026-10-01, this equipment maintenance implementation**. Work in progress is not delivered mainline functionality. Progress describes capabilities rather than an undefined percentage.

| Stage | Status | Delivered / next steps |
| --- | --- | --- |
| Purchasing–inventory–sales–production flow | Basic flows implemented | Partial receipts/shipments, returns, corrections and tracing; complex cases remain. |
| Backend data access | Migration complete | Existing business access uses ORM; migrations, SQLite configuration and online backup retain necessary low-level operations. |
| Inventory and finished-goods costs | Foundation implemented | Moving-average valuation and batch allocations; variances, work in progress and cross-period costs remain. |
| Ledger master data | Merged | Accounts, periods and auditing; period closing is provided separately. |
| Formal opening balances | Implemented | First setup before any posted journal, independent review/confirmation, versions and audit, reversal before posting; excluded from current activity. |
| Manual journals | Merged | Balanced entries, independent review, posting, linked reversals and auditing; business-source journals and company statements are provided separately. |
| Posted ledger reports | Merged | Account ledgers, trial balance, journal drill-down and CSV; formal opening balances and snapshot sources are available; company balance sheet and income statement are provided separately. |
| Period closing | Implemented | Check and close ended periods in order, lock historical valuations/allocations, reopen in reverse order, retain every archive and audit. |
| Business-source journals | Implemented | Configurable accounts, source recomputation, purchase variances and sales-cost entries, atomic deduplication, source snapshots and posted-source protection; independent review remains required. |
| Profit transfer | Implemented | Company account scope, period-end drafts, independent review, source protection, reverse-order corrections and zero-balance closing checks. |
| Company financial statements | Implemented | Project/account mappings, balance sheet and income statement, source drill-down, CSV, configuration audit and fixed archives for closed periods. |
| Auxiliary accounting | Implemented | Customer/supplier/department/project dimensions, required account rules, split openings, grouped transfers, balances, sources, auditing and CSV. |
| [Historical subsidiary openings](docs/subledger-openings.md) | Implemented | Per-document imports reconcile by complete auxiliary combination to confirmed ledger openings, with independent review, settlement/refund/reversal records, journal sources, auditing and CSV. |
| Full financial accounting | Planned | Cash flow, statutory templates, taxes, multiple currencies and bank reconciliation. |
| [Customer relations and quotations](docs/customer-relations.md) | Basic flow implemented | Shared customer master, follow-up tasks, opportunities, fixed quotations, independent approval and acceptance evidence to sales drafts; marketing, forecasts, attachments and notification scheduling remain. |
| [Production quality and rework](docs/quality-rework.md) | Basic flow implemented | Partial scrap/rework dispositions, independent review, source-cost carry-in, reinspection and audited correction. |
| [After-sales (Chinese)](docs/after-sales.md) | Basic flow implemented | Original-shipment cases, independent review, return/exchange drafts, repair custody, inspection, handover and explicit fees/corrections. |
| [Equipment maintenance (Chinese)](docs/equipment-maintenance.md) | Basic flow implemented | Register, calendar plans, independent review/acceptance, assigned execution, downtime, material source documents and audited correction; telemetry and full asset accounting remain. |
| Business expansion | Planned | Finite-capacity scheduling, full quality, advanced after-sales, deeper CRM/equipment, HR and multiple organizations. |
| Data and devices | Planned / acceptance pending | MySQL and offline sync are not implemented; cross-platform devices, unattended startup and recovery drills need acceptance. |

Candidate sequencing and entry conditions are in the [expansion assessment (Chinese)](docs/erp-expansion-assessment.md). Build success does not replace device or business acceptance.

## Development entry points

Requires Node.js 22.12+ and Python 3.11+. Setup, architecture, business constraints, testing, **build instructions**, backup/restore and website publishing now live in the detailed guide:

- [English development guide](docs/development.en.md)
- [中文开发文档](docs/development.zh-CN.md)

Run `npm run docs:build` to generate a local HTML website and bilingual guide. GitHub Pages configuration is included, with hosting intentionally not enabled yet. Installer artifacts go to `release/` and remain unsigned/unnotarized; see the guide for commands.

Material management now includes production details, fixed categories and server-generated category codes. See [material catalog rules (Chinese)](docs/material-catalog.md). Upgrade both client and server.
