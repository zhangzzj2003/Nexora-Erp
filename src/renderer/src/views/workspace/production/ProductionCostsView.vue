<script setup lang="ts">
// 页面只展示服务端保存的单号，原内部 ID 继续用于业务操作。
import { documentSearch, documentLabel, relatedDocumentLabel } from '../../../../../shared/document-numbering'
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
// 下拉选择统一使用工作台组件，业务值与切换回调保持原有类型。
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import { recordColumns, matchesRecordQuery } from '../../../utils/workspace-records'
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { NCollapse, NModal } from 'naive-ui'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import DocumentApprovalDialog from '../../../components/workspace/DocumentApprovalDialog.vue'
import type { ProductionCostSettlement } from '../../../../../shared/erp-api'
import { submitCreateDialog } from '../../../utils/create-dialog'

// 页面直接使用共享状态与操作，切换标签时不会丢失正在填写的草稿。
const store = usePiniaAppStore()
const {
  busy,
  error,
  notice,
  connectionLost,
  productionCostReport,
  productionCostSettlements,
  productionSettlementForm,
  settlementReversalReasons,
  materialValuationForm,
  productionChargeForm,
  costReversalReasons, user, server
} = storeToRefs(store)
const {
  can,
  localTime,
  recordMaterialValuation,
  recordProductionCharge,
  reverseProductionCost,
  settleProductionCost,
  reverseProductionSettlement, openDocumentApproval, changeProductionSettlementStatus
} = store
// 普通确认保护业务与批准代次；切服、换账号或撤权立即关闭旧操作。
const settlementCommand=ref<{row:ProductionCostSettlement;action:'post'|'cancel'}|null>(null)
const settlementReason=ref('')
watch(()=>`${server.value?.id}:${server.value?.fingerprint}:${user.value?.id}:${user.value?.roles.join('|')}:${user.value?.permissions.join('|')}`,()=>{
  settlementCommand.value=null;showSettlementForm.value=false
})
function mayExecuteSettlement(row:ProductionCostSettlement,action:'post'|'cancel'):boolean {
  return row.status==='draft' && can('production_cost.settle') && (action==='post' ? row.approval?.status==='approved' : !['submitted','approved'].includes(row.approval?.status??''))
}
function askSettlement(row:ProductionCostSettlement,action:'post'|'cancel'):void {
  if(!mayExecuteSettlement(row,action))return
  settlementCommand.value={row,action};settlementReason.value=''
}
async function confirmSettlement():Promise<void> {
  if(!settlementCommand.value || busy.value || connectionLost.value)return
  const {row,action}=settlementCommand.value,current=productionCostSettlements.value.find(item=>item.id===row.id)
  if(!current || current.version!==row.version || current.approval?.version!==row.approval?.version || !mayExecuteSettlement(current,action)){
    error.value='成本结算或批准已变化，请重新读取。';settlementCommand.value=null;return
  }
  await changeProductionSettlementStatus(current,action,settlementReason.value)
  if(!error.value)settlementCommand.value=null
}
// 分别搜索工单与成本记录，不改变待核价及冲销金额的展示。
const costQuery = ref('')
const entryQuery = ref('')
const costColumns = recordColumns
const showSettlementForm = ref(false)
const settledOrderIds = computed(
  () =>
    new Set(
      productionCostSettlements.value
        .filter((item) => item.status === 'active')
        .map((item) => item.work_order_id)
    )
)
const settlementOptions = computed(() =>
  (productionCostReport.value?.orders ?? [])
    .filter(
      (item) =>
        item.work_order_status === 'completed' && item.total_amount !== null && !item.settlement_id
    )
    .map((item) => ({
      value: item.work_order_id,
      label: `工单 ${relatedDocumentLabel(item, 'work_order')} · ${item.product_name} · ¥${item.total_amount}`
    }))
)
const settlementColumns = recordColumns
const sourceColumns = [
  { key: 'issue', title: '工单与领料' },
  { key: 'material', title: '物料' },
  { key: 'quantity', title: '净领数量' },
  { key: 'cost', title: '成本来源与金额' }
]
const selectedOrder = computed(() =>
  productionCostReport.value?.orders.find(
    (item) => item.work_order_id === productionSettlementForm.value.work_order_id
  )
)
function openSettlement(orderId: number): void {
  productionSettlementForm.value.work_order_id = orderId
  showSettlementForm.value = true
}
async function submitSettlement(): Promise<void> {
  await submitCreateDialog(settleProductionCost, { busy, error, notice }, showSettlementForm)
}
const costUnit = (value: string): string => Number(value).toFixed(4)
const filteredOrders = computed(() =>
  (productionCostReport.value?.orders ?? []).filter((item) =>
    matchesRecordQuery(costQuery.value, [documentSearch(item), item.work_order_id, item.product_name])
  )
)
// 结算单单独检索系统号、外部依据和工单关联，不混入费用明细 ID。
const settlementQuery = ref('')
const filteredSettlements = computed(() => productionCostSettlements.value.filter(item =>
  matchesRecordQuery(settlementQuery.value, [documentSearch(item), item.id, item.reference, item.work_order_id])))
