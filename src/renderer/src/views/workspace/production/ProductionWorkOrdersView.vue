<script setup lang="ts">
// 来源绑定在真实触发入口，键盘点击与鼠标点击共用同一回程位置。
import { captureDialogOrigin } from '../../../utils/dialog-origin'
// 新建工单直接复用仓库管理的单据外壳与产品资料选择器。
import WorkspaceDocumentDialog from '../../../components/workspace/WorkspaceDocumentDialog.vue'
import WorkspaceMaterialSelect from '../../../components/workspace/WorkspaceMaterialSelect.vue'
import type { MaterialChoice } from '../../../../../shared/material-api'
import { receiptLotMilli } from '../../../../../shared/receipt-lot-api'
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
  materials,
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
  if (productIssue.value) { error.value = productIssue.value; return; }
  await submitCreateDialog(
    createWorkOrder,
    { busy, error, notice },
    createOpen,
  );
}
// 单张工单固定一个产品及一个 BOM 版本；产品与版本均从 Pinia 草稿反推，收起后不会丢失。
const activeBoms = computed(() => boms.value.filter(item => item.status === 'active' && item.product_can_produce !== false)
  .sort((left, right) => right.version - left.version || right.id - left.id));
const selectedBom = computed(() => boms.value.find(item => item.id === workOrderForm.value.bom_id));
const productId = computed({
  get: () => selectedBom.value?.product_material_id ?? 0,
  set: (id: number) => {
    if (busy.value || connectionLost.value || !can('work_order.create')) return;
    // 同一产品保留已选版本；切换产品默认使用最新启用版本，不带入另一产品的 BOM。
    if (selectedBom.value?.status === 'active' && selectedBom.value.product_can_produce !== false && selectedBom.value.product_material_id === id) return;
    workOrderForm.value.bom_id = activeBoms.value.find(item => item.product_material_id === id)?.id ?? 0;
  },
});
const productChoices = computed<MaterialChoice[]>(() => {
  const seen = new Set<number>();
  return activeBoms.value.flatMap(bom => {
    if (seen.has(bom.product_material_id)) return [];
    seen.add(bom.product_material_id);
    // 生产权限可取得 BOM 简要产品信息；没有完整物料档案时仍能正常选择产品。
    return [materials.value.find(item => item.id === bom.product_material_id) ?? {
      id: bom.product_material_id, sku: bom.product_sku, name: bom.product_name, unit: bom.product_unit,
    }];
  });
});
const productBomOptions = computed(() => activeBoms.value
  .filter(item => item.product_material_id === productId.value)
  .map(item => ({ value: item.id, label: `V${item.version} · 基准 ${item.base_quantity} ${item.product_unit}` })));
