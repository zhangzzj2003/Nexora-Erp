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
import { NDatePicker,NModal } from 'naive-ui'
import { useAppStore } from '../../../store/app-store'
import { submitCreateDialog } from '../../../utils/create-dialog'
import {datePickerString,vDateField} from '../../../utils/date-field'
import {completionLotDate,completionLotMilli} from '../../../../../shared/completion-lot-api.ts'
import type {CompletionLotPartInput} from '../../../../../shared/completion-lot-api'
import type {ProductionCompletion} from '../../../../../shared/erp-api'

// 页面直接使用共享状态与操作，切换标签时不会丢失正在填写的草稿。
const {
  error,
  notice,
  busy,
  connectionLost,
  workOrders,
  productionCompletions,
  completionForm,
  inspectionDrafts,
  completionReversalReasons,
  can,
  selectedCompletionOrder,
  localTime,
  selectCompletionOrder,
  createProductionCompletion,
  inspectProductionCompletion,
  postProductionCompletion,
  cancelProductionCompletion,
  reverseProductionCompletion
} = useAppStore()

// 保存失败时保留弹窗和草稿，方便直接修正后重试。
const createOpen = ref(false)
const activeCompletionId = ref(0)
const lotDrafts = ref<CompletionLotPartInput[]>([])
const activeCompletion = computed(() => productionCompletions.value.find(item =>
  item.id === activeCompletionId.value && item.status === 'inspected') ?? null)
function startLotPost(item: ProductionCompletion): void {
  if (Number(item.accepted_quantity) === 0) {
    void postProductionCompletion(item.id)
    return
  }
  activeCompletionId.value = item.id
  lotDrafts.value = [{quantity: item.accepted_quantity ?? '', manufactured_on: null, expires_on: null}]
}
function addLot(): void {
  if (lotDrafts.value.length < 20)
    lotDrafts.value.push({quantity: '', manufactured_on: null, expires_on: null})
}
const lotIssue = computed(() => {
  if (!activeCompletion.value) return '完工单已变化，请重新读取。'
  const expected = completionLotMilli(activeCompletion.value.accepted_quantity ?? '')
  if (expected === null || !lotDrafts.value.length || lotDrafts.value.length > 20)
    return '合格入库须登记一个或多个实物批次。'
  let total = 0n
  for (const part of lotDrafts.value) {
    const quantity = completionLotMilli(part.quantity)
    if (quantity === null) return '批次数量须大于零、最多三位小数且不超过一百万。'
    total += quantity
    if (part.manufactured_on && !completionLotDate(part.manufactured_on)) return '生产日期无效。'
    if (part.expires_on && !completionLotDate(part.expires_on)) return '失效日期无效。'
    if (part.manufactured_on && part.expires_on && part.expires_on < part.manufactured_on)
      return '失效日期不能早于生产日期。'
  }
  return total === expected ? '' : `批次数量之和须等于合格入库量 ${activeCompletion.value.accepted_quantity}。`
})
async function confirmLotPost(): Promise<void> {
  if (!activeCompletion.value || lotIssue.value || busy.value || connectionLost.value) return
  await postProductionCompletion(activeCompletion.value.id,lotDrafts.value.map(part => ({...part})))
}
async function submitCreate(): Promise<void> {
  await submitCreateDialog(createProductionCompletion, { busy, error, notice }, createOpen)
}
// 只筛选当前列表快照，原有单据状态与跨页面草稿保持不变。
const recordQuery = ref('')
const filteredRecords = computed(() =>
  productionCompletions.value.filter((item) =>
    matchesRecordQuery(recordQuery.value, [documentSearch(item), item.id,
      item.product_name,
      item.warehouse_name,
      item.created_by_name,
      item.reference
    ])
  )
)
</script>

