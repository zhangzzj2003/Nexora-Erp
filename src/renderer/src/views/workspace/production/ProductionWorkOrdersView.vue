<script setup lang="ts">
// 来源绑定在真实触发入口，键盘点击与鼠标点击共用同一回程位置。
import { captureDialogOrigin } from '../../../utils/dialog-origin'
// 详情页脚按类型与 ID 双重定位，避免跨页面同号单据串单。
import { findDocumentApprovalItem } from "../../../utils/document-approval-item";
// 页面只展示服务端保存的单号，原内部 ID 继续用于业务操作。
import {
  documentSearch,
  documentLabel,
} from "../../../../../shared/document-numbering";
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from "../../../components/app/AppButton.vue";
import WorkspaceTable from "../../../components/workspace/WorkspaceTable.vue";
import ProductionAssociationDialog from "../../../components/workspace/ProductionAssociationDialog.vue";
import DocumentApprovalDialog from "../../../components/workspace/DocumentApprovalDialog.vue";
// 生产列表沿用仓库管理的概览、搜索和仓库筛选，数量统计覆盖全部匹配记录。
import WorkspaceSummaryFilters from '../../../components/workspace/WorkspaceSummaryFilters.vue';
import WorkspaceSearchFilters from '../../../components/workspace/WorkspaceSearchFilters.vue';
import { useProductionRecords } from '../../../composables/use-production-records';
import type { WorkspaceTableColumn } from "../../../utils/table-columns";
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from 'vue-router';
import { routeByKey } from '../../../router/workspace-routes';
// 首屏物料区必须同步注册加载屏障，避免父弹窗展开后才插入正文。
import WorkOrderMaterialFlowPanel from '../../../components/workspace/WorkOrderMaterialFlowPanel.vue';
import { storeToRefs } from "pinia";
import { usePiniaAppStore } from "../../../store/app-store";

// 页面复用共享工单与操作，来源跳转不改变已有单据。
import ProductionDemandDialog from './ProductionDemandDialog.vue';
import { groupProductionDemands } from './production-demand-groups';

const store = usePiniaAppStore();
const {
  busy,
  connectionLost,
  workOrders, productionPlanDemands, productionPlanDemandReady, productionPlanDemandError,
} = storeToRefs(store);
const {
  can,
  localTime,
  releaseWorkOrder,
  cancelWorkOrder,
} = store;

