# Nexora ERP development guide

[简体中文](development.zh-CN.md) · [Project overview](../README.en.md)

This guide covers setup, architecture, business boundaries, testing and building. Status reflects database version 74, auditable bank balance reconciliation with opening outstanding items, journal attachments and after-sales case attachments. [Home statistics (Chinese)](home-statistics.md) use one ORM read snapshot and existing permissions for business net amounts, daily sources, effective documents and current pending work/stock. Database version 74 has 170 static ORM tables. [Equipment maintenance (Chinese)](equipment-maintenance.md) provides the register, calendar plans and manual-meter operating-hour plans, independent execution/acceptance, downtime and original material documents; declared service costs do not create payables or journals. Bilingual documentation does not mean the application supports an English UI.

## Environment and startup

Requires Node.js 22.12+, npm and Python 3.11+. Use a project virtual environment so development and packaging share an interpreter. CI uses Node.js 22 and Python 3.13.

Windows PowerShell, from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
npm ci
python -m pip install -r backend/requirements-dev.txt
$env:NEXORA_PYTHON = (Resolve-Path .venv/Scripts/python.exe).Path
npm run dev
```

macOS, from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
npm ci
python -m pip install -r backend/requirements-dev.txt
export NEXORA_PYTHON="$PWD/.venv/bin/python"
npm run dev
```

The desktop starts Python when creating a host. Development hosts stop when the desktop explicitly exits; packaged OS services run independently of windows and login sessions. `NEXORA_PYTHON` selects an interpreter explicitly. On Windows, `python` replaces `python3` in other examples.

To debug the backend separately, start at the repository root:

```bash
cd backend
python -m app.server --data-dir ../.temp/nexora-dev-data --name "Development host" --port 8000
```

This temporary directory is for development; use durable storage for real data. Startup handles migrations, certificates and HTTPS. `GET /api/v1/health` checks the process/database; `GET /api/v1/server/info` returns public identity and initialization state. See the [backend guide (Chinese)](../backend/README.md) for APIs and permissions.

## Architecture and directories

```text
Vue views → Pinia state/actions → restricted preload → Electron main
                                                         ↓ HTTPS
                                 FastAPI permissions/business → ORM → SQLite
```

| Path | Responsibility |
| --- | --- |
| `src/main/` | Windows, IPC, server startup, certificate trust, discovery and OS services. |
| `src/preload/` | Minimal bridge without exposing privileged Node/Electron objects. |
| `src/shared/` | Shared types and protocols. |
| `src/renderer/src/` | Vue views, Pinia, routing, shared components and themes. |
| `backend/app/main.py` | FastAPI lifecycle and route assembly. |
| `backend/app/access/`, `catalog/` | Authorization, navigation icons, suppliers and materials. |
| `backend/app/purchase/`, `inventory/`, `sales/` | Purchasing, warehousing and sales. |
| `backend/app/production/`, `finance/`, `reports/` | Production, costs/operational finance/ledger foundations, business reports. |
| `backend/app/core/`, `service/` | ORM models, sessions, historical migrations, service state and operations. |
| `backend/app/server.py`, `backup.py`, `backend/launcher.py` | Stable server, backup and packaged command entry points. |
| `tests/`, `backend/tests/` | Desktop interfaces/behavior and backend tests. |
| `docs/`, `docs/site/` | Topic documents, bilingual guide and website styles. |

### Frontend conventions

Place views in the appropriate `views/workspace/` business domain, with page-only data/styles alongside them. Shared components are grouped into `app/`, `feedback/` and `workspace/`; component logic goes in `composables/`, helpers in `utils/`. See the [onboarding directory (Chinese)](../src/renderer/src/views/onboarding/README.md) and [workspace directory (Chinese)](../src/renderer/src/views/workspace/README.md).

Pinia owns sessions, themes, server snapshots and business actions, with one instance per window. New modules use `storeToRefs` for reactive state and access actions directly. Preserve the existing `useAppStore()` compatibility entry; do not create another `provide/inject` store. Root components assemble theme/messages and lifecycle subscriptions and release them on cleanup.

