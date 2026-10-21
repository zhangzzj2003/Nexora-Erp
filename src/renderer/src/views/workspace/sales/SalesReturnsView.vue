<script setup lang="ts">
import { useSalesDraftEditor } from '../../../composables/use-sales-draft-editor'
import { canReviseSalesDraft, newSalesFilters, matchesSalesFilters } from '../../../utils/sales-documents'
import type { SalesDraftType } from '../../../../../shared/sales-draft-api'
import SalesDocumentList from './SalesDocumentList.vue'
import SalesDocumentDetail from './SalesDocumentDetail.vue'
import {defineAsyncComponent} from 'vue'
// 修订历史按需加载，日常列表不提前初始化弹窗和历史读取。
const SalesDraftHistory = defineAsyncComponent(()=>import('./SalesDraftHistory.vue'))

// 来源绑定在真实触发入口，键盘点击与鼠标点击共用同一回程位置。
import { captureDialogOrigin } from '../../../utils/dialog-origin'
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
// 单据统一使用固定关闭区、基础信息和物料明细表格。
import { documentRows } from "../../../utils/document-rows";
import WorkspaceDocumentDialog from "../../../components/workspace/WorkspaceDocumentDialog.vue";
import DocumentApprovalDialog from "../../../components/workspace/DocumentApprovalDialog.vue";
// 全部批次单据共享标题、固定操作区与数量核对表。
import WorkspaceLotDialog from "../../../components/workspace/WorkspaceLotDialog.vue";
import WorkspaceLotLineEditor from "../../../components/workspace/WorkspaceLotLineEditor.vue";
import {
  matchesRecordQuery,
} from "../../../utils/workspace-records";
import { computed, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { usePiniaAppStore } from "../../../store/app-store";
import { submitCreateDialog } from "../../../utils/create-dialog";
import { displayError } from "../../../utils/formatters.ts";
import {
  receiptLotDate,
  receiptLotMilli,
} from "../../../../../shared/receipt-lot-api.ts";
import { physicalLotKindLabel } from "../../../../../shared/physical-lot-api.ts";
import type {
  SalesReturnLotLineInput,
  SalesReturnLotOptions,
  SalesReturnLotPartInput,
} from "../../../../../shared/sales-return-lot-api";
import type { SalesReturn } from "../../../../../shared/erp-api";

// 页面直接使用共享状态与操作，切换标签时不会丢失正在填写的草稿。
const store = usePiniaAppStore();
const {
  error,
  notice,
  busy,
  connectionLost,
  warehouses,
  customers,
  salesOrders,
  shipments,
  salesReturns,
  salesReturnReversalReasons,
  salesReturnForm,
} = storeToRefs(store);
const {
  can,
  localTime,
  createSalesReturn,
  loadAvailableSalesReturnLots,
  postSalesReturn,
  cancelSalesReturn,
  reverseSalesReturn,
} = store;

// 编号与查看先进入业务详情；审批保持独立入口，避免审批步骤遮住物料与金额。
const selectedId = ref<number | null>(null);
const businessDetail = computed(() => salesReturns.value.find(row => row.id === selectedId.value) ?? null);
function openBusinessDetail(row: SalesReturn): void {
  if (busy.value || connectionLost.value || !can('sales.view')) return;
  selectedId.value = row.id;
}
watch(() => `${store.server?.id}:${store.server?.fingerprint}:${store.user?.id}:${store.user?.permissions.join('|')}:${connectionLost.value}`, () => { selectedId.value = null; });
// 修订表单使用副本，原新建草稿继续保留在 Pinia 中。
const {open:createOpen, form:workingForm, target:editTarget, reason:revisionReason,
  isolated:isolatedForm, beginEdit, beginCreate} = useSalesDraftEditor(salesReturnForm);
const historyTarget = ref<{type:SalesDraftType; id:number} | null>(null);
const filters = ref(newSalesFilters());
function editRecord(row: SalesReturn): void {
  if (beginEdit(row, {shipment_id:row.shipment_id, warehouse_id:row.warehouse_id, reason:row.reason, lines:row.lines.map(line=>({shipment_line_id:line.shipment_line_id,quantity:line.quantity}))})) { selectedId.value = null; store.closeDocumentApproval(); }
}
const selectedSalesReturnShipment = computed(()=>shipments.value.find(row=>row.id===workingForm.value.shipment_id));
function selectReturnSource(): void {
  workingForm.value.lines = selectedSalesReturnShipment.value?.lines.filter(line=>Number(line.returnable_quantity)>0)
    .map(line=>({shipment_line_id:line.id,quantity:line.returnable_quantity})) ?? [];
  if(selectedSalesReturnShipment.value)workingForm.value.warehouse_id=selectedSalesReturnShipment.value.warehouse_id;
}

watch(()=>[store.salesNavigation,store.activeTab] as const, ([request,route])=>{
  if(route!=='salesReturns' || request?.action!=='createReturn')return;
  store.salesNavigation=null;
  const source=shipments.value.find(row=>row.id===request.sourceId && row.status==='posted' && !row.reversal_id);
  if(!source){error.value='原出库单已变化，请刷新后重试。';return;}
  beginCreate({shipment_id:source.id,warehouse_id:source.warehouse_id,reason:'',
    lines:source.lines.filter(line=>Number(line.returnable_quantity)>0).map(line=>({shipment_line_id:line.id,quantity:line.returnable_quantity}))});
}, {immediate:true});

// 详情弹窗由审批目标驱动；页脚业务按钮按当前单据与意图（执行/冲销）展示。
const detailItem = computed(() =>
  findDocumentApprovalItem(store.documentApprovalTarget, "SalesReturn", salesReturns.value),
);
const detailIntent = computed(
  () => store.documentApprovalTarget?.intent ?? "execute",
);


const activeReturnId = ref(0);
const lotOptions = ref<SalesReturnLotOptions | null>(null);
const lotDrafts = ref<SalesReturnLotLineInput[]>([]);
const lotLoading = ref(false);
const lotLoadError = ref("");
let loadTicket = 0;
const activeReturn = computed(
  () =>
    salesReturns.value.find(
      (item) =>
        item.id === activeReturnId.value &&
        item.status === "draft" &&
        item.approval?.status === "approved",
    ) ?? null,
);

function closeLotPost(): void {
  loadTicket++;
  activeReturnId.value = 0;
  lotOptions.value = null;
  lotDrafts.value = [];
}

function newPart(quantity: string): SalesReturnLotPartInput {
  return {
    lot_id: null,
    quantity,
    supplier_lot: null,
    manufactured_on: null,
    expires_on: null,
  };
}

async function startLotPost(saleReturn: SalesReturn): Promise<void> {
  const ticket = ++loadTicket;
  activeReturnId.value = saleReturn.id;
  lotOptions.value = null;
  lotDrafts.value = [];
  lotLoadError.value = "";
  lotLoading.value = true;
  try {
    const result = await loadAvailableSalesReturnLots(saleReturn.id);
    if (ticket !== loadTicket || activeReturnId.value !== saleReturn.id) return;
    if (
      result.shipment_id !== saleReturn.shipment_id ||
      result.warehouse_id !== saleReturn.warehouse_id ||
      result.lines.length !== saleReturn.lines.length ||
      result.lines.some(
        (line) =>
          !saleReturn.lines.some(
            (item) =>
              item.id === line.return_line_id &&
              item.shipment_line_id === line.shipment_line_id &&
              item.material_id === line.material_id &&
              item.quantity === line.quantity,
          ),
      )
    )
      throw Error("原出库批次与当前销售退货单不匹配，请刷新单据。");
    lotOptions.value = result;
    lotDrafts.value = saleReturn.lines.map((line) => ({
      return_line_id: line.id,
      lots: [newPart(line.quantity)],
    }));
  } catch (cause) {
    if (ticket === loadTicket) lotLoadError.value = displayError(cause);
  } finally {
    if (ticket === loadTicket) lotLoading.value = false;
  }
}

function addLot(line: SalesReturnLotLineInput): void {
  if (line.lots.length < 20) line.lots.push(newPart(""));
}

const lotIssue = computed(() => {
  const saleReturn = activeReturn.value,
    options = lotOptions.value;
  if (
    !saleReturn ||
    !options ||
    lotDrafts.value.length !== saleReturn.lines.length
  )
    return "原出库批次尚未读取。";
  for (const line of saleReturn.lines) {
    const draft = lotDrafts.value.find(
      (item) => item.return_line_id === line.id,
    );
    const available = options.lines.find(
      (item) => item.return_line_id === line.id,
    );
    if (!draft || !available || !draft.lots.length || draft.lots.length > 20)
      return "每条退货明细至少指定一个回仓实物批次。";
    const ids = new Set<number>();
    let total = 0n;
    for (const part of draft.lots) {
      const quantity = receiptLotMilli(part.quantity);
      if (quantity === null)
        return "批次数量须大于零、最多三位小数且不超过一百万。";
      if (part.lot_id === null) {
        if (part.supplier_lot && part.supplier_lot.length > 100)
          return "来源批号不能超过 100 字。";
        if (
          (part.manufactured_on && !receiptLotDate(part.manufactured_on)) ||
          (part.expires_on && !receiptLotDate(part.expires_on)) ||
          (part.manufactured_on &&
            part.expires_on &&
            part.expires_on < part.manufactured_on)
        )
          return "退回新批次的日期无效。";
      } else {
        const candidate = available.lots.find(
          (item) => item.lot_id === part.lot_id,
        );
        if (!candidate || ids.has(part.lot_id))
          return `物料 ${line.sku} 的原出库批次无效或重复。`;
        ids.add(part.lot_id);
        if (quantity > (receiptLotMilli(candidate.quantity) ?? 0n))
          return `原出库批次 ${candidate.code} 的剩余可退量不足，请重新读取。`;
      }
      total += quantity;
    }
    if (total !== receiptLotMilli(line.quantity))
      return `物料 ${line.sku} 的回仓批次数量之和须等于 ${line.quantity}。`;
  }
  return "";
});

async function confirmLotPost(): Promise<void> {
  const saleReturn = activeReturn.value;
  if (!saleReturn || lotIssue.value || busy.value || connectionLost.value)
    return;
  await postSalesReturn(
    saleReturn.id,
    lotDrafts.value.map((line) => ({
      return_line_id: line.return_line_id,
      lots: line.lots.map((part) => ({
        lot_id: part.lot_id,
        quantity: part.quantity,
        supplier_lot:
          part.lot_id === null ? part.supplier_lot?.trim() || null : null,
        manufactured_on: part.lot_id === null ? part.manufactured_on : null,
        expires_on: part.lot_id === null ? part.expires_on : null,
      })),
    })),
  );
  if (
    !salesReturns.value.some(
      (item) => item.id === saleReturn.id && item.status === "draft",
    )
  )
    closeLotPost();
}

// 保存失败时保留弹窗和草稿，方便直接修正后重试。

async function submitCreate(): Promise<void> {
  if (editTarget.value) {
    const current = editTarget.value;
    if (await store.reviseSalesDraft('reviseSalesReturn', {...workingForm.value, returnId:current.id,
      expected_version:current.version,revision_reason:revisionReason.value})) createOpen.value = false;
    return;
  }
  await submitCreateDialog(()=>createSalesReturn(isolatedForm.value ?? undefined), {busy,error,notice}, createOpen);
}
// 只筛选当前列表快照，原有单据状态与跨页面草稿保持不变。
const recordQuery = ref("");
const filteredRecords = computed(() =>
  salesReturns.value.filter((item) =>
    matchesSalesFilters(item, salesOrders.value.find(order=>order.id===item.sales_order_id)?.customer_id, filters.value) && matchesRecordQuery(recordQuery.value, [
      documentSearch(item),
      item.id,
      item.customer_name,
      item.warehouse_name,
      item.created_by_name,
      item.reason,
      ...item.lines.map((line) => line.material_name),
    ]),
  ),
);
// 保留每个草稿行的引用，表格编辑不会改写成另一套临时表单。
const salesReturnFormRows = computed(() =>
  documentRows(workingForm.value.lines),
);
const salesReturnFormColumns = [
  { key: "material", title: "原出库物料", width: "300" },
  { key: "quantity", title: "退货数量", width: "150" },
  { key: "actions", title: "操作", width: "90" },
];
// 审批进度与执行状态分开显示，上游批准不会代替本单批准。
const approvalLabels = {
  draft: "未送审",
  submitted: "审批中",
  approved: "已批准，待确认",
  rejected: "已驳回",
  withdrawn: "已撤回",
  executed: "已执行",
};
// 冲销执行重新读取批准原因，禁止以临时输入替换审批记录。
async function reverseApproved(identifier: number): Promise<void> {
  if (
    !(await store.openDocumentApproval({
      document_type: "SalesReturn",
      document_id: identifier,
      intent: "reverse",
    }))
  )
    return;
  const record = store.documentApprovalRecord;
  if (record?.status !== "approved" || !record.reversal_reason) return;
  salesReturnReversalReasons.value[identifier] = record.reversal_reason;
  store.closeDocumentApproval();
  await reverseSalesReturn(identifier);
}
</script>

<template>
  <section class="stack">
    <SalesDocumentDetail :materials="store.materials" :record="businessDetail" kind="return" title="销售退货" :busy="busy" :disabled="connectionLost" :local-time="localTime" @close="selectedId=null">
      <template #actions>
        <AppButton v-if="businessDetail" size="small" :disabled="busy || connectionLost" @click.capture="captureDialogOrigin('document-approval',$event)"
          @click="store.openDocumentApproval({document_type:'SalesReturn',document_id:businessDetail.id,intent:'execute'})">单据审批</AppButton>

        <!-- 操作色表达业务含义：冲销红色、取消橙色、确认绿色、查看与编辑蓝色。 -->
        <template v-if="businessDetail">
          <AppButton size="small" v-if="can('sales_return.create') && canReviseSalesDraft(businessDetail)" :disabled="busy || connectionLost"
            @click.capture="captureDialogOrigin('SalesReturnsView:form', $event)" @click="editRecord(businessDetail)">修订草稿</AppButton>
          <AppButton size="small" v-if="(businessDetail.draft_version ?? 0) > 0" :disabled="busy || connectionLost"
            @click="historyTarget={type:'SalesReturn',id:businessDetail.id}">修订记录</AppButton>
          <span v-if="businessDetail.status==='draft' && businessDetail.draft_edit_block_reason" class="muted">{{ businessDetail.draft_edit_block_reason }}</span>
          <AppButton size="small"
            tone="success"
            v-if="
              businessDetail.status === 'draft' &&
              businessDetail.approval?.status === 'approved' &&
              can('sales_return.post')
            "
            type="button"
            variant="primary"
            :disabled="busy || connectionLost"
            @click="postSalesReturn(businessDetail.id)"
            >确认退货</AppButton
          >
          <AppButton size="small"
            tone="info"
            v-if="
              businessDetail.status === 'draft' &&
              businessDetail.approval?.status === 'approved' &&
              can('sales_return.post')
            "
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click.capture="captureDialogOrigin('SalesReturnsView:lot', $event)" @click="startLotPost(businessDetail)"
            >指定实物批次（可选）</AppButton
          >
          <AppButton size="small"
            tone="warning"
            v-if="
              businessDetail.status === 'draft' &&
              !['submitted', 'approved'].includes(
                businessDetail.approval?.status ?? '',
              ) &&
              can('sales_return.cancel')
            "
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click="cancelSalesReturn(businessDetail.id)"
            >取消</AppButton
          >
          <!-- 冲销完成后仍可查批准人员和固定原因，查询入口沿用本单查看权限。 -->
          <AppButton size="small"
            tone="error"
            v-if="
              businessDetail.status === 'posted' &&
              (businessDetail.reversal_id || can('sales_return.reverse'))
            "
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click.capture="captureDialogOrigin('document-approval', $event)" @click="
              store.openDocumentApproval({
                document_type: 'SalesReturn',
                document_id: businessDetail.id,
                intent: 'reverse',
              })
            "
            >{{
              businessDetail.reversal_id ? "冲销审批记录" : "冲销审批"
            }}</AppButton
          >


        </template>

      </template>
    </SalesDocumentDetail>

    <!-- 业务操作统一在详情页脚办理；审批控件与关闭由公共弹窗承载。 -->
    <DocumentApprovalDialog origin-key="document-approval">
      <template #footerActions>
        <!-- 操作色表达业务含义：冲销红色、取消橙色、确认绿色、查看与编辑蓝色。 -->
        <template v-if="detailItem">
          <AppButton v-if="can('sales_return.create') && canReviseSalesDraft(detailItem)" :disabled="busy || connectionLost"
            @click.capture="captureDialogOrigin('SalesReturnsView:form', $event)" @click="editRecord(detailItem)">修订草稿</AppButton>
          <AppButton v-if="(detailItem.draft_version ?? 0) > 0" :disabled="busy || connectionLost"
            @click="historyTarget={type:'SalesReturn',id:detailItem.id}">修订记录</AppButton>
          <span v-if="detailItem.status==='draft' && detailItem.draft_edit_block_reason" class="muted">{{ detailItem.draft_edit_block_reason }}</span>
          <AppButton
            tone="success"
            v-if="
              detailIntent === 'execute' &&
              detailItem.status === 'draft' &&
              detailItem.approval?.status === 'approved' &&
              can('sales_return.post')
            "
            type="button"
            variant="primary"
            :disabled="busy || connectionLost"
            @click="postSalesReturn(detailItem.id)"
            >确认退货</AppButton
          >
          <AppButton
            tone="info"
            v-if="
              detailIntent === 'execute' &&
              detailItem.status === 'draft' &&
              detailItem.approval?.status === 'approved' &&
              can('sales_return.post')
            "
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click.capture="captureDialogOrigin('SalesReturnsView:lot', $event)" @click="startLotPost(detailItem)"
            >指定实物批次（可选）</AppButton
          >
          <AppButton
            tone="warning"
            v-if="
              detailIntent === 'execute' &&
              detailItem.status === 'draft' &&
              !['submitted', 'approved'].includes(
                detailItem.approval?.status ?? '',
              ) &&
              can('sales_return.cancel')
            "
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click="cancelSalesReturn(detailItem.id)"
            >取消</AppButton
          >
          <!-- 冲销完成后仍可查批准人员和固定原因，查询入口沿用本单查看权限。 -->
          <AppButton
            tone="error"
            v-if="
              detailIntent === 'execute' &&
              detailItem.status === 'posted' &&
              (detailItem.reversal_id || can('sales_return.reverse'))
            "
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click.capture="captureDialogOrigin('document-approval', $event)" @click="
              store.openDocumentApproval({
                document_type: 'SalesReturn',
                document_id: detailItem.id,
                intent: 'reverse',
              })
            "
            >{{
              detailItem.reversal_id ? "冲销审批记录" : "冲销审批"
            }}</AppButton
          >
          <AppButton
            tone="info"
            v-if="detailIntent === 'reverse'"
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click.capture="captureDialogOrigin('document-approval', $event)" @click="
              store.openDocumentApproval({
                document_type: 'SalesReturn',
                document_id: detailItem.id,
                intent: 'execute',
              })
            "
            >查看退货审批</AppButton
          >
          <AppButton
            tone="error"
            v-if="
              detailIntent === 'reverse' &&
              !detailItem.reversal_id &&
              detailItem.reversal_approval?.status === 'approved' &&
              can('sales_return.reverse')
            "
            type="button"
            variant="primary"
            :disabled="busy || connectionLost"
            @click="reverseApproved(detailItem.id)"
            >执行已批准冲销</AppButton
          >
        </template>
      </template>
    </DocumentApprovalDialog>
    <SalesDraftHistory v-if="historyTarget" v-model="historyTarget" />
    <!-- 共用基础信息与物料表格布局；行对象仍指向原 Pinia 草稿，保留业务字段和来源约束。 -->
    <WorkspaceDocumentDialog origin-key="SalesReturnsView:form" @invalidated="createOpen = false"
      v-if="can('sales_return.create')"
      v-model:show="createOpen"
      :title="editTarget ? '修订销售退货单' : '新建销售退货单'"
      :data="salesReturnFormRows"
      :columns="salesReturnFormColumns"
      :busy="busy"
      :disabled="connectionLost"
      :submit-disabled="!workingForm.lines.length || !warehouses.length"
      :submit-label="editTarget ? '保存修订' : '保存草稿'"
      :min-table-width="800"
      :show-add="false"
      empty-text="请先选择来源单据，系统将载入可处理的物料明细。"
      @submit="submitCreate"
    >
      <template #basicInfo
        ><label
          >原出库单<WorkspaceSelect
            :disabled="busy || connectionLost"
            v-model="workingForm.shipment_id"
            required
            @change="selectReturnSource"
            :options="[
              { label: '选择可退货的出库单', value: 0, disabled: true },
              ...shipments
                .filter(
                  (entry) =>
                    entry.status === 'posted' &&
                    !entry.reversal_id &&
                    entry.lines.some(
                      (line) => Number(line.returnable_quantity) > 0,
                    ),
                )
                .map((item) => ({
                  label: (
                    documentLabel(item) +
                    ' · ' +
                    item.customer_name +
                    ' · ' +
                    item.warehouse_name
                  ).trim(),
                  value: item.id,
                })),
            ]" /></label
        ><label
          >退回仓库<WorkspaceSelect
            :disabled="busy || connectionLost"
            v-model="workingForm.warehouse_id"
            required
            :options="[
              ...warehouses.map((item) => ({
                label: item.name,
                value: item.id,
              })),
            ]" /></label
        ><label
          >退货原因<AppInput
            :disabled="busy || connectionLost"
            v-model.trim="workingForm.reason"
            required
            maxlength="200"
        /></label>
        <label v-if="editTarget">修订原因<AppInput v-model.trim="revisionReason" required maxlength="200" :disabled="busy || connectionLost" /></label>
        <div class="document-basic-extra">
          <p class="muted">
            退货关联原出库明细，确认后新增入库流水并调整应收。草稿金额为预估，确认时按原出库累计退货数量分摊尾差；实际退款需另行登记。
          </p>
        </div>
      </template>
      <template #cell-material="{ row: { line, index } }"
        ><label
          >原出库物料<AppInput
            :model-value="
              selectedSalesReturnShipment?.lines.find(
                (item) => item.id === line.shipment_line_id,
              )?.material_name
            "
            disabled /></label
      ></template>
      <template #cell-quantity="{ row: { line, index } }"
        ><label
          >退货数量（最多
          {{
            selectedSalesReturnShipment?.lines.find(
              (item) => item.id === line.shipment_line_id,
            )?.returnable_quantity
          }}）<AppInput
            :disabled="busy || connectionLost"
            v-model.trim="line.quantity"
            type="number"
            min="0.001"
            :max="
              selectedSalesReturnShipment?.lines.find(
                (item) => item.id === line.shipment_line_id,
              )?.returnable_quantity
            "
            step="0.001"
            required /></label
      ></template>
      <template #cell-actions="{ row: { line, index } }"
        ><!-- 移除沿用主线完整点击区域，保留原有禁用与删行规则。 -->
        <AppButton size="small"
          :disabled="busy || connectionLost"
          type="button"
          @click="workingForm.lines.splice(index, 1)"
          variant="secondary"
        >
          移除
        </AppButton></template
      >
    </WorkspaceDocumentDialog>
    <!-- 列表复用生产计划的概览、查询、状态与分页，完整履约明细集中在详情。 -->
    <SalesDocumentList kind="return" title="销售退货" :records="salesReturns" :filtered="filteredRecords" :customers="customers"
      v-model:query="recordQuery" v-model:filters="filters" :disabled="busy || connectionLost" :local-time="localTime" @view="openBusinessDetail">
      <template #actions>
        <AppButton
          v-if="can('sales_return.create')"
          type="button"
          :disabled="busy"
          @click.capture="captureDialogOrigin('SalesReturnsView:form', $event)" @click="createOpen = true"
          variant="primary"
        >
          新建销售退货单
        </AppButton>
      </template>
    </SalesDocumentList>
    <!-- 批次登记统一使用公共弹窗和明细表，各业务仍保留原确认与校验逻辑。 -->
    <WorkspaceLotDialog origin-key="SalesReturnsView:lot" @invalidated="closeLotPost()"
      v-if="can('sales_return.post')"
      :show="!!activeReturn"
      title="销售退货 · 回仓批次"
      :document-number="activeReturn ? documentLabel(activeReturn) : ''"
      :hint="
        '可归回原出库已记录的批次，数量不得超过该批次剩余可退量；实物不属于原批次或原出库未记录批次时，登记“退货新批次”。退回仓库为 ' +
        activeReturn?.warehouse_name +
        '。'
      "
      :busy="busy"
      :disabled="connectionLost"
      :issue="lotIssue"
      submit-label="确认退货"
      :loading="lotLoading"
      :load-error="lotLoadError"
      loading-text="正在读取原出库批次…"
      @update:show="
        (value) => {
          if (!value) closeLotPost();
        }
      "
      @submit="confirmLotPost"
    >
      <template v-if="activeReturn">
      <WorkspaceLotLineEditor
        v-for="line in lotDrafts"
        :key="line.return_line_id"
        :lots="line.lots"
        :sku="
          activeReturn.lines.find((item) => item.id === line.return_line_id)
            ?.sku
        "
        :material-name="
          activeReturn.lines.find((item) => item.id === line.return_line_id)
            ?.material_name
        "
        :unit="
          activeReturn.lines.find((item) => item.id === line.return_line_id)
            ?.unit
        "
        :expected="
          activeReturn.lines.find((item) => item.id === line.return_line_id)
            ?.quantity ?? ''
        "
        expected-label="应退货"
        quantity-label="批次数量"
        :selectable="true"
        :new-lot-value="null"
        :options="[
          { label: '登记退货新批次', value: null },
          ...(
            lotOptions?.lines.find(
              (item) => item.return_line_id === line.return_line_id,
            )?.lots ?? []
          ).map((lot) => ({
            label: `${lot.code} · ${physicalLotKindLabel(lot.source_kind)} · 剩余可退 ${lot.quantity}`,
            value: lot.lot_id,
          })),
        ]"
        :disabled="busy || connectionLost || lotLoading"
        @add="addLot(line)"
        @remove="(index) => line.lots.splice(index, 1)"
      >
        <span
          v-if="
            !lotOptions?.lines.find(
              (item) => item.return_line_id === line.return_line_id,
            )?.lots.length
          "
          >原出库未登记可退批次，须登记退货新批次；旧单据仍可在批次核对页追踪差额。</span
        >
      </WorkspaceLotLineEditor>

      </template>
    </WorkspaceLotDialog>
  </section>
</template>

<style scoped>
.return-lot-proof {
  display: block;
  color: var(--workspace-field-muted);
  overflow-wrap: anywhere;
}
</style>
