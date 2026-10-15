import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { createRenderer, h, nextTick, ssrContextKey } from 'vue'
import { parse, compileScript, compileTemplate } from '@vue/compiler-sfc'
import { createPinia } from 'pinia'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'

// 真实页面和 Pinia 参与更新；可控离场替身验证供应商列表消失时外壳不会抢先卸载。
test('供应商消失先关闭绑定弹窗，保留离场外壳并拒绝旧绑定事件', async t => {
  // SSR 载入提供真实 setup；正常模板编译供内存渲染器检查跨更新的组件身份。
  // URL 的 pathname 在 Windows 会保留盘符前的斜杠，必须按系统规则转换为真实文件路径。
  const filename = fileURLToPath(new URL('../src/renderer/src/views/workspace/catalog/SuppliersView.vue', import.meta.url))
  const { descriptor } = parse(readFileSync(filename, 'utf8'), { filename })
  const { bindings } = compileScript(descriptor, { id: 'supplier-binding-test' })
  const template = compileTemplate({ source: descriptor.template.content, filename, id: 'supplier-binding-test', compilerOptions: { bindingMetadata: bindings } })
  const server = await createServer({ configFile: false, plugins: [{
    name: 'supplier-binding-fixtures', enforce: 'pre',
    transform(code, id) { if (id.endsWith('/SuppliersView.vue')) return code.replace("'naive-ui'", "'virtual:supplier-binding-naive'") },
    resolveId(id, importer) {
      if (id === 'virtual:supplier-binding-naive') return '\0supplier-binding-naive'
      if (!importer?.includes('/src/renderer/')) return
      if (id.endsWith('/store/app-store')) return '\0supplier-binding-store'
      if (id.endsWith('/AppModal.vue')) return '\0supplier-binding-modal'
      if (id.endsWith('/WorkspaceTable.vue')) return '\0supplier-binding-table'
      if (id.endsWith('.vue')) return '\0supplier-binding-control'
      if (id === 'naive-ui') return '\0supplier-binding-naive'
    },
    load(id) {
      if (id === '\0supplier-binding-render') return template.code
      if (id === '\0supplier-binding-store') return `import {ref} from 'vue';import {defineStore} from 'pinia';
        export const writes=[];export const usePiniaAppStore=defineStore('supplier-binding-test',()=>({
          busy:ref(false),error:ref(''),notice:ref(''),connectionLost:ref(false),
          suppliers:ref([{id:1,name:'供应商甲'}]),materials:ref([{id:7,sku:'M7',name:'物料',unit:'个'}]),supplierMaterials:ref([]),
          can:()=>true,saveSupplier:async()=>false,deleteSupplier:()=>{},localTime:x=>x,
          setSupplierMaterial:async(...args)=>{writes.push(args)}
        }));`
      if (id === '\0supplier-binding-table') return `import {defineComponent,h} from 'vue';export default defineComponent({props:['data','columns'],setup(p,{slots}){return()=>h('div',[slots.actions?.(),slots.filters?.(),slots.beforeTable?.(),...(p.data??[]).map(row=>h('div',(p.columns??[]).map(column=>slots['cell-'+column.key]?.({row}))))])}})`
      if (id === '\0supplier-binding-control') return `import {defineComponent,h} from 'vue';export default defineComponent({setup(p,{attrs,slots}){return()=>h('button',attrs,slots.default?.())}})`
      if (id === '\0supplier-binding-naive') return `import {defineComponent,h} from 'vue';export const NPopconfirm=defineComponent({setup(p,{slots}){return()=>h('span',slots.trigger?.())}})`
      if (id === '\0supplier-binding-modal') return `import {defineComponent,h,ref,watch,onBeforeUnmount} from 'vue';
        export const modals=new Map();export default defineComponent({props:['show','originKey','busy'],setup(p,{slots}){
          const visible=ref(p.show), state={props:p,events:[],unmounted:false,completeLeave(){visible.value=false;state.events.push('after-leave')}};
          modals.set(p.originKey,state);watch(()=>p.show,show=>{if(show){visible.value=true;state.events.push('after-enter')}else state.events.push('before-leave')},{flush:'sync'});
          onBeforeUnmount(()=>state.unmounted=true);return()=>visible.value?h('section',slots.default?.()):null;
        }})`
    }
  }, vue()], optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
  t.after(() => server.close())
  const previous = globalThis.window
  globalThis.window = { nexora: { callApi: async () => ({ items: [], total: 0, page: 1, page_size: 20 }) } }
  t.after(() => { globalThis.window = previous })
  const { usePiniaAppStore, writes } = await server.ssrLoadModule('\0supplier-binding-store')
  const { modals } = await server.ssrLoadModule('\0supplier-binding-modal')
  const { default: View } = await server.ssrLoadModule('/src/renderer/src/views/workspace/catalog/SuppliersView.vue')
  View.render = (await server.ssrLoadModule('\0supplier-binding-render')).render
  const { captureDialogOrigin, getDialogOrigin, visibleDialogOrigin, clearDialogOrigins } = await server.ssrLoadModule('/src/renderer/src/utils/dialog-origin.ts')
  t.after(clearDialogOrigins)
  const pinia = createPinia(), store = usePiniaAppStore(pinia)
  let page
  const renderer = createRenderer({ createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
    insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {}, parentNode: () => null, nextSibling: () => null })
  const app = renderer.createApp({ render: () => h(View) }).use(pinia)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mixin({ created() { if (this.$options.__name === 'SuppliersView') page = this.$.setupState } })
  app.mount({}); t.after(() => app.unmount())
  page.selectedId = 1
  await nextTick()
  const element = { isConnected: true, getBoundingClientRect: () => ({ left: 10, top: 20, width: 80, height: 32 }) }
  captureDialogOrigin('SuppliersView:binding', element)
  page.bindOpen = true; page.materialId = 7
  await nextTick()
  const modal = modals.get('SuppliersView:binding'), staleSubmit = page.submitBinding
  assert.equal(modal.props.show, true)
  assert.deepEqual(modal.events, ['after-enter'])
  // 来源与供应商一起消失，动画辅助逻辑应选择淡出，页面仍交由同一个 shell 结束关闭。
  element.isConnected = false; store.suppliers = []
  assert.equal(page.bindOpen, false)
  await nextTick()
  assert.equal(modals.get('SuppliersView:binding'), modal)
  assert.equal(modal.unmounted, false)
  assert.equal(modal.props.show, false)
  assert.deepEqual(modal.events, ['after-enter', 'before-leave'])
  assert.equal(visibleDialogOrigin(getDialogOrigin('SuppliersView:binding'), { width: 1024, height: 768 }), null)
  await staleSubmit()
  assert.deepEqual(writes, [])
  modal.completeLeave()
  assert.deepEqual(modal.events, ['after-enter', 'before-leave', 'after-leave'])
  store.suppliers = [{ id: 1, name: '恢复的供应商' }]
  await nextTick()
  assert.equal(page.bindOpen, false, '恢复列表不能自行重新弹出旧绑定窗口')
})