Vue Router uses hash addresses. New entries update `workspace-routes.ts`, `router/index.ts`, directory documentation and route tests. The [route table (Chinese)](workspace-routing.md) defines pages and viewing permissions.

`App.vue` supplies Naive UI language/themes through `NConfigProvider`. Tailwind CSS 4 enters through `style.css`, with Preflight disabled to preserve existing styles. Lists reuse `WorkspaceTable`, combining filters/actions and supporting wrapping and horizontal scrolling in narrow windows. Trees/forms retain their appropriate structure. Follow the [frontend UI guide (Chinese)](frontend-ui-guidelines.md).

Import Remix Icon on demand, for example `import IconRefreshLine from '~icons/ri/refresh-line'`; SVGs are compiled into the app without online requests. The brand source is `resources/nexora-nexus-aurora-logo.png`. Install Pillow and run `python scripts/create-icons.py`; headers/sidebars use `icon.png`, trays use `tray.png` and `tray@2x.png`.

`tsconfig.json` associates web/Electron projects; `npm run typecheck` checks both. Renamed pages can leave TS2307 in obsolete editor tabs; close them and open the current files. Windows hides the default in-window menu, while macOS retains its system menu. Main-process changes require restarting the app. `i18n/` currently extracts only some Chinese text.

### Backend and data conventions

Business reads/writes use SQLAlchemy 2.0 declarative models and ORM sessions. Existing migration is complete; see the [migration checklist (Chinese)](backend-orm-migration.md). Money uses Decimal and exact text storage. Reads use consistent snapshots; writes acquire a lock before validation, roll back as a whole on failure and release connections.

Schema migrations, SQLite transaction/foreign-key/timeout configuration, online backups and integrity diagnostics retain necessary low-level operations; these exceptions must not serve business CRUD. Static models do not reflect/replace historical tables at startup. `create_all` cannot replace old-database migrations. ORM adoption does not make MySQL available.

Put new APIs in their feature directory and assemble them in `main.py`, using explicit `app.<feature>.<module>` imports without cycles. Update permissions, shared types, error semantics and callers together. Validate inputs, paths, IPC and network responses at boundaries. Keep `contextIsolation`; do not bypass boundaries using `nodeIntegration`. Prefer Chinese development comments.

## Business rules and boundaries

