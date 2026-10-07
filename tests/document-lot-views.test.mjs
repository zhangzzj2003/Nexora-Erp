import assert from 'node:assert/strict'
import {readFile} from 'node:fs/promises'
import {test} from 'node:test'
import {createSSRApp,h} from 'vue'
import {renderToString} from '@vue/server-renderer'
import {createPinia} from 'pinia'
import {createServer} from 'vite'
import vue from '@vitejs/plugin-vue'
import {lotViewCases,documentLotFixture} from './fixtures/document-lot-ui.mjs'

// 真实页面使用完整初始 Pinia 状态，只替换网络操作与控件绘制，覆盖每一种单据的适配。
const methods=['postOtherInbound','postReceipt','postWarehouseOutbound','postTransfer','postStocktake','postStockAdjustment',
  'postShipment','postSalesReturn','postMaterialIssue','postMaterialReturn','postProductionCompletion',
  'loadAvailableOutboundLots','loadAvailableTransferLots','loadAvailableStocktakeLots','loadAvailableAdjustmentLots',
  'loadAvailableShipmentLots','loadAvailableSalesReturnLots','loadAvailableMaterialIssueLots','loadAvailableMaterialReturnLots']
const storeModule=`import {defineStore,storeToRefs} from 'pinia';import {ref} from 'vue';import {createAppState} from '/src/renderer/src/store/state.ts';
export const fixture={options:null,sent:[],fail:false};
export const usePiniaAppStore=defineStore('all-document-lot-tests',()=>{
 const state=createAppState();const actions={can:()=>true,localTime:v=>v};
 for(const name of ${JSON.stringify(methods)})actions[name]=async(...args)=>{
  if(name.startsWith('loadAvailable'))return fixture.options;
  fixture.sent.push({name,args});if(fixture.fail)state.error.value='模拟保存失败';
 };
 return {...state,...actions,selectedCompletionOrder:ref(null)}
});export const useAppStore=()=>{const store=usePiniaAppStore();return {...storeToRefs(store),...Object.fromEntries(Object.entries(store).filter(([,v])=>typeof v==='function'))}};`
const tableStub=`import {defineComponent,h} from 'vue';export default defineComponent({props:['data','columns'],setup(p,{slots}){return ()=>h('table',[slots.actions?.(),slots.filters?.(),...(p.data??[]).map(row=>h('tr',p.columns.map(c=>h('td',slots['cell-'+c.key]?.({row})))) )])}})`
const modalStub=`import {defineComponent,h} from 'vue';export const NModal=defineComponent({props:['show','title'],setup(p,{slots}){return ()=>p.show?h('section',[h('h2',p.title),slots.default?.(),slots.footer?.()]):null}});export const NDatePicker=defineComponent({setup(){return()=>h('input')}});`

