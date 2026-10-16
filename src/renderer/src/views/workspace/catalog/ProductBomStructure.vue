<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NCollapse } from 'naive-ui'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
import type { Bom } from '../../../../../shared/erp-api'
import AppButton from '../../../components/app/AppButton.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import IconArrowRightSLine from '~icons/ri/arrow-right-s-line'
import IconPushpinLine from '~icons/ri/pushpin-line'
import IconGitBranchLine from '~icons/ri/git-branch-line'
import { bomStructureRows } from './bom-structure'
import type { BomStructureRow } from './bom-structure'
import { captureDialogOrigin } from '../../../utils/dialog-origin'
const props = defineProps<{bom:Bom; catalog:Bom[]; disabled:boolean}>()
const emit = defineEmits<{open:[id:number]; material:[row:BomStructureRow]}>()
const expanded = ref(new Set<string>())
// 切换产品或版本重新收起；相同组件在不同分支独立展开。
watch(() => props.bom.id, () => {expanded.value = new Set()})
const rows = computed(() => bomStructureRows(props.bom, props.catalog, expanded.value))
function toggle(key:string): void {
  const next = new Set(expanded.value)
  if (next.has(key)) next.delete(key); else next.add(key)
  expanded.value = next
}
function openMaterial(row:BomStructureRow, event:MouseEvent): void {
  // 仅接受当前可见组成，切换版本或收起分支后的旧入口不能打开上一份物料。
  if (props.disabled || !rows.value.some(current => current.key === row.key && current.materialId === row.materialId
    && current.sku === row.sku && current.name === row.name)) return
  captureDialogOrigin('inventory-material', event)
  emit('material', row)
}
// 名称列保留树形缩进与长物料名称的空间，数量、单位和配方列采用紧凑的最小宽度。
const columns = [{key:'component',title:'组件 / 多层组成',width:'280'}, {key:'sku',title:'物料编号',width:'165'}, {key:'quantity',title:'用量',width:'90'},
  {key:'unit',title:'单位',width:'60'}, {key:'recipe',title:'下层生产配方',width:'200'}]
</script>
<template>
  <section class="bom-composition" aria-label="BOM 组成明细">
    <header class="structure-heading"><div><h4>组成明细</h4><span class="structure-basis">基准产出 <strong>{{ bom.base_quantity }} {{ bom.product_unit }}</strong><span class="structure-count">{{ bom.lines.length }} 项直接组件</span></span></div>
      <NCollapse class="structure-help"><AppCollapseItem name="production-notes" title="领料与版本说明"><p>生产领用第一层物料；展开下层仅查看其组成，不重复扣料。同一编码库存按可互换管理。固定版本约束配方，不区分实物库存版本。</p></AppCollapseItem></NCollapse>
    </header>
    <WorkspaceTable class="structure-table" :title="`组成明细 · V${bom.version}`" :show-title="false" :data="rows" :columns="columns" :min-table-width="860">
    <template #cell-component="{row}"><div class="structure-component" :class="{'is-assembly':!!row.childBom,'is-nested':row.depth>0}" :style="{'--structure-indent':`${row.depth * 22}px`}">
      <!-- 展开箭头与普通物料占用相同宽度，名称保持对齐；实际展开仍沿用每条分支的独立键。 -->
      <AppButton v-if="row.childBom && row.issue !== '存在循环引用' && row.depth < 20" variant="plain" class="structure-toggle" size="small" :aria-expanded="row.expanded" :aria-label="`${row.expanded ? '收起' : '展开'}${row.name}的组成`" :title="`${row.expanded ? '收起' : '展开'}下层组成`" :disabled="disabled" @click="toggle(row.key)"><IconArrowRightSLine class="structure-chevron" :class="{'is-expanded':row.expanded}" aria-hidden="true" focusable="false" /></AppButton>
      <span v-else class="structure-leaf" aria-hidden="true"><span /></span>
      <div class="structure-material"><strong>{{ row.name }}</strong><p v-if="row.issue" role="status">{{ row.issue }}</p></div>
    </div></template>
    <!-- 编号与名称分列；物料详情与右侧配方详情使用各自的入口，不触发树形展开。 -->
    <template #cell-sku="{row}"><AppButton variant="text" class="structure-sku" size="small" :disabled="disabled" :aria-label="`查看物料 ${row.sku} 的详情`" @click="openMaterial(row,$event)">{{ row.sku }}</AppButton></template>
    <template #cell-quantity="{row}"><span class="structure-quantity">{{ row.quantity }}</span></template><template #cell-unit="{row}">{{ row.unit }}</template>
    <template #cell-recipe="{row}">
      <!-- 固定配方与当前参考保留完整语义和原详情入口，仅通过轻量样式区分绑定方式。 -->
      <AppButton v-if="row.childBom" variant="plain" class="structure-recipe" :class="row.fixed ? 'is-fixed' : 'is-reference'" size="small" :title="`查看${row.name}的${row.fixed ? '固定' : '当前启用参考'}配方 V${row.childBom.version}`" :disabled="disabled" @click="emit('open',row.childBom.id)"><IconPushpinLine v-if="row.fixed" class="structure-recipe-icon" aria-hidden="true" focusable="false" /><IconGitBranchLine v-else class="structure-recipe-icon" aria-hidden="true" focusable="false" /><span>{{ row.fixed ? '固定' : '当前启用参考' }} <strong>V{{ row.childBom.version }}</strong></span></AppButton>
      <span v-else class="structure-recipe-empty" :class="{'is-unavailable':row.fixed}">{{ row.fixed ? '固定版本不可用' : '按物料领用' }}</span>
    </template>
    </WorkspaceTable>
  </section>
