import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { setup as setupSsrStyles } from '@css-render/vue3-ssr'
import vue from '@vitejs/plugin-vue'
import { createServer } from 'vite'

// 使用真实 Naive 按钮，确保统计项具有键盘可操作按钮和选中状态语义。
test('公共统计组件显示数量和选中项，零数量可筛选，拒绝无效或重复选项', async t => {
  const server = await createServer({configFile:false,plugins:[vue()],server:{middlewareMode:true,hmr:false},optimizeDeps:{noDiscovery:true,include:[]},appType:'custom'})
  t.after(()=>server.close())
  const {default:Summary}=await server.ssrLoadModule('/src/renderer/src/components/workspace/WorkspaceSummaryFilters.vue')
  let vnode
  const changes=[]
  const app=createSSRApp({render:()=>{
    vnode=h(Summary,{modelValue:'all',options:[{key:'all',label:'全部单据',count:45,hint:'完整统计'},{key:'pending',label:'未处理',count:0,hint:'尚未入库',tone:'pending'}],
      'onUpdate:modelValue':key=>changes.push(key)})
    return vnode
  }})
  setupSsrStyles(app)
  const html=await renderToString(app)
  assert.match(html,/aria-label="单据概览与快速筛选"/)
  assert.match(html,/<button[^>]*aria-pressed="true"[^>]*aria-label="全部单据，45 条"/)
  assert.match(html,/<button[^>]*aria-pressed="false"[^>]*aria-label="未处理，0 条"/)
  assert.doesNotMatch(html,/<button[^>]*\sdisabled(?:=|\s|>)/)
  vnode.component.setupState.select('all')
  vnode.component.setupState.select('unknown')
  assert.deepEqual(changes,[])
  vnode.component.setupState.select('pending')
  assert.deepEqual(changes,['pending'])
  // 其他页面可只传两项并自定义标题，无需为五项入库概览复制组件。
  assert.match(html,/--summary-columns:2/)
  const alternate=createSSRApp({render:()=>{
    vnode=h(Summary,{modelValue:'pending',label:'自定义概览',hint:'',options:[{key:'all',label:'全部',count:1,hint:'全部记录'},{key:'pending',label:'待办',count:1,hint:'待办记录'}],
      'onUpdate:modelValue':key=>changes.push(key)})
    return vnode
  }})
  setupSsrStyles(alternate)
  const alternateHtml=await renderToString(alternate)
  assert.match(alternateHtml,/aria-label="自定义概览"/)
  assert.doesNotMatch(alternateHtml,/summary-filter-hint/)
  vnode.component.setupState.select('all')
  assert.deepEqual(changes,['pending','all'])

})

test('统计放入标题右侧公共目标，切换页面时由路由页面卸载', () => {
  const shell=readFileSync(new URL('../src/renderer/src/views/WorkspaceShell.vue',import.meta.url),'utf8')
  const view=readFileSync(new URL('../src/renderer/src/views/workspace/warehouse/OtherInboundsView.vue',import.meta.url),'utf8')
  const target=shell.indexOf('id="workspace-page-summary"')
  assert.ok(target>shell.indexOf('<header v-if="!isNumberingScreen"'))
  assert.ok(target<shell.indexOf('</header>',shell.indexOf('<header v-if="!isNumberingScreen"')))
  assert.match(view,/<Teleport defer to="#workspace-page-summary">\s*<WorkspaceSummaryFilters v-model="statusFilter" :options="summaryOptions"/)
})
