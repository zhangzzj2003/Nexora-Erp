import assert from 'node:assert/strict'
import { test } from 'node:test'
import { groupProductionDemands } from '../src/renderer/src/views/workspace/production/production-demand-groups.ts'
import { productionPlanBody, validateProductionPlanResult } from '../src/shared/production-plan-api.ts'
import { createAppState } from '../src/renderer/src/store/state.ts'
import { createProductionPlanActions } from '../src/renderer/src/store/modules/production-plan-actions.ts'
import { planFixture, planInputFixture } from './production-plan-fixture.mjs'

const plan = (id, requirements = '甲公司 Logo；白色', quantity = '0.100') => {
  const row = structuredClone(planFixture())
  row.id = id; row.lines = [{ ...row.lines[0], id, plan_id: id, production_requirements: requirements, unreleased_quantity: quantity }]
  return row
}
test('同产品跨计划汇总，要求相同保留来源，颜色或 Logo 不同独立分组', () => {
  const groups = groupProductionDemands([plan(1), plan(2, undefined, '0.200'), plan(3, '甲公司 Logo；黑色'), plan(4, '乙公司 Logo；白色')])
  assert.equal(groups.length, 1); assert.equal(groups[0].quantity, '0.500')
  assert.equal(groups[0].variants.length, 3)
  assert.equal(groups[0].variants[0].quantity, '0.300')
  assert.deepEqual(groups[0].variants[0].sources.map(s => s.plan.id), [1, 2])
})
test('未明确要求不默认合并，BOM、仓库、产品身份和单位分别核对', () => {
  const a = plan(1, ''), b = plan(2, ''), c = plan(3), d = plan(4), e = plan(5), f = plan(6), g = plan(7)
  d.lines[0].bom_id++
  e.lines[0].warehouse_id++
  f.lines[0].material_id++
  g.lines[0].unit = '件'
  const groups = groupProductionDemands([a, b, c, d, e, f, g])
  assert.equal(groups.length, 3)
  assert.equal(groups[0].variants.length, 5)
  assert.equal(groups[0].variants[0].sources.length, 1)
})
test('角标只反映批准的未生成数量，不计草稿、取消和已生成余额', () => {
  const draft = plan(1), cancelled = plan(2), complete = plan(3), active = plan(4)
  draft.approval.status = 'draft'; cancelled.status = 'cancelled'; complete.lines[0].unreleased_quantity = '0.000'
  active.approval.status = 'executed'
  assert.deepEqual(groupProductionDemands([draft, cancelled, complete, active])[0].variants[0].sources.map(s => s.plan.id), [4])
})
test('生产要求校验边界，旧计划可缺省；待生产坏响应不能伪装成可生成', () => {
  const input = planInputFixture(); input.lines[0].production_requirements = '  黑色  '
  assert.equal(productionPlanBody(input).lines[0].production_requirements, '黑色')
  for (const value of [null, 123, '色'.repeat(501)]) {
    input.lines[0].production_requirements = value
    assert.throws(() => productionPlanBody(input))
  }
  assert.doesNotThrow(() => validateProductionPlanResult('productionPlanDemands', [plan(1)]))
  assert.throws(() => validateProductionPlanResult('productionPlanDemands', [plan(1), plan(1)]))
  assert.throws(() => validateProductionPlanResult('productionPlanDemands', [{ ...plan(1), status: 'cancelled' }]))
  assert.throws(() => validateProductionPlanResult('productionPlanDemands', {}))
})
test('待生产角标迟到响应不能跨账号；读取失败不能显示为零待办', async t => {
  const previous = globalThis.window; t.after(() => { globalThis.window = previous })
  let finish
  globalThis.window = { nexora: { callApi: () => new Promise(resolve => { finish = resolve }) } }
  const state = createAppState()
  state.user.value = { id: 1, permissions: ['production_plan.view'] }
  const actions = createProductionPlanActions(state, run => run())
  const pending = actions.loadProductionPlanDemands()
  state.user.value = { id: 2, permissions: ['production_plan.view'] }
  finish([plan(1)])
  assert.equal(await pending, false)
  assert.deepEqual(state.productionPlanDemands.value, [])
  assert.equal(state.productionPlanDemandReady.value, false)
  globalThis.window.nexora.callApi = async () => { throw Error('服务端尚未升级') }
  assert.equal(await actions.loadProductionPlanDemands(), false)
  assert.match(state.productionPlanDemandError.value, /尚未升级/)
  assert.equal(state.productionPlanDemandReady.value, false)
  globalThis.window.nexora.callApi = async () => [plan(2)]
  assert.equal(await actions.loadProductionPlanDemands(), true)
  assert.equal(state.productionPlanDemands.value[0].id, 2)
  state.connectionLost.value = true
  assert.deepEqual(state.productionPlanDemands.value, [])
  assert.equal(state.productionPlanDemandReady.value, false)
})
