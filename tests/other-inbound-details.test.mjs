import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createPinia } from 'pinia'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'

// 仅替换桌面桥接和渲染外壳；真实页面、公共弹窗与业务事件均参与验证。
const storeSource = `import {defineStore} from 'pinia'; import {ref} from 'vue'
export const usePiniaAppStore=defineStore('inbound-details-test',()=>({
 error:ref(''),notice:ref(''),busy:ref(false),connectionLost:ref(false),materials:ref([]),warehouses:ref([]),
 otherInbounds:ref([]),otherInboundForm:ref({lines:[{material_id:99,quantity:'7'}]}),otherInboundReversalReasons:ref({}),
 initialDetailId:ref(0),can:()=>false,localTime:value=>value,
 createOtherInbound(){throw Error('查看详情不应创建')},postOtherInbound(){throw Error('查看详情不应确认')},
 cancelOtherInbound(){throw Error('查看详情不应取消')},reverseOtherInbound(){throw Error('查看详情不应冲销')}
}))`
const tableSource = `import {defineComponent,h} from 'vue'
export default defineComponent({props:['data','columns','emptyText'],setup(p,{slots}){return()=>h('section',[
 slots.heading?.(),slots.actions?.(),slots.filters?.(),slots.beforeTable?.(),
 h('header',p.columns.map(c=>h('span',{'data-column':c.key},c.title))),
 ...p.data.map(row=>h('article',{'data-row':row.id},p.columns.map(c=>h('div',{'data-cell':c.key},slots['cell-'+c.key]?.({row}))))),p.data.length?null:h('p',p.emptyText)
])}})`
const buttonSource = `import {defineComponent,h} from 'vue'
export const buttons=[]
export default defineComponent({props:['type','disabled','variant'],setup(p,{slots,attrs}){return()=>{
 const content=slots.default?.();buttons.push({props:p,attrs,content});return h('button',{...attrs,type:p.type,disabled:p.disabled},content)
}}})`
const modalSource = `import {defineComponent,h} from 'vue'
export const NModal=defineComponent({props:['show','title'],setup(p,{slots,attrs}){return()=>p.show?h('section',{'data-modal':p.title},slots.default?.()):null}})
export const NDatePicker=NModal`

const inbound = {
 id:3,document_no:'QTRK-20261007-000003',status:'draft',reason:'gift',note:'历史说明',reference:'REF-3',
 warehouse_name:'主仓库',created_by_name:'建单人',created_at:'2026-10-07T06:00:00Z',
 posted_at:null,posted_by_name:null,cancelled_at:null,reversal_id:null,
 lines:[{id:7,material_id:1,sku:'OLD-SKU',material_name:'历史物料名称',quantity:'2.125',unit:'件',physical_lots:[]}]
}

const text = nodes => (nodes ?? []).map(n => typeof n.children === 'string' ? n.children
 : Array.isArray(n.children) ? text(n.children) : '').join('')

