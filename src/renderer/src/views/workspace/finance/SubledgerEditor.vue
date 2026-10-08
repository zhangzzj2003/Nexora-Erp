<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { NDatePicker } from 'naive-ui'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { dateOutsideRange, datePickerString, vDateField } from '../../../utils/date-field'
import type { SubledgerKind, SubledgerLineInput, SubledgerInput } from '../../../../../shared/erp-api'
import AuxiliarySelector from './AuxiliarySelector.vue'
import { subledgerDraftError, subledgerKindLabels } from './subledger-display'

const store = usePiniaAppStore()
const { subledgerForm: form, subledgerOptions: options, busy, connectionLost, error } = storeToRefs(store)
const emit = defineEmits<{ saved: [] }>()
const effective = computed(() => options.value?.opening_balance?.effective_date ?? '')
const problem = computed(() => subledgerDraftError(form.value, effective.value) ||
  (form.value.control_accounts.some(item => !options.value?.accounts.some(account => account.id === item.account_id && account.is_active))
    ? '控制科目已停用或不可用，请重新读取选项；调整原单归属后再移除该科目。' : ''))
const ready = computed(() => options.value?.opening_balance?.status === 'confirmed' && !problem.value && !busy.value && !connectionLost.value)
const kinds = ['receivable','payable'] as const
type Control = SubledgerInput['control_accounts'][number]
const controlColumns = [{key:'kind',title:'类别',width:'160'}, {key:'account_id',title:'控制科目',width:'300'},
  {key:'usage',title:'原单使用情况',width:'260'}, {key:'actions',title:'操作',width:'90'}]
const pastDate = computed(() => effective.value ? new Date(Date.parse(effective.value + 'T12:00:00Z') - 86400000).toISOString().slice(0,10) : '')
const columns = [{key:'position',title:'序号',width:'60'}, {key:'kind',title:'类别',width:'150'}, {key:'account_id',title:'控制科目',width:'220'}, {key:'party_id',title:'往来对象',width:'220'},
  {key:'document_reference',title:'原始单据编号',width:'180'}, {key:'document_date',title:'原单日期',width:'180'},
  {key:'debit',title:'借方（元）',width:'140'}, {key:'credit',title:'贷方（元）',width:'140'},
  {key:'auxiliary',title:'部门与项目',width:'280'}, {key:'actions',title:'操作',width:'90'}]
