import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createPinia} from 'pinia'
import {createSSRApp,h} from 'vue'
import {renderToString} from '@vue/server-renderer'
import {createServer} from 'vite'
import vue from '@vitejs/plugin-vue'

// 装载真实页面，只替换桌面边界与可视控件，检查表单约束及真实来源预览。
async function fixture(t) {
  const targets=['SubledgerEditor.vue','BusinessJournalPanel.vue','BusinessSourceEvidence.vue']
  const server=await createServer({configFile:false,plugins:[{
    name:'multiple-controls-view',enforce:'pre',
    transform(code,id){if(targets.some(name=>id.endsWith('/'+name)))return code.replaceAll("'naive-ui'","'virtual:multi-modal'")},
    resolveId(id,importer){
      if(id==='virtual:multi-modal')return '\0multi-modal'
      if(targets.some(name=>importer?.endsWith('/'+name)) && id.endsWith('/store/app-store'))return '\0multi-store'
      if(id.endsWith('/WorkspaceTable.vue'))return '\0multi-table'
      if(id.endsWith('/AppButton.vue'))return '\0multi-button'
      if(id.endsWith('/WorkspaceSelect.vue'))return '\0multi-select'
      if(id.endsWith('/AuxiliarySelector.vue'))return '\0multi-aux'
      if(id.endsWith('/AppInput.vue')||id.endsWith('/AppCollapseItem.vue'))return '\0multi-stub'
    },load(id){
      if(id==='\0multi-stub')return 'export default {render:()=>null}'
      if(id==='\0multi-modal')return `import {defineComponent,h} from 'vue';export const NModal=defineComponent({props:['show'],setup(p,{slots}){return()=>p.show?h('section',slots.default?.()):null}});export const NDatePicker={render:()=>null};export const NCollapse=defineComponent({setup(p,{slots}){return()=>h('div',slots.default?.())}})`
      if(id==='\0multi-table')return `import {defineComponent,h} from 'vue';export default defineComponent({props:['title','data','columns'],setup(p,{slots}){return()=>h('section',[h('h2',p.title),slots.actions?.(),...(p.data??[]).flatMap(row=>p.columns.map(c=>slots['cell-'+c.key]?.({row})??String(row[c.key]??'')))])}})`
      if(id==='\0multi-button')return `import {defineComponent,h} from 'vue';export default defineComponent({props:['disabled'],setup(p,{slots,attrs}){return()=>h('button',{...attrs,disabled:p.disabled},slots.default?.())}})`
      if(id==='\0multi-select')return `import {defineComponent,h} from 'vue';export default defineComponent({props:['disabled','modelValue','options'],setup(p,{attrs}){return()=>h('select',{...attrs,disabled:p.disabled},p.options?.map(item=>h('option',{value:item.value,selected:item.value===p.modelValue,disabled:item.disabled},item.label)))}})`
      if(id==='\0multi-aux')return `import {defineComponent,h} from 'vue';export default defineComponent({props:['disabled','policy','modelValue','labelPrefix'],setup(p){return()=>h('fieldset',{disabled:p.disabled,'data-account':p.policy?.account_id,'aria-label':p.labelPrefix},JSON.stringify(p.modelValue))}})`
      if(id==='\0multi-store')return `import {defineStore} from 'pinia';import {createAppState} from '/src/renderer/src/store/state.ts';export const calls=[];
        export const usePiniaAppStore=defineStore('multiple-view',()=>{const state=createAppState();return {...state,can:code=>state.user.value?.permissions.includes(code),loadBusinessJournals:async()=>true,saveSubledger:async()=>{calls.push('save');return false},generateBusinessJournal:async input=>{calls.push(input);return false}}})`
    }
  },vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
  t.after(()=>server.close())
  const {usePiniaAppStore,calls}=await server.ssrLoadModule('\0multi-store')
  const pinia=createPinia(),store=usePiniaAppStore(pinia)
  store.user={id:1,permissions:['business_journal.generate']}
  return {server,pinia,store,calls}
}

test('多科目实际表单逐张选科目，禁止批量改写及删除使用中的控制范围',async t=>{
  const {server,pinia,store,calls}=await fixture(t)
  const {default:View}=await server.ssrLoadModule('/src/renderer/src/views/workspace/finance/SubledgerEditor.vue')
  store.subledgerOptions={opening_balance:{status:'confirmed',effective_date:'2026-01-01'},
    accounts:[1,2,5,6].map(id=>({id,code:'AC'+id,name:'科目'+id,is_active:true})),auxiliary_items:[],auxiliary_policies:[]}
  store.subledgerForm={id:1,version:4,reference:'H',reason:'核对',control_accounts:[{kind:'receivable',account_id:1},{kind:'receivable',account_id:5},{kind:'payable',account_id:2}],
    lines:[{kind:'receivable',account_id:1,party_id:1,document_reference:'OLD',document_date:'2025-12-01',debit:'100',credit:'0',auxiliary:[{kind:'project',id:7}]}]}
  let bindings
  const Real={...View,setup(p,ctx){bindings=View.setup(p,ctx);return bindings}}
  const render=()=>renderToString(createSSRApp({render:()=>h(Real)}).use(pinia))
  const html=await render()
  assert.match(html,/aria-label="第 1 个控制科目"[^>]*disabled/)
  assert.match(html,/aria-label="删除第 1 个控制科目"[^>]*disabled/)
  assert.match(html,/aria-label="第 1 行控制科目"/)
  const original=structuredClone(JSON.parse(JSON.stringify(store.subledgerForm.lines)))
  const used=store.subledgerForm.control_accounts[0]
  bindings.setAccount(used,6);bindings.removeControl(used)
  assert.equal(used.account_id,1);assert.equal(store.subledgerForm.control_accounts.length,3)
  assert.deepEqual(JSON.parse(JSON.stringify(store.subledgerForm.lines)),original)
  assert.match(store.error,/先逐张/)
  const free=store.subledgerForm.control_accounts[1]
  assert.ok(!bindings.controlOptions(free).some(item=>item.value===1))
  bindings.setAccount(free,2);assert.equal(free.account_id,5)
  bindings.setAccount(free,6);assert.equal(free.account_id,6)
  assert.deepEqual(JSON.parse(JSON.stringify(store.subledgerForm.lines)),original)
  bindings.addLine();assert.equal(store.subledgerForm.lines[1].account_id,0)
  assert.equal(bindings.ready.value,false);await bindings.save();assert.equal(calls.length,0)
  bindings.setKind(store.subledgerForm.lines[1],'payable');assert.equal(store.subledgerForm.lines[1].account_id,2)
  store.subledgerForm.lines.splice(1)
  store.subledgerForm.lines[0].account_id=6;bindings.removeControl(used)
  assert.equal(store.subledgerForm.control_accounts.length,2)
  assert.equal(store.subledgerForm.lines[0].debit,'100');assert.equal(store.subledgerForm.lines[0].auxiliary[0].id,7)
  bindings.addControl('receivable');const empty=store.subledgerForm.control_accounts.at(-1)
  assert.equal(bindings.usage(empty),0);bindings.removeControl(empty)
  assert.equal(bindings.ready.value,true)
  store.subledgerOptions.accounts=store.subledgerOptions.accounts.filter(item=>item.id!==6)
  assert.equal(bindings.ready.value,false);assert.match(bindings.problem.value,/停用或不可用/)
  await bindings.save();assert.equal(calls.length,0)
})

test('实际历史资金预览显示原科目及完整归属，生成失败保留输入，普通来源仍可编辑辅助',async t=>{
  const {server,pinia,store,calls}=await fixture(t)
  const {default:View}=await server.ssrLoadModule('/src/renderer/src/views/workspace/finance/BusinessJournalPanel.vue')
  store.businessJournalOptions={policy:{version:1,mapping:{receivable:1,cash:4}},accounts:[{id:1,code:'AR',name:'通用应收',is_active:true},{id:5,code:'AR2',name:'其他应收',is_active:true},{id:4,code:'CASH',name:'银行',is_active:true}],
    auxiliary_items:[{kind:'customer',id:1,name:'客户甲'},{kind:'project',id:7,name:'项目甲'}],auxiliary_policies:[{account_id:5},{account_id:4}]}
  const source={key:'subledger_payment:1',source_type:'subledger_payment',source_id:1,label:'历史收款',source_date:'2026-10-08',minimum_date:'2026-10-08',fingerprint:'a'.repeat(64),policy_version:1,can_generate:true,
    roles:{cash:'10.00',receivable:'-10.00'},records:[{kind:'receivable',account_id:5}],movements:[],business:[],warnings:[],blockers:[],labels:{},auxiliary_defaults:[{kind:'customer',id:1},{kind:'project',id:7}]}
  store.businessJournalSources=[source]
  let bindings
  const Real={...View,setup(p,ctx){bindings=View.setup(p,ctx);bindings.open(source);return bindings}}
  const html=await renderToString(createSSRApp({render:()=>h(Real)}).use(pinia))
  assert.match(html,/AR2 · 其他应收/);assert.doesNotMatch(html,/供应商：项目甲/)
  assert.match(html,/客户：客户甲；项目：项目甲/)
  assert.match(html,/disabled data-account="5"/)
  assert.equal(bindings.selectedMapping.value.receivable,5)
  assert.deepEqual(JSON.parse(JSON.stringify(bindings.auxiliaryByRole.value)),{cash:[{kind:'project',id:7}],receivable:[{kind:'project',id:7}]})
  bindings.reference.value='BANK-1';bindings.reason.value='回单核对';await bindings.generate()
  assert.equal(bindings.selected.value.key,source.key);assert.equal(bindings.reference.value,'BANK-1')
  assert.equal(calls[0].auxiliary_by_role.receivable[0].id,7)
  bindings.open({...source,source_type:'payment',records:[]})
  assert.equal(bindings.historical.value,false);assert.equal(bindings.selectedMapping.value.receivable,1)
  assert.deepEqual(JSON.parse(JSON.stringify(bindings.auxiliaryByRole.value)),{cash:[],receivable:[]})
})
