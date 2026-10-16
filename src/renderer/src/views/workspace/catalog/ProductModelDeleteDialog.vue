<script setup lang="ts">
import { ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { usePiniaAppStore } from '../../../store/app-store'
import WorkspaceDocumentDialog from '../../../components/workspace/WorkspaceDocumentDialog.vue'
import AppInput from '../../../components/app/AppInput.vue'
import AppButton from '../../../components/app/AppButton.vue'
import type { ProductModel } from '../../../../../shared/product-api'
const props = defineProps<{model:ProductModel|null}>()
const emit = defineEmits<{close:[]}>()
const store = usePiniaAppStore()
const {busy,connectionLost} = storeToRefs(store)
const reason = ref('')
// 失败保留当前删除原因；更换目标或关闭后才清空，不能误删另一系列。
watch(() => props.model?.id, () => {reason.value=''})
async function remove(): Promise<void> {
  const model = props.model
  if (!model || busy.value || connectionLost.value || !store.can('catalog.manage') || (model.child_count ?? 0)>0 || !reason.value.trim()) return
  if (await store.deleteProductModel(model,reason.value.trim()) && props.model===model) emit('close')
}
</script>
<template>
  <WorkspaceDocumentDialog origin-key="product-model-delete" :show="!!model && store.can('catalog.manage')" title="删除产品系列"
    :data="[]" :columns="[]" :show-lines="false" :busy="busy" :disabled="connectionLost"
    @submit="remove" @update:show="!$event && emit('close')" @invalidated="emit('close')">
    <template #basicInfo><template v-if="model">
      <div class="document-detail-field"><span>产品系列</span><strong>{{ model.name }} · {{ model.code }}</strong></div>
      <div class="document-detail-field"><span>子机型数量</span><strong>{{ model.child_count ?? '由服务端再次校验' }}</strong></div>
      <label class="product-delete-reason">删除原因<AppInput v-model.trim="reason" required maxlength="500" :disabled="busy || connectionLost" placeholder="请说明为何删除此空系列" /></label>
    </template></template>
    <template #afterLines><p v-if="model && (model.child_count ?? 0)>0" class="product-delete-blocker" role="alert">此系列仍有 {{ model.child_count }} 个子机型，请先删除子机型，再删除系列。</p></template>
    <template #footer><p class="muted">仅隐藏空系列，保留原编码和删除记录；服务端会再次校验完整关联。</p>
      <div class="document-actions"><AppButton :disabled="busy" @click="emit('close')">取消</AppButton>
        <AppButton type="submit" tone="error" :loading="busy" :disabled="busy || connectionLost || !reason.trim() || (model?.child_count ?? 0)>0">确认删除系列</AppButton></div>
    </template>
  </WorkspaceDocumentDialog>
</template>
<style scoped>
/* 删除原因独占一行，关联阻断信息始终显示，不依赖禁用按钮的悬浮提示。 */
.product-delete-reason { grid-column:1/-1; }
.product-delete-blocker { margin:16px 0 0; color:var(--workspace-field-text); line-height:1.7; }
</style>
