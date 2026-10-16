<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { usePiniaAppStore } from '../../../store/app-store'
import WorkspaceDocumentDialog from '../../../components/workspace/WorkspaceDocumentDialog.vue'
import AppInput from '../../../components/app/AppInput.vue'
import AppButton from '../../../components/app/AppButton.vue'
import type { ProductProfile, ProductLifecycleAction } from '../../../../../shared/product-api'
const props = defineProps<{product:ProductProfile|null; action:ProductLifecycleAction}>()
const emit = defineEmits<{close:[]}>()
const store = usePiniaAppStore()
const {busy,connectionLost} = storeToRefs(store)
const reason = ref('')
const title = computed(() => ({delete:'删除子机型',disable:'停用子机型',enable:'启用子机型'}[props.action]))
// 切换操作目标才清原因；接口校验失败时保留输入，让用户先处理关联或刷新冲突。
watch(() => [props.product?.id,props.action], () => {reason.value=''})
async function submit(): Promise<void> {
  if (!props.product || busy.value || connectionLost.value || !reason.value.trim() || !store.can('catalog.manage')) return
  const target=props.product, action=props.action
  if (await store.applyProductLifecycle(target,action,reason.value.trim()) && props.product===target && props.action===action) emit('close')
}
</script>
<template>
  <WorkspaceDocumentDialog origin-key="product-lifecycle" :show="!!product && store.can('catalog.manage')" :title="title"
    :data="[]" :columns="[]" :show-lines="false" :busy="busy" :disabled="connectionLost"
    @submit="submit" @update:show="!$event && emit('close')" @invalidated="emit('close')">
    <template #basicInfo><template v-if="product">
      <div class="document-detail-field"><span>子机型</span><strong>{{ product.material.name }}</strong></div>
      <div class="document-detail-field"><span>物料编码</span><strong>{{ product.material.sku }}</strong></div>
      <label class="product-lifecycle-reason">操作原因<AppInput v-model.trim="reason" required maxlength="500" :disabled="busy || connectionLost" placeholder="请填写本次操作原因" /></label>
    </template></template>
    <template #afterLines>
      <p v-if="action==='delete'" class="product-lifecycle-hint">删除后从产品目录隐藏，保留原物料、库存、BOM 及历史工单。若被启用的上层 BOM 固定引用，须先修订或停用上层 BOM。</p>
      <p v-else-if="action==='disable'" class="product-lifecycle-hint">停用后禁止此子机型的新生产。子机型和 BOM 版本保留，已有工单继续履行，上层仍可领用已入库的半成品；停用的子机型仍计入系列。</p>
      <p v-else class="product-lifecycle-hint">恢复此子机型的生产用途，原 BOM 版本状态保持不变；新生产仍须选择已启用的 BOM 版本。</p>
    </template>
    <template #footer><div class="document-actions product-lifecycle-actions"><AppButton :disabled="busy" @click="emit('close')">取消</AppButton>
      <AppButton type="submit" :tone="action==='delete' ? 'error' : action==='disable' ? 'warning' : 'success'" :loading="busy" :disabled="busy || connectionLost || !reason.trim()">确认{{ title }}</AppButton></div>
    </template>
  </WorkspaceDocumentDialog>
</template>
<style scoped>
/* 危险操作与原因放在统一确认窗，避免树节点误触直接更改生产资格。 */
.product-lifecycle-reason { grid-column:1/-1; }
.product-lifecycle-hint { margin:16px 0 0; color:var(--workspace-field-muted); line-height:1.8; }
.product-lifecycle-actions { margin-left:auto; }
</style>
