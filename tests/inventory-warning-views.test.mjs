import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createSSRApp,h} from 'vue'
import {renderToString} from '@vue/server-renderer'
import {setup as setupSsrStyles} from '@css-render/vue3-ssr'
import {createRouter,createMemoryHistory} from 'vue-router'
import {createPinia} from 'pinia'
import {createServer} from 'vite'
import vue from '@vitejs/plugin-vue'
const storeModule=`
import {defineStore} from 'pinia';import {ref} from 'vue';
export const fixture={calls:0,fail:false,release:null};
export const usePiniaAppStore=defineStore('warning-ui-test',()=>({
warningForm:ref({warehouse_id:0,material_id:0,version:0,threshold:'',enabled:true,reason:''}),warningEditing:ref(false),
warningOverview:ref({as_of:'2026-10-01',rows:[],warehouses:[],materials:[],summary:{normal:0,low:0,out_of_stock:0,disabled:0,configured:0,unconfigured:2}}),
server:ref({id:'test'}),warningEvents:ref({events:[],next_before_id:null}),warningEventsLoading:ref(false),warningEventsError:ref(''),warningDetail:ref(null),warningLoading:ref(false),warningError:ref(''),warningWarehouseId:ref(0),busy:ref(false),error:ref(''),connectionLost:ref(false),user:ref({id:1,permissions:['inventory.view','inventory_warning.manage']}),
can(code){return this.user.permissions.includes(code)},localTime:value=>value,loadInventoryWarnings(){},clearWarningDetail(){this.warningDetail=null},
startWarningRule(){this.warningEditing=true;return true},
loadWarningDetail(){this.warningDetail={row:{id:1,warehouse_code:'MAIN',sku:'MAT',warehouse_name:'主仓',material_name:'物料',unit:'件',quantity:'2.000',threshold:'5.000',status:'low',version:4},changes:[]};return true},
async saveWarningRule(){fixture.calls++;await new Promise(resolve=>{fixture.release=resolve});if(fixture.fail){this.error='版本冲突';return false}this.warningEditing=false;return true}

}));`
test('真实阈值与原因必填，冲突保留版本；未配置、只读和无权页面明确区分',async t=>{
  const server=await createServer({configFile:false,plugins:[{name:'warning-view-fixture',enforce:'pre',transform(code,id){if(id.endsWith('/InventoryWarningsView.vue'))return code.replace("from 'naive-ui'","from 'virtual:warning-view-naive'")},resolveId(id,importer){
    if(importer?.includes('/views/workspace/warehouse/') && id.endsWith('/store/app-store'))return '\0warning-view-store'
    if(id.endsWith('/WorkspaceTable.vue'))return '\0warning-view-table'
    if(id.endsWith('/WorkspaceSelect.vue'))return '\0warning-view-select'
    if(id==='virtual:warning-view-naive')return '\0warning-view-naive'
  },load(id){if(id==='\0warning-view-store')return storeModule
    if(id==='\0warning-view-table')return `import {defineComponent,h} from 'vue';export default defineComponent({props:{error:String},setup(props,{slots}){return ()=>h('section',[slots.filters?.(),slots.actions?.(),slots.beforeTable?.(),props.error?slots.errorActions?.():slots.empty?.()])}})`
    if(id==='\0warning-view-select')return `import {defineComponent,h} from 'vue';export default defineComponent({setup(){return ()=>h('span')}})`
    // 折叠容器使用真实实现，确保公共折叠项得到正确的上下文与键盘语义。
    if(id==='\0warning-view-naive')return `import {defineComponent,h} from 'vue';export {NCollapse} from 'naive-ui';const Body=defineComponent({setup(_props,{slots}){return ()=>h('div',slots.default?.())}});export const NCheckbox=Body;
export const NModal=defineComponent({props:{show:Boolean,title:String,maskClosable:Boolean,closable:Boolean,closeOnEsc:Boolean},setup(props,{slots}){return ()=>props.show?h('div',{role:'dialog','aria-label':props.title,'data-mask-closable':String(props.maskClosable)},[slots.default?.(),slots.footer?.()]):null}});`
  }},vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
  t.after(()=>server.close())
  const {usePiniaAppStore,fixture}=await server.ssrLoadModule('\0warning-view-store')
  const pinia=createPinia(),store=usePiniaAppStore(pinia)
  const {default:Component}=await server.ssrLoadModule('/src/renderer/src/views/workspace/warehouse/InventoryWarningsView.vue')
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',component:{render:()=>null}},{path:'/workspace/inventory-ledger',component:{render:()=>null}}]})
  await router.push('/');await router.isReady()
  let vnode
  const render=()=>{
    const app=createSSRApp({render:()=>{vnode=h(Component);return vnode}}).use(pinia).use(router)
    setupSsrStyles(app)
    return renderToString(app)
  }
  const empty=await render();assert.match(empty,/未配置 2 个/);assert.match(empty,/不表示库存充足/);assert.match(empty,/当前范围尚未配置预警规则/);assert.match(empty,/事件记录说明/)
  store.warningEditing=true;const editor=await render()
  assert.match(editor,/现存量预警阈值[\s\S]*?<input[^>]*\brequired\b/)
  assert.match(editor,/配置或修订原因[\s\S]*?<input[^>]*\brequired\b/)
  assert.match(editor,/正现存量达到阈值显示正常/)
  // 编辑时背景列表与筛选保持挂载，弹窗页脚的按钮仍关联真实表单提交。
  assert.match(editor,/role="dialog" aria-label="配置库存预警"/)
  assert.match(editor,/data-mask-closable="false"/)
  assert.match(editor,/搜索规则/)
  assert.match(editor,/form="inventory-warning-form"/)
  assert.match(editor,/预警事件/)
  assert.doesNotMatch(editor,/<input\b[^>]*\bvalue="0(?:\.000)?"/)
  store.warningForm.version=4;store.error='版本冲突';const conflict=await render()
  assert.match(conflict,/旧版本 v4/);assert.match(conflict,/保留本次输入/);assert.match(conflict,/版本冲突/)
  assert.match(conflict,/role="dialog" aria-label="修订预警规则"/)
  const view=vnode.component.setupState
  store.busy=true;view.updateEditor(false);assert.equal(store.warningEditing,true)
  store.busy=false
  await view.saveRule();assert.equal(fixture.calls,0)
  store.warningForm={warehouse_id:1,material_id:1,threshold:'6.000',version:4,enabled:true,reason:'按最低安全量调整'}
  fixture.fail=true
  const failed=view.saveRule()
  view.updateEditor(false);assert.equal(store.warningEditing,true)
  await view.saveRule();assert.equal(fixture.calls,1)
  fixture.release();await failed
  assert.equal(store.warningEditing,true)
  assert.equal(store.warningForm.threshold,'6.000')
  assert.equal(store.warningForm.reason,'按最低安全量调整')
  fixture.fail=false
  const success=view.saveRule();fixture.release();await success
  assert.equal(store.warningEditing,false)
  // 读取详情由用户打开弹窗；保存后的详情快照不会自动把用户带离列表。
  store.warningOverview.rows=[{id:1}]
  await render()
  const detailView=vnode.component.setupState
  await detailView.open({id:1});assert.equal(detailView.detailOpen,true)
  detailView.closeDetail();assert.equal(detailView.detailOpen,false);assert.equal(store.warningDetail,null)
  store.warningEditing=false;store.user.permissions=['inventory.view']
  const readonly=await render();assert.doesNotMatch(readonly,/>配置预警规则<!--/)
  store.connectionLost=true;assert.match(await render(),/旧库存数量和证据已失效/)
  store.user.permissions=[];const denied=await render();assert.match(denied,/没有库存查看权限/);assert.doesNotMatch(denied,/搜索规则/)
})
