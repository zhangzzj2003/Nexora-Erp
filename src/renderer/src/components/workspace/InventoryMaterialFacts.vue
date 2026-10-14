<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import AppButton from '../app/AppButton.vue'
import { usePiniaAppStore } from '../../store/app-store'
import { materialChoiceFacts } from '../../utils/material-selection'
const props = defineProps<{ compact?: boolean }>()
const store = usePiniaAppStore()
const { connectionLost, materialCategories, ledgerMaterialTarget, ledgerMaterialDetail: material,
  ledgerMaterialLoading: loading, ledgerMaterialError: error } = storeToRefs(store)
const expanded = ref(false)
watch(ledgerMaterialTarget, () => { expanded.value = false })
const facts = computed(() => material.value ? [
  { key: 'sku', label: '物料编号', value: material.value.sku },
  { key: 'name', label: '物料名称', value: material.value.name },
  ...materialChoiceFacts(material.value, materialCategories.value),
  ...materialChoiceFacts(material.value, materialCategories.value, true)
] : [])
// 总览先显示辨认物料所需的六项资料，完整规格与备注可展开，给仓库分布和流水留出空间。
const visibleFacts = computed(() => !props.compact || expanded.value ? facts.value
  : facts.value.filter(item => ['sku', 'name', 'category_name', 'specification', 'unit', 'brand'].includes(item.key)))
</script>
<template>
  <p v-if="loading" role="status">正在读取物料详情…</p>
  <div v-else-if="error" role="alert" class="material-error">
    <p>{{ error }}</p><AppButton :disabled="connectionLost" @click="store.loadLedgerMaterial()">重新读取物料</AppButton>
  </div>
  <template v-else-if="material">
    <dl class="material-facts"><div v-for="fact in visibleFacts" :key="fact.key"><dt>{{ fact.label }}</dt><dd>{{ fact.value }}</dd></div></dl>
    <AppButton v-if="compact" variant="text" :aria-expanded="expanded" @click="expanded = !expanded">{{ expanded ? '收起更多资料' : '展开规格与更多资料' }}</AppButton>
  </template>
</template>
<style scoped>
/* 长名称和规格完整换行，窄窗口减少资料列数。 */
.material-facts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px 28px; margin: 16px 0; }
.material-facts dt { color: var(--workspace-field-muted); font-size: 12px; margin-bottom: 7px; }
.material-facts dd { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.material-error { color: var(--app-danger, #b94438); }
@media (max-width: 760px) { .material-facts { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 480px) { .material-facts { grid-template-columns: 1fr; } }
</style>