const filteredEntries = computed(() =>
  (productionCostReport.value?.entries ?? []).filter((item) =>
    matchesRecordQuery(entryQuery.value, [documentSearch(item), item.id,
      item.work_order_id,
      item.material_name,
      item.reference,
      item.created_by_name
    ])
  )
)
</script>

<template>
  <section class="stack">
    <!-- 成本金额与冲销记录复用共享表格，核价规则保持原样。 -->
    <WorkspaceTable
      :show-title="false"
      title="生产成本"
      :columns="costColumns"
      :data="filteredOrders"
      :min-table-width="800"
    >
      <template #filters>
        <label>
          搜索生产工单
          <AppInput v-model="costQuery" placeholder="输入编号或名称" />
        </label>
      </template>
      <template #cell-document="{ row: item }">
        <strong>工单 {{ relatedDocumentLabel(item, 'work_order') }} · {{ item.product_name }}</strong>
      </template>
      <template #cell-status="{ row: item }">
        <span class="pill">
          {{
            item.settlement_id
              ? '已结算'
              : item.work_order_status === 'draft'
                ? '未下达'
                : item.total_amount === null
                  ? (item.unpriced_rework ? '来源待结算' : '待核价')
                  : '当前已知'
          }}
        </span>
      </template>
      <template #cell-actions="{ row: item }">
        <AppButton
          v-if="
            can('production_cost.settle') &&
            item.work_order_status === 'completed' &&
            !item.settlement_id
          "
          size="small"
          :disabled="busy || connectionLost || item.total_amount === null"
          @click="openSettlement(item.work_order_id)"
          variant="primary"
          type="button"
          >结算完工成本</AppButton
        >
        <span v-else-if="item.settlement_id" class="muted">结算 {{ relatedDocumentLabel(item, 'settlement') }}</span>
      </template>
      <template #cell-details="{ row: item }">
        <div class="workspace-record-lines">
          <span>材料已知金额 ¥{{ item.known_material_amount }}</span>
          <span>人工 ¥{{ item.labor_amount }}</span>
          <span>制造费用 ¥{{ item.overhead_amount }}</span>
          <span v-if="item.rework_source">返工来源 {{ item.rework_source.reference }} · 原工单 {{ relatedDocumentLabel(item.rework_source, 'origin_work_order') }} · 携入 {{ item.rework_amount === null ? '原工单尚未结算' : `¥${item.rework_amount}` }}</span>
          <span>总成本 {{ item.total_amount === null ? (item.unpriced_rework ? '原工单尚未结算' : '待核价') : `¥${item.total_amount}` }}</span>
          <span v-if="item.unpriced_issue_count"
            >待核价领料 {{ item.unpriced_issue_count }} 条</span
          >
        </div>
      </template>

      <template #empty>{{ costQuery ? '没有匹配的记录。' : '暂无生产工单。' }}</template>
    </WorkspaceTable>
    <NModal
      v-model:show="showSettlementForm"
      preset="card"
      title="结算完工成本"
      :mask-closable="!busy"
      :style="{ width: 'min(680px, calc(100vw - 32px))' }"
    >
      <form class="flex flex-col gap-4" @submit.prevent="submitSettlement">
        <p class="muted">
          工单全部报工且不合格数量全部确认处置后，按所选规则分摊材料、人工、制造费用与返工携入成本。正常报废由合格品承担，独立报废列损失，返工携带来源成本。先保存预计草稿，独立批准执行后才更新正式计价和锁定来源；更正来源前须先冲销下游及原结算。
        </p>
        <label
          >生产工单<WorkspaceSelect
            v-model="productionSettlementForm.work_order_id"
            :options="settlementOptions"
            :disabled="busy"
        /></label>
        <p v-if="selectedOrder">
          材料 ¥{{ selectedOrder.known_material_amount }} · 人工 ¥{{ selectedOrder.labor_amount }} ·
          制造费用 ¥{{ selectedOrder.overhead_amount }} · 返工携入 ¥{{ selectedOrder.rework_amount ?? '待来源结算' }} · 合计 ¥{{ selectedOrder.total_amount }}
        </p>
        <label
          >结算依据编号<AppInput
            v-model="productionSettlementForm.reference"
            :maxlength="100"
            :disabled="busy"
            placeholder="成本结算单编号"
        /></label>
        <label
          >说明<AppInput
            v-model="productionSettlementForm.note"
            :maxlength="200"
            :disabled="busy"
        /></label>
        <div class="flex justify-end gap-3">
          <AppButton
            :disabled="busy"
            @click="showSettlementForm = false"
            variant="secondary"
            type="button"
            >取消</AppButton
          >
          <AppButton
            type="submit"
            :loading="busy"
            :disabled="
              connectionLost || !selectedOrder || !productionSettlementForm.reference.trim()
            "
            variant="primary"
            >保存结算草稿</AppButton
          >
        </div>
      </form>
    </NModal>
    <div v-if="can('production_cost.record')" class="two-columns">
      <div class="card">
        <div class="section-heading"><h2>核定领料单价</h2></div>
        <form @submit.prevent="recordMaterialValuation">
          <div class="form-grid">
            <label
              >待核价领料<WorkspaceSelect
                v-model="materialValuationForm.material_issue_line_id"
                required
                :options="[
                  { label: '选择领料明细', value: 0, disabled: true },
                  ...(productionCostReport?.unpriced_lines ?? []).map((line) => ({
                    label: (
                      ' 工单 #' +
                      line.work_order_id +
                      ' · 领料 #' +
                      line.material_issue_id +
                      ' · ' +
                      line.material_name +
                      ' · 净领 ' +
                      line.net_quantity +
                      ' ' +
                      line.unit
                    ).trim(),
                    value: line.material_issue_line_id
                  }))
                ]" /></label
            ><label
              >核定单价（元）<AppInput
                v-model.trim="materialValuationForm.unit_cost"
                type="number"
                min="0"
                max="1000000000"
                step="0.0001"
                required /></label
            ><label
              >依据编号<AppInput
                v-model.trim="materialValuationForm.reference"
                maxlength="100"
                required
                placeholder="发票或内部核价单编号" /></label
            ><label
              >说明（可选）<AppInput v-model.trim="materialValuationForm.note" maxlength="200"
            /></label>
          </div>
          <AppButton
            type="submit"
            :disabled="busy || !materialValuationForm.material_issue_line_id"
            variant="primary"
          >
            保存核价
          </AppButton>
        </form>
      </div>
      <div class="card">
        <div class="section-heading"><h2>登记人工或制造费用</h2></div>
        <form @submit.prevent="recordProductionCharge">
          <div class="form-grid">
            <label
              >生产工单<WorkspaceSelect
                v-model="productionChargeForm.work_order_id"
                required
                :options="[
                  { label: '选择已下达工单', value: 0, disabled: true },
                  ...(productionCostReport?.orders ?? [])
                    .filter(
                      (entry) =>
                        entry.work_order_status !== 'draft' &&
                        entry.work_order_status !== 'cancelled' &&
                        !entry.settlement_id
                    )
                    .map((item) => ({
                      label: (' #' + item.work_order_id + ' · ' + item.product_name).trim(),
                      value: item.work_order_id
                    }))
                ]" /></label
            ><label
              >费用类别<WorkspaceSelect
                v-model="productionChargeForm.kind"
                :options="[
                  { label: '人工', value: 'labor' },
                  { label: '制造费用', value: 'overhead' }
                ]" /></label
            ><label
              >金额（元）<AppInput
                v-model.trim="productionChargeForm.amount"
                type="number"
                min="0.01"
                max="1000000000000"
                step="0.01"
                required /></label
            ><label
              >依据编号<AppInput
                v-model.trim="productionChargeForm.reference"
                maxlength="100"
                required /></label
            ><label
              >说明（可选）<AppInput v-model.trim="productionChargeForm.note" maxlength="200"
            /></label>
          </div>
          <AppButton
            type="submit"
            :disabled="busy || !productionChargeForm.work_order_id"
            variant="primary"
          >
            登记费用
          </AppButton>
        </form>
      </div>
    </div>
    <WorkspaceTable
      title="当前领料成本来源"
      :columns="sourceColumns"
      :data="productionCostReport?.material_sources ?? []"
    >
      <template #cell-issue="{ row: item }"
        >工单 {{ relatedDocumentLabel(item, 'work_order') }} · 领料 {{ relatedDocumentLabel(item, 'material_issue') }}</template
      >
      <template #cell-material="{ row: item }">{{ item.sku }} · {{ item.material_name }}</template>
      <template #cell-quantity="{ row: item }">{{ item.net_quantity }}</template>
      <template #cell-cost="{ row: item }">
        {{ item.cost_source === 'inventory' ? '库存平均成本' : '人工核价' }} · 单价 ¥{{
          costUnit(item.unit_cost)
        }}
        · 金额 ¥{{ item.amount }}
      </template>
    </WorkspaceTable>
    <WorkspaceTable
      title="完工成本结算历史"
      :columns="settlementColumns"
      :data="filteredSettlements"
      :min-table-width="1000"
    >
      <template #filters><label>搜索结算单<AppInput v-model.trim="settlementQuery" placeholder="单号、参考号或工单" /></label></template>
      <template #cell-document="{ row: item }">
        <strong>结算 {{ documentLabel(item) }} · 工单 {{ relatedDocumentLabel(item, 'work_order') }}</strong>
        <p class="muted">
          {{ item.reference }} · {{ item.created_by_name }} · {{ localTime(item.created_at) }}
        </p>
      </template>
      <template #cell-status="{ row: item }"
        ><span class="pill">{{ item.status === 'active' ? '正式有效' : item.status === 'reversed' ? '已冲销' : item.status === 'cancelled' ? '已取消' : item.approval?.status === 'approved' ? '已批准待执行' : item.approval?.status === 'submitted' ? '审批中' : '预计草稿' }}</span></template
      >
      <template #cell-details="{ row: item }">
        <div class="workspace-record-lines">
          <span v-if="item.status === 'draft'">预计分摊，尚未正式计价或锁定来源。</span>
          <span>版本 {{ item.version }} · 实际执行 {{ item.executed_at ? localTime(item.executed_at) : '—' }}</span>
          <span>合格 {{ item.accepted_quantity }} · 总成本 ¥{{ item.total_amount }}</span>
          <span
            >材料 ¥{{ item.material_amount }} · 人工 ¥{{ item.labor_amount }} · 制造费用 ¥{{
              item.overhead_amount
            }}</span
          >
          <span v-if="item.note">{{ item.note }}</span>
          <span v-if="item.reversal_id"
            >{{ item.reversal_reason }} · {{ item.reversed_by_name }} ·
            {{ localTime(item.reversed_at!) }}</span
          >
        </div>
        <NCollapse class="mt-3">
          <AppCollapseItem title="查看分摊与来源快照" name="sources">
            <div class="flex flex-col gap-2">
              <span v-for="allocation in item.quality_allocations" :key="allocation.disposition_id">处置 {{ allocation.reference }} · 原完工 {{ relatedDocumentLabel(allocation, 'completion') }} · 数量 {{ allocation.quantity }} · {{ allocation.loss_treatment === 'absorb' ? '成本已由合格品承担' : allocation.loss_treatment === 'expense' ? `独立损失 ¥${allocation.amount}` : `携入返工 ¥${allocation.amount}` }}<template v-if="allocation.rework_order_id"> · 返工工单 {{ relatedDocumentLabel(allocation, 'rework_order') }}</template></span>
              <span v-for="source in item.rework_sources" :key="source.disposition_id">携入处置 {{ relatedDocumentLabel(source, 'disposition') }} · 原结算 {{ relatedDocumentLabel(source, 'origin_settlement') }} · ¥{{ source.amount }}</span>
              <span v-for="allocation in item.allocations" :key="allocation.movement_id"
                >完工 {{ relatedDocumentLabel(allocation, 'completion') }} · 流水 #{{ allocation.movement_id }} ·
                合格数量 {{ allocation.quantity }} · 分摊 ¥{{ allocation.amount }}</span
              >
              <span v-for="source in item.material_sources" :key="source.material_issue_line_id"
                >领料明细 #{{ source.material_issue_line_id }} · {{ source.material_name }} · 净领
                {{ source.net_quantity }} ·
                {{ source.cost_source === 'inventory' ? '库存平均成本' : '人工核价' }} ¥{{
                  costUnit(source.unit_cost)
                }}
                · 金额 ¥{{ source.amount }}</span
              >
              <span v-for="charge in item.charges" :key="charge.id"
                >费用 {{ documentLabel(charge) }} · {{ charge.kind === 'labor' ? '人工' : '制造费用' }} ·
                {{ charge.reference }} · ¥{{ charge.amount }}</span
              >
            </div>
          </AppCollapseItem>
        </NCollapse>
      </template>
      <template #cell-actions="{ row: item }">
        <AppButton type="button" variant="secondary" size="small" :disabled="busy || connectionLost"
          @click="openDocumentApproval({document_type:'ProductionCostSettlement',document_id:item.id,intent:'execute'})">结算审批</AppButton>
        <AppButton v-if="mayExecuteSettlement(item,'post')" type="button" size="small" :disabled="busy || connectionLost"
          @click="askSettlement(item,'post')">确认结算</AppButton>
        <AppButton v-if="mayExecuteSettlement(item,'cancel')" type="button" variant="secondary" size="small" :disabled="busy || connectionLost"
          @click="askSettlement(item,'cancel')">取消草稿</AppButton>
        <AppButton v-if="['active','reversed'].includes(item.status)" type="button" variant="secondary" size="small" :disabled="busy || connectionLost"
          @click="openDocumentApproval({document_type:'ProductionCostSettlement',document_id:item.id,intent:'reverse'})">{{item.status==='reversed'?'冲销记录':'冲销审批'}}</AppButton>
        <AppButton v-if="item.status==='active' && item.reversal_approval?.status==='approved' && can('production_cost.reopen')" type="button" size="small" :disabled="busy || connectionLost"
          @click="reverseProductionSettlement(item.id)">执行批准冲销</AppButton>
      </template>
    </WorkspaceTable>
    <!-- 成本金额与冲销记录复用共享表格，核价规则保持原样。 -->
    <WorkspaceTable
      title="成本记录与冲销"
      :columns="recordColumns"
      :data="filteredEntries"
      :min-table-width="1100"
    >
      <template #filters>
        <label>
          搜索成本记录
          <AppInput v-model="entryQuery" placeholder="输入编号或名称" />
        </label>
      </template>
      <template #cell-document="{ row: item }">
        <div>
          <strong>
            {{ documentLabel(item) }} · 工单 {{ relatedDocumentLabel(item, 'work_order') }} ·
            {{ { material: '材料核价', labor: '人工', overhead: '制造费用' }[item.kind] }}
          </strong>
          <p class="muted">
            {{ localTime(item.created_at) }} · {{ item.created_by_name }} · 依据
            {{ item.reference }}
          </p>
        </div>
      </template>
      <template #cell-status="{ row: item }">
        <span class="pill">{{ item.status === 'active' ? '有效' : '已冲销' }}</span>
      </template>
      <template #cell-details="{ row: item }">
        <div class="workspace-record-lines">
          <span v-if="item.kind === 'material'">
            {{ item.material_name }}（{{ item.material_sku }}）· 净领 {{ item.net_quantity }} · 单价
            ¥{{ item.unit_cost }}
          </span>
          <span>
            {{ item.included_in_current_cost ? '当前计入' : '记录金额' }}
            {{ item.current_amount === null ? '已冲销' : `¥${item.current_amount}` }}
          </span>
          <span
            v-if="
              item.status === 'active' && item.kind === 'material' && !item.included_in_current_cost
            "
            >此记录未用于当前成本，领料已采用库存平均成本。</span
          >
          <span v-if="item.note">{{ item.note }}</span>
          <span v-if="item.reversal_id">
            冲销原因：{{ item.reversal_reason }} · {{ item.reversed_by_name }} ·
            {{ localTime(item.reversed_at!) }}
          </span>
        </div>
      </template>
      <template #cell-actions="{ row: item }">
        <form
          v-if="
            item.status === 'active' &&
            can('production_cost.reverse') &&
            !settledOrderIds.has(item.work_order_id)
          "
          class="inline-form"
          @submit.prevent="reverseProductionCost(item.id)"
        >
          <label>
            冲销原因
            <AppInput v-model.trim="costReversalReasons[item.id]" required maxlength="200" />
          </label>
          <AppButton type="submit" :disabled="busy" variant="secondary" size="small"
            >冲销记录</AppButton
          >
        </form>
      </template>
      <template #empty>{{ entryQuery ? '没有匹配的记录。' : '暂无成本记录。' }}</template>
    </WorkspaceTable>
    <NModal :show="!!settlementCommand" preset="card" :title="settlementCommand?.action==='post'?'确认正式结算':'取消预计草稿'"
      :mask-closable="!busy" @update:show="value=>{if(!value)settlementCommand=null}" :style="{width:'min(600px,calc(100vw - 32px))'}">
      <p class="muted">{{ settlementCommand ? documentLabel(settlementCommand.row) : '' }}。执行重新核对数量、成本来源与期间，草稿和批准本身不计价。</p>
      <label>结算操作依据<AppInput v-model.trim="settlementReason" required maxlength="200" :disabled="busy" /></label>
      <AppButton type="button" :disabled="busy || connectionLost || !settlementReason" @click="confirmSettlement">确认操作</AppButton>
    </NModal>
    <DocumentApprovalDialog />
  </section>
</template>