| Area | Existing rules/corrections | Current boundary |
| --- | --- | --- |
| Master data | Material/supplier/warehouse CRUD with reference/default-warehouse deletion protection; independent customer search/create; idempotent supplier bindings. | Customer relations and quotations are provided separately; no full marketing automation or purchasing selection restrictions; supplier pagination does not cover every list. |
| Purchasing | Approved requests can split; draft orders reserve allowance. Accepted receiving creates pending receipts; posting adds stock/payables. Returns await warehouse shipment. | Receiving does not add stock; request approval does not yet require a different person. |
| Sales | Partial shipments check remaining quantity/stock in one transaction; returns reference original lines/prices. | Refunds are separately recorded, not automatically paid. |
| Warehousing | Single posting, two-sided transfers, stocktake snapshots/change checks; adjustments need independent approval and warehouse posting. | Not a general approval engine; full physical batch tracing remains future work. |
| Reversals | Preserve originals, append inverse movements/amount sources and reasons; check stock, dependent returns and duplicate correction. | Rules differ by document; deleting history/overwriting balances is not correction. |
| Valuation | Company-level material moving average; returns/transfers use source costs; eligible unknown inputs can be manually valued with revision history. | Revisions may change open-period costs; historical valuation and allocation are locked through the last closed period. Variances and formal COGS journals remain. |
| Production | BOM versions/cycle checks, frozen requirements, partial issues/returns/completions and accepted-goods receipt; consumed reporting requirements cannot be returned. | Targets include rejected quantities; [MRP quantity/date planning (Chinese)](material-planning.md) is available; [quality dispositions and rework (Chinese)](quality-rework.md) are available; finite-capacity scheduling and full quality management remain. |
| Finished-goods cost | Inventory issue price first, manual valuation when unknown; material/labor/overhead split into accepted-goods, independent-loss and rework carry-in pools, with accepted-goods costs allocated by accepted quantity and rounding reconciliation. | Normal scrap is absorbed by accepted goods; unknown rework carry-in blocks settlement, and old settlements retain their original basis. Reverse dependent settlements before corrections. Full WIP/cross-period cost remain. |
| Operational finance | Sources produce receivables/payables and order balances; manual settlements/refunds have limits and inverse reversals; historical subsidiary openings reconcile by complete combination before independent activation and settlements; bank lines can be entered manually or imported from CSV, matched to payments, and reconciled with posted journals through grouped matching, opening outstanding-item migration and clearance, balance adjustments and independent review. | Imported files do not prove authentic bank evidence; RMB scope, taxes, multiple currencies and bank feeds remain. |
| Ledger foundations | Flat account structures are fixed; inclusive periods cannot overlap. Name/activation changes carry versions, reasons and transactional auditing. | Closing/reopening is provided separately; auxiliary accounting is provided separately. |
| Period closing | Close ended periods in order, reopen in reverse order; archive balances/cost sources and lock historical valuation/allocations. | Does not generate business journals, profit transfer or statutory statements. |
| Reports | Purchasing execution, receiving/returns, stock balances/movements and CSV. | Business summaries are not formal financial statements. Dashboard demo charts are not actual business metrics. |
| Posted ledger reports | Trial balance, account ledgers, journal/reversal drill-down and snapshot CSV, current activity counts posted journals only, while confirmed opening balances are carried separately. | Without formal opening setup, openings only accumulate historical posted entries and do not represent business acceptance; company balance sheet and income statement are provided separately. |
| Company financial statements | Company project/account mappings, balance sheet and income statement, journal drill-down, CSV, configuration audits and fixed archives for closed periods. | No statutory templates, cash-flow statement, notes or tax filing; missing formal openings are explicitly flagged, and business/device acceptance remains necessary. |

Formal opening setup is available before any journal is posted, with independent review/confirmation, versioned auditing and reversal before posting. It does not add current activity or generate subsidiary opening balances. See [opening balance rules (Chinese)](opening-balances.md).

[Customer relations and quotations (Chinese)](customer-relations.md) provide contacts, follow-ups, manual opportunity probabilities and visible-scope weighted forecasts, independently approved frozen quotes, PDF export of approved quotes, and acceptance evidence to sales drafts, without posting stock or revenue. See [cost settlement rules (Chinese)](production-cost-settlement.md), [ledger foundations (Chinese)](ledger-foundation.md) and [manual journals (Chinese)](manual-journals.md). Manual journals support balanced entries, independent review, posting and linked reversals, with fixed posted snapshots and auditing. Business-source journal drafts are available; see [business journal rules (Chinese)](business-journals.md). Profit transfer drafts with independent review, source protection and zero-balance closing checks are available; see [profit transfer rules (Chinese)](profit-transfers.md). Cash flow, statutory statement templates, full quality management, advanced after-sales, deeper CRM marketing/forecast modeling, equipment telemetry/full asset accounting, HR, multiple organizations, MySQL and offline synchronization remain future work. Entry conditions are in the [expansion assessment (Chinese)](erp-expansion-assessment.md).

Closing conditions, historical locks and archive boundaries are in [period closing rules (Chinese)](period-closing.md).

Posted ledger query rules and source tracing are described in [posted ledger reports (Chinese)](ledger-reports.md).

## Connections, services and backups

On first launch, connect manually, scan the LAN or create a local host with name, directory, port and first administrator. Existing databases are not overwritten. Only loopback requests can create the first administrator; passwords need at least 12 characters. Administrators maintain later accounts/roles, with server authorization on each action. Deactivation/password changes invalidate old sessions; at least one enabled built-in administrator remains.

Before signing in to another computer, compare the complete SHA-256 fingerprints shown at both ends. Connection records store address, identity and certificate, not passwords. Changed certificates block automatic reconnection. Switching instances logs out; data is not merged. An expired address can recover only through matching identity/certificate, potentially requiring another login.

