<script setup lang="ts">
import {ref, watch} from 'vue'
import {NCollapse} from 'naive-ui'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
import type {SalesDraftChange, SalesDraftType} from '../../../../../shared/sales-draft-api'
import AppModal from '../../../components/app/AppModal.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import {usePiniaAppStore} from '../../../store/app-store'
import {displayError} from '../../../utils/formatters'
const target = defineModel<{type:SalesDraftType; id:number} | null>({required:true})
const store = usePiniaAppStore(), rows = ref<SalesDraftChange[]>([]), loading = ref(false), error = ref('')
let ticket = 0
const columns = [{key:'material',title:'物料',width:'260'}, {key:'quantity',title:'数量',width:'120'},
  {key:'price',title:'单价 / 保修条款',width:'260'}]
watch(target, async current => {
  const owner = ++ticket
  rows.value = []; error.value = ''; loading.value = !!current
  if (!current) return
  try {
    const result = await store.loadSalesDraftChanges(current.type, current.id)
    if (owner === ticket) rows.value = result
  } catch (cause) { if (owner === ticket) error.value = displayError(cause) }
  finally { if (owner === ticket) loading.value = false }
}, {immediate:true})
</script>
<template>
  <!-- 修订内容默认折叠，保留完整前后证据但不挤占日常单据详情。 -->
  <AppModal preset="card" title="草稿修订记录" :show="!!target" :ready="!loading" :load-error="error" :style="{width:'min(1050px, calc(100vw - 32px))',maxHeight:'calc(100vh - 48px)',overflowY:'auto'}"
    @update:show="value=>{if(!value)target=null}" @invalidated="target=null">
    <p v-if="!rows.length && !loading && !error" class="muted">暂无草稿修订记录。</p>
    <NCollapse>
    <AppCollapseItem v-for="row in rows" :key="row.id" :name="row.id"
      :title="`第 ${row.version} 次修订 · ${row.changed_by_name} · ${store.localTime(row.created_at)} · ${row.reason}`">
      <section v-for="part in (['before','after'] as const)" :key="part">
        <h3>{{ part === 'before' ? '修改前' : '修改后' }}</h3>
        <p>{{ row[part].customer_name }} {{ row[part].warehouse_name }} {{ row[part].reference || row[part].reason }}</p>
        <p v-if="row[part].sales_order_document_no">销售订单 {{ row[part].sales_order_document_no }}</p>
        <p v-if="row[part].shipment_document_no">原出库单 {{ row[part].shipment_document_no }}</p>
        <WorkspaceTable :data="row[part].lines" :columns="columns" title="物料明细" row-key="id" :show-title="false">
          <template #cell-material="{row:line}">{{ line.sku }} · {{ line.material_name }}</template>
          <template #cell-quantity="{row:line}">{{ line.quantity }} {{ line.unit }}</template>
          <template #cell-price="{row:line}">{{ line.unit_price === undefined ? '—' : `¥${line.unit_price}` }}<span v-if="line.warranty_days"> · {{ line.warranty_days }} 天 · {{ line.warranty_basis }}</span></template>
        </WorkspaceTable>
      </section>
    </AppCollapseItem>
    </NCollapse>
  </AppModal>
</template>
