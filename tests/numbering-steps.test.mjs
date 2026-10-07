import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ref } from 'vue'
import { useNumberingSteps } from '../src/renderer/src/composables/use-numbering-steps.ts'

// 执行表单真正使用的步骤控制器，验证回车、重试和禁用边界不会提前写入服务端。
test('首次设置前两步只切换，确认页才保存；返回和重试保留草稿', async () => {
  const disabled = ref(false), valid = ref(true)
  const draft = { style: 'english', timezone: 'America/New_York' }
  const requests = []
  let fail = true
  const flow = useNumberingSteps(true, disabled, valid, async () => {
    requests.push({ ...draft })
    if (fail) throw new Error('保存失败')
  })
  await flow.submit(); await flow.submit()
  assert.equal(flow.step.value, 2); assert.equal(requests.length, 0)
  await assert.rejects(flow.submit(), /保存失败/)
  assert.equal(flow.step.value, 2); assert.deepEqual(requests[0], draft)
  flow.back(0); assert.equal(flow.step.value, 0); assert.equal(flow.direction.value, 'back')
  await flow.submit(); await flow.submit(); fail = false; await flow.submit()
  assert.deepEqual(requests, [draft, draft])
})

test('无效时区不能进入确认页，忙碌或断线不能前进、返回或保存', async () => {
  const disabled = ref(false), valid = ref(false)
  let saved = 0
  const flow = useNumberingSteps(true, disabled, valid, async () => { saved++ })
  await flow.submit(); assert.equal(flow.step.value, 1)
  assert.equal(flow.canContinue.value, false); await flow.submit()
  assert.equal(flow.step.value, 1)
  for (const target of [2, 10, -1, 0.5]) flow.back(target)
  assert.equal(flow.step.value, 1)
  valid.value = true; disabled.value = true
  flow.back(); await flow.submit(); assert.equal(flow.step.value, 1); assert.equal(saved, 0)
  disabled.value = false; await flow.submit(); assert.equal(flow.step.value, 2)
  valid.value = false; await flow.submit(); assert.equal(saved, 0)
})

test('常规设置直接保存，不进入首次引导；锁定状态拒绝保存', async () => {
  const disabled = ref(false), valid = ref(true)
  let saved = 0
  const flow = useNumberingSteps(false, disabled, valid, async () => { saved++ })
  await flow.submit(); assert.equal(saved, 1); assert.equal(flow.step.value, 0)
  disabled.value = true; await flow.submit(); assert.equal(saved, 1)
})
