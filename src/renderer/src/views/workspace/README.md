# 工作台页面目录

`router/index.ts` 根据路由键装载下列页面，`WorkspaceShell.vue` 通过 `RouterView` 显示当前页面。目录表示业务领域，文件名表示实际页面；新增入口时同步更新 `router/workspace-routes.ts`、`router/index.ts` 和路由测试。

| 目录 | 页面组件 | 页面用途 |
| --- | --- | --- |
| `home/` | `HomeDashboardView.vue` | 按权限展示服务端业务净额、逐日趋势、有效单据与当前待办/库存；`dashboard-data.ts` 负责金额展示和图形坐标，规则见 `docs/home-statistics.md` |
| `warehouse/` | `InventoryOverviewView.vue` | 查看当前库存与库存流水 |
| `warehouse/` | `InventoryWarningsView.vue` | 按仓库现存量与阈值识别缺货/低库存，页内配置、启停及中文修订证据；工作台窗口定时读取并在状态新发生或恶化时提醒 |
| `warehouse/` | `PhysicalLotsView.vue` | 按仓库和物料核对批次结存、未分配差额、历史未识别期初和逐笔来源；支持历史期初现场补证与升级后未分配流水逐笔补证、先入后出成对及多笔成组补证，不推断旧单据的真实批号 |
| `warehouse/` | `OtherInboundsView.vue` | 处理期初、赠品等非采购入库，确认时登记多批实物来源并按原批次冲销 |
| `warehouse/` | `WarehouseTransfersView.vue` | 建立调拨草稿、逐行选择实物批次确认及按原批次冲销 |
| `warehouse/` | `InventoryStocktakesView.vue` | 建立库存盘点，逐行核对盘盈/盘亏实物批次并确认，沿原批次冲销 |
| `catalog/` | `MaterialsView.vue` | 物料分类筛选、参数搜索、分页、自动编码及版本编辑；`MaterialEditor.vue` 分组维护生产资料，`utils/material-form.ts` 管理共享草稿与搜索，`MaterialSpecificationsEditor.vue` 按模板维护动态规格与扩展属性；展示关联供应商；沿用 `/workspace/catalog` 地址 |
| `catalog/` | `SuppliersView.vue` | 供应商增删改查及供货物料绑定、解绑 |
| `catalog/` | `MaterialCategoriesView.vue` | 自定义两级物料类别与子类规格模板；版本编辑、启停、未使用项移除和变更快照，草稿保存在 Pinia |
| `catalog/` | `UnitsView.vue` | 独立单位表的搜索、分页、新增、版本编辑、启停和变更记录；物料弹窗从单位目录选择 |
| `catalog/` | `ProductionBomsView.vue` | 生产 BOM 基础资料；复用公共单据弹窗编辑成品与组件用量，`bom-form.ts` 校验重复、自引用及数量；保留原地址、权限和 Pinia 草稿 |
| `catalog/` | `CustomersView.vue` | 客户搜索、新增相似名称核对及单列 CSV 预检和批量导入；销售查看权限可浏览，客户管理权限可写入 |
| `catalog/` | `WarehousesView.vue` | 仓库增删改查，默认主仓库禁止删除 |
| `purchase/` | `PurchaseOrdersView.vue` | 建立和管理采购订单 |
| `purchase/` | `PurchaseRequestsView.vue` | 采购申请、审批、分批转采购订单 |
| `purchase/` | `PurchaseGoodsReceiptsView.vue` | 分批记录采购合格实收与拒收，确认后生成待入库单 |
| `purchase/` | `PurchaseReceiptsView.vue` | 确认采购入库时逐行登记实物批次，并查看原批次及冲销状态 |
| `purchase/` | `PurchaseReturnsView.vue` | 处理采购退货 |
| `sales/` | `SalesOrdersView.vue` | 建立和管理销售订单；客户资料独立维护，订单弹窗提供快捷入口并保留草稿 |
| `sales/` | `CustomerRelationsView.vue`、`CrmEditor.vue`、`CrmRecordAttachments.vue`、`CrmQuoteAttachments.vue` | 按客户维护联系人、跟进、商机；联系人新建和修订复用现有表单弹窗并保留列表及草稿，支持联系人及商机 CSV 导入与手工概率加权预测；固定报价独立审核后登记接受依据转销售草稿，并留存联系人、跟进、商机与报价附件及撤销证据 |
| `sales/` | `SalesShipmentsView.vue` | 处理销售出库 |
| `sales/` | `SalesReturnsView.vue` | 处理销售退货，确认时核对原出库批次或登记退货新批次，展示来源证据与旧单差额 |
| `sales/` | `AfterSalesView.vue`、`AfterSalesEditor.vue`、`AfterSalesEvidence.vue`、`AfterSalesAttachments.vue` | 售后来源、内联编制、独立审批、退换修办理、附件与保管/收费证据；状态及操作使用 `after-sales-actions.ts` |
| `finance/` | `ReceivablesPayablesView.vue` | 应收应付汇总及订单金额核对 |
| `finance/` | `PaymentRecordsView.vue` | 独立查询、登记收付款及冲销，保留审计记录 |
| `finance/` | `BankReconciliationView.vue` | 人工银行流水登记、CSV 文件预检及导入、逐笔收付款勾对与撤销证据 |
| `finance/` | `BankBalanceView.vue` | 银行账户绑定、期初未达项迁入与核销、已过账分录分组勾对、余额调节与独立复核 |
| `finance/` | `LedgerReportsView.vue` | 已过账科目明细、试算平衡、CSV 和凭证下钻 |
| `finance/` | `FinancialStatementsView.vue` | 公司项目/科目配置、资产负债与利润查询、来源核对、归档快照及 CSV |
| `finance/` | `AuxiliaryAccountingView.vue` | 客户/供应商/部门/项目辅助余额、来源与 CSV、档案和科目必填规则 |
| `finance/` | `SubledgerOpeningsView.vue` | 历史未结单据逐组合核对、独立审核启用、资金历史及 CSV |
| `finance/` | `FinancialSourcesView.vue` | 查看应收应付的业务来源明细 |
| `finance/` | `InventoryValuationView.vue` | 查看移动平均库存金额、待核价来源和核价修订历史 |
| `production/` | `ProductionWorkOrdersView.vue` | 建立和下达生产工单 |
| `production/` | `MaterialIssuesView.vue` | 处理生产领料，逐行选择来源仓批次确认并展示固定证据或旧确认差额 |
| `production/` | `MaterialReturnsView.vue` | 处理生产退料，核对原领料批次或登记退料新批次并展示固定证据 |
| `production/` | `ProductionCompletionsView.vue` | 报工、质检与合格成品实物批次入库；整批不合格不生成批次 |
| `production/` | `EquipmentMaintenanceView.vue`、`EquipmentEditor.vue`、`EquipmentEvidence.vue`、`EquipmentAttachments.vue` | 设备台账、周期计划、独立审核/执行/验收、停机、耗材原单、附件和中文审计；跨页状态由 `equipment-actions.ts` 管理 |
| `production/` | `ProductionCostsView.vue` | 库存领料成本、核价、费用归集、完工批次结算与冲销 |
| `system/` | `UserManagementView.vue` | 创建账号并管理用户状态与角色 |
| `system/` | `RolePermissionsView.vue` | 在职务表格中搜索、筛选、新增和配置自定义角色；按模块、单据、操作树授权 |
| `system/` | `PermissionCatalogView.vue` | 独立维护操作权限的中文名称，模块与单据仍按树状目录查看 |
| `system/` | `ConnectionSettingsView.vue` | 查看连接、修改密码和管理本机服务 |

