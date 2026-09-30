import type { MenuIconKey, MenuIconSetting } from './menu-icons'
// 桌面端与本地服务共用的数据契约；渲染进程不能自行指定请求地址。
// 账号资料与登录名分开，工号可为空；非空工号由服务端保证唯一。
export interface UserProfile { full_name: string; employee_no: string; phone: string }
export interface User extends UserProfile {
  id: number
  username: string
  is_active: boolean
  roles: string[]
  permissions: string[]
}

export interface PermissionGroup { code: string; label: string }
// 模块与单据层级用于展示；角色和服务端仍只保存、校验操作叶子的 code。
export interface Permission { code: string; label: string; group_path: PermissionGroup[] }
export interface Role { code: string; label: string; is_builtin: boolean; permissions: string[] }
// 分页列表返回筛选后的总数与有效页码，其他业务的选项列表仍使用原接口。
export interface PageQuery { query: string; page: number; page_size: number }
export interface TradeTermsInput { tax_rate?: string; discount_rate?: string; includes_tax?: boolean }
export type FinanceToolAction = 'openings' | 'create_opening' | 'confirm_opening' | 'cancel_opening' | 'settle_opening' | 'banks' | 'import_bank' | 'match_bank' | 'unmatch_bank' | 'reconcile' | 'statements' | 'auxiliary' | 'history'
export interface FinanceToolResult { rows: TableRow[]; snapshot_id: string; columns: {key: string; title: string}[]; totals: Record<string,string | boolean> }
export interface PageResult<T> { items: T[]; total: number; page: number; page_size: number }

