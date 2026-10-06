<script setup lang="ts">
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
// 下拉选择统一使用工作台组件，业务值与切换回调保持原有类型。
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { NDatePicker, NModal } from 'naive-ui'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import WorkspaceDocumentDialog from '../../../components/workspace/WorkspaceDocumentDialog.vue'
import { appendDocumentMaterial, documentMaterialIssue, documentMaterialLimit } from '../../../utils/document-material-lines'
import { usePiniaAppStore } from '../../../store/app-store'
import { submitCreateDialog } from '../../../utils/create-dialog'
import {datePickerString,vDateField} from '../../../utils/date-field'
import {receiptLotDate,receiptLotMilli} from '../../../../../shared/receipt-lot-api.ts'
import type {InboundLotLineInput} from '../../../../../shared/receipt-lot-api'
import type {OtherInbound} from '../../../../../shared/erp-api'

const store = usePiniaAppStore()
const { error, notice, busy, connectionLost, materials, warehouses, otherInbounds, otherInboundForm,
  otherInboundReversalReasons } = storeToRefs(store)
const { can, localTime, createOtherInbound, postOtherInbound, cancelOtherInbound,
  reverseOtherInbound } = store
const showForm = ref(false)
// 选择区是未加入的临时输入；已加入的明细仍由 Pinia 保留，收起不会丢失。
const pickerOpen = ref(false)
const materialDraft = ref({ material_id: 0, quantity: '1' })
const pickerIssue = ref('')
const materialOptions = computed(() => materials.value.map(item => ({
  label: `${item.sku} · ${item.name}`, value: item.id,
  disabled: otherInboundForm.value.lines.some(line => line.material_id === item.id)
})))
const materialRows = computed(() => otherInboundForm.value.lines.map((line, index) => ({
  ...line, index, material: materials.value.find(item => item.id === line.material_id)
})))
const materialColumns = [
  { key: 'sku', title: '物料编码', width: '210' },
  { key: 'name', title: '物料名称', width: '240' },
  { key: 'unit', title: '单位', width: '80' },
  { key: 'quantity', title: '数量', width: '160' },
  { key: 'actions', title: '操作', width: '90' }
]
const materialIssue = computed(() => documentMaterialIssue(otherInboundForm.value.lines, materials.value))
function openMaterialPicker(): void {
  if (busy.value || connectionLost.value) return
  pickerOpen.value = true
  pickerIssue.value = ''
}
function addMaterial(): void {
  if (busy.value || connectionLost.value) return
  const result = appendDocumentMaterial(otherInboundForm.value.lines, materialDraft.value, materials.value)
  pickerIssue.value = result.issue
  if (result.issue) return
  otherInboundForm.value.lines = result.lines
  materialDraft.value = { material_id: 0, quantity: '1' }
  pickerOpen.value = false
}
const activeInboundId = ref(0)
const lotDrafts = ref<InboundLotLineInput[]>([])
const activeInbound = computed(() => otherInbounds.value.find(item =>
  item.id === activeInboundId.value && item.status === 'draft') ?? null)
const query = ref('')
const filtered = computed(() => otherInbounds.value.filter((item) =>
  [item.id, item.reference, item.warehouse_name, item.note, ...item.lines.map((line) => line.material_name)]
    .join(' ').toLowerCase().includes(query.value.trim().toLowerCase())))
