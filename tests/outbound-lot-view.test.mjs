import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createSSRApp,h} from 'vue'
import {renderToString} from '@vue/server-renderer'
import { setup as setupSsrStyles } from '@css-render/vue3-ssr'
import {createPinia} from 'pinia'
import {createServer} from 'vite'
import vue from '@vitejs/plugin-vue'

const storeModule=`import {defineStore} from 'pinia';import {ref} from 'vue';
export const calls=[];
export const usePiniaAppStore=defineStore('outbound-lot-ui-test',()=>{
const warehouseOutbounds=ref([]),error=ref(''),notice=ref(''),busy=ref(false),connectionLost=ref(false);
const materials=ref([]),warehouses=ref([]),otherOutboundForm=ref({warehouse_id:1,reason:'other',note:'',reference:'',lines:[]});
const otherOutboundReversalReasons=ref({}),documentApprovalTarget=ref(null);
return {warehouseOutbounds,error,notice,busy,connectionLost,documentApprovalTarget,
documentApprovalRecord:ref(null),
materials,warehouses,otherOutboundForm,otherOutboundReversalReasons,
can:()=>true,localTime:value=>value,createOtherOutbound(){},loadAvailableOutboundLots(){},
postWarehouseOutbound(){},cancelOtherOutbound(){},reverseOtherOutbound(){},
openDocumentApproval(target){calls.push(['approval',target]);documentApprovalTarget.value=target;return true},
closeDocumentApproval(){documentApprovalTarget.value=null}}});`
const buttonModule=`import {defineComponent,h} from 'vue';export const buttons=[];
export default defineComponent({props:['disabled'],setup(p,{slots,attrs}){return()=>{
 const children=slots.default?.();const label=(children??[]).map(v=>typeof v.children==='string'?v.children:'').join('').trim();
 buttons.push({label,disabled:p.disabled,click:attrs.onClick});return h('button',attrs,children)}}});`