export interface SupplierMaterial { supplier_id: number; material_id: number }
export interface Supplier { id: number; name: string }
// 客户负责人和修改版本由服务端维护，订单负责人不会随客户自动转交。
export interface CustomerInput {
  name: string; contact_name?: string; phone?: string; address?: string; note?: string
  owner_id?: number | null; is_active?: boolean
}
export interface Customer {
  id: number; name: string; owner_id: number | null; owner_name: string
  contact_name: string; phone: string; address: string; note: string; is_active: boolean | number; version: number
}
export interface CustomerChange {
  id: number; action: string; reason: string; changed_by: number; created_at: string
}
export interface AccountingPeriod {
  id: number; code: string; name: string; start_date: string; end_date: string
  status: 'open' | 'closed'; version: number; created_by: number; created_at: string
}
export interface PeriodClosingCheck {
  period: AccountingPeriod; can_close: boolean
  blockers: { code: string; message: string; ids: number[] }[]; warnings: string[]
  ledger_totals: LedgerReportTotals; inventory_total: string | null
  movement_count: number; business_unpriced_count: number
}
export interface PeriodClosingEvidence {
  period: AccountingPeriod; currency: 'CNY'; time_basis: 'UTC'; opening_balance_id: number | null
  ledger: { rows: Record<string, string>[]; totals: LedgerReportTotals }
  inventory: InventoryValuationReport; business_sources: ReceivablesPayables
  payments: Pick<PaymentRecord, 'id' | 'kind' | 'order_id' | 'action' | 'amount' | 'reference' | 'note' | 'reverses_id' | 'created_by' | 'created_at'>[]; posted_journal_ids: number[]
  profit_transfer?: { required: boolean; residuals: ProfitTransferBalance[]; policy: ProfitTransferPolicy; journal_id: number | null; excluded_cost_accounts?: ProfitTransferExcludedCost[] }
}
export interface PeriodClosingRecord {
  snapshot_id?: string
  id: number; period_id: number; period_version: number; action: 'close' | 'reopen'
  evidence: PeriodClosingEvidence | { previous_closing_id: number; period: AccountingPeriod }
  reason: string; created_by: number; created_by_name: string; created_at: string
}
export interface FinanceMetadataChange<T> {
  id: number; before: T | null; after: T; reason: string
  changed_by: number; changed_by_name: string; created_at: string
}
export interface LedgerAccountInput {
  code: string; name: string; category: LedgerCategory; normal_balance: 'debit' | 'credit'; reason: string
}
export type JournalStatus = 'draft' | 'submitted' | 'approved' | 'rejected' | 'posted' | 'cancelled'
export type JournalAction = 'submit' | 'approve' | 'reject' | 'post' | 'cancel'
export interface JournalLineInput { customer_id?: number | null; supplier_id?: number | null; department?: string; project?: string; account_id: number; summary: string; debit: string; credit: string }
export interface JournalInput { reference: string; journal_date: string; note: string; reason: string; lines: JournalLineInput[] }
export interface JournalLine extends JournalLineInput {
  id: number; journal_id: number; position: number; account_code: string; account_name: string
  category: LedgerCategory; normal_balance: 'debit' | 'credit'
}
export interface Journal {
  id: number; reference: string; journal_date: string; period_id: number; period_code: string; note: string
  currency: 'CNY'; status: JournalStatus; version: number; reversal_of_id: number | null; reversal_journal_id: number | null
  created_by: number; created_by_name: string; created_at: string; author_ids: number[]
  submitted_by: number | null; reviewed_by: number | null; posted_by: number | null; cancelled_by: number | null
  submitted_at: string | null; reviewed_at: string | null; posted_at: string | null; cancelled_at: string | null
  lines: JournalLine[]; total_debit: string; total_credit: string
  business_source?: { key: string; evidence: BusinessJournalEvidence; mapping: BusinessJournalMapping; policy_version: number } | null
  profit_transfer?: { period_id: number; evidence: ProfitTransferEvidence; policy: ProfitTransferPolicy } | null
}
export interface ProfitTransferPolicy {
  version: number; start_date: string; target_account_id: number | null; cost_account_ids: number[]
  changed_by?: number; created_at?: string
}
export interface ProfitTransferBalance {
  account_id: number; code: string; name: string; category: LedgerCategory; balance: string; debit: string; credit: string
}
export interface ProfitTransferExcludedCost { account_id: number; code: string; name: string; balance: string }
export interface ProfitTransferEvidence {
  snapshot_id?: string
  period_id: number; start_date: string; end_date: string; policy_version: number; target_account_id: number | null
  cost_account_ids: number[]; fingerprint: string; currency: 'CNY'; time_basis: 'UTC'
  rows: ProfitTransferBalance[]; lines: Pick<JournalLineInput, 'account_id' | 'debit' | 'credit'>[]
  net_profit: string; blockers: string[]; excluded_cost_accounts: ProfitTransferExcludedCost[]
  target_account: LedgerAccount | null
  sources: { journal_id: number; line_id: number; account_id: number; journal_date: string; reference: string; reversal_of_id: number | null; debit: string; credit: string }[]
  opening_sources: { line_id: number; opening_balance_id: number; account_id: number; debit: string; credit: string }[]
}
export interface ProfitTransferPreview {
  snapshot_id?: string
  period: AccountingPeriod; policy_version: number; evidence: ProfitTransferEvidence; fingerprint: string
  can_generate: boolean; blockers: string[]; warnings: string[]; journal_id: number | null; journal_status: JournalStatus | null
}
export interface ProfitTransferOptions { policy: ProfitTransferPolicy; accounts: LedgerAccount[]; periods: AccountingPeriod[] }
export interface ProfitTransferGenerateInput {
  period_id: number; period_version: number; policy_version: number; fingerprint: string; reference: string; reason: string
}
export type BusinessJournalRole = 'inventory' | 'payable' | 'receivable' | 'income' | 'sales_cost' | 'cash' | 'price_variance' | 'work_in_progress' | 'labor_accrual' | 'overhead_accrual' | 'inventory_offset'
export type BusinessJournalMapping = Partial<Record<BusinessJournalRole, number>>
export interface BusinessJournalPolicy { version: number; start_date: string; mapping: BusinessJournalMapping; changed_by?: number; created_at?: string }
export interface BusinessJournalEvidence {
  snapshot_id?: string
  key: string; source_type: string; source_id: number; label: string; source_date: string; fingerprint: string
  roles: Partial<Record<BusinessJournalRole, string>>; blockers: string[]; warnings: string[]
  labels: Record<string, string>
  movements: Pick<InventoryValuationMovement, 'id' | 'warehouse_id' | 'material_id' | 'quantity' | 'source_line_id' | 'created_at' | 'amount' | 'accounting_amount' | 'unit_cost' | 'cost_source' | 'cost_input_id' | 'settlement_id'>[]
  business: Pick<FinancialEntry, 'source_line_id' | 'order_id' | 'party_id' | 'material_id' | 'quantity' | 'unit_price' | 'amount' | 'kind' | 'posted_at'>[]
  records: Record<string, string | number | null>[]
}
export interface BusinessJournalCandidate extends BusinessJournalEvidence {
  policy_version: number; journal_id: number | null; journal_status: JournalStatus | null
  minimum_date: string; can_generate: boolean; no_amount: boolean
}
export interface BusinessJournalOptions { policy: BusinessJournalPolicy; roles: Record<BusinessJournalRole, string>; accounts: LedgerAccount[] }
export interface BusinessJournalGenerateInput { source_key: string; fingerprint: string; policy_version: number; reference: string; journal_date: string; reason: string }
export interface JournalChange extends FinanceMetadataChange<Omit<Journal, 'period_code' | 'created_by_name' | 'reversal_journal_id' | 'author_ids'>> { action: JournalAction | 'create' | 'update' }
export type OpeningBalanceStatus = 'draft' | 'submitted' | 'approved' | 'rejected' | 'confirmed' | 'cancelled' | 'reversed'
export type OpeningBalanceAction = 'submit' | 'approve' | 'reject' | 'confirm' | 'cancel' | 'reverse'
export interface OpeningBalanceInput { reference: string; effective_date: string; note: string; reason: string; lines: JournalLineInput[] }
export interface OpeningBalance extends Omit<Journal, 'journal_date' | 'status' | 'posted_by' | 'posted_at' | 'reversal_of_id' | 'reversal_journal_id' | 'lines'> {
  effective_date: string; status: OpeningBalanceStatus; active_key: number | null
  confirmed_by: number | null; confirmed_at: string | null; reversed_by: number | null; reversed_at: string | null
  lines: (Omit<JournalLine, 'journal_id'> & { opening_balance_id: number })[]
}
export interface OpeningBalanceChange extends FinanceMetadataChange<Omit<OpeningBalance, 'period_code' | 'created_by_name' | 'author_ids'>> { action: OpeningBalanceAction | 'create' | 'update' }
export interface LedgerReportQuery {
  paged?: boolean
  kind: 'trial_balance' | 'account_ledger'; from_date: string; to_date: string; account_id: number | null
}
export interface LedgerReportTotals {
  opening_debit: string; opening_credit: string; debit: string; credit: string
  closing_debit: string; closing_credit: string; balanced?: boolean; code?: string; name?: string
}
export interface LedgerReportResult {
  snapshot_id?: string
  kind: LedgerReportQuery['kind']; filters: LedgerReportQuery
  columns: { key: string; title: string }[]; rows: Record<string, string>[]
  totals: LedgerReportTotals; periods: AccountingPeriod[]; generated_at: string; csv: string
  opening_balance: (OpeningBalance & { changes: OpeningBalanceChange[] }) | null
}
export interface AccountingPeriodInput {
  code: string; name: string; start_date: string; end_date: string; reason: string
}
// 非采购入库沿用单据确认和冲销模式，不进入采购应付来源。
export interface OtherInbound {
  id: number
  warehouse_id: number
  warehouse_name: string
  reason: 'opening' | 'gift' | 'other'
  note: string
  reference: string
  status: 'draft' | 'posted' | 'cancelled'
  created_by: number
  created_by_name: string
  posted_by: number | null
  posted_by_name: string | null
  cancelled_by: number | null
  created_at: string
  posted_at: string | null
  cancelled_at: string | null
  reversal_id: number | null
  reversal_reason: string | null
  reversed_by: number | null
  reversed_by_name: string | null
  reversed_at: string | null
  lines: ReceiptLine[]
}
// 出库确认才扣库存；后续采购退货沿用仓库确认单。
export interface WarehouseOutbound {
  id: number
  warehouse_id: number
  warehouse_name: string
  source_kind: 'other' | 'purchase_return'
  reason: 'scrap' | 'sample' | 'other' | 'purchase_return'
  note: string
  reference: string
  status: 'draft' | 'posted' | 'cancelled'
  created_by: number
  created_by_name: string
  posted_by: number | null
  posted_by_name: string | null
  cancelled_by: number | null
  created_at: string
  posted_at: string | null
  cancelled_at: string | null
  reversal_id: number | null
  reversal_reason: string | null
  reversed_by: number | null
  reversed_by_name: string | null
  reversed_at: string | null
  lines: ReceiptLine[]
  purchase_return_id: number | null
}
// 正负调整量在审批前固定，审批人与建单人必须不同。
export interface StockAdjustment {
  id: number
  warehouse_id: number
  warehouse_name: string
  reason: string
  reference: string
  status: 'draft' | 'submitted' | 'approved' | 'rejected' | 'cancelled' | 'posted'
  created_by: number
  created_by_name: string
  submitted_by: number | null
  reviewed_by: number | null
  reviewed_by_name: string | null
  posted_by: number | null
  posted_by_name: string | null
  review_reason: string
  created_at: string
  submitted_at: string | null
  reviewed_at: string | null
  posted_at: string | null
  reversal_id: number | null
  reversal_reason: string | null
  reversed_at: string | null
  lines: ReceiptLine[]
}
export interface Stock extends Material { quantity: string }
export interface InventoryValuationMovement {
  id: number
  warehouse_id: number
  material_id: number
  quantity: string
  source_type: string
  source_id: number
  source_line_id: number
  created_at: string
  unit_cost: string | null
  amount: string | null
  cost_source: 'purchase_order' | 'manual' | 'linked_movement' | 'moving_average' | 'unpriced' | 'production_settlement'
  settlement_id: number | null
  cost_input_id: number | null
  accounting_amount: string | null
}
export interface InventoryValuationReport {
  currency: 'CNY'
  method: 'moving_weighted_average'
  scope: 'company'
  total_amount: string | null
  materials: (Material & { quantity: string; amount: string | null;
    average_unit_cost: string | null })[]
  movements: InventoryValuationMovement[]
  unpriced_movement_ids: number[]
}
export interface InventoryCostInput {
  id: number
  movement_id: number
  unit_cost: string
  reference: string
  reason: string
  created_by: number
  created_by_name: string
  created_at: string
}
export interface ReceiptLine {
  id: number
  material_id: number
  sku: string
  material_name: string
  unit: string
  quantity: string
}
export interface ReceivedLine extends ReceiptLine {
  returned_quantity: string
  returnable_quantity: string
}
export interface Receipt {
  id: number
  supplier_id: number
  supplier_name: string
  purchase_order_id: number | null
  goods_receipt_id: number | null
  warehouse_id: number
  warehouse_name: string
  reference: string
  status: 'draft' | 'posted'
  created_by: number
  created_by_name: string
  posted_by: number | null
  created_at: string
  posted_at: string | null
  reversal_id: number | null
  reversal_reason: string | null
  reversed_by: number | null
  reversed_by_name: string | null
  reversed_at: string | null
  lines: ReceivedLine[]
}
// 收货单记录合格与拒收事实；只有合格数量会生成待确认入库单。
export interface GoodsReceiptLine {
  id: number
  purchase_order_line_id: number
  material_id: number
  sku: string
  material_name: string
  unit: string
  accepted_quantity: string
  rejected_quantity: string
  rejection_reason: string
}
export interface GoodsReceipt {
  id: number
  purchase_order_id: number
  supplier_id: number
  supplier_name: string
  warehouse_id: number
  warehouse_name: string
  inbound_receipt_id: number | null
  inbound_status: 'draft' | 'posted' | null
  inbound_reversal_id: number | null
  reference: string
  status: 'draft' | 'confirmed' | 'cancelled'
  created_by: number
  created_by_name: string
  confirmed_by: number | null
  confirmed_by_name: string | null
  cancelled_by: number | null
  created_at: string
  confirmed_at: string | null
  cancelled_at: string | null
  lines: GoodsReceiptLine[]
}
// 申请的已转数量包含未取消的订单草稿，由服务端在写事务内核算。
export interface PurchaseRequestLine extends ReceiptLine {
  ordered_quantity: string
  remaining_quantity: string
}
export interface PurchaseRequest {
  id: number
  reference: string
  note: string
  status: 'draft' | 'submitted' | 'approved' | 'rejected' | 'cancelled'
  created_by: number
  created_by_name: string
  submitted_by: number | null
  reviewed_by: number | null
  reviewed_by_name: string | null
  cancelled_by: number | null
  review_reason: string
  created_at: string
  submitted_at: string | null
  reviewed_at: string | null
  cancelled_at: string | null
  lines: PurchaseRequestLine[]
}
// 已入库数量由服务端按确认单据汇总，前端只展示而不自行累计。
export interface PurchaseOrderLine extends ReceiptLine {
  purchase_request_line_id: number | null
  unit_price: string
  received_quantity: string
  net_received_quantity: string
  returned_quantity: string
  remaining_quantity: string
  line_total: string
}
export interface PurchaseOrder {
  id: number
  purchase_request_id: number | null
  supplier_id: number
  supplier_name: string
  reference: string
  status: 'draft' | 'confirmed' | 'partially_received' | 'received' | 'cancelled'
  created_by: number
  created_by_name: string
  confirmed_by: number | null
  cancelled_by: number | null
  created_at: string
  confirmed_at: string | null
  cancelled_at: string | null
  lines: PurchaseOrderLine[]
  total_amount: string
}
// 历史未关联采购订单的入库单没有单价，退货金额明确为未知。
export interface PurchaseReturnLine extends ReceiptLine {
  receipt_line_id: number
  unit_price: string | null
  line_total: string | null
}
export interface PurchaseReturn {
  id: number
  receipt_id: number
  supplier_id: number
  supplier_name: string
  warehouse_id: number
  warehouse_name: string
  reason: string
  status: 'draft' | 'posted' | 'cancelled'
  outbound_id: number | null
  outbound_status: 'draft' | 'posted' | 'cancelled' | null
  created_by: number
  created_by_name: string
  posted_by: number | null
  cancelled_by: number | null
  created_at: string
  posted_at: string | null
  cancelled_at: string | null
  reversal_id: number | null
  reversal_reason: string | null
  reversed_by: number | null
  reversed_by_name: string | null
  reversed_at: string | null
  lines: PurchaseReturnLine[]
  total_amount: string | null
}
// 应收应付按已确认业务来源逐行推导，空金额表示原入库缺少合同单价。
export interface FinancialEntry {
  key: string
  kind: 'receivable' | 'payable'
  party_id: number
  party_name: string
  source_type: 'shipment' | 'shipment_reversal' | 'sales_return' | 'sales_return_reversal' | 'receipt' | 'receipt_reversal' | 'purchase_return' | 'purchase_return_reversal'
  source_id: number
  source_line_id: number
  order_id: number | null
  material_id: number
  sku: string
  quantity: string
  unit_price: string | null
  amount: string | null
  currency: 'CNY'
  posted_by: number | null
  posted_by_name: string | null
  posted_at: string
}
export interface ReceivablesPayables {
  currency: 'CNY'
  receivable_amount: string
  payable_amount: string
  unpriced_count: number
  entries: FinancialEntry[]
}
export interface FinanceAccount {
  kind: 'receivable' | 'payable'
  order_id: number
  party_id: number
  party_name: string
  currency: 'CNY'
  business_amount: string
  settled_amount: string
  outstanding_amount: string
  source_keys: string[]
}
// 原收付款和冲销均为独立、不可编辑的记录，负金额表示退款或反向冲销。
export interface PaymentRecord {
  id: number
  kind: 'receivable' | 'payable'
  order_id: number
  action: 'settlement' | 'refund' | 'reversal'
  amount: string
  reference: string
  note: string
  reverses_id: number | null
  created_by: number
  created_by_name: string
  created_at: string
  party_id: number
  party_name: string
  currency: 'CNY'
}
export interface FinanceOverview {
  report: ReceivablesPayables
  accounts: FinanceAccount[]
  payments: PaymentRecord[]
}
export interface BomLine {
  id: number
  component_material_id: number
  sku: string
  material_name: string
  unit: string
  quantity: string
}
// 生产工单将固定引用一个 BOM 版本，停用后历史内容仍可查询。
export interface Bom {
  id: number
  product_material_id: number
  product_sku: string
  product_name: string
  product_unit: string
  version: number
  base_quantity: string
  note: string
  status: 'draft' | 'active' | 'retired' | 'cancelled'
  created_by: number
  created_by_name: string
  activated_by: number | null
  retired_by: number | null
  cancelled_by: number | null
  created_at: string
  activated_at: string | null
  retired_at: string | null
  cancelled_at: string | null
  lines: BomLine[]
}
export interface WorkOrderLine {
  id: number
  component_material_id: number
  sku: string
  material_name: string
  unit: string
  required_quantity: string
  issued_quantity: string
  remaining_quantity: string
}
// 工单组件需求在建单时固定，旧 BOM 停用也不会改变已下达工单。
export interface WorkOrder {
  id: number
  bom_id: number
  bom_version: number
  product_material_id: number
  product_sku: string
  product_name: string
  product_unit: string
  warehouse_id: number
  warehouse_name: string
  target_quantity: string
  reported_quantity: string
  accepted_quantity: string
  rejected_quantity: string
  remaining_output_quantity: string
  reference: string
  note: string
  status: 'draft' | 'released' | 'in_progress' | 'completed' | 'cancelled'
  created_by: number
  created_by_name: string
  released_by: number | null
  completed_by: number | null
  cancelled_by: number | null
  created_at: string
  released_at: string | null
  completed_at: string | null
  cancelled_at: string | null
  lines: WorkOrderLine[]
}
export interface MaterialIssueLine {
  id: number
  work_order_line_id: number
  component_material_id: number
  sku: string
  material_name: string
  unit: string
  quantity: string
  returned_quantity: string
  returnable_quantity: string
}
// 确认后的领料单生成独立负向库存流水；原单据保留供追溯。
export interface MaterialIssue {
  id: number
  work_order_id: number
  warehouse_id: number
  warehouse_name: string
  reference: string
  status: 'draft' | 'posted' | 'cancelled'
  created_by: number
  created_by_name: string
  posted_by: number | null
  cancelled_by: number | null
  created_at: string
  posted_at: string | null
  cancelled_at: string | null
  lines: MaterialIssueLine[]
}
export interface MaterialReturnLine {
  id: number
  material_issue_line_id: number
  work_order_line_id: number
  component_material_id: number
  sku: string
  material_name: string
  unit: string
  quantity: string
}
// 退料引用原领料明细并回到原仓库，确认后生成独立正向流水。
export interface MaterialReturn {
  id: number
  material_issue_id: number
  work_order_id: number
  warehouse_id: number
  warehouse_name: string
  reason: string
  status: 'draft' | 'posted' | 'cancelled'
  created_by: number
  created_by_name: string
  posted_by: number | null
  cancelled_by: number | null
  created_at: string
  posted_at: string | null
  cancelled_at: string | null
  lines: MaterialReturnLine[]
}
// 完工单记录报工与质检结果；确认时只有合格数量进入成品仓库。
export interface ProductionCompletion {
  id: number
  work_order_id: number
  warehouse_id: number
  warehouse_name: string
  product_material_id: number
  product_sku: string
  product_name: string
  product_unit: string
  reported_quantity: string
  accepted_quantity: string | null
  rejected_quantity: string | null
  reference: string
  qc_note: string
  status: 'draft' | 'inspected' | 'posted' | 'reversed' | 'cancelled'
  created_by: number
  created_by_name: string
  inspected_by: number | null
  inspected_by_name: string | null
  posted_by: number | null
  cancelled_by: number | null
  created_at: string
  inspected_at: string | null
  posted_at: string | null
  cancelled_at: string | null
  reversal_id: number | null
  reversal_reason: string | null
  reversed_by: number | null
  reversed_by_name: string | null
  reversed_at: string | null
}
// 成本记录保留原始依据和冲销信息；材料金额随已确认退料后的净领料量计算。
export interface ProductionCostEntry {
  id: number
  work_order_id: number
  kind: 'material' | 'labor' | 'overhead'
  material_issue_line_id: number | null
  unit_cost: string | null
  amount: string | null
  reference: string
  note: string
  created_by: number
  created_by_name: string
  created_at: string
  material_sku: string | null
  material_name: string | null
  issue_quantity: string | null
  net_quantity: string | null
  current_amount: string | null
  included_in_current_cost?: boolean
  status: 'active' | 'reversed'
  reversal_id: number | null
  reversal_reason: string | null
  reversed_by: number | null
  reversed_by_name: string | null
  reversed_at: string | null
}
export interface ProductionCostOrder {
  work_order_id: number
  product_name: string
  work_order_status: WorkOrder['status']
  known_material_amount: string
  labor_amount: string
  overhead_amount: string
  total_amount: string | null
  unpriced_issue_count: number
  settlement_id: number | null
}
export interface ProductionMaterialSource {
  work_order_id: number
  material_issue_line_id: number
  material_issue_id: number
  movement_id: number
  sku: string
  material_name: string
  net_quantity: string
  unit_cost: string
  amount: string
  cost_source: 'inventory' | 'manual'
  cost_entry_id: number | null
}
export interface ProductionCostSettlement {
  id: number
  work_order_id: number
  reference: string
  note: string
  material_amount: string
  labor_amount: string
  overhead_amount: string
  total_amount: string
  accepted_quantity: string
  created_by: number
  created_by_name: string
  created_at: string
  status: 'active' | 'reversed'
  reversal_id: number | null
  reversal_reason: string | null
  reversed_by_name: string | null
  reversed_at: string | null
  allocations: { settlement_id: number; completion_id: number; movement_id: number; quantity: string; amount: string }[]
  material_sources: Omit<ProductionMaterialSource, 'work_order_id' | 'material_issue_id'>[]
  charges: { id: number; kind: 'labor' | 'overhead'; amount: string; reference: string; created_by: number; created_at: string }[]
}
export interface ProductionCostReport {
  currency: 'CNY'
  orders: ProductionCostOrder[]
  entries: ProductionCostEntry[]
  material_sources: ProductionMaterialSource[]
  unpriced_lines: { material_issue_line_id: number; material_issue_id: number; work_order_id: number;
    sku: string; material_name: string; unit: string; net_quantity: string }[]
}
// 销售订单剩余量由已确认的出库单计算，草稿不会预先扣减。
export interface SalesOrderLine extends ReceiptLine {
  unit_price: string | null
  shipped_quantity: string
  returned_quantity: string
  net_delivered_quantity: string
  remaining_quantity: string
  line_total: string | null
}
export interface SalesOrder {
  id: number
  customer_id: number
  customer_name: string
  reference: string
  status: 'draft' | 'confirmed' | 'partially_shipped' | 'shipped' | 'cancelled'
  created_by: number
  created_by_name: string
  confirmed_by: number | null
  cancelled_by: number | null
  created_at: string
  confirmed_at: string | null
  cancelled_at: string | null
  lines: SalesOrderLine[]
  total_amount: string | null
  amount_visible: boolean
  owner_id: number | null
  owner_version: number
}
export interface Shipment {
  id: number
  sales_order_id: number
  warehouse_id: number
  warehouse_name: string
  customer_name: string
  reference: string
  status: 'draft' | 'posted' | 'cancelled'
  created_by: number
  created_by_name: string
  posted_by: number | null
  cancelled_by: number | null
  created_at: string
  posted_at: string | null
  cancelled_at: string | null
  reversal_id: number | null
  reversal_reason: string | null
  reversed_by: number | null
  reversed_by_name: string | null
  reversed_at: string | null
  lines: ShipmentLine[]
}
export interface ShipmentLine extends ReceiptLine {
  returned_quantity: string
  returnable_quantity: string
}
// 退货明细固定关联原出库行，金额沿用原销售单价，由服务端计算。
export interface SalesReturnLine extends ReceiptLine {
  shipment_line_id: number
  unit_price: string | null
  line_total: string | null
}
export interface SalesReturn {
  id: number
  shipment_id: number
  sales_order_id: number
  warehouse_id: number
  warehouse_name: string
  customer_name: string
  reason: string
  status: 'draft' | 'posted' | 'cancelled'
  created_by: number
  created_by_name: string
  posted_by: number | null
  cancelled_by: number | null
  created_at: string
  posted_at: string | null
  cancelled_at: string | null
  reversal_id: number | null
  reversal_reason: string | null
  reversed_by: number | null
  reversed_by_name: string | null
  reversed_at: string | null
  lines: SalesReturnLine[]
  total_amount: string | null
  amount_visible: boolean
  owner_id: number | null
  owner_version: number
}
// 调拨单沿用单据的状态与明细结构，同时明确记录两个仓库。
export interface Transfer extends Omit<Receipt, 'supplier_id' | 'supplier_name' | 'warehouse_id' | 'warehouse_name'> {
  from_warehouse_id: number
  from_warehouse_name: string
  to_warehouse_id: number
  to_warehouse_name: string
  reversal_id: number | null
  reversal_reason: string | null
  reversed_by: number | null
  reversed_by_name: string | null
  reversed_at: string | null
}
// 盘点差异由服务端根据建单快照计算，桌面端不能自行修改账面数量。
export interface StocktakeLine {
  id: number
  material_id: number
  sku: string
  material_name: string
  unit: string
  book_quantity: string
  counted_quantity: string
  difference: string
}
export interface Stocktake {
  id: number
  warehouse_id: number
  warehouse_name: string
  reference: string
  status: 'draft' | 'posted' | 'cancelled'
  created_by: number
  created_by_name: string
  posted_by: number | null
  cancelled_by: number | null
  created_at: string
  posted_at: string | null
  cancelled_at: string | null
  reversal_id: number | null
  reversal_reason: string | null
  reversed_by: number | null
  reversed_by_name: string | null
  reversed_at: string | null
  lines: StocktakeLine[]
}
export interface Movement {
  id: number
  warehouse_id: number
  warehouse_name: string
  material_id: number
  sku: string
  material_name: string
  unit: string
  quantity: string
  source_type: 'receipt' | 'receipt_reversal' | 'other_inbound' | 'other_inbound_reversal' | 'other_outbound' | 'other_outbound_reversal' | 'adjustment' | 'adjustment_reversal' | 'transfer_out' | 'transfer_in' | 'transfer_reversal_out' | 'transfer_reversal_in' | 'stocktake' | 'stocktake_reversal' | 'shipment' | 'shipment_reversal' | 'sales_return' | 'sales_return_reversal' | 'purchase_return' | 'purchase_return_reversal' | 'material_issue' | 'material_return' | 'production_completion' | 'production_completion_reversal'
  source_id: number
  source_line_id: number
  receipt_id: number | null
  receipt_reversal_id: number | null
  other_inbound_id: number | null
  other_inbound_reversal_id: number | null
  other_outbound_id: number | null
  other_outbound_reversal_id: number | null
  adjustment_id: number | null
  adjustment_reversal_id: number | null
  transfer_id: number | null
  transfer_reversal_id: number | null
  stocktake_id: number | null
  stocktake_reversal_id: number | null
  shipment_id: number | null
  shipment_reversal_id: number | null
  sales_return_id: number | null
  sales_return_reversal_id: number | null
  purchase_return_id: number | null
  purchase_return_reversal_id: number | null
  material_issue_id: number | null
  material_return_id: number | null
  production_completion_id: number | null
  production_completion_reversal_id: number | null
  created_by: number | null
  created_at: string
}

