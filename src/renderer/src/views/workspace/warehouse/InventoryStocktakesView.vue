<script setup lang="ts">
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
// 下拉选择统一使用工作台组件，业务值与切换回调保持原有类型。
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
// 物料资料统一展示，候选范围和联动规则仍由当前业务决定。
import WorkspaceMaterialSelect from '../../../components/workspace/WorkspaceMaterialSelect.vue'
import { computed, ref } from 'vue'
// 单据统一使用固定关闭区、基础信息和物料明细表格。
import { documentRows } from '../../../utils/document-rows'
import WorkspaceDocumentDialog from '../../../components/workspace/WorkspaceDocumentDialog.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { NDatePicker, NModal } from 'naive-ui'
import { useAppStore } from '../../../store/app-store'
import { submitCreateDialog } from '../../../utils/create-dialog'
import {displayError} from '../../../utils/formatters.ts'
import {datePickerString, vDateField} from '../../../utils/date-field'
import {receiptLotDate, receiptLotMilli} from '../../../../../shared/receipt-lot-api.ts'
import {physicalLotKindLabel} from '../../../../../shared/physical-lot-api.ts'
import {signedStocktakeMilli} from '../../../../../shared/stocktake-lot-api.ts'
import type {StocktakeLotLineInput, StocktakeLotOptions, StocktakeLotPartInput} from '../../../../../shared/stocktake-lot-api'
import type {Stocktake} from '../../../../../shared/erp-api'

// 页面直接使用共享状态与操作，切换标签时不会丢失正在填写的草稿。
const {
  error,
  notice,
  busy,
  connectionLost,
  materials,
  warehouses,
  stocktakes,
  stocktakeForm,
  stocktakeReversalReasons,
  can,
  localTime,
  createStocktake,
  loadAvailableStocktakeLots,
  postStocktake,
  cancelStocktake,
  reverseStocktake
} = useAppStore()

// 搜索只过滤当前单据快照，不改动草稿、确认及冲销状态。
const query = ref('')
const filtered = computed(() => stocktakes.value.filter((item) =>
  [item.id, item.reference, item.warehouse_name, ...item.lines.map((line) => line.material_name)]
    .join(' ').toLowerCase().includes(query.value.trim().toLowerCase())))
const columns = [
  { key: 'document', title: '单据' }, { key: 'warehouse', title: '盘点仓库' },
  { key: 'lines', title: '盘点明细' }, { key: 'actions', title: '操作' }
]

// 保存失败时保留弹窗和草稿，方便直接修正后重试。
const createOpen = ref(false)
const activeStocktakeId = ref(0)
const lotOptions = ref<StocktakeLotOptions | null>(null)
const lotDrafts = ref<StocktakeLotLineInput[]>([])
const lotLoading = ref(false)
const lotLoadError = ref('')
let loadTicket = 0
const activeStocktake = computed(() => stocktakes.value.find(item =>
  item.id === activeStocktakeId.value && item.status === 'draft') ?? null)

function differenceMilli(value: string): bigint {
  return signedStocktakeMilli(value) ?? 0n
}

function closeLotPost(): void {
  loadTicket++
  activeStocktakeId.value = 0
  lotOptions.value = null
  lotDrafts.value = []
}

function newPart(quantity: string, difference: bigint): StocktakeLotPartInput {
  return {lot_id: difference > 0n ? -1 : 0, quantity,
    supplier_lot: null, manufactured_on: null, expires_on: null}
}

