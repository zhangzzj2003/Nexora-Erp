import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createSSRApp, h } from 'vue'
import { createPinia } from 'pinia'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { emptyCrmForms } from '../src/renderer/src/store/modules/crm-actions.ts'

// 只替换外围组件与服务，真实页面和编辑器的事件、校验及草稿绑定参与测试。
const storeSource = `import { defineStore } from 'pinia'; import { ref } from 'vue';
export const allowed = new Set(['crm.view','crm_contact.manage']);
export const calls = [];
export const usePiniaAppStore = defineStore('crm-contact-dialog-test',()=>({
  crmOverview:ref({contacts:[{id:1,name:'王女士',customer_id:4,customer_name:'客户甲',phone:'100',email:'',is_active:true,created_by_name:'销售员'}],activities:[],opportunities:[],quotes:[]}),
  crmForecast:ref(null),crmOptions:ref({customers:[{id:4,name:'客户甲'}],owners:[],materials:[]}),
  crmDetail:ref(null),crmError:ref(''),crmLoading:ref(false),crmForms:ref(null),crmEdit:ref({}),
  crmOwnerChanges:ref([]),busy:ref(false),user:ref({id:1,permissions:['crm.view','crm_contact.manage']}),connectionLost:ref(false),error:ref(''),
  saveResult:ref(false),can:code=>allowed.has(code),loadCrm:async()=>{},clearCrmDetail(){},
  startNewCrm(){},editCrm:async()=>true,
  saveCrm:async function(kind){calls.push(kind);return this.saveResult},navigateToRoute(){}
}));`
const modalSource = `import { defineComponent,h } from 'vue';
export { NModal as default }; export const NModal=defineComponent({props:['show','title','maskClosable','closeOnEsc','closable'],setup(p,{slots}){
  return ()=>p.show?h('section',{'data-modal':p.title,'data-mask':String(p.maskClosable),'data-esc':String(p.closeOnEsc),'data-close':String(p.closable)},slots.default?.()):null
}});export const NInputNumber=defineComponent({setup(){return()=>null}});`
const buttonSource = `import {defineComponent,h} from 'vue';export default defineComponent({props:['type','disabled','loading'],setup(p,{attrs,slots}){
  return()=>h('button',{...attrs,type:p.type,disabled:p.disabled||p.loading},slots.default?.())
}});`
const inputSource = `import {defineComponent,h} from 'vue';export default defineComponent({props:['modelValue','disabled'],setup(p,{attrs}){
  return()=>h('input',{...attrs,value:p.modelValue,disabled:p.disabled})
}});`
const selectSource = `import {defineComponent,h} from 'vue';export default defineComponent({props:['modelValue','disabled'],setup(p){
  return()=>h('select',{value:p.modelValue,disabled:p.disabled})
}});`
const tableSource = `import {defineComponent,h} from 'vue';export default defineComponent({props:['data','title'],setup(p,{slots}){
  return()=>h('section',{'data-table':p.title},[slots.filters?.(),...p.data.map(row=>h('article',row.name))])
}});`
async function fixture(t) {
  const server = await createServer({configFile:false,plugins:[{
    name:'crm-contact-dialog-fixture',enforce:'pre',
    transform(code,id){
      if(/\/(CustomerRelationsView|CrmEditor)\.vue$/.test(id))return code.replace("'naive-ui'","'virtual:contact-modal'").replace(/(['"])[^'"]*AppModal\.vue\1/g, "'virtual:contact-modal'")
    },resolveId(id,importer){
      if(id==='virtual:contact-modal')return '\0contact-modal'
      if(!importer?.includes('/src/renderer/'))return
      if(id.endsWith('/store/app-store'))return '\0contact-store'
      if(id.endsWith('/AppButton.vue'))return '\0contact-button'
      if(id.endsWith('/AppInput.vue'))return '\0contact-input'
      if(id.endsWith('/WorkspaceSelect.vue') || id.endsWith('/WorkspaceMaterialSelect.vue'))return '\0contact-select'
      if(id.endsWith('/WorkspaceTable.vue'))return '\0contact-table'
      if(/\/(CrmEvidence|ContactImportDialog|OpportunityImportDialog|CrmDate|DocumentApprovalDialog)\.vue$/.test(id))return '\0contact-empty'
    },load(id){return {'\0contact-store':storeSource,'\0contact-modal':modalSource,'\0contact-button':buttonSource,
      '\0contact-input':inputSource,'\0contact-select':selectSource,'\0contact-table':tableSource,
      '\0contact-empty':`export default {render:()=>null}`}[id]}
  },vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
  t.after(()=>server.close())
  const {usePiniaAppStore,allowed,calls}=await server.ssrLoadModule('\0contact-store')
  const pinia=createPinia(),store=usePiniaAppStore(pinia)
  store.crmForms=emptyCrmForms()
  const {default:View}=await server.ssrLoadModule('/src/renderer/src/views/workspace/sales/CustomerRelationsView.vue')
  const {default:Editor}=await server.ssrLoadModule('/src/renderer/src/views/workspace/sales/CrmEditor.vue')
  // 在真实 setup 后操作页面事件，SSR 展开弹窗插槽；不以源码匹配替代行为验证。
  async function render(Component,props={},prepare=()=>{}) {
    let setup
    const Wrapped={...Component,setup(p,context){setup=Component.setup(p,context);prepare(setup);return setup}}
    const html=await renderToString(createSSRApp({render:()=>h(Wrapped,props)}).use(pinia))
    return {html,setup}
  }
  return {store,allowed,calls,View,Editor,render}
}

test('新建联系人在列表上方弹出，继承客户筛选，关闭保留输入且保存中禁止关闭',async t=>{
  const {store,View,render}=await fixture(t)
  store.crmForms.contact.name='未保存姓名'
  const {html,setup}=await render(View,{},page=>{
    page.selectMode('contact');page.customer.value=4;page.query.value='王';page.newRecord('contact')
  })
  assert.match(html,/data-modal="新建联系人"/)
  assert.match(html,/data-table="联系人"/)
  // 普通 template 会让浏览器把列表当作惰性模板，SSR 字符串有内容也不可见。
  assert.doesNotMatch(html,/<template[\s>]/)
  assert.match(html,/王女士/)
  assert.match(html,/value="未保存姓名"/)
  assert.doesNotMatch(html,/联系人状态/)
  assert.doesNotMatch(html,/返回列表|class="crm-editor card"/)
  assert.match(html,/data-mask="false"/)
  assert.equal(store.crmForms.contact.customer_id,4)
  store.busy=true
  setup.closeEditor()
  assert.equal(setup.editor.value,'contact')
  store.busy=false
  setup.closeEditor()
  assert.equal(setup.editor.value,null)
  assert.equal(store.crmForms.contact.name,'未保存姓名')
  assert.equal(setup.query.value,'王')
  setup.newRecord('contact')
  assert.equal(setup.editor.value,'contact')
  assert.equal(store.crmForms.contact.name,'未保存姓名')
  const saving=await render(View,{},page=>{page.editor.value='contact';page.mode.value='contact';store.busy=true})
  assert.match(saving.html,/data-esc="false"/)
  assert.match(saving.html,/data-close="false"/)
  assert.match(saving.html,/<button[^>]*disabled[^>]*>取消/)
})

test('联系人管理权限限制弹窗，修订继续锁定客户并显示原因，其他编辑页保持原流程',async t=>{
  const {store,allowed,View,Editor,render}=await fixture(t)
  allowed.delete('crm_contact.manage')
  const denied=await render(View,{},page=>page.newRecord('contact'))
  assert.equal(denied.setup.editor.value,null)
  assert.doesNotMatch(denied.html,/data-modal="新建联系人"/)
  allowed.add('crm_contact.manage')
  store.crmEdit.contact={kind:'contact',id:1,version:2,reason:''}
  store.crmForms.contact={customer_id:4,name:'王女士',job_title:'采购',phone:'100',email:'',is_active:true,note:''}
  const editing=await render(View,{},page=>{page.editor.value='contact';page.mode.value='contact'})
  assert.match(editing.html,/data-modal="修订联系人"/)
  assert.match(editing.html,/<select[^>]*disabled/)
  assert.match(editing.html,/修订原因/)
  assert.match(editing.html,/联系人状态/)
  assert.match(editing.html,/保存修订/)
  const inline=await render(Editor,{kind:'activity'})
  assert.match(inline.html,/返回列表/)
  assert.match(inline.html,/class="crm-editor card"/)
})

test('弹窗表单校验阻止缺失客户和姓名，失败保留草稿，成功才发送 saved，断线及保存中不能提交',async t=>{
  const {store,calls,Editor,render}=await fixture(t)
  let saved=0
  const {setup}=await render(Editor,{kind:'contact',dialog:true,onSaved:()=>saved++})
  await setup.save()
  assert.match(setup.failure.value,/请选择客户并填写联系人姓名/)
  assert.equal(calls.length,0)
  store.crmForms.contact.customer_id=4;store.crmForms.contact.name='王女士'
  store.error='保存失败'
  await setup.save()
  assert.equal(saved,0)
  assert.equal(store.crmForms.contact.name,'王女士')
  const failure=await render(Editor,{kind:'contact',dialog:true})
  assert.match(failure.html,/保存失败/)
  assert.match(failure.html,/输入及修订原因已保留/)
  for(const blocked of ['busy','connectionLost','crmLoading']){
    const before=calls.length;store[blocked]=true
    await setup.save()
    assert.equal(calls.length,before)
    store[blocked]=false
  }
  store.crmEdit.contact={kind:'contact',id:1,version:2,reason:''}
  await setup.save()
  assert.match(setup.failure.value,/请填写修订原因/)
  store.crmEdit.contact.reason='电话更正';store.saveResult=true
  await setup.save()
  assert.equal(saved,1)
})

// 四类编辑器共用弹窗后，逐种核对列表仍可见且编辑内容在弹窗内。
test('跟进商机和报价沿用公共弹窗，背景列表不进入惰性模板',async t=>{
  const {allowed,View,render}=await fixture(t)
  for(const [kind,permission,label] of [['activity','crm_activity.manage','客户跟进'],
    ['opportunity','crm_opportunity.manage','销售商机'],['quote','crm_quote.create','销售报价']]) {
    allowed.add(permission)
    const {html}=await render(View,{},page=>page.newRecord(kind))
    assert.match(html,new RegExp(`data-modal="新建${label}"`))
    assert.match(html,new RegExp(`data-table="${label}"`))
    assert.doesNotMatch(html,/<template[\s>]/)
    assert.doesNotMatch(html,/返回列表|class="crm-editor card"/)
  }
})

// 视觉概览使用完整页签快照，切换筛选只能改变列表，不能清除原有表单。
test('CRM 分类统计、关键词和客户筛选组合，切换页签重置状态但保留草稿',async t=>{
  const {store,allowed,View,render}=await fixture(t)
  store.crmOverview.contacts.push({id:2,name:'旧联系人',customer_id:4,customer_name:'客户甲',phone:'200',email:'old@example.invalid',is_active:0,created_by_name:'销售员'})
  store.crmForms.contact.name='正在填写的联系人'
  const {setup}=await render(View,{},page=>page.selectMode('contact'))
  assert.equal(setup.counts.value.find(row=>row.key==='').count,2)
  setup.summary.value='inactive';setup.query.value='old@example.invalid';setup.customer.value=4
  assert.deepEqual(setup.records.value.map(row=>row.id),[2])
  assert.equal(setup.counts.value.find(row=>row.key==='').count,2)
  setup.customer.value=9;assert.equal(setup.records.value.length,0)
  setup.selectMode('quote');assert.equal(setup.summary.value,'');assert.equal(setup.query.value,'')
  assert.equal(store.crmForms.contact.name,'正在填写的联系人')
  allowed.add('crm_activity.manage');setup.summary.value='attention';setup.query.value='旧报价'
  setup.newRecord('activity')
  assert.equal(setup.mode.value,'activity');assert.equal(setup.summary.value,'');assert.equal(setup.query.value,'')
})