页面组件处理展示与表单绑定；跨页面草稿和服务端快照放在 `store/state.ts`，业务写操作放在 `store/modules/`。权限与地址规则只在 `router/workspace-routes.ts` 维护。

全应用按钮使用 `components/app/AppButton.vue` 二次封装 Naive UI `NButton`，统一主操作、次操作、文字操作与导航按钮的交互。`variant` 支持 `primary`、`secondary`、`text`、`plain`；默认 `type="button"`，提交表单须显式传 `type="submit"`，`loading` 同时禁用重复操作。导航、标签及启动卡片用 `plain` 保留专属结构样式，图标通过 `icon` 插槽传入。

文本、多行文本、密码、搜索和数字字段使用 `components/app/AppInput.vue` 封装 `NInput`，`required`、`min`、`max`、`step`、`pattern`、`minlength`、`maxlength` 等属性传给实际输入元素参与浏览器校验。金额、数量保留业务字符串；端口等数字模型及 `.number` 转成数字，清空仍为空字符串；`.trim` 保留原有去空格行为。密码提供显示/隐藏操作。复选框直接使用 `NCheckbox`，标签放在其默认插槽中，保留文字点击、键盘操作、半选及只读保护。输入主题在 `utils/app-theme.ts` 集中维护，配色使用明暗主题变量。

