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
  relatedDocumentLabel,
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
// 全部批次单据共享标题、固定操作区与数量核对表。
import WorkspaceLotDialog from "../../../components/workspace/WorkspaceLotDialog.vue";
import WorkspaceLotLineEditor from "../../../components/workspace/WorkspaceLotLineEditor.vue";
// 生产列表沿用仓库管理的概览、搜索和仓库筛选，数量统计覆盖全部匹配记录。
import WorkspaceSummaryFilters from '../../../components/workspace/WorkspaceSummaryFilters.vue';
import WorkspaceSearchFilters from '../../../components/workspace/WorkspaceSearchFilters.vue';
import { useProductionRecords } from '../../../composables/use-production-records';
import type { WorkspaceTableColumn } from "../../../utils/table-columns";
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from 'vue-router';
import { routeByKey } from '../../../router/workspace-routes';

import { storeToRefs } from "pinia";
import { usePiniaAppStore } from "../../../store/app-store";
import { submitCreateDialog } from "../../../utils/create-dialog";
import {
  completionLotDate,
  completionLotMilli,
} from "../../../../../shared/completion-lot-api.ts";
import type { CompletionLotPartInput } from "../../../../../shared/completion-lot-api";
import type { ProductionCompletion } from "../../../../../shared/erp-api";

// 页面直接使用共享状态与操作，切换标签时不会丢失正在填写的草稿。
const store = usePiniaAppStore();
const {
  error,
  notice,
  busy,
  connectionLost,
  workOrders,
  productionCompletions,
  completionForm,
  inspectionDrafts,
  completionReversalReasons,
  selectedCompletionOrder,
} = storeToRefs(store);
const {
  can,
  localTime,
  selectCompletionOrder,
  createProductionCompletion,
  inspectProductionCompletion,
  postProductionCompletion,
  cancelProductionCompletion,
  reverseProductionCompletion,
} = store;

// 保存失败时保留弹窗和草稿，方便直接修正后重试。
const createOpen = ref(false);
const activeCompletionId = ref(0);
const lotDrafts = ref<CompletionLotPartInput[]>([]);
const activeCompletion = computed(
  () =>
    productionCompletions.value.find(
      (item) =>
        item.id === activeCompletionId.value &&
        item.status === "inspected" &&
        item.approval?.status === "approved",
    ) ?? null,
);
function startLotPost(item: ProductionCompletion): void {
  if (Number(item.accepted_quantity) === 0) {
    void postProductionCompletion(item.id);
    return;
  }
  activeCompletionId.value = item.id;
  lotDrafts.value = [
    {
      quantity: item.accepted_quantity ?? "",
      manufactured_on: null,
      expires_on: null,
    },
  ];
}
function addLot(): void {
  if (lotDrafts.value.length < 20)
    lotDrafts.value.push({
      quantity: "",
      manufactured_on: null,
      expires_on: null,
    });
}
const lotIssue = computed(() => {
  if (!activeCompletion.value) return "完工单已变化，请重新读取。";
  const expected = completionLotMilli(
    activeCompletion.value.accepted_quantity ?? "",
  );
  if (
    expected === null ||
    !lotDrafts.value.length ||
    lotDrafts.value.length > 20
  )
    return "合格入库须登记一个或多个实物批次。";
  let total = 0n;
  for (const part of lotDrafts.value) {
    const quantity = completionLotMilli(part.quantity);
    if (quantity === null)
      return "批次数量须大于零、最多三位小数且不超过一百万。";
    total += quantity;
    if (part.manufactured_on && !completionLotDate(part.manufactured_on))
      return "生产日期无效。";
    if (part.expires_on && !completionLotDate(part.expires_on))
      return "失效日期无效。";
    if (
      part.manufactured_on &&
      part.expires_on &&
      part.expires_on < part.manufactured_on
    )
      return "失效日期不能早于生产日期。";
  }
  return total === expected
    ? ""
    : `批次数量之和须等于合格入库量 ${activeCompletion.value.accepted_quantity}。`;
});
async function confirmLotPost(): Promise<void> {
  if (
    !activeCompletion.value ||
    lotIssue.value ||
    busy.value ||
    connectionLost.value
  )
    return;
  await postProductionCompletion(
    activeCompletion.value.id,
    lotDrafts.value.map((part) => ({ ...part })),
  );
}
async function submitCreate(): Promise<void> {
  // 原生回车提交同样遵守断线和实时权限限制，失败由公共助手保留草稿。
  if (busy.value || connectionLost.value || !can('production_completion.create')) return;
  await submitCreateDialog(
    createProductionCompletion,
    { busy, error, notice },
    createOpen,
  );
}
// 从工单进入时保留来源范围，查看历史完工与继续报工使用同一工单。
const route = useRoute(), router = useRouter();
const scopeOrderId = computed(() => Number(route?.query.work_order_id) || 0);
const canCreateForScope = computed(() => !scopeOrderId.value || workOrders.value.some(item => item.id === scopeOrderId.value
  && item.status === 'in_progress' && Number(item.remaining_output_quantity) > 0));