// 台账按同一服务端筛选结果给出期初、逐笔余额和期末。
export interface LedgerGroup {
  warehouse_id: number
  warehouse_name: string
  material_id: number
  sku: string
  material_name: string
  unit: string
  opening_quantity: string
  closing_quantity: string
}
export interface LedgerRow {
  id: number
  warehouse_id: number
  warehouse_name: string
  material_id: number
  sku: string
  material_name: string
  unit: string
  quantity: string
  source_type: string
  source_id: number
  source_line_id: number
  created_at: string
  created_by_name: string | null
  balance_quantity: string
}
export interface LedgerResult {
  snapshot_id?: string groups: LedgerGroup[]; rows: LedgerRow[] }
export interface LedgerQuery {
  paged?: boolean
  warehouse_id: number | null
  material_id: number | null
  from_date: string | null
  to_date: string | null
  source_type: string | null
}

export type ReportKind = 'purchase_requests' | 'purchase_orders' | 'receiving_returns' | 'inventory_balance' | 'stock_flow'
export interface ReportQuery {
  paged?: boolean
  kind: ReportKind
  warehouse_id: number | null
  material_id: number | null
  supplier_id: number | null
  from_date: string | null
  to_date: string | null
}
export interface ReportResult {
  snapshot_id?: string
  kind: ReportKind
  columns: { key: string; title: string }[]
  rows: Record<string, string>[]
  csv: string
}