const reasonName = { opening: '期初补录', gift: '赠品', other: '其他' }
const columns = [
  { key: 'document', title: '单据' }, { key: 'source', title: '仓库与来源' },
  { key: 'lines', title: '物料明细' }, { key: 'actions', title: '操作' }
]
// 写入失败时保留表单，成功后才关闭弹窗。
async function submitCreate(): Promise<void> {
  // 原生表单校验之外再检查物料和数量，防止空明细或已失效物料提交到服务端。
  if (connectionLost.value || !can('other_inbound.create') || materialIssue.value || pickerOpen.value) return
  await submitCreateDialog(createOtherInbound, { busy, error, notice }, showForm)
}
function startLotPost(inbound: OtherInbound): void {
  activeInboundId.value = inbound.id
  lotDrafts.value = inbound.lines.map(line => ({inbound_line_id: line.id,
    lots: [{quantity: line.quantity, supplier_lot: null, manufactured_on: null, expires_on: null}]}))
}
function addLot(line: InboundLotLineInput): void {
  if (line.lots.length < 20) line.lots.push({quantity: '', supplier_lot: null,
    manufactured_on: null, expires_on: null})
}
const lotIssue = computed(() => {
  const inbound = activeInbound.value
  if (!inbound || lotDrafts.value.length !== inbound.lines.length) return '入库单明细已经变化，请重新读取。'
  for (const line of inbound.lines) {
    const draft = lotDrafts.value.find(item => item.inbound_line_id === line.id)
    if (!draft || !draft.lots.length || draft.lots.length > 20) return '每条入库明细至少登记一个实物批次。'
    const expected = receiptLotMilli(line.quantity)
    let total = 0n
    for (const part of draft.lots) {
      const value = receiptLotMilli(part.quantity)
      if (value === null) return '批次数量须大于零、最多三位小数且不超过一百万。'
      total += value
      if (part.supplier_lot && part.supplier_lot.length > 100) return '来源批号不能超过 100 字。'
      if (part.manufactured_on && !receiptLotDate(part.manufactured_on)) return '生产日期无效。'
      if (part.expires_on && !receiptLotDate(part.expires_on)) return '失效日期无效。'
      if (part.manufactured_on && part.expires_on && part.expires_on < part.manufactured_on)
        return '失效日期不能早于生产日期。'
    }
    if (expected === null || total !== expected) return `物料 ${line.sku} 的批次数量之和须等于 ${line.quantity}。`
  }
  return ''
})
async function confirmLotPost(): Promise<void> {
  if (!activeInbound.value || lotIssue.value || busy.value || connectionLost.value) return
  await postOtherInbound(activeInbound.value.id, lotDrafts.value.map(line => ({
    inbound_line_id: line.inbound_line_id,
    lots: line.lots.map(part => ({quantity: part.quantity, supplier_lot: part.supplier_lot?.trim() || null,
      manufactured_on: part.manufactured_on, expires_on: part.expires_on}))})))
}
</script>

