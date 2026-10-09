// 所有名称、单号及金额均为虚构示例；库存与成本围绕同一款控制板组织。
export const previewRoutes = ['home', 'catalog', 'receipts', 'inventoryLedger', 'productionCosts', 'financeSources', 'journals']
const createdAt = '2026-10-01T08:00:00+00:00'
const material = (id, sku, name, category_code, specification, packageName, part, unit = '个') => ({
  id, sku, name, category_code, specification, package: packageName, brand: '示例品牌',
  manufacturer_part_number: part, unit, electrical_value: '', tolerance: '', rated_voltage: '',
  rated_power: '', temperature_range: '-40℃～85℃', compliance: 'RoHS', notes: '控制板示例用料', version: 1,
})
export const materials = [
  material(1, 'EL-IC-000001', '低功耗微控制器', 'EL-IC', '32 位 · 48 MHz · 64 KB', 'LQFP-48', 'DEMO-MCU48'),
  material(2, 'EL-SR-000001', '贴片电阻', 'EL-SR', '10 kΩ · ±1% · 0.1 W', '0603', 'DEMO-R10K'),
  material(3, 'EL-SC-000001', '陶瓷电容', 'EL-SC', '100 nF · 50 V · X7R', '0603', 'DEMO-C100N'),
  material(4, 'EL-PC-000001', '控制板裸板', 'EL-PC', '双层 · FR-4 · 1.6 mm', '80 × 60 mm', 'DEMO-PCB01'),
  material(5, 'EL-PC-000002', '智能控制板', 'EL-PC', 'DC 24 V · 四路控制', '成品组件', 'DEMO-CTRL01', '块'),
]
export const warehouses = [{ id: 1, name: '电子原料仓', is_active: true }, { id: 2, name: '成品仓', is_active: true }]
const amount = value => ({ amount: value, known_amount: value, unpriced_count: 0, source_line_count: 1 })
const sales = ['1200.00', '1800.00', '1400.00', '2200.00', '1600.00', '2400.00', '2000.00']
const purchase = ['800.00', '1200.00', '900.00', '1400.00', '1000.00', '1500.00', '1200.00']
export const dashboard = {
  period: '7d', from_date: '2026-09-25', to_date: '2026-10-01', previous_from_date: '2026-09-18', previous_to_date: '2026-09-24',
  generated_at: createdAt, currency: 'CNY', time_basis: 'UTC',
  finance: {
    sales: { current: amount('12600.00'), previous: amount('10800.00') },
    purchase: { current: amount('8000.00'), previous: amount('7200.00') },
    trend: sales.map((value, index) => ({ date: index < 6 ? `2026-09-${25 + index}` : '2026-10-01', sales: amount(value), purchase: amount(purchase[index]) })),
    evidence_total: 14, evidence: [],
  },
  sales: { draft: 2, waiting: 3 }, purchase: { draft: 1, waiting: 2 },
  production: { draft: 1, released: 2, awaiting_inspection: 1, awaiting_post: 1 },
  inventory: { positive_positions: 4, stocked_materials: 4, registered_materials: 5, negative_positions: 0 },
  composition: [{ key: 'receipt', label: '采购入库', count: 8 }, { key: 'shipment', label: '销售出库', count: 6 }, { key: 'production_completion', label: '生产完工', count: 3 }, { key: 'transfer', label: '仓库调拨', count: 2 }],
}
const movement = (id, item, quantity, balance, source_type, source_id, warehouse = warehouses[0]) => ({
  id, created_at: createdAt, created_by_name: '示例仓管', warehouse_name: warehouse.name,
  sku: item.sku, material_name: item.name, unit: item.unit, quantity, balance_quantity: balance,
  source_type, source_id, source_line_id: id,
})
export const ledger = {
  rows: [movement(1, materials[0], '200', '200', 'receipt', 101), movement(2, materials[1], '2000', '2000', 'receipt', 101),
    movement(3, materials[2], '1000', '1000', 'receipt', 101), movement(4, materials[0], '-100', '100', 'material_issue', 201),
    movement(5, materials[1], '-1000', '1000', 'material_issue', 201), movement(6, materials[2], '-500', '500', 'material_issue', 201),
    movement(7, materials[4], '100', '100', 'production_completion', 301, warehouses[1])],
  groups: [materials[0], materials[1], materials[2], materials[4]].map((item, index) => ({ warehouse_name: index === 3 ? '成品仓' : '电子原料仓', sku: item.sku, material_name: item.name, unit: item.unit, opening_quantity: '0', closing_quantity: ['100', '1000', '500', '100'][index] })),
}
export const productionCostReport = {
  currency: 'CNY', orders: [
    { work_order_id: 201, product_name: '智能控制板 · 首批 100 块', work_order_status: 'completed', known_material_amount: '2400.00', labor_amount: '600.00', overhead_amount: '300.00', rework_amount: '0.00', rework_source: null, unpriced_rework: false, total_amount: '3300.00', unpriced_issue_count: 0, settlement_id: 401 },
    { work_order_id: 202, product_name: '智能控制板 · 第二批 100 块', work_order_status: 'released', known_material_amount: '2400.00', labor_amount: '300.00', overhead_amount: '150.00', rework_amount: '0.00', rework_source: null, unpriced_rework: false, total_amount: '2850.00', unpriced_issue_count: 0, settlement_id: null },
  ], entries: [], unpriced_lines: [],
  material_sources: materials.slice(0, 3).map((item, index) => ({ work_order_id: 201, material_issue_id: 201, material_issue_line_id: index + 4, movement_id: index + 4, sku: item.sku, material_name: item.name, net_quantity: ['100', '1000', '500'][index], unit_cost: ['20.00', '0.20', '0.40'][index], amount: ['2000.00', '200.00', '200.00'][index], cost_source: 'inventory', cost_entry_id: null })),
}
export const productionCostSettlements = [{
  id: 401, work_order_id: 201, reference: 'DEMO-COST-201', note: '控制板首批完工成本',
  material_amount: '2400.00', labor_amount: '600.00', overhead_amount: '300.00', rework_amount: '0.00', total_amount: '3300.00', accepted_quantity: '100',
  created_by: 2, created_by_name: '示例会计', created_at: createdAt, status: 'active', reversal_id: null,
  allocations: [{ completion_id: 301, movement_id: 7, quantity: '100', amount: '3300.00' }], quality_allocations: [], rework_sources: [],
  material_sources: productionCostReport.material_sources, charges: [],
}]
const journal = (id, reference, status, value, source) => ({
  id, reference, journal_date: '2026-10-01', period_id: 1, period_code: '2026-10', note: '智能控制板示例业务', currency: 'CNY', status, version: 1,
  reversal_of_id: null, reversal_journal_id: null, created_by: 2, created_by_name: '示例会计', created_at: createdAt, author_ids: [2],
  submitted_by: status === 'draft' ? null : 2, reviewed_by: ['approved', 'posted'].includes(status) ? 3 : null, posted_by: status === 'posted' ? 3 : null, cancelled_by: null,
  submitted_at: status === 'draft' ? null : createdAt, reviewed_at: ['approved', 'posted'].includes(status) ? createdAt : null, posted_at: status === 'posted' ? createdAt : null, cancelled_at: null,
  lines: [], total_debit: value, total_credit: value,
  business_source: source ? { key: source, policy_version: 1, mapping: {}, evidence: {
    label: { receipt: '采购入库', production_completion: '生产完工', shipment: '销售出库' }[source.split(':')[0]], source_id: Number(source.split(':')[1]),
  } } : null,
})
export const journals = [journal(501, 'DEMO-RCPT-101', 'posted', '4800.00', 'receipt:101'), journal(502, 'DEMO-PROD-301', 'submitted', '3300.00', 'production_completion:301'), journal(503, 'DEMO-SHIP-601', 'draft', '2000.00', 'shipment:601'), journal(504, 'DEMO-LABOR-201', 'approved', '600.00', null)]

