import { materials, warehouses, receipts, supplyPreviewInbounds, previewResponse } from './fixtures.mjs'

// 弹窗验收只开放虚构数据的读取，保存/审批/入库等写入仍由默认分支明确拒绝。
export const dialogPreviewInbounds = [supplyPreviewInbounds[0], { ...structuredClone(supplyPreviewInbounds[0]),
  id: 902, document_no: 'QTRK-DEMO-000902', note: '已批准批次验收示例', approval: {status: 'approved'} }]
export const dialogPreviewPermissions = ['inventory.view', 'other_inbound.view', 'other_inbound.create', 'other_inbound.post', 'production.view', 'material_flow.view', 'material_dispatch.create', 'material_dispatch.post']
// 前置生产流程合并后，使用同一只读桥验证它的正文、审批和工单摘要准备链。
export const dialogPreviewWorkOrders = [{ id: 903, document_no: 'SCGD-DEMO-000903', product_name: '智能控制板',
  product_id: 5, warehouse_id: 1, warehouse_name: '电子原料仓', status: 'released', quantity: '60',
  completed_quantity: '0', version: 1, lines: [], approval: { status: 'approved' } }]
const dispatch = { id: 904, document_no: 'SCFL-DEMO-000904', kind: 'dispatch', work_order_id: 903,
  work_order_document_no: 'SCGD-DEMO-000903', product_name: '智能控制板', warehouse_id: 1, warehouse_name: '电子原料仓',
  status: 'draft', version: 1, reference: '动画验收', reason: '完整正文准备示例', note: '', created_by: 3,
  created_by_name: '示例仓管', created_at: '2026-10-01T08:00:00+00:00', source_document_no: null,
  approval: { status: 'approved' }, executions: [], planned_quantity: '60', executed_quantity: '0',
  received_quantity: '0', remaining_quantity: '60', damaged_quantity: '0',
  lines: [{ id: 905, work_order_line_id: 906, material_id: 1, sku: materials[0].sku, material_name: materials[0].name,
    unit: '个', quantity: '60', executed_quantity: '0', received_quantity: '0', remaining_quantity: '60',
    source_receipt_line_id: null, legacy_issue_line_id: null, exchange_line_id: null }] }
const orderFlow = { work_order_id: 903, dispatches: [dispatch], receipts: [], exchanges: [], returns: [], sources: [],
  lines: [{ work_order_line_id: 906, material_id: 1, sku: materials[0].sku, material_name: materials[0].name, unit: '个',
    required_quantity: '100', signed_quantity: '0', returned_quantity: '0', damaged_quantity: '0', in_transit_quantity: '0',
    reserved_quantity: '60', effective_quantity: '0', available_quantity: '0', dispatchable_quantity: '40' }] }
export function dialogPreviewResponse(operation, payload, store) {
  const reads = { me: store.user, documentNumbering: { configured: true }, permissions: [], menuIcons: [],
    materials, materialCategories: store.materialCategories, materialUnits: [{ id: 1, code: '个', name: '个' }],
    suppliers: store.suppliers, supplierMaterials: store.supplierMaterials, stock: [], receipts, warehouses,
    workOrders: dialogPreviewWorkOrders, boms: [], materialIssues: [], materialReturns: [], productionCompletions: [], transfers: [], purchaseOrders: [], stocktakes: [], purchaseReturns: [], otherInbounds: dialogPreviewInbounds }
  if (Object.hasOwn(reads, operation)) return JSON.parse(JSON.stringify(reads[operation]))
  if (operation === 'materialFlowQuery') return { items: payload.kind === 'dispatch' ? [structuredClone(dispatch)] : [],
    total: payload.kind === 'dispatch' ? 1 : 0, page: 1, page_size: 20, summary: { draft: payload.kind === 'dispatch' ? 1 : 0 },
    actors: [{ id: 3, name: '示例仓管' }], warehouses, work_orders: dialogPreviewWorkOrders }
  if (operation === 'materialFlowDetail' && payload.kind === 'dispatch' && payload.id === 904) return structuredClone(dispatch)
  if (operation === 'workOrderMaterialFlow' && payload.orderId === 903) return structuredClone(orderFlow)
  if (operation === 'materialFlowLots') return { lines: [{ line_id: 905, lots: [{ lot_id: 907, code: 'LOT-DEMO-907', quantity: '60' }] }] }
  if (operation === 'documentApproval' && ['MaterialDispatch', 'WorkOrder'].includes(payload.document_type)) {
    return { ...payload, document_no: payload.document_type === 'WorkOrder' ? dialogPreviewWorkOrders[0].document_no : dispatch.document_no,
      business_status: payload.document_type === 'WorkOrder' ? 'released' : 'draft', version: 2, status: 'approved', generation: 1,
      current_step: 1, steps: [{ name: '批准', role: null }], policy_version: 1, submitted_by: 3, submitted_at: dispatch.created_at,
      executed_by: null, executed_at: null, reversal_reason: '', content_matches: true, can_submit: false,
      can_review: false, can_withdraw: false, events: ['submit', 'approve'].map((action, index) => ({ id: index + 1,
        version: index + 1, generation: 1, action, step: 0, step_name: index ? '批准' : null, actor_id: index ? 4 : 3,
        actor_name: index ? '示例审批人' : '示例仓管', reason: '示例审批依据', created_at: dispatch.created_at })), summary: [{ label: '仓库', value: '电子原料仓' },
        { label: '物料', value: '低功耗微控制器 × 60 个' }] }
  }
  if (operation === 'documentApproval') {
    const row = dialogPreviewInbounds.find(item => item.id === payload.document_id)
    if (!row || payload.document_type !== 'WarehouseInbound') throw new Error('验收单据不存在')
    const approved = row.approval.status === 'approved'
    const approval = approved ? { version: 2, status: 'approved', generation: 1, current_step: 1,
      steps: [{name: '批准', role: null}], policy_version: 1, submitted_by: 2, submitted_at: '2026-10-01T08:00:00+00:00',
      can_submit: false, can_withdraw: true, events: ['submit','approve'].map((action,index)=>({id:index+1,
        version:index+1,generation:1,action,step:0,step_name:index?'批准':null,actor_id:index?4:2,
        actor_name:index?'示例审批人':'示例申请人',reason:'示例审批依据',created_at:'2026-10-01T08:00:00+00:00'})) } : {}
    return { ...payload, document_no: row.document_no, business_status: row.status, version: 0, status: 'draft',
      generation: 0, current_step: 0, steps: [], policy_version: null, submitted_by: null, submitted_at: null,
      executed_by: null, executed_at: null, reversal_reason: '', content_matches: true, can_submit: true,
      can_review: false, can_withdraw: false, events: [], ...approval, summary: [{label: '仓库', value: row.warehouse_name},
        {label: '入库说明', value: row.note}, ...row.lines.map(line => ({label: '入库明细', value: `${line.material_name} × ${line.quantity} ${line.unit}`}))] }
  }
  return previewResponse(operation, payload)
}