mDNS queries use current LAN IPv4 interfaces and release previous discovery on rescan. Allow UDP 5353 multicast and the selected HTTPS port. Manual connection success does not prove discovery works. macOS may require local-network permission; Windows needs private-network access. With blocked multicast, use a manual address and verify the fingerprint again.

Packaged hosts register Windows services or macOS LaunchDaemons. Installation/manual start-stop requires administrator authorization. Closing windows keeps the tray; double-click/open restores them. The tray shows/refreshes/stops the local service. Exiting the desktop does not stop installed services, which can run without login; real devices still need acceptance.

Protect `nexora.db`, `server.crt` and `server.key` together. Use SQLite online backup instead of copying a live database. Commands are described in the [backend backup guide (Chinese)](../backend/README.md):

```bash
cd backend
python -m app.backup --help
python -m app.backup backup --data-dir /path/to/instance --output /path/to/instance.nexora-backup
python -m app.backup restore --archive /path/to/instance.nexora-backup --data-dir /path/to/new-instance
```

Create and inspect a backup, then restore into an empty directory without overwriting a database. Stop the service and retain old data before switching. Losing the private key requires renewed trust. Settings can upgrade the service using the current installer, with grouped backups and rollback on failure. See the backend guide for paths/parameters, and the [device checklist (Chinese)](lan-host-acceptance.md) for cross-platform, unattended restart, upgrade and recovery acceptance. CI does not replace real devices.

## Testing and workflow

Follow [AGENTS.md (Chinese)](../AGENTS.md): one `codex/<requirement>` branch per requirement; check branch/workspace first and finish existing work before another requirement. Independent parallel worktrees require user authorization. Preserve existing changes; read modules/types/tests and cover new behavior, failures, concurrency and rollback risks.

Windows PowerShell, from the repository root:

```powershell
npm run typecheck
$desktopTests = @(Get-ChildItem tests -Filter '*.test.mjs' -File | ForEach-Object { $_.FullName })
node --experimental-strip-types --test $desktopTests
$env:PYTHONPATH = 'backend'
python -m pytest backend/tests -q
npm run build
```

macOS, from the repository root:

```bash
npm run typecheck
node --experimental-strip-types --test tests/*.test.mjs
PYTHONPATH=backend python -m pytest backend/tests -q
npm run build
```

PowerShell does not expand native-command wildcards, so enumerate tests. `npm run build` includes typechecking; `npm run preview` previews an existing build. Website-specific checks:

```bash
node --test tests/docs-site.test.mjs tests/docs-cover.test.mjs tests/docs-sandbox.test.mjs tests/docs-webgl.test.mjs tests/docs-gallery.test.mjs
npm run docs:build
```

Finish implementation, unit tests, required checks/builds and docs before committing/pushing a PR. Merge after platform checks pass. Use concise Chinese commit titles matching the changes. Ask before deleting merged branches. Report checks that cannot run; do not delete/skip old tests.

## Build instructions

### Desktop build

```bash
npm ci
npm run build
npm run preview
```

Desktop output goes to `out/`, without installers. The website separately outputs to `dist/site/`.

### Windows x64 installer

On a Windows x64 host, using the project virtual environment:

```powershell
python -m pip install -r backend/requirements-dev.txt "pyinstaller>=6,<7"
npm run dist:win
```

### macOS Apple Silicon installer

On an Apple Silicon Mac, using the project virtual environment:

```bash
python -m pip install -r backend/requirements-dev.txt 'pyinstaller>=6,<7'
npm run dist:mac
```

Run `npm ci` first on both platforms. Packaging builds the backend, then checks/builds the desktop and produces NSIS x64 or DMG arm64 through electron-builder. Interpreter priority is `NEXORA_PYTHON`, project `.venv`, then system Python. Dependency checks fail early. PyInstaller must build on the target OS; Windows cannot cross-build the Mac service. Ignored output goes to `release/`, with caches in `build/`.

### CI and release boundaries

