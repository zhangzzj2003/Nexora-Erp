import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'
import { matchesRecordQuery } from '../src/renderer/src/utils/workspace-records.ts'
import { workspacePageDescriptions } from '../src/renderer/src/utils/workspace-page-copy.ts'
import { workspaceRoutes } from '../src/renderer/src/router/workspace-routes.ts'

test('所有业务页具备卡片外说明，搜索兼容空关键词、编号和空字段', () => {
  for (const route of workspaceRoutes.filter(route => route.key !== 'home')) {
    assert.ok(workspacePageDescriptions[route.key]?.trim(), route.key)
  }
  assert.equal(matchesRecordQuery('   ', []), true)
  assert.equal(matchesRecordQuery(' mat-01 ', [null, undefined, 'MAT-01', '铝材']), true)
  assert.equal(matchesRecordQuery('71', [71]), true)
  assert.equal(matchesRecordQuery('不存在', ['铝材']), false)
  assert.equal(matchesRecordQuery('undefined', [undefined]), false)
})

// 展开真实业务插槽，验证换成表格后仍遵循状态、权限和当前账号保护规则。
const storeModule = `
import {ref} from 'vue'
export const permissions = new Set()
export const state = {
  busy:ref(false), connectionLost:ref(false), error:ref(''), notice:ref(''), server:ref(null), user:ref({id:1,permissions:[]}), activeTab:ref('finance'),
  roles:ref([{code:'admin',label:'管理员'}]), users:ref([{id:1,username:'当前账号',is_active:true,roles:['admin']},{id:2,username:'其他账号',is_active:true,roles:['admin']}]),
  roleDrafts:ref({1:['admin'],2:['admin']}), resetPasswords:ref({1:'sample-password-1',2:'sample-password-2'}), newUser:ref({roles:[]}),
  financeAccounts:ref([]), paymentForm:ref({kind:'receivable'}), reversalReasons:ref({}),
  orderSettlements:ref([]), orderSettlementForm:ref({kind:'receivable',from_order_id:0,to_order_id:0,
    amount:'',reference:'',reason:''}), orderSettlementReversalReasons:ref({}),
  receivablesPayables:ref({receivable_amount:'100',payable_amount:'0',unpriced_count:0,entries:[]}),
  paymentRecords:ref([{id:1,status:'executed',action:'settlement',party_name:'客户A',amount:'100'},{id:2,status:'executed',action:'settlement',party_name:'客户B',amount:'20'},{id:3,action:'reversal',reverses_id:2,amount:'-20'}]),
  workOrders:ref([]), completionForm:ref({}), selectedCompletionOrder:ref(null), completionReversalReasons:ref({}),
  productionCompletions:ref(['draft','inspected','posted','reversed','cancelled'].map((status,i)=>({id:i+1,status,product_name:'测试成品',reported_quantity:'5',accepted_quantity:status==='draft'?null:'4',rejected_quantity:status==='draft'?null:'1',physical_lots:[],approval:{status:status==='inspected'?'approved':'draft'},reversal_approval:{status:status==='posted'?'approved':'draft'}}))),
  inspectionDrafts:ref({1:{accepted_quantity:'4',qc_note:'测试质检'}}),
  productionCostReport:ref({orders:[{work_order_id:1,product_name:'待核价成品',work_order_status:'released',known_material_amount:'0',labor_amount:'0',overhead_amount:'0',total_amount:null,unpriced_issue_count:1}],entries:[{id:1,kind:'labor',status:'active',current_amount:'20'},{id:2,kind:'material',status:'reversed',current_amount:null,reversal_id:3,reversal_reason:'重复核价',material_name:'铝材'}],unpriced_lines:[]}),
  materialValuationForm:ref({}), productionChargeForm:ref({}), costReversalReasons:ref({}),
  productionCostSettlements:ref([]), productionSettlementForm:ref({work_order_id:0,reference:'',note:''}), settlementReversalReasons:ref({}),
  can:p=>permissions.has(p), localTime:v=>v, paymentActionLabel:item=>item.action==='reversal'?'冲销':'收款', financialSource:()=>''
}
export const useAppStore=()=>state
export const usePiniaAppStore=()=>state
`
const tableModule = `
import {defineComponent,h} from 'vue'
export default defineComponent({props:['data','columns','title'],setup(props,{slots}) {
 return ()=>h('section',{'data-table':props.title},[slots.actions?.(),slots.filters?.(),slots.beforeTable?.(),...props.data.map(row=>h('article',{'data-id':row.id},props.columns.map(col=>slots['cell-'+col.key]?.({row})))),props.data.length?null:slots.empty?.()])
}})
`