原生控件检查已覆盖引导、登录、工作台与公共组件。仅保留 `WorkspaceSelect` 的不可见必填校验代理及 `WorkspaceTable` 专用横向滚动条；后者复用表格滚动定位和宽度计算，不属于业务表单输入。表格继续使用已有 vxe-table 公共封装，弹窗、开关和通知继续使用 Naive UI。

权限目录、结账来源明细及生产成本来源快照使用 `NCollapse` 搭配 `components/app/AppCollapseItem.vue`。折叠项封装 `NCollapseItem`，标题复用 `AppButton`，支持 Tab 聚焦、Enter/空格展开和 `aria-expanded`、`aria-controls` 读屏关联。使用 `display-directive="show"` 保留收起的内容，避免嵌套目录状态与编辑草稿丢失；分隔线和标题配色通过根主题统一维护。不要重新引入原生 `details`、`summary`。

工作台单值下拉选择统一使用 `components/workspace/WorkspaceSelect.vue`，在 Naive UI `NSelect` 上封装输入高度、明暗主题、可搜索菜单与必填校验。页面传入 `v-model` 和 `{ label, value, disabled? }` 选项，数字编号、布尔值及表示“全部”的 `null` 保持原类型；不要继续使用原生 `<select>` 或绕过公共组件直接引入 `NSelect`。`change` 在模型更新后触发，订单切换等操作可继续读取共享草稿；分页选择使用 `size="small"` 与 `filterable=false`。菜单传送到 `body`，避免被表格和弹窗滚动区截断。

日期输入直接使用 Naive UI `NDatePicker`，不额外封装日期组件。统一设置 `to="body"`、`type="date"`、`format="yyyy-MM-dd"` 和 `value-format="yyyy-MM-dd"`，通过 `formatted-value` 读写已有字符串字段，清空时使用 `utils/date-field.ts` 的 `datePickerString` 转回空字符串。`vDateField` 指令补回原生必填与手输日期的有效性、上下限校验；日历可选范围通过 `dateOutsideRange` 和 `is-date-disabled` 设置，按设备本地日期比较，避免时区使边界偏移。主题在根 `NConfigProvider` 中统一设置。控件替换不改变服务端校验、会计期间规则或 API 数据协议。

工作台中的表格统一由 `components/workspace/WorkspaceTable.vue` 封装的 vxe-table 渲染。页面传入 `columns`、`data` 和可选的最小宽度，通过 `cell-<列键>` 插槽填写业务单元格；标题、筛选、操作、表前说明、空状态和页脚分别使用 `heading`、`filters`、`actions`、`beforeTable`、`empty`、`footer` 插槽。表格超出可视宽度时，底部提供始终可见的横向滚动条；查询失败可用 `error` 和 `errorActions` 显示失败原因与重试入口。采购与库存报表也使用同一组件，CSV 继续基于相同的服务端查询结果。列表新增入口以按钮打开 Naive UI 弹窗，保存失败保留草稿；复杂单据的确认、冲销仍保留原有操作流程。职务仍沿用现有角色与操作权限数据，内置角色只读；授权树由 `components/workspace/PermissionTreePicker.vue` 提供。权限目录在系统管理下使用单独路由，避免职务列表下方再展开很长的名称维护区域。权限目录可独立重试读取服务端数据，其他业务列表加载失败时不会使目录一直空白。

公共分页栏把筛选后总条数与分页控件集中放在表格底部右侧，窄窗允许换行；总数为 0 时仅保留“共 0 条”。物料页使用 `useLocalPagination` 对已经加载的名单分页，默认每页 20 条，可选 10/20/50/100 条；搜索或切换每页条数回到首页，删除导致末页越界时自动回退。完整物料名单仍保存在 Pinia 中供业务选项使用，此处不改变服务端查询方式。

