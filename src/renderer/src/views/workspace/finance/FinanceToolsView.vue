<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { NInput, NDatePicker } from 'naive-ui'
import AppInput from '../../../components/app/AppInput.vue'
import AppButton from '../../../components/app/AppButton.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import type { FinanceToolAction } from '../../../../../shared/erp-api'

// 草稿只在本页面编辑，正式处理和跨页面结果通过 Pinia 与受限 API 保存。
const store=usePiniaAppStore()
const { financeToolResult: result, busy, error, connectionLost, user }=storeToRefs(store)
const action=ref<FinanceToolAction>('openings')
const choices: {value:FinanceToolAction;label:string}[]=[
  {value:'openings',label:'往来期初'}, {value:'create_opening',label:'录入往来期初'},
  {value:'confirm_opening',label:'确认期初'}, {value:'cancel_opening',label:'作废期初'},
  {value:'settle_opening',label:'结算期初'}, {value:'reconcile',label:'期初与总账核对'},
  {value:'banks',label:'银行流水'}, {value:'import_bank',label:'导入银行流水'},
  {value:'match_bank',label:'匹配收付款'}, {value:'unmatch_bank',label:'解除匹配'},
  {value:'statements',label:'资产负债与利润'}, {value:'auxiliary',label:'辅助核算'}, {value:'history',label:'处理审计'}]
