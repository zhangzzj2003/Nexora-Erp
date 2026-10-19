<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { MaterialCategory, MaterialChoice } from '../../../../shared/material-api'
import WorkspaceMaterialInfo from './WorkspaceMaterialInfo.vue'
import { materialParameterSource } from '../../utils/material-parameter-source'

// 名称始终来自原单据；资料只按真实 ID 读取调用方已授权的数据，不能用当前档案覆盖历史身份。
const props = withDefaults(defineProps<{
  name: string
  materialId?: number
  material?: MaterialChoice | null
  cachedMaterials?: ReadonlyMap<number, MaterialChoice>
  categories?: readonly MaterialCategory[]
  secondary?: string
  currentReference?: boolean
}>(), { categories: () => [], secondary: '', currentReference: true })
const source = computed(() => materialParameterSource(props.materialId ?? 0, props.material, props.cachedMaterials))
const collapsed = ref(true)
// 同一行切换物料身份时收起资料；仅刷新规格或摘要时保留阅读状态。
watch(() => props.materialId, () => { collapsed.value = true })
</script>
<template>
  <div class="workspace-material-name">
    <strong class="workspace-material-name__label">{{ name }}</strong>
    <span v-if="secondary" class="workspace-material-name__secondary">{{ secondary }}</span>
    <WorkspaceMaterialInfo v-if="materialId" v-model:compact="collapsed" :material="source" :categories="categories" :current-reference="currentReference" />
  </div>
</template>
<style scoped>
/* 各详情只传入原名称与授权资料，统一由组件控制名称、单行摘要和资料卡之间的间距。 */
.workspace-material-name { display:flex; flex-direction:column; gap:6px; min-width:0; width:100%; }
.workspace-material-name__label { color:var(--workspace-material-name-color,inherit); font-weight:600; min-width:0; white-space:pre-wrap; overflow-wrap:anywhere; }
.workspace-material-name__secondary { font-size:12px; font-weight:400; color:var(--workspace-field-muted); white-space:pre-wrap; overflow-wrap:anywhere; }
</style>