// 三窗轨道也使用正式列表页面；入库、台账和金额来源共享 #101 业务依据。
export const receipts = [{ id: 101, supplier_id: 1, supplier_name: '示例电子供应商', warehouse_id: 1, warehouse_name: '电子原料仓', reference: 'DEMO-RCPT-101', status: 'posted', created_by: 2, created_by_name: '示例采购', created_at: createdAt, posted_at: createdAt, posted_by: 4, purchase_order_id: 101, goods_receipt_id: 101, reversal_id: null, reversal_reason: null, reversed_by: null, reversed_by_name: null, reversed_at: null,
  lines: materials.slice(0, 3).map((item, index) => ({ id: index + 1, material_id: item.id, material_name: item.name, sku: item.sku, unit: item.unit, quantity: ['200', '2000', '1000'][index], unit_price: ['20.00', '0.20', '0.40'][index], returned_quantity: '0', returnable_quantity: ['200', '2000', '1000'][index] })),
}]
export const receivablesPayables = { currency: 'CNY', receivable_amount: '0.00', payable_amount: '4800.00', unpriced_count: 0,
  entries: receipts[0].lines.map((line, index) => ({ key: `receipt:101:${line.id}`, kind: 'payable', source_type: 'receipt', source_id: 101, source_line_id: line.id, material_id: line.material_id, unit_price: line.unit_price, currency: 'CNY', order_id: 101, party_id: 1, party_name: '示例电子供应商', sku: line.sku, quantity: line.quantity, amount: ['4000.00', '400.00', '400.00'][index], posted_at: createdAt, posted_by: 4, posted_by_name: '示例仓管' })),
}

