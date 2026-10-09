<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { NModal } from 'naive-ui'
import AppButton from '../app/AppButton.vue'
import WorkspaceTable from './WorkspaceTable.vue'
import { usePiniaAppStore } from '../../store/app-store'
import { materialSupplyPhases, materialSupplyLabels, materialSupplyKindLabels } from '../../../../shared/material-supply-api'

const props = withDefaults(defineProps<{ materialId: number; active?: boolean }>(), { active: true })
const store = usePiniaAppStore()
const { materialSupplyRows, materialSupplyLoading, materialSupplyErrors, materialSupplyEpoch, connectionLost } = storeToRefs(store)
const open = ref(false)
const entry = computed(() => materialSupplyRows.value[props.materialId])
const loading = computed(() => !!materialSupplyLoading.value[props.materialId])
const error = computed(() => materialSupplyErrors.value[props.materialId] ?? '')
watch(() => [props.materialId, props.active, materialSupplyEpoch.value], (_value, _old, onCleanup) => {
  open.value = false
  if (props.active && props.materialId > 0 && !connectionLost.value) onCleanup(store.subscribeMaterialSupply(props.materialId))
}, { immediate: true })
async function showDetails(): Promise<void> {
  open.value = true
  await store.loadMaterialSupply(props.materialId, true)
}
const columns = [{key: 'phase', title: '阶段', width: '100'}, {key: 'source', title: '来源单据 / 仓库', width: '280'},
  {key: 'quantity', title: '数量', width: '130'}]
</script>

<template>
  <!-- 四项始终显示明确标签；未知、失败和无权限不伪装成零库存。 -->
  <span v-if="!materialId" class="supply-placeholder">选择物料后查看</span>
  <AppButton v-else variant="plain" type="button" class="material-supply-cell" :disabled="!active || connectionLost"
    :aria-label="`${entry?.row.name ?? '当前物料'}物料供需，点击查看来源`" @click="showDetails">
    <span v-for="phase in materialSupplyPhases" :key="phase" class="supply-count">
      <span>{{ materialSupplyLabels[phase] }}</span>
      <strong>{{ connectionLost ? '—' : loading ? '…' : error ? '—' : entry ? (entry.row[`${phase}_quantity`] ?? '无权限') : '—' }}</strong>
    </span>
    <span class="supply-caption">{{ connectionLost ? '连接已断开' : error ? '读取失败，点击重试' : '全仓 · 查看来源' }}</span>
  </AppButton>
  <!-- 当前供需独立于原单据正文，历史明细与审批冻结数量保持原样。 -->
  <NModal :show="open && active" @update:show="value => open = value" preset="card"
    :title="`物料供需${entry ? ` · ${entry.row.sku}` : ''}`" class="material-supply-dialog"
    :style="{ width: 'min(860px, calc(100vw - 32px))', maxHeight: 'calc(100vh - 48px)' }">
    <section class="supply-detail">
      <div class="supply-toolbar"><p>全仓当前采购供需 · {{ entry?.row.name ?? '正在读取物料' }}<br />
        <span v-if="entry" class="muted">更新于 {{ store.localTime(entry.generatedAt) }} · 单位：{{ entry.row.unit }}</span></p>
        <AppButton type="button" :disabled="loading || connectionLost" @click="store.loadMaterialSupply(materialId, true)">刷新数值</AppButton></div>
      <p v-if="error" role="alert">{{ error }}</p>
      <p v-if="loading" role="status">正在读取当前供需…</p>
      <div v-if="entry" class="supply-cards">
        <div v-for="phase in materialSupplyPhases" :key="phase"><span>{{ materialSupplyLabels[phase] }}</span>
          <strong>{{ entry.row[`${phase}_quantity`] ?? '无权限' }}</strong></div>
      </div>
      <p class="supply-explanation">库存为账面结存；计划中为已生效的采购计划尚未正式下单部分；待回料为已采购未到货；待入库为合格已收货或已批准采购入库单尚未入库。生产待退料独立统计。预计数量不能直接当作可用库存。</p>
      <WorkspaceTable title="数值来源" :data="entry?.row.sources ?? []" :columns="columns" :loading="loading" :min-table-width="510"
        empty-text="没有正数量的采购来源或库存流水；无权限的阶段不返回来源。">
        <template #cell-phase="{row}">{{ materialSupplyLabels[row.phase] }}</template>
        <template #cell-source="{row}"><strong>{{ row.warehouse_name ?? `${materialSupplyKindLabels[row.kind]} · ${row.document_no ?? '#' + row.document_id}` }}</strong>
          <small v-if="row.reference">{{ row.reference }}</small></template>
      </WorkspaceTable>
    </section>
    <template #footer><AppButton type="button" @click="open = false">关闭</AppButton></template>
  </NModal>
</template>

<style scoped>
/* 两列四项让数据可快速扫描；使用已有主题变量保持明暗主题一致。 */
.material-supply-cell { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px 12px;
  width: 100%; padding: 9px 10px; text-align: left; font: inherit; color: inherit; cursor: pointer;
  border: 1px solid var(--workspace-field-border); border-radius: 9px; background: var(--app-modal-surface); }
.material-supply-cell:hover { border-color: var(--workspace-field-accent); }
.material-supply-cell:focus-visible { outline: 2px solid var(--workspace-field-accent); outline-offset: 2px; }
.material-supply-cell:disabled { cursor: default; opacity: .7; }
.supply-count { display: flex; justify-content: space-between; gap: 4px 8px; font-size: 12px; flex-wrap: wrap; white-space: normal; }
.supply-count > span, .supply-caption, .supply-placeholder { color: var(--workspace-field-muted); }
.supply-count strong { font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.supply-caption { grid-column: 1 / -1; font-size: 11px; }
.supply-detail { display: grid; gap: 14px; max-height: calc(100dvh - 220px); overflow-y: auto; }
.supply-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.supply-toolbar p, .supply-explanation { margin: 0; font-size: 12px; line-height: 1.7; }
.supply-explanation { color: var(--workspace-field-muted); }
.supply-cards { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.supply-cards > div { display: grid; gap: 8px; padding: 14px; border: 1px solid var(--workspace-field-border); border-radius: 10px; }
.supply-cards span { font-size: 12px; color: var(--workspace-field-muted); }
.supply-cards strong { font-size: 20px; overflow-wrap: anywhere; }
@media (max-width: 650px) { .supply-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
<style>
/* 嵌套来源弹窗使用独立滚动区，窄屏和长来源列表仍能关闭。 */
.n-modal.n-card.material-supply-dialog > .n-card-content { min-height: 0; overflow-y: auto; }
</style>
