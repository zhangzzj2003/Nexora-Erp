<script setup lang="ts">
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
// 下拉选择统一使用工作台组件，业务值与切换回调保持原有类型。
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import { computed, ref } from 'vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { NModal } from 'naive-ui'
import { useAppStore } from '../../../store/app-store'
import { submitCreateDialog } from '../../../utils/create-dialog'

// 页面直接使用共享状态与操作，切换标签时不会丢失正在填写的草稿。
const {
  error,
  notice,
  busy,
  connectionLost,
  materials,
  warehouses,
  transfers,
  transferForm,
  transferReversalReasons,
  can,
  localTime,
  createTransfer,
  postTransfer,
  reverseTransfer
} = useAppStore()

// 搜索只过滤当前单据快照，不改动草稿、确认及冲销状态。
const query = ref('')
const filtered = computed(() => transfers.value.filter((item) =>
  [item.id, item.reference, item.from_warehouse_name, item.to_warehouse_name, ...item.lines.map((line) => line.material_name)]
    .join(' ').toLowerCase().includes(query.value.trim().toLowerCase())))
const columns = [
  { key: 'document', title: '单据' }, { key: 'warehouse', title: '调拨仓库' },
  { key: 'lines', title: '物料明细' }, { key: 'actions', title: '操作' }
]

// 保存失败时保留弹窗和草稿，方便直接修正后重试。
const createOpen = ref(false)
async function submitCreate(): Promise<void> {
  await submitCreateDialog(createTransfer, { busy, error, notice }, createOpen)
}
</script>

<template>
  <section class="stack">
    <NModal
      v-if="can('transfer.create')"
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
          <p class="eyebrow">WAREHOUSE TRANSFER</p>
          <h2>新建调拨单</h2>
        </div>
        <span class="pill">草稿</span>
      </div>
      <form @submit.prevent="submitCreate">
        <div class="form-grid">
          <label
            >来源仓库<WorkspaceSelect remote-dataset="warehouses"
              v-model="transferForm.from_warehouse_id"
              required
              :options="[
                ...warehouses.map((item) => ({ label: item.name.trim(), value: item.id }))
              ]" /></label
          ><label
            >目标仓库<WorkspaceSelect remote-dataset="warehouses"
              v-model="transferForm.to_warehouse_id"
              required
              :options="[
                { label: '选择目标仓库'.trim(), value: 0, disabled: true },
                ...warehouses
                  .filter((entry) => entry.id !== transferForm.from_warehouse_id)
                  .map((item) => ({ label: item.name.trim(), value: item.id }))
              ]" /></label
          ><label
            >参考单号（可选）<AppInput v-model.trim="transferForm.reference" maxlength="100"
          /></label>
        </div>
        <h3>调拨明细</h3>
        <div v-for="(line, index) in transferForm.lines" :key="index" class="line-row">
          <label
            >物料<WorkspaceSelect remote-dataset="materials"
              v-model="line.material_id"
              required
              :options="[
                { label: '选择物料'.trim(), value: 0, disabled: true },
                ...materials.map((item) => ({
                  label: (item.sku + ' · ' + item.name).trim(),
                  value: item.id
                }))
              ]" /></label
          ><label
            >数量<AppInput
              v-model.trim="line.quantity"
              type="number"
              min="0.001"
              max="1000000"
              step="0.001"
              required /></label
          ><AppButton
            type="button"
            :disabled="transferForm.lines.length === 1"
            @click="transferForm.lines.splice(index, 1)"
            variant="text"
          >
            移除
          </AppButton>
        </div>
        <div class="form-actions">
          <AppButton
            type="button"
            @click="transferForm.lines.push({ material_id: 0, quantity: '1' })"
            variant="secondary"
          >
            添加明细</AppButton
          ><AppButton
            type="submit"
            :disabled="busy || connectionLost || warehouses.length < 2 || !materials.length"
            variant="primary"
          >
            保存草稿
          </AppButton>
        </div>
      </form>
    </NModal>
    <!-- 单据列表与台账共用表格，原有权限检查和冲销明细完整保留。 -->
    <WorkspaceTable dataset="transfers" :query="query"
      :show-title="false"
      title="仓库调拨"
      :columns="columns"
      :data="filtered"
      :min-table-width="1050"
    >
      <template #actions>
        <AppButton
          v-if="can('transfer.create')"
          type="button"
          :disabled="busy || connectionLost"
          @click="createOpen = true"
          variant="primary"
          >新建调拨单</AppButton
        >
      </template>
      <template #filters
        ><label>搜索调拨单<AppInput v-model="query" placeholder="单号、仓库或物料" /></label
      ></template>
      <template #cell-document="{ row: item }">
        <strong>#{{ item.id }}</strong>
        <small>{{
          item.reversal_id ? '已冲销' : item.status === 'posted' ? '已调拨' : '待确认'
        }}</small>
        <small>{{ localTime(item.created_at) }} · {{ item.created_by_name }}</small>
        <small v-if="item.reference">{{ item.reference }}</small>
      </template>
      <template #cell-warehouse="{ row: item }"
        >{{ item.from_warehouse_name }} → {{ item.to_warehouse_name }}</template
      >
      <template #cell-lines="{ row: item }">
        <div v-for="line in item.lines" :key="line.id">
          {{ line.material_name }} × {{ line.quantity }} {{ line.unit }}
        </div>
        <small v-if="item.reversal_id"
          >冲销 #{{ item.reversal_id }} · {{ item.reversal_reason }} · {{ item.reversed_by_name }} ·
          {{ localTime(item.reversed_at!) }}</small
        >
      </template>
      <template #cell-actions="{ row: item }">
        <div class="form-actions">
          <AppButton
            v-if="item.status === 'draft' && can('transfer.post')"
            type="button"
            :disabled="busy || connectionLost"
            @click="postTransfer(item.id)"
            variant="primary"
            size="small"
          >
            确认调拨
          </AppButton>
        </div>
        <form
          v-if="item.status === 'posted' && !item.reversal_id && can('transfer.reverse')"
          class="inline-form"
          @submit.prevent="reverseTransfer(item.id)"
        >
          <label
            >冲销原因<AppInput
              v-model.trim="transferReversalReasons[item.id]"
              required
              maxlength="200"
              placeholder="说明原调拨为何需要冲销" /></label
          ><AppButton
            type="submit"
            :disabled="busy || connectionLost"
            variant="secondary"
            size="small"
          >
            冲销已确认调拨
          </AppButton>
        </form>
      </template>
      <template #empty>
        <strong>{{ query ? '没有匹配的单据' : '暂无调拨单' }}</strong>
        <span>{{
          query
            ? '可调整单号、仓库或物料关键词后重新搜索。'
            : '保存新建单据后，可在这里查看明细与处理状态。'
        }}</span>
      </template>
    </WorkspaceTable>
  </section>
</template>
