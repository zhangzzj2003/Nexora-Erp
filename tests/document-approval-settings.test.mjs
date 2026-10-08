import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createPinia } from 'pinia'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'

test('真实审批设置组件展示有序步骤、冲突及禁用状态，普通用户无配置入口', async t => {
  const fixture = `import {defineStore} from 'pinia';import {ref} from 'vue';
    export const usePiniaAppStore=defineStore('approval-settings-test',()=>({
      user:ref({id:1,roles:['admin']}),busy:ref(false),connectionLost:ref(false),roles:ref([{code:'admin',label:'管理员'}]),
      approvalPolicies:ref([{document_type:'WarehouseInbound',title:'其他入库',version:2}]),
      approvalPolicyDrafts:ref({WarehouseInbound:{document_type:'WarehouseInbound',version:1,steps:[{name:'审核',role:null},{name:'批准',role:'admin'}]}}),
      approvalPolicyLoading:ref(false),approvalPolicyError:ref('版本冲突，草稿已保留'),
      loadApprovalPolicies:async()=>true,editApprovalPolicy(type){this.approvalPolicyDrafts[type]={document_type:type,version:2,steps:[{name:'恢复草稿',role:null}]}},saveApprovalPolicy:async()=>true
    }));`
  const server = await createServer({ configFile: false, plugins: [{
    name: 'approval-settings-fixture', enforce: 'pre', resolveId(id, importer) {
      if (importer?.includes('DocumentApprovalSettings') && id.endsWith('/store/app-store')) return '\0approval-settings-store'
      for (const suffix of ['AppButton.vue', 'AppInput.vue', 'WorkspaceSelect.vue']) {
        if (id.endsWith('/' + suffix)) return '\0approval-settings-' + suffix
      }
    }, load(id) {
      if (id === '\0approval-settings-store') return fixture
      if (id === '\0approval-settings-AppButton.vue') return `import {defineComponent,h} from 'vue';export default defineComponent({props:['disabled'],setup(p,{slots,attrs}){return()=>h('button',{...attrs,disabled:p.disabled},slots.default?.())}})`
      if (id === '\0approval-settings-AppInput.vue') return `import {defineComponent,h} from 'vue';export default defineComponent({props:['modelValue','disabled'],setup(p,{attrs}){return()=>h('input',{...attrs,value:p.modelValue,disabled:p.disabled})}})`
      if (id === '\0approval-settings-WorkspaceSelect.vue') return `import {defineComponent,h} from 'vue';export default defineComponent({props:['modelValue','disabled','options'],setup(p){return()=>h('select',{disabled:p.disabled},p.options.map(o=>h('option',{value:o.value},o.label)))}})`
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
})
