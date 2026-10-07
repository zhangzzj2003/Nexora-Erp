import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createSSRApp, effectScope, h, ref } from 'vue'
import { createPinia } from 'pinia'
import { renderToString } from '@vue/server-renderer'
import { setup as setupSsrStyles } from '@css-render/vue3-ssr'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { hasMaterialDetails, materialChoiceFacts, materialSelectOptions, matchesMaterialChoice } from '../src/renderer/src/utils/material-selection.ts'
import { appendDocumentMaterialRow, documentMaterialDisabled, documentMaterialIssue } from '../src/renderer/src/utils/document-material-lines.ts'
import { validateMaterialChoiceResult } from '../src/shared/material-choice-validation.ts'
import { callBackend } from '../src/main/backend.ts'
import { useOtherInboundMaterialDetails } from '../src/renderer/src/views/workspace/warehouse/other-inbound-material-details.ts'

const resistor = {id:1,sku:'EL-SR-000001',name:'贴片电阻',unit:'个',category_code:'EL-SR',
  specification:'10kΩ',package:'0603',brand:'示例品牌',manufacturer_part_number:'RC0603-10K',
  electrical_value:'10kΩ',tolerance:'±1%',rated_voltage:'50V',rated_power:'0.1W',
  temperature_range:'-55～155℃',compliance:'RoHS',notes:'精密电阻'}
const capacitor = {...resistor,id:2,sku:'EL-SC-000002',name:'贴片电容',category_code:'EL-SC',specification:'100nF'}
const categories=[{code:'EL',name:'电子类',children:[{code:'EL-SR',name:'贴片电阻'},{code:'EL-SC',name:'贴片电容'}]}]

test('业务候选集合、占位和禁用条件保留，搜索可跨规格及封装命中',()=>{
  const candidates=[{value:null,label:'全部物料'},{value:1,label:'电阻',disabled:true}]
  const result=materialSelectOptions(candidates,[resistor,capacitor],categories)
  assert.deepEqual(result.map(item=>[item.value,item.disabled]),[[null,undefined],[1,true]])
  assert.match(result[1].description,/10kΩ · 0603 · 示例品牌 · RC0603-10K/)
  for(const query of ['000001','贴片电阻','电子类','10KΩ 0603','示例品牌','rc0603-10k','±1%','50V','0.1W','155℃','RoHS','精密电阻']) {
    assert.ok(matchesMaterialChoice(query,result[1].searchText),query)
  }
  assert.equal(matchesMaterialChoice('100nF',result[1].searchText),false)
  assert.ok(matchesMaterialChoice('全部',result[0].searchText))
})

test('简要响应与未填写详情区分，中文分类来自业务接口或已加载目录',()=>{
  const summary={id:1,sku:'OLD',name:'旧料',unit:'件'}
  assert.equal(hasMaterialDetails(summary),false)
  assert.equal(hasMaterialDetails({...resistor,specification:''}),true)
  assert.match(materialSelectOptions([{value:1,label:'旧料'}],[summary],[])[0].description,/详细资料暂不可用/)
  assert.equal(materialChoiceFacts(resistor,categories)[0].value,'电子类 / 贴片电阻')
  assert.equal(materialChoiceFacts({...resistor,category_name:'接口分类'},[])[0].value,'接口分类')
  assert.equal(materialChoiceFacts({...resistor,category_code:''},[])[0].value,'未分类')
  assert.equal(materialChoiceFacts({...resistor,brand:'  '},categories).find(item=>item.key==='brand').value,'未填写')
})

