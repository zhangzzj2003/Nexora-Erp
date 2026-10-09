import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createPinia} from 'pinia'
import {createSSRApp,createRenderer,h,nextTick,reactive,ssrContextKey} from 'vue'
import {renderToString} from '@vue/server-renderer'
import {createServer} from 'vite'
import vue from '@vitejs/plugin-vue'

test('真实附件组件展示来源变化、固定批准原件与更正，隔离方案变化和迟到失败',async t=>{
  const server=await createServer({configFile:false,plugins:[{name:'original-attachment-view',enforce:'pre',
    resolveId(id,importer){
      if(importer?.endsWith('/SubledgerAttachments.vue')&&id.endsWith('/store/app-store'))return '\0file-store'
      if(id.endsWith('/WorkspaceTable.vue'))return '\0file-table'
      if(id.endsWith('/AppButton.vue'))return '\0file-button'
      if(id.endsWith('/WorkspaceSelect.vue')||id.endsWith('/AppInput.vue'))return '\0file-stub'
    },load(id){
      if(id==='\0file-stub')return 'export default {render:()=>null}'
      if(id==='\0file-button')return `import {defineComponent,h} from 'vue';export default defineComponent({props:['disabled'],setup(p,{slots,attrs}){return()=>h('button',{...attrs,disabled:p.disabled},slots.default?.())}})`
      if(id==='\0file-table')return `import {defineComponent,h} from 'vue';export default defineComponent({props:['data','columns'],setup(p,{slots}){return()=>h('section',(p.data??[]).flatMap(row=>p.columns.map(c=>slots['cell-'+c.key]?.({row}))))}})`
      if(id==='\0file-store')return `import {defineStore} from 'pinia';import {createAppState} from '/src/renderer/src/store/state.ts';export const calls=[];export let pending;export const delay=()=>new Promise((resolve,reject)=>{pending={resolve,reject}});export let page=null;export const setPage=v=>{page=v};
        export const usePiniaAppStore=defineStore('file-view',()=>{const state=createAppState();return {...state,can:code=>state.user.value?.permissions.includes(code),
        loadSubledgerAttachments:async(id,p)=>{calls.push(['read',id,p]);return page},
        uploadSubledgerAttachment:async(...args)=>{calls.push(['upload',...args]);return delay()},
        reverseSubledgerAttachment:async(...args)=>{calls.push(['reverse',...args]);return {id:1}},saveSubledgerAttachment:async()=>true}})`
    }},vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
  t.after(()=>server.close())
  const fixtures=await server.ssrLoadModule('\0file-store'),{usePiniaAppStore,calls,setPage}=fixtures
  const {default:View}=await server.ssrLoadModule('/src/renderer/src/views/workspace/finance/SubledgerAttachments.vue')
  const pinia=createPinia(),store=usePiniaAppStore(pinia),props=reactive({openingId:7,openingVersion:2})
  store.user={id:1,roles:['finance'],permissions:['subledger_opening.view','subledger_opening.attachment']}
  const line={id:4,opening_id:7,opening_version:2,kind:'receivable',party_name:'客户甲',account_code:'AR',account_name:'应收',debit:'100.00',credit:'0.00',
    document_reference:'OLD-A',document_date:'2025-12-01',currency:'CNY',effective_date:'2026-01-01',auxiliary:[{kind:'customer',id:1,code:'customer:1',name:'客户甲'}]}
  const original={id:1,opening_id:7,source:line,file_name:'原件.pdf',byte_count:50,sha256:'a'.repeat(64),created_at:'2026-10-09 12:00:00',created_by_name:'admin',reason:'原始来源',source_status:'changed',approved_original:false,can_reverse:true,reversal:null}
  const page={opening_id:7,opening_version:2,opening_status:'draft',can_modify:true,page:2,page_size:50,total:51,active_count:1,changed_count:1,lines:[line],items:[original]}
  setPage(page)
  let bindings
  // 实际客户端生命周期保留监听；单独 SSR 挂载会主动停止监听，无法验证迟到结果。
  const renderer=createRenderer({createComment:()=>({}),insert:()=>{},remove:()=>{},parentNode:()=>null,nextSibling:()=>null,
    createElement:()=>({}),createText:()=>({}),setText:()=>{},setElementText:()=>{},patchProp:()=>{}})
  const app=renderer.createApp({setup(_p,ctx){bindings=View.setup(props,ctx);return()=>null}}).use(pinia)
  app.provide(ssrContextKey,{modules:new Set()})
  app.mount({});t.after(()=>app.unmount())
  const Real={...View,setup(){return bindings}}
  const render=()=>renderToString(createSSRApp({render:()=>h(Real,props)}).use(pinia))
  await render();await bindings.reload(2)
  let html=await render()
  assert.match(html,/1 个有效附件的原单已修改或移除/);assert.match(html,/原单来源已变化/);assert.match(html,/>撤销附件</)
  assert.match(html,/第 2 页 · 共 51 条/)
  bindings.inspected.value=original
  html=await render();assert.match(html,/SHA-256/);assert.match(html,/a{64}/);assert.match(html,/上传时方案版本 v2/)
  bindings.correction.value=original;bindings.correctionReason.value='录入错误';await bindings.write('reverse',original)
  assert.deepEqual(calls.find(row=>row[0]==='reverse'),['reverse',7,2,1,'录入错误'])
  setPage({...page,opening_status:'confirmed',can_modify:false,changed_count:0,items:[{...original,source_status:'matched',approved_original:true,can_reverse:false}]})
  await bindings.reload();html=await render()
  assert.match(html,/原批准附件/);assert.doesNotMatch(html,/>撤销附件<|>选择文件并上传</)
  setPage(page);await bindings.reload();bindings.lineId.value=4;bindings.reason.value='票据来源'
  const pending=bindings.write('upload');assert.deepEqual(calls.at(-1),['upload',7,2,4,'票据来源'])
  props.openingId=8;setPage({...page,opening_id:8});await nextTick()
  fixtures.pending.reject(Error('旧方案迟到失败'));await pending
  assert.equal(bindings.error.value,'');assert.equal(bindings.message.value,'');assert.equal(bindings.busy.value,false)
  store.connectionLost=true;await nextTick()
  assert.equal(bindings.data.value,null);assert.equal(bindings.correction.value,null);assert.equal(bindings.inspected.value,null)
})
