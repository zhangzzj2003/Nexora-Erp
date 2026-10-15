<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NCollapse } from 'naive-ui'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
import type { Bom } from '../../../../../shared/erp-api'
import AppButton from '../../../components/app/AppButton.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { bomStructureRows } from './bom-structure'
const props = defineProps<{bom:Bom; catalog:Bom[]; disabled:boolean}>()
const emit = defineEmits<{open:[id:number]}>()
const expanded = ref(new Set<string>())
// 切换产品或版本重新收起；相同组件在不同分支独立展开。
watch(() => props.bom.id, () => {expanded.value = new Set()})
const rows = computed(() => bomStructureRows(props.bom, props.catalog, expanded.value))
function toggle(key:string): void {
  const next = new Set(expanded.value)
  if (next.has(key)) next.delete(key); else next.add(key)
  expanded.value = next
}
const columns = [{key:'component',title:'组件 / 多层组成'}, {key:'quantity',title:'用量',width:'120'},
  {key:'unit',title:'单位',width:'70'}, {key:'recipe',title:'下层生产配方',width:'240'}]
</script>
<template>
  <section class="bom-composition" aria-label="BOM 组成明细">
    <header class="structure-heading"><div><h4>组成明细</h4><span class="structure-basis">基准产出 <strong>{{ bom.base_quantity }} {{ bom.product_unit }}</strong><span class="structure-count">{{ bom.lines.length }} 项直接组件</span></span></div>
      <NCollapse class="structure-help"><AppCollapseItem name="production-notes" title="领料与版本说明"><p>生产领用第一层物料；展开下层仅查看其组成，不重复扣料。同一编码库存按可互换管理。固定版本约束配方，不区分实物库存版本。</p></AppCollapseItem></NCollapse>
    </header>
    <WorkspaceTable class="structure-table" :title="`组成明细 · V${bom.version}`" :show-title="false" :data="rows" :columns="columns" :min-table-width="680">
    <template #cell-component="{row}"><div class="structure-component" :style="{paddingLeft:`${row.depth * 20}px`}">
      <AppButton v-if="row.childBom && row.issue !== '存在循环引用' && row.depth < 20" size="small" :aria-expanded="row.expanded" :aria-label="`${row.expanded ? '收起' : '展开'}${row.name}的组成`" :disabled="disabled" @click="toggle(row.key)">{{ row.expanded ? '−' : '+' }}</AppButton>
      <div><strong>{{ row.name }}</strong><small>{{ row.sku }}</small><p v-if="row.issue" role="status">{{ row.issue }}</p></div>
    </div></template>
    <template #cell-quantity="{row}">{{ row.quantity }}</template><template #cell-unit="{row}">{{ row.unit }}</template>
    <template #cell-recipe="{row}"><AppButton v-if="row.childBom" size="small" :disabled="disabled" @click="emit('open',row.childBom.id)">{{ row.fixed ? '固定' : '当前启用参考' }} V{{ row.childBom.version }}</AppButton><span v-else>{{ row.fixed ? '固定版本不可用' : '按物料领用' }}</span></template>
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
.structure-component strong { font-size:13px; }
.structure-component { display:flex; align-items:center; gap:10px; }
.structure-component small { display:block; color:var(--workspace-field-muted); margin-top:5px; }
.structure-component p { margin:5px 0 0; color:var(--workspace-warning); }
</style>