“其他入库”操作栏的“查看详情”复用 `WorkspaceDocumentDialog` 的 `readOnly` 模式，隐藏添加、保存并拦截相关事件，空明细采用只读提示。基础信息和物料表只显示已保存的单据字段与批次证据，不使用当前物料档案覆盖历史名称或单位。按单据 ID 跟随 Pinia 最新快照，不引用新建草稿；断线或其他操作忙碌时仍可查看和关闭。查看权限由原页面路由守卫控制，不额外要求创建、确认或冲销权限。其他列表暂未接入。

应用业务状态和主题状态由 Pinia 管理。`store/app-store.ts` 的 `useAppStore()` 保留页面现有的响应式 `ref` 取值接口；应用启动与监听器清理由根组件负责。

公共设置使用 `store/settings-store.ts` 管理语言偏好和抽屉开合；`AppSettingsButton` 提供入口，根组件只装配一份 `AppSettingsDrawer`，底层页面不随抽屉开合或语言切换重建。语言使用 `nexora-locale` 本地存储键，非法或缺失值回退简体中文；禁用存储时当前会话仍可切换。公共文案通过 `i18n/common-copy.ts` 显式翻译，英文表位于 `i18n/en-US.ts`，用户名称、单据内容及未知消息不做自动翻译。新增导航标签时同步补充英文表；业务页面完整多语言覆盖尚未实现。主题卡片和顶部主题按钮共用既有快照队列，连续操作按最后意图生效。

业务操作的临时成功与错误反馈写入共享 `notice` / `error` 后，由根组件内的 `AppMessageProvider.vue` 统一显示为右上角通知；页面不再占用内容区显示整行横幅。新页面在组件内需要主动提示时使用 `composables/use-app-message.ts`，不要直接建立第二个消息提供器。底栏继续显示服务端连接状态。

`warehouse/WarehouseOutboundsView.vue` 展示其他出库草稿、仓库确认、取消和冲销；其他用途出库和已提交采购退货确认时逐行选择来源仓库的实物批次，标记历史未识别期初，冲销后保留原批次证据。两类出库均在仓库确认时扣减库存，采购退货冲销沿原批次回仓。

采购退货页提交后展示待出库单号；仓库出库页复用列表确认采购退货，确认后才更新库存与应付。销售出库页确认时逐行选择来源仓库的实物批次，展示固定分配或旧确认差额，冲销沿原批次回仓。仓库调拨页确认时逐行选择来源仓批次，确认后在目标仓保留同一批次编号；冲销沿原分配回仓，目标仓批次已被耗用时拒绝冲销。

`warehouse/InventoryLedgerView.vue` 复用工作台表格展示服务端筛选后的期初、逐笔流水与期末。公共表格以完整占位区展示空结果或加载失败；台账查询失败时隐藏上次结果，并提供重新查询。服务端若返回默认 `Not Found`，桌面端会提示核对两端版本，不将失败误当作无流水。

`warehouse/InventoryAdjustmentsView.vue` 管理独立库存调整的提交、异人审批、逐批仓库确认、取消与按原批次冲销。

`purchase/PurchaseReportsView.vue` 与 `warehouse/InventoryReportsView.vue` 共用报表表格，查询和 CSV 使用同一份服务端结果。

仓库管理新增只读实物批次页后继续统一使用公共表格及台账式筛选面板。顶部保留 `NEXORA WORKSPACE` 和页面主标题，主列表设置 `showTitle=false`，仅保留说明与操作，避免重复标题；表格仍保留可访问名称，期初期末等次级列表继续显示标题。筛选面板的间距、底色、换行和明暗主题由 `WorkspaceTable` 统一管理，其他业务表格也沿用该样式。库存总览的汇总卡片放在筛选与表格之间；台账先显示筛选和流水，再显示期初期末。调拨与盘点以单据表格展示，支持按单号、仓库或物料搜索，并保留新增弹窗、权限控制、确认、取消（盘点）与冲销记录。

用户管理单独展示 ID、账号、姓名、工号、手机号和已分配角色；创建/编辑弹窗维护资料与角色，密码通过操作列的重置弹窗修改。账号状态使用 Naive UI Switch，保存失败保留原显示，当前账号不可停用或由此重置密码。

`system/MenuManagementView.vue` 提供「菜单管理」（`/workspace/menu-management`），沿用 `users.manage` 权限。一级导航分组与全部页面入口均可从内置图标库选择图标，支持搜索、预览和恢复默认；选择后点击保存才会写入服务端。页面从路由表构建菜单树，配置由 Pinia 共享，保存失败保留编辑内容。配置不支持上传图片，不改变菜单名称、顺序、路由和授权；其他客户端需重新登录或刷新数据后更新。

