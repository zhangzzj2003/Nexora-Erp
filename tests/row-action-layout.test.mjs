import assert from 'node:assert/strict'
import { test } from 'node:test'
import { visibleRowActionCount } from '../src/renderer/src/utils/row-action-layout.ts'

test('审批与取消放得下时直接展示全部按钮，不为更多预留空位', () => {
  assert.equal(visibleRowActionCount([104, 52], 164, 52), 2)
  assert.equal(visibleRowActionCount([104, 52], 200, 52), 2)
  // 不足两个按钮时必须保留菜单入口，不能丢弃取消操作。
  assert.equal(visibleRowActionCount([104, 52], 163, 52), 0)
  assert.equal(visibleRowActionCount([104], 104, 52), 1)
  assert.equal(visibleRowActionCount([104], 80, 52), 0)
})

test('展开数量随实际宽度变化，保留菜单空间且不改变操作优先顺序', () => {
  const widths = [104, 100, 190]
  assert.equal(visibleRowActionCount(widths, 270, 52), 1)
  assert.equal(visibleRowActionCount(widths, 272, 52), 2)
  assert.equal(visibleRowActionCount(widths, 409, 52), 2)
  assert.equal(visibleRowActionCount(widths, 410, 52), 3)
  // 宽度不足、加宽再缩窄都由同一计算恢复，无须保存额外的展开状态。
  assert.equal(visibleRowActionCount(widths, 50, 52), 0)
  assert.equal(visibleRowActionCount(widths, 272, 52), 2)
  assert.equal(visibleRowActionCount([104.25, 51.75], 164, 52), 2)
  assert.deepEqual(widths, [104, 100, 190])
})

test('尚未取得有效尺寸时收进菜单，空操作与异常测量不产生错误展开', () => {
  assert.equal(visibleRowActionCount([], 200, 52), 0)
  for (const width of [NaN, Infinity, -1, 0]) assert.equal(visibleRowActionCount([104], width, 52), 0)
  for (const width of [NaN, Infinity, -1, 0]) assert.equal(visibleRowActionCount([104, width], 300, 52), 0)
  assert.equal(visibleRowActionCount([104], 300, 0), 0)
  assert.equal(visibleRowActionCount([104], 300, 52, -8), 0)
})
