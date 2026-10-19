<script setup lang="ts">
import { computed, nextTick, ref, useId, watch } from 'vue'
import type { MaterialCategory, MaterialChoice } from '../../../../shared/material-api'
import AppButton from '../app/AppButton.vue'
import { hasMaterialDetails, materialChoiceFacts, materialChoiceSummary, materialParameterFacts } from '../../utils/material-selection'

// 只展示调用方已经取得的档案，避免每个表格行另发请求或读取跨页面业务状态。
const props = withDefaults(defineProps<{
  material?: MaterialChoice | null
  categories?: readonly MaterialCategory[]
  compact?: boolean
  currentReference?: boolean
}>(), { categories: () => [], compact: true, currentReference: false })
const facts = computed(() => props.material ? materialParameterFacts(props.material, props.categories) : [])
const core = computed(() => props.material ? materialChoiceFacts(props.material, props.categories).filter(fact => fact.key !== 'spec_summary') : [])
const technical = computed(() => facts.value.filter(fact => !core.value.some(item => item.key === fact.key)))
const summary = computed(() => props.material ? materialChoiceSummary(props.material) : '')
const showingInfo = ref(false)
const expanded = ref(false)
const infoId = useId()
const detailsId = useId()
const infoToggle = ref<{ $el: HTMLElement } | null>(null)
const emptyMessage = computed(() => props.material && hasMaterialDetails(props.material) ? '参数未填写' : '详细资料暂不可用')
// 换料或切换显示密度时回到一行摘要；同一物料刷新参数不抢走阅读状态。
watch([() => props.material?.id, () => props.compact], () => { showingInfo.value = false; expanded.value = false })
function toggleInfo(): void {
  showingInfo.value = !showingInfo.value
  expanded.value = false
  // 摘要和资料卡互相替换后，将键盘焦点交给新的查看/收起按钮。
  void nextTick(() => {
    if (typeof HTMLElement !== 'undefined' && infoToggle.value?.$el instanceof HTMLElement) infoToggle.value.$el.focus()
  })
}
</script>

<template>
  <div class="workspace-material-parameters" :class="{ 'is-compact': compact }" :aria-label="currentReference ? '当前档案参数' : '物料参数'">
    <!-- 单据名称下默认只留一行摘要，完整参数不能直接撑高每一行。 -->
    <div v-if="compact && facts.length && !showingInfo" class="material-parameters-summary" aria-label="物料资料摘要">
      <span class="material-parameters-summary-text" :title="summary">{{ summary }}</span>
      <AppButton ref="infoToggle" type="button" variant="text" size="small" aria-expanded="false" :aria-controls="infoId"
        @click.prevent.stop="toggleInfo">查看资料</AppButton>
    </div>
    <div v-else-if="facts.length" :id="infoId" :class="{ 'material-parameters-card': compact }">
      <p v-if="currentReference" class="material-parameters-reference">当前档案参数</p>
      <dl class="material-parameters-facts">
        <div v-for="fact in compact ? core : facts" :key="fact.key" class="material-parameters-fact" :class="{ 'is-note': fact.key === 'notes' }">
          <dt>{{ fact.label }}</dt><dd>{{ fact.value }}</dd>
        </div>
      </dl>
      <div v-if="compact" class="material-parameters-actions">
        <AppButton v-if="technical.length" type="button" variant="text" size="small" :aria-expanded="expanded" :aria-controls="detailsId"
          @click.prevent.stop="expanded = !expanded">{{ expanded ? '收起详情' : '展开详情' }}</AppButton>
        <AppButton ref="infoToggle" type="button" variant="text" size="small" aria-expanded="true" :aria-controls="infoId"
          @click.prevent.stop="toggleInfo">收起资料</AppButton>
      </div>
      <dl v-if="compact && expanded" :id="detailsId" class="material-parameters-facts material-parameters-technical">
        <div v-for="fact in technical" :key="fact.key" class="material-parameters-fact" :class="{ 'is-note': fact.key === 'notes' }">
          <dt>{{ fact.label }}</dt><dd>{{ fact.value }}</dd>
        </div>
      </dl>
    </div>
    <p v-else class="material-parameters-empty" role="status">{{ emptyMessage }}</p>
  </div>
</template>

<style scoped>
/* 与选料器相同：摘要单行省略，按钮常驻；展开后使用两列资料卡，长备注按需阅读。 */
.workspace-material-parameters { min-width:0; font-size:12px; font-weight:400; line-height:1.65; }
.material-parameters-summary { display:flex; align-items:center; gap:10px; min-width:0; color:var(--workspace-field-muted); }
.material-parameters-summary-text { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.material-parameters-summary > :last-child { flex-shrink:0; }
.material-parameters-reference,.material-parameters-empty { margin:0; color:var(--workspace-field-muted); font-size:12px; }
.material-parameters-reference { margin-bottom:4px; }
.material-parameters-facts { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,200px),1fr)); gap:8px 18px; margin:0; padding:0; }
.material-parameters-fact { display:flex; align-items:baseline; gap:5px; min-width:0; max-width:100%; }
.material-parameters-fact dt { flex-shrink:0; color:var(--workspace-field-muted); }
.material-parameters-fact dd { min-width:0; margin:0; color:var(--workspace-field-text); white-space:pre-wrap; overflow-wrap:anywhere; }
.material-parameters-fact.is-note { grid-column:1/-1; }
.material-parameters-card { margin-top:8px; padding:10px; border:1px solid var(--workspace-field-border); border-radius:8px; background:var(--app-accent-tint); }
.material-parameters-card .material-parameters-facts { grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px 14px; }
.material-parameters-card .material-parameters-fact { flex-direction:column; align-items:stretch; gap:2px; }
.material-parameters-actions { display:flex; align-items:center; gap:14px; margin-top:8px; }
.material-parameters-technical { margin-top:10px; padding-top:10px; border-top:1px solid var(--workspace-field-border); }
</style>
