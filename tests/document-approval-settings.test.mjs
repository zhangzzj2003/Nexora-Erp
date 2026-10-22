import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { createPinia } from 'pinia'
import { createRenderer, createSSRApp, h, nextTick } from 'vue'
import { compileScript, parse } from '@vue/compiler-sfc'
import { renderToString } from '@vue/server-renderer'
import { createServer, normalizePath } from 'vite'
import vue from '@vitejs/plugin-vue'

test('真实审批设置组件展示有序步骤、冲突及禁用状态，普通用户无配置入口', async t => {
  // 内存测试加载实际脚本和模板；样式交给生产构建及浏览器验证，避免 Windows SSR 的子组件 CSS 调用超时。
  const compile = name => {
    const filename = resolve(`src/renderer/src/components/workspace/${name}.vue`)
    return compileScript(parse(readFileSync(filename, 'utf8'), { filename }).descriptor,
      { id: name, inlineTemplate: true }).content
  }
  const clientId = name => normalizePath(resolve(`src/renderer/src/components/workspace/${name}.vue.client.ts`))
  const fixture = `import {defineStore} from 'pinia';import {ref} from 'vue';
    export const usePiniaAppStore=defineStore('approval-settings-test',()=>({
      user:ref({id:1,roles:['admin']}),busy:ref(false),connectionLost:ref(false),roles:ref([{code:'admin',label:'管理员'}]),
      approvalPolicies:ref([{document_type:'WarehouseInbound',title:'其他入库',version:2},
        {document_type:'PurchaseOrder',title:'采购订单',version:1,amount_basis:'订单逐行金额合计'}]),
      approvalPolicyDrafts:ref({WarehouseInbound:{document_type:'WarehouseInbound',version:1,steps:[{name:'审核',role:null},{name:'批准',role:'admin'}]},
        PurchaseOrder:{document_type:'PurchaseOrder',version:1,steps:[{name:'批准',role:null}],branches:[]}}),
      approvalPolicyLoading:ref(false),approvalPolicyError:ref('版本冲突，草稿已保留'),
      loadApprovalPolicies:async()=>true,editApprovalPolicy(type){this.approvalPolicyDrafts[type]={document_type:type,version:2,steps:[{name:'恢复草稿',role:null}]}},saveApprovalPolicy:async()=>true
    }));`
  const server = await createServer({ configFile: false, plugins: [{
    name: 'approval-settings-fixture', enforce: 'pre', resolveId(id, importer) {
      if (importer?.includes('DocumentApprovalSettings') && id.endsWith('/store/app-store')) return '\0approval-settings-store'
      if (id.endsWith('/ApprovalStepEditor.vue')) return clientId('ApprovalStepEditor')
      if (id === clientId('DocumentApprovalSettings') || id === clientId('ApprovalStepEditor')) return id
      for (const suffix of ['AppButton.vue', 'AppInput.vue', 'WorkspaceSelect.vue']) {
        if (id.endsWith('/' + suffix)) return '\0approval-settings-' + suffix
      }
    }, load(id) {
      if (id === '\0approval-settings-store') return fixture
      if (id === clientId('ApprovalStepEditor')) return compile('ApprovalStepEditor')
      if (id === clientId('DocumentApprovalSettings')) return compile('DocumentApprovalSettings')
      if (id === '\0approval-settings-AppButton.vue') return `import {defineComponent,h} from 'vue';export default defineComponent({props:['disabled'],setup(p,{slots,attrs}){return()=>h('button',{...attrs,disabled:p.disabled},slots.default?.())}})`
      if (id === '\0approval-settings-AppInput.vue') return `import {defineComponent,h} from 'vue';export default defineComponent({props:['modelValue','disabled'],emits:['update:modelValue'],setup(p,{attrs,emit}){return()=>h('input',{...attrs,value:p.modelValue,disabled:p.disabled,onInput:e=>emit('update:modelValue',e.target.value)})}})`
      if (id === '\0approval-settings-WorkspaceSelect.vue') return `import {defineComponent,h} from 'vue';export default defineComponent({props:['modelValue','disabled','options'],emits:['update:modelValue','change'],setup(p,{emit}){return()=>h('select',{disabled:p.disabled,value:p.modelValue,onChange:e=>{emit('update:modelValue',e.target.value);emit('change',e.target.value)}},p.options.map(o=>h('option',{value:o.value},o.label)))}})`
    }
  }, vue()], optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  t.after(() => server.close())
  const { usePiniaAppStore } = await server.ssrLoadModule('\0approval-settings-store')
  const pinia = createPinia(), store = usePiniaAppStore(pinia)
  const { default: Settings } = await server.ssrLoadModule('/src/renderer/src/components/workspace/DocumentApprovalSettings.vue')
  const render = () => renderToString(createSSRApp({ render: () => h(Settings) }).use(pinia))
  let html = await render()
  assert.match(html, /单据审批步骤/)
  assert.match(html, /按钮权限/); assert.match(html, /同一人员可完成多个已授权步骤/); assert.match(html, /审批操作/); assert.match(html, /value="verify"/)
  assert.match(html, /value="审核"/)
  assert.match(html, /value="批准"/)
  assert.match(html, /载入最新规则/)
  assert.match(html, /role="alert"/)
  store.connectionLost = true
  html = await render()
  assert.match(html, /<button[^>]*disabled[^>]*>保存审批规则/)
  store.user.roles = ['viewer']
  assert.doesNotMatch(await render(), /单据审批步骤|保存审批规则/)
  // 恢复登录时全局仍忙碌，初始加载不能永久丢失模板编辑草稿。
  store.user.roles = ['admin']; store.busy = true; store.connectionLost = false
  store.approvalPolicyDrafts = {}
  assert.doesNotMatch(await render(), /value="恢复草稿"/)
  store.busy = false
  assert.match(await render(), /value="恢复草稿"/)
  const { default: InteractiveSettings } = await server.ssrLoadModule(clientId('DocumentApprovalSettings'))
  const element = type => ({ type, props: {}, children: [], parent: null, text: '' })
  const renderer = createRenderer({
    createElement: element, createText: text => ({ ...element('#text'), text }), createComment: text => ({ ...element('#comment'), text }),
    setText: (node, text) => { node.text = text }, setElementText: (node, text) => { node.children = []; node.text = text },
    patchProp: (node, key, _, value) => { node.props[key] = value }, parentNode: node => node.parent,
    nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1] ?? null,
    insert(node, parent, anchor = null) { if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1); node.parent = parent
      const index = anchor ? parent.children.indexOf(anchor) : -1; parent.children.splice(index < 0 ? parent.children.length : index, 0, node) },
    remove(node) { if (node.parent) { node.parent.children.splice(node.parent.children.indexOf(node), 1); node.parent = null } }
  })
  const root = element('root'), app = renderer.createApp({ render: () => h(InteractiveSettings) }).use(pinia)
  app.mount(root); t.after(() => app.unmount()); await nextTick()
  const flatten = node => [node, ...node.children.flatMap(flatten)]
  const text = node => (node.type === '#comment' ? '' : node.text) + node.children.map(text).join('')
  const button = label => flatten(root).find(node => node.type === 'button' && text(node) === label)
  const choose = async type => { flatten(root).find(node => node.type === 'select').props.onChange({ target: { value: type } }); await nextTick() }
  assert.equal(button('增加金额分支'), undefined)
  await choose('PurchaseOrder')
  assert.match(text(root), /订单逐行金额合计（人民币）/)
  assert.match(text(root), /尚未设置金额分支/)
  button('增加金额分支').props.onClick(); await nextTick()
  assert.equal(store.approvalPolicyDrafts.PurchaseOrder.branches.length, 1)
  const branch = store.approvalPolicyDrafts.PurchaseOrder.branches[0]
  const branchPanel = () => flatten(root).find(node => node.type === 'fieldset')
  const inputs = flatten(branchPanel()).filter(node => node.type === 'input')
  for (const [index, value] of ['大额采购', '1000.00', '5000.00'].entries()) inputs[index].props.onInput({ target: { value } })
  await nextTick()
  assert.equal(branch.name, '大额采购'); assert.equal(branch.min_amount, '1000.00'); assert.equal(branch.max_amount, '5000.00')
  flatten(branchPanel()).find(node => node.type === 'button' && text(node) === '增加步骤').props.onClick(); await nextTick()
  assert.equal(branch.steps.length, 2)
  flatten(branchPanel()).find(node => node.type === 'select').props.onChange({ target: { value: 'verify' } }); await nextTick()
  assert.equal(branch.steps[0].action, 'verify'); assert.equal(branch.steps[0].name, '核准')
  store.connectionLost = true; await nextTick()
  store.approvalPolicies = []; await nextTick()
  assert.match(text(root), /金额分支 1|单据固定金额（人民币）/)
  assert.equal(flatten(branchPanel()).find(node => node.type === 'input').props.value, '大额采购')
  assert.equal(button('增加金额分支').props.disabled, true)
  assert.equal(button('移除金额分支').props.disabled, true)
  assert.equal(button('保存审批规则').props.disabled, true)
  // 禁用时即使回调被重复触发，也不能修改草稿。
  button('增加金额分支').props.onClick(); await nextTick()
  assert.equal(store.approvalPolicyDrafts.PurchaseOrder.branches.length, 1)
  store.connectionLost = false; await nextTick()
  button('移除金额分支').props.onClick(); await nextTick()
  assert.equal(store.approvalPolicyDrafts.PurchaseOrder.branches.length, 0)
})
