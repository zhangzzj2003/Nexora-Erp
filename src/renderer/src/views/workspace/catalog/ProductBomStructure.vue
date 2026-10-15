<script setup lang="ts">
import { computed, ref, watch } from 'vue'
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
  <WorkspaceTable :title="`组成明细 · V${bom.version}`" :data="rows" :columns="columns" :min-table-width="680">
    <template #beforeTable><p class="structure-note">按 {{ bom.base_quantity }} {{ bom.product_unit }}产出查看。生产领用第一层物料；展开下层仅查看其组成，不重复扣料。同一编码库存按可互换管理。</p></template>
    <template #cell-component="{row}"><div class="structure-component" :style="{paddingLeft:`${row.depth * 20}px`}">
      <AppButton v-if="row.childBom && row.issue !== '存在循环引用' && row.depth < 20" size="small" :aria-expanded="row.expanded" :aria-label="`${row.expanded ? '收起' : '展开'}${row.name}的组成`" :disabled="disabled" @click="toggle(row.key)">{{ row.expanded ? '−' : '+' }}</AppButton>
      <div><strong>{{ row.name }}</strong><small>{{ row.sku }}</small><p v-if="row.issue" role="status">{{ row.issue }}</p></div>
    </div></template>
    <template #cell-quantity="{row}">{{ row.quantity }}</template><template #cell-unit="{row}">{{ row.unit }}</template>
    <template #cell-recipe="{row}"><AppButton v-if="row.childBom" size="small" :disabled="disabled" @click="emit('open',row.childBom.id)">{{ row.fixed ? '固定' : '当前启用参考' }} V{{ row.childBom.version }}</AppButton><span v-else>{{ row.fixed ? '固定版本不可用' : '按物料领用' }}</span></template>
  </WorkspaceTable>
</template>
<style scoped>
/* 层级通过缩进与展开键表达，沿用公共表格颜色和间距。 */
.structure-note { margin:0 0 14px; color:var(--workspace-field-muted); font-size:12px; line-height:1.7; }
.structure-component { display:flex; align-items:center; gap:10px; }
.structure-component small { display:block; color:var(--workspace-field-muted); margin-top:5px; }
.structure-component p { margin:5px 0 0; color:var(--workspace-warning); }
</style>