test('其他入库各状态详情沿用历史字段，离线与只读账号可查看，关闭及刷新不影响草稿', async t => {
 const server=await createServer({configFile:false,plugins:[{
  name:'inbound-detail-fixtures',enforce:'pre',
  transform(code,id){
   // 可设置初始选中 ID 来展开真实弹窗；正常打开事件另行直接触发验证。
   if(id.endsWith('/OtherInboundsView.vue'))return code.replace('const detailInboundId = ref(0)','const detailInboundId = ref(store.initialDetailId)').replace("'naive-ui'","'virtual:inbound-detail-modal'")
   if(id.endsWith('/WorkspaceDocumentDialog.vue'))return code.replace("'naive-ui'","'virtual:inbound-detail-modal'")
  },
  resolveId(id,importer){
   if(id==='virtual:inbound-detail-modal')return '\0inbound-detail-modal'
   if(!importer?.includes('/src/renderer/'))return
   if(id.endsWith('/store/app-store')&&importer.includes('OtherInboundsView'))return '\0inbound-detail-store'
   if(id.endsWith('/DocumentApprovalDialog.vue'))return '\0inbound-approval-placeholder'
   if(id.endsWith('/WorkspaceTable.vue'))return '\0inbound-detail-table'
   if(id.endsWith('/AppButton.vue'))return '\0inbound-detail-button'
   if(id==='naive-ui'&&(importer.includes('OtherInboundsView')||importer.includes('WorkspaceDocumentDialog')))return '\0inbound-detail-modal'
  },load(id){if(id==='\0inbound-approval-placeholder')return 'export default {render(){return null}}';return {'\0inbound-detail-store':storeSource,'\0inbound-detail-table':tableSource,
   '\0inbound-detail-button':buttonSource,'\0inbound-detail-modal':modalSource}[id]}
 },vue()],server:{middlewareMode:true,hmr:false},optimizeDeps:{noDiscovery:true,include:[]},appType:'custom'})
 t.after(()=>server.close())
 const {usePiniaAppStore}=await server.ssrLoadModule('\0inbound-detail-store')
 const pinia=createPinia(),store=usePiniaAppStore(pinia)
 const {default:View}=await server.ssrLoadModule('/src/renderer/src/views/workspace/warehouse/OtherInboundsView.vue')
 const {buttons}=await server.ssrLoadModule('\0inbound-detail-button')
 let vnode
 const render=()=>{buttons.length=0;vnode=h(View);return renderToString(createSSRApp({render:()=>vnode}).use(pinia))}
 store.otherInbounds=[structuredClone(inbound)]
 const draft=JSON.stringify(store.otherInboundForm)
 store.connectionLost=true
 store.busy=true
 let html=await render()
 // 核对真实列插槽，防止元信息再次挤回单号列；只读且断线时单号仍能打开对应记录。
 for(const [key,title] of [['document','单据号'],['time','时间'],['status','状态'],['operator','处理人']]) {
  assert.ok(html.includes(`<span data-column="${key}">${title}</span>`),title)
 }
 const cell=key=>html.match(new RegExp(`<div data-cell="${key}">([\\s\\S]*?)</div>`))?.[1]
 assert.match(cell('document'),/QTRK-20261007-000003/)
 assert.doesNotMatch(cell('document'),/建单人|2026-10-07T06:00:00Z|待送审/)
 assert.equal(cell('time'),inbound.created_at)
 // 状态标签保留可读文案；颜色区分业务阶段，装饰圆点对读屏隐藏。
 const assertStatus=(label,tone)=>{
  const content=cell('status')
  assert.equal(content.replace(/<[^>]*>/g,'').trim(),label)
  assert.ok(content.includes(`app-status-tag--${tone}`))
  assert.match(content,/class="app-status-tag__dot" aria-hidden="true"/)
 }
 assertStatus('待送审','pending')
 assert.equal(cell('operator'),'建单人')
 assert.doesNotMatch(cell('actions'),/查看详情/)
 const view=buttons.find(b=>text(b.content)===inbound.document_no)
 assert.equal(view.props.type,'button')
 assert.equal(view.props.variant,'text')
 assert.equal(view.attrs['aria-label'],`查看单据 ${inbound.document_no} 详情`)
 assert.equal(view.props.disabled,undefined)
 view.attrs.onClick()
 assert.equal(vnode.component.setupState.detailInboundId,3)
 assert.equal(vnode.component.setupState.detailInbound.id,3)
 assert.equal(JSON.stringify(store.otherInboundForm),draft)
 store.initialDetailId=3
 html=await render()
 for(const value of ['其他入库详情','QTRK-20261007-000003','OLD-SKU','历史物料名称','2.125','历史说明','REF-3','建单人','待送审','尚未登记实物批次'])assert.ok(html.includes(value),value + ': ' + html)
 // 列表与详情使用同一个公共标签，防止详情退回无高亮文本。
 assert.equal((html.match(/app-status-tag--pending/g) ?? []).length, 2)
 assert.doesNotMatch(html,/添加物料|保存草稿|登记批次并确认|type="submit"/)
 const close=buttons.find(b=>text(b.content)==='关闭')
 assert.equal(close.props.disabled,false)
 close.attrs.onClick()
 assert.equal(vnode.component.setupState.detailInboundId,0)
 assert.equal(JSON.stringify(store.otherInboundForm),draft)
 // 多行时按点击行的内部 ID 选中，避免展示首行或把单号作为业务 ID。
 store.initialDetailId=0
 store.otherInbounds=[structuredClone(inbound),{...structuredClone(inbound),id:4,document_no:'QTRK-20261007-000004'}]
 await render()
 buttons.find(b=>text(b.content)==='QTRK-20261007-000004').attrs.onClick()
 assert.equal(vnode.component.setupState.detailInbound.id,4)
 assert.equal(JSON.stringify(store.otherInboundForm),draft)
 store.initialDetailId=3
 // 审批进度须在独立状态列保留；详情入口不受当前单据状态影响。
 for(const [status,label,tone] of [['submitted','审批中','info'],['approved','已批准，待入库','ready'],['rejected','已驳回','danger'],['withdrawn','已撤回','neutral'],['executed','已执行','success']]) {
  store.otherInbounds=[{...inbound,approval:{status}}]
  html=await render()
  assertStatus(label,tone)
  assert.ok(buttons.some(b=>text(b.content)===inbound.document_no))
 }
 // 页面刷新时跟随最新保存快照，避免详情固定显示旧状态；单据消失后自动不再展示。
 store.otherInbounds=[{...inbound,status:'posted',posted_at:'确认时间',posted_by_name:'确认人',lines:[{
  ...inbound.lines[0],physical_lots:[{id:1,code:'LOT-3',quantity:'2.125',supplier_lot:'SUP-1',manufactured_on:'2026-09-01',expires_on:'2027-09-01'}]
 }]}]
 html=await render()
 assertStatus('已入库','success')
 for(const value of ['已入库','确认时间','确认人','LOT-3','SUP-1','2026-09-01','2027-09-01'])assert.ok(html.includes(value),value + ': ' + html)
 store.otherInbounds=[{...inbound,status:'posted'}]
 assert.match(await render(),/普通入库，未登记实物批次/)
 store.otherInbounds=[{...inbound,status:'cancelled',approval:{status:'approved'},cancelled_at:'取消时间'}]
 html=await render()
 assert.match(html,/取消时间/)
 assertStatus('已取消','neutral')
 store.otherInbounds=[{...inbound,status:'posted',approval:{status:'executed'},reversal_id:8,reversal_reason:'重复录入',reversed_at:'冲销时间',reversed_by_name:'冲销人'}]
 html=await render()
 assertStatus('已冲销','reversed')
 for(const value of ['已冲销','重复录入','冲销时间','冲销人'])assert.ok(html.includes(value),value + ': ' + html)
 store.otherInbounds=[{...inbound,lines:[]}]
 assert.match(await render(),/此单据暂无物料明细/)
 store.otherInbounds=[]
 assert.equal(vnode.component.setupState.detailInbound,null)
 assert.doesNotMatch(await render(),/data-modal=/)
 assert.equal(JSON.stringify(store.otherInboundForm),draft)
})