async function startLotPost(stocktake: Stocktake): Promise<void> {
  const ticket = ++loadTicket
  activeStocktakeId.value = stocktake.id
  lotOptions.value = null
  lotDrafts.value = []
  lotLoadError.value = ''
  lotLoading.value = true
  try {
    const result = await loadAvailableStocktakeLots(stocktake.id)
    if (ticket !== loadTicket || activeStocktakeId.value !== stocktake.id) return
    if (result.warehouse_id !== stocktake.warehouse_id
        || result.lines.length !== stocktake.lines.length
        || result.lines.some(line => !stocktake.lines.some(item =>
          item.id === line.stocktake_line_id && item.material_id === line.material_id
          && item.book_quantity === line.book_quantity
          && item.counted_quantity === line.counted_quantity
          && differenceMilli(item.difference) === differenceMilli(line.difference))))
      throw Error('可用批次与当前盘点单不匹配，请刷新单据。')
    lotOptions.value = result
    lotDrafts.value = stocktake.lines.filter(line => differenceMilli(line.difference) !== 0n)
      .map(line => ({stocktake_line_id: line.id, lots: [
        newPart(line.difference.replace('-', ''), differenceMilli(line.difference))]}))
  } catch (cause) {
    if (ticket === loadTicket) lotLoadError.value = displayError(cause)
  } finally {
    if (ticket === loadTicket) lotLoading.value = false
  }
}

function addLot(line: StocktakeLotLineInput): void {
  if (line.lots.length < 20) line.lots.push(newPart('', differenceMilli(
    activeStocktake.value?.lines.find(item => item.id === line.stocktake_line_id)?.difference ?? '0')))
}

const lotIssue = computed(() => {
  const stocktake = activeStocktake.value, options = lotOptions.value
  if (!stocktake || !options) return '可用批次尚未读取。'
  const changed = stocktake.lines.filter(line => differenceMilli(line.difference) !== 0n)
  if (lotDrafts.value.length !== changed.length) return '盘点差异明细不完整。'
  for (const line of changed) {
    const draft = lotDrafts.value.find(item => item.stocktake_line_id === line.id)
    const available = options.lines.find(item => item.stocktake_line_id === line.id)
    if (!draft || !available || !draft.lots.length || draft.lots.length > 20)
      return '每条非零盘点差异至少指定一个实物批次。'
    const difference = differenceMilli(line.difference)
    const ids = new Set<number>()
    let total = 0n
    for (const part of draft.lots) {
      const quantity = receiptLotMilli(part.quantity)
      if (quantity === null) return '批次数量须大于零、最多三位小数且不超过一百万。'
      if (part.lot_id === -1 && difference > 0n) {
        if (part.supplier_lot && part.supplier_lot.length > 100)
          return '来源批号不能超过 100 字。'
        if ((part.manufactured_on && !receiptLotDate(part.manufactured_on))
            || (part.expires_on && !receiptLotDate(part.expires_on))
            || (part.manufactured_on && part.expires_on
                && part.expires_on < part.manufactured_on))
          return '盘点发现批次的日期无效。'
      } else {
        const candidate = available.lots.find(item => item.lot_id === part.lot_id)
        if (!candidate || ids.has(part.lot_id ?? 0)) return `物料 ${line.sku} 的批次无效或重复。`
        ids.add(part.lot_id!)
        if (difference < 0n && quantity > (signedStocktakeMilli(candidate.quantity) ?? 0n))
          return `批次 ${candidate.code} 的本仓余量不足，请重新读取。`
      }
      total += quantity
    }
    if (total !== (difference < 0n ? -difference : difference))
      return `物料 ${line.sku} 的批次数量之和须等于差异 ${line.difference} 的绝对值。`
  }
  return ''
})

