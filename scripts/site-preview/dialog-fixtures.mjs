import { materials, warehouses, receipts, supplyPreviewInbounds, previewResponse } from './fixtures.mjs'

// 弹窗验收只开放虚构数据的读取，保存/审批/入库等写入仍由默认分支明确拒绝。
export const dialogPreviewInbounds = [supplyPreviewInbounds[0], { ...structuredClone(supplyPreviewInbounds[0]),
  id: 902, document_no: 'QTRK-DEMO-000902', note: '已批准批次验收示例', approval: {status: 'approved'} }]
export const dialogPreviewPermissions = ['inventory.view', 'other_inbound.view', 'other_inbound.create', 'other_inbound.post']
export function dialogPreviewResponse(operation, payload, store) {
  const reads = { me: store.user, documentNumbering: { configured: true }, permissions: [], menuIcons: [],
    materials, materialCategories: store.materialCategories, materialUnits: [{ id: 1, code: '个', name: '个' }],
    suppliers: store.suppliers, supplierMaterials: store.supplierMaterials, stock: [], receipts, warehouses,
    transfers: [], purchaseOrders: [], stocktakes: [], purchaseReturns: [], otherInbounds: dialogPreviewInbounds }
  if (Object.hasOwn(reads, operation)) return JSON.parse(JSON.stringify(reads[operation]))
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
