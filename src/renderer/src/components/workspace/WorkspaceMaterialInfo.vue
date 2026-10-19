<script setup lang="ts">
import { computed, nextTick, ref, useId, watch } from 'vue'
import type { MaterialCategory, MaterialChoice } from '../../../../shared/material-api'
import AppButton from '../app/AppButton.vue'
import { hasMaterialDetails, materialChoiceFacts, materialChoiceSummary, materialParameterFacts } from '../../utils/material-selection'

// 选料器和只读名称共用这一份摘要、资料卡和展开逻辑；业务候选、权限及读取仍由调用方负责。
const props = withDefaults(defineProps<{
  material?: MaterialChoice | null
  categories?: readonly MaterialCategory[]
  // undefined 用于普通表单：显示核心资料，但不提供收起资料按钮。
  compact?: boolean
  disabled?: boolean
  currentReference?: boolean
}>(), { categories: () => [], compact: undefined, disabled: false, currentReference: false })
const emit = defineEmits<{ 'update:compact': [value: boolean] }>()
const available = computed(() => !!props.material && hasMaterialDetails(props.material))
const core = computed(() => props.material ? materialChoiceFacts(props.material, props.categories).filter(fact => fact.key !== 'spec_summary') : [])
const technical = computed(() => props.material ? materialParameterFacts(props.material, props.categories)
  .filter(fact => !core.value.some(item => item.key === fact.key)) : [])
const summary = computed(() => props.material ? materialChoiceSummary(props.material) : '')
const expanded = ref(false)
const infoId = useId(), detailsId = useId()
const infoToggle = ref<{ $el: HTMLElement } | null>(null)
// 只在物料身份或显示模式变化时收起技术参数，同一物料的授权资料刷新保留阅读状态。
watch([() => props.material?.id, () => props.compact], () => { expanded.value = false })
function toggleCompact(value: boolean): void {
  if (props.disabled) return
  emit('update:compact', value)
  // 互相替换摘要与资料卡之后，将键盘焦点交还给对应的查看或收起按钮。
  void nextTick(() => {
    if (typeof HTMLElement !== 'undefined' && infoToggle.value?.$el instanceof HTMLElement) infoToggle.value.$el.focus()
  })
}
</script>
<template>
  <div class="workspace-material-info" :aria-label="currentReference ? '当前档案参数' : '物料资料'">
    <div v-if="available && compact" class="workspace-material-summary" aria-label="物料资料摘要">
      <span class="workspace-material-summary__text" :title="summary">{{ summary }}</span>
      <AppButton ref="infoToggle" type="button" variant="text" size="small" :disabled="disabled" aria-expanded="false" :aria-controls="infoId"
        @click.prevent.stop="toggleCompact(false)">查看资料</AppButton>
    </div>
    <div v-else-if="available" :id="infoId" class="workspace-material-facts" aria-label="物料资料">
      <p v-if="currentReference" class="workspace-material-reference">当前档案参数</p>
      <dl class="workspace-material-core">
        <div v-for="fact in core" :key="fact.key" class="workspace-material-fact"><dt>{{ fact.label }}</dt><dd>{{ fact.value }}</dd></div>
      </dl>
      <div class="workspace-material-actions">
        <AppButton v-if="technical.length" type="button" variant="text" size="small" :disabled="disabled" :aria-expanded="expanded" :aria-controls="detailsId"
          @click.prevent.stop="expanded = !expanded">{{ expanded ? '收起详情' : '展开详情' }}</AppButton>
        <AppButton v-if="compact !== undefined" ref="infoToggle" type="button" variant="text" size="small" :disabled="disabled" aria-expanded="true" :aria-controls="infoId"
          @click.prevent.stop="toggleCompact(true)">收起资料</AppButton>
      </div>
      <dl v-if="expanded" :id="detailsId" class="workspace-material-core workspace-material-technical">
        <div v-for="fact in technical" :key="fact.key" class="workspace-material-fact" :class="{ 'workspace-material-fact--wide': fact.key === 'notes' }"><dt>{{ fact.label }}</dt><dd>{{ fact.value }}</dd></div>
      </dl>
    </div>
    <p v-else class="workspace-material-unavailable" role="status">详细资料暂不可用</p>
  </div>
</template>
<style scoped>
/* 名称列和选料器使用相同的两列资料卡；摘要保持单行，按钮不被长规格挤出。 */
.workspace-material-info { min-width:0; width:100%; font-size:12px; font-weight:400; line-height:1.5; }
.workspace-material-summary { display:flex; align-items:center; gap:10px; min-width:0; color:var(--workspace-field-muted); }
.workspace-material-summary__text { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.workspace-material-summary > :last-child { flex-shrink:0; }
.workspace-material-facts { padding:10px; border:1px solid var(--workspace-field-border); border-radius:8px; background:var(--app-accent-tint); }
.workspace-material-core { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px 14px; margin:0; padding:0; }
.workspace-material-fact { display:flex; flex-direction:column; gap:2px; min-width:0; overflow-wrap:anywhere; white-space:pre-wrap; }
.workspace-material-fact dt,.workspace-material-reference,.workspace-material-unavailable { color:var(--workspace-field-muted); }
.workspace-material-fact dd,.workspace-material-reference,.workspace-material-unavailable { margin:0; }
.workspace-material-reference { margin-bottom:8px; }
.workspace-material-fact--wide { grid-column:1/-1; }
.workspace-material-actions { display:flex; align-items:center; gap:14px; margin-top:8px; }
.workspace-material-technical { margin-top:10px; padding-top:10px; border-top:1px solid var(--workspace-field-border); }
</style>
