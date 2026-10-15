import { materials, warehouses, receipts, supplyPreviewInbounds, previewResponse } from './fixtures.mjs'

// 弹窗验收只开放虚构数据的读取，保存/审批/入库等写入仍由默认分支明确拒绝。
export const dialogPreviewInbounds = [supplyPreviewInbounds[0], { ...structuredClone(supplyPreviewInbounds[0]),
  id: 902, document_no: 'QTRK-DEMO-000902', note: '已批准批次验收示例', approval: {status: 'approved'} }]
export const dialogPreviewPermissions = ['inventory.view', 'other_inbound.view', 'other_inbound.create', 'other_inbound.post', 'production.view', 'production_completion.create', 'material_flow.view', 'material_dispatch.create', 'material_dispatch.post']
// 前置生产流程合并后，使用同一只读桥验证它的正文、审批和工单摘要准备链。
// 示例补齐真实列表必需字段，可验证工单到完工建单的交互；写接口继续由预览桥拒绝。
export const dialogPreviewWorkOrders = [{ id: 903, document_no: 'SCGD-DEMO-000903', product_name: '智能控制板',
  product_material_id: 5, product_sku: 'DEMO-PCB', product_unit: '块', bom_id: 1, bom_version: 1,
  warehouse_id: 1, warehouse_name: '电子原料仓', status: 'in_progress', target_quantity: '100',
  reported_quantity: '40', accepted_quantity: '40', rejected_quantity: '0', remaining_output_quantity: '60',
  created_at: '2026-10-14 02:00:00', created_by: 3, created_by_name: '示例计划员', reference: '生产闭环预览', note: '',
  lines: [{ id: 906, component_material_id: 1, sku: materials[0].sku, material_name: materials[0].name, unit: '个',
    required_quantity: '100', issued_quantity: '58', in_transit_quantity: '2', pending_dispatch_quantity: '40', remaining_quantity: '0', reserved_quantity: '0', damaged_quantity: '0' }],
  approval: { status: 'executed' } }]
export const dialogPreviewCompletions = [{ id: 908, document_no: 'SCWG-DEMO-000908', work_order_id: 903,
  work_order_document_no: 'SCGD-DEMO-000903', product_material_id: 5, product_name: '智能控制板', product_sku: 'DEMO-PCB', product_unit: '块',
  warehouse_id: 1, warehouse_name: '电子原料仓', status: 'posted', reported_quantity: '40', accepted_quantity: '40', rejected_quantity: '0',
  created_at: '2026-10-14 03:00:00', created_by: 3, created_by_name: '示例计划员', inspected_by_name: '示例质检员',
  qc_note: '首批逐件检验合格', reference: '首批报工', physical_lots: [], reversal_id: null, approval: { status: 'executed' } }]
const dispatch = { id: 904, document_no: 'SCFL-DEMO-000904', kind: 'dispatch', work_order_id: 903,
  work_order_document_no: 'SCGD-DEMO-000903', product_name: '智能控制板', warehouse_id: 1, warehouse_name: '电子原料仓',
  status: 'partial', version: 1, reference: '动画验收', reason: '完整正文准备示例', note: '', created_by: 3,
  created_by_name: '示例仓管', created_at: '2026-10-01T08:00:00+00:00', source_document_no: null,
  approval: { status: 'approved' }, executions: [], planned_quantity: '100', executed_quantity: '60',
  received_quantity: '58', remaining_quantity: '40', damaged_quantity: '0',
  lines: [{ id: 905, work_order_line_id: 906, material_id: 1, sku: materials[0].sku, material_name: materials[0].name,
    unit: '个', quantity: '100', executed_quantity: '60', received_quantity: '58', remaining_quantity: '40',
    source_receipt_line_id: null, legacy_issue_line_id: null, exchange_line_id: null }] }
// 工单与交接摘要使用同一组虚构数量，避免预览中出现列表已签收而详情仍为零的矛盾。
const flowReceipt = { ...dispatch, id: 909, kind: 'receipt', document_no: 'SCLL-DEMO-000909',
  source_document_type: 'dispatch', source_document_id: 904, source_document_no: dispatch.document_no,
  planned_quantity: '60', executed_quantity: '58', remaining_quantity: '2', approval: undefined,
  lines: [{ ...dispatch.lines[0], id: 910, quantity: '60', executed_quantity: '58', remaining_quantity: '2' }] }