test('其他出库与采购退货显示批次证据、旧单差额和统一确认入口',async t=>{
  const server=await createServer({configFile:false,plugins:[{name:'outbound-lot-view-fixture',enforce:'pre',
    resolveId(id,importer){
      if(importer?.includes('/views/workspace/warehouse/WarehouseOutboundsView')
          && id.endsWith('/store/app-store'))return '\0outbound-view-store'
      if(id.endsWith('/WorkspaceTable.vue'))return '\0outbound-view-table'
      if(id.endsWith('/WorkspaceSelect.vue'))return '\0outbound-view-select'
      if(id.endsWith('/AppButton.vue'))return '\0outbound-view-button'
      // 审批弹窗另有真实组件测试，此处聚焦仓库行的批次证据和批准门槛。
      if(id.endsWith('/DocumentApprovalDialog.vue'))return '\0outbound-view-approval'
    },load(id){
      if(id==='\0outbound-view-store')return storeModule
      if(id==='\0outbound-view-approval')return `export default {render(){return this.$slots.footerActions?.()??null}}`
      if(id==='\0outbound-view-button')return buttonModule
      if(id==='\0outbound-view-table')return `import {defineComponent,h} from 'vue';export const tableState={};export default defineComponent({props:['data','columns','pagination','minTableWidth'],setup(props,{slots,attrs}){Object.assign(tableState,{props,slots,attrs});return ()=>h('section',[
        slots.filters?.(),...(props.data??[]).flatMap(row=>Object.entries(slots).filter(([key])=>key.startsWith('cell-')).map(([,slot])=>slot?.({row})))])}})`
      if(id==='\0outbound-view-select')return `import {defineComponent,h} from 'vue';export default defineComponent({setup(){return ()=>h('span')}})`
    }} ,vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
  t.after(()=>server.close())
  const {usePiniaAppStore,calls}=await server.ssrLoadModule('\0outbound-view-store')
  const {buttons}=await server.ssrLoadModule('\0outbound-view-button')
  const pinia=createPinia(),store=usePiniaAppStore(pinia)
  const line={id:7,material_id:3,sku:'A',material_name:'样品',unit:'件',quantity:'1.000'}
  const outbound={id:2,warehouse_id:1,warehouse_name:'主仓库',source_kind:'other',reason:'sample',
    note:'现场领用',reference:'',status:'posted',created_at:'2026-10-02',created_by:1,created_by_name:'admin',
    reversal_id:null,reversal_reason:null,purchase_return_id:null,lines:[{...line,physical_lots:[
      {id:8,code:'LEGACY-W1-M3',quantity:'1.000',source_kind:'legacy'}]}]}
  store.warehouseOutbounds=[outbound,{...outbound,id:3,lines:[line]},
    {...outbound,id:4,source_kind:'purchase_return',reason:'purchase_return',status:'draft',approval:{status:'approved'},lines:[line]},
    {...outbound,id:5,source_kind:'purchase_return',reason:'purchase_return',lines:[{
      ...line,physical_lots:[{id:9,code:'R5-L7-P1',quantity:'1.000',source_kind:'receipt'}]}]}]
  const {default:Component}=await server.ssrLoadModule('/src/renderer/src/views/workspace/warehouse/WarehouseOutboundsView.vue')
  let vnode
  const render=async()=>{
    buttons.length=0
    const app=createSSRApp({render:()=>{vnode=h(Component);return vnode}}).use(pinia)
    // 公共日期筛选使用 Naive 浮层，SSR 显式收集样式，避免访问不存在的浏览器 document。
    setupSsrStyles(app)
    return renderToString(app)
  }
  const html=await render()
  assert.match(html,/LEGACY-W1-M3/)
  assert.match(html,/历史未识别/)
  assert.match(html,/普通出库，未指定实物批次/)
  assert.match(html,/R5-L7-P1/)
  assert.equal((html.match(/普通出库，未指定实物批次/g)??[]).length,1)
  // 出库与选批按钮不再出现在列表行内。
  assert.ok(!buttons.some(button=>['确认出库','指定实物批次（可选）'].includes(button.label)))
  // 行内只保留单号和「查看」两个入口，点击都打开同一详情。
  for(const entry of ['查看','#2']){
    calls.length=0
    const button=buttons.find(item=>item.label===entry)
    assert.ok(button,entry)
    await button.click()
    assert.deepEqual(calls.at(-1),['approval',{document_type:'WarehouseOutbound',document_id:2,intent:'execute'}])
  }
  // 统一确认入口移入详情页脚，批准后的草稿才能出库或登记批次。
  store.documentApprovalTarget={document_type:'WarehouseOutbound',document_id:4,intent:'execute'}
  const detail=await render()
  assert.match(detail,/>确认出库</)
  assert.match(detail,/指定实物批次（可选）/)
  assert.equal((detail.match(/指定实物批次（可选）/g)??[]).length,1)
  assert.equal(buttons.filter(button=>button.label==='确认出库').length,1)

  // 核对真实页面接入公共分页、筛选和状态列，且筛选不会重置创建草稿或审批目标。
  store.warehouseOutbounds=Array.from({length:45},(_,index)=>({...outbound,id:index+1,document_no:`CKD-${index+1}`,
    lines:[line,{...line,id:8,material_name:'第二项'},{...line,id:9,material_name:'第三项'}]}))
  const draft=store.otherOutboundForm, target=store.documentApprovalTarget
  const listed=await render()
  assert.match(listed,/另有 1 项物料/)
  assert.match(listed,/app-status-tag--success/)
  const {tableState}=await server.ssrLoadModule('\0outbound-view-table')
  assert.deepEqual(tableState.props.columns.map(column=>column.key),['document','status','operator','source','lines','time','actions'])
  assert.equal(tableState.props.minTableWidth,1410)
  assert.equal(tableState.props.pagination.total,45)
  assert.equal(tableState.props.data.length,20)
  const view=vnode.component.setupState
  tableState.attrs.onPageChange(2,20)
  assert.equal(view.page,2)
  const filters=tableState.slots.filters()[0]
  filters.props['onUpdate:query']('CKD-45')
  // SSR 结束会停止组件侦听器；这里验证事件与筛选连接，翻页重置由真实响应式用例覆盖。
  assert.equal(view.query,'CKD-45')
  assert.equal(view.filtered[0].id,45)
  assert.equal(view.summaryOptions[0].count,45)
  filters.props['onUpdate:filters']({...view.listFilters,source:'scrap'})
  assert.equal(view.filtered.length,0)
  view.statusFilter='cancelled'
  filters.props.onReset()
  assert.equal(view.statusFilter,'all')
  assert.equal(view.total,45)
  assert.equal(store.otherOutboundForm,draft)
  assert.equal(store.documentApprovalTarget,target)
})
