<script setup lang="ts">
import { useSalesDraftEditor } from '../../../composables/use-sales-draft-editor'
import { canReviseSalesDraft, newSalesFilters, matchesSalesFilters, shipmentDraftIssue } from '../../../utils/sales-documents'
import type { SalesDraftType } from '../../../../../shared/sales-draft-api'
import SalesDocumentList from './SalesDocumentList.vue'
import SalesDocumentDetail from './SalesDocumentDetail.vue'
import {defineAsyncComponent} from 'vue'
// 修订历史按需加载，日常列表不提前初始化弹窗和历史读取。
const SalesDraftHistory = defineAsyncComponent(()=>import('./SalesDraftHistory.vue'))

// 来源绑定在真实触发入口，键盘点击与鼠标点击共用同一回程位置。
import { captureDialogOrigin } from '../../../utils/dialog-origin'
// 复用公共物料资料的单行展开状态，新增或重选时收起其他行。
import { useDocumentMaterialDetails } from "../../../composables/use-document-material-details";
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
// 物料资料统一展示，候选范围和联动规则仍由当前业务决定。
import WorkspaceMaterialSelect from "../../../components/workspace/WorkspaceMaterialSelect.vue";
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
import { receiptLotMilli } from "../../../../../shared/receipt-lot-api.ts";
import { outboundAvailableMilli } from "../../../../../shared/outbound-lot-api.ts";
import { physicalLotKindLabel } from "../../../../../shared/physical-lot-api.ts";
import type {
  ShipmentLotLineInput,
  ShipmentLotOptions,
} from "../../../../../shared/shipment-lot-api";
import type { Stock, Shipment } from "../../../../../shared/erp-api";

// 页面直接使用共享状态与操作，切换标签时不会丢失正在填写的草稿。
const store = usePiniaAppStore();
const {
  error,
  notice,
  busy,
  connectionLost,
  materials,
  customers,
  warehouses,
  salesOrders,
  shipments,
  shipmentReversalReasons,
  shipmentForm,
} = storeToRefs(store);
const {
  can,
  localTime,
  createShipment,
  loadAvailableShipmentLots,
  postShipment,
  cancelShipment,
  reverseShipment,
} = store;

// 编号与查看先进入业务详情；审批保持独立入口，避免审批步骤遮住物料与金额。
const selectedId = ref<number | null>(null);
const businessDetail = computed(() => shipments.value.find(row => row.id === selectedId.value) ?? null);
function openBusinessDetail(row: Shipment): void {
  if (busy.value || connectionLost.value || !can('sales.view')) return;
  selectedId.value = row.id;
}
watch(() => `${store.server?.id}:${store.server?.fingerprint}:${store.user?.id}:${store.user?.permissions.join('|')}:${connectionLost.value}`, () => { selectedId.value = null; });
// 修订表单使用副本，原新建草稿继续保留在 Pinia 中。
const {open:createOpen, form:workingForm, target:editTarget, reason:revisionReason,
  isolated:isolatedForm, beginEdit, beginCreate} = useSalesDraftEditor(shipmentForm);
const historyTarget = ref<{type:SalesDraftType; id:number} | null>(null);
const filters = ref(newSalesFilters());
function editRecord(row: Shipment): void {
  if (beginEdit(row, {sales_order_id:row.sales_order_id, warehouse_id:row.warehouse_id, reference:row.reference, lines:row.lines.map(line=>({material_id:line.material_id,quantity:line.quantity}))})) { selectedId.value = null; store.closeDocumentApproval(); }
}
const selectedOrder = computed(()=>salesOrders.value.find(row=>row.id===workingForm.value.sales_order_id));
function selectShipmentOrder(): void {
  workingForm.value.lines = selectedOrder.value?.lines.filter(line=>Number(line.remaining_quantity)>0)
    .map(line=>({material_id:line.material_id,quantity:line.remaining_quantity})) ?? [];
}