async function confirmLotPost(): Promise<void> {
  const stocktake = activeStocktake.value
  if (!stocktake || lotIssue.value || busy.value || connectionLost.value) return
  const lines = lotDrafts.value.map(line => ({stocktake_line_id: line.stocktake_line_id,
    lots: line.lots.map(part => ({lot_id: part.lot_id === -1 ? null : part.lot_id,
      quantity: part.quantity,
      supplier_lot: part.lot_id === -1 ? part.supplier_lot?.trim() || null : null,
      manufactured_on: part.lot_id === -1 ? part.manufactured_on || null : null,
      expires_on: part.lot_id === -1 ? part.expires_on || null : null}))}))
  await postStocktake(stocktake.id, lines.length ? lines : undefined)
  if (!stocktakes.value.some(item => item.id === stocktake.id && item.status === 'draft')) closeLotPost()
}
async function submitCreate(): Promise<void> {
  await submitCreateDialog(createStocktake, { busy, error, notice }, createOpen)
}
// 保留每个草稿行的引用，表格编辑不会改写成另一套临时表单。
const stocktakeFormRows = computed(() => documentRows(stocktakeForm.value.lines))
const stocktakeFormColumns = [
  { key: 'material', title: '物料 / 资料', width: '470' },
  { key: 'unit', title: '单位', width: '70' },
  { key: 'quantity', title: '实盘数量', width: '150' },
  { key: 'actions', title: '操作', width: '90' },
]
</script>

