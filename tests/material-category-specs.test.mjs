import assert from 'node:assert/strict'
import {test} from 'node:test'
import {createSSRApp, effectScope, h} from 'vue'
import {createPinia} from 'pinia'
import {renderToString} from '@vue/server-renderer'
import {setup as setupSsrStyles} from '@css-render/vue3-ssr'
import {createServer} from 'vite'
import vue from '@vitejs/plugin-vue'
import {materialCategoryBody, materialSpecFieldBody, materialSpecBody, validateMaterialCategoryResult, validateMaterialSpecs} from '../src/shared/material-category-validation.ts'
import {materialDraft, materialInput, prepareMaterialSpecs, matchesMaterial} from '../src/renderer/src/utils/material-form.ts'
import {materialChoiceFacts, materialSelectOptions, matchesMaterialChoice} from '../src/renderer/src/utils/material-selection.ts'
import {createAppState} from '../src/renderer/src/store/state.ts'
import {createCatalogActions} from '../src/renderer/src/store/modules/catalog-actions.ts'
import {callBackend} from '../src/main/backend.ts'
import {materialCategoryAuditRows} from '../src/renderer/src/utils/material-category-audit.ts'

const field={id:1,category_code:'ZZ-AA',name:'长度',kind:'number',unit:'mm',options:[],allow_custom:false,required:false,enabled:true,sort_order:0,used:false,deleted:false}
const node={code:'ZZ-AA',parent_code:'ZZ',name:'结构件',enabled:true,deleted:false,used:false,sort_order:0,notes:'',version:2,template_version:2,material_count:0,fields:[field]}
const tree=[{...node,code:'ZZ',parent_code:null,name:'自定义材料',fields:[],children:[node,{...node,code:'ZZ-BB',name:'外壳',fields:[{...field,id:2,category_code:'ZZ-BB'}]}]}]
const input={code:'ZZ-AA',parent_code:'ZZ',name:'结构件',enabled:true,notes:'',sort_order:0,version:2,reason:'核对后修正'}
const spec={field_id:1,status:'filled',value:'1.25',source:'图纸 A',name:'长度',kind:'number',unit:'mm',category_code:'ZZ-AA',historical:false}

test('规格记录按稳定编号显示中文差异，改名、停用和移除不会混淆字段',()=>{
  const change={before:node,after:{...node,fields:[{...field,name:'图纸长度',enabled:false,used:true}]}}
  const rows=materialCategoryAuditRows(change)
  assert.deepEqual(rows.map(({label,before,after})=>({label,before,after})),[
    {label:'图纸长度 · 名称',before:'长度',after:'图纸长度'},
    {label:'图纸长度 · 状态',before:'启用',after:'停用'},
  ])
  assert.ok(materialCategoryAuditRows({...change,after:{...node,fields:[]}}).some(row=>row.label==='规格字段：长度'&&row.after==='已移除'))
  assert.ok(materialCategoryAuditRows({before:null,after:node}).some(row=>row.label==='长度 · 类型'&&row.after==='数值'))
})

test('分类和模板维护的 IPC 白名单、版本、长度、类型与层级均严格校验',()=>{
  assert.deepEqual(materialCategoryBody({...input,token:'私有',children:[]},true),input)
  for(const bad of [{...input,code:'../../users'},{...input,parent_code:'XX'},{...input,version:true},{...input,sort_order:-1},{...input,name:' '}]) assert.throws(()=>materialCategoryBody(bad,true))
  const body={name:'阻值',kind:'number',unit:'Ω',options:[],allow_custom:false,required:false,enabled:true,sort_order:0,version:2,reason:'补参数'}
  assert.deepEqual(materialSpecFieldBody({...body,id:9}),body)
  for(const bad of [{...body,kind:'sql'},{...body,kind:'text'},{...body,kind:'enum',unit:'',options:['铜',' 铜 ']},{...body,version:0},{...body,required:1}]) assert.throws(()=>materialSpecFieldBody(bad))
  const write=materialSpecBody({spec_values:[spec],spec_template_version:2,extra_attributes:[{name:'工艺',value:'绝缘',unit:''}]})
  assert.deepEqual(write.spec_values,[{field_id:1,status:'filled',value:'1.25',source:'图纸 A'}])
  for(const bad of [{spec_values:[spec],spec_template_version:true},{spec_values:[spec,spec],spec_template_version:2},
    {spec_values:[{...spec,value:1}],spec_template_version:2},{spec_values:[{...spec,status:'unknown'}],spec_template_version:2},
    {extra_attributes:[{name:'x',value:'x',unit:''},{name:'x',value:'x',unit:''}]}]) assert.throws(()=>materialSpecBody(bad))
})

test('完整分类和规格响应缺版本、单位或稳定身份时拒绝进入共享目录',()=>{
  validateMaterialCategoryResult('materialCategories',tree)
  validateMaterialCategoryResult('createMaterialCategory',node)
  validateMaterialSpecs({spec_values:[spec],spec_summary:'长度：1.25mm',spec_template_version:2})
  for(const bad of [{...node,template_version:0},{...node,fields:[{...field,id:true}]},{...node,fields:[field,field]}]) assert.throws(()=>validateMaterialCategoryResult('createMaterialCategory',bad))
  assert.throws(()=>validateMaterialSpecs({spec_values:[{...spec,historical:'false'}],spec_template_version:2,spec_summary:''}))
})