<template>
  <section class="stack">
    <WorkspaceTable
      :show-title="false"
      :data="filtered"
      title="其他入库"
      :columns="columns"
      :min-table-width="900"
    >
      <template #actions>
        <AppButton
          v-if="can('other_inbound.create')"
          :disabled="busy || connectionLost"
          @click="showForm = true"
          variant="primary"
          type="button"
          >新建其他入库</AppButton
        >
      </template>
      <template #filters>
        <label>搜索入库单<AppInput v-model="query" placeholder="单号、仓库或物料" /></label>
      </template>
      <template #beforeTable>
        <WorkspaceDocumentDialog
          v-if="can('other_inbound.create')"
          v-model:show="showForm"
          title="非采购来源入库"
          :data="materialRows"
          :columns="materialColumns"
          :busy="busy"
          :disabled="connectionLost"
          :submit-disabled="!!materialIssue || pickerOpen"
          :add-disabled="pickerOpen || materialRows.length >= documentMaterialLimit || !materialOptions.some(item => !item.disabled)"
          hint="确认后才增加库存；这类入库不产生采购应付。"
          @submit="submitCreate"
          @add-material="openMaterialPicker"
        >
          <template #basicInfo>
            <label>仓库<WorkspaceSelect v-model="otherInboundForm.warehouse_id" required
              :disabled="busy || connectionLost"
              :options="warehouses.map(item => ({ label: item.name, value: item.id }))" /></label>
            <label>用途<WorkspaceSelect v-model="otherInboundForm.reason" required
              :disabled="busy || connectionLost"
              :options="[{ label: '期初补录', value: 'opening' }, { label: '赠品', value: 'gift' }, { label: '其他', value: 'other' }]" /></label>
            <label>参考号<AppInput v-model.trim="otherInboundForm.reference" maxlength="100" :disabled="busy || connectionLost" /></label>
            <label>入库说明<AppInput v-model.trim="otherInboundForm.note" required maxlength="200" :disabled="busy || connectionLost" /></label>
          </template>
          <template #materialPicker>
            <div v-if="pickerOpen" class="inbound-material-picker">
              <div class="inbound-material-fields">
                <label>物料<WorkspaceSelect v-model="materialDraft.material_id" :options="materialOptions"
                  :disabled="busy || connectionLost" placeholder="搜索物料编码或名称" aria-label="待添加物料" /></label>
                <label>数量<AppInput v-model.trim="materialDraft.quantity" type="number" min="0.001"
                  max="1000000" step="0.001" :disabled="busy || connectionLost" aria-label="待添加数量" /></label>
                <AppButton type="button" variant="primary" :disabled="busy || connectionLost || !materialDraft.material_id"
                  @click="addMaterial">加入明细</AppButton>
                <AppButton type="button" :disabled="busy" @click="pickerOpen = false" variant="text">取消添加</AppButton>
              </div>
              <p v-if="pickerIssue" role="alert" class="inbound-material-issue">{{ pickerIssue }}</p>
            </div>
            <p v-if="materialRows.length && materialIssue" role="alert" class="inbound-material-issue">{{ materialIssue }}</p>
          </template>
          <template #cell-sku="{ row }"><strong>{{ row.material?.sku ?? '物料不可用' }}</strong></template>
          <template #cell-name="{ row }">{{ row.material?.name ?? '请移除后重新选择' }}</template>
          <template #cell-unit="{ row }">{{ row.material?.unit ?? '—' }}</template>
          <template #cell-quantity="{ row }">
            <AppInput v-model.trim="otherInboundForm.lines[row.index].quantity" type="number" min="0.001"
              max="1000000" step="0.001" required :disabled="busy || connectionLost"
              :aria-label="`${row.material?.name ?? '物料'}数量`" />
          </template>
          <template #cell-actions="{ row }">
            <AppButton type="button" variant="text" :disabled="busy || connectionLost"
              :aria-label="`移除${row.material?.name ?? '物料'}`" @click="otherInboundForm.lines.splice(row.index, 1)">移除</AppButton>
          </template>
        </WorkspaceDocumentDialog>
      </template>
      <template #cell-document="{ row: item }"
        ><strong>#{{ item.id }}</strong
        ><small>{{ localTime(item.created_at) }} · {{ item.created_by_name }}</small
        ><small>{{
          item.status === 'draft'
            ? '待确认'
            : item.status === 'cancelled'
              ? '已取消'
              : item.reversal_id
                ? '已冲销'
                : '已入库'
        }}</small></template
      >
      <template #cell-source="{ row: item }"
        >{{ item.warehouse_name }} · {{ reasonName[item.reason] }}<small>{{ item.note }}</small
        ><small v-if="item.reference">{{ item.reference }}</small></template
      >
      <template #cell-lines="{ row: item }"
        ><div v-for="line in item.lines" :key="line.id">
          {{ line.material_name }} × {{ line.quantity }} {{ line.unit }}
          <small v-if="item.status === 'posted' && line.physical_lots?.length" class="inbound-lot-proof">
            实物批次：{{ line.physical_lots?.map(lot => `${lot.code}（${lot.quantity}；来源批号 ${lot.supplier_lot || '未提供'}）`).join('、') }}
          </small>
          <small v-else-if="item.status === 'posted'" class="inbound-lot-proof">未登记实物批次，数量在批次核对页显示为差额。</small>
        </div></template
      >
      <template #cell-actions="{ row: item }"
        ><div class="form-actions">
          <AppButton
            v-if="item.status === 'draft' && can('other_inbound.post')"
            :disabled="busy || connectionLost"
            @click="startLotPost(item)"
            variant="primary"
            size="small"
            type="button"
            >登记批次并确认</AppButton
          >
          <AppButton
            v-if="item.status === 'draft' && can('other_inbound.cancel')"
            :disabled="busy || connectionLost"
            @click="cancelOtherInbound(item.id)"
            variant="secondary"
            size="small"
            type="button"
            >取消</AppButton
          >
        </div>
        <form
          v-if="item.status === 'posted' && !item.reversal_id && can('other_inbound.reverse')"
          class="inline-form"
          @submit.prevent="reverseOtherInbound(item.id)"
        >
          <label
            >冲销原因<AppInput
              v-model.trim="otherInboundReversalReasons[item.id]"
              required
              maxlength="200"
          /></label>
          <AppButton
            :disabled="busy || connectionLost"
            variant="secondary"
            size="small"
            type="submit"
            >冲销</AppButton
          >
        </form>
        <small v-if="item.reversal_reason">冲销：{{ item.reversal_reason }}</small></template
      >
      <template #empty>{{ query ? '没有匹配的入库单。' : '暂无其他入库单。' }}</template>
    </WorkspaceTable>
    <NModal :show="!!activeInbound" @update:show="value=>{if(!value) activeInboundId=0}" preset="card"
      :mask-closable="!busy" :style="{width:'min(1000px,calc(100vw - 32px))',
        maxHeight:'calc(100vh - 48px)',overflowY:'auto'}">
      <form v-if="activeInbound && can('other_inbound.post')" class="stack inbound-lot-editor"
        @submit.prevent="confirmLotPost">
        <h2>其他入库 #{{ activeInbound.id }} · 实物批次</h2>
        <p>按实际入库逐行登记批次，数量之和须等于入库量。来源批号和日期缺失时留空，系统会保留独立的入库来源编号。</p>
        <section v-for="line in lotDrafts" :key="line.inbound_line_id" class="stack inbound-lot-line">
          <h3>{{ activeInbound.lines.find(item=>item.id===line.inbound_line_id)?.sku }} · {{ activeInbound.lines.find(item=>item.id===line.inbound_line_id)?.material_name }} · {{ activeInbound.lines.find(item=>item.id===line.inbound_line_id)?.quantity }} {{ activeInbound.lines.find(item=>item.id===line.inbound_line_id)?.unit }}</h3>
          <div v-for="(part,index) in line.lots" :key="index" class="inbound-lot-grid">
            <label>批次数量<AppInput v-model="part.quantity" inputmode="decimal" required :disabled="busy" /></label>
            <label>来源批号<AppInput v-model.trim="part.supplier_lot" maxlength="100" placeholder="未提供则留空" :disabled="busy" /></label>
            <label>生产日期<NDatePicker v-date-field="{min:'2000-01-01',max:'2099-12-31'}" to="body" type="date" format="yyyy-MM-dd" value-format="yyyy-MM-dd" :formatted-value="part.manufactured_on" :disabled="busy" @update:formatted-value="value=>part.manufactured_on=datePickerString(value)||null" /></label>
            <label>失效日期<NDatePicker v-date-field="{min:'2000-01-01',max:'2099-12-31'}" to="body" type="date" format="yyyy-MM-dd" value-format="yyyy-MM-dd" :formatted-value="part.expires_on" :disabled="busy" @update:formatted-value="value=>part.expires_on=datePickerString(value)||null" /></label>
            <AppButton v-if="line.lots.length>1" type="button" :disabled="busy" @click="line.lots.splice(index,1)">移除批次</AppButton>
          </div>
          <AppButton type="button" :disabled="busy || line.lots.length>=20" @click="addLot(line)">添加一个批次</AppButton>
        </section>
        <p v-if="lotIssue" role="alert">{{ lotIssue }}</p>
        <div class="form-actions">
          <AppButton type="submit" variant="primary" :disabled="busy || connectionLost || !!lotIssue">确认入库并固定批次</AppButton>
          <AppButton type="button" :disabled="busy" @click="activeInboundId=0">取消</AppButton>
        </div>
      </form>
    </NModal>
  </section>