const orderFlow = { work_order_id: 903, dispatches: [dispatch], receipts: [flowReceipt], exchanges: [], returns: [], sources: [],
  lines: [{ work_order_line_id: 906, material_id: 1, sku: materials[0].sku, material_name: materials[0].name, unit: '个',
    required_quantity: '100', signed_quantity: '58', returned_quantity: '0', damaged_quantity: '0', in_transit_quantity: '2',
    reserved_quantity: '0', effective_quantity: '58', available_quantity: '58', dispatchable_quantity: '0' }] }
export function dialogPreviewResponse(operation, payload, store) {
  const reads = { me: store.user, documentNumbering: { configured: true }, permissions: [], menuIcons: [],
    materials, materialCategories: store.materialCategories, materialUnits: [{ id: 1, code: '个', name: '个' }],
    suppliers: store.suppliers, supplierMaterials: store.supplierMaterials, stock: [], receipts, warehouses,
    workOrders: dialogPreviewWorkOrders, boms: [], materialIssues: [], materialReturns: [], productionCompletions: dialogPreviewCompletions, transfers: [], purchaseOrders: [], stocktakes: [], purchaseReturns: [], otherInbounds: dialogPreviewInbounds }
  if (Object.hasOwn(reads, operation)) return JSON.parse(JSON.stringify(reads[operation]))
  if (operation === 'materialFlowQuery') return { items: payload.kind === 'dispatch' ? [structuredClone(dispatch)] : payload.kind === 'receipt' ? [structuredClone(flowReceipt)] : [],
    total: ['dispatch', 'receipt'].includes(payload.kind) ? 1 : 0, page: 1, page_size: 20, summary: { partial: ['dispatch', 'receipt'].includes(payload.kind) ? 1 : 0 },
    actors: [{ id: 3, name: '示例仓管' }], warehouses, work_orders: dialogPreviewWorkOrders }
  if (operation === 'materialFlowDetail' && payload.kind === 'dispatch' && payload.id === 904) return structuredClone(dispatch)
  if (operation === 'materialFlowDetail' && payload.kind === 'receipt' && payload.id === 909) return structuredClone(flowReceipt)
  if (operation === 'workOrderMaterialFlow' && payload.orderId === 903) return structuredClone(orderFlow)
  if (operation === 'materialFlowLots') return { lines: [{ line_id: 905, lots: [{ lot_id: 907, code: 'LOT-DEMO-907', quantity: '60' }] }] }
  if (operation === 'documentApproval' && ['MaterialDispatch', 'WorkOrder', 'ProductionCompletion'].includes(payload.document_type)) {
    const record = payload.document_type === 'WorkOrder' ? dialogPreviewWorkOrders[0] : payload.document_type === 'ProductionCompletion' ? dialogPreviewCompletions[0] : dispatch
    const executed = record.approval.status === 'executed'
    return { ...payload, document_no: record.document_no,
      business_status: record.status, version: executed ? 3 : 2, status: record.approval.status, generation: 1,
      current_step: 1, steps: [{ name: '批准', role: null }], policy_version: 1, submitted_by: 3, submitted_at: dispatch.created_at,
      executed_by: executed ? 3 : null, executed_at: executed ? record.created_at : null, reversal_reason: '', content_matches: true, can_submit: false,
      can_review: false, can_withdraw: false, events: (executed ? ['submit', 'approve', 'execute'] : ['submit', 'approve']).map((action, index) => ({ id: index + 1,
        version: index + 1, generation: 1, action, step: 0, step_name: index ? '批准' : null, actor_id: index ? 4 : 3,
        actor_name: index ? '示例审批人' : '示例仓管', reason: '示例审批依据', created_at: dispatch.created_at })), summary: [{ label: '仓库', value: '电子原料仓' },
        { label: record.product_name && payload.document_type !== 'MaterialDispatch' ? '产品' : '物料',
          value: payload.document_type === 'MaterialDispatch' ? '低功耗微控制器 × 100 个' : `智能控制板 × ${record.target_quantity ?? record.reported_quantity} 块` }] }
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