test('不同类别同名字段分别保留草稿；目录刷新不自动改模板版本或规格含义',()=>{
  const draft=materialDraft()
  draft.category_code='ZZ-AA';prepareMaterialSpecs(draft,tree)
  draft.spec_drafts['ZZ-AA'][0]={field_id:1,status:'filled',value:'1.000000000001',source:'图纸'}
  draft.category_code='ZZ-BB';prepareMaterialSpecs(draft,tree)
  assert.equal(draft.spec_drafts['ZZ-BB'][0].value,null)
  draft.spec_drafts['ZZ-BB'][0]={field_id:2,status:'not_applicable',value:null,source:'确认'}
  draft.category_code='ZZ-AA';prepareMaterialSpecs(draft,[{...tree[0],children:[{...node,template_version:3,fields:[{...field,unit:'cm'}]}]}])
  assert.equal(draft.spec_drafts['ZZ-AA'][0].value,'1.000000000001')
  assert.equal(draft.spec_templates['ZZ-AA'].version,2)
  assert.equal(draft.spec_templates['ZZ-AA'].fields[0].unit,'mm')
  assert.equal(materialInput(draft,false).spec_template_version,2)
  assert.equal(materialInput(draft,false).spec_values[0].field_id,1)
})

test('旧物料未改规格时仅保存其他资料；主动修改传读取时模板版本并复制扩展属性',()=>{
  const row={...materialInput(materialDraft(),false),id:9,sku:'OLD',version:1,category_code:'ZZ-AA',spec_values:[spec],extra_attributes:[{name:'工艺',value:'绝缘',unit:''}]}
  const draft=materialDraft(row);prepareMaterialSpecs(draft,tree)
  assert.equal('spec_values' in materialInput(draft,true),false)
  assert.equal('extra_attributes' in materialInput(draft,true),false)
  draft.spec_drafts['ZZ-AA'][0].value='0'
  draft.extra_attributes[0].value='新值'
  const write=materialInput(draft,true)
  assert.equal(write.spec_values[0].value,'0')
  assert.equal(write.spec_template_version,2)
  assert.equal(row.extra_attributes[0].value,'绝缘')
  assert.equal(write.sku,'OLD')
})

test('所有业务选料与物料搜索能命中动态参数及扩展属性，历史值标识仍保留',()=>{
  const row={...materialInput(materialDraft(),false),id:9,sku:'OLD',version:1,category_code:'ZZ-AA',spec_values:[spec],spec_summary:'长度：1.25mm',extra_attributes:[{name:'工艺',value:'双层绝缘',unit:''}]}
  assert.equal(matchesMaterial(row,'双层绝缘','ZZ-AA',tree),true)
  const choice=materialSelectOptions([{value:9,label:'物料'}],[row],tree)[0]
  assert.equal(matchesMaterialChoice('长度 1.25mm 双层绝缘',choice.searchText),true)
  assert.equal(materialChoiceFacts(row,tree,true).find(entry=>entry.key==='spec:1').value,'1.25mm')
  assert.match(materialChoiceFacts({...row,spec_values:[{...spec,historical:true}]},tree,true).find(entry=>entry.key==='spec:1').label,/历史/)
})

test('失败、关闭和权限刷新保留同一账号草稿；退出或切换实例立即清除', async t=>{
  const previous=globalThis.window;t.after(()=>{globalThis.window=previous})
  const scope=effectScope()
  try {
    const state=scope.run(()=>createAppState())
    state.user.value={id:1,permissions:['catalog.manage','inventory.view']};state.server.value={id:'server-a'}
    state.materialCategoryDraft.value={...input,name:'未保存类别'}
    state.materialEditorDraft.value.name='未保存物料'
    state.materialCategoryEditorOpen.value=true;state.materialCategoryEditorOpen.value=false
    globalThis.window={nexora:{async callApi(){throw Error('模板冲突')}}}
    const actions=createCatalogActions(state,async run=>{try{await run()}catch{/* 错误由统一消息入口显示，草稿继续保留。 */}})
    assert.equal(await actions.saveMaterialCategory(state.materialCategoryDraft.value,true),false)
    assert.equal(state.materialCategoryDraft.value.name,'未保存类别')
    state.user.value={id:1,permissions:['inventory.view','catalog.manage']}
    assert.equal(state.materialEditorDraft.value.name,'未保存物料')
    state.server.value={id:'server-b'}
    assert.equal(state.materialCategoryDraft.value.name,'')
    assert.equal(state.materialEditorDraft.value.name,'')
    state.materialEditorDraft.value.name='原实例草稿'
    state.server.value={id:'server-b',fingerprint:'different-instance'}
    assert.equal(state.materialEditorDraft.value.name,'')
    state.materialFieldDraft.value.name='待修订规格'
    state.user.value={id:1,permissions:['inventory.view']}
    assert.equal(state.materialFieldDraft.value.name,'')
    state.user.value=null
    assert.equal(state.materialCategoryChanges.value.length,0)
  } finally {scope.stop()}
})

