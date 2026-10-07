<script setup lang="ts">
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
// 下拉选择统一使用工作台组件，业务值与切换回调保持原有类型。
// 物料资料统一展示，候选范围和联动规则仍由当前业务决定。
import WorkspaceMaterialSelect from '../../../components/workspace/WorkspaceMaterialSelect.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { recordColumns, matchesRecordQuery } from '../../../utils/workspace-records'
import { computed, ref } from 'vue'
// 共用单据弹窗的基础信息、物料表格和固定操作区。
import WorkspaceDocumentDialog from '../../../components/workspace/WorkspaceDocumentDialog.vue'
import { bomDraftIssue, bomComponentOptions } from './bom-form'
import { useAppStore } from '../../../store/app-store'
import { submitCreateDialog } from '../../../utils/create-dialog'

// 页面直接使用共享状态与操作，切换标签时不会丢失正在填写的草稿。
const {
  error,
  notice,
  connectionLost,
  materialCategories,
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
  // 断线、撤权或草稿无效时不触发请求，失败后仍留在原弹窗。
  if (connectionLost.value || !can('bom.create') || bomIssue.value) return
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
// 行包装保留原 Pinia 对象；删行后重算索引，后续编辑不会错改其他组件。
const componentRows = computed(() => bomForm.value.lines.map((line, index) => ({ line, index })))
const componentColumns = [
  { key: 'material', title: '组件物料 / 资料', width: '470' },
  { key: 'unit', title: '单位', width: '80' },
  { key: 'quantity', title: '基准用量', width: '150' },
  { key: 'actions', title: '操作', width: '90' }
]
const bomIssue = computed(() => bomDraftIssue(bomForm.value, materials.value))
function addComponent(): void {
  // 与接口的一百行上限一致，并在事件入口重复核对交互状态。
  if (busy.value || connectionLost.value || !can('bom.create') || bomForm.value.lines.length >= 100) return
  bomForm.value.lines.push({ component_material_id: 0, quantity: '1' })
}
function removeComponent(index: number): void {
  if (busy.value || connectionLost.value || !can('bom.create') || bomForm.value.lines.length <= 1) return
  bomForm.value.lines.splice(index, 1)
}
</script>

<template>
  <section class="stack">
    <!-- 业务草稿仍由 Pinia 保存，公共弹窗只负责布局和交互边界。 -->
    <WorkspaceDocumentDialog
      v-if="can('bom.create')" v-model:show="createOpen" title="新建 BOM 版本"
      :data="componentRows" :columns="componentColumns" :busy="busy" :disabled="connectionLost"
      :submit-disabled="Boolean(bomIssue)" :add-disabled="bomForm.lines.length >= 100"
      :hint="bomIssue || '旧版本会保留供追溯；同一成品一次只能启用一个版本。'"
      @add-material="addComponent" @submit="submitCreate"
    >
      <template #basicInfo>
        <label class="bom-basic-field">成品物料<WorkspaceMaterialSelect v-model="bomForm.product_material_id"
          :materials="materials" :categories="materialCategories" :disabled="busy || connectionLost"
          placeholder="选择成品" required /></label>
        <label class="bom-basic-field">基准产出数量<AppInput v-model.trim="bomForm.base_quantity" :disabled="busy || connectionLost"
          type="number" min="0.001" max="1000000" step="0.001" required /></label>
        <label class="bom-basic-field">版本说明（可选）<AppInput v-model.trim="bomForm.note" :disabled="busy || connectionLost" maxlength="200" /></label>
      </template>
      <template #cell-material="{ row: { line, index } }">
        <WorkspaceMaterialSelect v-model="line.component_material_id" :materials="materials"
          :categories="materialCategories" :options="bomComponentOptions(bomForm, materials, index)"
          :disabled="busy || connectionLost" aria-label="组件物料" placeholder="选择组件" required />
      </template>
      <template #cell-unit="{ row: { line } }">
        {{ materials.find(item => item.id === line.component_material_id)?.unit ?? '—' }}
      </template>
      <template #cell-quantity="{ row: { line } }">
        <AppInput v-model.trim="line.quantity" :disabled="busy || connectionLost" aria-label="基准用量"
          type="number" min="0.001" max="1000000" step="0.001" required />
      </template>
      <template #cell-actions="{ row: { index } }">
        <AppButton type="button" variant="text" :disabled="busy || connectionLost || bomForm.lines.length === 1"
          @click="removeComponent(index)">移除</AppButton>
      </template>
    </WorkspaceDocumentDialog>
    <!-- 主标题由工作台提供，列表复用仓库管理的筛选区、状态和单元格布局。 -->
    <WorkspaceTable
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
          :disabled="busy || connectionLost"
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

<style scoped>
/* 成品资料卡展开时，同行数量输入框保持正常高度，避免随资料卡一起拉伸。 */
.bom-basic-field { align-content: start; }
</style>
