<script setup lang="ts">
// 来源绑定在真实触发入口，键盘点击与鼠标点击共用同一回程位置。
import { captureDialogOrigin } from '../../../utils/dialog-origin'
import AppModal from '../../../components/app/AppModal.vue'
// 详情页脚按类型与 ID 双重定位，避免跨页面同号单据串单。
import { findDocumentApprovalItem } from "../../../utils/document-approval-item";
// 页面只展示服务端保存的单号，原内部 ID 继续用于业务操作。
import {
  documentSearch,
  documentLabel,
} from "../../../../../shared/document-numbering";
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from "../../../components/app/AppInput.vue";
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from "../../../components/app/AppButton.vue";
// 下拉选择统一使用工作台组件，业务值与切换回调保持原有类型。
import WorkspaceSelect from "../../../components/workspace/WorkspaceSelect.vue";
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
import { submitCreateDialog } from "../../../utils/create-dialog";

// 页面直接使用共享状态与操作，切换标签时不会丢失正在填写的草稿。
const store = usePiniaAppStore();
const {
  error,
  notice,
  version,
  busy,
  connectionLost,
  boms,
  workOrders,
  warehouses,
  workOrderForm,
} = storeToRefs(store);
const {
  can,
  localTime,
  createWorkOrder,
  releaseWorkOrder,
  cancelWorkOrder,
} = store;

// 保存失败时保留弹窗和草稿，方便直接修正后重试。
const createOpen = ref(false);
async function submitCreate(): Promise<void> {
  // 回车提交与按钮执行使用相同的连接、权限约束。
  if (busy.value || connectionLost.value || !can('work_order.create')) return;
  await submitCreateDialog(
    createWorkOrder,
    { busy, error, notice },
    createOpen,
  );
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
  <section class="stack">
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
    <AppModal :busy="busy" origin-key="ProductionWorkOrdersView:create" @invalidated="createOpen = false"
      title="新建生产工单"
      v-if="can('work_order.create')"
      v-model:show="createOpen"
      preset="card"
      :mask-closable="!busy"
      :style="{
        width: 'min(900px, calc(100vw - 32px))',
        maxHeight: 'calc(100vh - 48px)',
        overflowY: 'auto',
      }"
    >
      <!-- 状态保留在公共标题栏，正文不再重复显示标题。 -->
      <template #header-extra><span class="pill">草稿</span></template>
      <p class="muted">
        选择已启用的 BOM
        和目标产量。建单时会固定本次组件需求；仓库用于后续完工入库，目前不会改变库存。
      </p>
      <form @submit.prevent="submitCreate">
        <div class="form-grid">
          <label
            >启用的 BOM<WorkspaceSelect
              v-model="workOrderForm.bom_id"
              required
              :options="[
                { label: '选择成品与版本', value: 0, disabled: true },
                ...boms
                  .filter((entry) => entry.status === 'active')
                  .map((item) => ({
                    label: (
                      item.product_name +
                      '（' +
                      item.product_sku +
                      '）· V' +
                      item.version
                    ).trim(),
                    value: item.id,
                  })),
              ]" /></label
          ><label
            >完工目标仓库<WorkspaceSelect
              v-model="workOrderForm.warehouse_id"
              required
              :options="[
                ...warehouses.map((item) => ({
                  label: item.name,
                  value: item.id,
                })),
              ]" /></label
          ><label
            >目标产量<AppInput
              v-model.trim="workOrderForm.target_quantity"
              type="number"
              min="0.001"
              max="1000000"
              step="0.001"
              required /></label
          ><label
            >参考号（可选）<AppInput
              v-model.trim="workOrderForm.reference"
              maxlength="100" /></label
          ><label
            >备注（可选）<AppInput
              v-model.trim="workOrderForm.note"
              maxlength="200"
          /></label>
        </div>
        <AppButton
          type="submit"
          :disabled="
            busy ||
            connectionLost ||
            !boms.some((item) => item.status === 'active') ||
            !warehouses.length
          "
          variant="primary"
        >
          保存工单草稿
        </AppButton>
      </form>
    </AppModal>
    <WorkspaceSummaryFilters v-model="recordFilters.status" :options="recordSummaries" hint="按搜索与仓库统计全部匹配单据 · 点击筛选状态" />
    <!-- 主标题由工作台提供，列表复用仓库管理的筛选区、状态和单元格布局。 -->
    <WorkspaceTable
      :show-title="false"
      title="生产工单"
      :data="filteredRecords"
      :columns="columns"
      :min-table-width="1100"
    >
      <template #actions>
        <AppButton
          v-if="can('work_order.create')"
          type="button"
          :disabled="busy || connectionLost"
          @click.capture="captureDialogOrigin('ProductionWorkOrdersView:create', $event)" @click="createOpen = true"
          variant="primary"
        >
          新建生产工单
        </AppButton>
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
