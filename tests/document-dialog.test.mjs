import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createSSRApp, h, ref } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { createWarehouseActions } from '../src/renderer/src/store/modules/warehouse-actions.ts'
import { appendDocumentMaterial, documentMaterialIssue } from '../src/renderer/src/utils/document-material-lines.ts'

const materials = [{ id: 1, sku: 'EL-SR-000001', name: '贴片电阻', unit: '个' },
  { id: 2, sku: 'EL-SC-000002', name: '贴片电容', unit: '个' }]

test('加入物料复制草稿；重复、失效及非法数量不改变已加入明细', () => {
  const draft = { material_id: 1, quantity: '0.125' }
  const added = appendDocumentMaterial([], draft, materials)
  assert.equal(added.issue, '')
  draft.quantity = '9'
  assert.equal(added.lines[0].quantity, '0.125')
  for (const invalid of [{ material_id: 1, quantity: '2' }, { material_id: 99, quantity: '1' },
    ...['', '0', '-1', '1.0001', '1000000.001', '1e2'].map(quantity => ({ material_id: 2, quantity }))]) {
    const failed = appendDocumentMaterial(added.lines, invalid, materials)
    assert.ok(failed.issue)
    assert.deepEqual(failed.lines, added.lines)
  }
  const second = appendDocumentMaterial(added.lines, { material_id: 2, quantity: '1000000' }, materials)
  assert.equal(second.issue, '')
  assert.equal(second.lines.length, 2)
})

test('保存前校验空表、重复物料、失效物料和编辑后的数量', () => {
  assert.ok(documentMaterialIssue([], materials))
  const line = { material_id: 1, quantity: '0.001' }
  assert.equal(documentMaterialIssue([line], materials), '')
  assert.ok(documentMaterialIssue([line, line], materials))
  assert.ok(documentMaterialIssue([line], []))
  assert.ok(documentMaterialIssue([{ ...line, quantity: '0' }], materials))
})

test('单据明细上限与接口一致，达到一百项后拒绝继续添加', () => {
  const catalog = Array.from({ length: 101 }, (_, i) => ({ ...materials[0], id: i + 1 }))
  const lines = catalog.slice(0, 100).map(item => ({ material_id: item.id, quantity: '1' }))
  assert.equal(documentMaterialIssue(lines, catalog), '')
  assert.ok(appendDocumentMaterial(lines, { material_id: 101, quantity: '1' }, catalog).issue)
  assert.ok(documentMaterialIssue([...lines, { material_id: 101, quantity: '1' }], catalog))
})

test('其他入库保存失败保留完整草稿，成功后保留仓库并清空物料表', async t => {
  const originalWindow = globalThis.window
  t.after(() => { if (originalWindow === undefined) delete globalThis.window; else globalThis.window = originalWindow })
  const draft = { warehouse_id: 2, reason: 'gift', reference: 'REF', note: '赠品', lines: [{ material_id: 1, quantity: '3' }] }
  const otherInboundForm = ref(structuredClone(draft))
  let fail = true, sent
  globalThis.window = { nexora: { callApi: async (operation, input) => {
    assert.equal(operation, 'createOtherInbound')
    sent = input
    if (fail) throw Error('保存失败')
  } } }
  let error = ''
  const actions = createWarehouseActions({ otherInboundForm }, async action => {
    try { await action(); error = '' } catch (issue) { error = issue.message }
  })
  await actions.createOtherInbound()
  assert.equal(error, '保存失败')
  assert.deepEqual(otherInboundForm.value, draft)
  fail = false
  await actions.createOtherInbound()
  assert.equal(error, '')
  assert.deepEqual(sent, draft)
  assert.notEqual(sent.lines[0], otherInboundForm.value.lines[0])
  assert.deepEqual(otherInboundForm.value, { warehouse_id: 2, reason: 'other', reference: '', note: '', lines: [] })
})

// 展开弹窗和表格插槽，以真实公共弹窗验证行数据传递及布局；表格本体另有真实 vxe 测试。
const modalStub = `import { defineComponent, h } from 'vue'
export const captured = {}
export const NModal = defineComponent({ props:['show','title','maskClosable','closeOnEsc','closable'], setup(p,{slots,attrs}) {
  Object.assign(captured, { props: p, slots, attrs })
  return () => p.show ? h('section', {...attrs, 'data-mask-closable':p.maskClosable, 'data-close-on-esc':p.closeOnEsc, 'data-closable':p.closable}, [h('h2',p.title),slots.default?.()]) : null
}})`
const tableStub = `import { defineComponent, h } from 'vue'
export default defineComponent({props:['data','columns','emptyText'], setup(p,{slots}) {
 return ()=>h('section', [slots.heading?.(),slots.actions?.(),slots.beforeTable?.(),
 ...p.data.map(row=>h('article',p.columns.map(c=>slots['cell-'+c.key]?.({row})))),p.data.length?null:h('p',p.emptyText)])
}})`
const buttonStub = `import { defineComponent, h } from 'vue'
export default defineComponent({props:['type','disabled','loading'],setup(p,{slots,attrs}) {
 return ()=>h('button',{...attrs,type:p.type,disabled:p.disabled},slots.default?.())
}})`