const scopedCompletions = computed(() => productionCompletions.value.filter(item => !scopeOrderId.value || item.work_order_id === scopeOrderId.value));
const { recordQuery, recordFilters, recordSummaries, recordFilterFields, filteredRecords, resetRecordFilters } = useProductionRecords(
  scopedCompletions, [
    { key: 'pending', label: '待质检 / 入库', statuses: ['draft', 'inspected'], tone: 'pending' },
    { key: 'posted', label: '已入库', statuses: ['posted'], tone: 'success' },
    { key: 'reversed', label: '已冲销', statuses: ['reversed'], tone: 'reversed' },
    { key: 'cancelled', label: '已取消', statuses: ['cancelled'], tone: 'neutral' },
  ],
  item => [documentSearch(item), relatedDocumentLabel(item, 'work_order'), item.work_order_id, item.product_name,
    item.product_sku, item.warehouse_name, item.created_by_name, item.inspected_by_name, item.reference, item.qc_note],
);
// 执行时重读服务端批准内容，禁止临时原因替换固定冲销依据。
async function reverseApproved(identifier: number): Promise<void> {
  if (
    !(await store.openDocumentApproval({
      document_type: "ProductionCompletion",
      document_id: identifier,
      intent: "reverse",
    }))
  )
    return;
  const record = store.documentApprovalRecord;
  if (record?.status !== "approved" || !record.reversal_reason) return;
  completionReversalReasons.value[identifier] = record.reversal_reason;
  store.closeDocumentApproval();
  await reverseProductionCompletion(identifier);
}
// 详情弹窗由审批目标驱动；页脚业务按钮按当前单据与意图（执行/冲销）展示。
const detailItem = computed(() =>
  findDocumentApprovalItem(store.documentApprovalTarget, "ProductionCompletion", productionCompletions.value),
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
function startCreate(): void {
  if (busy.value || connectionLost.value || !can('production_completion.create') || !canCreateForScope.value) return;
  // 查看来源工单后再点新建，也必须沿用该工单；同一工单再次打开保留已填写草稿。
  if (scopeOrderId.value && completionForm.value.work_order_id !== scopeOrderId.value)
    selectCompletionOrder(scopeOrderId.value, false);
  createOpen.value = true;
}
// 消费一次性建单意图后移除地址参数，刷新、关闭弹窗和快照更新都不会重复清空草稿。
let consumedCreateOrder = 0;
watch([() => route?.query.create_from_order, () => workOrders.value.length, () => store.user?.id,
  () => can('production_completion.create'), connectionLost, busy], () => {
  const id = Number(route?.query.create_from_order);
  if (!id) { consumedCreateOrder = 0; return; }
  if (consumedCreateOrder === id) return;
  if (scopeOrderId.value && scopeOrderId.value !== id) return;
  if (!Number.isSafeInteger(id) || id <= 0 || busy.value || connectionLost.value || !can('production_completion.create')) return;
  const order = workOrders.value.find(item => item.id === id);
  if (!order || order.status !== 'in_progress' || Number(order.remaining_output_quantity) <= 0) return;
  consumedCreateOrder = id;
  selectCompletionOrder(id, false);
  createOpen.value = true;
  const query = { ...route.query };
  delete query.create_from_order;
  void router.replace({ path: route.path, query });
}, { immediate: true });
// 完工记录保留返回来源工单的入口，库存和交接核对仍在原工单办理。
async function returnToWorkOrder(): Promise<void> {
  const item = detailItem.value;
  if (!item || busy.value || connectionLost.value || !can('production.view')) return;
  store.closeDocumentApproval();
  await router.push({ path: routeByKey('workOrders').path, query: { document_id: item.work_order_id } });
}
</script>

<template>
  <section class="stack">
    <!-- 业务操作统一在详情页脚办理；审批控件与关闭由公共弹窗承载。 -->
    <DocumentApprovalDialog origin-key="document-approval">
      <template #footerActions>
        <!-- 操作色表达业务含义：冲销红色、取消橙色、确认绿色、查看与编辑蓝色。 -->
        <template v-if="detailItem">
          <AppButton v-if="detailIntent === 'execute' && can('production.view')" tone="info"
            :disabled="busy || connectionLost" @click="returnToWorkOrder">返回生产工单</AppButton>
          <AppButton
            tone="info"
            v-if="detailIntent === 'execute'"
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click.capture="captureDialogOrigin('production-association', $event)" @click="
              store.openProductionAssociations({
                kind: 'completion',
                id: detailItem.id,
              })
            "
            >关联单据</AppButton
          >
          <RouterLink
            v-if="
              detailIntent === 'execute' &&
              detailItem.status === 'posted' &&
              !detailItem.reversal_id &&
              Number(detailItem.rejected_quantity) > 0 &&
              can('quality.view')
            "
            to="/workspace/production-quality"
            >处理不合格品</RouterLink
          >
          <AppButton
            tone="success"
            v-if="
              detailIntent === 'execute' &&
              detailItem.status === 'inspected' &&
              detailItem.approval?.status === 'approved' &&
              can('production_completion.post')
            "
            type="button"
            variant="primary"
            :disabled="busy || connectionLost"
            @click="postProductionCompletion(detailItem.id)"
            >确认完工</AppButton
          >
          <AppButton
            tone="info"
            v-if="
              detailIntent === 'execute' &&
              detailItem.status === 'inspected' &&
              detailItem.approval?.status === 'approved' &&
              can('production_completion.post') &&
              Number(detailItem.accepted_quantity) > 0
            "
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click.capture="captureDialogOrigin('ProductionCompletionsView:lot', $event)" @click="startLotPost(detailItem)"
            >指定实物批次（可选）</AppButton
          >
          <AppButton
            tone="warning"
            v-if="
              detailIntent === 'execute' &&
              (detailItem.status === 'draft' ||
                detailItem.status === 'inspected') &&
              !['submitted', 'approved'].includes(
                detailItem.approval?.status ?? '',
              ) &&
              can('production_completion.cancel')
            "
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click="cancelProductionCompletion(detailItem.id)"
            >取消</AppButton
          >
          <!-- 冲销另行送审；完成后保留查询入口而不允许再次执行。 -->
          <AppButton
            tone="error"
            v-if="
              detailIntent === 'execute' && detailItem.status === 'reversed'
            "
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click.capture="captureDialogOrigin('document-approval', $event)" @click="
              store.openDocumentApproval({
                document_type: 'ProductionCompletion',
                document_id: detailItem.id,
                intent: 'reverse',
              })
            "
            >冲销审批记录</AppButton
          >
          <AppButton
            tone="error"
            v-if="
              detailIntent === 'execute' &&
              detailItem.status === 'posted' &&
              can('production_completion.reverse')
            "
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click.capture="captureDialogOrigin('document-approval', $event)" @click="
              store.openDocumentApproval({
                document_type: 'ProductionCompletion',
                document_id: detailItem.id,
                intent: 'reverse',
              })
            "
            >冲销审批</AppButton
          >
          <AppButton
            tone="info"
            v-if="detailIntent === 'reverse'"
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click.capture="captureDialogOrigin('document-approval', $event)" @click="
              store.openDocumentApproval({
                document_type: 'ProductionCompletion',
                document_id: detailItem.id,
                intent: 'execute',
              })
            "
            >查看完工审批</AppButton
          >
          <AppButton
            tone="error"
            v-if="
              detailIntent === 'reverse' &&
              detailItem.status === 'posted' &&
              can('production_completion.reverse') &&
              detailItem.reversal_approval?.status === 'approved'
            "
            type="button"
            variant="primary"
            :disabled="busy || connectionLost"
            @click="reverseApproved(detailItem.id)"
            >执行已批准冲销</AppButton
          >
          <!-- 质检录入依赖逐行数量与说明，随详情页脚保留原表单交互。 -->
          <form
            v-if="
              detailIntent === 'execute' &&
              detailItem.status === 'draft' &&
              can('production_completion.inspect') &&
              inspectionDrafts[detailItem.id]
            "
            class="inline-form"
            @submit.prevent="inspectProductionCompletion(detailItem.id)"
          >
            <label>
              合格数量
              <AppInput
                v-model.trim="
                  inspectionDrafts[detailItem.id]!.accepted_quantity
                "
                type="number"
                min="0"
                :max="detailItem.reported_quantity"
                step="0.001"
                required
              />
            </label>
            <label>
              质检说明
              <AppInput
                v-model.trim="inspectionDrafts[detailItem.id]!.qc_note"
                required
                maxlength="200"
              />
            </label>
            <AppButton
              tone="info"
              type="submit"
              :disabled="busy || connectionLost"
              variant="primary"
              >记录质检结果</AppButton
            >
          </form>
        </template>
      </template>
    </DocumentApprovalDialog>
    <ProductionAssociationDialog origin-key="production-association" />
    <AppModal :busy="busy" origin-key="ProductionCompletionsView:create" @invalidated="createOpen = false"
      title="新建完工报工单"
      v-if="can('production_completion.create')"
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
        按工单目标产量分批报工。报工数包含待质检的合格与不合格产品；质检并确认后，只有合格数进入工单目标仓库。
      </p>
      <form @submit.prevent="submitCreate">
        <div class="form-grid">
          <label
            >生产工单<WorkspaceSelect
              v-model="completionForm.work_order_id"
              required
              @change="selectCompletionOrder(completionForm.work_order_id, false)"
              :options="[
                { label: '选择生产中工单', value: 0, disabled: true },
                ...workOrders
                  .filter(
                    (entry) =>
                      entry.status === 'in_progress' &&
                      (!scopeOrderId || entry.id === scopeOrderId) &&
                      Number(entry.remaining_output_quantity) > 0,
                  )
                  .map((item) => ({
                    label: (
                      documentLabel(item) +
                      ' · ' +
                      item.product_name +
                      ' · 待报工 ' +
                      item.remaining_output_quantity +
                      ' ' +
                      item.product_unit
                    ).trim(),
                    value: item.id,
                  })),
              ]" /></label
          ><label
            >本次报工数量<AppInput
              v-model.trim="completionForm.reported_quantity"
              type="number"
              min="0.001"
              :max="selectedCompletionOrder?.remaining_output_quantity"
              step="0.001"
              required /></label
          ><label
            >参考号（可选）<AppInput
              v-model.trim="completionForm.reference"
              maxlength="100"
          /></label>
        </div>
        <AppButton
          type="submit"
          :disabled="busy || connectionLost || !completionForm.work_order_id"
          variant="primary"
        >
          保存报工草稿
        </AppButton>
      </form>
    </AppModal>
    <!-- 统计统一进入页面标题右侧，与其他入库保持相同位置。 -->
    <Teleport to="#workspace-page-summary" defer>
      <WorkspaceSummaryFilters v-model="recordFilters.status" :options="recordSummaries" hint="按搜索与仓库统计全部匹配单据 · 点击筛选状态" />
    </Teleport>
    <p v-if="scopeOrderId" class="muted">当前仅显示来源工单的完工记录。
      <AppButton variant="text" @click="router.push(routeByKey('productionCompletions').path)">查看全部完工记录</AppButton>
    </p>
    <!-- 主标题由工作台提供，列表复用仓库管理的筛选区、状态和单元格布局。 -->
    <WorkspaceTable
      :show-title="false"
      title="完工与质检"
      :data="filteredRecords"
      :columns="columns"
      :min-table-width="1100"
    >
      <template #actions>
        <AppButton
          v-if="can('production_completion.create')"
          type="button"
          :disabled="busy || connectionLost || !canCreateForScope"
          @click.capture="captureDialogOrigin('ProductionCompletionsView:create', $event)" @click="startCreate"
          variant="primary"
        >
          新建完工报工单
        </AppButton>
      </template>
      <template #filters>
        <WorkspaceSearchFilters v-model:query="recordQuery" v-model:filters="recordFilters" :fields="recordFilterFields"
          search-label="搜索完工与质检" search-placeholder="单号、工单、产品或物料" @reset="resetRecordFilters" />
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
                  document_type: 'ProductionCompletion',
                  document_id: item.id,
                  intent: 'execute',
                })
              "
              >{{ documentLabel(item) }}</AppButton
            >
            · 工单 {{ relatedDocumentLabel(item, "work_order") }} ·
            {{ item.product_name }} ·
            {{ item.warehouse_name }}
          </strong>
          <p class="muted">
            {{ localTime(item.created_at) }} · 报工人
            {{ item.created_by_name }}
            <span v-if="item.reference">· {{ item.reference }}</span>
          </p>
        </div>
      </template>
      <template #cell-status="{ row: item }">
        <span class="pill" :class="item.status">
          {{
            {
              draft: "待质检",
              inspected: approvalLabels[item.approval?.status ?? "draft"],
              posted: "已入库",
              reversed: "已冲销",
              cancelled: "已取消",
            }[item.status]
          }}
        </span>
      </template>
      <template #cell-details="{ row: item }">
        <div class="workspace-record-lines">
          <span>
            报工 {{ item.reported_quantity }} · 合格
            {{ item.accepted_quantity ?? "待质检" }} · 不合格
            {{ item.rejected_quantity ?? "待质检" }}
            {{ item.product_unit }}
          </span>
          <span v-if="item.qc_note">
            质检说明：{{ item.qc_note }} · 质检人 {{ item.inspected_by_name }}
          </span>
          <span v-if="item.physical_lots?.length">
            {{ item.status === "reversed" ? "原实物批次" : "实物批次" }}：{{
              item.physical_lots
                .map((lot) => `${lot.code}（${lot.quantity}）`)
                .join("、")
            }}
          </span>
          <span
            v-else-if="
              item.status === 'posted' && Number(item.accepted_quantity) > 0
            "
          >
            普通确认未指定实物批次，不据此推断采购来源。
          </span>
          <span v-if="item.reversal_id">
            冲销 #{{ item.reversal_id }} · {{ item.reversal_reason }} ·
            {{ item.reversed_by_name }} ·
            {{ localTime(item.reversed_at!) }}
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
              document_type: 'ProductionCompletion',
              document_id: item.id,
              intent: 'execute',
            })
          "
          >查看</AppButton
        >
      </template>
      <template #empty>
        <strong>{{
          (recordQuery || recordFilters.status || recordFilters.warehouse) ? "没有匹配的记录" : "暂无完工与质检记录"
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
    <!-- 批次登记统一使用公共弹窗和明细表，各业务仍保留原确认与校验逻辑。 -->
    <WorkspaceLotDialog origin-key="ProductionCompletionsView:lot" @invalidated="activeCompletionId = 0"
      v-if="can('production_completion.post')"
      :show="!!activeCompletion"
      title="完工入库 · 成品批次"
      :document-number="activeCompletion ? documentLabel(activeCompletion) : ''"
      hint="按实际分开的成品批次登记，数量之和须等于合格入库量。系统生成独立内部编号供实物标识；缺少日期时留空。"
      :busy="busy"
      :disabled="connectionLost"
      :issue="lotIssue"
      submit-label="确认合格品入库"
      @update:show="
        (value) => {
          if (!value) activeCompletionId = 0;
        }
      "
      @submit="confirmLotPost"
    >
      <template v-if="activeCompletion">
      <WorkspaceLotLineEditor
        :lots="lotDrafts"
        :material-name="activeCompletion.product_name"
        :unit="activeCompletion.product_unit"
        :expected="activeCompletion.accepted_quantity ?? ''"
        expected-label="应入库"
        :show-source="false"
        :disabled="busy || connectionLost"
        @add="addLot"
        @remove="(index) => lotDrafts.splice(index, 1)"
      />

      </template>
    </WorkspaceLotDialog>
  </section>
</template>

<style scoped></style>
