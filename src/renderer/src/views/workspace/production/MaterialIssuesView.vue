<script setup lang="ts">
// 页面只展示服务端保存的单号，原内部 ID 继续用于业务操作。
import { documentSearch, documentLabel, relatedDocumentLabel } from '../../../../../shared/document-numbering'
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
// 下拉选择统一使用工作台组件，业务值与切换回调保持原有类型。
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { recordColumns, matchesRecordQuery } from '../../../utils/workspace-records'
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { NModal } from 'naive-ui'
import { usePiniaAppStore } from '../../../store/app-store'
import { submitCreateDialog } from '../../../utils/create-dialog'
import {displayError} from '../../../utils/formatters.ts'
import {receiptLotMilli} from '../../../../../shared/receipt-lot-api.ts'
import {outboundAvailableMilli} from '../../../../../shared/outbound-lot-api.ts'
import {physicalLotKindLabel} from '../../../../../shared/physical-lot-api.ts'
import type {MaterialIssueLotLineInput,MaterialIssueLotOptions} from '../../../../../shared/material-issue-lot-api'
import type {MaterialIssue} from '../../../../../shared/erp-api'

// 页面直接使用共享状态与操作，切换标签时不会丢失正在填写的草稿。
const store = usePiniaAppStore()
const {
  error,
  notice,
  busy,
  connectionLost,
  workOrders,
  materialIssues,
  warehouses,
  materialIssueForm,
  selectedIssueOrder,
} = storeToRefs(store)
const {
  can,
  localTime,
  selectIssueOrder,
  createMaterialIssue,
  loadAvailableMaterialIssueLots,
  postMaterialIssue,
  cancelMaterialIssue,
  reverseMaterialIssue,
  selectReturnIssue
} = store

const activeIssueId = ref(0)
const lotOptions = ref<MaterialIssueLotOptions | null>(null)
const lotDrafts = ref<MaterialIssueLotLineInput[]>([])
const lotLoading = ref(false)
const lotLoadError = ref('')
const reversalReasons = ref<Record<number, string>>({})
let loadTicket = 0
const activeIssue = computed(() => materialIssues.value.find(item =>
  item.id === activeIssueId.value && item.status === 'draft') ?? null)

function closeLotPost(): void {
  loadTicket++
  activeIssueId.value = 0
  lotOptions.value = null
  lotDrafts.value = []
}

async function startLotPost(issue: MaterialIssue): Promise<void> {
  const ticket = ++loadTicket
  activeIssueId.value = issue.id
  lotOptions.value = null
  lotDrafts.value = []
  lotLoadError.value = ''
  lotLoading.value = true
  try {
    const result = await loadAvailableMaterialIssueLots(issue.id)
    if (ticket !== loadTicket || activeIssueId.value !== issue.id) return
    if (result.warehouse_id !== issue.warehouse_id
        || result.lines.length !== issue.lines.length
        || result.lines.some(line => !issue.lines.some(item =>
          item.id === line.material_issue_line_id && item.component_material_id === line.material_id
          && item.quantity === line.quantity)))
      throw Error('可用批次与当前生产领料单不匹配，请刷新单据。')
    lotOptions.value = result
    lotDrafts.value = issue.lines.map(line => ({
      material_issue_line_id: line.id, lots: [{lot_id: 0, quantity: line.quantity}]}))
  } catch (cause) {
    if (ticket === loadTicket) lotLoadError.value = displayError(cause)
  } finally {
    if (ticket === loadTicket) lotLoading.value = false
  }
}

function addLot(line: MaterialIssueLotLineInput): void {
  if (line.lots.length < 20) line.lots.push({lot_id: 0, quantity: ''})
}

