<script setup lang="ts">
// 页面只展示服务端保存的单号，原内部 ID 继续用于业务操作。
import { documentLabel, relatedDocumentLabel } from '../../../../../shared/document-numbering'
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
// 下拉选择统一使用工作台组件，业务值与切换回调保持原有类型。
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { NModal } from 'naive-ui'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { submitCreateDialog } from '../../../utils/create-dialog'

const store = usePiniaAppStore()
const {
  busy,
  error,
  notice,
  connectionLost,
  inventoryValuation,
  inventoryCostInputs,
  inventoryCostForm
} = storeToRefs(store)
const { can, localTime, recordInventoryCost, refreshData, perform } = store
const showForm = ref(false)
const search = ref('')
const columns = [
  { key: 'material', title: '物料' },
  { key: 'quantity', title: '现存数量' },
  { key: 'average', title: '移动平均单价' },
  { key: 'amount', title: '库存金额' }
]
const sourceColumns = [
  { key: 'movement', title: '待核价流水' },
  { key: 'material', title: '物料' },
  { key: 'quantity', title: '入库数量' },
  { key: 'source', title: '来源' }
]
const historyColumns = [
  { key: 'movement', title: '流水' },
  { key: 'price', title: '核定单价' },
  { key: 'reference', title: '依据与原因' },
  { key: 'actor', title: '操作人及时间' }
]
const materials = computed(
  () =>
    inventoryValuation.value?.materials.filter((item) =>
      `${item.sku} ${item.name}`.toLowerCase().includes(search.value.trim().toLowerCase())
    ) ?? []
)
const unpriced = computed(
  () =>
    inventoryValuation.value?.movements.filter((item) =>
      inventoryValuation.value?.unpriced_movement_ids.includes(item.id)
    ) ?? []
)
const priceable = computed(
  () =>
    inventoryValuation.value?.movements.filter(
      (item) =>
        ['receipt', 'other_inbound', 'stocktake', 'adjustment', 'production_completion'].includes(
          item.source_type
        ) &&
        (unpriced.value.some((missing) => missing.id === item.id) || item.cost_source === 'manual')
    ) ?? []
)
const materialName = (id: number): string =>
  inventoryValuation.value?.materials.find((item) => item.id === id)?.name ?? `物料 #${id}`

async function submitPrice(): Promise<void> {
  await submitCreateDialog(recordInventoryCost, { busy, error, notice }, showForm)
}
</script>

<template>
  <section class="stack">
    <!-- 页面说明随主标题展示，刷新和核价按钮共用筛选工具栏。 -->
    <WorkspaceTable :show-title="false" title="库存计价" :columns="columns" :data="materials">
      <template #actions>
        <AppButton
          :disabled="busy"
          @click="perform(refreshData, '库存金额已刷新。')"
          variant="secondary"
          type="button"
          >刷新</AppButton
        >
        <AppButton
          v-if="can('inventory_valuation.record') && priceable.length"
          :disabled="busy || connectionLost"
          @click="showForm = true"
          variant="primary"
          type="button"
          >登记核价</AppButton
        >
      </template>
      <template #filters
        ><label>搜索物料<AppInput v-model="search" placeholder="编码或名称" /></label
      ></template>
      <template #beforeTable>
        <div class="summary-grid">
          <div class="metric">
            <span>库存总金额</span
            ><strong>{{
              inventoryValuation?.total_amount === null
                ? '待核价'
                : `¥${inventoryValuation?.total_amount ?? '0.00'}`
            }}</strong>
          </div>
          <div class="metric">
            <span>待核价入库流水</span><strong>{{ unpriced.length }}</strong>
          </div>
          <div class="metric">
            <span>核价修订记录</span><strong>{{ inventoryCostInputs.length }}</strong>
          </div>
        </div>
        <NModal title="登记库存核价"
          v-model:show="showForm"
          preset="card"
          :mask-closable="!busy"
          :style="{ width: 'min(680px, calc(100vw - 32px))' }"
        >
          <form
            v-if="showForm && can('inventory_valuation.record')"
            class="stack"
            @submit.prevent="submitPrice"
          >
            <!-- 标题统一放在弹窗顶部，原表单与操作布局保持不变。 -->
            <p class="muted">每次修订都会保留原核价、依据、原因与操作人，并重算后续库存金额。</p>
            <div class="form-grid">
              <label
                >入库流水<WorkspaceSelect
                  v-model="inventoryCostForm.movement_id"
                  required
                  :options="[
                    { label: '选择待核价流水', value: 0, disabled: true },
                    ...priceable.map((item) => ({
                      label: (
                        '#' +
                        item.id +
                        ' · ' +
                        materialName(item.material_id) +
                        ' · ' +
                        item.quantity +
                        (item.cost_source === 'manual' ? ' · 已核价，可修订' : '')
                      ).trim(),
                      value: item.id
                    }))
                  ]"
              /></label>
              <label
                >核定单价<AppInput
                  v-model="inventoryCostForm.unit_cost"
                  type="number"
                  min="0"
                  max="1000000000"
                  step="0.0001"
                  required
              /></label>
              <label
                >依据编号<AppInput
                  v-model.trim="inventoryCostForm.reference"
                  maxlength="100"
                  required
              /></label>
              <label
                >核价原因<AppInput v-model.trim="inventoryCostForm.reason" maxlength="200" required
              /></label>
            </div>
            <div class="form-actions">
              <AppButton :disabled="busy || connectionLost" variant="primary" type="submit"
                >保存核价</AppButton
              >
              <AppButton type="button" @click="showForm = false" variant="secondary"
                >取消</AppButton
              >
            </div>
          </form>
        </NModal>
      </template>
      <template #cell-material="{ row: item }"
        ><strong>{{ item.sku }}</strong
        ><small>{{ item.name }}</small></template
      >
      <template #cell-quantity="{ row: item }">{{ item.quantity }} {{ item.unit }}</template>
      <template #cell-average="{ row: item }">{{ item.average_unit_cost ?? '待核价' }}</template>
      <template #cell-amount="{ row: item }">{{
        item.amount === null ? '待核价' : `¥${item.amount}`
      }}</template>
    </WorkspaceTable>
    <WorkspaceTable
      title="待核价来源"
      description="历史无价入库、赠品及其他没有成本依据的入库需要人工核价。"
      :columns="sourceColumns"
      :data="unpriced"
    >
      <template #cell-movement="{ row: item }">{{ documentLabel(item) }}</template>
      <template #cell-material="{ row: item }">{{ materialName(item.material_id) }}</template>
      <template #cell-quantity="{ row: item }">{{ item.quantity }}</template>
      <template #cell-source="{ row: item }">{{ item.source_type }} {{ relatedDocumentLabel(item, 'source') }}</template>
    </WorkspaceTable>
    <WorkspaceTable
      title="核价修订历史"
      description="最新一条核价生效，历史记录仍可追溯。"
      :columns="historyColumns"
      :data="inventoryCostInputs"
    >
      <template #cell-movement="{ row: item }">#{{ item.movement_id }}</template>
      <template #cell-price="{ row: item }">¥{{ item.unit_cost }}</template>
      <template #cell-reference="{ row: item }"
        >{{ item.reference }}<small>{{ item.reason }}</small></template
      >
      <template #cell-actor="{ row: item }"
        >{{ item.created_by_name }}<small>{{ localTime(item.created_at) }}</small></template
      >
    </WorkspaceTable>
  </section>
</template>