test('连续新增空行、重选和删行保持真实草稿；空行提示行号并阻止保存',()=>{
  let lines=appendDocumentMaterialRow([])
  assert.deepEqual(lines,[{material_id:0,quantity:'1'}])
  const first=lines[0]
  lines=appendDocumentMaterialRow(lines)
  assert.equal(lines[0],first)
  assert.notEqual(lines[0],lines[1])
  lines[0].material_id=1
  assert.match(documentMaterialIssue(lines,[resistor,capacitor]),/第 2 行.*请选择物料/)
  assert.equal(documentMaterialDisabled(lines,0,1),false)
  assert.equal(documentMaterialDisabled(lines,1,1),true)
  lines[1].material_id=2;lines[1].quantity='0.125'
  assert.equal(documentMaterialIssue(lines,[resistor,capacitor]),'')
  const second=lines[1]
  lines.splice(0,1)
  assert.equal(lines[0],second)
  assert.equal(documentMaterialDisabled(lines,0,1),false)
  lines[0].material_id=1
  assert.equal(documentMaterialIssue(lines,[resistor,capacitor]),'')
  lines.splice(0,1)
  assert.deepEqual(appendDocumentMaterialRow(lines),[{material_id:0,quantity:'1'}])
  assert.equal(appendDocumentMaterialRow(Array.from({length:100},()=>({...first}))).length,100)
})

test('每一行的重复、失效和数量风险均在保存前拦截',()=>{
  const base={material_id:1,quantity:'1'}
  assert.match(documentMaterialIssue([base,base],[resistor]),/第 2 行.*只能添加一次/)
  assert.match(documentMaterialIssue([base],[]),/第 1 行.*不可用/)
  for(const quantity of ['', '0', '-1', '1.0001', '1000000.001', '1e2']) {
    assert.match(documentMaterialIssue([{...base,quantity}],[resistor]),/第 1 行.*数量/)
  }
  assert.equal(documentMaterialIssue([{...base,quantity:'1000000'}],[resistor]),'')
})

test('新增行自动切换资料展示，旧行可查看或收起，展示状态不改动草稿',()=>{
  const scope=effectScope()
  try {
    const lines=ref([])
    const details=scope.run(()=>useOtherInboundMaterialDetails(()=>lines.value))
    assert.equal(details.activeLine.value,null)
    lines.value=appendDocumentMaterialRow(lines.value)
    const first=lines.value[0];first.material_id=1;first.quantity='0.125';details.showLine(first)
    lines.value=appendDocumentMaterialRow(lines.value)
    const second=lines.value[1];details.showLine(second)
    assert.equal(details.activeLine.value,second)
    const before=JSON.stringify(lines.value)
    details.setCompact(first,false)
    assert.equal(details.activeLine.value,first)
    details.setCompact(first,true)
    assert.equal(details.activeLine.value,null)
    details.showLine({material_id:99,quantity:'1'})
    assert.equal(details.activeLine.value,null)
    assert.equal(JSON.stringify(lines.value),before)
    assert.equal(lines.value[0].quantity,'0.125')
    // 保存失败或收起不替换草稿时，当前查看行及所有输入均保留。
    details.showLine(second)
    assert.equal(details.activeLine.value,second)
    assert.equal(JSON.stringify(lines.value),before)
    lines.value=[]
    assert.equal(details.activeLine.value,null)
  } finally {scope.stop()}
})

test('移除中间行不按序号切换资料，移除当前行回到最后一行，恢复草稿仅默认查看最后行',()=>{
  const scope=effectScope()
  try {
    const lines=ref([{material_id:1,quantity:'1'},{material_id:2,quantity:'2'},{material_id:3,quantity:'3'}])
    const details=scope.run(()=>useOtherInboundMaterialDetails(()=>lines.value))
    const last=lines.value[2]
    assert.equal(details.activeLine.value,last)
    lines.value.splice(1,1)
    assert.equal(details.activeLine.value,last)
    assert.equal(last.quantity,'3')
    details.showLine(lines.value[0])
    lines.value.splice(0,1)
    assert.equal(details.activeLine.value,last)
    lines.value.splice(0,1)
    assert.equal(details.activeLine.value,null)
    lines.value=appendDocumentMaterialRow(lines.value)
    details.showLine(lines.value[0])
    assert.equal(details.activeLine.value,lines.value[0])
  } finally {scope.stop()}
})

