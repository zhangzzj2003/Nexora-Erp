import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { lotAllocation } from '../src/renderer/src/utils/lot-allocation.ts'

const parts = (...values) => values.map(quantity => ({ quantity }))
test('批次数量核对使用精确小数，覆盖拆分、超量、负差异与无效输入', () => {
  assert.deepEqual(lotAllocation('0.3', parts('0.1', '0.2')), { expected: '0.3', allocated: '0.3', remaining: '0', status: 'complete' })
  assert.equal(lotAllocation('100', parts('40', '20.125')).remaining, '39.875')
  assert.equal(lotAllocation('100', parts('100.001')).status, 'over')
  assert.equal(lotAllocation('100', parts('100.001')).remaining, '0.001')
  assert.equal(lotAllocation('-2.125', parts('2', '0.125')).status, 'complete')
  for (const value of ['', '0', '-1', '1e2', '1.0001', '1000000.001']) {
    assert.equal(lotAllocation('100', parts('40', value)).status, 'invalid', value)
  }
  assert.equal(lotAllocation('bad', parts('1')).expected, '—')
  assert.equal(lotAllocation('10', []).status, 'invalid')
  // 分批收货允许暂不登记某物料，其他十类单据继续要求至少一批。
  assert.equal(lotAllocation('10', [], true).status, 'incomplete')
  assert.equal(lotAllocation('10', [], true).remaining, '10')
  assert.equal(lotAllocation('20000000', parts(...Array(20).fill('1000000'))).status, 'complete')
})

