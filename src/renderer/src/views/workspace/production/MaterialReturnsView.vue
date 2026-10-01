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
  materialReturns,
  materialReturnForm,
  can,
  selectedReturnIssue,
  localTime,
  selectReturnIssue,
  createMaterialReturn,
  postMaterialReturn,
  cancelMaterialReturn
} = useAppStore()

// 保存失败时保留弹窗和草稿，方便直接修正后重试。
const createOpen = ref(false)
async function submitCreate(): Promise<void> {
  await submitCreateDialog(createMaterialReturn, { busy, error, notice }, createOpen)
}
// 只筛选当前列表快照，原有单据状态与跨页面草稿保持不变。
const recordQuery = ref('')
const filteredRecords = computed(() =>
  materialReturns.value.filter((item) =>
    matchesRecordQuery(recordQuery.value, [
      item.id,
      item.warehouse_name,
      item.created_by_name,
      item.reason,
      ...item.lines.map((line) => line.material_name)
    ])
  )
)
</script>

<template>
  <section class="stack">
    <NModal
      v-if="can('material_return.create')"
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
          <p class="eyebrow">MATERIAL RETURN</p>
          <h2>新建生产退料单</h2>
        </div>
        <span class="pill">草稿</span>
      </div>
      <p class="muted">
        只退回已确认领料的组件，确认后入原领料仓库，并恢复工单可领数量。请按实际退回数量填写。
      </p>
      <form @submit.prevent="submitCreate">
        <div class="form-grid">
          <label
            >原领料单<WorkspaceSelect remote-dataset="materialIssues" :remote-filters="{statuses:'posted'}"
              v-model="materialReturnForm.material_issue_id"
              required
              @change="selectReturnIssue(materialReturnForm.material_issue_id)"
              :options="[
                { label: '选择可退领料单', value: 0, disabled: true },
                ...materialIssues
                  .filter(
                    (entry) =>
                      entry.status === 'posted' &&
                      workOrders.some(
                        (order) =>
                          order.id === entry.work_order_id && order.status === 'in_progress'
                      ) &&
                      entry.lines.some((line) => Number(line.returnable_quantity) > 0)
                  )
                  .map((item) => ({
                    label: (
                      ' #' +
                      item.id +
                      ' · 工单 #' +
                      item.work_order_id +
                      ' · ' +
                      item.warehouse_name
                    ).trim(),
                    value: item.id
                  }))
              ]" /></label
          ><label
            >退料原因<AppInput v-model.trim="materialReturnForm.reason" required maxlength="200"
          /></label>
        </div>
        <h3>本次退料数量</h3>
        <div
          v-for="line in materialReturnForm.lines"
          :key="line.material_issue_line_id"
          class="line-row"
        >
          <label
            >{{
              selectedReturnIssue?.lines.find((item) => item.id === line.material_issue_line_id)
                ?.material_name
            }}
            · 可退
            {{
              selectedReturnIssue?.lines.find((item) => item.id === line.material_issue_line_id)
                ?.returnable_quantity
            }}<AppInput
              v-model.trim="line.quantity"
              type="number"
              min="0.001"
              :max="
                selectedReturnIssue?.lines.find((item) => item.id === line.material_issue_line_id)
                  ?.returnable_quantity
              "
              step="0.001"
              required /></label
          ><AppButton
            type="button"
            :disabled="busy"
            @click="
              materialReturnForm.lines = materialReturnForm.lines.filter(
                (item) => item.material_issue_line_id !== line.material_issue_line_id
              )
            "
            variant="text"
          >
            本次不退
          </AppButton>
        </div>
        <AppButton
          type="submit"
          :disabled="busy || !materialReturnForm.lines.length"
          variant="primary"
        >
          保存退料草稿
        </AppButton>
      </form>
    </NModal>
    <!-- 主标题由工作台提供，列表复用仓库管理的筛选区、状态和单元格布局。 -->
    <WorkspaceTable dataset="materialReturns" :query="recordQuery"
      :show-title="false"
      title="生产退料"
      :data="filteredRecords"
      :columns="recordColumns"
      :min-table-width="1100"
    >
      <template #actions>
        <AppButton
          v-if="can('material_return.create')"
          type="button"
          :disabled="busy"
          @click="createOpen = true"
          variant="primary"
        >
          新建生产退料单
        </AppButton>
      </template>
      <template #filters>
        <label>
          搜索生产退料
          <AppInput v-model="recordQuery" placeholder="单号、名称或物料" />
        </label>
      </template>

      <template #cell-document="{ row: item }">
        <div>
          <strong>
            #{{ item.id }} · 原领料 #{{ item.material_issue_id }} · 工单 #{{ item.work_order_id }} ·
            {{ item.warehouse_name }}
          </strong>
          <p class="muted">
            {{ localTime(item.created_at) }} · 创建人 {{ item.created_by_name }} · {{ item.reason }}
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
            {{ line.material_name }} × {{ line.quantity }} {{ line.unit }}
          </span>
        </div>
      </template>
      <template #cell-actions="{ row: item }">
        <div class="form-actions">
          <AppButton
            v-if="item.status === 'draft' && can('material_return.post')"
            type="button"
            :disabled="busy"
            @click="postMaterialReturn(item.id)"
            variant="primary"
            size="small"
          >
            确认退料
          </AppButton>
          <AppButton
            v-if="item.status === 'draft' && can('material_return.cancel')"
            type="button"
            :disabled="busy"
            @click="cancelMaterialReturn(item.id)"
            variant="secondary"
            size="small"
          >
            取消
          </AppButton>
        </div>
      </template>
      <template #empty>
        <strong>{{ recordQuery ? '没有匹配的记录' : '暂无生产退料记录' }}</strong>
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
