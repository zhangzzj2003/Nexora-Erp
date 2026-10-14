import assert from 'node:assert/strict'
import { test } from 'node:test'
import { computed, effectScope, ref } from 'vue'
import {
  emptyOutboundFilters, filterOutbounds, outboundDateIssue, outboundOperatorOptions,
  outboundWarehouseOptions, outboundGroup, outboundSummary, outboundStatus,
  outboundStatusTone, outboundMaterialTitle,
} from '../src/renderer/src/views/workspace/warehouse/warehouse-outbound-list.ts'
import { useLocalPagination } from '../src/renderer/src/composables/use-local-pagination.ts'

const row = (id, overrides = {}) => ({ id, document_no: `CKD-${id}`, status: 'draft', reason: 'scrap',
  created_by: 1, created_by_name: '同名账号', warehouse_id: 1, warehouse_name: '主仓库',
  created_at: new Date(2026, 9, 14, 12).toISOString(), reference: 'REF-A', note: '报废说明', reversal_id: null,
  lines: [{ id: 1, sku: 'MAT-A', material_name: '电阻', quantity: '100', unit: '个', physical_lots: [] }], ...overrides })

// 采购退货的冲销不写 reversal_id，必须同时核对原退货单的冲销关联。
test('出库概览、状态文案和颜色使用一致终态，已批准未出库仍属未处理', () => {
  const rows = [row(1), row(2, { approval: { status: 'approved' } }), row(3, { status: 'posted' }),
    row(4, { status: 'cancelled', approval: { status: 'approved' } }), row(5, { status: 'posted', reversal_id: 9 }),
    row(6, { status: 'posted', purchase_return_reversal_id: 10 })]
  const original = structuredClone(rows)
  assert.deepEqual(rows.map(outboundGroup), ['pending', 'pending', 'processed', 'cancelled', 'reversed', 'reversed'])
  assert.deepEqual(outboundSummary(rows), { all: 6, pending: 2, processed: 1, cancelled: 1, reversed: 2 })
  assert.deepEqual(rows.map(outboundStatus), ['待送审', '已批准待出库', '已出库', '已取消', '已冲销', '采购退货已冲销'])
  assert.deepEqual(rows.map(outboundStatusTone), ['pending', 'ready', 'success', 'neutral', 'reversed', 'reversed'])
  for (const [status, tone] of [['submitted', 'info'], ['rejected', 'danger'], ['withdrawn', 'neutral']]) {
    assert.equal(outboundStatusTone(row(7, { approval: { status } })), tone)
  }
  assert.deepEqual(rows, original)
  assert.deepEqual(outboundSummary([]), { all: 0, pending: 0, processed: 0, cancelled: 0, reversed: 0 })
})

test('出库列表取关键词、处理人、仓库、来源与状态的交集，支持历史仓库和同名账号', () => {
  const rows = [row(1), row(2, { created_by: 2 }), row(3, { warehouse_id: 2, warehouse_name: '历史仓库' }),
    row(4, { reason: 'sample' }), row(5, { reason: 'purchase_return', status: 'posted', purchase_return_reversal_id: 10 })]
  const select = (filters = {}, query = '', status = 'all') => filterOutbounds(rows, query, { ...emptyOutboundFilters(), ...filters }, status).map(item => item.id)
  assert.deepEqual(select({ operatorId: 2 }), [2])
  assert.deepEqual(select({ warehouseId: 2 }), [3])
  assert.deepEqual(select({ source: 'sample' }), [4])
  assert.deepEqual(select({ source: 'purchase_return' }, '', 'reversed'), [5])
  assert.deepEqual(select({ source: 'purchase_return' }, '', 'processed'), [])
  assert.deepEqual(select({ operatorId: 1, warehouseId: 1, source: 'scrap' }, '  REF-a ', 'pending'), [1])
  for (const query of ['ckd-1', '报废说明', '主仓库', '电阻', 'mat-a']) assert.ok(select({}, query).includes(1))
  assert.deepEqual(select({}, '不存在'), [])
  const operators = outboundOperatorOptions(rows)
  assert.deepEqual(operators.map(item => item.value), [null, 1, 2])
  assert.notEqual(operators[1].label, operators[2].label)
  assert.deepEqual(outboundWarehouseOptions(rows, [{ id: 1, name: '新仓名' }]), [
    { value: null, label: '全部仓库' }, { value: 1, label: '新仓名' }, { value: 2, label: '历史仓库' }])
})