const form=ref({id:0,kind:'receivable',party_id:0,ledger_account_id:0,payment_id:0,amount:'',reference:'',reason:'',bank_account:'',effective_date:'',from_date:'',to_date:'',dimension:'department',bankRows:''})
const write=computed(()=>['create_opening','confirm_opening','cancel_opening','settle_opening','import_bank','match_bank','unmatch_bank'].includes(action.value))
const permission=computed(()=>['cancel_opening','unmatch_bank'].includes(action.value)?'finance.reverse':write.value?'finance.record':'finance.view')
const hasId=computed(()=>['confirm_opening','cancel_opening','settle_opening','match_bank','unmatch_bank'].includes(action.value))
const columns=computed(()=>result.value?.columns ?? [])
const titles: Record<string,string>={id:'编号',kind:'往来类型',party_id:'单位编号',party_name:'单位名称',effective_date:'启用日期',amount:'金额',reference:'参考号',status:'状态',outstanding_amount:'未结金额',settled_amount:'已结金额',ledger_account_id:'总账科目',bank_account:'银行账号',statement_date:'银行日期',payment_id:'收付款编号',reason:'原因',created_at:'时间',created_by:'操作账号',code:'科目编码',name:'科目名称',difference:'差额',party_opening:'往来期初',ledger_opening:'总账期初',statement:'报表',category:'科目类别',journal_id:'凭证编号',account_code:'科目编码',account_name:'科目名称',dimension:'维度',value:'辅助项目',debit:'借方',credit:'贷方',balance:'余额',action:'操作',record_id:'业务编号',evidence_json:'审计证据'}
const shownColumns=computed(()=>columns.value.map(item=>({...item,title:titles[item.key]??item.title})))
watch(()=>`${user.value?.id}:${user.value?.permissions.join('|')}`,()=>{result.value=null;form.value.reason='';form.value.bankRows=''}, {flush:'sync'})
watch(action,()=>{result.value=null})
async function run():Promise<void>{
  if (!store.can(permission.value)||connectionLost.value)return
  let payload:Record<string,unknown>={}
  const f=form.value
  if(action.value==='create_opening')payload={kind:f.kind,party_id:f.party_id,ledger_account_id:f.ledger_account_id,effective_date:f.effective_date,amount:f.amount,reference:f.reference,reason:f.reason}
  else if(hasId.value)payload={id:f.id,reason:f.reason,...action.value==='settle_opening'?{amount:f.amount,reference:f.reference}:{},...action.value==='match_bank'?{payment_id:f.payment_id}:{}}
  else if(action.value==='import_bank'){
    // 银行复制数据按制表符分列，一次最多一百行，金额方向保持原始正负值。
    const rows=f.bankRows.trim().split('\n').filter(Boolean).map(line=>{const [statement_date,amount,reference]=line.split('\t');return {bank_account:f.bank_account,statement_date,amount,reference}})
    payload={rows,reason:f.reason}
  }else if(['statements','auxiliary'].includes(action.value))payload={from_date:f.from_date,to_date:f.to_date,dimension:f.dimension}
  await store.runFinanceTool(action.value,payload)
}
</script>
<template>
  <section class="page-header"><h1>财务核对</h1><p>人民币口径。往来期初与总账期初分别录入并核对；银行匹配仅核对收付款，不自动生成凭证。</p></section>
  <form class="card" @submit.prevent="run">
    <div class="form-grid">
      <label>处理事项<WorkspaceSelect v-model="action" :options="choices" :disabled="busy" /></label>
      <template v-if="action==='create_opening'">
        <label>往来类型<WorkspaceSelect v-model="form.kind" :options="[{value:'receivable',label:'应收'},{value:'payable',label:'应付'}]" /></label>
        <label>往来单位<WorkspaceSelect v-model="form.party_id" :remote-dataset="form.kind==='receivable'?'financeCustomers':'suppliers'" :options="[{value:0,label:'选择往来单位',disabled:true}]" required /></label>
        <label>核对总账科目<WorkspaceSelect v-model="form.ledger_account_id" remote-dataset="ledgerAccounts" :options="[{value:0,label:'选择科目',disabled:true}]" required /></label>
        <label>启用日期<NDatePicker type="date" value-format="yyyy-MM-dd" :formatted-value="form.effective_date || null" @update:formatted-value="value=>{form.effective_date=typeof value==='string'?value:''}" /></label>
      </template>
      <label v-if="hasId">{{ action.includes('bank')?'银行流水编号':'期初编号' }}<AppInput v-model.number="form.id" type="number" min="1" required /></label>
      <label v-if="action==='match_bank'">收付款编号<AppInput v-model.number="form.payment_id" type="number" min="1" required /></label>
      <template v-if="action==='create_opening'||action==='settle_opening'"><label>金额（负数表示贷方或退款）<AppInput v-model="form.amount" required inputmode="decimal" /></label><label>参考号<AppInput v-model.trim="form.reference" required maxlength="100" /></label></template>
      <template v-if="action==='statements'||action==='auxiliary'">
        <label>开始日期<NDatePicker type="date" value-format="yyyy-MM-dd" :formatted-value="form.from_date || null" @update:formatted-value="value=>{form.from_date=typeof value==='string'?value:''}" /></label>
        <label>结束日期<NDatePicker type="date" value-format="yyyy-MM-dd" :formatted-value="form.to_date || null" @update:formatted-value="value=>{form.to_date=typeof value==='string'?value:''}" /></label>
        <label v-if="action==='auxiliary'">辅助维度<WorkspaceSelect v-model="form.dimension" :options="[{value:'customer_id',label:'客户'},{value:'supplier_id',label:'供应商'},{value:'department',label:'部门'},{value:'project',label:'项目'}]" /></label>
      </template>
      <label v-if="action==='import_bank'">银行账号<AppInput v-model.trim="form.bank_account" required maxlength="80" /></label>
      <label v-if="write">处理原因<AppInput v-model.trim="form.reason" required maxlength="200" /></label>
    </div>
    <label v-if="action==='import_bank'">银行流水（每行：日期、带正负号的金额、唯一参考号；用制表符分隔）<NInput v-model:value="form.bankRows" type="textarea" :rows="6" placeholder="2026-10-01&#9;100.00&#9;BANK-001" /></label>
    <div class="form-actions"><AppButton type="submit" :disabled="busy||connectionLost||!store.can(permission)">{{ busy?'处理中…':write?'保存处理':'查询' }}</AppButton></div>
    <p v-if="error" role="alert">{{ error }}</p>
  </form>
  <section v-if="result" class="card"><p>查询口径：已确认期初、已过账凭证；未结账期间的结果可能变化。利润表排除损益结转分录，成本余额单独列入资产核对。</p><div class="form-grid"><p v-for="(value,key) in result.totals" :key="key">{{ ({assets:'资产合计',liabilities:'负债合计',equity_with_current_profit:'含本期损益的权益',revenue:'收入',expense:'费用',net_profit:'净利润',balance_difference:'资产负债差额',trial_balanced:'试算平衡',unmatched:'未匹配数',imported:'导入条数',unpriced_business_sources:'缺价业务数'} as Record<string,string>)[key]??key }}：{{ value }}</p></div></section>
  <WorkspaceTable v-if="result" title="财务核对结果" :snapshot-id="result.snapshot_id" :columns="shownColumns" :data="result.rows" :min-table-width="1100"><template #actions><AppButton :disabled="busy" @click="store.exportFinanceTool()">导出 CSV</AppButton></template></WorkspaceTable>
</template>
