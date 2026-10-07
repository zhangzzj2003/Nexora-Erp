import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createServer} from 'vite'
import vue from '@vitejs/plugin-vue'
import {createPinia} from 'pinia'
import {createSSRApp,h} from 'vue'
import {renderToString} from '@vue/server-renderer'
import {associationFixture,associationDocument} from './production-association-fixture.mjs'

// 编译实际 Vue 弹窗，确认共用只读表格与来源、参考、工单范围提示。
test('生产关联弹窗明确缺口、登记来源与采购参考，不出现写入动作', async t => {
  const server=await createServer({configFile:false,plugins:[{name:'association-view',enforce:'pre',resolveId(id){
    if(id.endsWith('/store/app-store'))return '\0association-store'
    if(id.endsWith('/WorkspaceDocumentDialog.vue'))return '\0association-document'
    if(id.endsWith('/AppButton.vue'))return '\0association-button'
  },load(id){
    if(id==='\0association-store')return `import {defineStore} from 'pinia';import {createAppState} from '/src/renderer/src/store/state.ts';export const calls=[];
      export const usePiniaAppStore=defineStore('association-view',()=>{const s=createAppState();return {...s,localTime:v=>v,
        closeProductionAssociations(){calls.push(['close'])},loadProductionAssociations:v=>calls.push(['load',v])}})`
    if(id==='\0association-button')return `import {defineComponent,h} from 'vue';export default defineComponent({setup(p,{attrs,slots}){return()=>h('button',attrs,slots.default?.())}})`
    if(id==='\0association-document')return `import {defineComponent,h} from 'vue';export const calls=[];export default defineComponent({props:['show','title','data','columns','readOnly','hint'],setup(p,{slots}){return()=>p.show?h('section',{'data-readonly':p.readOnly},[h('h1',p.title),slots.basicInfo?.(),...(p.data??[]).flatMap(row=>p.columns.map(c=>slots['cell-'+c.key]?.({row}))),h('p',p.hint)]):null}})`
  }},vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
  t.after(()=>server.close())
  const {usePiniaAppStore}=await server.ssrLoadModule('\0association-store')
  const {default:View}=await server.ssrLoadModule('/src/renderer/src/components/workspace/ProductionAssociationDialog.vue')
  const pinia=createPinia(),store=usePiniaAppStore(pinia),row=associationFixture()
  store.productionAssociationTarget=row.target;store.productionAssociationRecord=row
  const render=()=>renderToString(createSSRApp({render:()=>h(View)}).use(pinia))
  let html=await render();assert.match(html,/data-readonly="true"/);assert.match(html,/200 个 缺少固定批次分配证据/)
  assert.match(html,/不能证明某台产品或某次分批完工/);assert.doesNotMatch(html,/添加物料|确认领料|提交审批/)
  row.references_included=true;row.components[0].purchase_references=[{receipt_id:8,line_id:8,document_no:'PIN-REF',quantity:'500',supplier_id:4,supplier_name:'参考供应商',posted_at:'2026-10-07 10:00:00'}]
  row.components[0].issues[0].sources=[{lot_id:9,lot_code:'R1-L1-P1',quantity:'100',evidence_kind:'allocation',source_id:9,source_document_no:'PIN-REAL',supplier_id:3,supplier_name:'登记供应商',receipt_reversed:false,origin_movement_id:9}]
  row.components[0].issues[0].returns=[{...associationDocument(4,'MR-RETURN','reversed'),line_id:4,quantity:'50',effective:false,reversal_reason:'退料更正'}]
  store.productionAssociationRecord={...row};html=await render()
  assert.match(html,/采购入库 PIN-REAL · 登记供应商/);assert.match(html,/同物料排查参考（未经证实使用）/)
  assert.match(html,/入库 PIN-REF · 参考供应商/);assert.match(html,/退料 MR-RETURN · 已冲销 · 50/)
  row.target={kind:'completion',id:3};store.productionAssociationRecord={...row};html=await render()
  assert.match(html,/生产关联单据 · CMP-20261007-000001/);assert.match(html,/（当前查询）/)
})