const number = (row: SubledgerLineInput) => form.value.lines.indexOf(row) + 1
const controlNumber = (row: Control) => form.value.control_accounts.indexOf(row) + 1
const usage = (row: Control) => row.account_id > 0 ? form.value.lines.filter(item => item.kind === row.kind && item.account_id === row.account_id).length : 0
const selectedAccounts = (kind: SubledgerKind) => form.value.control_accounts.filter(item => item.kind === kind && item.account_id > 0)
const account = (kind: SubledgerKind) => selectedAccounts(kind).length === 1 ? selectedAccounts(kind)[0]!.account_id : 0
function controlOptions(row: Control) {
  const accounts = (options.value?.accounts ?? []).filter(item => item.is_active &&
    !form.value.control_accounts.some(other => other !== row && other.account_id === item.id))
    .map(item => ({value:item.id,label:`${item.code} · ${item.name}`,disabled:false}))
  if (row.account_id > 0 && !accounts.some(item => item.value === row.account_id)) {
    accounts.push({value:row.account_id,label:`科目 #${row.account_id}（不可用，请重新核对）`,disabled:true})
  }
  return [{value:0,label:'选择控制科目',disabled:true},...accounts]
}
function lineAccounts(kind: SubledgerKind) {
  return [{value:0,label:'选择原单控制科目',disabled:true},...selectedAccounts(kind).map(item => {
    const selected = options.value?.accounts.find(account => account.id === item.account_id)
    return {value:item.account_id,label:selected ? `${selected.code} · ${selected.name}` : `科目 #${item.account_id}（不可用）`,disabled:!selected?.is_active}
  })]
}
function addControl(kind: SubledgerKind): void {
  if (!busy.value && !connectionLost.value && form.value.control_accounts.length < 500) form.value.control_accounts.push({kind,account_id:0})
}
function setAccount(row: Control, value: number): void {
  if (busy.value || connectionLost.value) return
  if (usage(row)) { error.value = '该控制科目仍有原单使用，请先逐张调整原单科目。'; return }
  if (controlOptions(row).some(item => item.value === value && !item.disabled)) row.account_id = value
}
function removeControl(row: Control): void {
  if (busy.value || connectionLost.value) return
  if (usage(row)) { error.value = '该控制科目仍有原单使用，请先逐张调整或删除原单。'; return }
  const index = form.value.control_accounts.indexOf(row)
  if (index >= 0) form.value.control_accounts.splice(index,1)
}
function setKind(row: SubledgerLineInput, value: SubledgerKind): void { row.kind=value; row.party_id=0; row.account_id=account(value) }
function parties(kind: SubledgerKind) {
  return [{value:0,label:'选择往来对象',disabled:true},...(options.value?.auxiliary_items ?? [])
    .filter(item=>item.kind===(kind==='receivable'?'customer':'supplier')).map(item=>({value:item.id,label:item.name}))]
}
function addLine(): void {
  if (busy.value || connectionLost.value || form.value.lines.length >= 500) return
  const kind = form.value.control_accounts.find(item => item.account_id > 0)?.kind
  if (!kind) return
  form.value.lines.push({kind,account_id:account(kind),party_id:0,document_reference:'',document_date:'',debit:'0',credit:'0',auxiliary:[]})
}
async function save(): Promise<void> { if (ready.value && await store.saveSubledger()) emit('saved') }
</script>