// 每个数据集只允许服务端固定白名单查询；默认每页 20，最多 100。
export type TableDataset = 'inventoryLots' | 'salesOrderLines' | 'businessSources' | 'businessPolicyHistory' | 'profitPolicyHistory' | 'financeCustomers' | 'boundMaterials' | 'periodClosingHistory' | 'closingEvidence' | 'journalLines' | 'openingLines' | 'snapshot' | 'inventoryValuationMaterials' | 'inventoryValuationMovements' | 'productionCostOrders' | 'productionCostEntries' | 'productionMaterialSources' | 'financeAccounts' | 'financialSources' | 'materials' | 'suppliers' | 'supplierMaterials' | 'customers' | 'warehouses' | 'users' | 'roles' | 'purchaseRequests' | 'purchaseOrders' | 'goodsReceipts' | 'receipts' | 'purchaseReturns' | 'otherInbounds' | 'warehouseOutbounds' | 'stockAdjustments' | 'transfers' | 'stocktakes' | 'salesOrders' | 'shipments' | 'salesReturns' | 'boms' | 'workOrders' | 'materialIssues' | 'materialReturns' | 'productionCompletions' | 'productionCostSettlements' | 'ledgerAccounts' | 'accountingPeriods' | 'journals' | 'openingBalances' | 'paymentRecords' | 'inventoryCostInputs' | 'customerHistory' | 'journalHistory' | 'openingHistory' | 'ledgerAccountHistory' | 'periodHistory' | 'movements' | 'stock'
export interface TableQuery extends PageQuery {
  snapshot_id?: string; snapshot_path?: string
  dataset: TableDataset; sort?: string; descending?: boolean
  filters?: Record<string, string | number | boolean | null>
}
export type TableRow = Record<string, unknown>