test('财务冲销、生产质检与账号操作在表格迁移后保留原权限和状态限制', async t => {
  const server = await createServer({configFile:false,plugins:[{
    name:'record-view-fixtures', enforce:'pre',
    resolveId(id,importer) {
      // 批次表的公共封装也引用 WorkspaceTable，继续展开同一份表格绘制替身。
      if(id.endsWith('/WorkspaceTable.vue')) return '\0record-view-table'
      // 本夹具检查页面状态和权限；共用审批弹窗已有真实 Pinia 与接口专项测试。
      if(id.endsWith('/DocumentApprovalDialog.vue') || id.endsWith('/ProductionAssociationDialog.vue')) return '\0record-view-approval'
      if(!importer?.includes('/views/workspace/')) return
      if(id.endsWith('/store/app-store')) return '\0record-view-store'
    },
    load(id) {
      if(id==='\0record-view-store') return storeModule
      if(id==='\0record-view-table') return tableModule
      if(id==='\0record-view-approval') return 'export default {render:()=>null}'
    }
  },vue()],optimizeDeps:{noDiscovery:true,include:[]},server:{middlewareMode:true,hmr:false},appType:'custom'})
  t.after(()=>server.close())
  const {state,permissions}=await server.ssrLoadModule('\0record-view-store')
  const render = async file => {
    const {default:View}=await server.ssrLoadModule('/src/renderer/src/views/workspace/'+file)
    return renderToString(createSSRApp({render:()=>h(View)}))
  }
  // 每个财务页面只保留自己的列表，不再依赖旧 finance 标签键才能显示。
  state.activeTab.value = 'financePayments'
  const financePages = [
    ['finance/ReceivablesPayablesView.vue', ['订单核对']],
    ['finance/PaymentRecordsView.vue', ['收付款与冲销记录', '订单间核销与撤销']],
    ['finance/FinancialSourcesView.vue', ['应收应付来源']]
  ]
  for (const [file, titles] of financePages) {
    const html = await render(file)
    assert.deepEqual([...html.matchAll(/data-table="([^"]+)"/g)].map(match => match[1]), titles)
  }
  const accountHtml = await render(financePages[0][0])
  assert.match(accountHtml, /业务应收净额/)
  assert.doesNotMatch(accountHtml, /建立反向草稿|登记收付款/)
  permissions.add('finance.record')
  const paymentHtml = await render(financePages[1][0])
  assert.match(paymentHtml, /登记收付款/)
  state.connectionLost.value = true
  assert.match(await render(financePages[1][0]), /<button[^>]*disabled[^>]*>[\s\S]*?登记收付款[\s\S]*?<\/button>/)
  state.connectionLost.value = false
  permissions.delete('finance.record')
  const buttons = html => [...html.matchAll(/<button\b([^>]*)>([\s\S]*?)<\/button>/g)].map(m=>({disabled:/(?:^|\s)disabled(?:\s|=|$)/.test(m[1]),label:m[2].replace(/<[^>]*>/g,'').trim()}))
  const finance='finance/PaymentRecordsView.vue'
  assert.doesNotMatch(await render(finance),/建立反向草稿/)
  permissions.add('finance.reverse')
  assert.equal(buttons(await render(finance)).filter(b=>b.label==='建立反向草稿').length,1)
  // 已有反向记录时不允许再次冲销，判断依据始终是完整记录集。
  state.paymentRecords.value.push({id:4,action:'reversal',reverses_id:1})
  assert.equal(buttons(await render(finance)).filter(b=>b.label==='建立反向草稿').length,0)

  const completions='production/ProductionCompletionsView.vue'
  assert.doesNotMatch(await render(completions),/记录质检结果|确认完工|执行已批准冲销/)
  for(const p of ['inspect','post','cancel','reverse']) permissions.add('production_completion.'+p)
  const completionHtml=await render(completions)
  for(const label of ['记录质检结果','确认完工','指定实物批次（可选）','执行已批准冲销']) {
    assert.equal(buttons(completionHtml).filter(b=>b.label===label).length,1,label)
  }
  assert.equal(buttons(completionHtml).filter(b=>b.label==='取消').length,1)
  assert.match(completionHtml,/max="5"/)
  assert.match(completionHtml,/required maxlength="200"/)
  state.productionCompletions.value[1].accepted_quantity='0'
  assert.equal(buttons(await render(completions)).filter(b=>b.label==='确认完工').length,1)
  assert.equal(buttons(await render(completions)).filter(b=>b.label==='指定实物批次（可选）').length,0)
  state.productionCompletions.value[1].accepted_quantity='4'
  state.productionCompletions.value[2].physical_lots=[{id:9,code:'P3-P1',quantity:'4'}]
  assert.match(await render(completions),/P3-P1（4）/)
  state.productionCompletions.value[2].physical_lots=[]
  assert.match(await render(completions),/普通确认未指定实物批次/)

  const costs='production/ProductionCostsView.vue'
  permissions.add('production_cost.reverse')
  const costHtml=await render(costs)
  assert.match(costHtml,/总成本\s*待核价/)
  assert.match(costHtml,/重复核价/)
  assert.equal(buttons(costHtml).filter(b=>b.label==='冲销记录').length,1)

  // 只有有权限且未结算的已完工工单显示结算入口，未核价和断线时禁止提交。
  state.productionCostReport.value.orders = [
    {work_order_id:1,product_name:'可结算',work_order_status:'completed',total_amount:'20',settlement_id:null},
    {work_order_id:2,product_name:'已结算',work_order_status:'completed',total_amount:'20',settlement_id:7},
    {work_order_id:3,product_name:'未核价',work_order_status:'completed',total_amount:null,settlement_id:null},
    {work_order_id:4,product_name:'生产中',work_order_status:'in_progress',total_amount:'20',settlement_id:null}
  ]
  assert.doesNotMatch(await render(costs), /结算完工成本/)
  permissions.add('production_cost.settle')
  const plainButtons = html => buttons(html).map(b=>({...b,label:b.label.replace(/<[^>]*>/g,'').trim()}))
  assert.deepEqual(plainButtons(await render(costs)).filter(b=>b.label==='结算完工成本').map(b=>b.disabled),[false,true])
  state.connectionLost.value = true
  assert.ok(plainButtons(await render(costs)).filter(b=>b.label==='结算完工成本').every(b=>b.disabled))
  state.connectionLost.value = false
  state.productionCostReport.value.entries[0].work_order_id = 1
  state.productionCostSettlements.value = [{id:7,work_order_id:1,status:'active',allocations:[],material_sources:[],charges:[]}]
  assert.equal(buttons(await render(costs)).filter(b=>b.label==='冲销记录').length,0)

  const users='system/UserManagementView.vue'
  const userButtons=buttons(await render(users))
  assert.deepEqual(userButtons.filter(b=>b.label==='重置密码').map(b=>b.disabled),[true,false])
  const userHtml = await render(users)
  assert.doesNotMatch(userHtml, /type="password"|type="checkbox"|保存角色/)
  assert.match(userHtml, /role="switch"/)
  // 重置入口不依赖密码草稿；只有弹窗提交需要校验密码长度。
  state.resetPasswords.value[2]='short'
  assert.deepEqual(buttons(await render(users)).filter(b=>b.label==='重置密码').map(b=>b.disabled),[true,false])
  state.busy.value=true
  assert.ok(buttons(await render(completions)).every(b=>b.disabled))
  assert.ok(buttons(await render(users)).every(b=>b.disabled))
})
