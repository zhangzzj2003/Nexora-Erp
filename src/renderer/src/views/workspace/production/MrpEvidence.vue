<script setup lang="ts">
// 页面只展示服务端保存的单号，原内部 ID 继续用于业务操作。
import { documentLabel, relatedDocumentLabel } from '../../../../../shared/document-numbering'
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { NCollapse } from 'naive-ui'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { movementTypeLabel } from '../../../utils/formatters'
import type { MrpRow, MrpSuggestion } from '../../../../../shared/mrp-api'
import { mrpMode, mrpSourceLabel, mrpStatus, mrpCanConvert } from './mrp-display'
const store = usePiniaAppStore()
const { mrpDetail: item, mrpCheck: check, mrpChanges: changes, busy, connectionLost, user } = storeToRefs(store)
const emit = defineEmits<{ convert: [suggestion: MrpSuggestion] }>()
const query = ref(''); const source = ref<MrpRow | null>(null)
watch(item, () => { source.value = null })
const rows = computed(() => (item.value?.snapshot.rows ?? []).filter(row => `${row.sku} ${row.name} ${row.date}`.toLowerCase().includes(query.value.toLowerCase().trim())))
const columns = [{key:'material',title:'物料 / 日期',width:'220'}, {key:'opening_quantity',title:'期初'}, {key:'gross_quantity',title:'毛需求'},
  {key:'scheduled_quantity',title:'预计供给'}, {key:'net_quantity',title:'净缺口'}, {key:'planned_quantity',title:'建议数量'},
  {key:'closing_quantity',title:'预计结余'}, {key:'actions',title:'核对',width:'100'}]
const suggestions = [{key:'material',title:'物料 / 方式',width:'210'}, {key:'quantity',title:'建议数量',width:'140'},
  {key:'due_date',title:'需求日',width:'140'}, {key:'release',title:'投放日 / 交期风险',width:'260'}, {key:'actions',title:'原单草稿',width:'250'}]
