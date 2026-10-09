import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import { parse } from '@vue/compiler-sfc'
import postcss from 'postcss'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createPinia } from 'pinia'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { shortLocalTime } from '../src/renderer/src/utils/formatters.ts'

test('物料摘要不吞占列内余量，窄列可收缩且余项标签保持可见', () => {
 const source=readFileSync(new URL('../src/renderer/src/views/workspace/warehouse/OtherInboundsView.vue',import.meta.url),'utf8')
 const {descriptor}=parse(source)
 const styles=postcss.parse(descriptor.styles.map(style=>style.content).join('\n'))
 const declarations=selector=>{
  const values={}
  styles.walkRules(selector,rule=>rule.walkDecls(decl=>{values[decl.prop]=decl.value}))
  return values
 }
 const preview=declarations('.inbound-material-preview')
 // 不增长才能让标签跟随内容，同时允许文本收缩，保留窄列的省略能力。
 assert.deepEqual(preview.flex.split(/\s+/),['0','1','auto'])
 assert.equal(preview['min-width'],'0')
 // 摘要与余项标签保留明确的 20px 间距；文本仍可收缩，不能挤掉窄列中的标签。
 assert.equal(declarations('.inbound-material-summary').gap,'20px')
 assert.equal(declarations('.inbound-material-more').flex,'none')
 assert.equal(declarations('.inbound-material-text')['text-overflow'],'ellipsis')
})

// 仅替换桌面桥接和渲染外壳；真实页面、公共弹窗与业务事件均参与验证。
const storeSource = `import {defineStore} from 'pinia'; import {ref} from 'vue'
export const usePiniaAppStore=defineStore('inbound-details-test',()=>{
 const otherInboundReopenForms=ref({}), otherInbounds=ref([]), permissions=ref([]), calls=ref([]), fail=ref(false), error=ref(''), documentApprovalRecord=ref(null)
 const update=(id,status)=>{calls.value.push([status,id]); if(fail.value){error.value='操作失败';return}
 otherInbounds.value=otherInbounds.value.map(item=>item.id===id?{...item,status}:item)}
 return { error,permissions,calls,fail,documentApprovalRecord,
 notice:ref(''),busy:ref(false),connectionLost:ref(false),materials:ref([]),warehouses:ref([]),
 otherInbounds,otherInboundReopenForms,otherInboundForm:ref({lines:[{material_id:99,quantity:'7'}]}),otherInboundReversalReasons:ref({}),
 initialDetailId:ref(0),can:key=>permissions.value.includes(key),localTime:value=>value,
 prepareOtherInboundReopen(id){calls.value.push(['reopen',id]);otherInboundReopenForms.value[id]={lines:[]};return true},
 createOtherInbound(){throw Error('查看详情不应创建')},async postOtherInbound(id){update(id,'posted')},
 async cancelOtherInbound(id){update(id,'cancelled')},async reverseOtherInbound(id){calls.value.push(['reverse',id])},
 async openDocumentApproval(target){calls.value.push(['approval',target]);documentApprovalRecord.value={status:'approved',reversal_reason:'已批准原因'};return true},
 closeDocumentApproval(){calls.value.push(['closeApproval'])}
 }
})`

