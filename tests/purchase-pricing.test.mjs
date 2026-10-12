import assert from 'node:assert/strict'
import { test } from 'node:test'
import { effectScope, ref } from 'vue'
import { purchasePrice, recalculatePurchasePrice, editPurchasePrice, newPurchasePriceLine,
  restorePurchasePrice, purchasePricePayload, proratePurchaseTotal } from '../src/renderer/src/utils/purchase-pricing.ts'
import { useDocumentMaterialDetails } from '../src/renderer/src/composables/use-document-material-details.ts'

// 金额计算覆盖二进制浮点易错点、零价及最大可接受范围。
test('按单价算总价使用十进制四舍五入', () => {
  assert.equal(purchasePrice('3', 'unit_price', '0.335'), '1.01')
  assert.equal(purchasePrice('1e3', 'unit_price', '.5'), '500.00')
  assert.equal(purchasePrice('1000', 'unit_price', '0.0001'), '0.10')
  assert.equal(purchasePrice('1000000', 'unit_price', '1000000000'), '1000000000000000.00')
  assert.equal(purchasePrice('0.001', 'unit_price', '0'), '0.00')
})
test('总价保持输入金额，反算十二位单价并随数量更新', () => {
  const line = {...newPurchasePriceLine(), pricing_mode:'total', quantity:'3000', line_total:'10.00'}
  recalculatePurchasePrice(line)
  assert.equal(line.unit_price,'0.003333333333')
  line.quantity='6000';recalculatePurchasePrice(line)
  assert.equal(line.unit_price,'0.001666666667')
  assert.equal(line.line_total,'10.00')
  assert.deepEqual(purchasePricePayload(line),{pricing_mode:'total',line_total:'10.00'})
  editPurchasePrice(line,'unit_price','0.0017')
  assert.equal(line.unit_price,'0.0017');assert.equal(line.line_total,'10.20')
  line.quantity='3000';recalculatePurchasePrice(line);assert.equal(line.line_total,'5.10')
  editPurchasePrice(line,'line_total','')
  assert.equal(line.unit_price,'');assert.equal(line.line_total,'')
  assert.deepEqual(purchasePricePayload(line),{pricing_mode:'unit_price'})
})
test('空值、零数量、负数、非有限值与越界不生成伪造的金额', () => {
  for (const quantity of ['', '0', '-1','NaN','Infinity','1.0001','1000001']) {
    assert.equal(purchasePrice(quantity, 'total', '5'), '')
    assert.equal(purchasePrice(quantity, 'unit_price', '5'), '')
  }
  for (const source of ['', '-1', 'NaN','Infinity','1.001','1000000000000001']) {
    assert.equal(purchasePrice('1', 'total',source), '')
  }
  assert.equal(purchasePrice('1','unit_price','0.00001'),'')
  assert.equal(purchasePrice('0.001','total','1000000.01'),'')
  assert.equal(purchasePrice('3','total','0'),'0')
})
test('旧申请未定价保持空值，恢复草稿与按剩余数量带入总额', () => {
  const old = restorePurchasePrice({quantity:'3'})
  assert.equal(old.unit_price,'');assert.equal(old.line_total,'')
  assert.deepEqual(purchasePricePayload(old),{pricing_mode:'unit_price'})
  const total = proratePurchaseTotal('10.00','3','1')
  assert.equal(total,'3.33')
  const restored = restorePurchasePrice({quantity:'1',pricing_mode:'total',line_total:total})
  assert.equal(restored.unit_price,'3.33')
  assert.equal(proratePurchaseTotal('0.01','3','1.5'),'0.01')
})
test('共享收缩逻辑保留价格行引用，删除和换草稿后不会指向旧行', () => {
  const scope = effectScope()
  const lines = ref([{...newPurchasePriceLine(), material_id:1}, {...newPurchasePriceLine(), material_id:2}])
  const details = scope.run(()=>useDocumentMaterialDetails(()=>lines.value))
  assert.equal(details.activeLine.value,lines.value[1])
  details.showLine(lines.value[0]);const retained=lines.value[0]
  lines.value.splice(1,1);assert.equal(details.activeLine.value,retained)
  details.setCompact(retained,true);assert.equal(details.activeLine.value,null)
  details.setCompact(retained,false);retained.unit_price='2';recalculatePurchasePrice(retained)
  assert.equal(lines.value[0].line_total,'2.00')
  lines.value=[newPurchasePriceLine()];assert.equal(details.activeLine.value,lines.value[0])
  scope.stop()
})

test('采购动作保存算法依据，失败保留草稿，转单过滤零数量', async t => {
  const { createServer } = await import('vite')
  const server=await createServer({configFile:false,optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false,ws:false}})
  t.after(()=>server.close())
  const {createPurchaseActions}=await server.ssrLoadModule('/src/renderer/src/store/modules/purchase-actions.ts')
  const {createAppState}=await server.ssrLoadModule('/src/renderer/src/store/state.ts')
  const state=createAppState(), calls=[]
  const original=globalThis.window
  t.after(()=>{globalThis.window=original})
  let fail=true
  globalThis.window={nexora:{callApi:async (operation,payload)=>{
    calls.push([operation,payload]);if(fail)throw Error('保存失败')
  }}}
  const actions=createPurchaseActions(state,async action=>{try{await action()}catch{state.error.value='保存失败'}})
  state.purchaseRequestForm.value.lines=[{...newPurchasePriceLine(),material_id:1,pricing_mode:'total',quantity:'3',line_total:'10.00',unit_price:'3.333333333333'}]
  const draft=state.purchaseRequestForm.value.lines[0]
  await actions.savePurchaseRequest()
  assert.equal(state.purchaseRequestForm.value.lines[0],draft)
  assert.deepEqual(calls[0][1].lines,[{material_id:1,quantity:'3',pricing_mode:'total',line_total:'10.00'}])
  fail=false;await actions.savePurchaseRequest()
  assert.equal(state.purchaseRequestForm.value.lines[0].material_id,0)
  state.purchaseRequests.value=[{id:7,reference:'',note:'',lines:[{id:11,material_id:1,quantity:'3',remaining_quantity:'2',pricing_mode:'total',unit_price:'3.333333333333',line_total:'10.00'}]}]
  actions.selectRequestConversion(7)
  assert.equal(state.requestConversionForm.value.lines[0].line_total,'6.67')
  state.requestConversionForm.value.lines.push({...newPurchasePriceLine(),material_id:2,purchase_request_line_id:12,quantity:'0'})
  await actions.convertPurchaseRequest()
  assert.equal(calls.at(-1)[1].lines.length,1)
  assert.deepEqual(calls.at(-1)[1].lines[0],{material_id:1,purchase_request_line_id:11,quantity:'2',pricing_mode:'total',line_total:'6.67'})
})