// 首尾日期覆盖全天，并核对无时区协议及倒置日期失败路径。
test('出库日期筛选以本地显示为准，非法范围显示空列表', () => {
  const start = new Date(2026, 9, 14).getTime(), end = new Date(2026, 9, 15).getTime()
  const rows = [start - 1, start, end - 1, end].map((stamp, i) => row(i + 1, { created_at: new Date(stamp).toISOString() }))
  rows.push(row(5, { created_at: new Date(start).toISOString().replace('T', ' ').replace('Z', '') }))
  rows.push(row(6, { created_at: '无效时间' }))
  const select = filters => filterOutbounds(rows, '', { ...emptyOutboundFilters(), ...filters }, 'all').map(item => item.id)
  assert.deepEqual(select({ fromDate: '2026-10-14', toDate: '2026-10-14' }), [2, 3, 5])
  assert.deepEqual(select({ fromDate: '2026-10-14' }), [2, 3, 4, 5])
  assert.deepEqual(select({ toDate: '2026-10-14' }), [1, 2, 3, 5])
  for (const filters of [{ fromDate: '2026-02-29' }, { fromDate: '2026-10-15', toDate: '2026-10-14' }]) {
    assert.ok(outboundDateIssue({ fromDate: '', toDate: '', ...filters }))
    assert.deepEqual(select(filters), [])
  }
})

test('筛选或状态变更回到首页，概览仍统计全部记录，重置不修改单据与草稿', t => {
  const scope = effectScope()
  t.after(() => scope.stop())
  const source = ref(Array.from({ length: 65 }, (_, i) => row(i + 1)))
  const original = structuredClone(source.value.map(item => ({ ...item, lines: [] })))
  const filters = ref(emptyOutboundFilters()), query = ref(''), status = ref('all')
  const summary = computed(() => outboundSummary(source.value))
  const filtered = computed(() => filterOutbounds(source.value, query.value, filters.value, status.value))
  const key = computed(() => JSON.stringify([query.value, status.value, filters.value]))
  const pagination = scope.run(() => useLocalPagination(filtered, key))
  for (const [field, value] of Object.entries({ operatorId: 1, warehouseId: 1, source: 'scrap', fromDate: '2026-10-14', toDate: '2026-10-14' })) {
    pagination.changePage(3, 20)
    filters.value = { ...filters.value, [field]: value }
    assert.equal(pagination.page.value, 1, field)
  }
  pagination.changePage(3, 20)
  status.value = 'processed'
  assert.equal(pagination.page.value, 1)
  assert.equal(pagination.total.value, 0)
  assert.equal(summary.value.all, 65)
  status.value = 'all'; filters.value = emptyOutboundFilters(); query.value = 'CKD-65'
  assert.equal(pagination.total.value, 1)
  assert.equal(summary.value.all, 65)
  query.value = ''
  assert.equal(pagination.total.value, 65)
  assert.deepEqual(source.value.map(item => ({ ...item, lines: [] })), original)
})

test('两行摘要的悬停内容保留普通出库和真实批次来源证据', () => {
  const posted = row(1, { status: 'posted' })
  assert.match(outboundMaterialTitle(posted, posted.lines[0]), /电阻 × 100 个\n普通出库，未指定实物批次/)
  const line = { ...posted.lines[0], physical_lots: [{ code: 'LOT-A', quantity: '100', source_kind: 'receipt' }] }
  assert.match(outboundMaterialTitle(posted, line), /实物批次：LOT-A（100；采购入库）/)
  assert.equal(outboundMaterialTitle(row(2), line), '电阻 × 100 个')
})