Windows/macOS installer workflows test and upload builds on main/requirement pushes, main PRs and manual runs. Windows checks installation/runtime. macOS checks the packaged service, user/system startup and recovery, upgrade rollback and backup/restore. See the [workflow directory](../.github/workflows/).

Actions installers are test builds, unsigned/unnotarized, and may trigger SmartScreen or Gatekeeper. Cross-platform devices, unattended startup and recovery drills remain pending. Do not describe other architectures, signing or production readiness as implemented.

## Website and HTML documentation

The cover adds real interface satellites and a Materials → Inventory → Production → Finance path. `product-orbit.mjs` connects the cover, five interface previews, three-window stage and documentation margins through a transparent WebGL orbit. Paths draw and retract with scroll reading progress, while cards enter, become fully readable in the center, and recede. Light points follow scroll rather than an independent timer. Each scroll frame reads untransformed layout nodes before updating poses, without throttling or catch-up interpolation; the sticky stage entrance stays at its natural layout position. Rendering stops when scrolling stops or the page is hidden. Mobile uses SVG scroll paths and light card motion; reduced motion retains fully visible static images and paths. HTML retains text, screenshots and clicks, including when GPU rendering fails. The shared orbit sits above whitespace and gradients but behind real interface cards and the business stage, allowing solid surfaces to naturally occlude the line. Heading and caption containers are transparent; compact backgrounds protect only the text. The main element does not create a stacking context. WebGL and SVG share this ordering and never receive pointer input; navigation and native image dialogs remain in front.

The homepage ends with a bilingual “Stay tuned” section before the footer. The headline, background ellipse and orbit share one center, with hanging punctuation for optical alignment. The main path continues from the document ending into a full tilted orbit around the text. Its descending and orbiting parts form one continuous path with one arc-length progress and moving endpoint. A fainter orbit tilts in the other direction around the same center. The main orbit closes without crossing the text or continuing to the footer. The scroll-driven loop shares the existing full-page WebGL canvas and stops when idle or offscreen. Mobile, reduced motion and GPU failure use SVG; reduced motion keeps full static paths. Without scripts, text, the CSS loop and the native return-to-top link remain available.

The opening sequence lasts about 1.14 seconds: headline lines appear in sequence, supporting copy and actions follow, and the real interface satellites enter from the sides. `hero-entrance.mjs` updates the orbit only during this finite entrance and stops afterward. Scrolling, touch, clicks or keyboard focus immediately settle the entrance. Restored positions outside the cover and reduced motion remain immediately readable without waiting for business views. A synchronous head script chooses the initial entrance mode before rendering. Initial positioning is instant; smooth navigation is enabled two frames after load for subsequent clicks, preventing a glimpse of the cover before reaching an anchor. Without scripts, content remains fully visible. Cover entry uses the actual scroll position. Reloading at the top plays the entrance even with a retained fragment; zero-position scroll notifications do not cancel it. Anchors and restored positions below the cover remain instant and settle the entrance without resetting the reader's position.

The three stage windows are read-only HTML presentations generated directly into the website. The build extracts the workspace, light-theme, shared-table and title-bar styles from the project and scopes every selector to `.erp-display`. Business fields use 150% of the project’s 13px text size. `workspace-display.mjs` provides the presentation structure; `scripts/site-display.mjs` extracts CSS; `source-details.mjs` measures local field offsets and applies one camera matrix to the content and linked outlines. Receipt #101 keeps quantities 200 / 2000 / 1000 and CNY 4000 / 400 / 400. Invalid fields hide only their links. Mobile supports panning and reduced motion keeps a static view. The website embeds no iframe and starts no App, Vue, Pinia, business router or production connection. The independent Vue screenshot tool remains available to maintainers and is not included in the published website.

The website uses a static HTML/CSS/JavaScript build. `scripts/build-docs-site.mjs` uses Marked to convert version-controlled Markdown without business APIs, a database or browser-side Markdown compilation. Chinese lives at `/zh-CN/`, English at `/en/`, with `development.html` for each guide; the root opens Chinese.

