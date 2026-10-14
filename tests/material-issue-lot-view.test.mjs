import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createSSRApp,h} from 'vue'
import {createPinia} from 'pinia'
import {renderToString} from '@vue/server-renderer'
import {createServer} from 'vite'
import vue from '@vitejs/plugin-vue'

const storeModule=`import {ref} from 'vue';import {defineStore} from 'pinia';
export const calls=[];
export const usePiniaAppStore=defineStore('issue-view',()=>{
const materialIssues=ref([]),documentApprovalTarget=ref(null);return {
materialIssues,documentApprovalTarget,documentApprovalRecord:ref(null),
error:ref(''),notice:ref(''),busy:ref(false),connectionLost:ref(false),
workOrders:ref([]),warehouses:ref([]),selectedIssueOrder:ref(null),
materialIssueForm:ref({work_order_id:0,warehouse_id:1,reference:'',lines:[]}),
can:()=>true,localTime:value=>value,selectIssueOrder(){},createMaterialIssue(){},
loadAvailableMaterialIssueLots(){},postMaterialIssue(){},cancelMaterialIssue(){},reverseMaterialIssue(){},selectReturnIssue(){},
openDocumentApproval(target){calls.push(['approval',target]);documentApprovalTarget.value=target;return true},
closeDocumentApproval(){documentApprovalTarget.value=null}}});`
const buttonModule=`import {defineComponent,h} from 'vue';export const buttons=[];
export default defineComponent({props:['disabled'],setup(p,{slots,attrs}){return()=>{
 const children=slots.default?.();const label=(children??[]).map(v=>typeof v.children==='string'?v.children:'').join('').trim();
 buttons.push({label,disabled:p.disabled,click:attrs.onClick});return h('button',attrs,children)}}});`

test('生产领料显示批次证据、旧单差额和选批确认入口',async t=>{
  const server=await createServer({configFile:false,plugins:[{name:'issue-view-fixture',enforce:'pre',
    resolveId(id,importer){
      if(importer?.includes('/views/workspace/production/MaterialIssuesView')
          && id.endsWith('/store/app-store'))return '\0issue-view-store'
      if(id.endsWith('/DocumentApprovalDialog.vue'))return '\0approval-dialog-stub'
      if(id.endsWith('/WorkspaceTable.vue'))return '\0issue-view-table'
      if(id.endsWith('/WorkspaceSelect.vue'))return '\0issue-view-select'
      if(id.endsWith('/AppButton.vue'))return '\0issue-view-button'
    },load(id){
      if(id==='\0issue-view-store')return storeModule
      if (id === '\0approval-dialog-stub') return `export default {render(){return this.$slots.footerActions?.()??null}}`
      if(id==='\0issue-view-button')return buttonModule
      if(id==='\0issue-view-table')return `import {defineComponent,h} from 'vue';export default defineComponent({props:{data:Array},setup(props,{slots}){return ()=>h('section',[
        ...(props.data??[]).flatMap(row=>Object.entries(slots).filter(([key])=>key.startsWith('cell-')).map(([,slot])=>slot?.({row})))])}})`
      if(id==='\0issue-view-select')return `import {defineComponent,h} from 'vue';export default defineComponent({setup(){return ()=>h('span')}})`
    }},vue()],optimizeDeps:{noDiscovery:true,include:[]},
    server:{middlewareMode:true,hmr:false},appType:'custom'})
  t.after(()=>server.close())
  const {usePiniaAppStore,calls}=await server.ssrLoadModule('\0issue-view-store')
  const {buttons}=await server.ssrLoadModule('\0issue-view-button')
  const pinia=createPinia()
  const store=usePiniaAppStore(pinia)
  const line={id:7,work_order_line_id:5,component_material_id:3,sku:'A',material_name:'组件',
    unit:'件',quantity:'1.000',returned_quantity:'0',returnable_quantity:'1.000'}
  const issue={id:2,work_order_id:1,warehouse_id:1,warehouse_name:'主仓库',
    reference:'',status:'posted',created_at:'2026-10-03',created_by_name:'admin',lines:[
      {...line,physical_lots:[{id:8,code:'LEGACY-W1-M3',quantity:'1.000',source_kind:'legacy'}]}]}
  store.materialIssues=[issue,{...issue,id:3,lines:[{...line,physical_lots:[]}]},
    {...issue,id:5,status:'reversed',reversal_reason:'错误确认',reversed_at:'2026-10-03'},
    {...issue,id:4,status:'draft',approval:{status:'approved'},lines:[{...line,physical_lots:[]}]}]
  const {default:Component}=await server.ssrLoadModule(
    '/src/renderer/src/views/workspace/production/MaterialIssuesView.vue')
  const render=async()=>{buttons.length=0;return renderToString(createSSRApp({render:()=>h(Component)}).use(pinia))}
  const html=await render()
  assert.match(html,/LEGACY-W1-M3/)
  assert.match(html,/历史未识别/)
  assert.match(html,/普通确认未指定实物批次/)
  assert.match(html,/已冲销/)
  assert.match(html,/冲销原因：错误确认/)
  assert.equal((html.match(/普通确认未指定实物批次/g)??[]).length,1)
  // 领料与选批按钮不再出现在列表行内。
  assert.ok(!buttons.some(button=>['确认领料','指定实物批次（可选）'].includes(button.label)))
  // 行内只保留单号和「查看」两个入口，点击都打开同一详情。
  for(const entry of ['查看','#2']){
    calls.length=0
    const button=buttons.find(item=>item.label===entry)
    assert.ok(button,entry)
    await button.click()
    assert.deepEqual(calls.at(-1),['approval',{document_type:'MaterialIssue',document_id:2,intent:'execute'}])
  }
  // 选批确认入口移入详情页脚，批准后的草稿才能继续领料。
  store.documentApprovalTarget={document_type:'MaterialIssue',document_id:4,intent:'execute'}
  const detail=await render()
  assert.match(detail,/指定实物批次（可选）/)
  assert.equal(buttons.filter(button=>button.label==='确认领料').length,1)
})
