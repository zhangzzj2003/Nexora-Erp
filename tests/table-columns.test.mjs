import assert from 'node:assert/strict'
import { test } from 'node:test'
import { resolveTableColumns } from '../src/renderer/src/utils/table-columns.ts'

// 业务列顺序和原对象保持不变，只有单据列表按约定启用两端固定。
test('单据与操作固定两端，中间列滚动且不修改页面配置', () => {
  const columns = [{ key: 'document', title: '单号', width: '230' }, { key: 'time', title: '时间' }, { key: 'actions', title: '操作' }]
  const before = structuredClone(columns)
  const result = resolveTableColumns(columns)
  assert.deepEqual(result.map(column => column.fixed), ['left', false, 'right'])
  assert.deepEqual(result.map(column => column.key), columns.map(column => column.key))
  assert.equal(result[0].width, '230')
  assert.deepEqual(columns, before)
})

test('明细表不误启用，支持显式固定与取消默认固定', () => {
  assert.deepEqual(resolveTableColumns([]), [])
  const details = [{ key: 'material', title: '物料' }, { key: 'actions', title: '移除' }]
  assert.deepEqual(resolveTableColumns(details).map(column => column.fixed), [false, false])
  assert.deepEqual(resolveTableColumns([
    { key: 'document', title: '单号', fixed: false },
    { key: 'custom', title: '自定义', fixed: 'left' },
    { key: 'actions', title: '操作', fixed: 'right' }
  ]).map(column => column.fixed), [false, 'left', 'right'])
})