<template>
  <section class="stack">
    <NModal
      v-if="can('production_completion.create')"
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
          <p class="eyebrow">PRODUCTION COMPLETION</p>
          <h2>新建完工报工单</h2>
        </div>
        <span class="pill">草稿</span>
      </div>
      <p class="muted">
        按工单目标产量分批报工。报工数包含待质检的合格与不合格产品；质检并确认后，只有合格数进入工单目标仓库。
      </p>
      <form @submit.prevent="submitCreate">
        <div class="form-grid">
          <label
            >生产工单<WorkspaceSelect
              v-model="completionForm.work_order_id"
              required
              @change="selectCompletionOrder(completionForm.work_order_id)"
              :options="[
                { label: '选择生产中工单', value: 0, disabled: true },
                ...workOrders
                  .filter(
                    (entry) =>
                      entry.status === 'in_progress' && Number(entry.remaining_output_quantity) > 0
                  )
                  .map((item) => ({
                    label: (
                      ' #' +
                      item.id +
                      ' · ' +
                      item.product_name +
                      ' · 待报工 ' +
                      item.remaining_output_quantity +
                      ' ' +
                      item.product_unit
                    ).trim(),
                    value: item.id
                  }))
              ]" /></label
          ><label
            >本次报工数量<AppInput
              v-model.trim="completionForm.reported_quantity"
              type="number"
              min="0.001"
              :max="selectedCompletionOrder?.remaining_output_quantity"
              step="0.001"
              required /></label
          ><label
            >参考号（可选）<AppInput v-model.trim="completionForm.reference" maxlength="100"
          /></label>
        </div>
        <AppButton
          type="submit"
          :disabled="busy || !completionForm.work_order_id"
          variant="primary"
        >
          保存报工草稿
        </AppButton>
      </form>
    </NModal>
    <!-- 主标题由工作台提供，列表复用仓库管理的筛选区、状态和单元格布局。 -->
    <WorkspaceTable
      :show-title="false"
      title="完工与质检"
      :data="filteredRecords"
      :columns="recordColumns"
      :min-table-width="1100"
    >
      <template #actions>
        <AppButton
          v-if="can('production_completion.create')"
          type="button"
          :disabled="busy"
          @click="createOpen = true"
          variant="primary"
        >
          新建完工报工单
        </AppButton>
      </template>
      <template #filters>
        <label>
          搜索完工与质检
          <AppInput v-model="recordQuery" placeholder="单号、名称或物料" />
        </label>
      </template>

      <template #cell-document="{ row: item }">
        <div>
          <strong>
            {{ documentLabel(item) }} · 工单 {{ relatedDocumentLabel(item, 'work_order') }} · {{ item.product_name }} ·
            {{ item.warehouse_name }}
          </strong>
          <p class="muted">
            {{ localTime(item.created_at) }} · 报工人
            {{ item.created_by_name }}
            <span v-if="item.reference">· {{ item.reference }}</span>
          </p>
        </div>
      </template>
      <template #cell-status="{ row: item }">
        <span class="pill" :class="item.status">
          {{
            {
              draft: '待质检',
              inspected: '已质检',
              posted: '已入库',
              reversed: '已冲销',
              cancelled: '已取消'
            }[item.status]
          }}
        </span>
      </template>
      <template #cell-details="{ row: item }">
        <div class="workspace-record-lines">
          <span>
            报工 {{ item.reported_quantity }} · 合格 {{ item.accepted_quantity ?? '待质检' }} ·
            不合格
            {{ item.rejected_quantity ?? '待质检' }}
            {{ item.product_unit }}
          </span>
          <span v-if="item.qc_note">
            质检说明：{{ item.qc_note }} · 质检人 {{ item.inspected_by_name }}
          </span>
          <span v-if="item.physical_lots?.length">
            {{ item.status === 'reversed' ? '原实物批次' : '实物批次' }}：{{ item.physical_lots.map(lot => `${lot.code}（${lot.quantity}）`).join('、') }}
          </span>
          <span v-else-if="item.status === 'posted' && Number(item.accepted_quantity) > 0">
            未登记实物批次，数量在批次核对页显示为差额。
          </span>
          <span v-if="item.reversal_id">
            冲销 #{{ item.reversal_id }} · {{ item.reversal_reason }} ·
            {{ item.reversed_by_name }} ·
            {{ localTime(item.reversed_at!) }}
          </span>
        </div>
      </template>
      <template #cell-actions="{ row: item }">
        <RouterLink v-if="item.status === 'posted' && !item.reversal_id && Number(item.rejected_quantity) > 0 && can('quality.view')" to="/workspace/production-quality">处理不合格品</RouterLink>
        <div class="form-actions">
          <AppButton
            v-if="item.status === 'inspected' && can('production_completion.post')"
            type="button"
            :disabled="busy"
            @click="startLotPost(item)"
            variant="primary"
            size="small"
          >
            {{ Number(item.accepted_quantity) > 0 ? '登记批次并确认' : '确认整批不合格' }}
          </AppButton>
          <AppButton
            v-if="
              (item.status === 'draft' || item.status === 'inspected') &&
              can('production_completion.cancel')
            "
            type="button"
            :disabled="busy"
            @click="cancelProductionCompletion(item.id)"
            variant="secondary"
            size="small"
          >
            取消
          </AppButton>
        </div>
        <form
          v-if="
            item.status === 'draft' &&
            can('production_completion.inspect') &&
            inspectionDrafts[item.id]
          "
          class="inline-form"
          @submit.prevent="inspectProductionCompletion(item.id)"
        >
          <label>
            合格数量
            <AppInput
              v-model.trim="inspectionDrafts[item.id]!.accepted_quantity"
              type="number"
              min="0"
              :max="item.reported_quantity"
              step="0.001"
              required
            />
          </label>
          <label>
            质检说明
            <AppInput v-model.trim="inspectionDrafts[item.id]!.qc_note" required maxlength="200" />
          </label>
          <AppButton type="submit" :disabled="busy" variant="primary" size="small"
            >记录质检结果</AppButton
          >
        </form>
        <form
          v-if="item.status === 'posted' && can('production_completion.reverse')"
          class="inline-form"
          @submit.prevent="reverseProductionCompletion(item.id)"
        >
          <label>
            冲销原因
            <AppInput
              v-model.trim="completionReversalReasons[item.id]"
              required
              maxlength="200"
              placeholder="说明报工或质检记录错误"
            />
          </label>
          <AppButton type="submit" :disabled="busy" variant="secondary" size="small"
            >冲销已确认完工</AppButton
          >
        </form>
      </template>
      <template #empty>
        <strong>{{ recordQuery ? '没有匹配的记录' : '暂无完工与质检记录' }}</strong>
        <span>
          {{
            recordQuery
              ? '可调整单号、名称或物料关键词后重新搜索。'
              : '业务记录生成后，可在这里查看明细与处理状态。'
          }}
        </span>
      </template>
    </WorkspaceTable>
    <NModal :show="!!activeCompletion" @update:show="value=>{if(!value) activeCompletionId=0}"
      preset="card" :mask-closable="!busy" :style="{width:'min(900px,calc(100vw - 32px))',
        maxHeight:'calc(100vh - 48px)',overflowY:'auto'}">
      <form v-if="activeCompletion && can('production_completion.post')" class="stack"
        @submit.prevent="confirmLotPost">
        <h2>完工单 {{ documentLabel(activeCompletion) }} · 合格品实物批次</h2>
        <p>按实际分开的成品批次登记，数量之和须等于合格入库量。系统生成独立内部编号供实物标识；缺少日期时留空。</p>
        <p>{{ activeCompletion.product_name }} · {{ activeCompletion.warehouse_name }} · 合格 {{ activeCompletion.accepted_quantity }} {{ activeCompletion.product_unit }}</p>
        <div v-for="(part,index) in lotDrafts" :key="index" class="completion-lot-grid">
          <label>批次数量<AppInput v-model="part.quantity" inputmode="decimal" required :disabled="busy" /></label>
          <label>生产日期<NDatePicker v-date-field="{min:'2000-01-01',max:'2099-12-31'}" to="body" type="date" format="yyyy-MM-dd" value-format="yyyy-MM-dd" :formatted-value="part.manufactured_on" :disabled="busy" @update:formatted-value="value=>part.manufactured_on=datePickerString(value)||null" /></label>
          <label>失效日期<NDatePicker v-date-field="{min:'2000-01-01',max:'2099-12-31'}" to="body" type="date" format="yyyy-MM-dd" value-format="yyyy-MM-dd" :formatted-value="part.expires_on" :disabled="busy" @update:formatted-value="value=>part.expires_on=datePickerString(value)||null" /></label>
          <AppButton v-if="lotDrafts.length>1" type="button" :disabled="busy" @click="lotDrafts.splice(index,1)">移除批次</AppButton>
        </div>
        <AppButton type="button" :disabled="busy || lotDrafts.length>=20" @click="addLot">添加一个批次</AppButton>
        <p v-if="lotIssue" role="alert">{{ lotIssue }}</p>
        <div class="form-actions">
          <AppButton type="submit" variant="primary" :disabled="busy || connectionLost || !!lotIssue">确认合格品入库并固定批次</AppButton>
          <AppButton type="button" :disabled="busy" @click="activeCompletionId=0">取消</AppButton>
        </div>
      </form>
    </NModal>
  </section>
</template>

<style scoped>
.completion-lot-grid{display:grid;grid-template-columns:repeat(3,minmax(150px,1fr));gap:12px;align-items:end}
@media(max-width:700px){.completion-lot-grid{grid-template-columns:1fr}}
</style>