test('分类和字段 IPC 固定地址，UI 元数据不进入请求，路径注入和无效响应被拒绝',async t=>{
  const original=globalThis.fetch;t.after(()=>{globalThis.fetch=original})
  const calls=[]
  globalThis.fetch=async(url,init)=>{
    calls.push([new URL(url).pathname,init.method,init.body ? JSON.parse(init.body) : undefined])
    return new Response(JSON.stringify(new URL(url).pathname.endsWith('/login') ? {token:'test',user:{id:1}} : node),{status:200})
  }
  await callBackend('login',{})
  await callBackend('updateMaterialCategory',{...input,children:[]})
  assert.deepEqual(calls.at(-1),['/api/v1/material-categories/ZZ-AA','PUT',input])
  await callBackend('createMaterialSpecField',{code:'ZZ-AA',...field,version:2,reason:'补录',options:[]})
  assert.equal(calls.at(-1)[0],'/api/v1/material-categories/ZZ-AA/fields')
  assert.equal('id' in calls.at(-1)[2],false)
  await callBackend('deleteMaterialSpecField',{code:'ZZ-AA',field_id:1,version:2,reason:'移除'})
  assert.deepEqual(calls.at(-1),['/api/v1/material-categories/ZZ-AA/fields/1','DELETE',{version:2,reason:'移除'}])
  const before=calls.length
  await assert.rejects(callBackend('materialCategoryChanges',{code:'../users'}),/短码/)
  await assert.rejects(callBackend('updateMaterialSpecField',{code:'ZZ-AA',field_id:true}),/编号|字段/)
  assert.equal(calls.length,before)
})

test('真实动态编辑器展示状态、数值单位、来源、扩展属性和历史参数，断线禁用输入',async t=>{
  const server=await createServer({configFile:false,plugins:[vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
  t.after(()=>server.close())
  const {default:Editor}=await server.ssrLoadModule('/src/renderer/src/views/workspace/catalog/MaterialSpecificationsEditor.vue')
  const draft=materialDraft({category_code:'ZZ-AA',spec_values:[spec,{...spec,field_id:3,category_code:'ZZ-CC',historical:true}],extra_attributes:[{name:'工艺',value:'绝缘',unit:''}]})
  const app=createSSRApp({render:()=>h(Editor,{form:draft,categories:tree,disabled:true})});app.use(createPinia());setupSsrStyles(app)
  const html=await renderToString(app)
  // 历史区域默认收起，SSR 核对可展开入口；展开后的内容在真实界面验收。
  for(const label of ['分类规格字段','长度','mm','未知','确认依据 / 来源','非标准扩展属性','保留的历史规格']) assert.ok(html.includes(label),label)
  assert.match(html,/aria-expanded="false"/)
  assert.match(html,/<fieldset[^>]*disabled/)
  assert.match(html,/value="1.25"/)
})

test('旧服务目录仍可读取，但真实分类管理页禁止提交新版维护接口',async t=>{
  // 只替换页面依赖的会话快照，表格、按钮和新管理页保持真实实现。
  const mock=`import {defineStore} from 'pinia';import {ref} from 'vue';
    export const usePiniaAppStore=defineStore('legacy-category-view',()=>({
      materialCategories:ref([{code:'EL',name:'电子类',children:[{code:'EL-SR',name:'贴片电阻'}]}]),
      busy:ref(false),connectionLost:ref(false),materialCategoryDraft:ref({name:''}),materialCategoryEditing:ref(false),materialCategoryEditorOpen:ref(false),
      materialFieldDraft:ref({name:'',code:'',options:[]}),materialFieldEditorOpen:ref(false),materialCategoryChanges:ref([]),can:()=>true,
      reloadMaterialCategories:async()=>true,saveMaterialCategory:async()=>false,saveMaterialSpecField:async()=>false,removeMaterialCategory:async()=>false,loadMaterialCategoryChanges:async()=>false,localTime:value=>value
    }));`
  const server=await createServer({configFile:false,plugins:[{name:'legacy-category-store',enforce:'pre',resolveId(id){if(/\/app-store(?:\.ts)?$/.test(id))return '\0legacy-category-store'},load(id){if(id==='\0legacy-category-store')return mock}},vue()],ssr:{noExternal:['vxe-table']},optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
  t.after(()=>server.close())
  const {default:View}=await server.ssrLoadModule('/src/renderer/src/views/workspace/catalog/MaterialCategoriesView.vue')
  const app=createSSRApp({render:()=>h(View)}).use(createPinia());setupSsrStyles(app)
  const html=await renderToString(app)
  assert.ok(html.includes('请升级 ERP 服务'))
  assert.match(html,/<button[^>]*disabled[^>]*>[\s\S]*?新增大类/)
})