`finance/LedgerAccountsView.vue` 与 `finance/AccountingPeriodsView.vue` 分别维护总账科目与会计期间，按独立查看、维护权限控制。共享草稿和快照在 Pinia，修改携带旧版本，冲突保留输入；`MetadataHistory.vue` 展示建立、名称、启停及版本变更，读取失败可重试。科目结构和期间日期保存后固定；`JournalsView.vue` 提供手工及业务来源凭证，`JournalHistory.vue` 展示操作审计，`JournalAttachments.vue` 在详情中展示附件与追加撤销，文件选择和保存只经主进程受限接口；会计期间支持结账检查、结账与重开，操作沿用公共控件；历史成本锁定由服务端执行。

`finance/OpeningBalancesView.vue` 提供首次总账启用方案，使用 Pinia、独立动作授权和版本校验；同账号不能审核自身建改或提交的方案。`OpeningHistory.vue` 展示阶段、操作者、结果及原因。主表、余额编辑和详情沿用 WorkspaceTable，窄窗口内部横向滚动。`LedgerReportsView.vue` 展示同快照期初来源与审计，正式期初不计本期发生额；业务分户初始余额不自动生成，须单独录入并核对。

`finance/SubledgerOpeningsView.vue` 提供 `/workspace/subledger-openings` 独立查看权限入口，使用 Pinia 的 `subledger-actions.ts` 管理方案、查询、审计、资金与迟到请求。`SubledgerEditor.vue` 编辑原单与附加部门/项目，`SubledgerEvidence.vue` 显示逐完整组合差额、确认快照及审计前后明细。失败保留输入，同账号断线保留草稿；换号撤权清理全部共享数据，表格内部行标记不发送服务端。只读用户没有建单选项或资金写入能力，规则见 [分户期初](../../../../../docs/subledger-openings.md)。

`finance/AuxiliaryAccountingView.vue` 及 `auxiliary-actions.ts` 提供独立辅助查看、配置和档案维护权限，使用 Pinia 保存查询、证据与加载状态；切换账号或撤权清理，迟到响应丢弃，写入失败保留表单。`AuxiliarySelector.vue` 供凭证、拆分期初和业务生成选择，`auxiliary-display.ts` 展示服务端名称快照。详情和公司报表保留辅助来源，损益结转逐完整组合清零，规则与限制见 [辅助核算](../../../../../docs/auxiliary-accounting.md)。

`finance/BusinessJournalPanel.vue` 在总账凭证页提供来源搜索、科目配置、缺价与生成核对；`BusinessSourceEvidence.vue` 展示服务端金额、库存流水、订单及登记证据，并在凭证详情读取生成快照。加载与写操作统一由 Pinia 的 `business-journal-actions.ts` 管理；换号撤权清理、迟到响应丢弃、失败保留输入，新增表单与操作复用工作台公共控件。

`finance/ProfitTransferPanel.vue` 在同一总账凭证页提供损益结转范围配置、期间预览与草稿生成；`ProfitTransferEvidence.vue` 展示逐科目清零、累计待结净额、已过账凭证及正式期初来源，详情沿用生成快照。`profit-transfer-actions.ts` 管理 Pinia 快照、迟到请求与撤权清理；配置失败保留输入，成本复选框与证据折叠复用 Naive UI 和公共封装。业务凭证来源折叠也沿用 `AppCollapseItem`，符合主线统一控件检查。

`production/MaterialPlanningView.vue` 提供独立 `mrp.view` 入口及固定计划、需求编排、参数三种工作模式。`MrpEditor.vue` 安排来源日期，`MrpEvidence.vue` 展示日期净需求、来源与审计，`MrpPolicies.vue` 维护版本参数；`mrp-actions.ts` 统一 Pinia 状态、撤权清理、迟到响应和转单。日期使用既有 Naive 控件与校验指令，表格沿用公共控件。断线保留输入，来源变化后新建重算，规则见 [MRP](../../../../../docs/material-planning.md)。