test('旧业务响应兼容，新增字段的错误类型、超长内容及重复编号被边界拒绝',()=>{
  for(const action of ['crmOptions','afterSalesOverview','qualityOverview','equipmentOverview','inventoryWarnings','mrpOptions']) {
    validateMaterialChoiceResult(action,{materials:[resistor]})
    validateMaterialChoiceResult(action,{materials:[{id:1,sku:'OLD',name:'旧料',unit:'个'}]})
    for(const value of [{...resistor,brand:123},{...resistor,category_name:123},
      {...resistor,category_name:'x'.repeat(201)},{...resistor,notes:'x'.repeat(1001)},{...resistor,id:0}]) {
      assert.throws(()=>validateMaterialChoiceResult(action,{materials:[value]}),/物料/)
    }
    assert.throws(()=>validateMaterialChoiceResult(action,{materials:[resistor,resistor]}),/重复/)
    assert.throws(()=>validateMaterialChoiceResult(action,{materials:null}),/物料/)
  }
})

test('主进程实际业务读取入口拒绝损坏的新增详情，不扩大请求权限或接口路径',async t=>{
  const original=globalThis.fetch;t.after(()=>{globalThis.fetch=original})
  let malformed=false
  const paths=[]
  globalThis.fetch=async(url)=>{
    const path=new URL(url).pathname;paths.push(path)
    return new Response(JSON.stringify(path.endsWith('/login')?{token:'test',user:{id:1}}:
      {materials:[malformed?{...resistor,package:123}:resistor]}),{status:200})
  }
  await callBackend('login',{})
  for(const action of ['crmOptions','afterSalesOverview','qualityOverview']) {
    const result=await callBackend(action,undefined)
    assert.equal(result.materials[0].specification,'10kΩ')
    malformed=true;await assert.rejects(callBackend(action,undefined),/物料字段/);malformed=false
  }
  assert.deepEqual([...new Set(paths)],['/api/v1/auth/login','/api/v1/crm/options','/api/v1/after-sales','/api/v1/production-quality'])
})

test('真实选择器显示只读核心资料，空值、历史来源与无详情响应不会被自动改写',async t=>{
  // 使用真实选择器、Naive UI 和主题，资料由调用方传入，不需要伪造应用 store。
  const server=await createServer({configFile:false,plugins:[vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'})
  t.after(()=>server.close())
  const {default:Select}=await server.ssrLoadModule('/src/renderer/src/components/workspace/WorkspaceMaterialSelect.vue')
  async function render(modelValue,materials,options,extra={}){
    const app=createSSRApp({render:()=>h(Select,{modelValue,materials,options,required:true,ariaLabel:'待添加物料',...extra})}).use(createPinia())
    setupSsrStyles(app);return renderToString(app)
  }
  const ready=await render(1,[{...resistor,category_name:'电子类 / 贴片电阻'}])
  for(const text of ['10kΩ','0603','示例品牌','RC0603-10K','电子类 / 贴片电阻','单位','展开详情']) assert.ok(ready.includes(text),text)
  assert.doesNotMatch(ready,/额定电压|<textarea/)
  assert.match(ready,/aria-expanded="false"/)
  const empty=await render(0,[resistor])
  assert.doesNotMatch(empty,/展开详情|详细资料暂不可用/)
  assert.match(await render(1,[{id:1,sku:'OLD',name:'旧料',unit:'个'}]),/详细资料暂不可用/)
  assert.match(await render(9,[],[{value:9,label:'物料 #9（保留的来源）'}]),/保留的来源/)
  assert.doesNotMatch(await render(null,[],[{value:null,label:'全部物料'}]),/详细资料暂不可用/)
  assert.ok((await render(1,[{...resistor,brand:'<img src=x onerror=alert(1)>'}])).includes('&lt;img'))
  // 仅主动接入的表格精简旧行；普通表单保持核心资料，旧简要响应仍有明确提示。
  const compact=await render(1,[resistor],undefined,{compact:true})
  assert.match(compact,/物料资料摘要|查看资料/)
  assert.ok(compact.includes('10kΩ · 0603 · 示例品牌 · RC0603-10K'))
  assert.doesNotMatch(compact,/当前物料资料|展开详情|规格型号/)
  assert.doesNotMatch(ready,/收起资料|查看资料/)
  assert.match(await render(1,[resistor],undefined,{compact:false}),/当前物料资料.*收起资料/s)
  assert.match(await render(1,[{id:1,sku:'OLD',name:'旧料',unit:'个'}],undefined,{compact:true}),/详细资料暂不可用/)
  assert.doesNotMatch(await render(0,[resistor],undefined,{compact:true}),/查看资料|物料资料摘要/)
})
