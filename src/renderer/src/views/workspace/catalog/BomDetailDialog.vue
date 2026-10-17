<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import { usePiniaAppStore } from '../../../store/app-store'
import WorkspaceDocumentDialog from '../../../components/workspace/WorkspaceDocumentDialog.vue'
import AppButton from '../../../components/app/AppButton.vue'
import WorkspaceMaterialParameters from '../../../components/workspace/WorkspaceMaterialParameters.vue'
import { materialParameterIndex, materialParameterSource } from '../../../utils/material-parameter-source'
const store = usePiniaAppStore(), router = useRouter()
const {bomDetailRecord: record, bomDetailLoading, bomDetailError, busy, connectionLost, materials, materialCategories} = storeToRefs(store)
const materialById = computed(() => materialParameterIndex(materials.value))
const show = computed(() => !!record.value || bomDetailLoading.value || !!bomDetailError.value)
const columns = [{key:'sku',title:'组件编码',width:'200'}, {key:'name',title:'组件名称'}, {key:'quantity',title:'基准用量',width:'150'}, {key:'unit',title:'单位',width:'80'}, {key:'recipe',title:'下层生产配方',width:'170'}]
async function createOrder(): Promise<void> {
  // 只传递一次性建单意图，实际保存和需求快照仍由原工单流程校验。
  if (!record.value || record.value.status !== 'active' || record.value.product_can_produce === false || busy.value || connectionLost.value || !store.can('work_order.create')) return
  const id = record.value.id
  store.closeBomDetail(); store.closeProduct()
  await router.push({path:'/workspace/work-orders', query:{create_from_bom:id}})
}
</script>
<template>
  <WorkspaceDocumentDialog :show="show" read-only title="BOM 版本详情" :data="record?.lines ?? []" :columns="columns"
    :ready="!bomDetailLoading" :load-error="bomDetailError" :busy="busy" @update:show="!$event && store.closeBomDetail()" @invalidated="store.closeBomDetail">
    <template #basicInfo>
      <div class="document-detail-field"><span>产品</span><strong>{{ record?.product_name }}（{{ record?.product_sku }}）</strong></div>
      <div class="document-detail-field"><span>版本 / 状态</span><strong>V{{ record?.version }} · {{ {draft:'草稿',active:'已启用',retired:'已停用',cancelled:'已取消'}[record?.status ?? 'draft'] }}</strong></div>
      <div class="document-detail-field"><span>基准产出</span><strong>{{ record?.base_quantity }} {{ record?.product_unit }}</strong></div>
      <div class="document-detail-field"><span>版本说明</span><strong>{{ record?.note || '—' }}</strong></div>
      <div class="document-detail-field"><span>来源版本</span>
        <AppButton v-if="record?.source_bom" :disabled="busy || connectionLost" @click="store.openBomDetail(record.source_bom.id)">{{ record.source_bom.product_name }} · V{{ record.source_bom.version }}</AppButton><strong v-else>独立创建</strong>
      </div>
    </template>
    <template #cell-sku="{row}">{{ row.sku }}</template><template #cell-name="{row}"><strong>{{ row.material_name }}</strong><WorkspaceMaterialParameters :material="materialParameterSource(row.component_material_id,row.material,materialById)" :categories="materialCategories" current-reference /></template>
    <template #cell-quantity="{row}">{{ row.quantity }}</template><template #cell-unit="{row}">{{ row.unit }}</template>
    <template #cell-recipe="{row}"><AppButton v-if="row.component_bom_id" size="small" :disabled="busy || connectionLost" @click="store.openBomDetail(row.component_bom_id)">固定 V{{ row.component_bom_version }}</AppButton><span v-else>按物料领用</span></template>
    <template #footer><div class="form-actions">
      <AppButton v-if="record?.status === 'active' && store.can('work_order.create')" :disabled="busy || connectionLost || record?.product_can_produce === false" variant="primary" @click="createOrder">创建生产工单</AppButton>
      <AppButton :disabled="busy" @click="store.closeBomDetail">关闭</AppButton>
    </div></template>
  </WorkspaceDocumentDialog>
</template>