// 角标表示机型种数，不混加不同产品的件数；读取失败保留明确的待核对提示。
const showDemands = ref(false);
const demandCount = computed(() => groupProductionDemands(productionPlanDemands.value).length);
async function openDemands(): Promise<void> {
  if (busy.value || connectionLost.value || !can('production_plan.view')) return;
  showDemands.value = true;
  await store.loadProductionPlanDemands();
}
watch([() => `${store.server?.id}:${store.server?.fingerprint}:${store.user?.id}:${store.user?.permissions.join('|')}`,
  connectionLost, () => store.activeTab, workOrders], () => {
  if (connectionLost.value || !can('production_plan.view')) { showDemands.value = false; return; }
  if (store.activeTab === 'workOrders') void store.loadProductionPlanDemands();
}, { immediate: true });
// 普通工单只能从批准计划生成；此页面专注执行与追溯，不再提供产品和数量自由输入。
async function openPlans(id?: number): Promise<void> {
  if (busy.value || connectionLost.value || !can('production_plan.view')) return;
  showDemands.value = false; store.closeDocumentApproval();
  await router.push({ path: routeByKey('productionPlans').path, query: id ? { document_id: id } : {} });
}
const { recordQuery, recordFilters, recordSummaries, recordFilterFields, filteredRecords, resetRecordFilters } = useProductionRecords(
  workOrders, [
    { key: 'draft', label: '待下达', statuses: ['draft'], tone: 'pending' },
    { key: 'active', label: '待完工', statuses: ['released', 'in_progress'], tone: 'pending' },
    { key: 'completed', label: '已完工', statuses: ['completed'], tone: 'success' },
    { key: 'cancelled', label: '已取消', statuses: ['cancelled'], tone: 'neutral' },
  ],
  item => [documentSearch(item), item.id, item.product_name, item.product_sku, item.warehouse_name,
    item.created_by_name, item.reference, ...item.lines.flatMap(line => [line.sku, line.material_name])],
);
// 详情弹窗由审批目标驱动；页脚业务按钮按当前单据与意图（执行/冲销）展示。
const detailItem = computed(() =>
  findDocumentApprovalItem(store.documentApprovalTarget, "WorkOrder", workOrders.value),
);
const detailIntent = computed(
  () => store.documentApprovalTarget?.intent ?? "execute",
);
// 操作列只保留查看入口，业务按钮统一移入详情页脚。
const columns: readonly WorkspaceTableColumn[] = [
  { key: "document", title: "单据", width: "28%" },
  { key: "status", title: "状态", width: "120" },
  { key: "details", title: "业务明细" },
  { key: "actions", title: "查看", width: "72", align: "center" },
];
// 审批状态独立于下达、质检和库存执行状态，避免上游批准被误认为本单批准。
const approvalLabels = {
  draft: "未送审",
  submitted: "审批中",
  approved: "已批准，待确认",
  rejected: "已驳回",
  withdrawn: "已撤回",
  executed: "已执行",
};
// 仓库单据返回工单时直接打开对应详情，避免再次搜索同一工单。
const route = useRoute();
const router = useRouter();
// 完工建单携带明确的一次性意图，先关闭工单详情，避免新页面仍显示旧审批弹窗。
async function openCompletions(create = false): Promise<void> {
  const order = detailItem.value;
  if (!order || busy.value || connectionLost.value || !can('production.view')) return;
  if (create && (order.status !== 'in_progress' || Number(order.remaining_output_quantity) <= 0 || !can('production_completion.create'))) return;
  store.closeDocumentApproval();
  await router.push({ path: routeByKey('productionCompletions').path,
    query: { work_order_id: order.id, ...(create ? { create_from_order: order.id } : {}) } });
}
// 仅监听稳定的字段值；审批刷新会替换账号和工单数组，不能因此反复重新打开详情。
watch([() => route?.query.document_id, () => store.user?.id, () => workOrders.value.length], () => {
  const id = Number(route?.query.document_id);
  const target = store.documentApprovalTarget;
  if (target?.document_type === 'WorkOrder' && target.document_id === id) return;
  if (id > 0 && workOrders.value.some(item => item.id === id) && store.activeTab === 'workOrders')
    void store.openDocumentApproval({ document_type: 'WorkOrder', document_id: id, intent: 'execute' });
}, { immediate: true });
</script>

