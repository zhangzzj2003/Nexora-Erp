import { computed, ref } from 'vue'
import type {EquipmentOverview,EquipmentDetail,EquipmentForms,EquipmentEntity} from '../../../shared/equipment-api'
import type {DashboardPeriod, DashboardResult} from '../../../shared/dashboard-api'
import type { CrmOptions, CrmOverview, CrmKind, CrmRecord, CrmChange, CrmForms, CrmEditTarget } from '../../../shared/crm-api'
import type { QualityOverview, QualityEvidence, QualityDraft } from '../../../shared/quality-api'
import type { AfterSalesOverview, AfterSalesEvidence, AfterSalesDraft } from '../../../shared/after-sales-api'
import type { MrpChange, MrpCheck, MrpDetail, MrpOptions, MrpPlan, MrpPlanInput, MrpPolicy } from '../../../shared/mrp-api'
import type { MenuIconSetting } from '../../../shared/menu-icons'
import type {
  Bom,
  Customer,
  FinanceAccount,
  LedgerAccount,
  Journal,
  JournalInput,
  BusinessJournalCandidate,
  BusinessJournalOptions,
  BusinessJournalPolicy,
  ProfitTransferOptions,
  ProfitTransferPreview,
  ProfitTransferPolicy,
  StatementOptions,
  StatementPolicy,
  StatementQuery,
  StatementReport,
  StatementArchiveSummary,
  StatementArchive,
  AuxiliaryOptions,
  AuxiliaryChange,
  AuxiliaryReport,
  AuxiliaryQuery,
  AuxiliarySelectionOptions,
  FinanceMetadataChange,
  OpeningBalance,
  OpeningBalanceInput,
  SubledgerInput,
  SubledgerOpening,
  SubledgerOptions,
  SubledgerQuery,
  SubledgerReport,
  SubledgerChange,
  SubledgerReconciliation,
  SubledgerPayment,
  LedgerReportQuery,
  LedgerReportResult,
  LedgerAccountInput,
  AccountingPeriod,
  PeriodClosingCheck,
  PeriodClosingRecord,
  AccountingPeriodInput,
  FinancialEntry,
  GoodsReceipt,
  InventoryCostInput,
  InventoryValuationReport,
  LedgerResult,
  LedgerQuery,
  Material,
  MaterialCategory,
  MaterialIssue,
  MaterialReturn,
  Movement,
  OtherInbound,
  WarehouseOutbound,
  PaymentRecord,
  Permission,
  ProductionCompletion,
  ProductionCostReport,
  ProductionCostSettlement,
  PurchaseOrder,
  PurchaseRequest,
  PurchaseReturn,
  ReceivablesPayables,
  Receipt,
  ReportQuery,
  ReportResult,
  Role,
  SalesOrder,
  SalesReturn,
  Shipment,
  Stock,
  StockAdjustment,
  Stocktake,
  Supplier,
  SupplierMaterial,
  Transfer,
  User,
  Warehouse,
  WorkOrder
} from '../../../shared/erp-api'
import type {
  ConnectionCandidate,
  DiscoveryResult,
  HostStatus,
  ServerProfile
} from '../../../shared/desktop-api'
import type {
  WorkspaceRouteGroupKey,
  WorkspaceRouteKey
} from '../router/workspace-routes'
import type { Screen } from './types'