// 库存快照只作填写提示，最终扣减仍由确认出库事务复核。
const stockRows = ref<Stock[] | null>(null), stockLoading = ref(false), stockError = ref('');
let stockRead = 0;
watch(()=>[createOpen.value,workingForm.value.warehouse_id,connectionLost.value,store.user?.id,
  store.user?.permissions.join('|')] as const, async ([open,warehouseId,lost])=>{
  const owner = ++stockRead; stockRows.value=null; stockError.value=''; stockLoading.value=false;
  if(!open || !warehouseId || lost || !can('inventory.view')) return;
  stockLoading.value=true;
  try {const rows=await store.loadShipmentStock(warehouseId); if(owner===stockRead)stockRows.value=rows;}
  catch(cause){if(owner===stockRead)stockError.value=displayError(cause);}
  finally{if(owner===stockRead)stockLoading.value=false;}
});
const shipmentIssue = computed(()=>shipmentDraftIssue(selectedOrder.value,workingForm.value.lines));
const orderMaterials = computed(()=>materials.value.filter(material=>selectedOrder.value?.lines.some(line=>line.material_id===material.id)));
function remainingFor(materialId:number): string {return selectedOrder.value?.lines.find(line=>line.material_id===materialId)?.remaining_quantity ?? '0';}
function stockFor(materialId:number): string | null {return stockRows.value===null?null:stockRows.value.find(row=>row.id===materialId)?.quantity ?? '0';}
function materialOptions(materialId:number) {
  return [{label:'选择订单物料',value:0,disabled:true},...orderMaterials.value.map(row=>({value:row.id,label:`${row.sku} · ${row.name}`,
    disabled: row.id!==materialId && (Number(remainingFor(row.id))<=0 || workingForm.value.lines.some(line=>line.material_id===row.id))}))];
}
function createReturnFromShipment(row:Shipment):void {
  selectedId.value = null; store.closeDocumentApproval();store.salesNavigation={action:'createReturn',sourceId:row.id};store.navigateToRoute('salesReturns');
}
watch(()=>[store.salesNavigation,store.activeTab] as const, ([request,route])=>{
  if(route!=='shipments' || request?.action!=='createShipment')return;
  store.salesNavigation=null;
  const source=salesOrders.value.find(row=>row.id===request.sourceId);
  if(!source || !['confirmed','partially_shipped'].includes(source.status)){error.value='订单已不处于可出库状态，请刷新后重试。';return;}
  beginCreate({sales_order_id:source.id,warehouse_id:shipmentForm.value.warehouse_id,reference:'',
    lines:source.lines.filter(line=>Number(line.remaining_quantity)>0).map(line=>({material_id:line.material_id,quantity:line.remaining_quantity}))});
}, {immediate:true});

// 详情弹窗由审批目标驱动；页脚业务按钮按当前单据与意图（执行/冲销）展示。
const detailItem = computed(() =>
  findDocumentApprovalItem(store.documentApprovalTarget, "Shipment", shipments.value),
);
const detailIntent = computed(
  () => store.documentApprovalTarget?.intent ?? "execute",
);


// 保存失败时保留弹窗和草稿，方便直接修正后重试。

const activeShipmentId = ref(0);
const lotOptions = ref<ShipmentLotOptions | null>(null);
const lotDrafts = ref<ShipmentLotLineInput[]>([]);
const lotLoading = ref(false);
const lotLoadError = ref("");
let loadTicket = 0;
const activeShipment = computed(
  () =>
    shipments.value.find(
      (item) =>
        item.id === activeShipmentId.value &&
        item.status === "draft" &&
        item.approval?.status === "approved",
    ) ?? null,
);

function closeLotPost(): void {
  loadTicket++;
  activeShipmentId.value = 0;
  lotOptions.value = null;
  lotDrafts.value = [];
}

async function startLotPost(shipment: Shipment): Promise<void> {
  const ticket = ++loadTicket;
  activeShipmentId.value = shipment.id;
  lotOptions.value = null;
  lotDrafts.value = [];
  lotLoadError.value = "";
  lotLoading.value = true;
  try {
    const result = await loadAvailableShipmentLots(shipment.id);
    if (ticket !== loadTicket || activeShipmentId.value !== shipment.id) return;
    if (
      result.warehouse_id !== shipment.warehouse_id ||
      result.lines.length !== shipment.lines.length ||
      result.lines.some(
        (line) =>
          !shipment.lines.some(
            (item) =>
              item.id === line.shipment_line_id &&
              item.material_id === line.material_id &&
              item.quantity === line.quantity,
          ),
      )
    )
      throw Error("可用批次与当前销售出库单不匹配，请刷新单据。");
    lotOptions.value = result;
    lotDrafts.value = shipment.lines.map((line) => ({
      shipment_line_id: line.id,
      lots: [{ lot_id: 0, quantity: line.quantity }],
    }));
  } catch (cause) {
    if (ticket === loadTicket) lotLoadError.value = displayError(cause);
  } finally {
    if (ticket === loadTicket) lotLoading.value = false;
  }
}

