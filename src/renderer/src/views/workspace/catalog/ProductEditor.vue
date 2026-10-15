<script setup lang="ts">
import { storeToRefs } from 'pinia'
import AppModal from '../../../components/app/AppModal.vue'
import AppInput from '../../../components/app/AppInput.vue'
import WorkspaceDocumentDialog from '../../../components/workspace/WorkspaceDocumentDialog.vue'
import WorkspaceMaterialSelect from '../../../components/workspace/WorkspaceMaterialSelect.vue'
import MaterialEditor from './MaterialEditor.vue'
import ProductProfileFields from './ProductProfileFields.vue'
import { usePiniaAppStore } from '../../../store/app-store'
const store = usePiniaAppStore()
const {productForm, productMaterialForm, productEditorOpen, productModels, busy, connectionLost,
  materialCategories, materials, materialUnits, suppliers} = storeToRefs(store)
async function save(): Promise<void> {
  // 联合编辑只有一份修改原因，物料与产品审计同时保存。
  if (productForm.value.mode === 'edit') productForm.value.reason = productMaterialForm.value.reason
  await store.saveProduct()
}
</script>
<template>
  <WorkspaceDocumentDialog v-if="store.can('catalog.manage') && productForm.mode === 'existing'"
    v-model:show="productEditorOpen" title="纳入已有物料" :data="[]" :columns="[]" :show-lines="false"
    :busy="busy" :disabled="connectionLost" :submit-disabled="!productForm.material_id"
    hint="沿用现有编码、库存和历史单据，只增加产品归组资料。" @submit="save" @invalidated="productEditorOpen = false">
    <template #basicInfo>
      <label>已有物料<WorkspaceMaterialSelect v-model="productForm.material_id" :materials="materials" :categories="materialCategories" :disabled="busy || connectionLost" required /></label>
      <ProductProfileFields :form="productForm" :models="productModels" :disabled="busy || connectionLost" />
      <label>说明<AppInput v-model.trim="productForm.reason" maxlength="500" :disabled="busy || connectionLost" /></label>
    </template>
  </WorkspaceDocumentDialog>
  <AppModal v-else-if="store.can('catalog.manage')" :show="productEditorOpen"
    :title="productForm.mode === 'edit' ? '编辑产品' : '新增产品'" :busy="busy" preset="card"
    :style="{width: 'min(1280px, calc(100vw - 32px))', maxHeight: 'calc(100vh - 48px)', overflowY: 'auto'}"
    :mask-closable="!busy" @update:show="productEditorOpen = $event" @invalidated="productEditorOpen = false">
    <!-- 参数与供应商、分类目录复用物料编辑器；保存由产品接口一次提交。 -->
    <MaterialEditor entity-label="产品" :title="productForm.mode === 'edit' ? '编辑产品资料' : '建立产品档案'"
      :form="productMaterialForm" :categories="materialCategories" :units="materialUnits" :suppliers="suppliers"
      :editing="productForm.mode === 'edit'" :busy="busy" :disconnected="connectionLost"
      @save="save" @cancel="productEditorOpen = false">
      <template #beforeFields><fieldset :disabled="busy || connectionLost" class="product-fields"><legend>产品归组</legend>
        <div class="form-grid"><ProductProfileFields :form="productForm" :models="productModels" :disabled="busy || connectionLost" /></div>
      </fieldset></template>
    </MaterialEditor>
  </AppModal>
</template>
<style scoped>
/* 沿用物料编辑器的分组边界和主题，不建立第二套产品参数样式。 */
.product-fields { border: 1px solid var(--workspace-field-border); border-radius: 12px; padding: 16px; margin: 0 0 18px; }
</style>
