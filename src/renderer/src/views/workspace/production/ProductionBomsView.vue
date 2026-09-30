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
  version,
  busy,
  materials,
  boms,
  bomForm,
  can,
  localTime,
  createBom,
  activateBom,
  retireBom,
  cancelBom
} = useAppStore()

// 保存失败时保留弹窗和草稿，方便直接修正后重试。
const createOpen = ref(false)
async function submitCreate(): Promise<void> {
  await submitCreateDialog(createBom, { busy, error, notice }, createOpen)
}
// 只筛选当前列表快照，原有单据状态与跨页面草稿保持不变。
const recordQuery = ref('')
const filteredRecords = computed(() =>
  boms.value.filter((item) =>
    matchesRecordQuery(recordQuery.value, [
      item.id,
      item.product_name,
      item.product_sku,
      item.created_by_name,
      ...item.lines.map((line) => line.material_name)
    ])
  )
)
</script>

<template>
  <section class="stack">
    <NModal
      v-if="can('bom.create')"
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
          <p class="eyebrow">BILL OF MATERIALS</p>
          <h2>新建 BOM 版本</h2>
        </div>
        <span class="pill">草稿</span>
      </div>
      <p class="muted">
        BOM 记录生产指定数量成品所需的组件。旧版本会保留供追溯；同一成品一次只能启用一个版本。
      </p>
      <form @submit.prevent="submitCreate">
        <div class="form-grid">
          <label
            >成品物料<WorkspaceSelect remote-dataset="materials"
              v-model="bomForm.product_material_id"
              required
              :options="[
                { label: '选择成品'.trim(), value: 0, disabled: true },
                ...materials.map((item) => ({
                  label: (item.sku + ' · ' + item.name).trim(),
                  value: item.id
                }))
              ]" /></label
          ><label
            >基准产出数量<AppInput
              v-model.trim="bomForm.base_quantity"
              type="number"
              min="0.001"
              max="1000000"
              step="0.001"
              required /></label
          ><label>版本说明（可选）<AppInput v-model.trim="bomForm.note" maxlength="200" /></label>
        </div>
        <h3>组件用量</h3>
        <div v-for="(line, index) in bomForm.lines" :key="index" class="line-row">
          <label
            >组件物料<WorkspaceSelect remote-dataset="materials"
              v-model="line.component_material_id"
              required
              :options="[
                { label: '选择组件'.trim(), value: 0, disabled: true },
                ...materials
                  .filter((entry) => entry.id !== bomForm.product_material_id)
                  .map((item) => ({ label: (item.sku + ' · ' + item.name).trim(), value: item.id }))
              ]" /></label
          ><label
            >基准用量<AppInput
              v-model.trim="line.quantity"
              type="number"
              min="0.001"
              max="1000000"
              step="0.001"
              required /></label
          ><AppButton
            type="button"
            :disabled="bomForm.lines.length === 1"
            @click="bomForm.lines.splice(index, 1)"
            variant="text"
          >
            移除
          </AppButton>
        </div>
        <div class="form-actions">
          <AppButton
            type="button"
            @click="bomForm.lines.push({ component_material_id: 0, quantity: '1' })"
            variant="secondary"
          >
            添加组件</AppButton
          ><AppButton type="submit" :disabled="busy || materials.length < 2" variant="primary">
            保存草稿
          </AppButton>
        </div>
      </form>
    </NModal>
    <!-- 主标题由工作台提供，列表复用仓库管理的筛选区、状态和单元格布局。 -->
    <WorkspaceTable dataset="boms" :query="recordQuery"
      :show-title="false"
      title="生产 BOM"
      :data="filteredRecords"
      :columns="recordColumns"
      :min-table-width="1100"
    >
      <template #actions>
        <AppButton
          v-if="can('bom.create')"
          type="button"
          :disabled="busy"
          @click="createOpen = true"
          variant="primary"
        >
          新建 BOM 版本
        </AppButton>
      </template>
      <template #filters>
        <label>
          搜索生产 BOM
          <AppInput v-model="recordQuery" placeholder="单号、名称或物料" />
        </label>
      </template>

      <template #cell-document="{ row: item }">
        <div>
          <strong>
            #{{ item.id }} · {{ item.product_name }}（{{ item.product_sku }}）· V{{ item.version }}
          </strong>
          <p class="muted">
            {{ localTime(item.created_at) }} · 创建人 {{ item.created_by_name }} · 基准产出
            {{ item.base_quantity }}
            {{ item.product_unit }}
            <span v-if="item.note">· {{ item.note }}</span>
          </p>
        </div>
      </template>
      <template #cell-status="{ row: item }">
        <span class="pill" :class="item.status">
          {{
            {
              draft: '草稿',
              active: '已启用',
              retired: '已停用',
              cancelled: '已取消'
            }[item.status]
          }}
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
            v-if="item.status === 'draft' && can('bom.activate')"
            type="button"
            :disabled="
              busy ||
              boms.some(
                (other) =>
                  other.product_material_id === item.product_material_id &&
                  other.status === 'active'
              )
            "
            @click="activateBom(item.id)"
            variant="primary"
            size="small"
          >
            启用
          </AppButton>
          <AppButton
            v-if="item.status === 'active' && can('bom.retire')"
            type="button"
            :disabled="busy"
            @click="retireBom(item.id)"
            variant="secondary"
            size="small"
          >
            停用
          </AppButton>
          <AppButton
            v-if="item.status === 'draft' && can('bom.cancel')"
            type="button"
            :disabled="busy"
            @click="cancelBom(item.id)"
            variant="secondary"
            size="small"
          >
            取消草稿
          </AppButton>
        </div>
      </template>
      <template #empty>
        <strong>{{ recordQuery ? '没有匹配的记录' : '暂无生产 BOM记录' }}</strong>
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
