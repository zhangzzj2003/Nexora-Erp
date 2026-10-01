<script setup lang="ts">
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
// 下拉选择统一使用工作台组件，业务值与切换回调保持原有类型。
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { recordColumns, matchesRecordQuery } from '../../../utils/workspace-records'
import { computed, ref } from 'vue'
import { NModal } from 'naive-ui'
import { useAppStore } from '../../../store/app-store'
import { submitCreateDialog } from '../../../utils/create-dialog'

// 页面直接使用共享状态与操作，切换标签时不会丢失正在填写的草稿。
const {
  error,
  notice,
  busy,
  workOrders,
  materialIssues,
  warehouses,
  materialIssueForm,
  can,
  selectedIssueOrder,
  localTime,
  selectIssueOrder,
  createMaterialIssue,
  postMaterialIssue,
  cancelMaterialIssue,
  selectReturnIssue
} = useAppStore()

// 保存失败时保留弹窗和草稿，方便直接修正后重试。
const createOpen = ref(false)
async function submitCreate(): Promise<void> {
  await submitCreateDialog(createMaterialIssue, { busy, error, notice }, createOpen)
}
// 只筛选当前列表快照，原有单据状态与跨页面草稿保持不变。
const recordQuery = ref('')
const filteredRecords = computed(() =>
  materialIssues.value.filter((item) =>
    matchesRecordQuery(recordQuery.value, [
      item.id,
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
            >生产工单<WorkspaceSelect remote-dataset="workOrders" :remote-filters="{statuses:'released,in_progress'}"
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
            >领料源仓库<WorkspaceSelect remote-dataset="warehouses"
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
    <WorkspaceTable dataset="materialIssues" :query="recordQuery"
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
            >#{{ item.id }} · 工单 #{{ item.work_order_id }} · {{ item.warehouse_name }}</strong
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
          {{ { draft: '草稿', posted: '已确认', cancelled: '已取消' }[item.status] }}
        </span>
      </template>
      <template #cell-details="{ row: item }">
        <div class="workspace-record-lines">
          <span v-for="line in item.lines" :key="line.id">
            {{ line.material_name }} · 已领 {{ line.quantity }} · 已退
            {{ line.returned_quantity }} · 可退 {{ line.returnable_quantity }} {{ line.unit }}
          </span>
        </div>
      </template>
      <template #cell-actions="{ row: item }">
        <div class="form-actions">
          <AppButton
            v-if="item.status === 'draft' && can('material_issue.post')"
            type="button"
            :disabled="busy"
            @click="postMaterialIssue(item.id)"
            variant="primary"
            size="small"
          >
            确认领料
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
  </section>
</template>
