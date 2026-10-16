<script setup lang="ts">
import { ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import AppModal from '../../../components/app/AppModal.vue'
import AppInput from '../../../components/app/AppInput.vue'
import WorkspaceDocumentDialog from '../../../components/workspace/WorkspaceDocumentDialog.vue'
import WorkspaceMaterialSelect from '../../../components/workspace/WorkspaceMaterialSelect.vue'
import MaterialEditor from './MaterialEditor.vue'
import ProductProfileFields from './ProductProfileFields.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import type { ProductProfile } from '../../../../../shared/product-api'
withDefaults(defineProps<{entityLabel?: string}>(), {entityLabel:'产品'})
const emit = defineEmits<{saved:[product:ProductProfile]}>()
const store = usePiniaAppStore()
const {productForm, productMaterialForm, productEditorOpen, productModels, busy, connectionLost,
  materialCategories, materials, materialUnits, suppliers} = storeToRefs(store)
const materialInfoCompact = ref(true)
// 只重置资料展示状态，更换物料或重开弹窗时不携带上一物料的大块资料卡，也不修改产品草稿。
watch([productEditorOpen, () => productForm.value.material_id, () => productForm.value.mode], () => {
  materialInfoCompact.value = true
})
async function save(): Promise<void> {
  // 联合编辑只有一份修改原因，物料与产品审计同时保存。
  if (productForm.value.mode === 'edit') productForm.value.reason = productMaterialForm.value.reason
  const product = await store.saveProduct()
  if (product) emit('saved', product)
}
</script>
<template>
  <WorkspaceDocumentDialog v-if="store.can('catalog.manage') && productForm.mode === 'existing'"
    v-model:show="productEditorOpen" title="纳入已有物料" :data="[]" :columns="[]" :show-lines="false"
    :busy="busy" :disabled="connectionLost" :submit-disabled="!productForm.material_id"
    hint="沿用现有编码、库存和历史单据，只增加产品归组资料。" @submit="save" @invalidated="productEditorOpen = false">
    <template #basicInfo>
      <label>已有物料<WorkspaceMaterialSelect v-model="productForm.material_id" v-model:compact="materialInfoCompact" :materials="materials" :categories="materialCategories" :disabled="busy || connectionLost" required /></label>
      <ProductProfileFields :form="productForm" :models="productModels" :disabled="busy || connectionLost" />
      <label>说明<AppInput v-model.trim="productForm.reason" maxlength="500" :disabled="busy || connectionLost" /></label>
    </template>
  </WorkspaceDocumentDialog>
  <AppModal v-else-if="store.can('catalog.manage')" :show="productEditorOpen"
    class="product-editor-dialog"
    :title="`${productForm.mode === 'edit' ? '编辑' : '新建'}${entityLabel}`" :busy="busy" preset="card"
    :style="{width: 'min(1120px, calc(100vw - 32px))', height: 'min(860px, calc(100vh - 48px))'}"
    :mask-closable="!busy" @update:show="productEditorOpen = $event" @invalidated="productEditorOpen = false">
    <!-- 参数与供应商、分类目录复用物料编辑器；保存由产品接口一次提交。 -->
    <MaterialEditor :entity-label="entityLabel" compact :title="`${entityLabel}资料`"
      :form="productMaterialForm" :categories="materialCategories" :units="materialUnits" :suppliers="suppliers"
      :editing="productForm.mode === 'edit'" :busy="busy" :disconnected="connectionLost"
      @save="save" @cancel="productEditorOpen = false">
      <template #profileFields><ProductProfileFields :form="productForm" :models="productModels" :disabled="busy || connectionLost" /></template>
    </MaterialEditor>
  </AppModal>
</template>
<style>
/* 卡片标题与底部动作固定，仅字段区滚动；样式限定产品弹窗，不改变普通物料编辑器。 */
.n-modal.n-card.product-editor-dialog { display:flex; flex-direction:column; overflow:hidden; }
.n-modal.n-card.product-editor-dialog>.n-card-content { display:flex; min-height:0; padding:0; overflow:hidden; }
.product-editor-dialog .material-editor { display:flex; flex-direction:column; flex:1; min-height:0; gap:0; }
.product-editor-dialog .material-editor-body { overflow-y:auto; overscroll-behavior:contain; padding:20px 24px; }
.product-editor-dialog .material-section { padding:16px; }
.product-editor-dialog .material-editor>.form-actions { flex-shrink:0; justify-content:flex-end; gap:10px; margin:0 24px; padding:16px 0; border-top:1px solid var(--workspace-field-border); }
@media(max-width:600px) { .product-editor-dialog .material-editor-body { padding:16px; } .product-editor-dialog .material-editor>.form-actions { margin:0 16px; } }
</style>
