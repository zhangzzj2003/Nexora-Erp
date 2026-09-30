<script setup lang="ts">
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
const { error, notice, user, busy, connectionLost, warehouses, materials, stockAdjustments,
  adjustmentForm, adjustmentDecisionReasons, adjustmentReversalReasons } = storeToRefs(store)
const { can, localTime, createStockAdjustment, submitStockAdjustment,
  approveStockAdjustment, rejectStockAdjustment, cancelStockAdjustment,
  postStockAdjustment, reverseStockAdjustment } = store
const showForm = ref(false)
const query = ref('')
const filtered = computed(() => stockAdjustments.value.filter((item) =>
  [item.id, item.warehouse_name, item.reason, item.reference, ...item.lines.map((line) => line.material_name)]
    .join(' ').toLowerCase().includes(query.value.trim().toLowerCase())))
const statusLabel = { draft: '草稿', submitted: '待审批', approved: '待仓库确认',
  rejected: '已驳回', cancelled: '已取消', posted: '已确认' }
const columns = [
  { key: 'document', title: '单据' }, { key: 'source', title: '仓库与原因' },
  { key: 'lines', title: '调整明细' }, { key: 'actions', title: '操作' }
]
// 写入失败时保留表单，成功后才关闭弹窗。
async function submitCreate(): Promise<void> {
  await submitCreateDialog(createStockAdjustment, { busy, error, notice }, showForm)
}
</script>