// 仅允许截图需要的读取；任何未配置请求（包括写入）明确失败，不回退正式服务。
// 供需预览只使用虚构数量与来源，不读取正式服务端数据。
export const supplyPreviewInbounds = [{
  id: 901, document_no: 'QTRK-DEMO-000901', reason: 'other', status: 'draft', note: '物料供需界面示例',
  reference: 'SUPPLY-DEMO', warehouse_id: 1, warehouse_name: '电子原料仓', created_by_name: '示例管理员',
  created_at: createdAt, posted_at: null, cancelled_at: null, reversal_id: null,
  approval: {status: 'draft'},
  lines: materials.slice(0, 3).map((row, index) => ({id: 901 + index, material_id: row.id, sku: row.sku,
    material_name: row.name, quantity: '1000.000', unit: row.unit, physical_lots: []}))
}]
export function previewResponse(operation, payload) {
  if (operation === 'materialSupply') {
    const values = ['200.000', '50.000', '700.000', '100.000']
    const phases = ['stock', 'planned', 'awaiting_delivery', 'awaiting_inbound']
    const kinds = ['warehouse', 'purchase_request', 'purchase_order', 'receipt']
    return {scope: 'all_warehouses', generated_at: new Date().toISOString(), rows: payload.material_ids.map(id => {
      const material = materials.find(row => row.id === id)
      if (!material) throw Error('示例物料不存在')
      return {material_id: id, sku: material.sku, name: material.name, unit: material.unit,
        stock_quantity: values[0], planned_quantity: values[1], awaiting_delivery_quantity: values[2], awaiting_inbound_quantity: values[3],
        sources: phases.map((phase, index) => ({phase, kind: kinds[index], document_id: 1 + index,
          document_no: index ? 'DEMO-' + index : null, reference: index ? '示例来源' : '',
          quantity: values[index], warehouse_name: index ? null : '电子原料仓'}))}
    })}
  }
  // 计划页面只提供虚构的采购供给，编排交互仍走正式页面；计算、保存等写入继续拒绝。
  const responses = { dashboard, inventoryLedger: ledger, mrpPlans: [], mrpOptions: {
    materials, warehouses, policies: [], boms: [], demands: [], reservations: [],
    fingerprint: 'sample-only', today: new Date().toISOString().slice(0, 10),
    supplies: materials.slice(0, 3).map(item => ({key: `purchase_order:2:${item.id}`, kind: 'purchase_order',
      source_id: 2, source_line_id: item.id, reference: 'DEMO-2', status: 'confirmed', material_id: item.id, quantity: '700.000', due_date: null}))
  } }
  if (!Object.hasOwn(responses, operation)) throw new Error('截图预览不支持此操作，未连接业务服务。')
  return structuredClone(responses[operation])
}
