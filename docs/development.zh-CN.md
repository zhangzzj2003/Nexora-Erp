# Nexora ERP 开发文档

[English](development.en.md) · [项目介绍](../README.md)

整合开发环境、架构、业务边界、验证与构建说明。状态按第 67 版生产退料冲销能力更新；[首页统计](home-statistics.md) 使用同一 ORM 读取快照，按原有权限返回净额、逐日来源、有效单据与当前待办/库存。数据库为第 67 版，149 张静态 ORM 表；[设备维护](equipment-maintenance.md)已提供台账、日历及人工读数触发的运行小时保养、独立执行验收、停机与耗材原单，声明费用不自动生成应付或总账。文档双语不表示应用界面已支持英文。

## 环境与启动

需要 Node.js 22.12+、npm、Python 3.11+。建议使用项目虚拟环境，让开发与打包采用同一解释器。CI 使用 Node.js 22、Python 3.13。

Windows PowerShell，在仓库根目录运行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
npm ci
python -m pip install -r backend/requirements-dev.txt
$env:NEXORA_PYTHON = (Resolve-Path .venv/Scripts/python.exe).Path
npm run dev
```

macOS，在仓库根目录运行：

```bash
python3 -m venv .venv
source .venv/bin/activate
npm ci
python -m pip install -r backend/requirements-dev.txt
export NEXORA_PYTHON="$PWD/.venv/bin/python"
npm run dev
```

桌面应用在“新建服务端”时启动 Python 服务。开发服务依附桌面进程，明确退出后停止；安装版系统服务独立于窗口与登录会话。`NEXORA_PYTHON` 可显式指定解释器；Windows 的 `python` 对应其他说明中的 `python3`。

单独调试后端，从仓库根目录执行：

```bash
cd backend
python -m app.server --data-dir ../.temp/nexora-dev-data --name "开发服务端" --port 8000
```

示例临时目录仅用于开发，正式数据选持久目录。服务负责迁移、证书和 HTTPS 监听。`GET /api/v1/health` 检查进程和数据库，`GET /api/v1/server/info` 返回公开实例身份及初始化状态。接口与权限详见 [后端说明](../backend/README.md)。

## 架构与目录

```text
Vue 页面 → Pinia 状态与操作 → 受限 preload → Electron 主进程
                                                ↓ HTTPS
                                  FastAPI 权限与业务 → ORM → SQLite