| File | Maintenance |
| --- | --- |
| `README.md`, `README.en.md` | Update Chinese/English features and progress together. |
| `docs/development.zh-CN.md`, `docs/development.en.md` | Guide content sources; HTML is generated. |
| `docs/site/site.css` | Website, documentation, mobile and print styles. |
| `scripts/build-docs-site.mjs` | Page, contents, path and asset generation. |
| `docs/site/source-details.mjs` | Original-page camera transforms, actual row geometry validation and linked material evidence. |
| `docs/site/product-orbit.mjs` | Full-page scroll orbit, card entry and exit, stable layout nodes and SVG fallback. |
| `docs/site/hero-entrance.mjs` | One-time cover entrance coordination, interruption, motion preferences and cleanup. |
| `docs/site/product-showcase.*`, `product-gallery.mjs` | Interface screenshots, bilingual captions, load failures and native image dialog. |
| `docs/site/screenshots/`, `scripts/site-preview/` | Screenshot assets, isolated capture session and separately bundled read-only component entry. |
| `.github/workflows/docs-site.yml` | PR validation, explicit manual publishing and optional mainline Pages publishing. |

Build with `npm run docs:build`, then run `python -m http.server 4173 --directory dist/site` and visit `http://localhost:4173/`. Language links retain the page type. Text and contents work without JavaScript. Existing specialist documents remain in Chinese, clearly labeled in this guide.

The cover identifies Nexora as a desktop ERP for internal company use. Its primary action opens the business demo; the secondary action opens core capabilities. Five real-component screenshots sit between the cover and demo: the workspace overview as the main image, followed by materials, inventory ledger, production costs and journals. All use a light theme at 1800 × 1200 and carry “Current interface preview · Sample data.” Images open in a native dialog and stack vertically on mobile; original links work without JavaScript. Copy explains electronic materials, traceable origins and business-finance links: business sources generate journal drafts for independent review before posting.

Run `npm run docs:preview-ui` for the isolated capture session. It loads the current App, Pinia, sidebar, top navigation, tabs and shared tables with fictional local fixtures, rejecting all unconfigured requests. It neither connects to production services nor writes business data. This provides interface captures rather than native desktop or service-connection acceptance; the [screenshot guide (Chinese)](site/screenshots/README.md) records dimensions and sample provenance. The application UI remains Chinese.

The three-window stage defaults to real purchase receipt, inventory ledger and financial origin components sharing purchase receipt #101, with focused detail views. Select “Business demo” for the independent interactive sandbox; switching preserves its state. A full receipt window appears first; inventory and payable windows enter from the right as the page scrolls, with WebGL paths connected to actual source anchors. It supports multiple receipts and materials, warehouse/supplier selection, receipt confirmation, stock filtering and tracing, and partial/full demo payments. Quantities use three fixed decimal places; money uses integer cents. Drafts do not produce movements, confirmation cannot repeat, confirmed receipts can only be copied to drafts, and payments cannot exceed the balance.

`sandbox.mjs` manages business state, `sandbox-ui.mjs` renders and mounts HTML controls, `scene-geometry.mjs` defines the shared HTML/WebGL projection, `motion.mjs` handles the camera and paths only, and `sandbox.css` styles the stage. Scrolling never changes business data, and no ERP service is contacted. In the same tab, a language-link click transfers data once through `sessionStorage`; refreshing restores the seed. Navigation still works if storage is unavailable. Step and overview buttons scroll to actual page positions. Expanded interaction can remain focused while idle, but any page scroll immediately exits focus and redraws from the scrollbar, with no pause/resume controls. Input focus cannot lock page scrolling. Mobile windows are stacked vertically; reduced motion disables movement. Without JavaScript, static business examples and documentation remain available.

`webgl-stage.mjs` uses native WebGL for contact shadows, diffuse light pools, grazing light and source connections. Frames use a single cool-gray edge without static plating or corner highlights. HTML controls share the 1400px camera layout. Entire desktop windows scale with their text sidebars intact; side windows use opposing 30° angles and stock uses 4°. HTML content mirrors are removed. Floor lighting uses projected base endpoints, span and scroll progress, combining cool/warm highlights, subtle material texture and a short contact shadow. The stage GPU layers never intercept input or draw continuously while idle. Context loss or unavailable WebGL restores the CSS/SVG fallback without resetting data. Mobile and reduced-motion modes retain static relationships without creating GPU contexts.

