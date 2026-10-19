import assert from 'node:assert/strict'
import { test } from 'node:test'
import { effectScope, ref } from 'vue'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createBusinessOperation } from '../src/renderer/src/store/business-operation.ts'
import { submitCreateDialog } from '../src/renderer/src/utils/create-dialog.ts'

function fixture(t, refresh = async () => {}, approval = async () => {}) {
  const scope = effectScope(), state = scope.run(createAppState)
  state.user.value = { id: 1, roles: [], permissions: [] }
  t.after(() => scope.stop())
  return { state, perform: createBusinessOperation(state, refresh, () => approval) }
}

test('保存成功但列表刷新失败仍关闭新建表单，仅提示刷新告警', async t => {
  let writes = 0, approvalReads = 0
  const { state, perform } = fixture(t, async () => { throw Error('网络超时') }, async () => { approvalReads++ })
  const open = ref(true)
  await submitCreateDialog(() => perform(async () => { writes++ }, '订单已保存。'), state, open)
  assert.equal(writes, 1); assert.equal(approvalReads, 1); assert.equal(open.value, false)
  assert.equal(state.notice.value, '订单已保存。'); assert.equal(state.error.value, '')
  assert.match(state.warning.value, /操作已完成.*刷新失败.*勿重复提交.*网络超时/)
  assert.equal(state.busy.value, false)
})

test('写入失败保留表单与草稿，不产生成功消息或刷新告警', async t => {
  let reads = 0, approvalReads = 0
  const { state, perform } = fixture(t, async () => { reads++ }, async () => { approvalReads++ })
  state.salesForm.value.reference = '原输入'; const open = ref(true)
  await submitCreateDialog(() => perform(async () => { throw Error('版本冲突') }, '已保存'), state, open)
  assert.equal(open.value, true); assert.equal(state.salesForm.value.reference, '原输入')
  assert.equal(state.error.value, '版本冲突'); assert.equal(state.notice.value, ''); assert.equal(state.warning.value, '')
  assert.equal(reads, 0); assert.equal(approvalReads, 1)
})

test('审批刷新抛错也不能将已成功写入变成保存失败，忙碌状态正常释放', async t => {
  const { state, perform } = fixture(t, async () => {}, async () => { throw Error('审批超时') })
  await perform(async () => {}, '已确认')
  assert.equal(state.notice.value, '已确认'); assert.equal(state.error.value, '')
  assert.match(state.warning.value, /操作已完成.*审批详情刷新失败/); assert.equal(state.busy.value, false)
})

test('写入期间换账号不会把旧成功或错误消息写入新会话', async t => {
  for (const failed of [false, true]) {
    let finish, refreshes = 0
    const pending = new Promise((resolve, reject) => { finish = () => failed ? reject(Error('旧账号失败')) : resolve() })
    const { state, perform } = fixture(t, async () => { refreshes++ }, async () => { refreshes++ })
    const operation = perform(() => pending, '旧账号已保存')
    state.user.value = { id: 2, roles: [], permissions: [] }; finish(); await operation
    assert.equal(state.notice.value, ''); assert.equal(state.error.value, ''); assert.equal(state.warning.value, '')
    assert.equal(refreshes, 0); assert.equal(state.busy.value, false)
  }
})

test('忙碌或断线不提交，新操作清除上次告警', async t => {
  const { state, perform } = fixture(t); let calls = 0
  state.busy.value = true; await perform(async () => { calls++ }, '已保存')
  state.busy.value = false; state.connectionLost.value = true; await perform(async () => { calls++ }, '已保存')
  assert.equal(calls, 0)
  state.connectionLost.value = false; state.warning.value = '旧告警'
  await perform(async () => { calls++ }, '已保存')
  assert.equal(calls, 1); assert.equal(state.warning.value, ''); assert.equal(state.error.value, '')
})