function addLot(line: ShipmentLotLineInput): void {
  if (line.lots.length < 20) line.lots.push({ lot_id: 0, quantity: "" });
}

const lotIssue = computed(() => {
  const shipment = activeShipment.value,
    options = lotOptions.value;
  if (!shipment || !options || lotDrafts.value.length !== shipment.lines.length)
    return "可用批次尚未读取。";
  for (const line of shipment.lines) {
    const draft = lotDrafts.value.find(
      (item) => item.shipment_line_id === line.id,
    );
    const available = options.lines.find(
      (item) => item.shipment_line_id === line.id,
    );
    if (!draft || !available || !draft.lots.length || draft.lots.length > 20)
      return "每条销售出库明细至少指定一个实物批次。";
    const ids = new Set<number>();
    let total = 0n;
    for (const part of draft.lots) {
      const candidate = available.lots.find(
        (item) => item.lot_id === part.lot_id,
      );
      if (!candidate || ids.has(part.lot_id))
        return `物料 ${line.sku} 的批次无效或重复。`;
      ids.add(part.lot_id);
      const quantity = receiptLotMilli(part.quantity);
      if (quantity === null)
        return "批次数量须大于零、最多三位小数且不超过一百万。";
      if (quantity > (outboundAvailableMilli(candidate.quantity) ?? 0n))
        return `批次 ${candidate.code} 的可用量不足，请重新读取。`;
      total += quantity;
    }
    if (total !== receiptLotMilli(line.quantity))
      return `物料 ${line.sku} 的批次数量之和须等于 ${line.quantity}。`;
  }
  return "";
});

async function confirmLotPost(): Promise<void> {
  const shipment = activeShipment.value;
  if (!shipment || lotIssue.value || busy.value || connectionLost.value) return;
  await postShipment(
    shipment.id,
    lotDrafts.value.map((line) => ({
      shipment_line_id: line.shipment_line_id,
      lots: line.lots.map((part) => ({
        lot_id: part.lot_id,
        quantity: part.quantity,
      })),
    })),
  );
  if (
    !shipments.value.some(
      (item) => item.id === shipment.id && item.status === "draft",
    )
  )
    closeLotPost();
}
async function submitCreate(): Promise<void> {
  if (editTarget.value) {
    const current = editTarget.value;
    if (await store.reviseSalesDraft('reviseShipment', {...workingForm.value, shipmentId:current.id,
      expected_version:current.version,revision_reason:revisionReason.value})) createOpen.value = false;
    return;
  }
  await submitCreateDialog(()=>createShipment(isolatedForm.value ?? undefined), {busy,error,notice}, createOpen);
}
// 只筛选当前列表快照，原有单据状态与跨页面草稿保持不变。
const recordQuery = ref("");
const filteredRecords = computed(() =>
  shipments.value.filter((item) =>
    matchesSalesFilters(item, salesOrders.value.find(order=>order.id===item.sales_order_id)?.customer_id, filters.value) && matchesRecordQuery(recordQuery.value, [
      documentSearch(item),
      item.id,
      item.customer_name,
      item.warehouse_name,
      item.created_by_name,
      item.reference,
      ...item.lines.map((line) => line.material_name),
    ]),
  ),
);
// 保留每个草稿行的引用，表格编辑不会改写成另一套临时表单。
const shipmentFormRows = computed(() => documentRows(workingForm.value.lines));
const shipmentFormColumns = [
  { key: "material", title: "物料 / 资料", width: "470" },
  { key: "unit", title: "单位", width: "70" },
  { key: "quantity", title: "出库数量", width: "150" },
  {key:"remaining",title:"订单剩余",width:"130"},
  {key:"stock",title:"所选仓库存",width:"170"},
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
      document_type: "Shipment",
      document_id: identifier,
      intent: "reverse",
    }))
  )
    return;
  const record = store.documentApprovalRecord;
  if (record?.status !== "approved" || !record.reversal_reason) return;
  shipmentReversalReasons.value[identifier] = record.reversal_reason;
  store.closeDocumentApproval();
  await reverseShipment(identifier);
}
// 资料展示绑定原草稿行引用，删除中间行不会展开到另一项物料。
const { activeLine, showLine, setCompact } = useDocumentMaterialDetails(() => workingForm.value.lines)
</script>