`sales/CustomerRelationsView.vue` 提供 `crm.view` 入口与四类列表；`CrmEditor.vue` 在页内编辑，`ContactImportDialog.vue` 和 `OpportunityImportDialog.vue` 分别解析、预检本地联系人及商机 CSV；商机列表汇总可见范围的加权预测，`CrmEvidence.vue` 展示固定报价及前后变更，`CrmDate.vue` 复用现有日期校验方式。`crm-actions.ts` 保存 Pinia 表单，负责版本操作、权限清理、批量写入、迟到响应和双权限转单；审批与转单使用保护焦点弹窗，失败保留依据。规则和边界见 [客户关系](../../../../../docs/customer-relations.md)。

`production/QualityDispositionView.vue` 提供独立 `quality.view` 入口，`QualityEditor.vue` 编制报废及返工，`QualityEvidence.vue` 核对冻结检验、追加材料与前后变更；`quality-actions.ts` 管理 Pinia 草稿、版本、断线及权限清理。生产工单、报工与成本显示关联来源；规则见 [不合格品处置与返工](../../../../../docs/quality-rework.md)。

`warehouse/InventoryWarningsView.vue` 使用 `inventory-warning-actions.ts` 管理 Pinia 规则、数量、草稿与修订版本。只读权限沿用库存查看，维护另需独立权限；同账号断线失效旧量而保留正文，换号撤权及迟到响应隔离。库存台账链接预设来源组合；页面可翻阅服务端定时留存的预警事件，换号和断线失效旧历史。`inventory-warning-alerts.ts` 在当前登录窗口内轮询，失焦时通过受限预加载接口请求不含物料详情的系统通知；窗口关闭后由主进程托盘轮询服务端事件。规则和升级见 [库存预警](../../../../../docs/inventory-warnings.md)。

`warehouse/PhysicalLotsView.vue` 使用 `physical-lot-actions.ts` 管理 Pinia 批次快照与补证写操作，查询沿用库存查看权限，现场补证另需 `physical_lot.reclassify`，旧客户端未分配流水逐笔、成对及成组补证需 `physical_lot.movement_evidence`；仓库/物料筛选、迟到响应、断线、换号和撤权都不能留下旧批次证据。历史未识别期初、新流水、现场补证、逐笔、成对及成组补证记录分开展示，补证与可审计冲销只转移批次归属，未分配差额不会显示成可追踪批次，规则见 [实物批次基础](../../../../../docs/physical-lot-tracing.md)。

业务物料编号选择统一使用公共 `WorkspaceMaterialSelect`，候选集合、保留来源、禁用项与业务联动由页面提供。公共组件在两行菜单中展示关键辨认信息，并提供只读核心资料、技术参数展开和多字段搜索；模块自带的物料选项直接作为资料源，不依赖库存查看权限。“其他入库”通过 `WorkspaceDocumentDialog` 的添加事件直接增加 Pinia 明细行，在表格内搜索、重选、编辑数量及移除；空行保留草稿但不能提交。

物料单据新增和修改使用 `WorkspaceDocumentDialog` 的基础信息、分隔线、物料表格及固定操作区。除其他入库外，采购、仓库、销售及生产的十五个单据弹窗已接入；页面的行插槽直接引用 Pinia 草稿，保留原数量、价格、保修和来源关联字段。`showAdd=false` 用于申请转单、收货、退货及领退料，隐藏自由添加入口；各页面继续决定来源候选与数量上限。卡片弹窗顶部由全局样式固定关闭区，普通资料弹窗滚动正文，单据弹窗滚动 `document-body`，避免出现两个滚动层。

单据新增与已接入的详情只统一顶部标题，原正文、只读约束和底部操作保持原布局。批次确认使用共享 `WorkspaceLotDialog` 固定标题及页脚，`WorkspaceLotLineEditor` 按物料显示批次表格、数量核对与紧凑添加入口，直接编辑原页面草稿对象。所有十一类批次入口继续调用原 Pinia 确认方法，保留各单据可用量、日期、权限和载荷校验；盘亏与负调整按差异绝对量核对。公共表格处理窄窗口横向滚动，弹窗正文处理长单据纵向滚动；保存期间禁止关闭与重复提交，失败保留草稿。

生产工单和完工单的“关联单据”共用 `ProductionAssociationDialog.vue`，复用只读 `WorkspaceDocumentDialog`，由 Pinia 的 `production-association-actions.ts` 管理查询与会话失效。来源证据、未分配缺口和主动加载的采购参考分别显示，均明确工单范围；该弹窗不提供建单、补证或审批动作。