```

| 路径 | 职责 |
| --- | --- |
| `src/main/` | 窗口、IPC、服务启动、证书信任、发现及系统服务。 |
| `src/preload/` | 最小必要预加载桥接，不暴露 Node/Electron 高权限对象。 |
| `src/shared/` | 共享类型与协议。 |
| `src/renderer/src/` | Vue 页面、Pinia、路由、公共组件及主题。 |
| `backend/app/main.py` | FastAPI 生命周期与路由装配。 |
| `backend/app/access/`、`catalog/` | 账号授权、导航图标、供应商和物料资料。 |
| `backend/app/purchase/`、`inventory/`、`sales/` | 采购、仓库与销售业务。 |
| `backend/app/production/`、`finance/`、`reports/` | 生产、成本/业务财务/总账基础、业务报表。 |
| `backend/app/core/`、`service/` | ORM 模型、会话与历史结构迁移、服务状态及运维。 |
| `backend/app/server.py`、`backup.py`、`backend/launcher.py` | 稳定的服务、备份和打包命令入口。 |
| `tests/`、`backend/tests/` | 桌面接口/行为与后端测试。 |
| `docs/`、`docs/site/` | 专题、双语指南与官网样式。 |

### 前端开发约定

页面放在 `views/workspace/` 对应业务域，仅本页使用的数据和样式与页面同目录。共享组件按 `app/`、`feedback/`、`workspace/` 分类；组件级逻辑放 `composables/`，辅助函数放 `utils/`。见 [引导目录](../src/renderer/src/views/onboarding/README.md)、[工作台目录](../src/renderer/src/views/workspace/README.md)。

会话、主题、服务快照与业务操作统一由 Pinia 管理，每个窗口独立实例。新增模块用 `storeToRefs` 解构状态，操作方法直接取自 store。保留现有 `useAppStore()` 的 `ref` 兼容入口，不新建 `provide/inject` store。根组件统一装配消息/主题和生命周期，释放订阅。

Vue Router 使用 Hash 地址。新增入口同步 `workspace-routes.ts`、`router/index.ts`、页面目录与路由测试；页面和查看权限以 [路由表](workspace-routing.md) 为准。

Naive UI 语言和主题由 `App.vue` 的 `NConfigProvider` 提供；Tailwind CSS 4 入口为 `style.css`，保留现有样式而未开启 Preflight。列表复用 `WorkspaceTable`，工具栏合并筛选与操作，窄窗口支持换行/横向滚动，权限树和表单保留各自结构。遵循 [前端 UI 规范](frontend-ui-guidelines.md)。

Remix Icon 按需导入，例如 `import IconRefreshLine from '~icons/ri/refresh-line'`，构建为 SVG，无需在线服务。品牌源文件为 `resources/nexora-nexus-aurora-logo.png`；安装 Pillow 后运行 `python scripts/create-icons.py`，页眉/侧栏使用 `icon.png`，托盘用 `tray.png` 和 `tray@2x.png`。

`tsconfig.json` 关联网页/Electron 类型项目，`npm run typecheck` 分别检查。页面重命名后旧编辑器标签可能残留 TS2307，应关闭旧标签并打开现用页面。Windows 不显示默认窗口内菜单，macOS 保留系统菜单；主进程变更需重启应用。当前 `i18n/` 只抽离部分中文文案。

### 后端与数据约定

业务读写统一 SQLAlchemy 2.0 声明式模型和 ORM 会话，现有业务迁移已完成，见 [迁移清单](backend-orm-migration.md)。金额使用 Decimal 与精确文本存储；读会话采用一致快照，写会话在核对前取写锁，异常整体回滚并释放连接。

结构迁移、SQLite 事务/外键/超时配置、在线备份和完整性诊断保留必要底层操作，不得用于业务 CRUD。静态模型不在启动时反射/替换历史表，不用 `create_all` 代替旧库升级；ORM 不意味着 MySQL 已可用。

新增接口放入功能目录并在 `main.py` 装配，使用明确的 `app.<功能>.<模块>` 导入，避免循环依赖。同步权限、共享类型、错误语义与调用方。输入、路径、IPC 和网络响应均在边界校验。保留 `contextIsolation`，不以 `nodeIntegration` 绕过进程边界。开发注释尽量中文。

## 业务规则与功能边界

| 领域 | 已有规则与更正 | 当前边界 |
| --- | --- | --- |
| 基础资料 | 物料、供应商和仓库增删改；业务引用和默认主仓库保护删除。客户独立搜索/新增；供货关系幂等绑定。 | 客户关系与报价另由独立模块提供；无完整营销自动化或采购选料限制；供应商分页不代表所有列表分页。 |
| 采购 | 审批申请可拆单，草稿订单占用额度；合格收货生成待入库单，入库后才记库存/应付；退货待仓库出库。 | 收货不增加库存，申请审批尚不要求异人。 |
| 销售 | 分批出库同事务核对订单余量及库存；退货关联原明细和单价。 | 实际退款独立登记，不自动付款。 |
| 仓库 | 单次确认、双向调拨流水、盘点账面快照与变化检查；调整需异人审批和仓库确认。 | 不是通用审批引擎，完整实物批次追踪待实现。 |
| 冲销 | 保留原单，追加反向流水/金额来源和原因；检查库存、依赖退货及重复更正。 | 不以删历史或覆盖余额代替更正，规则随单据类型不同。 |
| 计价 | 公司物料移动平均，退货/退料/调拨沿用来源成本；允许的缺价来源可人工核价并留修订。 | 未结期间修订可能改变历史成本；已结边界内核价和完工分摊锁定，业务来源凭证已提供采购价差和销售成本分录，完整价差分摊仍待实现。 |
| 生产 | BOM 版本/循环保护、需求快照、分批领退料/报工，合格品入库；已用于报工的需料不能退。 | 目标含不合格数，[MRP 数量与日期计划](material-planning.md)已提供；[不合格品处置与返工](quality-rework.md)已提供；有限产能排产及完整质量管理待实现。 |
| 完工成本 | 库存领料价优先，未知时人工核价；材料/人工/费用分为合格品、独立损失与返工携入成本池，合格品成本池按合格量分摊，尾分保证合计。 | 正常报废由合格品承担；返工携入未知时禁止结算，旧结算保持原口径；更正来源前冲销依赖结算，完整在制/跨期成本待实现。 |
| 业务财务 | 来源形成应收应付，按订单核对余额；手工收付款/退款限额，冲销追加反向记录；历史分户期初逐组合核对，独立审核后登记资金。 | 不证明银行到账；人民币口径，税费/多币种/银行对账待补。 |
| 总账基础 | 平级科目结构固定，期间含首尾且不重叠；名称/启停变更带版本、原因和同事务审计。 | 结账与重开由独立功能提供；辅助核算由独立功能提供。 |
| 期间结账 | 结束后按序检查结账、倒序重开；保存余额与成本来源，锁定历史核价/分摊。 | 不自动生成业务凭证、损益结转或法定财务报表。 |
| 报表 | 采购执行、收退货、余额和收发存 CSV。 | 业务汇总不是正式财务报表，首页演示图表不是实际经营指标。 |
| 已过账总账报表 | 试算平衡、科目明细、凭证/冲销下钻和当前快照 CSV，本期仅统计已过账凭证，正式期初单独计入余额。 | 未录入正式期初时只有历史累计，不等于业务方期初验收；公司项目资产负债与利润报表由独立模块提供。 |

| 公司财务报表 | 公司项目与科目映射、资产负债和利润查询、分录下钻、CSV、配置审计及关闭期间固定归档。 | 不预置法定模板，不提供现金流量、附注或税务申报；尚无正式期初时明确提示，业务数据核对与实机验收仍需完成。 |

[客户关系与报价](customer-relations.md)已提供联系人、跟进、商机手工概率与可见范围预测、固定报价独立审核、已批准报价 PDF 导出及接受依据转销售草稿；不计库存或收入。见 [完工成本规则](production-cost-settlement.md)、[总账基础规则](ledger-foundation.md) 和 [手工凭证规则](manual-journals.md)。手工凭证支持借贷平衡、独立审核、过账和关联冲销，过账快照固定并保留审计。业务来源凭证草稿已提供，见 [业务来源凭证规则](business-journals.md)；[损益结转](profit-transfers.md)已提供期间末草稿、独立审核、来源保护和结账清零检查；现金流量、法定报表格式、完整质量管理、售后深化、CRM 营销/预测模型深化、设备遥测及资产财务深化、人力、多组织、MySQL 与离线同步仍属后续工作，进入条件见 [模块评估](erp-expansion-assessment.md)。

正式期初提供首次无过账启用、独立审核确认、版本审计和启用前撤销，不增加本期发生额，也不自动生成业务分户期初，见 [期初余额规则](opening-balances.md)。

结账条件、历史锁定及归档边界见 [期间结账规则](period-closing.md)。

已过账查询口径与来源追溯见 [已过账总账报表](ledger-reports.md)，公司报表的配置、归档及权限见 [公司财务报表](financial-statements.md)。

## 连接、服务与备份

首次打开可手动连接、扫描局域网或本机创建服务端，填写实例名、目录、端口与首位管理员；已有数据库不覆盖。首位管理员只允许环回请求创建，密码至少 12 位。后续账号/角色由管理员维护，服务端逐项授权；账号停用/密码变更令旧会话失效，始终保留一位启用内置管理员。

首次连接其他电脑，完整比对两端 SHA-256 指纹后再登录。连接记录只存地址、实例身份与证书，不存密码；证书变化阻止自动重连，切换实例退出登录，数据不合并。旧地址失效时查找同身份/证书的新地址，恢复可能需重新登录。

mDNS 按当前 LAN IPv4 网卡查询，重扫释放旧连接；需允许 UDP 5353 组播和所选 HTTPS 端口。手动连接成功不表示发现可达。macOS 可能要求本地网络授权，Windows 需允许专用网络通信；组播受限时用手动地址并重新核验指纹。

安装版注册 Windows 服务或 macOS LaunchDaemon，安装与手动启停需管理员授权。关闭窗口保留托盘，双击/“打开 Nexora ERP”恢复；托盘可查看、刷新或停止服务。“退出桌面应用”不退出已安装服务，可无人登录运行，但实际设备须验收。

成组保护 `nexora.db`、`server.crt`、`server.key`。使用 SQLite 在线备份，不直接复制运行中的数据库。具体命令以 [后端备份说明](../backend/README.md) 为准：

```bash
cd backend
python -m app.backup --help
python -m app.backup backup --data-dir /path/to/instance --output /path/to/instance.nexora-backup
python -m app.backup restore --archive /path/to/instance.nexora-backup --data-dir /path/to/new-instance
```

备份先创建并检查，再恢复到空目录；不覆盖现有数据库。停止服务、保留旧数据后安排切换。丢失私钥会要求重新信任。设置可使用当前安装包升级服务，升级前成组备份，失败回退。系统路径、恢复步骤与命令参数见后端说明；按 [实机验收清单](lan-host-acceptance.md) 检查跨平台、无人登录重启、升级和恢复，CI 不代替实机。

## 验证与开发流程

遵守 [AGENTS.md](../AGENTS.md)：一需求一 `codex/<需求名>` 分支，先检查分支/工作区，已有需求继续原需求；独立并行工作树须用户授权。不覆盖已有改动，先读模块/类型/测试，新增行为测试正常流程、失败路径、并发与回滚风险。

Windows PowerShell，仓库根目录：

```powershell
npm run typecheck
$desktopTests = @(Get-ChildItem tests -Filter '*.test.mjs' -File | ForEach-Object { $_.FullName })
node --experimental-strip-types --test $desktopTests
$env:PYTHONPATH = 'backend'
python -m pytest backend/tests -q
npm run build
```

macOS，仓库根目录：

```bash
npm run typecheck
node --experimental-strip-types --test tests/*.test.mjs
PYTHONPATH=backend python -m pytest backend/tests -q
npm run build
```

PowerShell 不替原生命令展开通配符，显式枚举测试。`npm run build` 已含类型检查，`npm run preview` 预览已有构建。网站专用检查：

```bash
node --test tests/docs-site.test.mjs tests/docs-cover.test.mjs tests/docs-sandbox.test.mjs tests/docs-webgl.test.mjs tests/docs-gallery.test.mjs
npm run docs:build
```

完成实现、单元测试、必要检查/构建和文档后提交推送，创建 PR，平台检查通过再合并。中文提交标题简明、匹配内容。合并后询问是否删除分支，未经确认不删除。不能执行的检查报告原因，不删除/跳过旧测试。

## 构建说明

### 桌面构建

```bash
npm ci
npm run build
npm run preview
```

桌面输出在 `out/`，不生成安装包；官网单独输出到 `dist/site/`。

### Windows x64 安装包

在 Windows x64 主机和项目虚拟环境执行：

```powershell
python -m pip install -r backend/requirements-dev.txt "pyinstaller>=6,<7"
npm run dist:win
```

### macOS Apple Silicon 安装包

在 Apple Silicon Mac 和项目虚拟环境执行：

```bash
python -m pip install -r backend/requirements-dev.txt 'pyinstaller>=6,<7'
npm run dist:mac
```

两平台先 `npm ci`。打包依次构建后端、桌面类型检查/构建，electron-builder 生成 NSIS x64 或 DMG arm64。Python 优先级为 `NEXORA_PYTHON`、项目 `.venv`、系统解释器；先核验依赖，缺失直接报错。PyInstaller 必须在目标系统构建，不能从 Windows 交叉生成 Mac 服务。产物在忽略 Git 的 `release/`，缓存在 `build/`。

### CI 与发布边界

Windows/macOS 安装包工作流在主线/需求分支推送、主线 PR 和手动触发时测试并上传构建。Windows 检查安装运行；macOS 检查打包服务、用户/系统启动和异常恢复、升级回退、备份恢复。见 [工作流目录](../.github/workflows/)。

Actions 安装包是测试构建，尚未签名/公证，可能触发 SmartScreen 或 Gatekeeper 提示。跨平台实机、无人登录开机及恢复演练待验收；不把其他架构、代码签名或生产可用性写成已实现。

## 官网与 HTML 文档

首页以真实界面卫星、物料 → 库存 → 生产 → 财务路径填充首屏。`product-orbit.mjs` 用透明 WebGL 轨道贯穿首屏、五张界面、三窗展示和正文外缘，轨道按滚动阅读进度绘制与回收，卡片依次入场、完整阅读、退场，光点不再独立计时。滚动每帧读取未变形节点并更新，不限速或追赶；吸顶舞台入口固定在自然布局位置，停止滚动及后台停绘。手机保留 SVG 滚动连线与轻量卡片入场，减少动态保留完整静态阅读。标题、正文与截图由 HTML 展示，不被画布截获点击，GPU 失效后仍可读。 全页轨道位于留白和渐变上方、真实界面与业务舞台后方，实体卡片自然遮挡经过背后的线。标题和说明容器透明，文字以自身大小的紧凑底色保护阅读，避免整块背景截断轨道；main 不建立层叠上下文。WebGL 与 SVG 共用层级，覆盖层不接收点击，导航与原生大图弹窗保持在前。

官网正文末尾新增“敬请期待”双语收尾，标题主字与背景同心，主线从正文末尾直接延续为倾斜环绕路径，下降与整圈共用单一路径、进度和行进端点，随滚动展开并闭合，较淡的反向倾斜辅轨补充空间感，不再穿过标题或续到页脚，复用全页 WebGL 画布并在空闲与离屏时停绘。手机、减少动态及 WebGL 失败使用 SVG；无脚本保留文字、CSS 静态轨道与“回到起点”原生链接。

首屏出场约 1.14 秒：两行标题先后出现，说明和按钮跟上，左右真实界面从外侧进入。`hero-entrance.mjs` 只在这段出场期间让轨道跟随窗口，结束后停帧；滚动、触摸、点击或键盘焦点会立即结束出场。首屏之外的锚点与恢复位置、减少动态直接可读，不等待业务视图。head 同步确定首屏出场状态；初次定位保持即时，load 后两帧才启用后续点击的平滑导航，避免打开时先露出首页再滚走。无脚本直接显示完整内容。 首屏入场按实际滚动位置判断，顶部刷新即使保留旧锚点也播放；浏览器顶部零位滚动通知不中断动画。下方锚点或恢复位置仍直接定位并取消首屏出场，不重置用户滚动位置。

官网三窗是直接生成的只读 HTML 展示，构建时从项目的工作台、浅色主题、共享表格及标题栏抽取所需样式，并限制在 `.erp-display` 内。业务字段采用项目 13px 的 150%。`workspace-display.mjs` 维护展示结构，`scripts/site-display.mjs` 提取项目 CSS，`source-details.mjs` 测量本地字段 offset，并使用同一镜头矩阵平移、缩放内容和关联边框。示例行对应 200 / 2000 / 1000 个与 4000 / 400 / 400 元。缺失或越界字段只隐藏连线；手机可移动取景，减少动态保留静态阅读。官网不嵌入 iframe，不加载原 App、Vue、Pinia、业务路由或生产连接，不使用加载计时器。上方截图的独立 Vue 取景工具仍供维护者使用，不进入发布目录。

官网采用静态 HTML/CSS/JavaScript 构建，`scripts/build-docs-site.mjs` 使用 Marked 将版本控制中的 Markdown 转成页面，无业务 API、数据库或浏览器端 Markdown 编译。中文入口 `/zh-CN/`，英文 `/en/`，对应 `development.html` 为开发文档，根入口为中文。

| 文件 | 维护方式 |
| --- | --- |
| `README.md`、`README.en.md` | 中英文功能与进度，同时修改。 |
| `docs/development.zh-CN.md`、`docs/development.en.md` | 指南内容源，自动生成 HTML。 |
| `docs/site/site.css` | 官网/文档/移动端/打印样式。 |
| `scripts/build-docs-site.mjs` | 页面、目录、路径与资源生成。 |
| `docs/site/source-details.mjs` | 原始页面镜头、真实行矩形验证与逐项关联。 |
| `docs/site/product-orbit.mjs` | 全页滚动轨道、卡片入退场、固定布局节点及 SVG 兼容层。 |
| `docs/site/hero-entrance.mjs` | 一次性首屏出场的轨道跟随、中断、偏好适配与资源释放。 |
| `docs/site/product-showcase.*`、`product-gallery.mjs` | 真实界面截图、双语说明、失败提示和原生大图弹窗。 |
| `docs/site/screenshots/`、`scripts/site-preview/` | 截图素材、独立取景会话与只读组件入口；官网构建单独打包只读入口。 |
| `.github/workflows/docs-site.yml` | PR 验证、明确手动发布及可选的主线 Pages 发布配置。 |

本地 `npm run docs:build` 后运行 `python -m http.server 4173 --directory dist/site`，访问 `http://localhost:4173/`。语言切换保留页面类型，正文和目录无需 JavaScript；已有专题文档保留中文原文，英文指南明确标注语言。

首屏明确“联光 ERP · 面向企业内部的桌面 ERP”，主行动进入业务演示，次行动查看核心能力。五张真实组件截图位于封面与交互演示之间，以工作台首页为主图，补充物料管理、库存台账、生产成本和总账凭证。统一浅色 1800 × 1200，标注“当前界面预览 · 示例数据”，可点击查看大图；手机纵向展示，原图链接在无脚本时仍有效。优势说明覆盖电子生产物料、跨业务来源与业务财务衔接；业务来源生成凭证草稿，独立审核后过账。

运行 `npm run docs:preview-ui` 打开独立取景会话；它加载当前真实 App、Pinia、侧栏、顶部导航、标签和共享表格，只提供本地虚构数据，拒绝所有未配置请求，不连接正式服务、不写入业务数据。它用于界面取景，不构成原生桌面或服务连接验收；[截图说明](site/screenshots/README.md)记录尺寸与业务示例。

三窗默认展示真实采购入库、库存台账和应收应付来源组件，来源均为采购入库 #101，可聚焦明细；“业务演示”切换到独立网页沙盒，切换不重置沙盒状态：先显示完整入库窗口，再随滚动从右侧引入库存和应付窗口，用 WebGL 连接实际来源锚点。支持多单据、多物料、仓库与供应商选择、确认入库、库存筛选和来源追溯、部分或全部模拟付款。数量使用三位定点小数，金额以整数分计算；草稿不生成业务流水，确认不能重复，已确认单据只能复制为草稿，付款不得超过未付余额。

`sandbox.mjs` 管理业务状态，`sandbox-ui.mjs` 生成并装配 HTML 控件，`scene-geometry.mjs` 统一逻辑画布和窗底投影，`motion.mjs` 只控制镜头与连接线，`sandbox.css` 提供舞台样式。业务数据不由滚动改变，也不连接 ERP 服务。同一标签页点击语言链接时通过一次性 `sessionStorage` 交接数据，刷新恢复初始示例；存储不可用时仍允许导航。分步与总览按钮滚动到页面的实际阶段；放大操作可在停滚时保持聚焦，但任何页面滚动都会立即退出聚焦并按滚动条位置重绘，没有暂停或恢复按钮。输入框获得焦点不会锁住页面滚动。手机纵向排列，减少动态效果时取消运动；无 JavaScript 时保留静态业务示例和文档入口。

`webgl-stage.mjs` 使用原生 WebGL 绘制接触阴影、漫射光池、低角度掠光与来源连接线；窗框使用单层冷灰细边，已移除静态镀层和角部高光，HTML 控件共享 1400px 镜头投影。桌面窗口整体缩放并保留文字侧栏，两侧使用相反的 30° 角度，库存窗为 4°；不再复制 HTML 内容倒影；地面光场根据投影窗底的两端、跨度与滚动进度计算，冷暖光斑、细微材质与短接触阴影共同建立层次。GPU 图层不截获输入，静止时不连续绘制；上下文丢失或 WebGL 不可用时自动显示 CSS/SVG 兼容层，不重置业务数据。手机和减少动态效果模式保留静态关系，不创建 GPU 上下文。

三窗手动切换先淡出旧线，再沿已测量的实体起止姿态过渡，避免每帧重排造成尺寸跳变；连续切换从当前帧接续。连线由逻辑锚点与窗口共用投影，只绘制同屏、顺向、同来源的关系，退场或交叉时清除，回到总览后淡入。页面滚动打断聚焦补间时直接使用实际进度，并重新测量来源锚点，避免旧线残留。视口高度低于 620px 时改为纵向布局；宽度不超过 1000px 的低高度横屏使用手机行卡片，避免底部操作被固定舞台裁掉。

长记录分页展示：入库和应付明细每页 2 行，库存流水每页 4 行，余额和付款记录每页 3 行。页码属于展示状态，合计、确认和余额始终使用完整业务数据。添加物料打开最后一页；确认时若其他页有错误，自动返回对应页并定位字段。删除或筛选后的越界页会收敛到有效页。桌面先按实际内容（包括展开明细和错误提示）计算逻辑高度，再统一缩放窗口与连线；窗口内不建立滚动容器。总览保留物料、数量和单价，金额列及逐行删除入口在放大窗口中操作。

运行 `node --test tests/docs-site.test.mjs tests/docs-cover.test.mjs tests/docs-sandbox.test.mjs tests/docs-webgl.test.mjs tests/docs-gallery.test.mjs` 验证页面路径、业务规则、滚动阶段及 GPU 生命周期。详细说明见 [官网动效与沙盒说明](site/motion-proposal.zh-CN.md)。

官网预览发布入口为 [https://zhangzzj2003.github.io/Nexora-Erp/](https://zhangzzj2003.github.io/Nexora-Erp/)。README 顶部的官网链接和可点击预览图打开完整 WebGL 展示，GitHub README 本身只显示静态内容。管理员将 Pages 来源设为 GitHub Actions；在所选官网分支手动运行 `docs-site.yml` 并勾选 `publish=true`，即可发布该分支而不合并。PR 和未勾选发布的手动运行只验证，工作流只上传 `dist/site/`。仓库变量 `PAGES_ENABLED=true` 另外控制主线推送自动发布，分支预览验收期间保持关闭。`github-pages` 环境须允许此次发布分支。

参考 [GitHub Pages 官方工作流](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)。公开官网不包含数据库、私钥、令牌或本地日志。发布前核对源码版本和双语文档；明确要求发布的分支预览不表示需求已合并或应用已验收，默认分支 README 仍须另行授权合并后更新。

辅助核算使用静态 ORM 模型提供四类辅助归属、版本规则、拆分期初与组合结转；接口、快照更正和桌面权限边界见 [辅助核算规则](auxiliary-accounting.md)。[分户期初](subledger-openings.md)逐笔核对历史未结单据，独立审核后启用并记录资金，导入不会重复增加总账余额。

## 生产不合格品与返工

[不合格品处置与返工](quality-rework.md)覆盖不合格数量、明确报废成本处理、独立审核、追加材料工单、再次检验及来源成本携入。原工单成本未知时禁止返工结算；已过账损失凭证保护其来源，结账归档保留分配证据。此能力不等于完整质量或售后体系。


## 售后退换修

[售后规则](after-sales.md)提供独立审批、退换货关联草稿、客户物品保管、维修检验与交付、明确收费、实际工时留痕及追加式更正；客户物品不进入公司可售库存。结账固定期末方案、保管与工时记录。保修自动判定、序列号、附件、工时成本计价及分批交接仍待实现。

原位展示内容随 HTML 直接生成，无脚本也能看见，不需要等待应用挂载。官网构建只生成静态 HTML/CSS/JavaScript，并清理上一版嵌入应用的生成目录；模块及样式使用内容版本。字体和窗口变化只校正本地字段与连线，不会出现全屏加载提示。