const lotIssue = computed(() => {
  const issue = activeIssue.value, options = lotOptions.value
  if (!issue || !options || lotDrafts.value.length !== issue.lines.length)
    return '可用批次尚未读取。'
  for (const line of issue.lines) {
    const draft = lotDrafts.value.find(item => item.material_issue_line_id === line.id)
    const available = options.lines.find(item => item.material_issue_line_id === line.id)
    if (!draft || !available || !draft.lots.length || draft.lots.length > 20)
      return '每条领料明细至少指定一个实物批次。'
    const ids = new Set<number>()
    let total = 0n
    for (const part of draft.lots) {
      const candidate = available.lots.find(item => item.lot_id === part.lot_id)
      if (!candidate || ids.has(part.lot_id)) return `物料 ${line.sku} 的批次无效或重复。`
      ids.add(part.lot_id)
      const quantity = receiptLotMilli(part.quantity)
      if (quantity === null) return '批次数量须大于零、最多三位小数且不超过一百万。'
      if (quantity > (outboundAvailableMilli(candidate.quantity) ?? 0n))
        return `批次 ${candidate.code} 的可用量不足，请重新读取。`
      total += quantity
    }
    if (total !== receiptLotMilli(line.quantity))
      return `物料 ${line.sku} 的批次数量之和须等于 ${line.quantity}。`
  }
  return ''
})

async function confirmLotPost(): Promise<void> {
  const issue = activeIssue.value
  if (!issue || lotIssue.value || busy.value || connectionLost.value) return
  await postMaterialIssue(issue.id, lotDrafts.value.map(line => ({
    material_issue_line_id: line.material_issue_line_id,
    lots: line.lots.map(part => ({lot_id: part.lot_id, quantity: part.quantity}))})))
  if (!materialIssues.value.some(item => item.id === issue.id && item.status === 'draft')) closeLotPost()
}

async function submitReverse(issue: MaterialIssue): Promise<void> {
  const reason = reversalReasons.value[issue.id]?.trim() ?? ''
  if (!reason || busy.value || connectionLost.value || issue.status !== 'posted') return
  await reverseMaterialIssue(issue.id, reason)
  if (materialIssues.value.some(item => item.id === issue.id && item.status === 'reversed'))
    delete reversalReasons.value[issue.id]
}

// 保存失败时保留弹窗和草稿，方便直接修正后重试。
const createOpen = ref(false)
async function submitCreate(): Promise<void> {
  await submitCreateDialog(createMaterialIssue, { busy, error, notice }, createOpen)
}
// 只筛选当前列表快照，原有单据状态与跨页面草稿保持不变。
const recordQuery = ref('')
const filteredRecords = computed(() =>
  materialIssues.value.filter((item) =>
    matchesRecordQuery(recordQuery.value, [documentSearch(item), item.id,
      item.warehouse_name,
      item.created_by_name,
      item.reference,
      ...item.lines.map((line) => line.material_name)
    ])
  )
)
</script>

