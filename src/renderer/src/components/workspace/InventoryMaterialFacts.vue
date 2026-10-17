<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import AppButton from '../app/AppButton.vue'
import { usePiniaAppStore } from '../../store/app-store'
import { materialChoiceFacts } from '../../utils/material-selection'
import WorkspaceMaterialParameters from './WorkspaceMaterialParameters.vue'
const props = defineProps<{ compact?: boolean }>()
const store = usePiniaAppStore()
const { connectionLost, materialCategories, ledgerMaterialDetail: material,
  ledgerMaterialLoading: loading, ledgerMaterialError: error } = storeToRefs(store)
const facts = computed(() => material.value ? [
  { key: 'sku', label: '物料编号', value: material.value.sku },
  { key: 'name', label: '物料名称', value: material.value.name },
  ...materialChoiceFacts(material.value, materialCategories.value).filter(item => ['category_name', 'unit'].includes(item.key))
] : [])
</script>
<template>
  <p v-if="loading" role="status">正在读取物料详情…</p>
  <div v-else-if="error" role="alert" class="material-error">
    <p>{{ error }}</p><AppButton :disabled="connectionLost" @click="store.loadLedgerMaterial()">重新读取物料</AppButton>
  </div>
  <template v-else-if="material">
    <!-- 身份与参数分开阅读，真实规格及扩展属性不再藏在首屏折叠白名单后面。 -->
    <dl class="material-facts"><div v-for="fact in facts" :key="fact.key"><dt>{{ fact.label }}</dt><dd>{{ fact.value }}</dd></div></dl>
    <WorkspaceMaterialParameters :material="material" :categories="materialCategories" :compact="props.compact ?? false" />
  </template>
</template>
<style scoped>
/* 长名称和规格完整换行，窄窗口减少资料列数。 */
.material-facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px 28px; margin: 16px 0; }
.material-facts dt { color: var(--workspace-field-muted); font-size: 12px; margin-bottom: 7px; }
.material-facts dd { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.material-error { color: var(--app-danger, #b94438); }
@media (max-width: 480px) { .material-facts { grid-template-columns: 1fr; } }
</style>