// 仅替换基础控件的绘制层；公共组件的计算、行对象和事件保护均使用真实实现。
const modalStub = `import {defineComponent,h} from 'vue';export const captured={};
export const NModal=defineComponent({props:['show','title','closable','closeOnEsc','maskClosable'],setup(p,{slots,attrs}){
 Object.assign(captured,{p,slots,attrs});return ()=>p.show?h('section',{...attrs,'data-closable':p.closable,'data-esc':p.closeOnEsc},[h('h2',p.title),slots.default?.(),slots.footer?.()]):null}});
export const NDatePicker=defineComponent({props:['formattedValue','disabled','inputProps'],setup(p,{attrs}){return ()=>h('input',{...attrs,...p.inputProps,'data-date':true,value:p.formattedValue,disabled:p.disabled})}});`
const tableStub = `import {defineComponent,h} from 'vue';export const capturedTable={};export default defineComponent({props:['data','columns','title'],setup(p,{slots}){
Object.assign(capturedTable,{p,slots});return ()=>h('table',[h('thead',p.columns.map(c=>h('th',c.title))),h('tbody',p.data.map(row=>h('tr',p.columns.map(c=>h('td',slots['cell-'+c.key]?.({row}))))))])}});`
const buttonStub = `import {defineComponent,h} from 'vue';export default defineComponent({props:['type','disabled','loading'],setup(p,{slots,attrs}){return ()=>h('button',{...attrs,type:p.type,disabled:p.disabled},slots.default?.())}});`
const inputStub = `import {defineComponent,h} from 'vue';export default defineComponent({props:['modelValue','disabled'],setup(p,{attrs}){return ()=>h('input',{...attrs,value:p.modelValue,disabled:p.disabled})}});`
const selectStub = `import {defineComponent,h} from 'vue';export default defineComponent({props:['modelValue','disabled','options','ariaLabel'],setup(p){return ()=>h('select',{'aria-label':p.ariaLabel,disabled:p.disabled},p.options.map(o=>h('option',{value:o.value},o.label)))}});`
async function environment(t) {
  const server = await createServer({ configFile: false, plugins: [{ name: 'lot-dialog-test', enforce: 'pre',
    transform(code, id) {
      // 控件库默认作为外部依赖加载，显式替换路径后才能在 SSR 测试中展开日期与弹窗。
      if (id.includes('/components/workspace/')) return code.replace(/'naive-ui'/g, "'virtual:lot-modal'")
    },
    resolveId(id) {
      if (id === 'virtual:lot-modal') return '\0lot-modal'
      for (const [suffix, virtual] of [['WorkspaceTable.vue','table'],['AppButton.vue','button'],['AppInput.vue','input'],['WorkspaceSelect.vue','select']]) {
        if (id.endsWith('/'+suffix)) return '\0lot-'+virtual
      }
    }, load(id) { return {'\0lot-modal':modalStub,'\0lot-table':tableStub,'\0lot-button':buttonStub,'\0lot-input':inputStub,'\0lot-select':selectStub}[id] }
  }, vue()], optimizeDeps: { noDiscovery: true, include: [] }, server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  t.after(() => server.close())
  const load = name => server.ssrLoadModule('/src/renderer/src/components/workspace/'+name+'.vue')
  return { server, load }
}

test('批次表保留草稿对象，新增删除遵守禁用、单行和二十批次限制', async t => {
  const { server, load } = await environment(t)
  const { default: Editor } = await load('WorkspaceLotLineEditor')
  const lots = [{ quantity:'0.125',supplier_lot:null,manufactured_on:null,expires_on:null }]
  const base = { lots, sku:'EL-01', materialName:'排针', expected:'0.125', unit:'条' }
  const render = extra => renderToString(createSSRApp({render:()=>h(Editor,{...base,...extra})}))
  const html = await render({})
  assert.match(html,/数量已核对/)
  assert.match(html,/来源批号（可选）/)
  assert.equal((html.match(/data-date="true"/g)??[]).length,2)
  assert.match(html,/EL-01 第 1 行批次数量/)
  let adds=0,removes=0
  const vnode=h(Editor,{...base,onAdd:()=>adds++,onRemove:()=>removes++})
  await renderToString(createSSRApp({render:()=>vnode}))
  const { capturedTable } = await server.ssrLoadModule('\0lot-table')
  assert.equal(capturedTable.p.data[0].part,lots[0])
  const row=capturedTable.p.data[0]
  capturedTable.slots['cell-quantity']({row})[0].props['onUpdate:modelValue']('0.124')
  assert.equal(lots[0].quantity,'0.124')
  const remove=capturedTable.slots['cell-actions']({row})[0].props.onClick
  remove();assert.equal(removes,0)
  vnode.component.props.lots.push({quantity:'0.001'})
  remove();assert.equal(removes,1)
  // 直接调用已渲染的事件也不能绕过禁用保护。
  const bindings=vnode.component.setupState
  bindings.add();assert.equal(adds,1)
  vnode.component.props.disabled=true
  bindings.add();remove();assert.equal(adds,1);assert.equal(removes,1)
  vnode.component.props.disabled=false
  while(lots.length<20)lots.push({quantity:'0.001'})
  bindings.add();assert.equal(adds,1)
})

test('已有批次与新批次使用不同列，退货和盘盈保留原选择值及日期', async t => {
  const {load}=await environment(t)
  const {default:Editor}=await load('WorkspaceLotLineEditor')
  const existing={lot_id:7,quantity:'1',supplier_lot:null,manufactured_on:null,expires_on:null}
  const fresh={lot_id:null,quantity:'1',supplier_lot:'LABEL',manufactured_on:'2026-10-07',expires_on:null}
  const base={sku:'A',lots:[existing,fresh],expected:'2',selectable:true,newLotValue:null,
    options:[{label:'登记退货新批次',value:null},{label:'原出库批次 · 可退 1',value:7}]}
  const render=extra=>renderToString(createSSRApp({render:()=>h(Editor,{...base,...extra})}))
  const mixed=await render({})
  assert.equal((mixed.match(/data-date="true"/g)??[]).length,2)
  assert.match(mixed,/value="LABEL"/)
  assert.match(mixed,/沿用原批次/)
  assert.match(mixed,/原出库批次 · 可退 1/)
  const outbound=await render({newLotValue:undefined,lots:[existing]})
  assert.doesNotMatch(outbound,/生产日期|来源批号|data-date/)
  assert.doesNotMatch(await render({selectable:false,showSource:false}),/来源批号（可选）/)
  const surplus=await render({newLotValue:-1,lots:[{...fresh,lot_id:-1}],expected:'-1'})
  assert.match(surplus,/value="LABEL"/)
  assert.match(surplus,/数量已核对/)
})

test('批次弹窗固定标题和页脚，禁止错误、读取中、断线或重复提交并保留输入', async t => {
  const {server,load}=await environment(t)
  const {default:Dialog}=await load('WorkspaceLotDialog')
  const base={show:true,title:'其他入库 · 批次登记',documentNumber:'QTRK-001',hint:'按实际批次填写',submitLabel:'确认入库'}
  let submits=0,closes=0
  const vnode=h(Dialog,{...base,onSubmit:()=>submits++,'onUpdate:show':()=>closes++},{default:()=>h('input',{value:'批次草稿'})})
  const html=await renderToString(createSSRApp({render:()=>vnode}))
  assert.match(html,/其他入库 · 批次登记 · QTRK-001/)
  assert.ok(html.indexOf('批次草稿')<html.indexOf('<footer'))
  const {captured}=await server.ssrLoadModule('\0lot-modal')
  const form=captured.slots.default()[0]
  const submit=()=>form.props.onSubmit({preventDefault(){}})
  const close=()=>captured.attrs['onUpdate:show'](false)
  submit();assert.equal(submits,1)
  for(const [prop,value] of [['busy',true],['disabled',true],['loading',true],['loadError','读取失败'],['issue','数量不一致']]){
    vnode.component.props[prop]=value;submit();assert.equal(submits,1)
    vnode.component.props[prop]=typeof value==='string'?'':false
  }
  vnode.component.props.busy=true;close();assert.equal(closes,0)
  vnode.component.props.busy=false;close();assert.equal(closes,1)
  assert.match(await renderToString(createSSRApp({render:()=>h(Dialog,{...base,busy:true})})),/data-closable="false" data-esc="false"/)
})