<template>
  <section class="stack">
    <NModal
      v-if="can('material_issue.create')"
      v-model:show="createOpen"
      preset="card"
      :mask-closable="!busy"
      :style="{
        width: 'min(900px, calc(100vw - 32px))',
        maxHeight: 'calc(100vh - 48px)',
        overflowY: 'auto'
      }"
    >
      <div class="section-heading">
        <div>
          <p class="eyebrow">MATERIAL ISSUE</p>
          <h2>新建领料单</h2>
        </div>
        <span class="pill">草稿</span>
      </div>
      <p class="muted">
        按工单剩余需料分批建单。草稿不预留库存；确认时服务端再次检查源仓库存与剩余需料。
      </p>
      <form @submit.prevent="submitCreate">
        <div class="form-grid">
          <label
            >生产工单<WorkspaceSelect
              v-model="materialIssueForm.work_order_id"
              required
              @change="selectIssueOrder(materialIssueForm.work_order_id)"
              :options="[
                { label: '选择已下达工单', value: 0, disabled: true },
                ...workOrders
                  .filter(
                    (entry) =>
                      (entry.status === 'released' || entry.status === 'in_progress') &&
                      entry.lines.some((line) => Number(line.remaining_quantity) > 0)
                  )
                  .map((item) => ({
                    label: (
                      ' #' +
                      item.id +
                      ' · ' +
                      item.product_name +
                      ' · ' +
                      item.target_quantity +
                      ' ' +
                      item.product_unit
                    ).trim(),
                    value: item.id
                  }))
              ]" /></label
          ><label
            >领料源仓库<WorkspaceSelect
              v-model="materialIssueForm.warehouse_id"
              required
              :options="[
                ...warehouses.map((item) => ({ label: item.name, value: item.id }))
              ]" /></label
          ><label
            >参考号（可选）<AppInput v-model.trim="materialIssueForm.reference" maxlength="100"
          /></label>
        </div>
        <h3>本次领料数量</h3>
        <div
          v-for="line in materialIssueForm.lines"
          :key="line.work_order_line_id"
          class="line-row"
        >
          <label
            >{{
              selectedIssueOrder?.lines.find((item) => item.id === line.work_order_line_id)
                ?.material_name
            }}
            · 剩余
            {{
              selectedIssueOrder?.lines.find((item) => item.id === line.work_order_line_id)
                ?.remaining_quantity
            }}<AppInput
              v-model.trim="line.quantity"
              type="number"
              min="0.001"
              :max="
                selectedIssueOrder?.lines.find((item) => item.id === line.work_order_line_id)
                  ?.remaining_quantity
              "
              step="0.001"
              required /></label
          ><AppButton
            type="button"
            :disabled="busy"
            @click="
              materialIssueForm.lines = materialIssueForm.lines.filter(
                (item) => item.work_order_line_id !== line.work_order_line_id
              )
            "
            variant="text"
          >
            本次不领
          </AppButton>
        </div>
        <AppButton
          type="submit"
          :disabled="busy || !materialIssueForm.lines.length || !warehouses.length"
          variant="primary"
        >
          保存领料草稿
        </AppButton>
      </form>
    </NModal>
    <!-- 主标题由工作台提供，列表复用仓库管理的筛选区、状态和单元格布局。 -->
    <WorkspaceTable
      :show-title="false"
      title="生产领料"
      :data="filteredRecords"
      :columns="recordColumns"
      :min-table-width="1100"
    >
      <template #actions>
        <AppButton
          v-if="can('material_issue.create')"
          type="button"
          :disabled="busy"
          @click="createOpen = true"
          variant="primary"
        >
          新建领料单
        </AppButton>
      </template>
      <template #filters>
        <label>
          搜索生产领料
          <AppInput v-model="recordQuery" placeholder="单号、名称或物料" />
        </label>
      </template>

      <template #cell-document="{ row: item }">
        <div>
          <strong
            >{{ documentLabel(item) }} · 工单 {{ relatedDocumentLabel(item, 'work_order') }} · {{ item.warehouse_name }}</strong
          >
          <p class="muted">
            {{ localTime(item.created_at) }} · 创建人
            {{ item.created_by_name }}
            <span v-if="item.reference">· {{ item.reference }}</span>
          </p>
        </div>
      </template>
      <template #cell-status="{ row: item }">
        <span class="pill" :class="item.status">
          {{ { draft: '草稿', posted: '已确认', cancelled: '已取消', reversed: '已冲销' }[item.status] }}
        </span>
        <small v-if="item.reversal_reason" class="muted">
          {{ item.reversed_at ? localTime(item.reversed_at) : '' }} · 冲销原因：{{ item.reversal_reason }}
        </small>
      </template>
      <template #cell-details="{ row: item }">
        <div class="workspace-record-lines">
          <span v-for="line in item.lines" :key="line.id">
            {{ line.material_name }} · 已领 {{ line.quantity }} · 已退
            {{ line.returned_quantity }} · 可退 {{ line.returnable_quantity }} {{ line.unit }}
            <small v-if="['posted', 'reversed'].includes(item.status) && line.physical_lots.length" class="issue-lot-proof">
              实物批次：{{ line.physical_lots.map(lot => `${lot.code}（${lot.quantity}；${physicalLotKindLabel(lot.source_kind)}）`).join('、') }}
            </small>
            <small v-else-if="['posted', 'reversed'].includes(item.status)" class="issue-lot-proof">原确认未指定实物批次，查看批次核对页确认差额。</small>
          </span>
        </div>
      </template>
      <template #cell-actions="{ row: item }">
        <div class="form-actions">
          <AppButton
            v-if="item.status === 'draft' && can('material_issue.post')"
            type="button"
            :disabled="busy"
            @click="startLotPost(item)"
            variant="primary"
            size="small"
          >
            指定批次并确认
          </AppButton>
          <AppButton
            v-if="item.status === 'draft' && can('material_issue.cancel')"
            type="button"
            :disabled="busy"
            @click="cancelMaterialIssue(item.id)"
            variant="secondary"
            size="small"
          >
            取消
          </AppButton>
          <AppButton
            v-if="
              item.status === 'posted' &&
              item.lines.some((line) => Number(line.returnable_quantity) > 0) &&
              can('material_return.create')
            "
            type="button"
            :disabled="busy"
            @click="selectReturnIssue(item.id)"
            variant="secondary"
            size="small"
          >
            创建退料单
          </AppButton>
          <template v-if="item.status === 'posted' && can('material_issue.reverse')">
            <label>冲销原因
              <AppInput v-model.trim="reversalReasons[item.id]" maxlength="200" placeholder="填写错误确认依据" />
            </label>
            <AppButton type="button" variant="secondary" size="small"
              :disabled="busy || connectionLost || !reversalReasons[item.id]?.trim()"
              @click="submitReverse(item)">冲销已确认领料</AppButton>
          </template>
        </div>
      </template>
      <template #empty>
        <strong>{{ recordQuery ? '没有匹配的记录' : '暂无生产领料记录' }}</strong>
        <span>
          {{
            recordQuery
              ? '可调整单号、名称或物料关键词后重新搜索。'
              : '业务记录生成后，可在这里查看明细与处理状态。'
          }}
        </span>
      </template>
    </WorkspaceTable>
    <NModal :show="!!activeIssue" @update:show="value=>{if(!value) closeLotPost()}" preset="card"
      :mask-closable="!busy" :style="{width:'min(900px,calc(100vw - 32px))',
        maxHeight:'calc(100vh - 48px)',overflowY:'auto'}">
      <form v-if="activeIssue && can('material_issue.post')" class="stack" @submit.prevent="confirmLotPost">
        <h2>生产领料 {{ documentLabel(activeIssue) }} · 指定实物批次</h2>
        <p>从 {{ activeIssue.warehouse_name }} 的实际可用批次逐行选择；历史未识别期初会明确标记。</p>
        <p v-if="lotLoading">正在读取可用批次…</p>
        <p v-if="lotLoadError" role="alert">{{ lotLoadError }}</p>
        <section v-for="line in lotDrafts" :key="line.material_issue_line_id" class="stack issue-lot-line">
          <h3>{{ activeIssue.lines.find(item=>item.id===line.material_issue_line_id)?.sku }} · {{ activeIssue.lines.find(item=>item.id===line.material_issue_line_id)?.material_name }} · {{ activeIssue.lines.find(item=>item.id===line.material_issue_line_id)?.quantity }} {{ activeIssue.lines.find(item=>item.id===line.material_issue_line_id)?.unit }}</h3>
          <div v-for="(part,index) in line.lots" :key="index" class="issue-lot-grid">
            <label>实物批次<WorkspaceSelect v-model="part.lot_id" required :disabled="busy"
              :options="[{label:'选择批次',value:0,disabled:true},
                ...(lotOptions?.lines.find(item=>item.material_issue_line_id===line.material_issue_line_id)?.lots ?? []).map(lot=>({
                  label:`${lot.code} · ${physicalLotKindLabel(lot.source_kind)} · 可用 ${lot.quantity}`,
                  value:lot.lot_id}))]" /></label>
            <label>领料数量<AppInput v-model.trim="part.quantity" type="number" min="0.001" max="1000000" step="0.001" required :disabled="busy" /></label>
            <AppButton v-if="line.lots.length>1" type="button" :disabled="busy" @click="line.lots.splice(index,1)">移除批次</AppButton>
          </div>
          <AppButton type="button" :disabled="busy || line.lots.length>=20" @click="addLot(line)">添加一个批次</AppButton>
        </section>
        <p v-if="lotIssue && !lotLoading" role="alert">{{ lotIssue }}</p>
        <div class="form-actions">
          <AppButton type="submit" variant="primary" :disabled="busy || connectionLost || !!lotIssue">确认领料并固定批次</AppButton>
          <AppButton type="button" :disabled="busy" @click="closeLotPost">取消</AppButton>
        </div>
      </form>
    </NModal>
  </section>
</template>

<style scoped>
.issue-lot-line{padding:12px;border:1px solid var(--workspace-field-border);border-radius:8px}
.issue-lot-line h3{margin:0}
.issue-lot-grid{display:grid;grid-template-columns:repeat(2,minmax(150px,1fr));gap:12px;align-items:end}
.issue-lot-proof{display:block;color:var(--workspace-field-muted);overflow-wrap:anywhere}
@media(max-width:550px){.issue-lot-grid{grid-template-columns:1fr}}
</style>
