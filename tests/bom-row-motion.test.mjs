import assert from 'node:assert/strict'
import { test } from 'node:test'
import { retainLeavingBomRows } from '../src/renderer/src/views/workspace/catalog/bom-row-motion.ts'

const rows = keys => keys.map(key => ({ key }))
// 相同物料在不同分支按路径隔离，离场不得被挪到其他父项下面。
test('收起保留原位置，快速换分支同时接纳新行且不修改输入', () => {
  const before = rows(['1/a','1/a/x','1/a/x/z','1/b','1/c'])
  const next = rows(['1/a','1/b','1/b/x','1/c'])
  const result = retainLeavingBomRows(before,next)
  assert.deepEqual(result.map(row=>row.key),['1/a','1/a/x','1/a/x/z','1/b','1/b/x','1/c'])
  assert.equal(result[0],next[0])
  assert.equal(result[1],before[1])
  assert.equal(before.length,5)
  assert.equal(next.length,4)
})
test('快速重新展开更新原行，保留深层收起行但不重复分支', () => {
  const before = rows(['1/a','1/a/x','1/a/x/z','1/b'])
  const next = rows(['1/a','1/a/x','1/b'])
  const result = retainLeavingBomRows(before,next)
  assert.deepEqual(result.map(row=>row.key),before.map(row=>row.key))
  assert.equal(result[1],next[1])
  assert.equal(retainLeavingBomRows([],next).length,3)
  assert.deepEqual(retainLeavingBomRows(before,[]),before)
})