<template>
  <section class="stack production-work-orders">
    <!-- 业务操作统一在详情页脚办理；审批控件与关闭由公共弹窗承载。 -->
    <DocumentApprovalDialog origin-key="document-approval">
      <WorkOrderMaterialFlowPanel v-if="detailItem && detailIntent === 'execute' && can('material_flow.view')" :order-id="detailItem.id" />
      <template #footerActions>
        <!-- 操作色表达业务含义：冲销红色、取消橙色、确认绿色、查看与编辑蓝色。 -->
        <template v-if="detailItem">
          <AppButton
            tone="info"
            v-if="detailIntent === 'execute'"
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click.capture="captureDialogOrigin('production-association', $event)" @click="
              store.openProductionAssociations({
                kind: 'work_order',
                id: detailItem.id,
              })
            "
            >关联单据</AppButton
          >
          <AppButton
            tone="success"
            v-if="
              detailIntent === 'execute' &&
              detailItem.status === 'draft' &&
              detailItem.approval?.status === 'approved' &&
              can('work_order.release')
            "
            type="button"
            variant="primary"
            :disabled="busy || connectionLost"
            @click="releaseWorkOrder(detailItem.id)"
            >下达</AppButton
          >
          <AppButton
            tone="info"
            v-if="
              detailIntent === 'execute' &&
              detailItem.status === 'in_progress' &&
              Number(detailItem.remaining_output_quantity) > 0 &&
              can('production_completion.create')
            "
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click="openCompletions(true)"
            >创建完工单</AppButton
          >
          <AppButton v-if="detailIntent === 'execute' && can('production.view')" tone="info"
            :disabled="busy || connectionLost" @click="openCompletions()">查看完工记录</AppButton>
          <AppButton
            tone="warning"
            v-if="
              detailIntent === 'execute' &&
              (detailItem.status === 'draft' ||
                detailItem.status === 'released') &&
              !['submitted', 'approved'].includes(
                detailItem.approval?.status ?? '',
              ) &&
              !detailItem.rework_disposition_id &&
              can('work_order.cancel')
            "
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click="cancelWorkOrder(detailItem.id)"
            >取消</AppButton
          >
        </template>
      </template>
    </DocumentApprovalDialog>
    <ProductionAssociationDialog origin-key="production-association" />
    <ProductionDemandDialog v-model:show="showDemands" @view-plan="openPlans" />
    <p class="muted">普通生产工单由已批准的生产计划分批生成；返工工单由已审批的不合格品处置生成。</p>
    <!-- 统计统一进入页面标题右侧，与其他入库保持相同位置。 -->
    <Teleport to="#workspace-page-summary" defer>
      <WorkspaceSummaryFilters v-model="recordFilters.status" :options="recordSummaries" hint="" />
    </Teleport>
    <!-- 主标题由工作台提供，列表复用仓库管理的筛选区、状态和单元格布局。 -->
    <WorkspaceTable
      :show-title="false"
      title="生产工单"
      :data="filteredRecords"
      :columns="columns"
      :min-table-width="1100"
    >
      <template #actions>
        <span v-if="can('production_plan.view')" class="production-demand-entry">
          <AppButton type="button" :disabled="busy || connectionLost" variant="primary"
            :aria-label="`从生产计划生成${productionPlanDemandReady ? `，${demandCount} 种机型待生成` : '，待生产数量待核对'}`"
            @click.capture="captureDialogOrigin('production-demands', $event)" @click="openDemands">从生产计划生成</AppButton>
          <span v-if="productionPlanDemandReady && demandCount > 0" class="production-demand-badge" aria-hidden="true" :title="`${demandCount} 种机型待生成工单`">{{ demandCount > 99 ? '99+' : demandCount }}</span>
          <span v-else-if="productionPlanDemandError" class="production-demand-badge" aria-hidden="true" title="待生产需求读取失败，点击刷新核对">!</span>
        </span>
      </template>
      <template #filters>
        <WorkspaceSearchFilters v-model:query="recordQuery" v-model:filters="recordFilters" :fields="recordFilterFields"
          search-label="搜索生产工单" search-placeholder="单号、工单、产品或物料" @reset="resetRecordFilters" />
      </template>

      <template #cell-document="{ row: item }">
        <div>
          <strong>
            <!-- 单号直接打开只读详情，与操作列「查看」并存两个入口。 -->
            <AppButton
              type="button"
              variant="text"
              :disabled="busy || connectionLost"
              :aria-label="`查看单据 ${documentLabel(item)} 详情`"
              @click.capture="captureDialogOrigin('document-approval', $event)" @click="
                store.openDocumentApproval({
                  document_type: 'WorkOrder',
                  document_id: item.id,
                  intent: 'execute',
                })
              "
              >{{ documentLabel(item) }}</AppButton
            >
            · {{ item.product_name }}（{{ item.product_sku }}）· BOM V{{
              item.bom_version
            }}
          </strong>
          <p class="muted">
            {{ localTime(item.created_at) }} · 创建人
            {{ item.created_by_name }} · 目标 {{ item.target_quantity }}
            {{ item.product_unit }} · {{ item.warehouse_name }}
            <span v-if="item.reference">· {{ item.reference }}</span>
            <span v-if="item.note">· {{ item.note }}</span>
          </p>
        </div>
      </template>
      <template #cell-status="{ row: item }">
        <span class="pill" :class="item.status">
          {{
            {
              draft: approvalLabels[item.approval?.status ?? "draft"],
              released: "已下达",
              in_progress: "生产中",
              completed: "已完工",
              cancelled: "已取消",
            }[item.status]
          }}
        </span>
      </template>
      <template #cell-details="{ row: item }">
        <div class="workspace-record-lines">
          <span v-if="item.production_schedule">生产计划
            <AppButton v-if="can('production_plan.view')" variant="text" size="small" :disabled="busy || connectionLost"
              @click="openPlans(item.production_schedule.production_plan_id)">{{ item.production_schedule.production_plan_document_no || '#' + item.production_schedule.production_plan_id }}</AppButton>
            <span v-else>{{ item.production_schedule.production_plan_document_no || '#' + item.production_schedule.production_plan_id }}</span>
            · {{ item.production_schedule.start_date }} 至 {{ item.production_schedule.end_date }}
          </span>
          <span v-if="item.production_schedule?.production_requirements" class="production-requirements">生产要求：{{ item.production_schedule.production_requirements }}</span>
          <span v-if="!item.production_schedule && !item.rework_disposition_id" class="muted">历史工单（无生产计划关联）</span>
          <span v-if="item.rework_disposition_id"
            >返工来源 {{ item.rework_reference }} · 原完工 #{{
              item.rework_completion_id
            }}。<RouterLink
              v-if="can('quality.view')"
              to="/workspace/production-quality"
              >查看处置证据</RouterLink
            ></span
          >
          <span>
            已报工 {{ item.reported_quantity }} · 合格
            {{ item.accepted_quantity }} · 不合格 {{ item.rejected_quantity }} ·
            待报工 {{ item.remaining_output_quantity }}
            {{ item.product_unit }}
          </span>
          <span v-for="line in item.lines" :key="line.id">
            <!-- 这是累计材料口径，包含已经报工的耗用，不能标成尚未使用的剩余量。 -->
            {{ line.material_name }} · 需求 {{ line.required_quantity }} · 有效领用
            {{ line.issued_quantity }} · 已发未签 {{ line.in_transit_quantity ?? '0' }} · 待发 {{ line.pending_dispatch_quantity ?? '—' }} · 待安排 {{ line.remaining_quantity }}
            {{ line.unit }}
            <small v-if="Number(line.reserved_quantity ?? 0) > 0 || Number(line.damaged_quantity ?? 0) > 0" class="muted">
              待退换预留 {{ line.reserved_quantity ?? '0' }} · 已确认损坏 {{ line.damaged_quantity ?? '0' }} {{ line.unit }}
            </small>
          </span>
        </div>
      </template>
      <template #cell-actions="{ row: item }">
        <!-- 行内只保留查看入口，业务操作统一移入详情页脚。 -->
        <AppButton
          type="button"
          variant="secondary"
          size="small"
          :disabled="busy || connectionLost"
          :aria-label="`查看单据 ${documentLabel(item)} 详情`"
          @click.capture="captureDialogOrigin('document-approval', $event)" @click="
            store.openDocumentApproval({
              document_type: 'WorkOrder',
              document_id: item.id,
              intent: 'execute',
            })
          "
          >查看</AppButton
        >
      </template>
      <template #empty>
        <strong>{{
          (recordQuery || recordFilters.status || recordFilters.warehouse) ? "没有匹配的记录" : "暂无生产工单记录"
        }}</strong>
        <span>
          {{
            (recordQuery || recordFilters.status || recordFilters.warehouse)
              ? "可调整关键词、状态或仓库后重新搜索。"
              : "业务记录生成后，可在这里查看明细与处理状态。"
          }}
        </span>
      </template>
    </WorkspaceTable>
  </section>
</template>

<style scoped>
/* 本页移除概览说明后收紧卡片与列表间距，其他业务页面继续使用公共间距。 */
.production-work-orders { gap: 12px; }
/* 角标固定在入口右上角，数字和无障碍名称同时表达待生产数量。 */
.production-demand-entry { position: relative; display: inline-flex; }
.production-demand-badge { position: absolute; right: -8px; top: -9px; min-width: 22px; height: 22px; padding: 0 5px; border-radius: 11px; display: flex; justify-content: center; align-items: center; background: var(--danger, #bd414a); color: white; font-size: 12px; font-weight: 700; pointer-events: none; }
.production-requirements { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