// 默认使用仓库选择器的资料摘要，常用桌面高度下可同时看到数量和保存按钮。
const productCompact = ref(true);
const productRows = computed(() => [{ form: workOrderForm.value, bom: selectedBom.value }]);
const productColumns: readonly WorkspaceTableColumn[] = [
  { key: 'sku', title: '产品编码', width: '170' },
  { key: 'product', title: '生产产品 / 资料', width: '380' },
  { key: 'bom', title: '启用的 BOM 版本', width: '230' },
  { key: 'unit', title: '单位', width: '70', align: 'center' },
  { key: 'quantity', title: '目标产量', width: '150' },
];
const productIssue = computed(() => {
  if (selectedBom.value?.product_can_produce === false) return '此子机型已停用或删除，请选择可生产的子机型。';
  if (!activeBoms.value.length) return '暂无已启用的 BOM，请先为生产产品启用 BOM。';
  if (!selectedBom.value) return '请在下方表格选择生产产品及 BOM 版本。';
  if (selectedBom.value.status !== 'active') return '所选 BOM 已停用，请重新选择启用版本。';
  if (receiptLotMilli(workOrderForm.value.target_quantity) === null)
    return '目标产量须大于零、最多三位小数且不超过一百万。';
  if (!warehouses.value.some(item => item.id === workOrderForm.value.warehouse_id)) return '请选择有效的完工目标仓库。';
  return '';
});
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
// 产品 BOM 详情使用一次性建单意图；仅有效启用版本和实时权限允许打开草稿。
const consumedBom = ref(0);
watch([() => route?.query.create_from_bom, () => busy.value, () => connectionLost.value,
  () => store.user?.id, () => store.user?.permissions.join('|'), () => boms.value.find(item => item.id === Number(route?.query.create_from_bom))?.status, () => boms.value.find(item => item.id === Number(route?.query.create_from_bom))?.product_can_produce], () => {
  const id = Number(route?.query.create_from_bom);
  if (!Number.isSafeInteger(id) || id <= 0 || consumedBom.value === id || busy.value || connectionLost.value || !can('work_order.create')) return;
  const bom = boms.value.find(item => item.id === id && item.status === 'active' && item.product_can_produce !== false);
  if (!bom) return;
  consumedBom.value = id;
  workOrderForm.value.bom_id = id; workOrderForm.value.target_quantity = '1';
  createOpen.value = true;
  const {create_from_bom: _intent, ...query} = route.query;
  void router.replace({query}).then(() => {consumedBom.value = 0});
}, {immediate:true});
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
    <!-- 与仓库单据共用基础信息、产品明细表、可滚动正文及固定操作页脚。 -->
    <WorkspaceDocumentDialog
      v-if="can('work_order.create')"
      origin-key="ProductionWorkOrdersView:create"
      v-model:show="createOpen"
      title="新建生产工单"
      :data="productRows"
      :columns="productColumns"
      lines-title="生产产品"
      :show-add="false"
      :min-table-width="1000"
      :busy="busy"
      :disabled="connectionLost"
      :submit-disabled="!!productIssue"
      submit-label="保存工单草稿"
      hint="每张工单生产一种产品。保存时固定所选 BOM 的组件需求，完工入库前不改变库存。"
      @invalidated="createOpen = false"
      @submit="submitCreate"
    >
      <template #basicInfo>
        <label>完工目标仓库<WorkspaceSelect
          v-model="workOrderForm.warehouse_id" required :disabled="busy || connectionLost"
          :options="warehouses.map(item => ({ label: item.name, value: item.id }))"
        /></label>
        <label>参考号（可选）<AppInput v-model.trim="workOrderForm.reference" maxlength="100" :disabled="busy || connectionLost" /></label>
        <label>备注（可选）<AppInput v-model.trim="workOrderForm.note" maxlength="200" :disabled="busy || connectionLost" /></label>
        <div class="document-detail-field"><span>状态</span><strong>草稿</strong></div>
      </template>
      <template #materialPicker>
        <p v-if="productIssue" role="status" class="muted">{{ productIssue }}</p>
      </template>
      <template #cell-sku="{ row }"><strong>{{ row.bom?.product_sku ?? '待选择' }}</strong></template>
      <template #cell-product>
        <WorkspaceMaterialSelect
          v-model="productId"
          v-model:compact="productCompact"
          :materials="productChoices"
          :categories="store.materialCategories"
          required
          placeholder="搜索并选择生产产品"
          aria-label="生产产品"
          :disabled="busy || connectionLost"
        />
      </template>
      <template #cell-bom="{ row }">
        <WorkspaceSelect v-model="row.form.bom_id" :options="productBomOptions" required
          placeholder="选择启用版本" aria-label="生产 BOM 版本" :disabled="busy || connectionLost || !productId" />
      </template>
      <template #cell-unit="{ row }">{{ row.bom?.product_unit ?? '—' }}</template>
      <template #cell-quantity="{ row }">
        <!-- 数量仍直接写入同一 Pinia 草稿，隐藏步进按钮并保留原精度和范围。 -->
        <AppInput v-model.trim="row.form.target_quantity" type="number" hide-number-controls
          min="0.001" max="1000000" step="0.001" required aria-label="目标产量" :disabled="busy || connectionLost" />
      </template>
    </WorkspaceDocumentDialog>
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

<style scoped>
/* 本页移除概览说明后收紧卡片与列表间距，其他业务页面继续使用公共间距。 */
.production-work-orders { gap: 12px; }
</style>