Manual switches fade old paths out and interpolate measured starting and destination window poses, avoiding per-frame table reflow and size jumps. Rapid switches continue from the displayed frame. Logical anchors share the window projection; paths only link onscreen, forward-ordered matching sources, clearing when windows retreat or cross and fading back into the overview. Page scrolling interrupts a focus transition immediately, using actual progress and remeasuring source anchors rather than leaving stale paths. Heights below 620px use a vertical layout; short landscape widths up to 1000px use mobile row cards so sticky stages cannot clip bottom controls.

Long records use pagination: 2 rows for receipt/payable lines, 4 for stock movements, and 3 for balances/payment history. Page numbers belong to presentation state; totals, confirmation and balances use all business records. Adding a material opens the last page. Confirmation reveals and focuses invalid fields on another page; removal/filtering clamps out-of-range pages. Desktop layout measures actual content, including expanded details and errors, before scaling windows and paths together. There are no internal scrolling containers. Overview keeps material, quantity and price; line amounts and removal controls appear in the expanded window.

Run `node --test tests/docs-site.test.mjs tests/docs-cover.test.mjs tests/docs-sandbox.test.mjs tests/docs-webgl.test.mjs tests/docs-gallery.test.mjs` to check page paths, business rules, motion stages and GPU lifecycle. See the [website motion and sandbox guide](site/motion-proposal.en.md).

The website preview is published at [https://zhangzzj2003.github.io/Nexora-Erp/](https://zhangzzj2003.github.io/Nexora-Erp/). README links and a clickable preview image open the full WebGL presentation; GitHub README itself shows only static content. An administrator enables GitHub Actions as the Pages source. Run `docs-site.yml` with `publish=true` on the selected website branch to publish without merging it. PRs and manual runs without this input only validate; only `dist/site/` is uploaded. `PAGES_ENABLED=true` separately enables automatic publication on mainline pushes and remains disabled during branch preview review. The `github-pages` environment must permit the selected publication branch.

See the [official GitHub Pages workflow guide](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages). Public output excludes databases, private keys, tokens and local logs. Check the source revision and both languages before publication. An explicitly requested branch preview does not mark the PR as merged or the application as accepted; the default-branch README updates only after a separately authorized merge.

Company statement configuration, archive rules and permissions are described in the [statement rules (Chinese)](financial-statements.md).

Auxiliary accounting uses static ORM models for four dimensions, versioned rules, split openings and grouped transfers; see [rules and desktop permission boundaries (Chinese)](auxiliary-accounting.md). [Historical subsidiary openings (Chinese)](subledger-openings.md) reconcile individual unsettled documents before independent activation and subsequent settlements, without adding ledger openings a second time.

## Production quality and rework

[Quality dispositions and rework (Chinese)](quality-rework.md) cover rejected completion quantities, explicit scrap-cost treatment, independently approved dispositions, additional-material work orders, reinspection and source-cost carry-in. Unknown parent cost blocks child settlement. Posted loss journals protect their sources, and period closing archives allocation evidence. This is a production-quality workflow, not a complete quality or after-sales suite.


## After-sales

[After-sales rules (Chinese)](after-sales.md) cover independently approved cases, return/exchange drafts, customer-owned repair custody, inspection, handover, explicit fees, auditable repair hours, case attachments and additive corrections. Customer goods do not become company stock. Closing freezes period-end plans, custody and repair-hour evidence. Automatic warranty decisions, serial numbers, labor costs and partial handovers remain future work.

Presentation content is included in the initial HTML and remains visible without JavaScript. The website build generates only static HTML/CSS/JavaScript and removes previous embedded-app build artifacts. Content versions cover modules and styles. Font and window changes only realign local fields and links without blocking the interface behind a loading screen.
