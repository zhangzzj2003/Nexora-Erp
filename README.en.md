# Nexora ERP

[简体中文](README.md) · [Live website](https://zhangzzj2003.github.io/Nexora-Erp/en/) · [Website source](docs/site/) · [Development guide](docs/development.en.md)

[![Open the Nexora website · WebGL business connections and sample interfaces](docs/site/website-preview.jpg)](https://zhangzzj2003.github.io/Nexora-Erp/en/)

A desktop ERP for internal operations, connecting purchasing, warehousing, sales, production and operational finance through traceable documents and stock movements. The desktop uses Electron, Vue 3, TypeScript and Pinia; the server uses FastAPI, SQLAlchemy and SQLite.

The desktop uses an integrated title bar across onboarding, login and the workspace. macOS retains native traffic lights at the upper left; Windows retains native window controls at the upper right. Branding, refresh, home, the current category/page directory and theme switching share the top row; page tabs occupy a separate fixed row below it, to the right of the sidebar. Empty title bar areas drag the window and Windows control icons follow the app theme. Windows controls use a transparent background so the page title bar, bottom divider and modal backdrop remain visible beneath them, avoiding a separate block in the upper right. Browser previews and Linux retain their native window frame, and closing a window retains the existing tray behavior.

The settings drawer provides six accent presets: teal, blue, indigo, violet, amber and rose, each adapted to light and dark modes. Shared table empty-state icons update their foreground, background and border with the accent; account avatar backgrounds, account-menu icons and onboarding identity-verification icons follow it as well. Success, warning, error and chart-category colors keep their existing meanings. On Windows, the settings panel starts below the 48px title bar, keeping its close button clear of native window controls. On macOS and Windows, in-app messages start 12px below the title bar and stack downward, keeping settings, theme and native window controls accessible.

Theme buttons morph between moon and sun and use a 450 ms circular transition: both directions reveal the new snapshot from the actual triggering button’s click position. Keyboard activation uses the button center. Percentage-based centers and radii keep live compositor clipping correctly scaled on Retina and other high-density displays, covering the farthest corner before the snapshot ends. Component and pseudo-element transitions pause during the snapshot to avoid continuing color changes and mid-animation flashes; browser animation timing is used without a fixed 30 fps cap. The theme entry is consolidated at the top and removed from the lower-left sidebar; The new snapshot is clipped before animation starts, then remains fully revealed until the paint handoff completes before normal styles resume, preventing a brief return to the old theme. A choice made during a reveal waits for that circle to finish, then only the latest choice continues, avoiding an abrupt full-page change when a mask is removed. Cancellation before capture does not wait for a timeout. Unsupported snapshots, reduced motion and capture failures fall back to a direct theme update. The motion is adapted from Vben; see [third-party notices](docs/third-party-notices.md).

The project is in an **internal trial phase for one company, multiple warehouses and online LAN clients**. Windows and macOS clients access centralized server data over HTTPS. Disconnected clients cannot submit changes. Documentation and the website are bilingual; the application UI remains Chinese. The website preview is published through GitHub Pages using sample data, without connecting to the production ERP service.

The directory follows the active route and offers permitted pages in the same category. Refresh reads authorized data before remounting the current page, retaining the login session and opened tabs. Independent pagination and dashboard queries reload as well. Repeated refresh and business submission are blocked during the operation; failures show a shared error message and can be retried. Browser and Linux workspaces provide the same controls above the content.

Material document dialogs share `WorkspaceDocumentDialog`: basic information appears above a divider and a shared material table, while the header close control and footer actions remain visible as the body scrolls. Other inbounds, warehouse outbounds, transfers, stocktakes, adjustments, purchase requests and conversion, purchase orders and receiving/returns, sales orders and shipments/returns, BOMs and production issues/returns use this layout. Editable material tables add rows through the searchable material selector, with a 100-row limit; source-linked documents retain their original line identifiers and quantity limits and do not allow arbitrary additions. Existing quantity, price and warranty rules remain in place. Busy dialogs block closing and editing; disconnected dialogs allow closing while blocking edits and saves. Reopening the same purchase-request draft retains its inputs, and failed saves preserve the draft. Naive UI card modals also share a contrasting header with an independently scrolling body.

## Project features

| Area | Current functionality |
| --- | --- |
| Accounts and permissions | Users, built-in/custom roles, document action permissions, account activation, password resets, permission trees and navigation icon settings. |
| Master data | BOM versions and component quantities; materials, suppliers, customers, warehouses and supplier-material relationships; server-side pagination for suppliers. |
| Purchasing | Request approval and split orders, orders, partial receiving, warehouse-confirmed receipts, returns awaiting shipment confirmation, and reversals. |
| Warehousing | Multi-warehouse stock, other inbounds/outbounds, transfers, stocktakes, independently approved adjustments, source movements and stock ledgers; [inventory warnings (Chinese)](docs/inventory-warnings.md) use per-warehouse thresholds, current quantities, versions and audit evidence. The [physical lot foundation (Chinese)](docs/physical-lot-tracing.md) provides unidentified historical openings, balance differences and source history; purchase receipts and other inbound confirmation can record actual lots per line; other-purpose outbounds, purchase returns, sales shipments and warehouse transfers can select existing lots per line; stocktake differences and inventory adjustments can be assigned to physical lots. |
| Sales | [Customer relations and quotations (Chinese)](docs/customer-relations.md) add contacts, follow-ups, opportunities and independently approved quotation conversion; orders, partial shipments, linked returns and reversals; confirmation checks remaining order quantities and stock. |
| Production | Frozen work-order requirements, partial material issues/returns, completion reports, basic inspection and lot-recorded accepted-goods receipts; [MRP (Chinese)](docs/material-planning.md) adds dated net requirements, fixed evidence, independent approval and draft conversion; [equipment maintenance (Chinese)](docs/equipment-maintenance.md) adds calendar and manually recorded operating-hour plans, independent execution/acceptance, downtime, material sources and asset/job attachments. |
| Cost and operational finance | Moving-average valuation, manual valuation of unknown costs, material/labor/overhead collection, finished-goods cost allocation, receivable/payable sources, manual payments and reversals. |
| General ledger | Accounts, periods, independently reviewed/confirmed opening balances, independently reviewed/posted/reversed manual and business-source journals with [attachments](docs/journal-attachments.md), posted account ledgers and trial balance; ordered closing, reverse-order reopening and archived balances/cost evidence. |
| Reports and operations | Basic purchasing/inventory reports and CSV; [live home statistics (Chinese)](docs/home-statistics.md) show authorized business net amounts, trends and current pending documents/stock; LAN discovery, certificate fingerprint trust, OS services, backup/restore and upgrade backups. |

Stock and financial changes retain sources, operators and correction records. Confirmation and movements commit together. Unknown prices remain unknown instead of becoming zero. Manual payments and basic inspection do not prove bank settlement or physical verification.

## Development progress

Snapshot: **2026-10-03, physical lot data foundation**. Work in progress is not delivered mainline functionality. Progress describes capabilities rather than an undefined percentage.

| Stage | Status | Delivered / next steps |
| --- | --- | --- |
| Purchasing–inventory–sales–production flow | Basic flows implemented | Partial receipts/shipments, returns, corrections and tracing; complex cases remain. |
| Backend data access | Migration complete | Existing business access uses ORM; migrations, SQLite configuration and online backup retain necessary low-level operations. |
| Inventory and finished-goods costs | Foundation implemented | Moving-average valuation and batch allocations; variances, work in progress and cross-period costs remain. |
| Ledger master data | Merged | Accounts, periods and auditing; period closing is provided separately. |
| Formal opening balances | Implemented | First setup before any posted journal, independent review/confirmation, versions and audit, reversal before posting; excluded from current activity. |
| Manual journals | Merged | Balanced entries, independent review, posting, linked reversals, auditing and journal attachments; business-source journals and company statements are provided separately. |
| Posted ledger reports | Merged | Account ledgers, trial balance, journal drill-down and CSV; formal opening balances and snapshot sources are available; company balance sheet and income statement are provided separately. |
| Period closing | Implemented | Check and close ended periods in order, lock historical valuations/allocations, reopen in reverse order, retain every archive and audit. |
| Business-source journals | Implemented | Configurable accounts, source recomputation, purchase variances and sales-cost entries, atomic deduplication, source snapshots and posted-source protection; independent review remains required. |
| Profit transfer | Implemented | Company account scope, period-end drafts, independent review, source protection, reverse-order corrections and zero-balance closing checks. |
| Company financial statements | Implemented | Project/account mappings, balance sheet and income statement, source drill-down, CSV, configuration audit and fixed archives for closed periods. |
| Auxiliary accounting | Implemented | Customer/supplier/department/project dimensions, required account rules, split openings, grouped transfers, balances, sources, auditing and CSV. |
| [Historical subsidiary openings](docs/subledger-openings.md) | Implemented | Per-document imports reconcile by complete auxiliary combination to confirmed ledger openings, with independent review, settlement/refund/reversal records, journal sources, auditing and CSV. |
| [Bank statement matching and balance reconciliation](docs/bank-reconciliation.md) | Basic flow implemented | Manual and CSV bank lines, payment matching, ledger account binding, grouped matching to posted journal lines, unreached-item adjustments, immutable reports and independent review. Original bank evidence still requires human verification. |
| Full financial accounting | Planned | Cash flow, statutory templates, taxes, multiple currencies, bank feeds and opening unreached-item migration. |
| [Customer relations and quotations](docs/customer-relations.md) | Basic flow implemented | Shared customer master, follow-up tasks, opportunities, fixed quotations, independent approval, contact, follow-up, opportunity and quote attachments, and acceptance evidence to sales drafts; marketing, deeper forecasting and notification scheduling remain. |
| [Production quality and rework](docs/quality-rework.md) | Basic flow implemented | Partial scrap/rework dispositions, independent review, source-cost carry-in, reinspection and audited correction. |
| [After-sales (Chinese)](docs/after-sales.md) | Basic flow implemented | Original-shipment cases, independent review, return/exchange drafts, repair custody, inspection, handover, attachments and explicit fees/corrections. |
| [Equipment maintenance (Chinese)](docs/equipment-maintenance.md) | Basic flow implemented | Register, calendar and manually recorded operating-hour plans, independent review/acceptance, assigned execution, downtime, material source documents and audited correction; telemetry and full asset accounting remain. |
| [Inventory warnings (Chinese)](docs/inventory-warnings.md) | Foundation implemented | Per-warehouse thresholds, shortages, low stock, enable/disable, versions and audit. The desktop window shows scheduled state-change alerts and system notifications when unfocused; the server records warning events about every 60 seconds, and a signed-in tray process can poll new events after the window closes. Server-initiated push and demand forecasting are not provided. |
| [Physical lot tracing (Chinese)](docs/physical-lot-tracing.md) | Inbound and outbound source foundation | Unidentified historical openings, difference diagnostics and source history; purchase receipts, other inbounds and accepted production completions can record multiple lots; other-purpose outbounds, purchase returns, sales shipments and warehouse transfers can select existing lots; stocktake differences and inventory adjustments can use existing or newly created lots. Where supported, reversals follow original allocations. Production material issues can select source-warehouse lots; material returns can reenter original issue lots or record a new returned lot; unidentified historical openings can be reclassified with recorded field evidence; legacy-client movements after the upgrade checkpoint support audited per-movement, paired inbound/outbound, or atomic multi-pair reconciliation and reversal, while older movements without a recoverable checkpoint and out-of-order or cross-warehouse matches remain unresolved; sales returns can reenter original shipment lots or record a new returned lot. |
| Business expansion | Planned | Finite-capacity scheduling, full quality, advanced after-sales, deeper CRM/equipment, HR and multiple organizations. |
| Data and devices | Planned / acceptance pending | MySQL and offline sync are not implemented; cross-platform devices, unattended startup and recovery drills need acceptance. |

Candidate sequencing and entry conditions are in the [expansion assessment (Chinese)](docs/erp-expansion-assessment.md). Build success does not replace device or business acceptance.

### Document numbering

The server assigns stable business numbers to 29 core document and independent payment types. A centered three-step guide lets administrators choose pinyin initials or English prefixes, select a server, UTC or specified IANA time zone, and review the policy on first login, including after an existing database upgrade. Historical backfill and the initial policy lock commit atomically, while references, physical lots and frozen evidence remain intact. See [document numbering rules](docs/document-numbering.md). The complete lot traceability page remains planned.

## Development entry points

Requires Node.js 22.12+ and Python 3.11+. Setup, architecture, business constraints, testing, **build instructions**, backup/restore and website publishing now live in the detailed guide:

- [English development guide](docs/development.en.md)
- [中文开发文档](docs/development.zh-CN.md)

Run `npm run docs:build` to generate a local HTML website and bilingual guide. The website is published manually through GitHub Pages; open the link at the top for the full interactive presentation. Installer artifacts go to `release/` and remain unsigned/unnotarized; see the guide for commands.

Material management now includes production details, fixed categories and server-generated category codes. See [material catalog rules (Chinese)](docs/material-catalog.md). Upgrade both client and server.

Production BOM is listed under Master data and uses the shared document dialog for product details and editable component rows. Its existing URL, production permissions and fixed work-order version references are preserved.
