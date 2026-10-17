<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import type { MaterialCategory, MaterialChoice } from '../../../../shared/material-api'
import AppButton from '../app/AppButton.vue'
import { hasMaterialDetails, materialParameterFacts } from '../../utils/material-selection'

// 只展示调用方已经取得的档案，避免每个表格行另发请求或读取跨页面业务状态。
const props = withDefaults(defineProps<{
  material?: MaterialChoice | null
  categories?: readonly MaterialCategory[]
  compact?: boolean
  currentReference?: boolean
}>(), { categories: () => [], compact: true, currentReference: false })
const facts = computed(() => props.material ? materialParameterFacts(props.material, props.categories) : [])
const expanded = ref(false)
const supplementId = useId()
// 当前规格及扩展属性始终可见；只有长备注属于可收起的补充资料。
const supplemental = computed(() => props.compact && facts.value.some(fact => fact.key !== 'notes') ? facts.value.filter(fact => fact.key === 'notes'
  && (fact.value.length > 120 || fact.value.includes('\n'))) : [])
const mainFacts = computed(() => facts.value.filter(fact => !supplemental.value.includes(fact)))
const emptyMessage = computed(() => props.material && hasMaterialDetails(props.material) ? '参数未填写' : '详细资料暂不可用')
// 换料或切换显示密度时收起旧备注，同一物料资料刷新不抢走阅读状态。
watch(() => [props.material?.id, props.compact], () => { expanded.value = false })
</script>

<template>
  <div class="workspace-material-parameters" :class="{ 'is-compact': compact }" :aria-label="currentReference ? '当前档案参数' : '物料参数'">
    <p v-if="currentReference" class="material-parameters-reference">当前档案参数</p>
    <dl v-if="mainFacts.length" class="material-parameters-facts">
      <div v-for="fact in mainFacts" :key="fact.key" class="material-parameters-fact" :class="{ 'is-note': fact.key === 'notes' }">
        <dt>{{ fact.label }}</dt><dd>{{ fact.value }}</dd>
      </div>
    </dl>
    <template v-if="supplemental.length">
      <AppButton type="button" variant="text" size="small" class="material-parameters-toggle" :aria-expanded="expanded" :aria-controls="supplementId"
        @click.stop="expanded = !expanded">{{ expanded ? '收起补充资料' : '展开补充资料' }}</AppButton>
      <dl v-if="expanded" :id="supplementId" class="material-parameters-facts material-parameters-supplement">
        <div v-for="fact in supplemental" :key="fact.key" class="material-parameters-fact is-note"><dt>{{ fact.label }}</dt><dd>{{ fact.value }}</dd></div>
      </dl>
    </template>
    <p v-if="!facts.length" class="material-parameters-empty" role="status">{{ emptyMessage }}</p>
  </div>
</template>

<style scoped>
/* 名称下使用紧凑换行，详情中按可用宽度排布；长参数完整展示，不依赖鼠标悬停。 */
.workspace-material-parameters { min-width:0; font-size:12px; font-weight:400; line-height:1.65; }
.material-parameters-reference,.material-parameters-empty { margin:0; color:var(--workspace-field-muted); font-size:12px; }
.material-parameters-reference { margin-bottom:4px; }
.material-parameters-facts { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,200px),1fr)); gap:8px 18px; margin:0; padding:0; }
.material-parameters-fact { display:flex; align-items:baseline; gap:5px; min-width:0; max-width:100%; }
.material-parameters-fact dt { flex-shrink:0; color:var(--workspace-field-muted); }
.material-parameters-fact dd { min-width:0; margin:0; color:var(--workspace-field-text); white-space:pre-wrap; overflow-wrap:anywhere; }
.material-parameters-fact.is-note { grid-column:1/-1; }
.is-compact .material-parameters-facts { display:flex; flex-wrap:wrap; gap:3px 12px; }
.is-compact .material-parameters-fact.is-note { flex-basis:100%; }
.material-parameters-toggle { margin-top:5px; }
.material-parameters-supplement { margin-top:5px; }
</style>