<template>
  <section class="stack">
    <SalesDocumentDetail :materials="materials" :record="businessDetail" kind="shipment" title="销售出库" :busy="busy" :disabled="connectionLost" :local-time="localTime" @close="selectedId=null">
      <template #actions>
        <AppButton v-if="businessDetail" size="small" :disabled="busy || connectionLost" @click.capture="captureDialogOrigin('document-approval',$event)"
          @click="store.openDocumentApproval({document_type:'Shipment',document_id:businessDetail.id,intent:'execute'})">单据审批</AppButton>

        <!-- 操作色表达业务含义：冲销红色、取消橙色、确认绿色、查看与编辑蓝色。 -->
        <template v-if="businessDetail">
          <AppButton size="small" v-if="can('sales_return.create') && businessDetail.status==='posted' && !businessDetail.reversal_id && businessDetail.lines.some(line=>Number(line.returnable_quantity)>0)" :disabled="busy || connectionLost" @click="createReturnFromShipment(businessDetail)">创建退货单</AppButton>
          <AppButton size="small" v-if="can('shipment.create') && canReviseSalesDraft(businessDetail)" :disabled="busy || connectionLost"
            @click.capture="captureDialogOrigin('SalesShipmentsView:form', $event)" @click="editRecord(businessDetail)">修订草稿</AppButton>
          <AppButton size="small" v-if="(businessDetail.draft_version ?? 0) > 0" :disabled="busy || connectionLost"
            @click="historyTarget={type:'Shipment',id:businessDetail.id}">修订记录</AppButton>
          <span v-if="businessDetail.status==='draft' && businessDetail.draft_edit_block_reason" class="muted">{{ businessDetail.draft_edit_block_reason }}</span>
          <AppButton size="small"
            tone="success"
            v-if="
              businessDetail.status === 'draft' &&
              businessDetail.approval?.status === 'approved' &&
              can('shipment.post')
            "
            type="button"
            variant="primary"
            :disabled="busy || connectionLost"
            @click="postShipment(businessDetail.id)"
            >确认出库</AppButton
          >
          <AppButton size="small"
            tone="info"
            v-if="
              businessDetail.status === 'draft' &&
              businessDetail.approval?.status === 'approved' &&
              can('shipment.post')
            "
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click.capture="captureDialogOrigin('SalesShipmentsView:lot', $event)" @click="startLotPost(businessDetail)"
            >指定实物批次（可选）</AppButton
          >
          <AppButton size="small"
            tone="warning"
            v-if="
              businessDetail.status === 'draft' &&
              !['submitted', 'approved'].includes(
                businessDetail.approval?.status ?? '',
              ) &&
              can('shipment.cancel')
            "
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click="cancelShipment(businessDetail.id)"
            >取消</AppButton
          >
          <!-- 冲销完成后仍可查批准人员和固定原因，查询入口沿用本单查看权限。 -->
          <AppButton size="small"
            tone="error"
            v-if="
              businessDetail.status === 'posted' &&
              (businessDetail.reversal_id || can('shipment.reverse'))
            "
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click.capture="captureDialogOrigin('document-approval', $event)" @click="
              store.openDocumentApproval({
                document_type: 'Shipment',
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
          <AppButton v-if="can('sales_return.create') && detailItem.status==='posted' && !detailItem.reversal_id && detailItem.lines.some(line=>Number(line.returnable_quantity)>0)" :disabled="busy || connectionLost" @click="createReturnFromShipment(detailItem)">创建退货单</AppButton>
          <AppButton v-if="can('shipment.create') && canReviseSalesDraft(detailItem)" :disabled="busy || connectionLost"
            @click.capture="captureDialogOrigin('SalesShipmentsView:form', $event)" @click="editRecord(detailItem)">修订草稿</AppButton>
          <AppButton v-if="(detailItem.draft_version ?? 0) > 0" :disabled="busy || connectionLost"
            @click="historyTarget={type:'Shipment',id:detailItem.id}">修订记录</AppButton>
          <span v-if="detailItem.status==='draft' && detailItem.draft_edit_block_reason" class="muted">{{ detailItem.draft_edit_block_reason }}</span>
          <AppButton
            tone="success"
            v-if="
              detailIntent === 'execute' &&
              detailItem.status === 'draft' &&
              detailItem.approval?.status === 'approved' &&
              can('shipment.post')
            "
            type="button"
            variant="primary"
            :disabled="busy || connectionLost"
            @click="postShipment(detailItem.id)"
            >确认出库</AppButton
          >
          <AppButton
            tone="info"
            v-if="
              detailIntent === 'execute' &&
              detailItem.status === 'draft' &&
              detailItem.approval?.status === 'approved' &&
              can('shipment.post')
            "
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click.capture="captureDialogOrigin('SalesShipmentsView:lot', $event)" @click="startLotPost(detailItem)"
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
              can('shipment.cancel')
            "
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click="cancelShipment(detailItem.id)"
            >取消</AppButton
          >
          <!-- 冲销完成后仍可查批准人员和固定原因，查询入口沿用本单查看权限。 -->
          <AppButton
            tone="error"
            v-if="
              detailIntent === 'execute' &&
              detailItem.status === 'posted' &&
              (detailItem.reversal_id || can('shipment.reverse'))
            "
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click.capture="captureDialogOrigin('document-approval', $event)" @click="
              store.openDocumentApproval({
                document_type: 'Shipment',
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
                document_type: 'Shipment',
                document_id: detailItem.id,
                intent: 'execute',
              })
            "
            >查看出库审批</AppButton
          >
          <AppButton
            tone="error"
            v-if="
              detailIntent === 'reverse' &&
              !detailItem.reversal_id &&
              detailItem.reversal_approval?.status === 'approved' &&
              can('shipment.reverse')
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
    <WorkspaceDocumentDialog origin-key="SalesShipmentsView:form" @invalidated="createOpen = false"
      v-if="can('shipment.create')"
      v-model:show="createOpen"
      :title="editTarget ? '修订销售出库' : '新建销售出库'"
      :data="shipmentFormRows"
      :columns="shipmentFormColumns"
      :busy="busy"
      :disabled="connectionLost"
      :submit-disabled="
        busy || !!shipmentIssue ||
        !materials.length ||
        !salesOrders.some((entry) =>
          ['confirmed', 'partially_shipped'].includes(entry.status),
        )
      "
      :submit-label="editTarget ? '保存修订' : '保存草稿'"
      :min-table-width="1000"
      :add-disabled="!selectedOrder || workingForm.lines.length >= selectedOrder.lines.filter(line=>Number(line.remaining_quantity)>0).length"
      @add-material="workingForm.lines.push({ material_id: 0, quantity: '1' })"
      @submit="submitCreate"
    >
      <template #basicInfo
        ><label
          >销售订单<WorkspaceSelect
            :disabled="busy || connectionLost"
            v-model="workingForm.sales_order_id"
            required
            @change="selectShipmentOrder"
            :options="[
              { label: '选择待出库订单'.trim(), value: 0, disabled: true },
              ...salesOrders
                .filter((entry) =>
                  ['confirmed', 'partially_shipped'].includes(entry.status),
                )
                .map((item) => ({
                  label: documentLabel(item) + ' · ' + item.customer_name,
                  value: item.id,
                })),
            ]" /></label
        ><label
          >出库仓库<WorkspaceSelect
            :disabled="busy || connectionLost"
            v-model="workingForm.warehouse_id"
            required
            :options="[
              ...warehouses.map((item) => ({
                label: item.name.trim(),
                value: item.id,
              })),
            ]" /></label
        ><label
          >参考单号（可选）<AppInput
            :disabled="busy || connectionLost"
            v-model.trim="workingForm.reference"
            maxlength="100"
        /></label>
        <label v-if="editTarget">修订原因<AppInput v-model.trim="revisionReason" required maxlength="200" :disabled="busy || connectionLost" /></label>
        <div class="document-basic-extra">
          <p v-if="shipmentIssue" role="status">{{ shipmentIssue }}</p>
          <p v-if="stockError" class="muted">{{ stockError }} 可切换仓库重新读取。</p>
          <p class="muted">
            可先保存缺货草稿；确认出库时会重新核对订单剩余量和仓库库存。
          </p>
        </div>
      </template>
      <template #cell-material="{ row: { line, index } }"
        ><!-- 标题由表头统一展示，控件保留逐行无障碍名称。 -->
            <WorkspaceMaterialSelect
                :aria-label="`第 ${index + 1} 行物料`"
            :disabled="busy || connectionLost"
            :materials="orderMaterials"
                :categories="store.materialCategories"
                :compact="activeLine !== line"
                @update:compact="(value) => setCompact(line, value)"
                @change="showLine(line)"
            v-model="line.material_id"
            required
