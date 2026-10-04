export type AfterSalesKind = 'return' | 'exchange' | 'repair'
export type AfterSalesStatus = 'draft' | 'submitted' | 'approved' | 'rejected' | 'processing' | 'received' | 'repaired' | 'closed' | 'cancelled' | 'reversed'
export type AfterSalesAction = 'submit' | 'approve' | 'reject' | 'process' | 'receive' | 'inspect' | 'close' | 'cancel' | 'reverse'
export interface AfterSalesAttachment {
  id:number; case_id:number; file_name:string; media_type:'application/pdf'|'image/png'|'image/jpeg'
  byte_count:number; sha256:string; reason:string; created_by:number; created_by_name:string; created_at:string
  reversal:{id:number; reason:string; created_by:number; created_by_name:string; created_at:string}|null
}
export interface AfterSalesAttachmentList {case_id:number; can_modify:boolean; items:AfterSalesAttachment[]}
export interface AfterSalesSource {
  shipment_line_id:number; shipment_id:number; sales_order_id:number; customer_id:number; customer_name:string
  material_id:number; sku:string; material_name:string; unit:string; quantity:string; unit_price:string
  posted_at:string; shipment_reference:string; valid:boolean
  replacement?:{material_id:number;sku:string;material_name:string;unit:string;quantity:string;unit_price:string}
}
export interface AfterSalesPart {material_id:number; quantity:string}
export interface AfterSalesInput {
  shipment_line_id:number; reference:string; kind:AfterSalesKind; quantity:string; complaint:string; solution:string
  charge_mode:'none'|'free'|'charge'; fee_amount:string; customer_acceptance:string; warehouse_id:number|null
  warranty_days:number|null; warranty_basis:string
  replacement_material_id:number|null; replacement_quantity:string|null; replacement_unit_price:string|null
  parts:AfterSalesPart[]; reason:string
}
export interface AfterSalesDraft extends Omit<AfterSalesInput,'charge_mode'> {charge_mode:AfterSalesInput['charge_mode']|''}
export interface AfterSalesEvidence extends Omit<AfterSalesInput,'parts'|'reason'> {
  id:number; status:AfterSalesStatus; version:number; created_by:number; created_by_name:string; created_at:string
  submitted_by:number|null; reviewed_by:number|null; closed_by:number|null; reversed_by:number|null
  submitted_at:string|null; reviewed_at:string|null; closed_at:string|null; reversed_at:string|null
  sales_return_id:number|null; replacement_order_id:number|null; parts_outbound_id:number|null
  frozen_source:AfterSalesSource; current_source_valid:boolean; remaining_quantity:string; author_ids:number[]
  warranty_applied_on:string; warranty_expires_on:string|null; warranty_status:'unknown'|'within_period'|'expired'
  return_effective:boolean; parts_status:'draft'|'posted'|'cancelled'|'reversed'|null
  parts:(AfterSalesPart&{sku:string; material_name:string; unit:string})[]
  custody_quantity:string
  custody:{id:number; case_id:number; action:'receive'|'return'; quantity:string; evidence:string; created_by:number; created_by_name:string; created_at:string}[]
  labor_hours:string
  labor:{id:number;case_id:number;action:'record'|'reverse';hours:string;original_id:number|null;
    reason:string;evidence:string;created_by:number;created_by_name:string;created_at:string}[]
  changes:{id:number; action:string; reason:string; evidence:string; changed_by:number; changed_by_name:string; created_at:string;
    before:Record<string,unknown>|null; after:Record<string,unknown>}[]
}
export interface AfterSalesOverview {
  sources:(AfterSalesSource&{remaining_quantity:string})[]; cases:AfterSalesEvidence[]
  materials:{id:number; sku:string; name:string; unit:string}[]; warehouses:{id:number;name:string}[]
}
export interface AfterSalesArchive {
  case: Pick<AfterSalesEvidence, 'id'|'reference'|'kind'|'status'|'quantity'|'charge_mode'|'fee_amount'|'customer_acceptance'|'solution'> &
    Partial<Pick<AfterSalesEvidence, 'warranty_days'|'warranty_basis'|'warranty_applied_on'|'warranty_expires_on'|'warranty_status'>>
  source: AfterSalesSource; custody_quantity:string; labor_hours:string
  custody: AfterSalesEvidence['custody']; labor:AfterSalesEvidence['labor']; changes: AfterSalesEvidence['changes']
}
export interface AfterSalesOperations {
  afterSalesOverview:{input:undefined;output:AfterSalesOverview}
  afterSalesDetail:{input:{id:number};output:AfterSalesEvidence}
  afterSalesAttachments:{input:{id:number};output:AfterSalesAttachmentList}
  addAfterSalesAttachment:{input:{id:number;file_name:string;content_base64:string;reason:string};output:AfterSalesAttachment}
  reverseAfterSalesAttachment:{input:{caseId:number;attachmentId:number;reason:string};output:AfterSalesAttachment}
  saveAfterSalesCase:{input:AfterSalesInput&{id?:number;version?:number};output:AfterSalesEvidence}
  changeAfterSalesCase:{input:{id:number;version:number;action:AfterSalesAction;reason:string;evidence:string;inspection_result?:'pass'|'fail'|null};output:AfterSalesEvidence}
  recordAfterSalesLabor:{input:{id:number;version:number;hours:string;reason:string;evidence:string};output:AfterSalesEvidence}
  reverseAfterSalesLabor:{input:{id:number;version:number;entry_id:number;reason:string;evidence:string};output:AfterSalesEvidence}
}
