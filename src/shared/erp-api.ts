import type { DocumentNumberingOperations, NumberedDocument } from './document-numbering'
import type { DocumentApprovalOperations, DocumentApprovalState } from './document-approval-api'
import type { Supplier, SupplierInput } from './supplier-api'
export type { Supplier, SupplierInput } from './supplier-api'
import type {InventoryWarningOperations} from './inventory-warning-api'
import type {PhysicalLotOperations} from './physical-lot-api'
import type {InboundLotLineInput,ReceiptLotLineInput,ReceiptPhysicalLot} from './receipt-lot-api'
import type {OutboundLotLineInput,OutboundLotOptions} from './outbound-lot-api'
import type {ShipmentLotLineInput,ShipmentLotOptions} from './shipment-lot-api'
import type {MaterialIssueLotLineInput,MaterialIssueLotOptions} from './material-issue-lot-api'
import type {MaterialReturnLotLineInput,MaterialReturnLotOptions} from './material-return-lot-api'
import type {TransferLotLineInput,TransferLotOptions} from './transfer-lot-api'
import type {StocktakeLotLineInput,StocktakeLotOptions} from './stocktake-lot-api'
import type {AdjustmentLotLineInput,AdjustmentLotOptions} from './adjustment-lot-api'
import type {SalesReturnLotLineInput,SalesReturnLotOptions} from './sales-return-lot-api'
import type {CompletionLotPartInput,CompletionPhysicalLot} from './completion-lot-api'
import type { Material, MaterialSummary, MaterialCategory, MaterialInput } from './material-api'
import type { MaterialUnit, MaterialUnitInput, MaterialUnitChange } from './material-unit-api'
export type { Material, MaterialCategory, MaterialInput } from './material-api'
import type { MenuIconKey, MenuIconSetting } from './menu-icons'
import type { MrpOperations } from './mrp-api'
import type { CrmOperations } from './crm-api'
import type { QualityOperations, QualityTreatment, QualityKind, ReworkCostSource } from './quality-api'
import type { AfterSalesOperations } from './after-sales-api'
import type { EquipmentOperations } from './equipment-api'
import type { DashboardOperations } from './dashboard-api'
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
export interface PageResult<T> { items: T[]; total: number; page: number; page_size: number }

