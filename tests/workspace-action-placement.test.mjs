import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { parse as parseSfc } from '@vue/compiler-sfc'
import { parse } from '@vue/compiler-dom'

// 固定迁移前的业务约束，验证移动操作入口时不丢失权限、禁用条件和弹窗原点。
const cases = [
  {"file":"production/EquipmentMaintenanceView.vue","click":"store.loadEquipment()","count":4,"directives":[{"name":"bind","arg":"disabled","exp":"disabled","modifiers":[]},{"name":"on","arg":"click","exp":"store.loadEquipment()","modifiers":[]}]},
  {"file":"production/QualityDispositionView.vue","click":"store.loadQuality()","count":2,"directives":[{"name":"bind","arg":"disabled","exp":"disabled","modifiers":[]},{"name":"on","arg":"click","exp":"store.loadQuality()","modifiers":[]}]},
  {"file":"sales/AfterSalesView.vue","click":"store.loadAfterSales()","count":2,"directives":[{"name":"bind","arg":"disabled","exp":"disabled","modifiers":[]},{"name":"on","arg":"click","exp":"store.loadAfterSales()","modifiers":[]}]},
  {"file":"sales/CustomerRelationsView.vue","click":"newRecord(mode)","count":1,"directives":[{"name":"if","exp":"store.can(permission(mode))","modifiers":[]},{"name":"bind","arg":"disabled","exp":"disabled || !options","modifiers":[]},{"name":"on","arg":"click","exp":"captureDialogOrigin('CustomerRelationsView:contact', $event)","modifiers":["capture"]},{"name":"on","arg":"click","exp":"newRecord(mode)","modifiers":[]}]},
  {"file":"sales/CustomerRelationsView.vue","click":"ownerModal=true","count":1,"directives":[{"name":"if","exp":"store.can('customer.assign')","modifiers":[]},{"name":"bind","arg":"disabled","exp":"disabled || !options","modifiers":[]},{"name":"on","arg":"click","exp":"captureDialogOrigin('CustomerRelationsView:owner', $event)","modifiers":["capture"]},{"name":"on","arg":"click","exp":"ownerModal=true","modifiers":[]}]},
  {"file":"sales/CustomerRelationsView.vue","click":"contactImportOpen=true","count":1,"directives":[{"name":"if","exp":"mode==='contact' && store.can('crm_contact.manage')","modifiers":[]},{"name":"bind","arg":"disabled","exp":"disabled || !options","modifiers":[]},{"name":"on","arg":"click","exp":"captureDialogOrigin('ContactImportDialog:import', $event)","modifiers":["capture"]},{"name":"on","arg":"click","exp":"contactImportOpen=true","modifiers":[]}]},
  {"file":"sales/CustomerRelationsView.vue","click":"opportunityImportOpen=true","count":1,"directives":[{"name":"if","exp":"mode==='opportunity' && store.can('crm_opportunity.manage')","modifiers":[]},{"name":"bind","arg":"disabled","exp":"disabled || !options","modifiers":[]},{"name":"on","arg":"click","exp":"captureDialogOrigin('OpportunityImportDialog:import', $event)","modifiers":["capture"]},{"name":"on","arg":"click","exp":"opportunityImportOpen=true","modifiers":[]}]},
  {"file":"production/MaterialPlanningView.vue","click":"store.loadMrp()","count":1,"directives":[{"name":"bind","arg":"disabled","exp":"disabled","modifiers":[]},{"name":"on","arg":"click","exp":"store.loadMrp()","modifiers":[]}]},
  {"file":"finance/ControlBalanceTransfersView.vue","click":"start","count":1,"directives":[{"name":"if","exp":"can('control_transfer.create')","modifiers":[]},{"name":"bind","arg":"disabled","exp":"disabled || !options","modifiers":[]},{"name":"on","arg":"click","exp":"captureDialogOrigin('ControlBalanceTransfersView:form', $event)","modifiers":["capture"]},{"name":"on","arg":"click","exp":"start","modifiers":[]}]},
  {"file":"finance/SubledgerSettlements.vue","click":"start","count":1,"directives":[{"name":"if","exp":"can('finance.record')","modifiers":[]},{"name":"bind","arg":"disabled","exp":"disabled || !report","modifiers":[]},{"name":"on","arg":"click","exp":"captureDialogOrigin('SubledgerSettlements:form', $event)","modifiers":["capture"]},{"name":"on","arg":"click","exp":"start","modifiers":[]}]},
  {"file":"finance/SubledgerOrderSettlements.vue","click":"start","count":1,"directives":[{"name":"if","exp":"can('finance.record')","modifiers":[]},{"name":"bind","arg":"disabled","exp":"disabled || !options?.active","modifiers":[]},{"name":"on","arg":"click","exp":"captureDialogOrigin('SubledgerOrderSettlements:form', $event)","modifiers":["capture"]},{"name":"on","arg":"click","exp":"start","modifiers":[]}]},
  {"file":"finance/BusinessJournalPanel.vue","click":"editPolicy","count":1,"directives":[{"name":"if","exp":"can('business_journal.configure')","modifiers":[]},{"name":"bind","arg":"disabled","exp":"!options || loading || busy || connectionLost","modifiers":[]},{"name":"on","arg":"click","exp":"editPolicy","modifiers":[]}]},
  {"file":"finance/AuxiliaryAccountingView.vue","click":"loadAuxiliaryOptions","count":1,"directives":[{"name":"bind","arg":"disabled","exp":"loading || busy || connectionLost","modifiers":[]},{"name":"on","arg":"click","exp":"loadAuxiliaryOptions","modifiers":[]}]},
  {"file":"finance/SubledgerOpeningsView.vue","click":"reload","count":4,"directives":[{"name":"bind","arg":"disabled","exp":"disabled","modifiers":[]},{"name":"on","arg":"click","exp":"reload","modifiers":[]}]}
]
const root = new URL('../src/renderer/src/views/workspace/', import.meta.url)
for (const entry of cases) test(entry.file + '：' + entry.click + ' 进入操作栏并保留约束', () => {
  const source = readFileSync(new URL(entry.file, root), 'utf8')
  const found = []
  function walk(node, ancestors = []) {
    if (node.type === 1) {
      if (node.tag === 'AppButton' && node.props.some(p => p.name === 'on' && p.arg?.content === 'click' && p.exp?.content === entry.click)) found.push({ node, ancestors })
      ancestors = [...ancestors, node]
    }
    for (const child of node.children ?? []) walk(child, ancestors)
  }
  walk(parse(parseSfc(source).descriptor.template.content))
  const actions = found.filter(({ ancestors }) => ancestors.some(n => n.tag === 'template' && n.props.some(p => p.name === 'slot' && p.arg?.content === 'actions')))
  assert.equal(actions.length, entry.count)
  for (const { node } of actions) for (const expected of entry.directives) {
    assert.ok(node.props.some(p => p.type === 7 && p.name === expected.name && p.arg?.content === expected.arg && p.exp?.content === expected.exp && JSON.stringify(p.modifiers.map(m => m.content)) === JSON.stringify(expected.modifiers)), JSON.stringify(expected))
  }
  // 表格之外只允许受编辑/报表状态限制的备用入口，不能在列表上重复出现。
  for (const { node, ancestors } of found.filter(item => !actions.includes(item))) {
    assert.ok([node, ...ancestors].some(n => n.props.some(p => p.name === 'if' && /editor|mode/.test(p.exp?.content ?? ''))))
  }
})