const movements = computed(() => item.value?.snapshot.sources.movements.filter(row => row.material_id === source.value?.material_id) ?? [])
const materialPolicy = computed(() => item.value?.snapshot.sources.policies.find(row => row.material_id === source.value?.material_id))
const materialBom = computed(() => item.value?.snapshot.sources.boms.find(row => row.product_material_id === source.value?.material_id))
const conversions = (key: string) => item.value?.conversions.find(row => row.suggestion_key === key)
const canConvert = (row: MrpSuggestion) => mrpCanConvert(item.value, check.value, row, user.value?.permissions ?? [])
const actionName = (action?: string) => ({create:'建立计划',submit:'提交审核',approve:'批准',reject:'驳回',cancel:'取消',convert:'建议转单'})[action ?? ''] ?? action
</script>
<template>
  <section v-if="item" class="stack">
    <div class="card mrp-panel">
      <div class="mrp-toolbar"><h2>{{ documentLabel(item) }} · {{ item.reference }} · 固定计划</h2><AppButton :disabled="connectionLost" @click="store.exportMrp()">导出固定 CSV</AppButton><AppButton @click="store.clearMrpDetail()">关闭结果</AppButton></div>
      <p>{{ mrpStatus[item.status] }} · v{{ item.version }} · {{ item.created_by_name }} · 计划起日 {{ item.start_date }} · 计算于 {{ store.localTime(item.snapshot.captured_at) }}</p>
      <p v-if="!check?.matched" role="alert">当前来源已变化或计划已过期，旧结果保留供追溯。请回到需求编排重新读取并新建计算；此结果不能提交、批准或转单。</p>
      <p v-else role="status">当前库存、来源、BOM 与参数仍匹配。每次提交、批准及转单都会再次核对。</p>
      <NCollapse :default-expanded-names="item.snapshot.warnings.length ? ['warnings'] : []"><AppCollapseItem name="warnings" :title="`计算警告（${item.snapshot.warnings.length}）与使用口径`">
        <ul><li v-for="(warning,index) in item.snapshot.warnings" :key="index">{{ warning }}</li></ul>
        <ul><li v-for="text in item.snapshot.assumptions" :key="text">{{ text }}</li></ul>
      </AppCollapseItem></NCollapse>
    </div>
    <WorkspaceTable title="采购与生产建议" :columns="suggestions" :data="item.snapshot.suggestions" :min-table-width="1050">
      <template #cell-material="{ row }">{{ row.sku }} · {{ row.name }}<span class="muted mrp-line">{{ mrpMode[row.supply_mode] }} · {{ row.unit }}<template v-if="row.bom_id"> · BOM #{{ row.bom_id }} v{{ row.bom_version }}</template></span></template>
      <template #cell-release="{ row }">{{ row.release_date }}<span v-if="row.late" class="mrp-line">提前期不足：应在 {{ row.required_release_date }} 投放</span></template>
      <template #cell-actions="{ row }">
        <template v-if="conversions(row.key)"><span>{{ conversions(row.key)!.purchase_request_id ? '采购申请' : '工单' }} {{ relatedDocumentLabel(conversions(row.key)!, conversions(row.key)!.purchase_request_id ? 'purchase_request' : 'work_order') }} · {{ conversions(row.key)!.target_reference }}</span>
          <span class="muted mrp-line">{{ conversions(row.key)!.target_status === 'cancelled' ? '原单已取消，须新建计划' : '已转原单，按原单流程执行' }}</span>
          <AppButton v-if="store.can(conversions(row.key)!.purchase_request_id ? 'purchase_request.view' : 'production.view')" size="small" @click="store.navigateToRoute(conversions(row.key)!.purchase_request_id ? 'purchaseRequests' : 'workOrders')">打开原单列表</AppButton>
        </template>
        <AppButton v-else-if="canConvert(row)" size="small" variant="primary" :disabled="busy || connectionLost" @click="emit('convert',row)">{{ row.supply_mode === 'buy' ? '转采购申请' : '转生产工单' }}</AppButton>
        <span v-else class="muted">{{ item.status !== 'approved' || !['approved', 'executed'].includes(item.approval?.status ?? '') ? '须完成本单独立审批' : !check?.matched ? '须新建重算' : '缺少计划或原单建单权限' }}</span>
      </template>
      <template #empty>没有净缺口，不需要新增采购或生产供给。</template>
    </WorkspaceTable>
    <WorkspaceTable title="日期净需求" :columns="columns" :data="rows" :min-table-width="1050">
      <template #filters><label>搜索物料 / 日期<AppInput v-model="query" placeholder="编码、名称或 YYYY-MM-DD" /></label></template>
      <template #cell-material="{ row }">{{ row.sku }} · {{ row.name }}<span class="muted mrp-line">{{ row.date }} · {{ row.unit }} · 低层码 {{ row.level }}</span></template>
      <template #cell-actions="{ row }"><AppButton size="small" @click="source=row">来源核对</AppButton></template>
      <template #empty>{{ query ? '没有匹配的日期行。' : '没有需求、供给或安全库存补足任务。' }}</template>
    </WorkspaceTable>
    <section v-if="source" class="mrp-panel">
      <div class="mrp-toolbar"><h3>{{ source.sku }} · {{ source.name }} · {{ source.date }} 来源</h3><AppButton @click="source=null">关闭来源</AppButton></div>
      <p>期初 {{ source.opening_quantity }} ＋预计供给 {{ source.scheduled_quantity }} ＋建议 {{ source.planned_quantity }} −毛需求 {{ source.gross_quantity }} ＝预计结余 {{ source.closing_quantity }}。安全库存 {{ source.safety_stock }}。</p>
      <h4>该日需求与供给</h4>
      <ul><li v-for="row in source.demand_sources" :key="row.key">需求 {{ mrpSourceLabel(row) }} · {{ row.quantity }}<template v-if="row.bom_id"> · BOM #{{ row.bom_id }} v{{ row.bom_version }}</template></li>
        <li v-for="row in source.supply_sources" :key="row.key">供给 {{ mrpSourceLabel(row) }} · {{ row.quantity }} · 安排日 {{ row.scheduled_date }}</li></ul>
      <h4>计算时参数与 BOM</h4><p v-if="materialPolicy">{{ mrpMode[materialPolicy.supply_mode] }} · 参数 v{{ materialPolicy.version }} · 提前期 {{ materialPolicy.lead_time_days }} 日 · 安全库存 {{ materialPolicy.safety_stock }} · 最小批量 {{ materialPolicy.minimum_quantity }} · 倍数 {{ materialPolicy.multiple_quantity }}</p>
      <p v-if="materialBom">BOM {{ documentLabel(materialBom) }} v{{ materialBom.version }} · 基数 {{ materialBom.base_quantity }}</p>
      <ul v-if="materialBom"><li v-for="line in materialBom.lines" :key="line.id">{{ item.snapshot.sources.materials.find(row=>row.id===line.component_material_id)?.name }} · {{ line.quantity }}</li></ul>
      <WorkspaceTable title="计算时库存流水（全部仓库）" :columns="[{key:'id',title:'流水'}, {key:'warehouse_id',title:'仓库编号'}, {key:'quantity',title:'数量'}, {key:'source_type',title:'来源类型'}, {key:'source_id',title:'原单编号'}, {key:'created_at',title:'记入时间'}]" :data="movements" :min-table-width="800">
        <template #cell-source_type="{ row }">{{ movementTypeLabel(row.source_type) }}</template>
        <template #cell-created_at="{ row }">{{ store.localTime(row.created_at) }}</template>
        <template #empty>该物料没有库存流水，计算起日库存为 0。</template>
      </WorkspaceTable>
    </section>
    <section class="card mrp-panel"><h3>计划审计与转单依据</h3>
      <p class="mrp-fingerprint">来源指纹 {{ item.fingerprint }}</p>
      <NCollapse><AppCollapseItem v-for="change in changes" :key="change.id" :name="String(change.id)" :title="`${store.localTime(change.created_at)} · ${change.changed_by_name} · ${actionName(change.action)} · ${change.reason}`">
        <p>{{ change.before ? mrpStatus[change.before.status] + ' v' + change.before.version : '无原计划' }} → {{ mrpStatus[change.after.status] }} v{{ change.after.version }} · 累计转单 {{ change.after.conversions.length }} 条</p>
      </AppCollapseItem></NCollapse>
      <p v-for="conversion in item.conversions" :key="conversion.id">{{ conversion.suggestion_key }} → {{ conversion.purchase_request_id ? '采购申请' : '工单' }} {{ relatedDocumentLabel(conversion, conversion.purchase_request_id ? 'purchase_request' : 'work_order') }} · {{ conversion.created_by_name }} · {{ store.localTime(conversion.created_at) }} · {{ conversion.reason }}</p>
    </section>
  </section>
</template>