export interface SupplierMaterial { supplier_id: number; material_id: number }
export interface Customer { id: number; name: string; owner_id: number | null; version: number }
export interface CustomerDuplicateCandidate {
  id: number; name: string; match: 'same_name' | 'similar_name'
}
export interface CustomerImportPreview {
  rows: {
    row: number; name: string; candidates: CustomerDuplicateCandidate[]
    batch_candidates: number[]; can_import: boolean; requires_confirmation: boolean
  }[]
  can_import: boolean; requires_confirmation: boolean
}
export interface CustomerImportResult {
  batch_reference: string; created: Customer[]
}
export interface Warehouse { id: number; code: string; name: string; version: number }
export interface MasterDataChange<T> {
  id: number; action: 'create' | 'update' | 'delete'; before: T | null; after: T | null
  reason: string; changed_by: number; changed_by_name: string; created_at: string
}
export interface SupplierChange extends MasterDataChange<Supplier> { supplier_id: number }
export interface WarehouseChange extends MasterDataChange<Warehouse> { warehouse_id: number }
export type LedgerCategory = 'asset' | 'liability' | 'equity' | 'income' | 'expense' | 'cost'
export interface LedgerAccount {
  id: number; code: string; name: string; category: LedgerCategory
  normal_balance: 'debit' | 'credit'; is_active: boolean; version: number
  created_by: number; created_at: string
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
  after_sales?: import('./after-sales-api').AfterSalesArchive[]
  subledger?: { opening: SubledgerOpening; rows: SubledgerBalanceRow[] } | null
  period: AccountingPeriod; currency: 'CNY'; time_basis: 'UTC'; opening_balance_id: number | null
  ledger: { rows: Record<string, string>[]; totals: LedgerReportTotals }
  inventory: InventoryValuationReport; business_sources: ReceivablesPayables
  payments: Pick<PaymentRecord, 'id' | 'kind' | 'order_id' | 'action' | 'amount' | 'reference' | 'note' | 'reverses_id' | 'created_by' | 'created_at'>[]; posted_journal_ids: number[]
  profit_transfer?: { required: boolean; residuals: ProfitTransferBalance[]; policy: ProfitTransferPolicy; journal_id: number | null; excluded_cost_accounts?: ProfitTransferExcludedCost[] }
}
export interface PeriodClosingRecord {
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
export type AuxiliaryKind = 'customer' | 'supplier' | 'department' | 'project'
export interface AuxiliaryReference { kind: AuxiliaryKind; id: number }
export interface AuxiliarySnapshot extends AuxiliaryReference { code: string; name: string }
export interface AuxiliaryItem extends AuxiliarySnapshot {
  is_active: boolean; version?: number; created_by?: number; created_at?: string
}
export interface AuxiliaryPolicy {
  account_id: number; start_date: string; required_kinds: AuxiliaryKind[]; version: number
  changed_by?: number; created_at?: string
}
export interface AuxiliarySelectionOptions { auxiliary_items: AuxiliaryItem[]; auxiliary_policies: AuxiliaryPolicy[] }
export interface AuxiliaryOptions extends AuxiliarySelectionOptions {
  kinds: Record<AuxiliaryKind, string>; accounts: LedgerAccount[]; periods: AccountingPeriod[]
}
export interface AuxiliaryItemInput { kind: 'department' | 'project'; code: string; name: string; reason: string }
export interface AuxiliaryItemUpdate { id: number; version: number; name: string; is_active: boolean; reason: string }
export interface AuxiliaryPolicyInput { account_id: number; version: number; start_date: string; required_kinds: AuxiliaryKind[]; reason: string }
export interface AuxiliaryQuery { account_id: number; kind: AuxiliaryKind; from_date: string; to_date: string; entity_id: number | null }
export interface AuxiliaryEntry {
  journal_id: number | null; opening_balance_id: number | null; line_id: number; position: number
  reference: string; date: string; source: string; summary: string; debit: string; credit: string
  auxiliary: AuxiliarySnapshot[]; opening_contribution: boolean; reversal_of_id?: number | null
}
export interface AuxiliaryReport {
  filters: AuxiliaryQuery; account: LedgerAccount; currency: 'CNY'; generated_at: string; csv: string; warnings: string[]
  columns: { key: string; title: string }[]
  rows: { entity_id: number; code: string; name: string; opening_debit: string; opening_credit: string; debit: string; credit: string; closing_debit: string; closing_credit: string; entries: AuxiliaryEntry[] }[]
  totals: { opening_net: string; debit: string; credit: string; closing_net: string }
}
export interface AuxiliaryChange {
  id: number; category: 'item' | 'policy'; target_id: number; before: AuxiliaryItem | AuxiliaryPolicy | null
  after: AuxiliaryItem | AuxiliaryPolicy; reason: string; changed_by: number; changed_by_name: string; created_at: string
}
export interface JournalLineInput { account_id: number; summary: string; debit: string; credit: string; auxiliary?: AuxiliaryReference[] }
export interface JournalInput { reference: string; journal_date: string; note: string; reason: string; lines: JournalLineInput[] }
export interface JournalLine extends JournalLineInput {
  auxiliary?: AuxiliarySnapshot[]
  id: number; journal_id: number; position: number; account_code: string; account_name: string
  category: LedgerCategory; normal_balance: 'debit' | 'credit'
}
export interface Journal extends NumberedDocument {
  // 新服务返回本凭证独立审批；旧响应缺失时客户端不开放过账。
  approval?: DocumentApprovalState
  id: number; reference: string; journal_date: string; period_id: number; period_code: string; note: string
  currency: 'CNY'; status: JournalStatus; version: number; reversal_of_id: number | null; reversal_journal_id: number | null
  created_by: number; created_by_name: string; created_at: string; author_ids: number[]
  submitted_by: number | null; reviewed_by: number | null; posted_by: number | null; cancelled_by: number | null
  submitted_at: string | null; reviewed_at: string | null; posted_at: string | null; cancelled_at: string | null
  lines: JournalLine[]; total_debit: string; total_credit: string
  business_source?: { key: string; evidence: BusinessJournalEvidence; mapping: BusinessJournalMapping; policy_version: number } | null
  profit_transfer?: { period_id: number; evidence: ProfitTransferEvidence; policy: ProfitTransferPolicy } | null
}
export interface JournalAttachment {
  can_reverse?: boolean
  id: number; journal_id: number; file_name: string; media_type: 'application/pdf' | 'image/png' | 'image/jpeg'
  byte_count: number; sha256: string; reason: string; created_by: number; created_by_name: string; created_at: string
  reversal: { id: number; reason: string; created_by: number; created_by_name: string; created_at: string } | null
}
export interface JournalAttachmentList { journal_id: number; can_modify: boolean; items: JournalAttachment[] }
export interface ProfitTransferPolicy {
  version: number; start_date: string; target_account_id: number | null; cost_account_ids: number[]
  changed_by?: number; created_at?: string
}
export interface ProfitTransferBalance {
  auxiliary?: AuxiliarySnapshot[]
  account_id: number; code: string; name: string; category: LedgerCategory; balance: string; debit: string; credit: string
}
export interface ProfitTransferExcludedCost { account_id: number; code: string; name: string; balance: string }
export interface ProfitTransferEvidence {
  period_id: number; start_date: string; end_date: string; policy_version: number; target_account_id: number | null
  cost_account_ids: number[]; fingerprint: string; currency: 'CNY'; time_basis: 'UTC'
  rows: ProfitTransferBalance[]; lines: Pick<JournalLineInput, 'account_id' | 'debit' | 'credit'>[]
  line_auxiliary?: AuxiliarySnapshot[][]
  net_profit: string; blockers: string[]; excluded_cost_accounts: ProfitTransferExcludedCost[]
  target_account: LedgerAccount | null
  sources: { journal_id: number; line_id: number; account_id: number; journal_date: string; reference: string; reversal_of_id: number | null; debit: string; credit: string; auxiliary?: AuxiliarySnapshot[] }[]
  opening_sources: { line_id: number; opening_balance_id: number; account_id: number; debit: string; credit: string; auxiliary?: AuxiliarySnapshot[] }[]
}
export interface ProfitTransferPreview {
  period: AccountingPeriod; policy_version: number; evidence: ProfitTransferEvidence; fingerprint: string
  can_generate: boolean; blockers: string[]; warnings: string[]; journal_id: number | null; journal_status: JournalStatus | null
}
export interface ProfitTransferOptions { policy: ProfitTransferPolicy; accounts: LedgerAccount[]; periods: AccountingPeriod[] }
export interface ProfitTransferGenerateInput {
  period_id: number; period_version: number; policy_version: number; fingerprint: string; reference: string; reason: string
}
export type StatementGroup = 'asset' | 'liability' | 'equity' | 'revenue' | 'expense'
export interface StatementLine { code: string; name: string; group: StatementGroup }
export interface StatementAllocation { account_id: number; line_code: string }
export interface StatementPolicy {
  version: number; lines: StatementLine[]; allocations: StatementAllocation[]; manual_transfer_ids: number[]
}
export interface StatementQuery { from_date: string; to_date: string }
export interface StatementOptions {
  policy: StatementPolicy; accounts: LedgerAccount[]; periods: AccountingPeriod[]; groups: Record<StatementGroup, string>
}
export interface StatementSource {
  auxiliary?: AuxiliarySnapshot[]
  line_id: number; journal_id: number; journal_date: string; reference: string; reversal_of_id: number | null
  account_id: number; debit: string; credit: string; summary: string; line_code: string | null; excluded_from_income: boolean
}
export interface StatementContribution {
  account_id: number; code: string; name: string; line_code: string; group: StatementGroup
  opening: string; closing: string; movement: string
}
export interface StatementReport {
  filters: StatementQuery; policy: StatementPolicy; policy_version: number; fingerprint: string
  balance_rows: (StatementLine & { opening: string; amount: string; account_ids: number[] })[]
  income_rows: (StatementLine & { opening: string; amount: string; account_ids: number[] })[]
  contributions: StatementContribution[]; sources: StatementSource[]
  account_snapshots: LedgerAccount[]
  opening_sources: { id: number; opening_balance_id: number; account_id: number; debit: string; credit: string; line_code: string | null; auxiliary?: AuxiliarySnapshot[] }[]
  opening_balance_id: number | null; periods: AccountingPeriod[]
  pending: { id: number; date: string; status: JournalStatus }[]
  unmapped: { account_id: number; code: string; name: string; opening: string; closing: string; movement: string }[]
  unclassified_transfers: number[]
  totals: Record<'assets' | 'liabilities' | 'equity' | 'unclosed_profit' | 'opening_difference' | 'closing_difference' | 'revenue' | 'expense' | 'net_profit', string>
  can_archive: boolean; blockers: string[]; warnings: string[]; currency: 'CNY'; time_basis: 'UTC'; generated_at: string; csv: string
}
export interface StatementArchiveSummary {
  id: number; from_date: string; to_date: string; policy_version: number; reason: string
  created_by: number; created_by_name: string; created_at: string
}
export interface StatementArchive { id: number; snapshot: StatementReport; reason: string; created_by: number; created_at: string }
export interface StatementArchiveInput extends StatementQuery { policy_version: number; fingerprint: string; reason: string }
export type BusinessJournalRole = 'inventory' | 'payable' | 'receivable' | 'income' | 'sales_cost' | 'cash' | 'price_variance' | 'work_in_progress' | 'labor_accrual' | 'overhead_accrual' | 'inventory_offset'
export type BusinessJournalMapping = Partial<Record<BusinessJournalRole, number>>
export interface BusinessJournalPolicy { version: number; start_date: string; mapping: BusinessJournalMapping; changed_by?: number; created_at?: string }
export interface BusinessJournalEvidence {
  key: string; source_type: string; source_id: number; label: string; source_date: string; fingerprint: string
  roles: Partial<Record<BusinessJournalRole, string>>; blockers: string[]; warnings: string[]
  labels: Record<string, string>
  movements: Pick<InventoryValuationMovement, 'id' | 'warehouse_id' | 'material_id' | 'quantity' | 'source_line_id' | 'created_at' | 'amount' | 'accounting_amount' | 'unit_cost' | 'cost_source' | 'cost_input_id' | 'settlement_id'>[]
  business: Pick<FinancialEntry, 'source_line_id' | 'order_id' | 'party_id' | 'material_id' | 'quantity' | 'unit_price' | 'amount' | 'kind' | 'posted_at'>[]
  records: Record<string, string | number | null>[]
}
export interface BusinessJournalCandidate extends BusinessJournalEvidence {
  auxiliary_defaults?: AuxiliaryReference[]
  policy_version: number; journal_id: number | null; journal_status: JournalStatus | null
  minimum_date: string; can_generate: boolean; no_amount: boolean
}
export interface BusinessJournalOptions extends Partial<AuxiliarySelectionOptions> { policy: BusinessJournalPolicy; roles: Record<BusinessJournalRole, string>; accounts: LedgerAccount[] }
export interface BusinessJournalGenerateInput { source_key: string; fingerprint: string; policy_version: number; reference: string; journal_date: string; reason: string; auxiliary_by_role?: Partial<Record<BusinessJournalRole, AuxiliaryReference[]>> }
export interface JournalChange extends FinanceMetadataChange<Omit<Journal, 'period_code' | 'created_by_name' | 'reversal_journal_id' | 'author_ids'>> { action: JournalAction | 'create' | 'update' | 'withdraw' }
export type OpeningBalanceStatus = 'draft' | 'submitted' | 'approved' | 'rejected' | 'confirmed' | 'cancelled' | 'reversed'
export type OpeningBalanceAction = 'submit' | 'approve' | 'reject' | 'confirm' | 'cancel' | 'reverse'
export interface OpeningBalanceInput { reference: string; effective_date: string; note: string; reason: string; lines: JournalLineInput[] }
export interface OpeningBalance extends Omit<Journal, 'journal_date' | 'status' | 'posted_by' | 'posted_at' | 'reversal_of_id' | 'reversal_journal_id' | 'lines'> {
  effective_date: string; status: OpeningBalanceStatus; active_key: number | null
  reversal_approval?: DocumentApprovalState; reversal_reason?: string
  confirmed_by: number | null; confirmed_at: string | null; reversed_by: number | null; reversed_at: string | null
  lines: (Omit<JournalLine, 'journal_id'> & { opening_balance_id: number })[]
}
export interface OpeningBalanceChange extends FinanceMetadataChange<Omit<OpeningBalance, 'period_code' | 'created_by_name' | 'author_ids'>> { action: OpeningBalanceAction | 'create' | 'update' | 'withdraw' }
export type SubledgerKind = 'receivable' | 'payable'
export interface SubledgerControl { kind: SubledgerKind; account_id: number }
export interface SubledgerLineInput {
  kind: SubledgerKind; account_id: number; party_id: number; document_reference: string; document_date: string
  debit: string; credit: string; auxiliary: AuxiliaryReference[]
}
export interface SubledgerInput {
  reference: string; opening_balance_id: number; opening_version: number; control_accounts: SubledgerControl[]
  lines: SubledgerLineInput[]; note: string; reason: string
}
export interface SubledgerLine extends Omit<SubledgerLineInput, 'auxiliary'> {
  id: number; opening_id: number; position: number; account_code: string; account_name: string
  customer_id: number | null; supplier_id: number | null; auxiliary: AuxiliarySnapshot[]
  party_name: string; opening_amount: string
}
export interface SubledgerReconciliation {
  opening_balance_id: number; opening_version: number; effective_date: string; currency: 'CNY'; matched: boolean
  rows: { account_id: number; auxiliary: AuxiliarySnapshot[]; ledger_amount: string; subledger_amount: string; difference: string }[]
}
export interface SubledgerOpening extends Omit<SubledgerInput, 'reason' | 'lines'>, NumberedDocument {
  approval?: DocumentApprovalState; reversal_approval?: DocumentApprovalState; reversal_reason?: string
  id: number; effective_date: string; status: OpeningBalance['status']; version: number; active_key: number | null
  lines: SubledgerLine[]; evidence: SubledgerReconciliation | null; currency: 'CNY'; author_ids: number[]
  created_by: number; created_by_name: string; created_at: string
  submitted_by: number | null; reviewed_by: number | null; confirmed_by: number | null
  cancelled_by: number | null; reversed_by: number | null; submitted_at: string | null; reviewed_at: string | null
  confirmed_at: string | null; cancelled_at: string | null; reversed_at: string | null
}
export interface SubledgerOptions extends AuxiliarySelectionOptions { accounts: LedgerAccount[]; opening_balance: OpeningBalance | null }
export interface SubledgerChange extends FinanceMetadataChange<Omit<SubledgerOpening, 'created_by_name' | 'author_ids'>> {
  action: OpeningBalanceAction | 'create' | 'update' | 'withdraw'
}
export interface SubledgerPaymentInput { line_id: number; action: 'settlement' | 'refund'; amount: string; reference: string; reason: string }
export interface SubledgerPayment extends NumberedDocument {
  id: number; opening_line_id: number; action: 'settlement' | 'refund' | 'reversal'; amount: string; reference: string; note: string
  reverses_id: number | null; created_by: number; created_by_name: string; created_at: string; currency: 'CNY'
  kind: SubledgerKind; account_id: number; party_id: number; party_name: string; document_reference: string; auxiliary: AuxiliarySnapshot[]
}
export interface SubledgerQuery { to_date: string; kind: SubledgerKind | null; party_id: number | null }
export interface SubledgerBalanceRow extends SubledgerLine { settled_amount: string; outstanding_amount: string; payments: SubledgerPayment[] }
export interface SubledgerReport {
  currency: 'CNY'; time_basis: 'UTC'; to_date: string; rows: SubledgerBalanceRow[]; opening: SubledgerOpening | null
  totals: Record<SubledgerKind, { opening_amount: string; settled_amount: string; outstanding_amount: string }>
  csv: string; generated_at: string
}
export interface LedgerReportQuery {
  kind: 'trial_balance' | 'account_ledger'; from_date: string; to_date: string; account_id: number | null
}
export interface LedgerReportTotals {
  opening_debit: string; opening_credit: string; debit: string; credit: string
  closing_debit: string; closing_credit: string; balanced?: boolean; code?: string; name?: string
}
export interface LedgerReportResult {
  kind: LedgerReportQuery['kind']; filters: LedgerReportQuery
  columns: { key: string; title: string }[]; rows: Record<string, string>[]
  totals: LedgerReportTotals; periods: AccountingPeriod[]; generated_at: string; csv: string
  opening_balance: (OpeningBalance & { changes: OpeningBalanceChange[] }) | null
}
export interface AccountingPeriodInput {
  code: string; name: string; start_date: string; end_date: string; reason: string
}
// 非采购入库沿用单据确认和冲销模式，不进入采购应付来源。
export interface OtherInbound extends NumberedDocument {
  // 审批进度与仓库状态分开，未批准的草稿不能确认入库。
  approval?: DocumentApprovalState
  reversal_approval?: DocumentApprovalState
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
  lines: (ReceiptLine & {physical_lots: ReceiptPhysicalLot[]})[]
}
// 出库确认才扣库存；后续采购退货沿用仓库确认单。
export interface WarehouseOutbound extends NumberedDocument {
  // 执行与冲销各自批准；旧响应缺省时界面关闭执行入口。
  approval?: DocumentApprovalState
  reversal_approval?: DocumentApprovalState
  // 退货出库由采购退货原单冲销，关联 ID 与其他出库冲销分别保存。
  purchase_return_reversal_id?: number | null
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
  lines: (ReceiptLine & {physical_lots: (ReceiptPhysicalLot & {source_kind: string})[]})[]
  purchase_return_id: number | null
}
// 正负调整量在审批前固定，审批人与建单人必须不同。
export interface StockAdjustment extends NumberedDocument {
  // 审批缺省时不能确认；状态由服务端统一审批事务提供。
  approval?: DocumentApprovalState
  reversal_approval?: DocumentApprovalState
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
  lines: (ReceiptLine & {physical_lots: (ReceiptPhysicalLot & {source_kind: string})[]})[]
}
export interface Stock extends MaterialSummary { quantity: string }
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
  materials: (MaterialSummary & { quantity: string; amount: string | null;
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
  physical_lots: ReceiptPhysicalLot[]
}
export interface Receipt extends NumberedDocument {
  reversal_approval?: DocumentApprovalState
  // 缺少服务端审批状态时界面不展示执行按钮，兼容旧响应而不放宽新流程。
  approval?: DocumentApprovalState
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
export interface GoodsReceipt extends NumberedDocument {
  // 缺少服务端审批状态时界面不展示执行按钮，兼容旧响应而不放宽新流程。
  approval?: DocumentApprovalState
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
export interface PurchaseRequest extends NumberedDocument {
  // 审批流程由服务端统一保存，原申请状态继续用于分批转单。
  approval?: DocumentApprovalState
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
export interface PurchaseOrder extends NumberedDocument {
  // 缺少服务端审批状态时界面不展示执行按钮，兼容旧响应而不放宽新流程。
  approval?: DocumentApprovalState
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
export interface PurchaseReturn extends NumberedDocument {
  // 退货转单和下游出库分别审批，进度不包含下游敏感正文。
  approval?: DocumentApprovalState
  outbound_approval?: DocumentApprovalState
  reversal_approval?: DocumentApprovalState
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
  source_type: 'shipment' | 'shipment_reversal' | 'sales_return' | 'sales_return_reversal' | 'receipt' | 'receipt_reversal' | 'purchase_return' | 'purchase_return_reversal' | 'after_sales_repair' | 'after_sales_repair_reversal'
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
  credit_used_amount: string
  debt_covered_amount: string
  outstanding_amount: string
  source_keys: string[]
}
// 原收付款和冲销均为独立、不可编辑的记录，负金额表示退款或反向冲销。
export interface PaymentRecord extends NumberedDocument {
  // 草稿金额不进入余额，审批与业务执行版本分别校验。
  status: 'draft' | 'executed' | 'cancelled'
  version: number
  approval?: DocumentApprovalState
  executed_by: number | null
  executed_at: string | null
  cancelled_by: number | null
  cancelled_at: string | null
  cancellation_reason: string
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
export interface OrderSettlementTransfer extends NumberedDocument {
  id: number
  kind: 'receivable' | 'payable'
  party_id: number
  party_name: string
  from_order_id: number
  to_order_id: number
  amount: string
  reference: string
  reason: string
  reverses_id: number | null
  created_by: number
  created_by_name: string
  created_at: string
  currency: 'CNY'
}
export interface BankAccount { id: number; code: string; name: string; ledger_account_id: number | null; opening_balance: string | null; effective_date: string | null; version: number; created_by: number; created_by_name: string; created_at: string }
export interface BankImportBatch { id: number; account_id: number; file_name: string; sha256: string; row_count: number; created_by: number; created_by_name: string; created_at: string }
export interface BankCsvInput { account_id: number; file_name: string; content_base64: string }
export interface BankCsvPreview { sha256: string; row_count: number; duplicate_file: boolean; existing_transaction_ids: string[]; can_import: boolean; sample: Pick<BankStatementLine, 'transaction_id' | 'occurred_on' | 'amount' | 'counterparty'>[] }
export interface BankStatementLine { id: number; account_id: number; account_code: string; transaction_id: string; occurred_on: string; amount: string; counterparty: string; note: string; import_batch_id: number | null; match_id: number | null; created_by: number; created_by_name: string; created_at: string }
export interface BankPaymentSource { source_type: 'order_payment' | 'subledger_payment'; source_id: number; label: string; kind: 'receivable' | 'payable'; action: string; bank_amount: string; reference: string; created_at: string; match_id: number | null }
export interface BankMatchReversal { id: number; match_id: number; reason: string; created_by: number; created_by_name: string; created_at: string }
export interface BankMatch { id: number; statement_line_id: number; source_type: BankPaymentSource['source_type']; source_id: number; reason: string; created_by: number; created_by_name: string; created_at: string; reversal: BankMatchReversal | null }
export interface BankReconciliationOverview { currency: 'CNY'; accounts: BankAccount[]; imports: BankImportBatch[]; lines: BankStatementLine[]; sources: BankPaymentSource[]; matches: BankMatch[] }
export interface BankBalanceInput { account_id: number; as_of_date: string; declared_bank_closing: string }
export interface BankBalanceItem { id: number; amount: string; occurred_on?: string; transaction_id?: string; counterparty?: string; journal_id?: number; journal_date?: string; reference?: string; summary?: string }
export interface BankOpeningInput { side: 'bank' | 'book'; occurred_on: string; amount: string; reference: string; description: string }
export interface BankOpeningItem extends BankOpeningInput { id: number; account_id: number; created_by: number; created_by_name?: string; created_at: string }
export interface BankOpeningClearance {
  id: number; opening_item_id: number; reason: string; created_by: number; created_by_name: string; created_at: string
  members: { id: number; clearance_id: number; side: 'bank' | 'book'; source_id: number; bank_line_id: number | null; journal_line_id: number | null; amount: string }[]
  reversal: { id: number; clearance_id: number; reason: string; created_by: number; created_by_name: string; created_at: string } | null
}
export interface BankBalancePreview {
  account_id: number; account_code: string; ledger_account_id: number; ledger_code: string
  effective_date: string; as_of_date: string; bank_opening: string; bank_movements: string
  bank_closing_computed: string; bank_closing_declared: string; book_opening: string
  book_movements: string; book_closing: string; bank_unmatched: BankBalanceItem[]
  book_unmatched: BankBalanceItem[]; bank_opening_unmatched: BankOpeningItem[]
  book_opening_unmatched: BankOpeningItem[]; adjusted_bank: string; adjusted_book: string
  bank_statement_balanced: boolean; balanced: boolean; fingerprint: string
  matched_evidence: { group_id: number; bank_line_ids: number[]; journal_line_ids: number[] }[]
  clearance_evidence: { clearance_id: number; opening_item_id: number; source_ids: number[] }[]
}
export interface BankLedgerMatchGroup {
  id: number; account_id: number; amount: string; reason: string; created_by: number
  created_by_name: string; created_at: string
  members: { id: number; group_id: number; side: 'bank' | 'book'; source_id: number; bank_line_id: number | null; journal_line_id: number | null; amount: string }[]
  reversal: { id: number; group_id: number; reason: string; created_by: number; created_at: string } | null
}
export interface BankBalanceReport {
  id: number; account_id: number; as_of_date: string; declared_bank_closing: string
  fingerprint: string; snapshot_json: string; snapshot: BankBalancePreview; reason: string
  created_by: number; created_by_name: string; created_at: string
  status: 'draft' | 'approved' | 'rejected' | 'superseded'; stale: boolean
  decisions: { id: number; report_id: number; action: 'approve' | 'reject' | 'supersede'; reason: string; created_by: number; created_by_name: string; created_at: string }[]
}
export interface BankBalanceOverview {
  accounts: BankAccount[]; ledger_accounts: { id: number; code: string; name: string }[]; opening_effective_date: string | null
  account_changes: { id: number; account_id: number; before_json: string; after_json: string; reason: string; changed_by: number; changed_by_name: string; created_at: string }[]
  opening_items: BankOpeningItem[]; opening_clearances: BankOpeningClearance[]
  matches: BankLedgerMatchGroup[]; reports: BankBalanceReport[]
}
export interface FinanceOverview {
  report: ReceivablesPayables
  accounts: FinanceAccount[]
  payments: PaymentRecord[]
  transfers: OrderSettlementTransfer[]
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
export interface WorkOrder extends NumberedDocument {
  // 本单独立审批；旧响应缺失时界面不允许执行。
  approval?: DocumentApprovalState
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
  rework_disposition_id: number | null
  rework_completion_id: number | null
  rework_reference: string | null
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
  physical_lots: (ReceiptPhysicalLot & {source_kind: string})[]
}
// 确认后的领料单生成独立负向库存流水；原单据保留供追溯。
export interface MaterialIssue extends NumberedDocument {
  // 本单独立审批；旧响应缺失时界面不允许执行。
  approval?: DocumentApprovalState
  reversal_approval?: DocumentApprovalState
  id: number
  work_order_id: number
  warehouse_id: number
  warehouse_name: string
  reference: string
  status: 'draft' | 'posted' | 'cancelled' | 'reversed'
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
  reversed_at: string | null
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
  physical_lots: (ReceiptPhysicalLot & {source_kind: string})[]
}
// 退料引用原领料明细并回到原仓库，确认后生成独立正向流水。
export interface MaterialReturn extends NumberedDocument {
  // 本单独立审批；旧响应缺失时界面不允许执行。
  approval?: DocumentApprovalState
  reversal_approval?: DocumentApprovalState
  id: number
  material_issue_id: number
  work_order_id: number
  warehouse_id: number
  warehouse_name: string
  reason: string
  status: 'draft' | 'posted' | 'cancelled' | 'reversed'
  reversal_id: number | null
  reversal_reason: string | null
  reversed_by: number | null
  reversed_at: string | null
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
export interface ProductionCompletion extends NumberedDocument {
  // 本单独立审批；旧响应缺失时界面不允许执行。
  approval?: DocumentApprovalState
  reversal_approval?: DocumentApprovalState
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
  physical_lots: CompletionPhysicalLot[]
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
  rework_amount: string | null
  rework_source: ReworkCostSource | null
  unpriced_rework: boolean
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
export interface ProductionCostSettlement extends NumberedDocument {
  id: number
  work_order_id: number
  reference: string
  note: string
  material_amount: string
  labor_amount: string
  overhead_amount: string
  rework_amount: string
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
  quality_allocations: {settlement_id:number; disposition_id:number; quantity:string; amount:string; kind:QualityKind;
    loss_treatment:QualityTreatment; reference:string; completion_id:number; rework_order_id:number | null}[]
  rework_sources: {settlement_id:number; disposition_id:number; origin_settlement_id:number; amount:string}[]
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
  unit_price: string
  warranty_days: number | null
  warranty_basis: string
  shipped_quantity: string
  returned_quantity: string
  net_delivered_quantity: string
  remaining_quantity: string
  line_total: string
}
export interface SalesOrder extends NumberedDocument {
  // 服务端返回独立审批进度，旧响应缺失时页面禁止确认。
  approval?: DocumentApprovalState
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
  total_amount: string
}
export interface SalesOrderContractRevision {
  id: number
  sales_order_id: number
  version: number
  body: string
  acceptance_reference: string
  reason: string
  created_by: number
  created_by_name: string
  created_at: string
}
export interface SalesOrderContract {
  sales_order_id: number
  status: SalesOrder['status']
  version: number
  current: SalesOrderContractRevision | null
  history: SalesOrderContractRevision[]
}
export interface SalesOrderContractAttachment {
  id: number
  revision_id: number
  file_name: string
  media_type: 'application/pdf' | 'image/png' | 'image/jpeg'
  byte_count: number
  sha256: string
  reason: string
  created_by: number
  created_by_name: string
  created_at: string
  reversal: { id: number; reason: string; created_by: number; created_by_name: string; created_at: string } | null
}
export interface SalesOrderContractAttachmentList {
  order_id: number
  revision_id: number
  can_modify: boolean
  items: SalesOrderContractAttachment[]
}
export interface Shipment extends NumberedDocument {
  // 服务端返回独立审批进度，旧响应缺失时页面禁止确认。
  approval?: DocumentApprovalState
  reversal_approval?: DocumentApprovalState
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
  physical_lots: (ReceiptPhysicalLot & {source_kind: string})[]
}
// 退货明细固定关联原出库行，金额沿用原销售单价，由服务端计算。
export interface SalesReturnLine extends ReceiptLine {
  shipment_line_id: number
  unit_price: string
  line_total: string
  physical_lots: (ReceiptPhysicalLot & {source_kind: string})[]
}
export interface SalesReturn extends NumberedDocument {
  // 服务端返回独立审批进度，旧响应缺失时页面禁止确认。
  approval?: DocumentApprovalState
  reversal_approval?: DocumentApprovalState
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
  total_amount: string
}
// 调拨单沿用单据的状态与明细结构，同时明确记录两个仓库。
export interface Transfer extends Omit<Receipt, 'supplier_id' | 'supplier_name' | 'warehouse_id' | 'warehouse_name' | 'lines'> {
  from_warehouse_id: number
  from_warehouse_name: string
  to_warehouse_id: number
  to_warehouse_name: string
  reversal_id: number | null
  reversal_reason: string | null
  reversed_by: number | null
  reversed_by_name: string | null
  reversed_at: string | null
  lines: (ReceiptLine & {physical_lots: (ReceiptPhysicalLot & {source_kind: string})[]})[]
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
  physical_lots: (ReceiptPhysicalLot & {source_kind: string})[]
}
export interface Stocktake extends NumberedDocument {
  // 审批缺省时不能确认；状态由服务端统一审批事务提供。
  approval?: DocumentApprovalState
  reversal_approval?: DocumentApprovalState
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
  source_type: 'receipt' | 'receipt_reversal' | 'other_inbound' | 'other_inbound_reversal' | 'other_outbound' | 'other_outbound_reversal' | 'adjustment' | 'adjustment_reversal' | 'transfer_out' | 'transfer_in' | 'transfer_reversal_out' | 'transfer_reversal_in' | 'stocktake' | 'stocktake_reversal' | 'shipment' | 'shipment_reversal' | 'sales_return' | 'sales_return_reversal' | 'purchase_return' | 'purchase_return_reversal' | 'material_issue' | 'material_issue_reversal' | 'material_return' | 'material_return_reversal' | 'production_completion' | 'production_completion_reversal'
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
  material_issue_reversal_id: number | null
  material_return_id: number | null
  material_return_reversal_id: number | null
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
export interface LedgerResult { groups: LedgerGroup[]; rows: LedgerRow[] }
export interface LedgerQuery {
  warehouse_id: number | null
  material_id: number | null
  from_date: string | null
  to_date: string | null
  source_type: string | null
}

export type ReportKind = 'purchase_requests' | 'purchase_orders' | 'receiving_returns' | 'inventory_balance' | 'stock_flow'
export interface ReportQuery {
  kind: ReportKind
  warehouse_id: number | null
  material_id: number | null
  supplier_id: number | null
  from_date: string | null
  to_date: string | null
}
export interface ReportResult {
  kind: ReportKind
  columns: { key: string; title: string }[]
  rows: Record<string, string>[]
  csv: string
}

export interface ErpOperations extends DocumentApprovalOperations, DocumentNumberingOperations, MrpOperations, CrmOperations, QualityOperations, AfterSalesOperations, DashboardOperations, EquipmentOperations, InventoryWarningOperations, PhysicalLotOperations {
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
  updateMaterial: { input: MaterialInput & { id: number; version: number }; output: Material }
  deleteMaterial: { input: { id: number }; output: void }
  supplierDetail: { input: { id: number }; output: Supplier }
  supplierChanges: { input: { id: number }; output: SupplierChange[] }
  recentSupplierChanges: { input: { before_id?: number }; output: SupplierChange[] }
  updateSupplier: { input: SupplierInput & { id: number; version: number; reason: string }; output: Supplier }
  deleteSupplier: { input: { id: number; version: number }; output: void }
  warehouseDetail: { input: { id: number }; output: Warehouse }
  warehouseChanges: { input: { id: number }; output: WarehouseChange[] }
  recentWarehouseChanges: { input: { before_id?: number }; output: WarehouseChange[] }
  updateWarehouse: { input: { id: number; code: string; name: string; version: number; reason: string }; output: Warehouse }
  deleteWarehouse: { input: { id: number; version: number }; output: void }
  supplierMaterials: { input: undefined; output: SupplierMaterial[] }
  bindSupplierMaterial: { input: { supplierId: number; materialId: number }; output: void }
  unbindSupplierMaterial: { input: { supplierId: number; materialId: number }; output: void }
  createSupplier: { input: SupplierInput; output: Supplier }
  customers: { input: undefined; output: Customer[] }
  customerDuplicateCandidates: { input: { name: string }; output: CustomerDuplicateCandidate[] }
  customerImportPreview: { input: { names: string[] }; output: CustomerImportPreview }
  importCustomers: { input: { names: string[]; reason: string; allow_similar: boolean }; output: CustomerImportResult }
  createCustomer: { input: { name: string }; output: Customer }
  materialCategories: { input: undefined; output: MaterialCategory[] }
  materialUnits: { input: undefined; output: MaterialUnit[] }
  materialUnitDetail: { input: { id: number }; output: MaterialUnit }
  createMaterialUnit: { input: MaterialUnitInput; output: MaterialUnit }
  updateMaterialUnit: { input: MaterialUnitInput & { id: number; version: number; reason: string }; output: MaterialUnit }
  materialUnitChanges: { input: { id: number }; output: MaterialUnitChange[] }
  materials: { input: undefined; output: Material[] }
  materialDetail: { input: { id: number; include_suppliers?: boolean }; output: Material }
  createMaterial: { input: MaterialInput; output: Material }
  warehouses: { input: undefined; output: Warehouse[] }
  otherInbounds: { input: undefined; output: OtherInbound[] }
  createOtherInbound: { input: { warehouse_id: number; reason: 'opening' | 'gift' | 'other'; note: string; reference: string; lines: { material_id: number; quantity: string }[] }; output: OtherInbound }
  postOtherInbound: { input: { inboundId: number; lines?: InboundLotLineInput[] }; output: OtherInbound }
  cancelOtherInbound: { input: { inboundId: number }; output: OtherInbound }
  reverseOtherInbound: { input: { inboundId: number; reason: string }; output: OtherInbound }
  warehouseOutbounds: { input: undefined; output: WarehouseOutbound[] }
  createOtherOutbound: { input: { warehouse_id: number; reason: 'scrap' | 'sample' | 'other'; note: string; reference: string; lines: { material_id: number; quantity: string }[] }; output: WarehouseOutbound }
  availableOutboundLots: {input: {outboundId: number}; output: OutboundLotOptions}
  postWarehouseOutbound: { input: { outboundId: number; lines?: OutboundLotLineInput[] }; output: WarehouseOutbound }
  cancelOtherOutbound: { input: { outboundId: number }; output: WarehouseOutbound }
  reverseOtherOutbound: { input: { outboundId: number; reason: string }; output: WarehouseOutbound }
  stockAdjustments: { input: undefined; output: StockAdjustment[] }
  createStockAdjustment: { input: { warehouse_id: number; reason: string; reference: string; lines: { material_id: number; quantity: string }[] }; output: StockAdjustment }
  submitStockAdjustment: { input: { adjustmentId: number }; output: StockAdjustment }
  approveStockAdjustment: { input: { adjustmentId: number }; output: StockAdjustment }
  rejectStockAdjustment: { input: { adjustmentId: number; reason: string }; output: StockAdjustment }
  cancelStockAdjustment: { input: { adjustmentId: number }; output: StockAdjustment }
  availableAdjustmentLots: {input: {adjustmentId: number}; output: AdjustmentLotOptions}
  postStockAdjustment: { input: { adjustmentId: number; lines?: AdjustmentLotLineInput[] }; output: StockAdjustment }
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
  postReceipt: { input: { receiptId: number; lines?: ReceiptLotLineInput[] }; output: Receipt }
  reverseReceipt: { input: { receiptId: number; reason: string }; output: Receipt }
  purchaseReturns: { input: undefined; output: PurchaseReturn[] }
  receivablesPayables: { input: undefined; output: ReceivablesPayables }
  financeOverview: { input: undefined; output: FinanceOverview }
  financeAccounts: { input: undefined; output: FinanceAccount[] }
  ledgerAccounts: { input: undefined; output: LedgerAccount[] }
  journals: { input: undefined; output: Journal[] }
  businessJournalSources: { input: undefined; output: BusinessJournalCandidate[] }
  auxiliaryOptions: { input: undefined; output: AuxiliaryOptions }
  auxiliaryChanges: { input: undefined; output: AuxiliaryChange[] }
  createAuxiliaryItem: { input: AuxiliaryItemInput; output: AuxiliaryItem }
  updateAuxiliaryItem: { input: AuxiliaryItemUpdate; output: AuxiliaryItem }
  saveAuxiliaryPolicy: { input: AuxiliaryPolicyInput; output: AuxiliaryPolicy }
  queryAuxiliary: { input: AuxiliaryQuery; output: AuxiliaryReport }
  businessJournalOptions: { input: undefined; output: BusinessJournalOptions }
  businessJournalPolicyChanges: { input: undefined; output: FinanceMetadataChange<BusinessJournalPolicy>[] }
  saveBusinessJournalPolicy: { input: BusinessJournalPolicy & { reason: string }; output: BusinessJournalPolicy }
  generateBusinessJournal: { input: BusinessJournalGenerateInput; output: Journal }
  profitTransferOptions: { input: undefined; output: ProfitTransferOptions }
  statementOptions: { input: undefined; output: StatementOptions }
  statementPolicyChanges: { input: undefined; output: FinanceMetadataChange<StatementPolicy>[] }
  saveStatementPolicy: { input: StatementPolicy & { reason: string }; output: StatementPolicy }
  queryStatement: { input: StatementQuery; output: StatementReport }
  archiveStatement: { input: StatementArchiveInput; output: StatementArchive }
  statementArchives: { input: undefined; output: StatementArchiveSummary[] }
  statementArchiveDetail: { input: { id: number }; output: StatementArchive }
  profitTransferPolicyChanges: { input: undefined; output: FinanceMetadataChange<ProfitTransferPolicy>[] }
  profitTransferPreview: { input: { id: number }; output: ProfitTransferPreview }
  saveProfitTransferPolicy: { input: ProfitTransferPolicy & { reason: string }; output: ProfitTransferPolicy }
  generateProfitTransfer: { input: ProfitTransferGenerateInput; output: Journal }
  openingBalances: { input: undefined; output: OpeningBalance[] }
  subledgerOpenings: { input: undefined; output: SubledgerOpening[] }
  subledgerOptions: { input: undefined; output: SubledgerOptions }
  subledgerChanges: { input: { id: number }; output: SubledgerChange[] }
  subledgerCheck: { input: { id: number }; output: SubledgerReconciliation }
  createSubledgerOpening: { input: SubledgerInput; output: SubledgerOpening }
  updateSubledgerOpening: { input: SubledgerInput & { id: number; version: number }; output: SubledgerOpening }
  changeSubledgerStatus: { input: { id: number; version: number; action: OpeningBalanceAction; reason: string }; output: SubledgerOpening }
  querySubledger: { input: SubledgerQuery; output: SubledgerReport }
  subledgerPayments: { input: undefined; output: SubledgerPayment[] }
  createSubledgerPayment: { input: SubledgerPaymentInput; output: SubledgerPayment }
  reverseSubledgerPayment: { input: { id: number; reason: string }; output: SubledgerPayment }
  openingBalanceOptions: { input: undefined; output: { accounts: LedgerAccount[]; period: AccountingPeriod | null } & Partial<AuxiliarySelectionOptions> }
  createOpeningBalance: { input: OpeningBalanceInput; output: OpeningBalance }
  updateOpeningBalance: { input: OpeningBalanceInput & { id: number; version: number }; output: OpeningBalance }
  changeOpeningBalanceStatus: { input: { id: number; version: number; action: OpeningBalanceAction; reason: string }; output: OpeningBalance }
  openingBalanceChanges: { input: { id: number }; output: OpeningBalanceChange[] }
  journalDetail: { input: { id: number }; output: Journal }
  ledgerReportOptions: { input: undefined; output: LedgerAccount[] }
  queryLedgerReport: { input: LedgerReportQuery; output: LedgerReportResult }
  journalOptions: { input: undefined; output: { accounts: LedgerAccount[]; periods: AccountingPeriod[] } & Partial<AuxiliarySelectionOptions> }
  createJournal: { input: JournalInput; output: Journal }
  updateJournal: { input: JournalInput & { id: number; version: number }; output: Journal }
  changeJournalStatus: { input: { id: number; action: JournalAction; version: number; reason: string }; output: Journal }
  reverseJournal: { input: { id: number; version: number; reference: string; journal_date: string; reason: string }; output: Journal }
  journalChanges: { input: { id: number }; output: JournalChange[] }
  journalAttachments: { input: { id: number }; output: JournalAttachmentList }
  addJournalAttachment: { input: { id: number; file_name: string; content_base64: string; reason: string }; output: JournalAttachment }
  reverseJournalAttachment: { input: { journalId: number; attachmentId: number; reason: string }; output: JournalAttachment }
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
  orderSettlements: { input: undefined; output: OrderSettlementTransfer[] }
  bankReconciliationOverview: { input: undefined; output: BankReconciliationOverview }
  createBankAccount: { input: { code: string; name: string }; output: BankAccount }
  importBankLines: { input: { account_id: number; lines: { transaction_id: string; occurred_on: string; amount: string; counterparty: string; note: string }[] }; output: { account_id: number; line_ids: number[]; imported_count: number } }
  previewBankCsv: { input: BankCsvInput; output: BankCsvPreview }
  importBankCsv: { input: BankCsvInput; output: { batch_id: number; account_id: number; sha256: string; line_ids: number[]; imported_count: number } }
  matchBankLine: { input: { statement_line_id: number; source_type: BankPaymentSource['source_type']; source_id: number; reason: string }; output: BankMatch }
  reverseBankMatch: { input: { matchId: number; reason: string }; output: BankMatchReversal }
  bankBalanceOverview: { input: undefined; output: BankBalanceOverview }
  bindBankLedgerAccount: { input: { accountId: number; ledger_account_id: number; opening_balance: string; effective_date: string; version: number; reason: string; opening_items: BankOpeningInput[] }; output: BankAccount }
  clearBankOpeningItem: { input: { openingItemId: number; source_ids: number[]; reason: string }; output: Omit<BankOpeningClearance, 'created_by_name' | 'members' | 'reversal'> & { source_ids: number[] } }
  reverseBankOpeningClearance: { input: { clearanceId: number; reason: string }; output: NonNullable<BankOpeningClearance['reversal']> }
  previewBankBalance: { input: BankBalanceInput; output: BankBalancePreview }
  matchBankLedger: { input: { account_id: number; bank_line_ids: number[]; journal_line_ids: number[]; reason: string }; output: { id: number; account_id: number; amount: string; reason: string; created_by: number; created_at: string; bank_line_ids: number[]; journal_line_ids: number[] } }
  reverseBankLedgerMatch: { input: { groupId: number; reason: string }; output: NonNullable<BankLedgerMatchGroup['reversal']> }
  createBankBalanceReport: { input: BankBalanceInput & { reason: string }; output: Omit<BankBalanceReport, 'created_by_name' | 'stale' | 'decisions'> }
  decideBankBalanceReport: { input: { reportId: number; action: 'approve' | 'reject'; reason: string }; output: Omit<BankBalanceReport['decisions'][number], 'created_by_name'> }
  createPaymentRecord: { input: { kind: 'receivable' | 'payable'; order_id: number; action: 'settlement' | 'refund'; amount: string; reference: string; note: string }; output: PaymentRecord }
  reversePaymentRecord: { input: { paymentId: number; reason: string }; output: PaymentRecord }
  changePaymentRecordStatus: { input: { id: number; version: number; action: 'post' | 'cancel'; reason: string }; output: PaymentRecord }
  createOrderSettlement: { input: { kind: 'receivable' | 'payable'; from_order_id: number; to_order_id: number; amount: string; reference: string; reason: string }; output: OrderSettlementTransfer }
  reverseOrderSettlement: { input: { transferId: number; reason: string }; output: OrderSettlementTransfer }
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
  availableMaterialIssueLots: {input: {issueId: number}; output: MaterialIssueLotOptions}
  postMaterialIssue: { input: { issueId: number; lines?: MaterialIssueLotLineInput[] }; output: MaterialIssue }
  cancelMaterialIssue: { input: { issueId: number }; output: MaterialIssue }
  reverseMaterialIssue: { input: { issueId: number; reason: string }; output: MaterialIssue }
  materialReturns: { input: undefined; output: MaterialReturn[] }
  createMaterialReturn: { input: { material_issue_id: number; reason: string; lines: { material_issue_line_id: number; quantity: string }[] }; output: MaterialReturn }
  availableMaterialReturnLots: {input: {returnId: number}; output: MaterialReturnLotOptions}
  postMaterialReturn: { input: { returnId: number; lines?: MaterialReturnLotLineInput[] }; output: MaterialReturn }
  cancelMaterialReturn: { input: { returnId: number }; output: MaterialReturn }
  reverseMaterialReturn: { input: { returnId: number; reason: string }; output: MaterialReturn }
  productionCompletions: { input: undefined; output: ProductionCompletion[] }
  createProductionCompletion: { input: { work_order_id: number; reported_quantity: string; reference: string }; output: ProductionCompletion }
  inspectProductionCompletion: { input: { completionId: number; accepted_quantity: string; qc_note: string }; output: ProductionCompletion }
  postProductionCompletion: { input: { completionId: number; lots?: CompletionLotPartInput[] }; output: ProductionCompletion }
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
  createPurchaseOrder: { input: { supplier_id: number; purchase_request_id?: number; reference: string; lines: { material_id: number; purchase_request_line_id?: number; quantity: string; unit_price: string }[] }; output: PurchaseOrder }
  confirmPurchaseOrder: { input: { orderId: number }; output: PurchaseOrder }
  cancelPurchaseOrder: { input: { orderId: number }; output: PurchaseOrder }
  salesOrders: { input: undefined; output: SalesOrder[] }
  salesOrderContract: { input: { orderId: number }; output: SalesOrderContract }
  reviseSalesOrderContract: { input: { orderId: number; expected_version: number; body: string; acceptance_reference: string; reason: string }; output: SalesOrderContract }
  salesContractAttachments: { input: { orderId: number; revisionId: number }; output: SalesOrderContractAttachmentList }
  addSalesContractAttachment: { input: { orderId: number; revisionId: number; file_name: string; content_base64: string; reason: string }; output: SalesOrderContractAttachment }
  reverseSalesContractAttachment: { input: { orderId: number; revisionId: number; attachmentId: number; reason: string }; output: SalesOrderContractAttachment }
  createSalesOrder: { input: { customer_id: number; reference: string; lines: { material_id: number; quantity: string; unit_price: string; warranty_days: number | null; warranty_basis: string }[] }; output: SalesOrder }
  confirmSalesOrder: { input: { orderId: number }; output: SalesOrder }
  cancelSalesOrder: { input: { orderId: number }; output: SalesOrder }
  shipments: { input: undefined; output: Shipment[] }
  availableShipmentLots: { input: {shipmentId: number}; output: ShipmentLotOptions }
  createShipment: { input: { sales_order_id: number; warehouse_id: number; reference: string; lines: { material_id: number; quantity: string }[] }; output: Shipment }
  postShipment: { input: { shipmentId: number; lines?: ShipmentLotLineInput[] }; output: Shipment }
  cancelShipment: { input: { shipmentId: number }; output: Shipment }
  reverseShipment: { input: { shipmentId: number; reason: string }; output: Shipment }
  salesReturns: { input: undefined; output: SalesReturn[] }
  createSalesReturn: { input: { shipment_id: number; warehouse_id: number; reason: string; lines: { shipment_line_id: number; quantity: string }[] }; output: SalesReturn }
  availableSalesReturnLots: { input: { returnId: number }; output: SalesReturnLotOptions }
  postSalesReturn: { input: { returnId: number; lines?: SalesReturnLotLineInput[] }; output: SalesReturn }
  cancelSalesReturn: { input: { returnId: number }; output: SalesReturn }
  reverseSalesReturn: { input: { returnId: number; reason: string }; output: SalesReturn }
  transfers: { input: undefined; output: Transfer[] }
  createTransfer: { input: { from_warehouse_id: number; to_warehouse_id: number; reference: string; lines: { material_id: number; quantity: string }[] }; output: Transfer }
  availableTransferLots: {input: {transferId: number}; output: TransferLotOptions}
  postTransfer: { input: { transferId: number; lines?: TransferLotLineInput[] }; output: Transfer }
  reverseTransfer: { input: { transferId: number; reason: string }; output: Transfer }
  stocktakes: { input: undefined; output: Stocktake[] }
  createStocktake: { input: { warehouse_id: number; reference: string; lines: { material_id: number; counted_quantity: string }[] }; output: Stocktake }
  availableStocktakeLots: {input: {stocktakeId: number}; output: StocktakeLotOptions}
  postStocktake: { input: { stocktakeId: number; lines?: StocktakeLotLineInput[] }; output: Stocktake }
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
