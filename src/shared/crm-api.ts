/** 客户关系、固定报价和审计的受限通信协议。 */
export type CrmKind = 'contact' | 'activity' | 'opportunity' | 'quote'
export type CrmStage = 'prospect' | 'qualified' | 'proposal' | 'negotiation' | 'won' | 'lost'
export type CrmQuoteStatus = 'draft' | 'submitted' | 'approved' | 'rejected' | 'cancelled' | 'converted'
export type CrmQuoteAction = 'submit' | 'approve' | 'reject' | 'cancel'
export interface CrmVersion { version: number; reason: string }
interface CrmBase {
  id: number; customer_id: number; customer_name: string; contact_name: string
  version: number; created_by: number; created_by_name: string; created_at: string
}
export interface CrmContactInput {
  customer_id: number; name: string; job_title: string; phone: string; email: string; note: string; is_active: boolean
}
export interface CrmContact extends CrmBase, Omit<CrmContactInput, 'is_active'> { is_active: number }
export type ContactImportRow = Omit<CrmContactInput, 'is_active'>
export interface ContactImportPreview {
  rows: {
    row: number; customer_id: number; customer_name: string; name: string
    existing_contact_ids: number[]; batch_rows: number[]; requires_confirmation: boolean
  }[]
  requires_confirmation: boolean
}
export interface ContactImportResult {
  batch_reference: string; created: { id: number; customer_id: number; name: string; version: number }[]
}
export interface CrmOpportunityInput {
  customer_id: number; contact_id: number | null; title: string; owner_id: number
  stage: Exclude<CrmStage, 'won'>; estimated_amount: string; probability_percent: number | null; expected_close_date: string; note: string
}
export interface CrmOpportunity extends CrmBase, Omit<CrmOpportunityInput,'stage'> {
  stage: CrmStage; owner_name: string; orders: { quote_id: number; sales_order_id: number; status: string }[]
}
export type OpportunityImportRow = Omit<CrmOpportunityInput, 'stage' | 'probability_percent'>
export interface CrmForecast {
  currency: 'CNY'; rated_count: number; unrated_count: number
  estimated_amount: string; weighted_amount: string
  rows: {id: number; customer_id: number; customer_name: string; title: string; owner_name: string
    stage: Exclude<CrmStage, 'won' | 'lost'>; expected_close_date: string; estimated_amount: string
    probability_percent: number; weighted_amount: string; overdue: boolean}[]
}
export interface OpportunityImportPreview {
  rows: {
    row: number; customer_id: number; customer_name: string; title: string
    owner_id: number; owner_name: string; contact_name: string
    existing_opportunity_ids: number[]; batch_rows: number[]; requires_confirmation: boolean
  }[]
  requires_confirmation: boolean
}
export interface OpportunityImportResult {
  batch_reference: string; created: { id: number; customer_id: number; title: string; version: number }[]
}
export interface CrmActivityInput {
  customer_id: number; contact_id: number | null; opportunity_id: number | null; subject: string
  owner_id: number; due_date: string; note: string
}
export interface CrmActivity extends CrmBase, CrmActivityInput {
  status: 'planned' | 'completed' | 'cancelled'; result: string; owner_name: string
  overdue: boolean; closed_by: number | null; closed_at: string | null
}
export interface CrmQuoteLineInput { material_id: number; quantity: string; unit_price: string }
export interface CrmQuoteInput {
  opportunity_id: number; contact_id: number | null; reference: string; valid_until: string; terms: string; lines: CrmQuoteLineInput[]
}
export interface CrmQuote extends CrmBase, CrmQuoteInput {
  status: CrmQuoteStatus; currency: 'CNY'; total_amount: string; expired: boolean; contact_active: boolean; review_blocked: number[]
  opportunity_title: string; opportunity_version: number; opportunity_stage: CrmStage; sales_order_id: number | null; sales_order_status: string | null
  acceptance_reference: string | null; submitted_by: number | null; reviewed_by: number | null; converted_by: number | null
  submitted_at: string | null; reviewed_at: string | null; converted_at: string | null
  party: { customer_name: string; contact_name: string; phone: string; email: string }
  lines: (CrmQuoteLineInput & { id: number; position: number; quote_id: number; sku: string; material_name: string; unit: string; line_total: string })[]
}
export interface CrmQuoteAttachment {
  id: number; quote_id: number; file_name: string; media_type: 'application/pdf' | 'image/png' | 'image/jpeg'
  byte_count: number; sha256: string; reason: string; created_by: number; created_by_name: string; created_at: string
  reversal: { id: number; reason: string; created_by: number; created_by_name: string; created_at: string } | null
}
export interface CrmQuoteAttachmentList { quote_id: number; can_modify: boolean; items: CrmQuoteAttachment[] }
export type CrmRecord = CrmContact | CrmActivity | CrmOpportunity | CrmQuote
export interface CrmOverview { contacts: CrmContact[]; activities: CrmActivity[]; opportunities: CrmOpportunity[]; quotes: CrmQuote[] }
export interface CrmOptions {
  customers: {id: number; name: string; owner_id: number | null; version: number}[]; materials: {id: number; sku: string; name: string; unit: string}[]
  owners: {id: number; name: string}[]
}
export interface CustomerOwnerChange {
  id: number; customer_id: number; before_owner_id: number | null; after_owner_id: number
  version: number; reason: string; changed_by: number; created_at: string
}
export interface CrmChange {
  id: number; entity_kind: CrmKind; entity_id: number; action: string; reason: string
  changed_by: number; changed_by_name: string; created_at: string
  before: Record<string, unknown> | null; after: Record<string, unknown>
}
export interface CrmForms {
  contact: CrmContactInput; activity: CrmActivityInput; opportunity: CrmOpportunityInput; quote: CrmQuoteInput
}
export interface CrmEditTarget {kind: CrmKind; id: number; version: number; reason: string}
export interface CrmOperations {
  crmOptions: {input: undefined; output: CrmOptions}
  crmOverview: {input: undefined; output: CrmOverview}
  crmForecast: {input: undefined; output: CrmForecast}
  contactImportPreview: {input: {rows: ContactImportRow[]}; output: ContactImportPreview}
  importContacts: {input: {rows: ContactImportRow[]; reason: string; allow_similar: boolean}; output: ContactImportResult}
  opportunityImportPreview: {input: {rows: OpportunityImportRow[]}; output: OpportunityImportPreview}
  importOpportunities: {input: {rows: OpportunityImportRow[]; reason: string; allow_similar: boolean}; output: OpportunityImportResult}
  customerOwnerChanges: {input: {id: number}; output: CustomerOwnerChange[]}
  assignCustomerOwner: {input: {id: number; owner_id: number; version: number; reason: string}; output: CrmOptions['customers'][number]}
  crmDetail: {input: {kind: CrmKind; id: number}; output: CrmRecord}
  crmQuoteAttachments: {input: {id: number}; output: CrmQuoteAttachmentList}
  addCrmQuoteAttachment: {input: {id: number; file_name: string; content_base64: string; reason: string}; output: CrmQuoteAttachment}
  reverseCrmQuoteAttachment: {input: {quoteId: number; attachmentId: number; reason: string}; output: CrmQuoteAttachment}
  crmChanges: {input: {kind: CrmKind; id: number}; output: CrmChange[]}
  saveCrmContact: {input: CrmContactInput & Partial<CrmVersion> & {id?: number}; output: CrmContact}
  saveCrmOpportunity: {input: CrmOpportunityInput & Partial<CrmVersion> & {id?: number}; output: CrmOpportunity}
  createCrmActivity: {input: CrmActivityInput; output: CrmActivity}
  saveCrmQuote: {input: CrmQuoteInput & Partial<CrmVersion> & {id?: number}; output: CrmQuote}
  closeCrmActivity: {input: CrmVersion & {id: number; action: 'complete' | 'cancel'}; output: CrmActivity}
  reopenCrmOpportunity: {input: CrmVersion & {id: number}; output: CrmOpportunity}
  changeCrmQuote: {input: CrmVersion & {id: number; action: CrmQuoteAction}; output: CrmQuote}
  convertCrmQuote: {input: CrmVersion & {id: number; opportunity_version: number; acceptance_reference: string}; output: CrmQuote}
}