test('全部十一类单据接入公共批次弹窗并保留原确认载荷、失败草稿和数量约束',async t=>{
 const server=await createServer({configFile:false,plugins:[{name:'all-lot-view-tests',enforce:'pre',
  transform(code,id){if(id.endsWith('.vue'))return code.replace(/'naive-ui'/g,"'virtual:all-lot-naive'")},
  resolveId(id,importer){
   if(id==='virtual:all-lot-naive')return '\0all-lot-naive'
   // 关联查询独立测试，此处只验证十一类批次执行，不加载真实应用 store。
   if(id.endsWith('/ProductionAssociationDialog.vue'))return '\0all-lot-association'
   if((importer?.includes('/views/workspace/')||importer?.includes('/components/workspace/DocumentApprovalDialog'))&&id.endsWith('/store/app-store'))return '\0all-lot-store'
   if(id.endsWith('/WorkspaceTable.vue'))return '\0all-lot-table'
   if(id.endsWith('/WorkspaceSelect.vue'))return '\0all-lot-select'
   if(id.endsWith('/AppButton.vue'))return '\0all-lot-button'
   if(id.endsWith('/AppInput.vue'))return '\0all-lot-input'
  },load(id){return {'\0all-lot-association':'export default {render:()=>null}','\0all-lot-store':storeModule,'\0all-lot-table':tableStub,'\0all-lot-naive':modalStub,
   '\0all-lot-button':`import {defineComponent,h} from 'vue';export default defineComponent({props:['type','disabled'],setup(p,{slots,attrs}){return()=>h('button',{...attrs,type:p.type,disabled:p.disabled},slots.default?.())}})`,
   '\0all-lot-input':`import {defineComponent,h} from 'vue';export default defineComponent({props:['modelValue','disabled'],setup(p,{attrs}){return()=>h('input',{...attrs,value:p.modelValue,disabled:p.disabled})}})`,
   '\0all-lot-select':`import {defineComponent,h} from 'vue';export default defineComponent({props:['options'],setup(p){return()=>h('span',(p.options??[]).map(o=>o.label).join(' / '))}})`}[id]}
 },vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
 t.after(()=>server.close())
 const {usePiniaAppStore,fixture}=await server.ssrLoadModule('\0all-lot-store')
 for(const config of lotViewCases){
  const seed=documentLotFixture(config),pinia=createPinia(),store=usePiniaAppStore(pinia)
  // 已接入审批的入库批次操作属于批准后的仓库执行，不能让布局测试绕过新审批前提。
  if(['otherInbounds','receipts','warehouseOutbounds','transfers','stocktakes','stockAdjustments'].includes(seed.state))seed.record.approval={status:'approved'}
  store[seed.state]=[seed.record];fixture.options=seed.options;fixture.sent=[];fixture.fail=true
  const {default:View}=await server.ssrLoadModule('/src/renderer/src/views/workspace/'+seed.file)
  const originalSetup=View.setup;let bindings
  const OpenView={...View,async setup(props,context){bindings=originalSetup(props,context);await bindings.startLotPost(seed.record);return bindings}}
  const app=createSSRApp({render:()=>h(OpenView)}).use(pinia)
  // 路由链接与批次适配无关，只在测试中保留其文本，避免无关的组件告警。
  app.component('RouterLink',{setup(_props,{slots}){return()=>h('a',slots.default?.())}})
  const html=await renderToString(app)
  assert.match(html,new RegExp(config[3]),seed.file)
  assert.match(html,/DEMO-20261007-000001/,seed.file)
  assert.match(html,/已分配/,seed.file)
  assert.match(html,/数量已核对/,seed.file)
  const draft=seed.lineKey?bindings.lotDrafts.value[0].lots:bindings.lotDrafts.value
  if('lot_id' in draft[0]&&draft[0].lot_id===0)draft[0].lot_id=8
  // 用真实可提交的日期和来源批号核对界面调整后仍发送原业务协议。
  if('manufactured_on' in draft[0]){
   draft[0].manufactured_on='2026-10-01';draft[0].expires_on='2027-10-01'
   if('supplier_lot' in draft[0])draft[0].supplier_lot=' SUP-42 '
  }
  assert.equal(bindings.lotIssue.value,'',seed.file)
  const before=structuredClone(JSON.parse(JSON.stringify(bindings.lotDrafts.value)))
  await bindings.confirmLotPost()
  assert.equal(fixture.sent.length,1,seed.file)
  assert.equal(fixture.sent[0].args[0],1,seed.file)
  const dates={manufactured_on:'2026-10-01',expires_on:'2027-10-01'}
  const existingOnly=['warehouseOutbounds','transfers','shipments','materialIssues'].includes(seed.state)
  const freshLot=seed.state==='productionCompletions'?{quantity:'100',...dates}
   :existingOnly?{lot_id:8,quantity:'100'}
   :{...(['stocktakes','stockAdjustments','salesReturns','materialReturns'].includes(seed.state)?{lot_id:null}:{}),
     quantity:'100',supplier_lot:'SUP-42',...dates}
  assert.deepEqual(fixture.sent[0].args[1],seed.lineKey?[{[seed.lineKey]:7,lots:[freshLot]}]:[freshLot],seed.file+' 确认载荷')
  assert.deepEqual(JSON.parse(JSON.stringify(bindings.lotDrafts.value)),before,seed.file+' 保存失败应保留输入')
  store.connectionLost=true;await bindings.confirmLotPost();assert.equal(fixture.sent.length,1,seed.file+' 断线禁止提交')
  store.connectionLost=false;draft[0].quantity='99';await bindings.confirmLotPost();assert.equal(fixture.sent.length,1,seed.file+' 差额禁止提交')
  assert.match(bindings.lotIssue.value,/100/,seed.file)
 }
})

test('新增与详情只统一标题栏，基础信息、明细和原操作布局继续保留',async()=>{
 const source=await readFile(new URL('../src/renderer/src/components/workspace/WorkspaceDocumentDialog.vue',import.meta.url),'utf8')
 assert.match(source,/:title="title"/)
 assert.match(source,/class="document-basic"/)
 assert.match(source,/class="document-footer"/)
 assert.match(source,/readOnly \? '关闭' : '收起'/)
 const titles=[['production/ProductionWorkOrdersView.vue','新建生产工单'],['production/ProductionCompletionsView.vue','新建完工报工单'],['finance/PaymentRecordsView.vue','登记收付款'],['finance/InventoryValuationView.vue','登记库存核价']]
 for(const [file,title] of titles){
  const text=await readFile(new URL('../src/renderer/src/views/workspace/'+file,import.meta.url),'utf8')
  assert.match(text,new RegExp(`<NModal title="${title}"`))
  assert.doesNotMatch(text,new RegExp(`<h[23]>${title}</h[23]>`))
 }
})