<template>
  <section class="stack">
    <!-- 共用基础信息与物料表格布局；行对象仍指向原 Pinia 草稿，保留业务字段和来源约束。 -->
        <WorkspaceDocumentDialog
          v-if="can('stocktake.create')"
          v-model:show="createOpen"
          title="新建盘点单"
          :data="stocktakeFormRows"
          :columns="stocktakeFormColumns"
          :busy="busy"
          :disabled="connectionLost"
          :submit-disabled="connectionLost || !materials.length"
          submit-label="保存草稿"
          :min-table-width="1000"
          :add-disabled="stocktakeForm.lines.length >= 100"
          @add-material="
            stocktakeForm.lines.push({
              material_id: 0,
              counted_quantity: '0'
            })
          "
          @submit="submitCreate"
        >
          <template #basicInfo
            ><label
              >盘点仓库<WorkspaceSelect
                :disabled="busy || connectionLost"
                v-model="stocktakeForm.warehouse_id"
                required
                :options="[...warehouses.map((item) => ({ label: item.name.trim(), value: item.id }))]" /></label
            ><label
              >盘点批次或备注（可选）<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="stocktakeForm.reference"
                maxlength="100"
            /></label>
            <div class="document-basic-extra">
              <p class="muted">
                只填写实际清点数量。保存时记录账面数量；若确认前库存发生变化，系统会要求重新盘点。
              </p>
            </div>
          </template>
          <template #cell-material="{ row: { line, index } }"
            ><label
              >物料<WorkspaceMaterialSelect
                :disabled="busy || connectionLost"
                :materials="materials"
                v-model="line.material_id"
                required
                :options="[
                  { label: '选择物料'.trim(), value: 0, disabled: true },
                  ...materials.map((item) => ({
                    label: (item.sku + ' · ' + item.name).trim(),
                    value: item.id
                  }))
                ]" /></label
          ></template>
          <template #cell-quantity="{ row: { line, index } }"
            ><label
              >实盘数量<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="line.counted_quantity"
                type="number"
                min="0"
                max="1000000"
                step="0.001"
                required /></label
          ></template>
          <template #cell-actions="{ row: { line, index } }"
            ><AppButton
              type="button"
              :disabled="busy || connectionLost || stocktakeForm.lines.length === 1"
              @click="stocktakeForm.lines.splice(index, 1)"
              variant="text"
            >
              移除
            </AppButton></template
          >
          <template #cell-unit="{ row: { line } }">{{
            materials.find((item) => item.id === line.material_id)?.unit ?? '—'
          }}</template>
        </WorkspaceDocumentDialog>
    <!-- 单据列表与台账共用表格，原有权限检查和冲销明细完整保留。 -->
    <WorkspaceTable
      :show-title="false"
      title="库存盘点"
      :columns="columns"
      :data="filtered"
      :min-table-width="1050"
    >
      <template #actions>
        <AppButton
          v-if="can('stocktake.create')"
          type="button"
          :disabled="busy || connectionLost"
          @click="createOpen = true"
          variant="primary"
          >新建盘点单</AppButton
        >
      </template>
      <template #filters
        ><label>搜索盘点单<AppInput v-model="query" placeholder="单号、仓库或物料" /></label
      ></template>
      <template #cell-document="{ row: item }">
        <strong>#{{ item.id }}</strong>
        <small>{{
          item.reversal_id
            ? '已冲销'
            : item.status === 'posted'
              ? '已确认'
              : item.status === 'cancelled'
                ? '已取消'
                : '待确认'
        }}</small>
        <small>{{ localTime(item.created_at) }} · {{ item.created_by_name }}</small>
        <small v-if="item.reference">{{ item.reference }}</small>
      </template>
      <template #cell-warehouse="{ row: item }">{{ item.warehouse_name }}</template>
      <template #cell-lines="{ row: item }">
        <div v-for="line in item.lines" :key="line.id">
          {{ line.material_name }} · 账面 {{ line.book_quantity }} → 实盘
          {{ line.counted_quantity }} {{ line.unit }} · 差异 {{ line.difference }}
          <small v-if="item.status === 'posted' && line.physical_lots?.length" class="stocktake-lot-proof">
            实物批次：{{ line.physical_lots?.map(lot => `${lot.code}（${lot.quantity}；${physicalLotKindLabel(lot.source_kind)}）`).join('、') }}
          </small>
          <small v-else-if="item.status === 'posted' && differenceMilli(line.difference) !== 0n" class="stocktake-lot-proof">旧确认未指定实物批次，数量在批次核对页显示为差额。</small>
        </div>
        <small v-if="item.reversal_id"
          >冲销 #{{ item.reversal_id }} · {{ item.reversal_reason }} · {{ item.reversed_by_name }} ·
          {{ localTime(item.reversed_at!) }}</small
        >
      </template>
      <template #cell-actions="{ row: item }">
        <div class="form-actions">
          <AppButton
            v-if="item.status === 'draft' && can('stocktake.post')"
            type="button"
            :disabled="busy || connectionLost"
            @click="startLotPost(item)"
            variant="primary"
            size="small"
          >
            核对批次并确认</AppButton
          ><AppButton
            v-if="item.status === 'draft' && can('stocktake.cancel')"
            type="button"
            :disabled="busy || connectionLost"
            @click="cancelStocktake(item.id)"
            variant="secondary"
            size="small"
          >
            取消
          </AppButton>
        </div>
        <form
          v-if="item.status === 'posted' && !item.reversal_id && can('stocktake.reverse')"
          class="inline-form"
          @submit.prevent="reverseStocktake(item.id)"
        >
          <label
            >冲销原因<AppInput
              v-model.trim="stocktakeReversalReasons[item.id]"
              required
              maxlength="200"
              placeholder="说明原盘点差异为何需要冲销" /></label
          ><AppButton
            type="submit"
            :disabled="busy || connectionLost"
            variant="secondary"
            size="small"
          >
            冲销已确认盘点
          </AppButton>
        </form>
      </template>
      <template #empty>
        <strong>{{ query ? '没有匹配的单据' : '暂无盘点单' }}</strong>
        <span>{{
          query
            ? '可调整单号、仓库或物料关键词后重新搜索。'
            : '保存新建单据后，可在这里查看明细与处理状态。'
        }}</span>
      </template>
    </WorkspaceTable>
    <NModal :show="!!activeStocktake" @update:show="value=>{if(!value) closeLotPost()}" preset="card"
      :mask-closable="!busy" :style="{width:'min(900px,calc(100vw - 32px))',
        maxHeight:'calc(100vh - 48px)',overflowY:'auto'}">
      <form v-if="activeStocktake && can('stocktake.post')" class="stack" @submit.prevent="confirmLotPost">
        <h2>盘点单 #{{ activeStocktake.id }} · 差异批次归属</h2>
        <p>盘亏选择本仓实际减少的已有批次；盘盈可补入已有批次，或登记明确标为“盘点发现”的新批次。仅填写实物标签上实际可见的来源批号与日期。</p>
        <p v-if="lotLoading">正在读取批次…</p>
        <p v-if="lotLoadError" role="alert">{{ lotLoadError }}</p>
        <p v-if="lotOptions && !lotDrafts.length">这张盘点单没有数量差异，确认时不会生成库存或批次流水。</p>
        <section v-for="line in lotDrafts" :key="line.stocktake_line_id" class="stack stocktake-lot-line">
          <h3>{{ activeStocktake.lines.find(item=>item.id===line.stocktake_line_id)?.sku }} · 差异 {{ activeStocktake.lines.find(item=>item.id===line.stocktake_line_id)?.difference }}</h3>
          <div v-for="(part,index) in line.lots" :key="index" class="stocktake-lot-grid">
            <label>实物批次<WorkspaceSelect v-model="part.lot_id" required :disabled="busy"
              :options="[{label:'选择批次',value:0,disabled:true},
                ...(differenceMilli(activeStocktake?.lines.find(item=>item.id===line.stocktake_line_id)?.difference ?? '0') > 0n
                  ? [{label:'登记盘点发现的新批次',value:-1}] : []),
                ...(lotOptions?.lines.find(item=>item.stocktake_line_id===line.stocktake_line_id)?.lots ?? [])
                  .filter(lot=>differenceMilli(activeStocktake?.lines.find(item=>item.id===line.stocktake_line_id)?.difference ?? '0') > 0n
                    || (signedStocktakeMilli(lot.quantity) ?? 0n) > 0n)
                  .map(lot=>({label:`${lot.code} · ${physicalLotKindLabel(lot.source_kind)} · 本仓 ${lot.quantity}`,
                    value:lot.lot_id}))]" /></label>
            <label>差异数量<AppInput v-model.trim="part.quantity" type="number" min="0.001" max="1000000" step="0.001" required :disabled="busy" /></label>
            <template v-if="part.lot_id === -1">
              <label>实物标签来源批号（可选）<AppInput v-model.trim="part.supplier_lot" maxlength="100" placeholder="未看到则留空" :disabled="busy" /></label>
              <label>生产日期（可选）<NDatePicker v-date-field="{min:'2000-01-01',max:'2099-12-31'}" to="body"
                type="date" format="yyyy-MM-dd" value-format="yyyy-MM-dd"
                :formatted-value="part.manufactured_on" :disabled="busy"
                @update:formatted-value="value=>part.manufactured_on=datePickerString(value)||null" /></label>
              <label>失效日期（可选）<NDatePicker v-date-field="{min:'2000-01-01',max:'2099-12-31'}" to="body"
                type="date" format="yyyy-MM-dd" value-format="yyyy-MM-dd"
                :formatted-value="part.expires_on" :disabled="busy"
                @update:formatted-value="value=>part.expires_on=datePickerString(value)||null" /></label>
            </template>
            <AppButton v-if="line.lots.length>1" type="button" :disabled="busy" @click="line.lots.splice(index,1)">移除批次</AppButton>
          </div>
          <AppButton type="button" :disabled="busy || line.lots.length>=20" @click="addLot(line)">添加一个批次</AppButton>
        </section>
        <p v-if="lotIssue && !lotLoading" role="alert">{{ lotIssue }}</p>
        <div class="form-actions">
          <AppButton type="submit" variant="primary" :disabled="busy || connectionLost || !!lotIssue">确认盘点并固定批次</AppButton>
          <AppButton type="button" :disabled="busy" @click="closeLotPost">取消</AppButton>
        </div>
      </form>
    </NModal>
  </section>
</template>

<style scoped>
.stocktake-lot-line{padding:12px;border:1px solid var(--workspace-field-border);border-radius:8px}
.stocktake-lot-line h3{margin:0}
.stocktake-lot-grid{display:grid;grid-template-columns:repeat(2,minmax(150px,1fr));gap:12px;align-items:end}
.stocktake-lot-proof{display:block;color:var(--workspace-field-muted);overflow-wrap:anywhere}
@media(max-width:550px){.stocktake-lot-grid{grid-template-columns:1fr}}
</style>