:options="materialOptions(line.material_id)" /></template>
      <template #cell-quantity="{ row: { line, index } }"
        ><!-- 数量标题只在表头显示，数值边界和草稿绑定保持不变。 -->
            <AppInput
                :aria-label="`第 ${index + 1} 行出库数量`"
            :disabled="busy || connectionLost"
            v-model.trim="line.quantity"
            type="number"
            min="0.001"
            :max="remainingFor(line.material_id)"
            step="0.001"
            required /></template>
      <template #cell-remaining="{row:{line}}">{{ remainingFor(line.material_id) }}</template>
      <template #cell-stock="{row:{line}}">
        <span v-if="!can('inventory.view')">无查看权限</span><span v-else-if="stockLoading">读取中…</span>
        <span v-else-if="stockFor(line.material_id)===null">{{ stockError ? '读取失败' : '待选择仓库' }}</span>
        <span v-else>{{ stockFor(line.material_id) }}<span v-if="Number(line.quantity)>Number(stockFor(line.material_id))"> · 库存不足</span></span>
      </template>
      <template #cell-actions="{ row: { line, index } }"
        ><!-- 移除沿用主线完整点击区域，保留原有禁用与删行规则。 -->
        <AppButton size="small"
          type="button"
          :disabled="busy || connectionLost || workingForm.lines.length === 1"
          @click="workingForm.lines.splice(index, 1)"
          variant="secondary"
        >
          移除
        </AppButton></template
      >
      <template #cell-unit="{ row: { line } }">{{
        materials.find((item) => item.id === line.material_id)?.unit ?? "—"
      }}</template>
    </WorkspaceDocumentDialog>
    <!-- 列表复用生产计划的概览、查询、状态与分页，完整履约明细集中在详情。 -->
    <SalesDocumentList kind="shipment" title="销售出库" :records="shipments" :filtered="filteredRecords" :customers="customers"
      v-model:query="recordQuery" v-model:filters="filters" :disabled="busy || connectionLost" :local-time="localTime" @view="openBusinessDetail">
      <template #actions>
        <AppButton
          v-if="can('shipment.create')"
          type="button"
          :disabled="busy"
          @click.capture="captureDialogOrigin('SalesShipmentsView:form', $event)" @click="createOpen = true"
          variant="primary"
        >
          新建出库单
        </AppButton>
      </template>
    </SalesDocumentList>
    <!-- 批次登记统一使用公共弹窗和明细表，各业务仍保留原确认与校验逻辑。 -->
    <WorkspaceLotDialog origin-key="SalesShipmentsView:lot" @invalidated="closeLotPost()"
      v-if="can('shipment.post')"
      :show="!!activeShipment"
      title="销售出库 · 批次选择"
      :document-number="activeShipment ? documentLabel(activeShipment) : ''"
      :hint="
        '从 ' +
        activeShipment?.warehouse_name +
        ' 的实际可用批次逐行选择；历史未识别期初会明确标记，不能当作真实来料批号。'
      "
      :busy="busy"
      :disabled="connectionLost"
      :issue="lotIssue"
      submit-label="确认出库"
      :loading="lotLoading"
      :load-error="lotLoadError"
      @update:show="
        (value) => {
          if (!value) closeLotPost();
        }
      "
      @submit="confirmLotPost"
    >
      <template v-if="activeShipment">
      <WorkspaceLotLineEditor
        v-for="line in lotDrafts"
        :key="line.shipment_line_id"
        :lots="line.lots"
        :sku="
          activeShipment.lines.find((item) => item.id === line.shipment_line_id)
            ?.sku
        "
        :material-name="
          activeShipment.lines.find((item) => item.id === line.shipment_line_id)
            ?.material_name
        "
        :unit="
          activeShipment.lines.find((item) => item.id === line.shipment_line_id)
            ?.unit
        "
        :expected="
          activeShipment.lines.find((item) => item.id === line.shipment_line_id)
            ?.quantity ?? ''
        "
        expected-label="应出库"
        quantity-label="出库数量"
        :selectable="true"
        :options="[
          { label: '选择批次', value: 0, disabled: true },
          ...(
            lotOptions?.lines.find(
              (item) => item.shipment_line_id === line.shipment_line_id,
            )?.lots ?? []
          ).map((lot) => ({
            label: `${lot.code} · ${physicalLotKindLabel(lot.source_kind)} · 可用 ${lot.quantity}`,
            value: lot.lot_id,
          })),
        ]"
        :disabled="busy || connectionLost || lotLoading"
        @add="addLot(line)"
        @remove="(index) => line.lots.splice(index, 1)"
      />

      </template>
    </WorkspaceLotDialog>
  </section>
</template>

<style scoped>
.shipment-lot-proof {
  display: block;
  color: var(--workspace-field-muted);
  overflow-wrap: anywhere;
}
</style>
