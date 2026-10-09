import type { AuxiliaryReference, AuxiliarySnapshot, AuxiliarySelectionOptions, Journal, LedgerAccount, SubledgerKind } from './erp-api'
import type { NumberedDocument } from './document-numbering'
import type { DocumentApprovalState } from './document-approval-api'

export type ControlOriginType = 'historical' | 'order'
export type ControlTransferOperation = 'reclassify' | 'allocate'
export type ControlBalanceEvidence =
  | { type: 'journal'; source_key: string; fingerprint: string; journal_id: number; journal_line_id: number; journal_date: string; amount: string }
  | { type: 'opening'; line_id: number; opening_id: number; opening_version: number; date: string; document_reference: string; debit: string; credit: string }
  | { type: 'historical_payment'; payment_id: number; amount: string; date: string; reverses_id: number | null; journal_id?: number; journal_date?: string; fingerprint?: string }
  | { type: 'pending_payment'; payment_id: number; date: string; amount: string }
  | { type: 'historical_settlement' | 'historical_order_settlement'; settlement_id: number; date: string; amount: string }
  | { type: 'order_settlement'; transfer_id: number; executed_at: string; amount: string }
  | { type: 'control_transfer'; transfer_id: number; journal_id: number; date: string; from_delta: string; reverses_id: number | null }
export interface ControlScopeIdentity {
  kind: SubledgerKind; source_type: ControlOriginType; source_id: number; party_id: number
  account_id: number; auxiliary: AuxiliarySnapshot[]
}
export interface ControlScopeGroup extends ControlScopeIdentity {
  party_name: string; reference: string; outstanding_amount: string; fingerprint: string
  evidence: ControlBalanceEvidence[]; blockers: string[]
}
export interface ControlOrigin extends Pick<ControlScopeGroup, 'kind' | 'source_type' | 'source_id' | 'party_id' | 'party_name' | 'reference' | 'outstanding_amount' | 'blockers'> { groups: ControlScopeGroup[] }
export interface ControlScopeChoice {
  source_type: ControlOriginType; source_id: number; account_id: number; auxiliary: AuxiliaryReference[]; fingerprint: string | null
}
export interface FundsScopeChoice { account_id: number; auxiliary: AuxiliaryReference[]; fingerprint: string }
export interface FundsFrozenScope extends ControlScopeIdentity { evidence: ControlBalanceEvidence[] }
export interface ControlFundsQuery { kind: SubledgerKind; source_type: ControlOriginType; source_id: number }
export interface ControlFundsOptions { required: boolean; origin: ControlOrigin | null; currency: 'CNY'; accounts?: Pick<LedgerAccount, 'id' | 'code' | 'name'>[] }
export interface ControlTransferInput {
  kind: SubledgerKind; operation: ControlTransferOperation; business_date: string; from_scope: ControlScopeChoice
  to_scope: ControlScopeChoice; amount: string; reference: string; reason: string
}
export interface ControlBalanceTransfer extends Omit<ControlTransferInput, 'from_scope' | 'to_scope'>, NumberedDocument {
  id: number; party_id: number; from_scope: ControlScopeIdentity; to_scope: ControlScopeIdentity
  evidence: { source: ControlScopeGroup; target: ControlScopeGroup }; currency: 'CNY'; from_delta: string
  reverses_id: number | null; reversal_id: number | null; journal_id: number | null; journal_status: Journal['status'] | null
  status: 'draft' | 'executed' | 'cancelled'; version: number; approval: DocumentApprovalState
  created_by: number; created_by_name: string; created_at: string; executed_by: number | null; executed_at: string | null
  cancelled_by: number | null; cancelled_at: string | null; cancellation_reason: string
}
export interface ControlBalanceOptions extends AuxiliarySelectionOptions { currency: 'CNY'; origins: ControlOrigin[]; accounts: LedgerAccount[]; control_accounts: { kind: 'receivable' | 'payable'; account_id: number }[] }
export interface ControlBalanceReport { to_date: string; currency: 'CNY'; time_basis: 'UTC'; origins: ControlOrigin[] }
export interface ControlTransferCommand { id: number; version: number; reason: string }
export interface ControlTransferChange { id: number; action: 'create' | 'generate' | 'post' | 'cancel'; snapshot: ControlBalanceTransfer; reason: string; changed_by: number; created_at: string }
export interface ControlBalanceOperations {
  controlBalanceTransfers: { input: undefined; output: ControlBalanceTransfer[] }
  controlBalanceOptions: { input: undefined; output: ControlBalanceOptions }
  controlBalanceDetail: { input: { id: number }; output: ControlBalanceTransfer }
  controlBalanceChanges: { input: { id: number }; output: ControlTransferChange[] }
  queryControlBalances: { input: { to_date: string }; output: ControlBalanceReport }
  controlBalanceFundsOptions: { input: ControlFundsQuery; output: ControlFundsOptions }
  createControlBalanceTransfer: { input: ControlTransferInput; output: ControlBalanceTransfer }
  generateControlBalanceJournal: { input: ControlTransferCommand & { reference: string }; output: { transfer: ControlBalanceTransfer; journal: Journal } }
  reverseControlBalanceTransfer: { input: ControlTransferCommand & { reference: string; business_date: string }; output: ControlBalanceTransfer }
  cancelControlBalanceTransfer: { input: ControlTransferCommand; output: ControlBalanceTransfer }
}