</template>

<style scoped>
.inbound-lot-line{padding:12px;border:1px solid var(--workspace-field-border);border-radius:8px}
.inbound-lot-line h3{margin:0}
.inbound-lot-grid{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:12px;align-items:end}
.inbound-lot-proof{display:block;color:var(--workspace-field-muted);overflow-wrap:anywhere}
@media(max-width:950px){.inbound-lot-grid{grid-template-columns:repeat(2,minmax(150px,1fr))}}
@media(max-width:550px){.inbound-lot-grid{grid-template-columns:1fr}}
</style>

<style scoped>
/* 物料选择区紧邻明细表，窄窗口自动换行，选择菜单沿用公共组件的浮层。 */
.inbound-material-picker { padding: 16px; border: 1px solid var(--workspace-field-border); border-radius: 10px; background: var(--app-accent-tint); }
.inbound-material-fields { display: flex; flex-wrap: wrap; align-items: end; gap: 12px; }
.inbound-material-fields label:first-child { flex: 1 1 280px; }
.inbound-material-fields label:nth-child(2) { flex: 0 1 140px; }
.inbound-material-issue { margin: 10px 0 0; color: #c45a53; font-size: 13px; }
:root[data-theme='dark'] .inbound-material-issue { color: #ffaaa2; }
</style>