<template>
  <section class="stack">
    <WorkspaceTable dataset="stockAdjustments" :query="query"
      :show-title="false"
      :data="filtered"
      title="库存调整"
      :columns="columns"
      :min-table-width="1050"
    >
      <template #actions>
        <AppButton
          v-if="can('adjustment.create')"
          :disabled="busy || connectionLost"
          @click="showForm = true"
          variant="primary"
          type="button"
          >新建调整</AppButton
        >
      </template>
      <template #filters
        ><label>搜索调整单<AppInput v-model="query" placeholder="单号、仓库或物料" /></label
      ></template>
      <template #beforeTable>
        <NModal
          v-model:show="showForm"
          preset="card"
          :mask-closable="!busy"
          :style="{
            width: 'min(900px, calc(100vw - 32px))',
            maxHeight: 'calc(100vh - 48px)',
            overflowY: 'auto'
          }"
        >
          <form
            v-if="showForm && can('adjustment.create')"
            class="stack"
            @submit.prevent="submitCreate"
          >
            <div class="form-grid">
              <label
                >仓库<WorkspaceSelect remote-dataset="warehouses"
                  v-model="adjustmentForm.warehouse_id"
                  required
                  :options="[...warehouses.map((item) => ({ label: item.name, value: item.id }))]"
              /></label>
              <label
                >调整原因<AppInput v-model.trim="adjustmentForm.reason" required maxlength="200"
              /></label>
              <label
                >参考号<AppInput v-model.trim="adjustmentForm.reference" maxlength="100"
              /></label>
            </div>
            <div v-for="(line, index) in adjustmentForm.lines" :key="index" class="line-row">
              <label
                >物料<WorkspaceSelect remote-dataset="materials"
                  v-model="line.material_id"
                  required
                  :options="[
                    { label: '选择物料', value: 0, disabled: true },
                    ...materials.map((item) => ({
                      label: (item.sku + ' · ' + item.name).trim(),
                      value: item.id
                    }))
                  ]"
              /></label>
              <label
                >调整量<AppInput
                  v-model.trim="line.quantity"
                  type="number"
                  min="-1000000"
                  max="1000000"
                  step="0.001"
                  required
              /></label>
              <AppButton
                type="button"
                :disabled="adjustmentForm.lines.length === 1"
                @click="adjustmentForm.lines.splice(index, 1)"
                variant="text"
                >移除</AppButton
              >
            </div>
            <div class="form-actions">
              <AppButton
                type="button"
                @click="adjustmentForm.lines.push({ material_id: 0, quantity: '1' })"
                variant="secondary"
                >添加明细</AppButton
              >
              <AppButton :disabled="busy || connectionLost" variant="primary" type="submit"
                >保存草稿</AppButton
              >
              <AppButton type="button" @click="showForm = false" variant="secondary"
                >收起</AppButton
              >
            </div>
            <p class="muted">正数为增加，负数为减少；零调整量不会保存。</p>
          </form>
        </NModal>
      </template>
      <template #cell-document="{ row: item }"
        ><strong>#{{ item.id }}</strong
        ><small>{{ statusLabel[item.status] }}{{ item.reversal_id ? ' · 已冲销' : '' }}</small
        ><small>{{ localTime(item.created_at) }} · {{ item.created_by_name }}</small
        ><small v-if="item.reviewed_by_name">审批：{{ item.reviewed_by_name }}</small></template
      >
      <template #cell-source="{ row: item }"
        >{{ item.warehouse_name }}<small>{{ item.reason }}</small
        ><small v-if="item.reference">{{ item.reference }}</small
        ><small v-if="item.review_reason">驳回：{{ item.review_reason }}</small></template
      >
      <template #cell-lines="{ row: item }"
        ><div v-for="line in item.lines" :key="line.id">
          {{ line.material_name }} {{ line.quantity.startsWith('-') ? '' : '+'
          }}{{ line.quantity }} {{ line.unit }}
        </div></template
      >
      <template #cell-actions="{ row: item }"
        ><div class="form-actions">
          <AppButton
            v-if="item.status === 'draft' && can('adjustment.submit')"
            :disabled="busy || connectionLost"
            @click="submitStockAdjustment(item.id)"
            variant="primary"
            size="small"
            type="button"
            >提交</AppButton
          >
          <AppButton
            v-if="
              item.status === 'submitted' &&
              can('adjustment.review') &&
              user?.id !== item.created_by
            "
            :disabled="busy || connectionLost"
            @click="approveStockAdjustment(item.id)"
            variant="primary"
            size="small"
            type="button"
            >批准</AppButton
          >
          <AppButton
            v-if="item.status === 'approved' && can('adjustment.post')"
            :disabled="busy || connectionLost"
            @click="postStockAdjustment(item.id)"
            variant="primary"
            size="small"
            type="button"
            >仓库确认</AppButton
          >
          <AppButton
            v-if="
              ['draft', 'submitted', 'approved', 'rejected'].includes(item.status) &&
              can('adjustment.cancel')
            "
            :disabled="busy || connectionLost"
            @click="cancelStockAdjustment(item.id)"
            variant="secondary"
            size="small"
            type="button"
            >取消</AppButton
          >
        </div>
        <form
          v-if="
            item.status === 'submitted' && can('adjustment.review') && user?.id !== item.created_by
          "
          class="inline-form"
          @submit.prevent="rejectStockAdjustment(item.id)"
        >
          <label
            >驳回原因<AppInput
              v-model.trim="adjustmentDecisionReasons[item.id]"
              required
              maxlength="200" /></label
          ><AppButton
            :disabled="busy || connectionLost"
            variant="secondary"
            size="small"
            type="submit"
            >驳回</AppButton
          >
        </form>
        <form
          v-if="item.status === 'posted' && !item.reversal_id && can('adjustment.reverse')"
          class="inline-form"
          @submit.prevent="reverseStockAdjustment(item.id)"
        >
          <label
            >冲销原因<AppInput
              v-model.trim="adjustmentReversalReasons[item.id]"
              required
              maxlength="200" /></label
          ><AppButton
            :disabled="busy || connectionLost"
            variant="secondary"
            size="small"
            type="submit"
            >冲销</AppButton
          >
        </form>
        <small v-if="item.reversal_reason">冲销：{{ item.reversal_reason }}</small></template
      >
      <template #empty>{{ query ? '没有匹配的库存调整单。' : '暂无库存调整单。' }}</template>
    </WorkspaceTable>
  </section>
</template>