</template>
<style scoped>
/* 表格嵌入当前 BOM 工作区，仅移除重复外壳，不改公共列宽、横向滚动和空状态。 */
.structure-table { padding:0; border:0; border-radius:0; background:transparent; box-shadow:none; }
.structure-heading { display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:12px; padding:18px 0 14px; }
.structure-heading>div { display:grid; gap:7px; }
.structure-heading h4 { margin:0; font-size:15px; }
.structure-basis { display:flex; align-items:center; gap:6px; flex-wrap:wrap; color:var(--workspace-field-muted); font-size:12px; }
.structure-basis strong { font-weight:600; color:var(--workspace-field-text); }
.structure-count { padding-left:8px; margin-left:2px; border-left:1px solid var(--workspace-field-border); }
/* 说明原地展开，窄窗口自然换行，不使用会遮挡表格的浮层。 */
.structure-help { width:auto; max-width:420px; font-size:12px; line-height:1.7; color:var(--workspace-field-muted); }
.structure-help :deep(.app-collapse-trigger) { color:var(--workspace-field-accent); font-size:12px; }
.structure-help p { margin:8px 0 0; }
/* 固定宽度的树形入口让普通物料与有下层配方的组件对齐，分支线只提示真实的嵌套层级。 */
.structure-component { position:relative; display:grid; grid-template-columns:26px minmax(0,1fr); align-items:center; gap:8px; min-width:0; padding-left:var(--structure-indent); }
.structure-component.is-nested::before { content:''; position:absolute; left:calc(var(--structure-indent) - 12px); top:2px; width:9px; height:18px; border-left:1px solid var(--workspace-field-border); border-bottom:1px solid var(--workspace-field-border); border-bottom-left-radius:4px; }
.structure-material { min-width:0; }
.structure-material strong { font-size:13px; font-weight:600; overflow-wrap:anywhere; }
.is-assembly>.structure-material>strong { color:var(--workspace-field-accent); }
.structure-sku { font-size:12px; font-weight:500; font-variant-numeric:tabular-nums; overflow-wrap:anywhere; text-align:left; }
.structure-material p { margin:5px 0 0; color:var(--structure-warning-color); font-size:12px; }
.structure-toggle { display:inline-grid; place-items:center; width:26px; height:26px; padding:0; border-radius:6px; background:var(--app-accent-tint); color:var(--workspace-field-accent); }
.structure-toggle:hover:not(:disabled) { background:var(--app-accent-active-tint); }
.structure-chevron { width:17px; height:17px; transition:transform 140ms ease; }
.structure-chevron.is-expanded { transform:rotate(90deg); }
.structure-leaf { display:grid; place-items:center; width:26px; height:26px; }
.structure-leaf>span { width:4px; height:4px; border-radius:50%; background:var(--workspace-field-border); }
.structure-quantity { font-variant-numeric:tabular-nums; }
/* 配方仍是可点击按钮；图钉表示固定版本，分支表示随当前启用配方参考查看。 */
.structure-recipe { display:inline-flex; align-items:center; gap:6px; min-height:28px; padding:3px 8px; border:1px solid var(--workspace-field-border); border-radius:6px; font-size:12px; font-weight:400; line-height:18px; white-space:nowrap; }
.structure-recipe.is-fixed { color:var(--workspace-field-accent); background:var(--app-accent-tint); border-color:color-mix(in srgb,var(--workspace-field-accent) 24%,transparent); }
.structure-recipe.is-reference { color:var(--workspace-field-muted); border-style:dashed; }
.structure-recipe:hover:not(:disabled) { color:var(--workspace-field-accent); border-color:var(--workspace-field-accent); background:var(--app-accent-active-tint); }
.structure-recipe strong { font-weight:600; }
.structure-recipe-icon { width:13px; height:13px; flex:none; }
.structure-recipe-empty { color:var(--workspace-field-muted); font-size:12px; }
.structure-recipe-empty.is-unavailable { color:var(--structure-warning-color); }
.bom-composition { --structure-warning-color:#946000; }
:root[data-theme='dark'] .bom-composition { --structure-warning-color:#efc16a; }
@media (prefers-reduced-motion:reduce) { .structure-chevron { transition:none; } }
</style>
