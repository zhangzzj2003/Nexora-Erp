import assert from 'node:assert/strict'
import { test } from 'node:test'
import { effectScope, ref } from 'vue'
import { useDocumentMaterialDetails } from '../src/renderer/src/composables/use-document-material-details.ts'

// 用真实响应式草稿覆盖新增、重排、删除及重置，防止资料卡展开到错误的物料。
for (const draft of [
  { material_id: 1, quantity: '3' },
  { material_id: 1, counted_quantity: '0' },
  { component_material_id: 1, quantity: '0.125' }
]) {
  test(`资料收缩兼容 ${Object.keys(draft).join('/')} 且不修改业务字段`, t => {
    const scope = effectScope()
    t.after(() => scope.stop())
    const lines = ref([{ ...draft }])
    const details = scope.run(() => useDocumentMaterialDetails(() => lines.value))
    const first = lines.value[0]
    assert.equal(details.activeLine.value, first)
    lines.value.push({ ...draft })
    const second = lines.value[1]
    assert.equal(details.activeLine.value, second)
    details.setCompact(first, false)
    assert.equal(details.activeLine.value, first)
    lines.value.reverse()
    assert.equal(details.activeLine.value, first)
    details.showLine({ ...draft })
    assert.equal(details.activeLine.value, first, '未知草稿行不能改变当前展开项')
    details.setCompact(first, true)
    assert.equal(details.activeLine.value, null)
    lines.value.push({ ...draft })
    const third = lines.value.at(-1)
    assert.equal(details.activeLine.value, third, '全部收起后新增仍切换到新行')
    lines.value.splice(1, 1)
    assert.equal(details.activeLine.value, third, '删除中间行保留当前行引用')
    lines.value.pop()
    assert.equal(details.activeLine.value, second, '删除展开行后展示剩余行')
    assert.deepEqual(first, draft)
    assert.deepEqual(second, draft)
    lines.value = []
    assert.equal(details.activeLine.value, null)
    lines.value = [{ ...draft }]
    assert.equal(details.activeLine.value, lines.value[0])
    assert.notEqual(details.activeLine.value, first)
  })
}
