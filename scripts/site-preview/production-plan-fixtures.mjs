import { planFixture, planOptionsFixture, planApproval } from '../../tests/production-plan-fixture.mjs'

// 仅在 qa=productionPlans 的回环预览启用；操作只改变本页面内存样例。
const records = [planFixture(), { ...planFixture(), id: 2, document_no: 'SCJH-20261019-000002',
  reference: '十一月补货安排', approval: planApproval('draft'), can_edit: true,
  lines: planFixture().lines.map(line => ({ ...line, id: 2, plan_id: 2 })) }]
const options = planOptionsFixture()
options.sales_lines = [{ id: 10, sales_order_id: 10, sales_order_document_no: 'XS-20261019-000010', reference: '客户交付批次',
  material_id: 1, quantity: '200.000', remaining_quantity: '200.000', available_quantity: '200.000' }]
export const productionPlanPreviewOperations = ['productionPlans', 'productionPlanOptions', 'productionPlanDetail',
  'createProductionPlan', 'updateProductionPlan', 'releaseProductionPlan', 'cancelProductionPlan']
export const productionPlanPreviewPermissions = ['production_plan.view', 'production_plan.create', 'production_plan.submit',
  'production_plan.review', 'production_plan.verify', 'production_plan.approve', 'production_plan.release', 'production_plan.cancel', 'work_order.create']
export function productionPlanPreviewResponse(operation, payload) {
  if (operation === 'productionPlans') return structuredClone(records)
  if (operation === 'productionPlanOptions') return structuredClone(options)
  if (operation === 'createProductionPlan') {
    const id = records.length + 1, sample = planFixture()
    const row = { ...sample, ...payload, id, document_no: `SCJH-20261019-${String(id).padStart(6, '0')}`, approval: planApproval('draft'), can_edit: true,
      line_count: payload.lines.length, lines: payload.lines.map((line, index) => ({ ...sample.lines[0], ...line,
        id: id * 100 + index, plan_id: id, remaining_quantity: line.quantity, unreleased_quantity: line.quantity })) }
    records.unshift(row)
    return structuredClone(row)
  }
  const row = records.find(row => row.id === (payload?.id ?? payload?.document_id))
  if (!row) throw Error('此隔离样例没有对应生产计划')
  if (operation === 'productionPlanDetail') return structuredClone(row)
  if (operation === 'documentApproval') return { ...payload, ...row.approval, document_no: row.document_no,
    business_status: row.status, content_matches: true, reversal_reason: '', can_submit: false, can_review: false, can_withdraw: false,
    events: ['submit', 'approve'].map((action, index) => ({ id: index + 1, version: index + 1, generation: 1,
      action, step: 0, step_name: index ? '批准' : null, actor_id: index + 1, actor_name: index ? '示例审批人' : '示例计划员',
      reason: '示例计划审批依据', created_at: row.created_at })),
    summary: [{ label: '计划名称', value: row.reference }, ...row.lines.map(line => ({ label: line.name,
      value: `${line.quantity} ${line.unit}；${line.start_date} 至 ${line.end_date}；${line.warehouse_name}` }))] }
  if (operation === 'releaseProductionPlan') {
    const line = row.lines.find(line => line.id === payload.line_id)
    line.released_quantity = (Number(line.released_quantity) + Number(payload.quantity)).toFixed(3)
    line.unreleased_quantity = (Number(line.quantity) - Number(line.released_quantity)).toFixed(3)
    row.version++; row.approval = planApproval('executed'); row.progress = 'released'
    row.releases.push({ id: row.releases.length + 1, plan_id: row.id, line_id: line.id,
      work_order_id: 100 + row.releases.length, work_order_document_no: 'GD-20261019-000100', work_order_status: 'draft',
      quantity: payload.quantity, reason: payload.reason, created_by: 3, created_at: row.created_at })
    return structuredClone(row)
  }
  if (operation === 'cancelProductionPlan') { row.status = 'cancelled'; row.version++; return structuredClone(row) }
  throw Error('此取景样例不提供该写入操作')
}
