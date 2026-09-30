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
  stocktakes,
  stocktakeForm,
  stocktakeReversalReasons,
  can,
  localTime,
  createStocktake,
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
async function submitCreate(): Promise<void> {
  await submitCreateDialog(createStocktake, { busy, error, notice }, createOpen)
}
</script>

<template>
  <section class="stack">
    <NModal
      v-if="can('stocktake.create')"
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
          <p class="eyebrow">STOCKTAKE</p>
          <h2>新建盘点单</h2>
        </div>
        <span class="pill">草稿</span>
      </div>
      <form @submit.prevent="submitCreate">
        <div class="form-grid">
          <label
            >盘点仓库<WorkspaceSelect remote-dataset="warehouses"
              v-model="stocktakeForm.warehouse_id"
              required
              :options="[
                ...warehouses.map((item) => ({ label: item.name.trim(), value: item.id }))
              ]" /></label
          ><label
            >盘点批次或备注（可选）<AppInput v-model.trim="stocktakeForm.reference" maxlength="100"
          /></label>
        </div>
        <p class="muted">
          只填写实际清点数量。保存时记录账面数量；若确认前库存发生变化，系统会要求重新盘点。
        </p>
        <div v-for="(line, index) in stocktakeForm.lines" :key="index" class="line-row">
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
            >实盘数量<AppInput
              v-model.trim="line.counted_quantity"
              type="number"
              min="0"
              max="1000000"
              step="0.001"
              required /></label
          ><AppButton
            type="button"
            :disabled="stocktakeForm.lines.length === 1"
            @click="stocktakeForm.lines.splice(index, 1)"
            variant="text"
          >
            移除
          </AppButton>
        </div>
        <div class="form-actions">
          <AppButton
            type="button"
            @click="
              stocktakeForm.lines.push({
                material_id: 0,
                counted_quantity: '0'
              })
            "
            variant="secondary"
          >
            添加明细</AppButton
          ><AppButton
            type="submit"
            :disabled="busy || connectionLost || !materials.length"
            variant="primary"
          >
            保存草稿
          </AppButton>
        </div>
      </form>
    </NModal>
    <!-- 单据列表与台账共用表格，原有权限检查和冲销明细完整保留。 -->
    <WorkspaceTable dataset="stocktakes" :query="query"
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
            @click="postStocktake(item.id)"
            variant="primary"
            size="small"
          >
            确认差异</AppButton
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
  </section>
</template>