<template>
  <form class="ledger-editor" @submit.prevent="save">
    <p>历史未结单据须早于启用日 {{ effective || '尚无已确认总账期初' }}。只填借或贷一方；客户贷方、供应商借方表示可退余额。分户明细不要求独立借贷平衡，提交时逐完整辅助组合核对总账。</p>
    <p v-if="options?.opening_balance?.status !== 'confirmed'" role="alert">请先独立审核并确认总账期初。</p>
    <div class="form-grid">
      <label>依据编号<AppInput v-model.trim="form.reference" required maxlength="80" :disabled="busy || connectionLost" /></label>
      <label>建立依据 / 修改原因<AppInput v-model.trim="form.reason" required maxlength="200" :disabled="busy || connectionLost" /></label>
      <label>备注<AppInput v-model.trim="form.note" maxlength="500" :disabled="busy || connectionLost" /></label>
    </div>
    <WorkspaceTable class="journal-line-editor" title="往来控制科目" description="同一类别可添加多个科目，每张原单单独选择。正在使用的科目须先调整原单归属，才能更换或删除。" :columns="controlColumns" :data="form.control_accounts" :min-table-width="810">
      <template #actions><AppButton v-for="kind in kinds" :key="kind" type="button" :disabled="busy || connectionLost || form.control_accounts.length >= 500" @click="addControl(kind)">{{ kind === 'receivable' ? '添加应收科目' : '添加应付科目' }}</AppButton></template>
      <template #cell-kind="{row}">{{ subledgerKindLabels[row.kind] }}</template>
      <template #cell-account_id="{row}"><WorkspaceSelect :model-value="row.account_id" :options="controlOptions(row)" :aria-label="`第 ${controlNumber(row)} 个控制科目`" required :disabled="busy || connectionLost || usage(row) > 0" @update:model-value="value=>setAccount(row,value)" /></template>
      <template #cell-usage="{row}">{{ usage(row) ? `${usage(row)} 张原单使用中` : '尚未用于原单' }}</template>
      <template #cell-actions="{row}"><AppButton variant="text" type="button" :aria-label="`删除第 ${controlNumber(row)} 个控制科目`" :disabled="busy || connectionLost || usage(row) > 0" @click="removeControl(row)">删除</AppButton></template>
      <template #empty>添加需要纳管的应收或应付科目，再逐张录入历史未结单据。</template>
    </WorkspaceTable>
    <WorkspaceTable class="journal-line-editor" title="历史未结单据" :columns="columns" :data="form.lines" :min-table-width="1760">
      <template #actions><AppButton type="button" :disabled="busy || connectionLost || !form.control_accounts.some(item => item.account_id > 0) || form.lines.length >= 500" @click="addLine">添加未结单据</AppButton></template>
      <template #cell-position="{row}">{{ number(row) }}</template>
      <template #cell-kind="{row}"><WorkspaceSelect :model-value="row.kind" :options="kinds.map(value=>({value,label:subledgerKindLabels[value]}))" :aria-label="`第 ${number(row)} 行类别`" :disabled="busy || connectionLost" @update:model-value="value=>setKind(row,value)" /></template>
      <template #cell-account_id="{row}"><WorkspaceSelect v-model="row.account_id" :options="lineAccounts(row.kind)" :aria-label="`第 ${number(row)} 行控制科目`" required :disabled="busy || connectionLost" /></template>
      <template #cell-party_id="{row}"><WorkspaceSelect v-model="row.party_id" :options="parties(row.kind)" :aria-label="`第 ${number(row)} 行往来对象`" required :disabled="busy || connectionLost" /></template>
      <template #cell-document_reference="{row}"><AppInput v-model.trim="row.document_reference" :aria-label="`第 ${number(row)} 行原单编号`" maxlength="80" required :disabled="busy || connectionLost" /></template>
      <template #cell-document_date="{row}"><NDatePicker :formatted-value="row.document_date || null" type="date" format="yyyy-MM-dd" value-format="yyyy-MM-dd" :disabled="busy || connectionLost" :is-date-disabled="(timestamp: number)=>dateOutsideRange(timestamp,undefined,pastDate)" v-date-field="{required:true,max:pastDate}" :aria-label="`第 ${number(row)} 行原单日期`" @update:formatted-value="value=>{row.document_date=datePickerString(value)}" /></template>
      <template #cell-debit="{row}"><AppInput v-model="row.debit" :aria-label="`第 ${number(row)} 行借方`" inputmode="decimal" pattern="[0-9]{1,12}(\.[0-9]{1,2})?" required :disabled="busy || connectionLost" /></template>
      <template #cell-credit="{row}"><AppInput v-model="row.credit" :aria-label="`第 ${number(row)} 行贷方`" inputmode="decimal" pattern="[0-9]{1,12}(\.[0-9]{1,2})?" required :disabled="busy || connectionLost" /></template>
      <template #cell-auxiliary="{row}"><AuxiliarySelector v-model="row.auxiliary" :kinds="['department','project']" :items="options?.auxiliary_items" :policy="options?.auxiliary_policies.find(item=>item.account_id===row.account_id)" :date="effective" :label-prefix="`第 ${number(row)} 行`" :disabled="busy || connectionLost" /></template>
      <template #cell-actions="{row}"><AppButton variant="text" type="button" :aria-label="`删除第 ${number(row)} 行`" :disabled="busy || connectionLost" @click="form.lines.splice(number(row)-1,1)">删除</AppButton></template>
      <template #empty>先选择控制科目，再添加历史未结单据。对应科目全部为零时可保存空明细，提交时仍须核对总账。</template>
    </WorkspaceTable>
    <p v-if="problem" role="status">{{ problem }}</p><p v-if="error" role="alert">{{ error }}</p>
    <AppButton type="submit" variant="primary" :disabled="!ready">{{ busy ? '正在保存…' : '保存分户草稿' }}</AppButton>
  </form>
</template>
