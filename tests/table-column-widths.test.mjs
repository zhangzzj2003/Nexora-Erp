import assert from 'node:assert/strict'
import { test } from 'node:test'
import { clearTableColumnWidths, readTableColumnWidths, resolveTableColumnWidths,
  saveTableColumnWidths, tableColumnWidthKey, validTableColumnWidth } from '../src/renderer/src/utils/table-column-widths.ts'

// 本地设置只记录字段与宽度，不同页面和不同表格不能相互覆盖。
test('列宽键隔离页面、名称和字段，并避免分隔字符造成冲突', () => {
  const key = tableColumnWidthKey('/warehouse', '入库', ['document', 'lines'])
  assert.notEqual(key, tableColumnWidthKey('/purchase', '入库', ['document', 'lines']))
  assert.notEqual(key, tableColumnWidthKey('/warehouse', '出库', ['document', 'lines']))
  assert.notEqual(key, tableColumnWidthKey('/warehouse', '入库', ['document', 'time']))
  assert.notEqual(tableColumnWidthKey('a:b', 'c', ['d']), tableColumnWidthKey('a', 'b:c', ['d']))
})

test('列宽保存、重新读取及恢复默认只影响当前表格', () => {
  const values = new Map([['other-table', '保留其他表格设置']])
  const storage = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) }
  saveTableColumnWidths(storage, 'current', { document: 220, lines: 480 })
  assert.deepEqual(JSON.parse(values.get('current')), { version: 1, widths: { document: 220, lines: 480 } })
  assert.deepEqual(readTableColumnWidths(storage, 'current', ['document', 'lines']), { document: 220, lines: 480 })
  clearTableColumnWidths(storage, 'current')
  assert.deepEqual(readTableColumnWidths(storage, 'current', ['document']), {})
  assert.equal(values.get('other-table'), '保留其他表格设置')
})

test('损坏、未知版本、非法宽度及已删除字段不进入当前布局', () => {
  const read = text => readTableColumnWidths({ getItem: () => text }, 'table', ['name', 'unit'])
  for (const text of [null, '{bad', 'null', '[]', '{"version":2,"widths":{"name":100}}', '{"version":1,"widths":[]}']) assert.deepEqual(read(text), {})
  for (const width of [0, -1, 63, 2401, 100.5, '100', null]) assert.deepEqual(read(JSON.stringify({ version: 1, widths: { name: width } })), {})
  assert.deepEqual(read('{"version":1,"widths":{"name":64,"unit":2400,"oldField":200}}'), { name: 64, unit: 2400 })
  assert.equal(validTableColumnWidth(Infinity), false)
  assert.equal(validTableColumnWidth(NaN), false)
})

test('读取和写入被禁用时安全回退，恢复默认仍可调用', () => {
  const storage = { getItem() { throw Error('blocked') }, setItem() { throw Error('full') }, removeItem() { throw Error('blocked') } }
  assert.deepEqual(readTableColumnWidths(storage, 'table', ['name']), {})
  assert.deepEqual(readTableColumnWidths(undefined, 'table', ['name']), {})
  assert.doesNotThrow(() => saveTableColumnWidths(storage, 'table', { name: 150 }))
  assert.doesNotThrow(() => clearTableColumnWidths(storage, 'table'))
  assert.doesNotThrow(() => saveTableColumnWidths(undefined, 'table', { name: 150 }))
})

test('已调整列使用手动宽度，未调整列继续铺满且不修改原始配置', () => {
  const columns = [{ key: 'document', title: '单据号', width: '200', fixed: 'left' },
    { key: 'lines', title: '明细', width: '310' }, { key: 'actions', title: '操作', width: '160', fixed: 'right' }]
  const before = structuredClone(columns)
  const layout = resolveTableColumnWidths(columns, { document: 180 }, true, 200)
  assert.equal(layout[0].width, 180)
  assert.equal(layout[0].minWidth, undefined)
  assert.equal(layout[1].width, undefined)
  assert.equal(layout[1].minWidth, '310')
  assert.equal(layout[2].fixed, 'right')
  assert.deepEqual(columns, before)
  // 全部调整后优先让中间列分配余量，不能让固定操作列吞掉右侧空白。
  const customized = resolveTableColumnWidths(columns, { document: 180, lines: 280, actions: 150 }, true, 200)
  assert.deepEqual(customized.map(c => c.width), [180, undefined, 150])
  assert.deepEqual(customized.map(c => c.minWidth), [undefined, 280, undefined])
  assert.equal(resolveTableColumnWidths(columns, { document: 180 }, false, 200)[1].width, '310')
  assert.deepEqual(resolveTableColumnWidths([], {}, true, 200), [])
  assert.equal(resolveTableColumnWidths([columns[0]], { document: 180 }, true, 200)[0].minWidth, 180)
})