// 表单草稿与服务端快照按应用实例创建，切换页面时保留输入。
export function createAppState() {
  const equipmentOverview=ref<EquipmentOverview|null>(null),equipmentDetail=ref<EquipmentDetail|null>(null)
  const equipmentLoading=ref(false),equipmentError=ref('')
  const equipmentEdit=ref<{kind:EquipmentEntity;id:number;version:number}|null>(null)
  const equipmentForms=ref<EquipmentForms>({asset:{code:'',name:'',serial_number:'',location:'',status:'active',reason:''},
    plan:{equipment_id:0,reference:'',title:'',interval_days:30,next_due:'',enabled:true,reason:''},
    job:{reference:'',equipment_id:0,kind:'corrective',plan_id:null,work_order_id:null,assigned_to:0,request_note:'',warehouse_id:null,parts:[],reason:''}})
  const dashboardResult = ref<DashboardResult|null>(null)
  const dashboardPeriod = ref<DashboardPeriod>('7d')
  const dashboardLoading = ref(false), dashboardError = ref('')
  const qualityOverview = ref<QualityOverview | null>(null)
  const afterSalesOverview=ref<AfterSalesOverview|null>(null)
  const afterSalesDetail=ref<AfterSalesEvidence|null>(null)
  const afterSalesLoading=ref(false), afterSalesError=ref('')
  const afterSalesEdit=ref<{id:number;version:number}|null>(null)
  const afterSalesForm=ref<AfterSalesDraft>({shipment_line_id:0,reference:'',kind:'return',quantity:'1',
    complaint:'',solution:'',charge_mode:'none',fee_amount:'0',customer_acceptance:'',warehouse_id:1,
    replacement_material_id:null,replacement_quantity:null,replacement_unit_price:null,parts:[],reason:''})
  const qualityDetail = ref<QualityEvidence | null>(null)
  const qualityLoading = ref(false)
  const qualityError = ref('')
  const qualityEdit = ref<{id:number;version:number} | null>(null)
  const qualityForm = ref<QualityDraft>({completion_id:0,reference:'',kind:'scrap',quantity:'1',loss_treatment:'',
    defect:'',action_note:'',warehouse_id:1,materials:[],reason:''})
  const mrpPlans = ref<MrpPlan[]>([])
  const crmOptions = ref<CrmOptions | null>(null)
  const crmOverview = ref<CrmOverview | null>(null)
  const crmDetail = ref<{kind: CrmKind; record: CrmRecord} | null>(null)
  const crmChanges = ref<CrmChange[]>([])
  const crmForms = ref<CrmForms>({contact:{customer_id:0,name:'',job_title:'',phone:'',email:'',note:'',is_active:true},
    opportunity:{customer_id:0,contact_id:null,title:'',owner_id:0,stage:'prospect',estimated_amount:'0.00',expected_close_date:'',note:''},
    activity:{customer_id:0,contact_id:null,opportunity_id:null,subject:'',owner_id:0,due_date:'',note:''},
    quote:{opportunity_id:0,contact_id:null,reference:'',valid_until:'',terms:'',lines:[{material_id:0,quantity:'1',unit_price:'0'}]}})
  const crmEdit = ref<Partial<Record<CrmKind, CrmEditTarget>>>({})
  const crmLoading = ref(false)
  const crmError = ref('')
  const mrpOptions = ref<MrpOptions | null>(null)
  const mrpDetail = ref<MrpDetail | null>(null)
  const mrpCheck = ref<MrpCheck | null>(null)
  const mrpChanges = ref<MrpChange<MrpPlan>[]>([])
  const mrpPolicyChanges = ref<MrpChange<MrpPolicy>[]>([])
  const mrpForm = ref<MrpPlanInput>({ reference: '', start_date: '', reason: '', demand_dates: [], supply_dates: [], manual_demands: [] })
  const mrpLoading = ref(false)
  const mrpError = ref('')
  const screen = ref<Screen>('loading')
  const openedRouteKeys = ref<WorkspaceRouteKey[]>([])
  // 日常默认全部收起，点击分类时最多展开一个。
  const expandedGroupKey = ref<WorkspaceRouteGroupKey | null>(null)
  const version = ref('')
  const notice = ref('')
  const error = ref('')
  const busy = ref(false)
  const user = ref<User | null>(null)
  const username = ref('')
  const password = ref('')
  // 分类目录与物料快照一同读取，供各页面复用。
  const materialCategories = ref<MaterialCategory[]>([])
  const materials = ref<Material[]>([])
  const supplierMaterials = ref<SupplierMaterial[]>([])
  const suppliers = ref<Supplier[]>([])
  const stock = ref<Stock[]>([])
  const inventoryValuation = ref<InventoryValuationReport | null>(null)
  const inventoryCostInputs = ref<InventoryCostInput[]>([])
  const inventoryCostForm = ref({ movement_id: 0, unit_cost: '', reference: '', reason: '' })
  const movements = ref<Movement[]>([])
  const ledgerResult = ref<LedgerResult>({ groups: [], rows: [] })
  const stockAdjustments = ref<StockAdjustment[]>([])
  const purchaseReportQuery = ref<ReportQuery>({ kind: 'purchase_requests', warehouse_id: null,
    material_id: null, supplier_id: null, from_date: null, to_date: null })
  const inventoryReportQuery = ref<ReportQuery>({ kind: 'inventory_balance', warehouse_id: null,
    material_id: null, supplier_id: null, from_date: null, to_date: null })
  const purchaseReportResult = ref<ReportResult | null>(null)
  const inventoryReportResult = ref<ReportResult | null>(null)
  const ledgerQuery = ref<LedgerQuery>({ warehouse_id: null, material_id: null,
    from_date: null, to_date: null, source_type: null })
  const otherInbounds = ref<OtherInbound[]>([])
  const warehouseOutbounds = ref<WarehouseOutbound[]>([])
  const receipts = ref<Receipt[]>([])
  const goodsReceipts = ref<GoodsReceipt[]>([])
  const purchaseOrders = ref<PurchaseOrder[]>([])
  const purchaseRequests = ref<PurchaseRequest[]>([])
  const purchaseReturns = ref<PurchaseReturn[]>([])
  const receivablesPayables = ref<ReceivablesPayables | null>(null)
  const financeAccounts = ref<FinanceAccount[]>([])
  const ledgerAccounts = ref<LedgerAccount[]>([])
  const openingBalances = ref<OpeningBalance[]>([])
  const openingBalanceOptions = ref<{ accounts: LedgerAccount[]; period: AccountingPeriod | null } & Partial<AuxiliarySelectionOptions>>({ accounts: [], period: null })
  const openingBalanceForm = ref<OpeningBalanceInput & { id: number | null; version: number }>({ id: null, version: 1, reference: '', effective_date: '', note: '', reason: '', lines: [] })
  const subledgerOpenings = ref<SubledgerOpening[]>([])
  const subledgerOptions = ref<SubledgerOptions | null>(null)
  const subledgerForm = ref<SubledgerInput & { id: number | null; version: number }>({ id: null, version: 1,
    reference: '', opening_balance_id: 0, opening_version: 0, control_accounts: [], lines: [], note: '', reason: '' })
  const subledgerQuery = ref<SubledgerQuery>({ to_date: '', kind: null, party_id: null })
  const subledgerReport = ref<SubledgerReport | null>(null)
  const subledgerPayments = ref<SubledgerPayment[]>([])
  const subledgerChanges = ref<SubledgerChange[]>([])
  const subledgerCheck = ref<SubledgerReconciliation | null>(null)
  const subledgerLoading = ref(false)
  const subledgerError = ref('')
  const journals = ref<Journal[]>([])
  const businessJournalSources = ref<BusinessJournalCandidate[]>([])
  const businessJournalOptions = ref<BusinessJournalOptions | null>(null)
  const businessJournalPolicyChanges = ref<FinanceMetadataChange<BusinessJournalPolicy>[]>([])
  const businessJournalLoading = ref(false)
  const businessJournalError = ref('')
  const profitTransferOptions = ref<ProfitTransferOptions | null>(null)
  const profitTransferPreview = ref<ProfitTransferPreview | null>(null)
  const profitTransferPolicyChanges = ref<FinanceMetadataChange<ProfitTransferPolicy>[]>([])
  const profitTransferLoading = ref(false)
  const profitTransferError = ref('')
  const statementOptions = ref<StatementOptions | null>(null)
  const auxiliaryOptions = ref<AuxiliaryOptions | null>(null)
  const auxiliaryChanges = ref<AuxiliaryChange[]>([])
  const auxiliaryQuery = ref<AuxiliaryQuery>({ account_id: 0, kind: 'customer', from_date: '', to_date: '', entity_id: null })
  const auxiliaryReport = ref<AuxiliaryReport | null>(null)
  const auxiliaryLoading = ref(false)
  const auxiliaryError = ref('')
  const statementPolicyChanges = ref<FinanceMetadataChange<StatementPolicy>[]>([])
  const statementQuery = ref<StatementQuery>({ from_date: '', to_date: '' })
  const statementReport = ref<StatementReport | null>(null)
  const statementArchives = ref<StatementArchiveSummary[]>([])
  const statementArchive = ref<StatementArchive | null>(null)
  const statementLoading = ref(false)
  const statementArchiveLoading = ref(false)
  const statementError = ref('')
  const ledgerReportQuery = ref<LedgerReportQuery>({ kind: 'trial_balance', from_date: '', to_date: '', account_id: null })
  const ledgerReportResult = ref<LedgerReportResult | null>(null)
  const ledgerReportAccounts = ref<LedgerAccount[]>([])
  const ledgerReportLoading = ref(false)
  const ledgerReportError = ref('')
  const ledgerReportJournal = ref<Journal | null>(null)
  const ledgerReportJournalLoading = ref(false)
  const ledgerReportJournalError = ref('')
  const journalOptions = ref<{ accounts: LedgerAccount[]; periods: AccountingPeriod[] } & Partial<AuxiliarySelectionOptions>>({ accounts: [], periods: [] })
  const journalForm = ref<JournalInput & { id: number | null; version: number }>({
    id: null, version: 1, reference: '', journal_date: '', note: '', reason: '', lines: []
  })
  const accountingPeriods = ref<AccountingPeriod[]>([])
  const periodClosingCheck = ref<PeriodClosingCheck | null>(null)
  const periodClosingHistory = ref<PeriodClosingRecord[]>([])
  const periodClosingLoading = ref(false)
  const periodClosingError = ref('')
  const ledgerAccountForm = ref<LedgerAccountInput & { id: number | null; version: number; is_active: boolean }>({
    id: null, version: 1, code: '', name: '', category: 'asset', normal_balance: 'debit', is_active: true, reason: ''
  })
  const accountingPeriodForm = ref<AccountingPeriodInput & { id: number | null; version: number }>({
    id: null, version: 1, code: '', name: '', start_date: '', end_date: '', reason: ''
  })
  const paymentRecords = ref<PaymentRecord[]>([])
  const boms = ref<Bom[]>([])
  const workOrders = ref<WorkOrder[]>([])
  const materialIssues = ref<MaterialIssue[]>([])
  const materialReturns = ref<MaterialReturn[]>([])
  const productionCompletions = ref<ProductionCompletion[]>([])
  const productionCostReport = ref<ProductionCostReport | null>(null)
  const productionCostSettlements = ref<ProductionCostSettlement[]>([])
  const productionSettlementForm = ref({ work_order_id: 0, reference: '', note: '' })
  const settlementReversalReasons = ref<Record<number, string>>({})
  const warehouses = ref<Warehouse[]>([])
  const transfers = ref<Transfer[]>([])
  const stocktakes = ref<Stocktake[]>([])
  const customers = ref<Customer[]>([])
  const salesOrders = ref<SalesOrder[]>([])
  const shipments = ref<Shipment[]>([])
  const salesReturns = ref<SalesReturn[]>([])
  const selectedWarehouseId = ref(0)
  const roles = ref<Role[]>([])
  const menuIcons = ref<MenuIconSetting[]>([])
  const permissions = ref<Permission[]>([])
  const permissionLabelDrafts = ref<Record<string, string>>({})
  const users = ref<User[]>([])
  const roleDrafts = ref<Record<number, string[]>>({})
  const rolePermissionDrafts = ref<Record<string, string[]>>({})
  const roleLabelDrafts = ref<Record<string, string>>({})
  const resetPasswords = ref<Record<number, string>>({})
  const materialForm = ref({ sku: '', name: '', unit: '件' })
  const supplierForm = ref({ name: '' })
  const receiptForm = ref({
    supplier_id: 0,
    warehouse_id: 1,
    purchase_order_id: null as number | null,
    reference: '',
    lines: [{ material_id: 0, quantity: '1' }]
  })
  const goodsReceiptForm = ref({
    purchase_order_id: 0,
    warehouse_id: 1,
    reference: '',
    lines: [] as { purchase_order_line_id: number; accepted_quantity: string;
      rejected_quantity: string; rejection_reason: string }[]
  })
  const purchaseForm = ref({
    supplier_id: 0,
    reference: '',
    lines: [{ material_id: 0, quantity: '1', unit_price: '0' }]
  })
  const purchaseRequestForm = ref({
    requestId: null as number | null,
    reference: '',
    note: '',
    lines: [{ material_id: 0, quantity: '1' }]
  })
  const requestConversionForm = ref({
    requestId: 0,
    supplier_id: 0,
    reference: '',
    lines: [] as { material_id: number; purchase_request_line_id: number; quantity: string; unit_price: string }[]
  })
  const requestRejectReasons = ref<Record<number, string>>({})
  const purchaseReturnForm = ref({
    receipt_id: 0,
    reason: '',
    lines: [] as { receipt_line_id: number; quantity: string }[]
  })
  const paymentForm = ref({
    kind: 'receivable' as 'receivable' | 'payable',
    order_id: 0,
    action: 'settlement' as 'settlement' | 'refund',
    amount: '',
    reference: '',
    note: ''
  })
  const reversalReasons = ref<Record<number, string>>({})
  const bomForm = ref({
    product_material_id: 0,
    base_quantity: '1',
    note: '',
    lines: [{ component_material_id: 0, quantity: '1' }]
  })
  const workOrderForm = ref({
    bom_id: 0,
    warehouse_id: 1,
    target_quantity: '1',
    reference: '',
    note: ''
  })
  const materialIssueForm = ref({
    work_order_id: 0,
    warehouse_id: 1,
    reference: '',
    lines: [] as { work_order_line_id: number; quantity: string }[]
  })
  const materialReturnForm = ref({
    material_issue_id: 0,
    reason: '',
    lines: [] as { material_issue_line_id: number; quantity: string }[]
  })
  const completionForm = ref({
    work_order_id: 0,
    reported_quantity: '1',
    reference: ''
  })
  const inspectionDrafts = ref<
    Record<number, { accepted_quantity: string; qc_note: string }>
  >({})
  const completionReversalReasons = ref<Record<number, string>>({})
  const materialValuationForm = ref({
    material_issue_line_id: 0,
    unit_cost: '0',
    reference: '',
    note: ''
  })
  const productionChargeForm = ref({
    work_order_id: 0,
    kind: 'labor' as 'labor' | 'overhead',
    amount: '',
    reference: '',
    note: ''
  })
  const costReversalReasons = ref<Record<number, string>>({})
  const warehouseForm = ref({ code: '', name: '' })
  const otherInboundForm = ref({
    warehouse_id: 1,
    reason: 'other' as 'opening' | 'gift' | 'other',
    note: '',
    reference: '',
    lines: [{ material_id: 0, quantity: '1' }]
  })
  const otherInboundReversalReasons = ref<Record<number, string>>({})
  const otherOutboundForm = ref({
    warehouse_id: 1,
    reason: 'other' as 'scrap' | 'sample' | 'other',
    note: '',
    reference: '',
    lines: [{ material_id: 0, quantity: '1' }]
  })
  const otherOutboundReversalReasons = ref<Record<number, string>>({})
  const adjustmentForm = ref({
    warehouse_id: 1,
    reason: '',
    reference: '',
    lines: [{ material_id: 0, quantity: '1' }]
  })
  const adjustmentDecisionReasons = ref<Record<number, string>>({})
  const adjustmentReversalReasons = ref<Record<number, string>>({})
  const transferForm = ref({
    from_warehouse_id: 1,
    to_warehouse_id: 0,
    reference: '',
    lines: [{ material_id: 0, quantity: '1' }]
  })
  const transferReversalReasons = ref<Record<number, string>>({})
  const salesReturnReversalReasons = ref<Record<number, string>>({})
  const purchaseReturnReversalReasons = ref<Record<number, string>>({})
  const receiptReversalReasons = ref<Record<number, string>>({})
  const shipmentReversalReasons = ref<Record<number, string>>({})
  const stocktakeForm = ref({
    warehouse_id: 1,
    reference: '',
    lines: [{ material_id: 0, counted_quantity: '0' }]
  })
  const stocktakeReversalReasons = ref<Record<number, string>>({})
  const customerForm = ref({ name: '' })
  const salesForm = ref({
    customer_id: 0,
    reference: '',
    lines: [{ material_id: 0, quantity: '1', unit_price: '0' }]
  })
  const shipmentForm = ref({
    sales_order_id: 0,
    warehouse_id: 1,
    reference: '',
    lines: [{ material_id: 0, quantity: '1' }]
  })
  const salesReturnForm = ref({
    shipment_id: 0,
    warehouse_id: 1,
    reason: '',
    lines: [] as { shipment_line_id: number; quantity: string }[]
  })
  const newUser = ref({
    full_name: '', employee_no: '', phone: '',
    username: '',
    password: '',
    roles: ['viewer'] as string[]
  })
  // 新角色默认不授予任何权限，必须由管理员明确勾选授权范围。
  const newRole = ref({ label: '', permissions: [] as string[] })
  const passwordChange = ref({ current_password: '', new_password: '' })
  const server = ref<ServerProfile | null>(null)
  const candidate = ref<ConnectionCandidate | null>(null)
  const recentServers = ref<ServerProfile[]>([])
  const discoveries = ref<DiscoveryResult[]>([])
  const scanSeconds = ref(0)
  const scanning = ref(false)
  const manualForm = ref({ address: '', port: 8000 })
  const hostForm = ref({
    name: '我的 Nexora ERP',
    dataDir: '',
    port: 8000,
    username: 'admin',
    password: '',
    confirm: ''
  })
  const trustChecked = ref(false)
  const host = ref<HostStatus>({
    configured: false,
    running: false,
    systemManaged: false,
    migrationNeeded: false,
    fingerprint: null
  })
  const connectionLost = ref(false)
  // 连接恢复反馈独立于业务操作提示，供所有页面共用的底栏展示。
  const connectionNotice = ref('')

  const selectedSalesReturnShipment = computed(() =>
    shipments.value.find(
      (item) => item.id === salesReturnForm.value.shipment_id
    )
  )
  const selectedPurchaseReturnReceipt = computed(() =>
    receipts.value.find(
      (item) => item.id === purchaseReturnForm.value.receipt_id
    )
  )
  const selectedIssueOrder = computed(() =>
    workOrders.value.find(
      (item) => item.id === materialIssueForm.value.work_order_id
    )
  )
  const selectedReturnIssue = computed(() =>
    materialIssues.value.find(
      (item) => item.id === materialReturnForm.value.material_issue_id
    )
  )
  const selectedCompletionOrder = computed(() =>
    workOrders.value.find(
      (item) => item.id === completionForm.value.work_order_id
    )
  )

  return {
    dashboardResult, dashboardPeriod, dashboardLoading, dashboardError,
    qualityOverview, qualityDetail, qualityLoading, qualityError, qualityEdit, qualityForm,
    afterSalesOverview,afterSalesDetail,afterSalesLoading,afterSalesError,afterSalesEdit,afterSalesForm,
    equipmentOverview,equipmentDetail,equipmentLoading,equipmentError,equipmentEdit,equipmentForms,
    mrpPlans, mrpOptions, mrpDetail, mrpCheck, mrpChanges, mrpPolicyChanges, mrpForm, mrpLoading, mrpError,
    crmOptions, crmOverview, crmDetail, crmChanges, crmForms, crmEdit, crmLoading, crmError,
    screen,
    openedRouteKeys,
    expandedGroupKey,
    version,
    notice,
    error,
    busy,
    user,
    username,
    password,
    materials,
    materialCategories,
    suppliers,
    supplierMaterials,
    stock,
    inventoryValuation,
    inventoryCostInputs,
    inventoryCostForm,
    movements,
    ledgerResult,
    stockAdjustments,
    purchaseReportQuery,
    inventoryReportQuery,
    purchaseReportResult,
    inventoryReportResult,
    ledgerQuery,
    otherInbounds,
    warehouseOutbounds,
    receipts,
    goodsReceipts,
    purchaseOrders,
    purchaseRequests,
    purchaseReturns,
    receivablesPayables,
    financeAccounts,
    ledgerAccounts,
    journals,
    businessJournalSources,
    businessJournalOptions,
    businessJournalPolicyChanges,
    businessJournalLoading,
    businessJournalError,
    profitTransferOptions,
    profitTransferPreview,
    profitTransferPolicyChanges,
    profitTransferLoading,
    profitTransferError,
    statementOptions,
    auxiliaryOptions,
    auxiliaryChanges,
    auxiliaryQuery,
    auxiliaryReport,
    auxiliaryLoading,
    auxiliaryError,
    statementPolicyChanges,
    statementQuery,
    statementReport,
    statementArchives,
    statementArchive,
    statementLoading,
    statementArchiveLoading,
    statementError,
    openingBalances,
    subledgerOpenings,
    subledgerOptions,
    subledgerForm,
    subledgerQuery,
    subledgerReport,
    subledgerPayments,
    subledgerChanges,
    subledgerCheck,
    subledgerLoading,
    subledgerError,
    openingBalanceOptions,
    openingBalanceForm,
    ledgerReportQuery,
    ledgerReportResult,
    ledgerReportAccounts,
    ledgerReportLoading,
    ledgerReportError,
    ledgerReportJournal,
    ledgerReportJournalLoading,
    ledgerReportJournalError,
    journalOptions,
    journalForm,
    accountingPeriods,
    periodClosingCheck,
    periodClosingHistory,
    periodClosingLoading,
    periodClosingError,
    ledgerAccountForm,
    accountingPeriodForm,
    paymentRecords,
    boms,
    workOrders,
    materialIssues,
    materialReturns,
    productionCompletions,
    productionCostReport,
    productionCostSettlements,
    productionSettlementForm,
    settlementReversalReasons,
    warehouses,
    transfers,
    stocktakes,
    customers,
    salesOrders,
    shipments,
    salesReturns,
    selectedWarehouseId,
    roles,
    menuIcons,
    permissions,
    permissionLabelDrafts,
    users,
    roleDrafts,
    rolePermissionDrafts,
    roleLabelDrafts,
    resetPasswords,
    materialForm,
    supplierForm,
    receiptForm,
    goodsReceiptForm,
    purchaseForm,
    purchaseRequestForm,
    requestConversionForm,
    requestRejectReasons,
    purchaseReturnForm,
    paymentForm,
    reversalReasons,
    bomForm,
    workOrderForm,
    materialIssueForm,
    materialReturnForm,
    completionForm,
    inspectionDrafts,
    completionReversalReasons,
    materialValuationForm,
    productionChargeForm,
    costReversalReasons,
    warehouseForm,
    otherInboundForm,
    otherInboundReversalReasons,
    otherOutboundForm,
    otherOutboundReversalReasons,
    adjustmentForm,
    adjustmentDecisionReasons,
    adjustmentReversalReasons,
    transferForm,
    transferReversalReasons,
    salesReturnReversalReasons,
    purchaseReturnReversalReasons,
    receiptReversalReasons,
    shipmentReversalReasons,
    stocktakeForm,
    stocktakeReversalReasons,
    customerForm,
    salesForm,
    shipmentForm,
    salesReturnForm,
    newUser,
    newRole,
    passwordChange,
    server,
    candidate,
    recentServers,
    discoveries,
    scanSeconds,
    scanning,
    manualForm,
    hostForm,
    trustChecked,
    host,
    connectionLost,
    connectionNotice,
    selectedSalesReturnShipment,
    selectedPurchaseReturnReceipt,
    selectedIssueOrder,
    selectedReturnIssue,
    selectedCompletionOrder
  }
}

export type AppState = ReturnType<typeof createAppState>
