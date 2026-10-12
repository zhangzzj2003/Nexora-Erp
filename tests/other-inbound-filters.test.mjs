import assert from 'node:assert/strict'
import { test } from 'node:test'
import { computed, effectScope, ref } from 'vue'
import { emptyOtherInboundFilters, filterOtherInbounds, otherInboundDateIssue, otherInboundOperatorOptions, otherInboundWarehouseOptions } from '../src/renderer/src/views/workspace/warehouse/other-inbound-filters.ts'
import { otherInboundSummary } from '../src/renderer/src/views/workspace/warehouse/other-inbound-summary.ts'
import { useLocalPagination } from '../src/renderer/src/composables/use-local-pagination.ts'

const row = (id, overrides = {}) => ({ id, document_no: `QTRK-${id}`, created_by: 1, created_by_name: '同名账号', warehouse_id: 1,
  warehouse_name: '主仓库', reason: 'opening', status: 'draft', reversal_id: null, reference: 'REF-A', note: '补录说明',
  created_at: new Date(2026, 9, 9, 12).toISOString(), lines: [{ material_name: '电阻' }], ...overrides })
const rows = [row(1), row(2, { created_by: 2 }), row(3, { warehouse_id: 2, warehouse_name: '历史仓库' }),
  row(4, { reason: 'gift', status: 'posted' }), row(5, { reason: 'other', status: 'cancelled' })]

// 各维度先单独验证，再核对搜索和状态的交集，避免某个字段只渲染却不参与匹配。
test('处理人、仓库、来源、搜索和状态共同筛选，快照保持不变', () => {
  const original = structuredClone(rows)
  const select = (filters = {}, query = '', status = 'all') => filterOtherInbounds(rows, query, { ...emptyOtherInboundFilters(), ...filters }, status).map(item => item.id)
  assert.deepEqual(select(), [1, 2, 3, 4, 5])
  assert.deepEqual(select({ operatorId: 2 }), [2])
  assert.deepEqual(select({ warehouseId: 2 }), [3])
  assert.deepEqual(select({ source: 'gift' }), [4])
  assert.deepEqual(select({ operatorId: 1, warehouseId: 1, source: 'opening' }, '  ref-a ', 'pending'), [1])
  for (const query of ['qtrk-1', '补录说明', '主仓库', '电阻']) assert.ok(select({}, query).includes(1))
  assert.deepEqual(select({ source: 'gift' }, '电阻', 'pending'), [])
  assert.deepEqual(select({ operatorId: 999 }), [])
  assert.deepEqual(select({}, '不存在'), [])
  assert.deepEqual(rows, original)
  assert.deepEqual(otherInboundSummary(rows), { all: 5, pending: 3, processed: 1, cancelled: 1, reversed: 0 })
})

// 午夜和结束日最后一毫秒都参与验证，无时区时间沿用服务端 UTC 协议。
test('日期按本地显示筛选，支持单边范围和当天全天，拦截无效或倒置范围', () => {
  const start = new Date(2026, 9, 9).getTime(), end = new Date(2026, 9, 10).getTime()
  const timed = [start - 1, start, end - 1, end].map((stamp, index) => row(index + 1, { created_at: new Date(stamp).toISOString() }))
  timed.push(row(5, { created_at: new Date(start).toISOString().replace('T', ' ').replace('Z', '') }))
  timed.push(row(6, { created_at: '损坏的时间' }))
  const select = overrides => filterOtherInbounds(timed, '', { ...emptyOtherInboundFilters(), ...overrides }, 'all').map(item => item.id)
  assert.deepEqual(select({ fromDate: '2026-10-09', toDate: '2026-10-09' }), [2, 3, 5])
  assert.deepEqual(select({ fromDate: '2026-10-09' }), [2, 3, 4, 5])
  assert.deepEqual(select({ toDate: '2026-10-09' }), [1, 2, 3, 5])
  assert.deepEqual(select({}), [1, 2, 3, 4, 5, 6])
  for (const overrides of [{ fromDate: '2026-10-10', toDate: '2026-10-09' }, { fromDate: '2026-02-29' }, { toDate: '2026-13-01' }]) {
    assert.notEqual(otherInboundDateIssue({ fromDate: '', toDate: '', ...overrides }), '')
    assert.deepEqual(select(overrides), [])
  }
})

test('完整快照提供同名不同 ID 的处理人和历史仓库选项，不依赖当前筛选', () => {
  const options = otherInboundOperatorOptions(rows)
  assert.deepEqual(options.map(item => item.value), [null, 1, 2])
  assert.notEqual(options[1].label, options[2].label)
  assert.deepEqual(otherInboundWarehouseOptions(rows, [{ id: 1, name: '主仓库新名称' }, { id: 3, name: '新仓库' }]), [
    { value: null, label: '全部仓库' }, { value: 1, label: '主仓库新名称' }, { value: 2, label: '历史仓库' }, { value: 3, label: '新仓库' }])
  assert.deepEqual(otherInboundOperatorOptions([]), [{ value: null, label: '全部处理人' }])
})

test('所有条件变化重置分页，清空条件恢复完整列表并保留原快照', () => {
  const scope = effectScope(), source = ref(Array.from({ length: 65 }, (_, i) => row(i + 1)))
  const filters = ref(emptyOtherInboundFilters()), query = ref(''), status = ref('all')
  const filtered = computed(() => filterOtherInbounds(source.value, query.value, filters.value, status.value))
  const key = computed(() => JSON.stringify([query.value, status.value, filters.value]))
  const pagination = scope.run(() => useLocalPagination(filtered, key))
  try {
    for (const [field, value] of Object.entries({ operatorId: 1, warehouseId: 1, source: 'opening', fromDate: '2026-10-09', toDate: '2026-10-09' })) {
      pagination.changePage(3, 20)
      filters.value = { ...filters.value, [field]: value }
      assert.equal(pagination.page.value, 1, field)
      assert.equal(pagination.total.value, 65)
    }
    filters.value = { ...filters.value, source: 'gift' }
    assert.equal(pagination.total.value, 0)
    filters.value = emptyOtherInboundFilters()
    assert.equal(pagination.total.value, 65)
    assert.equal(source.value.length, 65)
    assert.equal(pagination.page.value, 1)
  } finally { scope.stop() }
})