export interface ErpOperations {
  snapshotCsv: { input: { snapshot_id: string }; output: { csv: string } }
  financeTools: { input: { action: FinanceToolAction; payload: Record<string, unknown> }; output: FinanceToolResult }
  queryTrace: { input: {kind:'sales_order'|'work_order'|'shipment'|'lot'|'receipt'; id:number}; output: {snapshot_id:string; nodes:TableRow[]; edges:TableRow[]; totals:{nodes:number;edges:number}} }
  allocateSalesWork: { input: {work_order_id:number;lines:{sales_order_line_id:number;quantity:string}[];reason:string}; output:{work_order_id:number;allocated_quantity:string} }
  queryTable: { input: TableQuery; output: PageResult<TableRow> & { metadata?: Record<string, unknown> | null } }
  setupStatus: { input: undefined; output: { needs_setup: boolean } }
  bootstrap: { input: { username: string; password: string }; output: User }
  login: { input: { username: string; password: string }; output: User }
  logout: { input: undefined; output: void }
  me: { input: undefined; output: User }
  changePassword: { input: { current_password: string; new_password: string }; output: void }
  menuIcons: { input: undefined; output: MenuIconSetting[] }
  saveMenuIcon: { input: { key: string; icon: MenuIconKey | null; version: number }; output: MenuIconSetting }
  permissions: { input: undefined; output: Permission[] }
  // 仅修改权限目录的展示文案；授权仍以 code 为准。
  updatePermissionLabel: { input: { code: string; label: string }; output: Pick<Permission, 'code' | 'label'> }
  roles: { input: undefined; output: Role[] }
  createRole: { input: { code: string; label: string; permissions: string[] }; output: Role }
  updateRole: { input: { code: string; label: string; permissions: string[] }; output: Role }
  users: { input: undefined; output: User[] }
  createUser: { input: UserProfile & { username: string; password: string; roles: string[] }; output: User }
  updateUser: { input: UserProfile & { userId: number; roles: string[] }; output: User }
  setUserRoles: { input: { userId: number; roles: string[] }; output: User }
  setUserStatus: { input: { userId: number; is_active: boolean }; output: User }
  resetUserPassword: { input: { userId: number; password: string }; output: void }
  suppliers: { input: undefined; output: Supplier[] }
  querySuppliers: { input: PageQuery; output: PageResult<Supplier> }
  updateMaterial: { input: { id: number; sku: string; name: string; unit: string }; output: Material }
  deleteMaterial: { input: { id: number }; output: void }
  updateSupplier: { input: { id: number; name: string }; output: Supplier }
  deleteSupplier: { input: { id: number }; output: void }
  updateWarehouse: { input: { id: number; code: string; name: string }; output: Warehouse }
  deleteWarehouse: { input: { id: number }; output: void }
  supplierMaterials: { input: undefined; output: SupplierMaterial[] }
  bindSupplierMaterial: { input: { supplierId: number; materialId: number }; output: void }
  unbindSupplierMaterial: { input: { supplierId: number; materialId: number }; output: void }
  createSupplier: { input: { name: string }; output: Supplier }
  customers: { input: undefined; output: Customer[] }
  createCustomer: { input: CustomerInput; output: Customer }
  updateCustomer: { input: CustomerInput & { id: number; version: number; reason: string }; output: Customer }
  customerHistory: { input: { id: number }; output: CustomerChange[] }
  transferSalesOwner: { input: { orderId: number; owner_id: number; version: number; reason: string }; output: { order_id: number; owner_id: number; version: number } }
  materials: { input: undefined; output: Material[] }
  createMaterial: { input: { sku: string; name: string; unit: string }; output: Material }
  warehouses: { input: undefined; output: Warehouse[] }
  otherInbounds: { input: undefined; output: OtherInbound[] }
  createOtherInbound: { input: { warehouse_id: number; reason: 'opening' | 'gift' | 'other'; note: string; reference: string; lines: { material_id: number; quantity: string }[] }; output: OtherInbound }
  postOtherInbound: { input: { inboundId: number }; output: OtherInbound }
  cancelOtherInbound: { input: { inboundId: number }; output: OtherInbound }
  reverseOtherInbound: { input: { inboundId: number; reason: string }; output: OtherInbound }
  warehouseOutbounds: { input: undefined; output: WarehouseOutbound[] }
  createOtherOutbound: { input: { warehouse_id: number; reason: 'scrap' | 'sample' | 'other'; note: string; reference: string; lines: { material_id: number; quantity: string }[] }; output: WarehouseOutbound }
  postWarehouseOutbound: { input: { outboundId: number }; output: WarehouseOutbound }
  cancelOtherOutbound: { input: { outboundId: number }; output: WarehouseOutbound }
  reverseOtherOutbound: { input: { outboundId: number; reason: string }; output: WarehouseOutbound }
  stockAdjustments: { input: undefined; output: StockAdjustment[] }
  createStockAdjustment: { input: { warehouse_id: number; reason: string; reference: string; lines: { material_id: number; quantity: string }[] }; output: StockAdjustment }
  submitStockAdjustment: { input: { adjustmentId: number }; output: StockAdjustment }
  approveStockAdjustment: { input: { adjustmentId: number }; output: StockAdjustment }
  rejectStockAdjustment: { input: { adjustmentId: number; reason: string }; output: StockAdjustment }
  cancelStockAdjustment: { input: { adjustmentId: number }; output: StockAdjustment }
  postStockAdjustment: { input: { adjustmentId: number }; output: StockAdjustment }
  reverseStockAdjustment: { input: { adjustmentId: number; reason: string }; output: StockAdjustment }
  createWarehouse: { input: { code: string; name: string }; output: Warehouse }
  receipts: { input: undefined; output: Receipt[] }
  goodsReceipts: { input: undefined; output: GoodsReceipt[] }
  createGoodsReceipt: { input: { purchase_order_id: number; warehouse_id: number; reference: string; lines: { purchase_order_line_id: number; accepted_quantity: string; rejected_quantity: string; rejection_reason: string }[] }; output: GoodsReceipt }
  confirmGoodsReceipt: { input: { goodsReceiptId: number }; output: GoodsReceipt }
  cancelGoodsReceipt: { input: { goodsReceiptId: number }; output: GoodsReceipt }
  createReceipt: {
    input: { supplier_id: number; warehouse_id: number; purchase_order_id: number | null; reference: string; lines: { material_id: number; quantity: string }[] }
    output: Receipt
  }
  postReceipt: { input: { receiptId: number }; output: Receipt }
  reverseReceipt: { input: { receiptId: number; reason: string }; output: Receipt }
  purchaseReturns: { input: undefined; output: PurchaseReturn[] }
  receivablesPayables: { input: undefined; output: ReceivablesPayables }
  financeOverview: { input: undefined; output: FinanceOverview }
  financeAccounts: { input: undefined; output: FinanceAccount[] }
  ledgerAccounts: { input: undefined; output: LedgerAccount[] }
  journals: { input: undefined; output: Journal[] }
  businessJournalSources: { input: undefined; output: BusinessJournalCandidate[] }
  businessJournalOptions: { input: undefined; output: BusinessJournalOptions }
  businessJournalPolicyChanges: { input: undefined; output: FinanceMetadataChange<BusinessJournalPolicy>[] }
  saveBusinessJournalPolicy: { input: BusinessJournalPolicy & { reason: string }; output: BusinessJournalPolicy }
  generateBusinessJournal: { input: BusinessJournalGenerateInput; output: Journal }
  profitTransferOptions: { input: undefined; output: ProfitTransferOptions }
  profitTransferPolicyChanges: { input: undefined; output: FinanceMetadataChange<ProfitTransferPolicy>[] }
  profitTransferPreview: { input: { id: number; paged?: boolean }; output: ProfitTransferPreview }
  saveProfitTransferPolicy: { input: ProfitTransferPolicy & { reason: string }; output: ProfitTransferPolicy }
  generateProfitTransfer: { input: ProfitTransferGenerateInput; output: Journal }
  openingBalances: { input: undefined; output: OpeningBalance[] }
  openingBalanceOptions: { input: undefined; output: { accounts: LedgerAccount[]; period: AccountingPeriod | null } }
  createOpeningBalance: { input: OpeningBalanceInput; output: OpeningBalance }
  updateOpeningBalance: { input: OpeningBalanceInput & { id: number; version: number }; output: OpeningBalance }
  changeOpeningBalanceStatus: { input: { id: number; version: number; action: OpeningBalanceAction; reason: string }; output: OpeningBalance }
  openingBalanceChanges: { input: { id: number }; output: OpeningBalanceChange[] }
  journalDetail: { input: { id: number; paged?: boolean }; output: Journal }
  ledgerReportOptions: { input: undefined; output: LedgerAccount[] }
  queryLedgerReport: { input: LedgerReportQuery; output: LedgerReportResult }
  journalOptions: { input: undefined; output: { accounts: LedgerAccount[]; periods: AccountingPeriod[] } }
  createJournal: { input: JournalInput; output: Journal }
  updateJournal: { input: JournalInput & { id: number; version: number }; output: Journal }
  changeJournalStatus: { input: { id: number; action: JournalAction; version: number; reason: string }; output: Journal }
  reverseJournal: { input: { id: number; version: number; reference: string; journal_date: string; reason: string }; output: Journal }
  journalChanges: { input: { id: number }; output: JournalChange[] }
  createLedgerAccount: { input: LedgerAccountInput; output: LedgerAccount }
  updateLedgerAccount: { input: { id: number; version: number; name: string; is_active: boolean; reason: string }; output: LedgerAccount }
  ledgerAccountChanges: { input: { id: number }; output: FinanceMetadataChange<LedgerAccount>[] }
  accountingPeriods: { input: undefined; output: AccountingPeriod[] }
  createAccountingPeriod: { input: AccountingPeriodInput; output: AccountingPeriod }
  updateAccountingPeriod: { input: { id: number; version: number; name: string; reason: string }; output: AccountingPeriod }
  accountingPeriodChanges: { input: { id: number }; output: FinanceMetadataChange<AccountingPeriod>[] }
  periodClosingCheck: { input: { id: number }; output: PeriodClosingCheck }
  periodClosingHistory: { input: { id: number }; output: PeriodClosingRecord[] }
  changePeriodClosingStatus: { input: { id: number; version: number; action: 'close' | 'reopen'; reason: string }; output: { period: AccountingPeriod; closing_id: number } }
  paymentRecords: { input: undefined; output: PaymentRecord[] }
  createPaymentRecord: { input: { kind: 'receivable' | 'payable'; order_id: number; action: 'settlement' | 'refund'; amount: string; reference: string; note: string }; output: PaymentRecord }
  reversePaymentRecord: { input: { paymentId: number; reason: string }; output: PaymentRecord }
  boms: { input: undefined; output: Bom[] }
  createBom: { input: { product_material_id: number; base_quantity: string; note: string; lines: { component_material_id: number; quantity: string }[] }; output: Bom }
  activateBom: { input: { bomId: number }; output: Bom }
  retireBom: { input: { bomId: number }; output: Bom }
  cancelBom: { input: { bomId: number }; output: Bom }
  workOrders: { input: undefined; output: WorkOrder[] }
  createWorkOrder: { input: { bom_id: number; warehouse_id: number; target_quantity: string; reference: string; note: string }; output: WorkOrder }
  releaseWorkOrder: { input: { orderId: number }; output: WorkOrder }
  cancelWorkOrder: { input: { orderId: number }; output: WorkOrder }
  materialIssues: { input: undefined; output: MaterialIssue[] }
  createMaterialIssue: { input: { work_order_id: number; warehouse_id: number; reference: string; lines: { work_order_line_id: number; quantity: string }[] }; output: MaterialIssue }
  postMaterialIssue: { input: { issueId: number }; output: MaterialIssue }
  cancelMaterialIssue: { input: { issueId: number }; output: MaterialIssue }
  materialReturns: { input: undefined; output: MaterialReturn[] }
  createMaterialReturn: { input: { material_issue_id: number; reason: string; lines: { material_issue_line_id: number; quantity: string }[] }; output: MaterialReturn }
  postMaterialReturn: { input: { returnId: number }; output: MaterialReturn }
  cancelMaterialReturn: { input: { returnId: number }; output: MaterialReturn }
  productionCompletions: { input: undefined; output: ProductionCompletion[] }
  createProductionCompletion: { input: { work_order_id: number; reported_quantity: string; reference: string }; output: ProductionCompletion }
  inspectProductionCompletion: { input: { completionId: number; accepted_quantity: string; qc_note: string }; output: ProductionCompletion }
  postProductionCompletion: { input: { completionId: number }; output: ProductionCompletion }
  cancelProductionCompletion: { input: { completionId: number }; output: ProductionCompletion }
  reverseProductionCompletion: { input: { completionId: number; reason: string }; output: ProductionCompletion }
  productionCosts: { input: undefined; output: ProductionCostReport }
  productionCostSettlements: { input: undefined; output: ProductionCostSettlement[] }
  settleProductionCost: { input: { work_order_id: number; reference: string; note: string }; output: ProductionCostSettlement }
  reverseProductionSettlement: { input: { settlementId: number; reason: string }; output: ProductionCostSettlement }
  recordMaterialValuation: { input: { material_issue_line_id: number; unit_cost: string; reference: string; note: string }; output: ProductionCostEntry }
  recordProductionCharge: { input: { work_order_id: number; kind: 'labor' | 'overhead'; amount: string; reference: string; note: string }; output: ProductionCostEntry }
  reverseProductionCost: { input: { entryId: number; reason: string }; output: ProductionCostEntry }
  createPurchaseReturn: { input: { receipt_id: number; reason: string; lines: { receipt_line_id: number; quantity: string }[] }; output: PurchaseReturn }
  submitPurchaseReturn: { input: { returnId: number }; output: PurchaseReturn }
  postPurchaseReturn: { input: { returnId: number }; output: PurchaseReturn }
  cancelPurchaseReturn: { input: { returnId: number }; output: PurchaseReturn }
  reversePurchaseReturn: { input: { returnId: number; reason: string }; output: PurchaseReturn }
  purchaseOrders: { input: undefined; output: PurchaseOrder[] }
  purchaseRequests: { input: undefined; output: PurchaseRequest[] }
  createPurchaseRequest: { input: { reference: string; note: string; lines: { material_id: number; quantity: string }[] }; output: PurchaseRequest }
  updatePurchaseRequest: { input: { requestId: number; reference: string; note: string; lines: { material_id: number; quantity: string }[] }; output: PurchaseRequest }
  submitPurchaseRequest: { input: { requestId: number }; output: PurchaseRequest }
  approvePurchaseRequest: { input: { requestId: number }; output: PurchaseRequest }
  rejectPurchaseRequest: { input: { requestId: number; reason: string }; output: PurchaseRequest }
  cancelPurchaseRequest: { input: { requestId: number }; output: PurchaseRequest }
  createPurchaseOrder: { input: { supplier_id: number; purchase_request_id?: number; reference: string; lines: { material_id: number; purchase_request_line_id?: number; quantity: string; unit_price: string; tax_rate?: string; discount_rate?: string; includes_tax?: boolean }[] }; output: PurchaseOrder }
  confirmPurchaseOrder: { input: { orderId: number }; output: PurchaseOrder }
  cancelPurchaseOrder: { input: { orderId: number }; output: PurchaseOrder }
  salesOrders: { input: undefined; output: SalesOrder[] }
  createSalesOrder: { input: { customer_id: number; reference: string; lines: { material_id: number; quantity: string; unit_price: string; tax_rate?: string; discount_rate?: string; includes_tax?: boolean }[] }; output: SalesOrder }
  confirmSalesOrder: { input: { orderId: number }; output: SalesOrder }
  cancelSalesOrder: { input: { orderId: number }; output: SalesOrder }
  shipments: { input: undefined; output: Shipment[] }
  createShipment: { input: { sales_order_id: number; warehouse_id: number; reference: string; lines: { material_id: number; quantity: string }[] }; output: Shipment }
  postShipment: { input: { shipmentId: number }; output: Shipment }
  cancelShipment: { input: { shipmentId: number }; output: Shipment }
  reverseShipment: { input: { shipmentId: number; reason: string }; output: Shipment }
  salesReturns: { input: undefined; output: SalesReturn[] }
  createSalesReturn: { input: { shipment_id: number; warehouse_id: number; reason: string; lines: { shipment_line_id: number; quantity: string }[] }; output: SalesReturn }
  postSalesReturn: { input: { returnId: number }; output: SalesReturn }
  cancelSalesReturn: { input: { returnId: number }; output: SalesReturn }
  reverseSalesReturn: { input: { returnId: number; reason: string }; output: SalesReturn }
  transfers: { input: undefined; output: Transfer[] }
  createTransfer: { input: { from_warehouse_id: number; to_warehouse_id: number; reference: string; lines: { material_id: number; quantity: string }[] }; output: Transfer }
  postTransfer: { input: { transferId: number }; output: Transfer }
  reverseTransfer: { input: { transferId: number; reason: string }; output: Transfer }
  stocktakes: { input: undefined; output: Stocktake[] }
  createStocktake: { input: { warehouse_id: number; reference: string; lines: { material_id: number; counted_quantity: string }[] }; output: Stocktake }
  postStocktake: { input: { stocktakeId: number }; output: Stocktake }
  cancelStocktake: { input: { stocktakeId: number }; output: Stocktake }
  reverseStocktake: { input: { stocktakeId: number; reason: string }; output: Stocktake }
  stock: { input: { warehouseId?: number } | undefined; output: Stock[] }
  inventoryValuation: { input: undefined; output: InventoryValuationReport }
  inventoryCostInputs: { input: undefined; output: InventoryCostInput[] }
  recordInventoryCost: { input: { movement_id: number; unit_cost: string;
    reference: string; reason: string }; output: InventoryCostInput }
  movements: { input: undefined; output: Movement[] }
  inventoryLedger: { input: LedgerQuery; output: LedgerResult }
  queryReport: { input: ReportQuery; output: ReportResult }
}
