<script setup lang="ts">
// 产品页与 BOM 页共用一个编辑器，明细直接引用同一 Pinia 草稿。
import { computed } from 'vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import type { BomLine } from '../../../../../shared/erp-api'
import AppInput from '../../../components/app/AppInput.vue'
import AppButton from '../../../components/app/AppButton.vue'
import WorkspaceMaterialSelect from '../../../components/workspace/WorkspaceMaterialSelect.vue'
import WorkspaceDocumentDialog from '../../../components/workspace/WorkspaceDocumentDialog.vue'
import ProductEditor from './ProductEditor.vue'
import { useDocumentMaterialDetails } from '../../../composables/use-document-material-details'
import { bomDraftIssue, bomComponentOptions } from './bom-form'
import { useAppStore } from '../../../store/app-store'
import { submitCreateDialog } from '../../../utils/create-dialog'
const props = defineProps<{show: boolean; targetMaterialId?:number}>()
const emit = defineEmits<{'update:show': [value: boolean]; saved: []}>()
const createOpen = computed({get: () => props.show, set: value => emit('update:show', value)})
const { error, notice, connectionLost, materialCategories, busy, materials, boms, bomForm, can, createBom,
  startProduct, productEditorOpen } = useAppStore()
async function submitCreate(): Promise<void> {
  if (busy.value || connectionLost.value || !can('bom.create') || bomIssue.value) return
  await submitCreateDialog(createBom, {busy, error, notice}, createOpen)
  if (!createOpen.value && !error.value && notice.value) emit('saved')
}
const componentRows = computed(() => bomForm.value.lines.map((line, index) => ({line, index})))
const componentColumns = [
  {key: 'material', title: '组件物料 / 资料', width: '470'}, {key: 'unit', title: '单位', width: '80'},
  {key: 'quantity', title: '基准用量', width: '150'},
  {key: 'componentBom', title: '下层生产配方', width: '240'}, {key: 'actions', title: '操作', width: '90'},
]
// 产品工作区固定产出身份，只适配用料；独立 BOM 页面省略目标仍可自由选择。
const bomIssue = computed(() => props.targetMaterialId && bomForm.value.product_material_id !== props.targetMaterialId
  ? '目标子机型与草稿不一致，请收起后重新打开。' : bomDraftIssue(bomForm.value, materials.value))
function addComponent(): void {
  if (busy.value || connectionLost.value || !can('bom.create') || bomForm.value.lines.length >= 100) return
  bomForm.value.lines.push({component_material_id: 0, quantity: '1'})
}
function removeComponent(index: number): void {
  if (busy.value || connectionLost.value || !can('bom.create') || bomForm.value.lines.length <= 1) return
  bomForm.value.lines.splice(index, 1)
}
// 更换物料必须清理不属于新物料的版本，避免把旧板配方带到另一个组件。
function componentChanged(line: {component_material_id:number; quantity:string; component_bom_id?:number|null}): void {
  if (line.component_bom_id && !boms.value.some(bom => bom.id === line.component_bom_id && bom.product_material_id === line.component_material_id)) line.component_bom_id = null
  showLine(line)
}
function componentBomOptions(line: Pick<BomLine, 'component_material_id' | 'component_bom_id'>) {
  return [{value:null as number|null,label:'按物料领用，不限制生产配方'}, ...boms.value
    .filter(bom => bom.product_material_id === line.component_material_id && (bom.status === 'active' || bom.id === line.component_bom_id))
    .map(bom => ({value:bom.id,label:`固定 V${bom.version}${bom.status === 'active' ? ' · 已启用' : ' · 已停用，需修订'}`}))]
}
const { activeLine, showLine, setCompact } = useDocumentMaterialDetails(() => bomForm.value.lines)
</script>
<template>
    <WorkspaceDocumentDialog origin-key="ProductionBomsView:form" @invalidated="createOpen = false"
      v-if="can('bom.create')"  :show="createOpen && !productEditorOpen" @update:show="createOpen = $event" title="新建 BOM 版本"
      :data="componentRows" :columns="componentColumns" :busy="busy" :disabled="connectionLost"
      :submit-disabled="Boolean(bomIssue)" :add-disabled="bomForm.lines.length >= 100"
      :hint="bomIssue || '旧版本会保留供追溯；同一产品或半成品只能启用一个版本。固定下层版本停用后，须修订本配方。'"
      @add-material="addComponent" @submit="submitCreate"
    >
      <template #basicInfo>
        <p v-if="bomForm.source_bom_id" class="document-basic-extra muted">派生来源 BOM #{{ bomForm.source_bom_id }}；保存为完整的新草稿，来源更新不会自动同步。</p>
        <label class="bom-basic-field">产出产品 / 半成品<WorkspaceMaterialSelect v-model="bomForm.product_material_id"
          :materials="materials" :categories="materialCategories" :disabled="busy || connectionLost || Boolean(targetMaterialId)"
          placeholder="选择产出物料" required />
        <AppButton v-if="!targetMaterialId && can('catalog.manage')" type="button" :disabled="busy || connectionLost"
          @click="startProduct('new', 0, true)">快捷新建产品</AppButton>
        </label>
        <label class="bom-basic-field">基准产出数量<AppInput v-model.trim="bomForm.base_quantity" :disabled="busy || connectionLost"
          type="number" min="0.001" max="1000000" step="0.001" required /></label>
        <label class="bom-basic-field">版本说明（可选）<AppInput v-model.trim="bomForm.note" :disabled="busy || connectionLost" maxlength="200" /></label>
      </template>
      <template #cell-material="{ row: { line, index } }">
        <!-- 标题由表头统一展示，控件保留逐行无障碍名称。 -->
        <WorkspaceMaterialSelect v-model="line.component_material_id" :materials="materials"
          :aria-label="`第 ${index + 1} 行物料`"
          :compact="activeLine !== line"
          @update:compact="(value) => setCompact(line, value)"
          @change="componentChanged(line)"
          :categories="materialCategories" :options="bomComponentOptions(bomForm, materials, index)"
          :disabled="busy || connectionLost" placeholder="选择组件" required />
      </template>
      <template #cell-unit="{ row: { line } }">
        {{ materials.find(item => item.id === line.component_material_id)?.unit ?? '—' }}
      </template>
      <template #cell-quantity="{ row: { line } }">
        <AppInput v-model.trim="line.quantity" :disabled="busy || connectionLost" aria-label="基准用量"
          type="number" min="0.001" max="1000000" step="0.001" required />
      </template>
      <template #cell-componentBom="{ row: { line, index } }">
      <WorkspaceSelect :model-value="line.component_bom_id ?? null"
        @update:model-value="line.component_bom_id = typeof $event === 'number' ? $event : null"
        :aria-label="`第 ${index + 1} 行下层生产配方`" :options="componentBomOptions(line)"
        :disabled="busy || connectionLost || !line.component_material_id" />
    </template>
    <template #cell-actions="{ row: { index } }">
        <!-- 移除使用公共按钮的完整点击区域，原有禁用与删行规则保持。 -->
        <AppButton size="small" type="button" variant="secondary" :disabled="busy || connectionLost || bomForm.lines.length === 1"
          @click="removeComponent(index)">移除</AppButton>
      </template>
    </WorkspaceDocumentDialog>
    <ProductEditor v-if="show && productEditorOpen" />
</template>
<style scoped>
/* 资料卡展开时数量输入仍按内容高度显示。 */
.bom-basic-field { align-content: start; }
</style>
