// 协议与界面共用只读示例；两个供应商的采购参考不伪装为实际来源。
export const associationDocument = (id, document_no, status = 'posted') => ({id, document_no, status, reference: '',
  created_at: '2026-10-07 10:00:00', posted_at: status === 'posted' ? '2026-10-07 10:00:00' : null, reversal_reason: null})
export const associationFixture = () => ({target: {kind: 'work_order', id: 1}, scope: 'work_order', inventory_visible: true,
  references_included: false, reference_cutoff: '2026-10-07 10:00:00', reference_limit: 50,
  work_order: {...associationDocument(1, 'WO-20261007-000001', 'completed'), target_quantity: '200', product_name: '测试产品', product_sku: 'PRODUCT'},
  bom: {id: 1, version: 2, base_quantity: '1'},
  components: [{id: 1, material_id: 7, sku: 'R', name: '电阻', unit: '个', required_quantity: '200', net_issued_quantity: '200',
    issues: [{...associationDocument(2, 'MI-20261007-000001'), line_id: 1, quantity: '200', effective: true, returned_quantity: '0',
      returns: [], sources: [], unassigned_quantity: '200'}], purchase_references: []}],
  completions: [{...associationDocument(3, 'CMP-20261007-000001'), reported_quantity: '100', accepted_quantity: '100', rejected_quantity: '0', effective: true}]})
