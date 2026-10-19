<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { MaterialCategory, MaterialChoice } from '../../../../shared/material-api'
import WorkspaceMaterialInfo from './WorkspaceMaterialInfo.vue'
import { hasMaterialDetails, materialParameterFacts } from '../../utils/material-selection'

// 兼容原有完整物料详情；名称列与选择器的摘要、资料卡统一交给公共资料组件。
const props = withDefaults(defineProps<{
  material?: MaterialChoice | null
  categories?: readonly MaterialCategory[]
  compact?: boolean
  currentReference?: boolean
}>(), { categories: () => [], compact: true, currentReference: false })
const collapsed = ref(true)
const facts = computed(() => props.material ? materialParameterFacts(props.material, props.categories) : [])
const emptyMessage = computed(() => props.material && hasMaterialDetails(props.material) ? '参数未填写' : '详细资料暂不可用')
// 换料及切换完整模式后恢复默认摘要，同一物料刷新资料不重置当前阅读状态。
watch([() => props.material?.id, () => props.compact], () => { collapsed.value = true })
</script>
<template>
  <div class="workspace-material-parameters" :aria-label="currentReference ? '当前档案参数' : '物料参数'">
    <WorkspaceMaterialInfo v-if="compact && facts.length" v-model:compact="collapsed" :material="material" :categories="categories" :current-reference="currentReference" />
    <template v-else-if="facts.length">
      <p v-if="currentReference" class="material-parameters-reference">当前档案参数</p>
      <dl class="material-parameters-facts"><div v-for="fact in facts" :key="fact.key" class="material-parameters-fact" :class="{ 'is-note': fact.key === 'notes' }"><dt>{{ fact.label }}</dt><dd>{{ fact.value }}</dd></div></dl>
    </template>
    <p v-else class="material-parameters-empty" role="status">{{ emptyMessage }}</p>
  </div>
</template>
<style scoped>
/* 独立物料详情完整展示参数；单据名称下的两级展开样式只在公共资料组件维护。 */
.workspace-material-parameters { min-width:0; font-size:12px; font-weight:400; line-height:1.65; }
.material-parameters-reference,.material-parameters-empty { margin:0; color:var(--workspace-field-muted); font-size:12px; }
.material-parameters-reference { margin-bottom:4px; }
.material-parameters-facts { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,200px),1fr)); gap:8px 18px; margin:0; padding:0; }
.material-parameters-fact { display:flex; align-items:baseline; gap:5px; min-width:0; max-width:100%; }
.material-parameters-fact dt { flex-shrink:0; color:var(--workspace-field-muted); }
.material-parameters-fact dd { min-width:0; margin:0; color:var(--workspace-field-text); white-space:pre-wrap; overflow-wrap:anywhere; }
.material-parameters-fact.is-note { grid-column:1/-1; }
</style>