const tableSource = `import {defineComponent,h} from 'vue'
export const tables=[]
export default defineComponent({props:['data','columns','emptyText','pagination'],setup(p,{slots,attrs}){tables.push({props:p,attrs});return()=>h('section',[
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
   if(id.endsWith('/OtherInboundActions.vue'))return code.replace("'naive-ui'","'virtual:inbound-action-controls'")
   // 可设置初始选中 ID 来展开真实弹窗；正常打开事件另行直接触发验证。
   if(id.endsWith('/OtherInboundsView.vue'))return code.replace('const detailInboundId = ref(0)','const detailInboundId = ref(store.initialDetailId)').replace("'naive-ui'","'virtual:inbound-detail-modal'")
   if(id.endsWith('/WorkspaceDocumentDialog.vue'))return code.replace("'naive-ui'","'virtual:inbound-detail-modal'")
  },
  resolveId(id,importer){
   if(id==='virtual:inbound-action-controls')return '\0inbound-action-controls'
   if(id==='virtual:inbound-detail-modal')return '\0inbound-detail-modal'
   if(!importer?.includes('/src/renderer/'))return
   if(id.endsWith('/store/app-store')&&importer.includes('OtherInboundsView'))return '\0inbound-detail-store'
   if(id.endsWith('/DocumentApprovalDialog.vue'))return '\0inbound-approval-placeholder'
   if(id.endsWith('/WorkspaceTable.vue'))return '\0inbound-detail-table'
   if(id.endsWith('/AppButton.vue'))return '\0inbound-detail-button'
   if(id==='naive-ui'&&importer.includes('OtherInboundActions'))return '\0inbound-action-controls'
   if(id==='naive-ui'&&(importer.includes('OtherInboundsView')||importer.includes('WorkspaceDocumentDialog')))return '\0inbound-detail-modal'
  },load(id){if(id==='\0inbound-action-controls')return `import {defineComponent,h} from 'vue'; export const NDropdown=defineComponent({setup(p,{slots}){return()=>h('span',slots.default?.())}})`;if(id==='\0inbound-approval-placeholder')return 'export default {render(){return null}}';return {'\0inbound-detail-store':storeSource,'\0inbound-detail-table':tableSource,
   '\0inbound-detail-button':buttonSource,'\0inbound-detail-modal':modalSource}[id]}
 },vue()],server:{middlewareMode:true,hmr:false},optimizeDeps:{noDiscovery:true,include:[]},appType:'custom'})
 t.after(()=>server.close())
 const {usePiniaAppStore}=await server.ssrLoadModule('\0inbound-detail-store')
 const pinia=createPinia(),store=usePiniaAppStore(pinia)
 const {default:View}=await server.ssrLoadModule('/src/renderer/src/views/workspace/warehouse/OtherInboundsView.vue')
 const {buttons}=await server.ssrLoadModule('\0inbound-detail-button')
 const {tables}=await server.ssrLoadModule('\0inbound-detail-table')
 let vnode
 const render=()=>{tables.length=0;buttons.length=0;vnode=h(View);return renderToString(createSSRApp({render:()=>vnode}).use(pinia))}
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
 assert.equal(cell('time'),shortLocalTime(inbound.created_at))
 // 核对真实页面配置，时间须紧挨操作列并显式固定，不能只是移动了表头文案。
 assert.deepEqual(vnode.component.setupState.columns.map(column=>column.key), ['document','status','operator','source','lines','time','actions'])
 assert.equal(vnode.component.setupState.columns.find(column=>column.key==='time').fixed, 'right')
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
 // 外侧隐藏参考号但仍可搜索；两条摘要不丢失隐藏物料的检索及详情内容。
 store.initialDetailId=0
 const many={...structuredClone(inbound),reference:'HIDDEN-REF',lines:Array.from({length:4},(_,i)=>({
  ...inbound.lines[0],id:70+i,material_name:`明细物料${i+1}`
 }))}
 store.otherInbounds=[many]
 html=await render()
 assert.doesNotMatch(cell('source'),/HIDDEN-REF/)
 assert.equal((cell('lines').match(/<li\b/g)??[]).length,2)
 assert.match(cell('lines'),/明细物料1/)
 assert.match(cell('lines'),/明细物料2/)
 assert.match(cell('lines'),/\+2 项/)
 // 隐藏项只进入悬停说明，不能增加列表的可见行数。
 assert.doesNotMatch(cell('lines').replace(/<[^>]*>/g,''),/明细物料3|明细物料4/)
 assert.match(cell('lines'),/title="明细物料3[^"]*明细物料4/)
 const setup=vnode.component.setupState
 for(const query of ['HIDDEN-REF','明细物料4']) {
  setup.query=query
  assert.equal(setup.filtered.length,1)
  assert.equal(setup.filtered[0].id,many.id)
 }
 setup.query='不存在的参考号'
 assert.equal(setup.filtered.length,0)
 for(const length of [0,1,2,3]) {
  store.otherInbounds=[{...many,lines:many.lines.slice(0,length)}]
  html=await render()
  assert.equal((cell('lines').match(/<li\b/g)??[]).length,Math.min(length,2))
  if(length<=2)assert.doesNotMatch(cell('lines'),/inbound-material-more/)
  else assert.match(cell('lines'),/\+1 项/)
 }
 store.initialDetailId=3
 store.otherInbounds=[many]
 html=await render()
 for(const value of ['HIDDEN-REF','明细物料3','明细物料4'])assert.ok(html.includes(value))
 store.initialDetailId=0
 store.otherInbounds=[structuredClone(inbound)]
 html=await render()
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
 assert.doesNotMatch(html,/冲销原因|冲销记录/)
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
 // 冲销原因只出现在单号打开的详情，不占用列表操作栏；空历史原因使用占位符。
 assert.doesNotMatch(cell('actions'),/重复录入|冲销：/)
 const detailHtml=()=>html.slice(html.indexOf('data-modal='))
 assert.match(detailHtml(),/冲销原因<\/span><strong[^>]*>重复录入<\/strong>/)
 assert.equal((html.match(/重复录入/g)??[]).length,1)
 store.otherInbounds=[{...store.otherInbounds[0],reversal_reason:null}]
 html=await render()
 assert.match(detailHtml(),/冲销原因<\/span><strong[^>]*>—<\/strong>/)
 store.otherInbounds=[{...store.otherInbounds[0],reversal_reason:'重复录入'}]
 store.initialDetailId=0
 html=await render()
 assert.doesNotMatch(html,/重复录入|冲销原因|冲销记录/)
 store.initialDetailId=3
 store.otherInbounds=[{...inbound,lines:[]}]
 assert.match(await render(),/此单据暂无物料明细/)
 store.otherInbounds=[]
 assert.equal(vnode.component.setupState.detailInbound,null)
 assert.doesNotMatch(await render(),/data-modal=/)
 assert.equal(JSON.stringify(store.otherInboundForm),draft)
 // 主列表真正绑定分页，搜索覆盖完整快照；切页不动详情和新建草稿。
 store.initialDetailId=0
 store.otherInbounds=Array.from({length:45},(_,i)=>({...structuredClone(inbound),id:i+1,document_no:`分页单-${i+1}`}))
 await render()
 const pagination=vnode.component.setupState
 assert.equal(pagination.rows.length,20)
 assert.equal(pagination.total,45)
 assert.deepEqual(tables[0].props.pagination,{page:1,pageSize:20,total:45})
 tables[0].attrs.onPageChange(3,20)
 assert.deepEqual(pagination.rows.map(item=>item.id),[41,42,43,44,45])
 pagination.query='分页单-45'
 assert.equal(pagination.total,1)
 // SSR 结束会停止组件 watcher；搜索及删末页自动回退由 local-pagination 测试验证。
 pagination.changePage(1,20)
 assert.deepEqual(pagination.rows.map(item=>item.id),[45])
 pagination.query=''
 pagination.changePage(2,10)
 assert.equal(pagination.page,1)
 assert.equal(pagination.rows.length,10)
 pagination.changePage(5,10)
 store.otherInbounds=store.otherInbounds.slice(0,40)
 pagination.changePage(5,10)
 assert.equal(pagination.page,4)
 assert.equal(store.otherInbounds.length,40)
 assert.equal(JSON.stringify(store.otherInboundForm),draft)
 store.initialDetailId=3
 // 概览按钮驱动真实页面筛选，关键词保留，计数不随列表过滤而减少。
 store.initialDetailId=0
 store.otherInbounds=[structuredClone(inbound),{...inbound,id:4,status:'posted'},
  {...inbound,id:5,status:'cancelled'},{...inbound,id:6,status:'posted',reversal_id:8}]
 await render()
 const overview=vnode.component.setupState
 assert.deepEqual(overview.summary,{all:4,pending:1,processed:1,cancelled:1,reversed:1})
 const summaryButton=label=>buttons.find(button=>button.attrs['aria-label']===label)
 summaryButton('已处理，1 条').attrs.onClick()
 assert.equal(overview.statusFilter,'processed')
 assert.deepEqual(overview.filtered.map(item=>item.id),[4])
 overview.query='不匹配'
 assert.equal(overview.filtered.length,0)
 assert.equal(overview.summary.all,4)
 // SSR 卸载后子组件 props 不再刷新；回到全部的事件交互由公共组件和浏览器验证。
 overview.statusFilter='all'
 assert.equal(overview.statusFilter,'all')
 assert.equal(overview.query,'不匹配')
 overview.query=''
 summaryButton('已冲销，1 条').attrs.onClick()
 assert.deepEqual(overview.filtered.map(item=>item.id),[6])
 assert.equal(JSON.stringify(store.otherInboundForm),draft)
 store.initialDetailId=3
 // 详情操作复用真实按钮和入口，验证目标 ID、最新快照及失败后草稿隔离。
 assert.deepEqual(store.calls, [])
 store.busy=false
 store.connectionLost=false
 store.permissions=['other_inbound.post','other_inbound.cancel','other_inbound.reverse']
 store.initialDetailId=3
 const approved={...structuredClone(inbound),approval:{status:'approved'}}
 const flush=()=>new Promise(resolve=>setImmediate(resolve))
 const detailButton=label=>buttons.filter(button=>text(button.content)===label).at(-1)
 store.otherInbounds=[approved]
 html=await render()
 assert.equal(buttons.filter(button=>text(button.content)==='确认入库').length,2)
 assert.ok(html.indexOf('单据操作',html.indexOf('data-modal='))>html.indexOf('物料明细',html.indexOf('data-modal=')))
 detailButton('确认入库').attrs.onClick()
 await flush()
 assert.deepEqual(store.calls.at(-1),['posted',3])
 assert.equal(vnode.component.setupState.detailInbound.status,'posted')
 assert.equal(vnode.component.setupState.detailInboundId,3)
 assert.equal(JSON.stringify(store.otherInboundForm),draft)

 // 失败不关闭详情，处理期间、离线和过期按钮都不能触发第二次写入。
 store.otherInbounds=[approved]
 store.fail=true
 await render()
 const post=detailButton('确认入库')
 post.attrs.onClick(); post.attrs.onClick()
 await flush()
 assert.equal(store.calls.filter(call=>call[0]==='posted').length,2)
 assert.equal(vnode.component.setupState.detailInbound.status,'draft')
 assert.equal(vnode.component.setupState.detailInboundId,3)
 assert.equal(store.error,'操作失败')
 const count=store.calls.length
 for(const flag of ['busy','connectionLost']) {
  store[flag]=true;post.attrs.onClick();await flush();store[flag]=false
  assert.equal(store.calls.length,count)
 }
 store.otherInbounds=[{...approved,status:'cancelled'}]
 post.attrs.onClick();await flush()
 assert.equal(store.calls.length,count)
 store.otherInbounds=[approved]
 store.permissions=[]
 post.attrs.onClick();await flush()
 assert.equal(store.calls.length,count)

 store.fail=false
 store.permissions=['other_inbound.post','other_inbound.cancel','other_inbound.reverse']
 await render()
 detailButton('登记实物批次（可选）').attrs.onClick();await flush()
 assert.equal(vnode.component.setupState.activeInboundId,3)
 assert.equal(vnode.component.setupState.lotDrafts[0].inbound_line_id,7)
 assert.equal(store.calls.length,count)
 detailButton('审批记录 / 送审').attrs.onClick();await flush()
 assert.deepEqual(store.calls.at(-1),['approval',{document_type:'WarehouseInbound',document_id:3,intent:'execute'}])
 store.otherInbounds=[structuredClone(inbound)]
 await render()
 detailButton('取消').attrs.onClick();await flush()
 assert.equal(vnode.component.setupState.detailInbound.status,'cancelled')
 store.otherInbounds=[{...inbound,status:'posted',reversal_approval:{status:'approved'}}]
 await render()
 detailButton('执行冲销').attrs.onClick();await flush()
 assert.deepEqual(store.calls.slice(-3),[
  ['approval',{document_type:'WarehouseInbound',document_id:3,intent:'reverse'}],['closeApproval'],['reverse',3]
 ])
 assert.equal(store.otherInboundReversalReasons[3],'已批准原因')
 assert.equal(JSON.stringify(store.otherInboundForm),draft)

 // 列表与详情都能重开，点击仅打开新建表单，不修改原单或调用取消/冲销。
 store.permissions=['other_inbound.create']
 store.otherInbounds=[{...inbound,status:'cancelled'}]
 await render()
 assert.equal(buttons.filter(button=>text(button.content)==='重开为新单').length,2)
 const reopen=detailButton('重开为新单')
 reopen.attrs.onClick();await flush()
 assert.deepEqual(store.calls.at(-1),['reopen',3])
 assert.equal(vnode.component.setupState.reopenSourceId,3)
 assert.equal(vnode.component.setupState.showForm,true)
 assert.equal(vnode.component.setupState.detailInboundId,0)
 assert.equal(store.otherInbounds[0].status,'cancelled')
 assert.equal(JSON.stringify(store.otherInboundForm),draft)
 const before=store.calls.length
 store.otherInbounds=[inbound]
 reopen.attrs.onClick();await flush()
 assert.equal(store.calls.length,before)

})