test('统一弹窗按基础信息、分隔线、添加物料、表格及页脚顺序显示，并限制关闭和提交', async t => {
  const server = await createServer({ configFile: false, plugins: [{ name: 'document-dialog-fixtures', enforce: 'pre',
    transform(code, id) {
      if (!id.endsWith('/WorkspaceDocumentDialog.vue')) return
      return code.replace("'naive-ui'", "'virtual:document-modal'")
        .replace("'./WorkspaceTable.vue'", "'virtual:document-table'")
        .replace("'../app/AppButton.vue'", "'virtual:document-button'")
    },
    resolveId(id) {
      if (id.startsWith('virtual:document-')) return '\0' + id.slice('virtual:'.length)
    },
    load(id) {
      return id === '\0document-modal' ? modalStub : id === '\0document-table' ? tableStub
        : id === '\0document-button' ? buttonStub : undefined
    }
  }, vue()], optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  t.after(() => server.close())
  const { default: Dialog } = await server.ssrLoadModule('/src/renderer/src/components/workspace/WorkspaceDocumentDialog.vue')
  const base = { show: true, title: '非采购来源入库', data: [{ name: '贴片电阻', quantity: '2' }],
    columns: [{ key: 'name', title: '物料名称' }, { key: 'quantity', title: '数量' }], hint: '确认后才增加库存。' }
  const slots = { basicInfo: () => h('label', '仓库'), 'cell-name': ({ row }) => h('strong', row.name),
    'cell-quantity': ({ row }) => h('input', { value: row.quantity }) }
  const render = extra => renderToString(createSSRApp({ render: () => h(Dialog, { ...base, ...extra }, slots) }))
  const ready = (await render({})).replace(/<!--[\s\S]*?-->/g, '')
  const parts = ['基础信息', '仓库', '<hr', '物料明细', '添加物料', '贴片电阻', '确认后才增加库存', '保存草稿']
  parts.forEach((part, i) => { assert.ok(ready.includes(part), `${part}: ${ready}`); if (i) assert.ok(ready.indexOf(parts[i - 1]) < ready.indexOf(part), `${parts[i - 1]} -> ${part}: ${ready}`) })
  assert.match(ready, /value="2"/)
  assert.match(await render({ data: [] }), /尚未添加物料/)
  assert.doesNotMatch(await render({ show: false }), /基础信息/)
  for (const extra of [{ busy: true }, { disabled: true }, { submitDisabled: true }]) {
    assert.match(await render(extra), /<button[^>]*type="submit"[^>]*disabled/)
  }
  const busy = await render({ busy: true })
  assert.match(busy, /data-mask-closable="false"/)
  assert.match(busy, /data-close-on-esc="false"/)
  assert.match(busy, /data-closable="false"/)

  // 展开真实弹窗传给 Modal 的插槽，直接执行表单与关闭事件，校验保护逻辑而非按钮外观。
  let submits = 0, closes = 0
  const vnode = h(Dialog, { ...base, onSubmit: () => submits++, 'onUpdate:show': () => closes++ }, slots)
  await renderToString(createSSRApp({ render: () => vnode }))
  const { captured } = await server.ssrLoadModule('\0document-modal')
  const form = captured.slots.default()[0]
  const submit = () => form.props.onSubmit({ preventDefault() {} })
  const close = () => captured.attrs['onUpdate:show'](false)
  submit()
  close()
  assert.equal(submits, 1)
  assert.equal(closes, 1)
  vnode.component.props.busy = true
  submit()
  close()
  assert.equal(submits, 1)
  assert.equal(closes, 1)
  vnode.component.props.busy = false
  vnode.component.props.disabled = true
  submit()
  close()
  assert.equal(submits, 1)
  assert.equal(closes, 2)
  vnode.component.props.disabled = false
  vnode.component.props.submitDisabled = true
  submit()
  assert.equal(submits, 1)
})
