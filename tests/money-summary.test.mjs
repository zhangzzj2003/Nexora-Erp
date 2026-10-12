import assert from 'node:assert/strict'
import { test } from 'node:test'
import { sumMoney, uppercaseMoney } from '../src/renderer/src/utils/money-summary.ts'
import { editPurchasePrice, newPurchasePriceLine, recalculatePurchasePrice } from '../src/renderer/src/utils/purchase-pricing.ts'

// 覆盖跨万、亿的补零，角分与大金额；数字汇总与大写必须来自同一份分位金额。
test('人民币大写正确处理零、连续零、角分和跨组金额',()=>{
  for (const [value, expected] of [
    ['0.00','零元整'],['0.01','零元壹分'],['0.10','零元壹角'],['10.01','壹拾元零壹分'],
    ['1001.50','壹仟零壹元伍角'],['10000.00','壹万元整'],['10001.01','壹万零壹元零壹分'],
    ['100010001.00','壹亿零壹万零壹元整'],['100100000.00','壹亿零壹拾万元整'],
    ['100000001.11','壹亿零壹元壹角壹分'],['100000000000000000.00','壹拾京元整'],
  ]) assert.equal(uppercaseMoney(value),expected,value)
  assert.equal(uppercaseMoney(null),'待完善')
})
test('金额合计不用浮点数，缺价不当零，删除物料即时更新',()=>{
  assert.equal(sumMoney(['0.10','0.20']),'0.30')
  assert.equal(sumMoney(['.1','2e3']),'2000.10')
  assert.equal(sumMoney(Array(100).fill('1000000000000000.00')),'100000000000000000.00')
  assert.equal(sumMoney(['1.00','']),null)
  assert.equal(sumMoney(['1.00',undefined]),null)
  assert.equal(sumMoney([null]),null)
  assert.equal(sumMoney(['1.00','-1.00']),null)
  assert.equal(sumMoney([]),'0.00')
  const rows=[{...newPurchasePriceLine(),quantity:'3'}, {...newPurchasePriceLine(),quantity:'2'}]
  editPurchasePrice(rows[0],'unit_price','.335')
  editPurchasePrice(rows[1],'line_total','10')
  // 总价输入暂未补 .00，也必须按分正确汇总。
  assert.equal(sumMoney(rows.map(row=>row.line_total)),'11.01')
  rows[1].quantity='4';recalculatePurchasePrice(rows[1])
  assert.equal(rows[1].unit_price,'2.5')
  assert.equal(sumMoney(rows.map(row=>row.line_total)),'11.01')
  rows.splice(0,1);assert.equal(sumMoney(rows.map(row=>row.line_total)),'10.00')
})

test('公共表格只在传入合计时显示右下角摘要，大写排在数字之前',async t=>{
  const {createServer}=await import('vite'), {default:vue}=await import('@vitejs/plugin-vue')
  const {createSSRApp,h}=await import('vue'), {renderToString}=await import('@vue/server-renderer')
  const server=await createServer({configFile:false,plugins:[vue()],ssr:{noExternal:['vxe-table']},optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false,ws:false}})
  t.after(()=>server.close())
  const {default:Table}=await server.ssrLoadModule('/src/renderer/src/components/workspace/WorkspaceTable.vue')
  const render=amountTotal=>renderToString(createSSRApp({render:()=>h(Table,{title:'测试表格',data:[],columns:[],amountTotal})}))
  const html=await render('11.01')
  assert.match(html,/物料金额合计/)
  assert.ok(html.indexOf('大写：壹拾壹元零壹分')<html.indexOf('¥ 11.01元'))
  assert.doesNotMatch(await render(undefined),/物料金额合计/)
  assert.match(await render(null),/大写：待完善/)
})
