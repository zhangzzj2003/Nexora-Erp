<script setup lang="ts">
import { useSalesDraftEditor } from '../../../composables/use-sales-draft-editor'
import { canReviseSalesDraft, newSalesFilters, matchesSalesFilters, salesAmountSummary, salesLineAmount } from '../../../utils/sales-documents'
import type { SalesDraftType } from '../../../../../shared/sales-draft-api'
import SalesDocumentList from './SalesDocumentList.vue'
import SalesDocumentDetail from './SalesDocumentDetail.vue'
import {defineAsyncComponent} from 'vue'
// 修订历史按需加载，日常列表不提前初始化弹窗和历史读取。
const SalesOrderClosureDialog = defineAsyncComponent(()=>import('./SalesOrderClosureDialog.vue'))
const SalesDraftHistory = defineAsyncComponent(()=>import('./SalesDraftHistory.vue'))

// 来源绑定在真实触发入口，键盘点击与鼠标点击共用同一回程位置。
import { captureDialogOrigin } from '../../../utils/dialog-origin'
import AppModal from '../../../components/app/AppModal.vue'
// 复用公共物料资料的单行展开状态，新增或重选时收起其他行。
import { useDocumentMaterialDetails } from "../../../composables/use-document-material-details";
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
// 物料资料统一展示，候选范围和联动规则仍由当前业务决定。
import WorkspaceMaterialSelect from "../../../components/workspace/WorkspaceMaterialSelect.vue";
// 单据统一使用固定关闭区、基础信息和物料明细表格。
import { documentRows } from "../../../utils/document-rows";
import WorkspaceDocumentDialog from "../../../components/workspace/WorkspaceDocumentDialog.vue";
import DocumentApprovalDialog from "../../../components/workspace/DocumentApprovalDialog.vue";
import SalesContractAttachments from "./SalesContractAttachments.vue";
import {
  matchesRecordQuery,
} from "../../../utils/workspace-records";
import { computed, ref, watch, onUnmounted } from "vue";

import type {
  SalesOrder,
  SalesOrderContract,
} from "../../../../../shared/erp-api";
import { storeToRefs } from "pinia";
import { usePiniaAppStore } from "../../../store/app-store";
import { submitCreateDialog } from "../../../utils/create-dialog";

// 页面直接使用共享状态与操作，切换标签时不会丢失正在填写的草稿。
const store = usePiniaAppStore();
const {
  error,
  notice,
  busy,
  connectionLost,
  user,
  materials,
  customers,
  salesOrders,
  salesForm,
} = storeToRefs(store);
const {
  can,
  localTime,
  navigateToRoute,
  createSalesOrder,
  loadSalesOrderContract,
  reviseSalesOrderContract,
  confirmSalesOrder,
  cancelSalesOrder,
} = store;

// 编号与查看先进入业务详情；审批保持独立入口，避免审批步骤遮住物料与金额。
const selectedId = ref<number | null>(null);
const businessDetail = computed(() => salesOrders.value.find(row => row.id === selectedId.value) ?? null);
function openBusinessDetail(row: SalesOrder): void {
  if (busy.value || connectionLost.value || !can('sales.view')) return;
  selectedId.value = row.id;
}
watch(() => `${store.server?.id}:${store.server?.fingerprint}:${store.user?.id}:${store.user?.permissions.join('|')}:${connectionLost.value}`, () => { selectedId.value = null; });
// 修订表单使用副本，原新建草稿继续保留在 Pinia 中。
const {open:createOpen, form:workingForm, target:editTarget, reason:revisionReason,
  isolated:isolatedForm, beginEdit, beginCreate} = useSalesDraftEditor(salesForm);
const historyTarget = ref<{type:SalesDraftType; id:number} | null>(null);
const filters = ref(newSalesFilters());
const closureTarget = ref<SalesOrder | null>(null);
function openClosure(row: SalesOrder): void {
  // 固定打开时的逐行实绩，保存时服务端再次核对，刷新不会悄悄改变用户确认的数量。
  error.value = "";
  selectedId.value = null;
  closureTarget.value = JSON.parse(JSON.stringify(row)) as SalesOrder;
  store.closeDocumentApproval();
}
function editRecord(row: SalesOrder): void {
  if (beginEdit(row, {customer_id:row.customer_id, reference:row.reference, lines:row.lines.map(line=>({material_id:line.material_id,quantity:line.quantity,unit_price:line.unit_price,warranty_days:line.warranty_days,warranty_basis:line.warranty_basis}))})) { selectedId.value = null; store.closeDocumentApproval(); }
}

// 详情弹窗由审批目标驱动；页脚业务按钮按当前单据与意图（执行/冲销）展示。
const detailItem = computed(() =>
  findDocumentApprovalItem(store.documentApprovalTarget, "SalesOrder", salesOrders.value),
);
const detailIntent = computed(
  () => store.documentApprovalTarget?.intent ?? "execute",
);


// 保存失败时保留弹窗和草稿，方便直接修正后重试。

const contractOpen = ref(false);
const contractLoading = ref(false);
const contractOrder = ref<SalesOrder | null>(null);
const contract = ref<SalesOrderContract | null>(null);
const contractBody = ref("");
const acceptanceReference = ref("");
const contractReason = ref("");
// 同一订单取消后重开也必须隔离请求，不能仅比较订单 ID。
let contractRead = 0;
watch(contractOpen, (open) => {
  if (!open) { contractRead++; contractLoading.value = false; }
}, { flush: "sync" });
onUnmounted(() => { contractRead++; });
watch(
  () =>
    `${user.value?.id}:${user.value?.permissions.join("|")}:${connectionLost.value}`,
  () => {
    contractOpen.value = false;
    contractOrder.value = null;
    contract.value = null;
    contractBody.value = "";
    acceptanceReference.value = "";
    contractReason.value = "";
  },
  { flush: "sync" },
);
async function openContract(order: SalesOrder): Promise<void> {
  const ticket = ++contractRead;
  error.value = "";
  contractOrder.value = order;
  contract.value = null;
  contractBody.value = "";
  acceptanceReference.value = "";
  contractReason.value = "";
  contractOpen.value = true;
  contractLoading.value = true;
  const result = await loadSalesOrderContract(order.id);
  if (ticket === contractRead && contractOpen.value && contractOrder.value?.id === order.id) {
    contract.value = result;
    contractBody.value = result?.current?.body ?? "";
    contractLoading.value = false;
  }
}
const contractEditable = computed(()=>{
  const latest = salesOrders.value.find(row=>row.id===contractOrder.value?.id);
  return !!latest && latest.status!=='cancelled' && !(latest.status==='draft' &&
    ['submitted','approved'].includes(latest.approval?.status ?? ''));
});
function createShipmentFromOrder(row: SalesOrder): void {
  selectedId.value = null; store.closeDocumentApproval();
  store.salesNavigation = {action:'createShipment',sourceId:row.id};
  store.navigateToRoute('shipments');
}
watch(()=>[store.salesNavigation,store.activeTab] as const, ([request,route])=>{
  if(route!=='sales' || request?.action!=='openOrder') return;
  store.salesNavigation=null;
  const row = salesOrders.value.find(item=>item.id===request.sourceId);
  if(row)openBusinessDetail(row);
}, {immediate:true});
async function submitContract(): Promise<void> {
  const order = contractOrder.value;
  const current = contract.value;
  if (!order || !current || !contractEditable.value) return;
  const saved = await reviseSalesOrderContract(
    order.id,
    current.version,
    contractBody.value,
    acceptanceReference.value,
    contractReason.value,
  );
  if (saved && contractOpen.value && contractOrder.value?.id === order.id) {
    contract.value = saved;
    acceptanceReference.value = "";
    contractReason.value = "";
  }
}
async function submitCreate(): Promise<void> {
  if (editTarget.value) {
    const current = editTarget.value;
    if (await store.reviseSalesDraft('reviseSalesOrder', {...workingForm.value, orderId:current.id,
      expected_version:current.version,revision_reason:revisionReason.value})) createOpen.value = false;
    return;
  }
  await submitCreateDialog(()=>createSalesOrder(isolatedForm.value ?? undefined), {busy,error,notice}, createOpen);
}
// 导航前关闭弹窗，订单草稿继续保存在共享状态中，返回后可继续填写。
function openCustomers(): void {
  createOpen.value = false;
  navigateToRoute("customers");
}
// 只筛选当前列表快照，原有单据状态与跨页面草稿保持不变。
const recordQuery = ref("");
const filteredRecords = computed(() =>
  salesOrders.value.filter((item) =>
    matchesSalesFilters(item, item.customer_id, filters.value) && matchesRecordQuery(recordQuery.value, [
      documentSearch(item),
      item.id,
      item.customer_name,
      item.created_by_name,
      item.reference,
      ...item.lines.map((line) => line.material_name),
    ]),
  ),
);
// 保留每个草稿行的引用，表格编辑不会改写成另一套临时表单。
const salesFormRows = computed(() => documentRows(workingForm.value.lines));
const amountSummary = computed(()=>salesAmountSummary(workingForm.value.lines));
const salesFormColumns = [
  { key: "material", title: "物料 / 资料", width: "470" },
  { key: "unit", title: "单位", width: "70" },
  { key: "quantity", title: "数量", width: "150" },
  { key: "unitPrice", title: "单价（元）", width: "150" },
  { key: "lineTotal", title: "金额（元）", width: "140" },
  { key: "warrantyDays", title: "约定保修天数", width: "150" },
  { key: "warrantyBasis", title: "合同或承诺依据", width: "220" },
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
// 资料展示绑定原草稿行引用，删除中间行不会展开到另一项物料。
const { activeLine, showLine, setCompact } = useDocumentMaterialDetails(() => workingForm.value.lines)
</script>

<template>
  <section class="stack">
    <SalesDocumentDetail :materials="materials" :record="businessDetail" kind="order" title="销售订单" :busy="busy" :disabled="connectionLost" :local-time="localTime" @close="selectedId=null">
      <template #actions>
        <AppButton v-if="businessDetail" size="small" :disabled="busy || connectionLost" @click.capture="captureDialogOrigin('document-approval',$event)"
          @click="store.openDocumentApproval({document_type:'SalesOrder',document_id:businessDetail.id,intent:'execute'})">单据审批</AppButton>

        <!-- 操作色表达业务含义：冲销红色、取消橙色、确认绿色、查看与编辑蓝色。 -->
        <template v-if="businessDetail">
          <AppButton size="small" v-if="can('sales_order.cancel') && businessDetail.status === 'partially_shipped' && businessDetail.closure === null"
            tone="warning" :disabled="busy || connectionLost" @click="openClosure(businessDetail)">终止剩余交付</AppButton>
          <AppButton size="small" v-if="businessDetail.closure" :disabled="busy" @click="openClosure(businessDetail)">终止记录</AppButton>
          <AppButton size="small" v-if="can('shipment.create') && ['confirmed','partially_shipped'].includes(businessDetail.status)" :disabled="busy || connectionLost" @click="createShipmentFromOrder(businessDetail)">创建出库单</AppButton>
          <AppButton size="small" v-if="can('sales_order.create') && canReviseSalesDraft(businessDetail)" :disabled="busy || connectionLost"
            @click.capture="captureDialogOrigin('SalesOrdersView:form', $event)" @click="editRecord(businessDetail)">修订草稿</AppButton>
          <AppButton size="small" v-if="(businessDetail.draft_version ?? 0) > 0" :disabled="busy || connectionLost"
            @click="historyTarget={type:'SalesOrder',id:businessDetail.id}">修订记录</AppButton>
          <span v-if="businessDetail.status==='draft' && businessDetail.draft_edit_block_reason" class="muted">{{ businessDetail.draft_edit_block_reason }}</span>
          <AppButton size="small"
            tone="info"

            type="button"
            variant="secondary"
            :disabled="busy"
            @click.capture="captureDialogOrigin('SalesOrdersView:contract', $event)" @click="openContract(businessDetail)"
            >合同正文</AppButton
          >
          <AppButton size="small"
            tone="success"
            v-if="
              businessDetail.status === 'draft' &&
              businessDetail.approval?.status === 'approved' &&
              can('sales_order.confirm')
            "
            type="button"
            variant="primary"
            :disabled="busy || connectionLost"
            @click="confirmSalesOrder(businessDetail.id)"
            >确认订单</AppButton
          >
          <AppButton size="small"
            tone="warning"
            v-if="
              ['draft', 'confirmed'].includes(businessDetail.status) &&
              !['submitted', 'approved'].includes(
                businessDetail.approval?.status ?? '',
              ) &&
              can('sales_order.cancel')
            "
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click="cancelSalesOrder(businessDetail.id)"
            >取消订单</AppButton
          >
        </template>

      </template>
    </SalesDocumentDetail>

    <!-- 业务操作统一在详情页脚办理；审批控件与关闭由公共弹窗承载。 -->
    <DocumentApprovalDialog origin-key="document-approval">
      <template #footerActions>
        <!-- 操作色表达业务含义：冲销红色、取消橙色、确认绿色、查看与编辑蓝色。 -->
        <template v-if="detailItem">
          <AppButton v-if="can('sales_order.cancel') && detailItem.status === 'partially_shipped' && detailItem.closure === null"
            tone="warning" :disabled="busy || connectionLost" @click="openClosure(detailItem)">终止剩余交付</AppButton>
          <AppButton v-if="detailItem.closure" :disabled="busy" @click="openClosure(detailItem)">终止记录</AppButton>
          <AppButton v-if="can('shipment.create') && ['confirmed','partially_shipped'].includes(detailItem.status)" :disabled="busy || connectionLost" @click="createShipmentFromOrder(detailItem)">创建出库单</AppButton>
          <AppButton v-if="can('sales_order.create') && canReviseSalesDraft(detailItem)" :disabled="busy || connectionLost"
            @click.capture="captureDialogOrigin('SalesOrdersView:form', $event)" @click="editRecord(detailItem)">修订草稿</AppButton>
          <AppButton v-if="(detailItem.draft_version ?? 0) > 0" :disabled="busy || connectionLost"
            @click="historyTarget={type:'SalesOrder',id:detailItem.id}">修订记录</AppButton>
          <span v-if="detailItem.status==='draft' && detailItem.draft_edit_block_reason" class="muted">{{ detailItem.draft_edit_block_reason }}</span>
          <AppButton
            tone="info"
            v-if="detailIntent === 'execute'"
            type="button"
            variant="secondary"
            :disabled="busy"
            @click.capture="captureDialogOrigin('SalesOrdersView:contract', $event)" @click="openContract(detailItem)"
            >合同正文</AppButton
          >
          <AppButton
            tone="success"
            v-if="
              detailIntent === 'execute' &&
              detailItem.status === 'draft' &&
              detailItem.approval?.status === 'approved' &&
              can('sales_order.confirm')
            "
            type="button"
            variant="primary"
            :disabled="busy || connectionLost"
            @click="confirmSalesOrder(detailItem.id)"
            >确认订单</AppButton
          >
          <AppButton
            tone="warning"
            v-if="
              detailIntent === 'execute' &&
              ['draft', 'confirmed'].includes(detailItem.status) &&
              !['submitted', 'approved'].includes(
                detailItem.approval?.status ?? '',
              ) &&
              can('sales_order.cancel')
            "
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click="cancelSalesOrder(detailItem.id)"
            >取消订单</AppButton
          >
        </template>
      </template>
    </DocumentApprovalDialog>
    <SalesOrderClosureDialog v-if="closureTarget" v-model="closureTarget" />
    <SalesDraftHistory v-if="historyTarget" v-model="historyTarget" />
    <AppModal :busy="busy" origin-key="SalesOrdersView:contract" @invalidated="contractOpen = false" :ready="!contractLoading && !!contract" :load-error="error"
      v-model:show="contractOpen"
      preset="card"
      title="销售合同正文与修订历史"
      :mask-closable="!busy"
      :closable="!busy"
      :style="{
        width: 'min(900px, calc(100vw - 32px))',
        maxHeight: 'calc(100vh - 48px)',
        overflowY: 'auto',
      }"
    >
      <template v-if="contractOrder">
        <p>
          销售订单 {{ documentLabel(contractOrder) }} ·
          {{
            contractOrder.customer_name
          }}。正文登记是合同证据；不会自动修改订单金额、明细保修条款或既有售后单。
        </p>
        <p v-if="contractLoading">正在读取合同历史…</p>
        <template v-else-if="contract">
          <p v-if="contract.version === 0">
            尚未登记合同正文。旧订单不追认未知条款。
          </p>
          <p v-if="contractOrder.status==='draft' && !contractEditable" class="muted">单据正在审批或已批准，请先撤回审批，再修订合同正文。</p>
          <form
            v-if="
              can('sales_order.confirm') && contractEditable
            "
            class="contract-form"
            @submit.prevent="submitContract"
          >
            <label
              >合同全文<AppInput
                v-model="contractBody"
                type="textarea"
                rows="12"
                maxlength="20000"
                required
                :disabled="busy"
            /></label>
            <label
              >客户确认依据<AppInput
                v-model.trim="acceptanceReference"
                maxlength="400"
                required
                :disabled="busy"
                placeholder="签署件、邮件或确认记录编号"
            /></label>
            <label
              >登记或修订原因<AppInput
                v-model.trim="contractReason"
                maxlength="200"
                required
                :disabled="busy"
            /></label>
            <AppButton
              type="submit"
              variant="primary"
              :disabled="
                busy ||
                !contractBody.trim() ||
                !acceptanceReference.trim() ||
                !contractReason.trim()
              "
              >追加第 {{ contract.version + 1 }} 版</AppButton
            >
          </form>
          <p v-if="error" role="alert">
            {{ error }}；输入已保留，请重新打开合同核对最新版本。
          </p>
          <h3>历史版本</h3>
          <div
            v-for="revision in contract.history"
            :key="revision.id"
            class="contract-revision"
          >
            <p>
              <strong>第 {{ revision.version }} 版</strong> ·
              {{ localTime(revision.created_at) }} ·
              {{ revision.created_by_name }}
            </p>
            <p>
              客户确认依据：{{ revision.acceptance_reference }} · 原因：{{
                revision.reason
              }}
            </p>
            <pre>{{ revision.body }}</pre>
            <SalesContractAttachments
              :order-id="contract.sales_order_id"
              :revision-id="revision.id"
              :version="revision.version"
            />
          </div>
        </template>
      </template>
    </AppModal>
    <!-- 共用基础信息与物料表格布局；行对象仍指向原 Pinia 草稿，保留业务字段和来源约束。 -->
    <WorkspaceDocumentDialog origin-key="SalesOrdersView:form" @invalidated="createOpen = false"
      v-if="can('sales_order.create')"
      v-model:show="createOpen"
      :title="editTarget ? '修订销售订单' : '新建销售订单'"
      :data="salesFormRows"
      :columns="salesFormColumns"
      :amount-total="amountSummary.total"
      :busy="busy"
      :disabled="connectionLost"
      :submit-disabled="!customers.length || !materials.length"
      :submit-label="editTarget ? '保存修订' : '保存草稿'"
      :min-table-width="1000"
      :add-disabled="workingForm.lines.length >= 100"
      @add-material="
        workingForm.lines.push({
          material_id: 0,
          quantity: '1',
          unit_price: '0',
          warranty_days: null,
          warranty_basis: '',
        })
      "
      @submit="submitCreate"
    >
      <template #basicInfo
        ><label
          >客户<WorkspaceSelect
            :disabled="busy || connectionLost"
            v-model="workingForm.customer_id"
            required
            :options="[
              { label: '选择客户'.trim(), value: 0, disabled: true },
              ...customers.map((item) => ({
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
          <p v-if="amountSummary.zeroCount" class="muted">有 {{ amountSummary.zeroCount }} 行单价为零，请确认是否为赠品或不收费项目。</p>
          <div class="form-actions">
            <span v-if="!customers.length" class="muted"
              >暂无客户，请先建立客户资料。</span
            >
            <AppButton
              type="button"
              :disabled="busy || connectionLost || busy"
              @click="openCustomers"
              variant="text"
            >
              前往客户资料
            </AppButton>
            <span class="muted">订单草稿会保留，返回后可继续填写。</span>
          </div>
        </div>
      </template>
      <template #cell-material="{ row: { line, index } }"
        ><!-- 标题由表头统一展示，控件保留逐行无障碍名称。 -->
            <WorkspaceMaterialSelect use="can_sell"
                :aria-label="`第 ${index + 1} 行物料`"
            :disabled="busy || connectionLost"
            :materials="materials"
                :categories="store.materialCategories"
                :compact="activeLine !== line"
                @update:compact="(value) => setCompact(line, value)"
                @change="showLine(line)"
            v-model="line.material_id"
            required
            :options="[
              { label: '选择物料'.trim(), value: 0, disabled: true },
              ...materials.map((item) => ({
                label: (item.sku + ' · ' + item.name).trim(),
                value: item.id,
              })),
            ]" /></template>
      <template #cell-quantity="{ row: { line, index } }"
        ><!-- 数量标题只在表头显示，数值边界和草稿绑定保持不变。 -->
            <AppInput
                :aria-label="`第 ${index + 1} 行数量`"
            :disabled="busy || connectionLost"
            v-model.trim="line.quantity"
            type="number"
            min="0.001"
            max="1000000"
            step="0.001"
            required /></template>
      <template #cell-unitPrice="{ row: { line, index } }"
        ><AppInput :aria-label="`第 ${index + 1} 行单价`"
            :disabled="busy || connectionLost"
            v-model.trim="line.unit_price"
            type="number"
            min="0"
            max="1000000000"
            step="0.0001"
            required /></template>
      <template #cell-lineTotal="{row:{line}}">{{ salesLineAmount(line) || '待完善' }}</template>
      <template #cell-warrantyDays="{ row: { line, index } }"
        ><AppInput :aria-label="`第 ${index + 1} 行约定保修天数（可留空）`"
            :disabled="busy || connectionLost"
            :model-value="
              line.warranty_days === null ? '' : String(line.warranty_days)
            "
            type="number"
            min="1"
            max="36500"
            step="1"
            @update:model-value="
              line.warranty_days = $event === '' ? null : Number($event)
            " /></template>
      <template #cell-warrantyBasis="{ row: { line, index } }"
        ><AppInput :aria-label="`第 ${index + 1} 行合同或承诺依据`"
            :disabled="busy || connectionLost"
            v-model.trim="line.warranty_basis"
            maxlength="400"
            :required="line.warranty_days !== null" /></template>
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
    <SalesDocumentList kind="order" title="销售订单" :records="salesOrders" :filtered="filteredRecords" :customers="customers"
      v-model:query="recordQuery" v-model:filters="filters" :disabled="busy || connectionLost" :local-time="localTime" @view="openBusinessDetail">
      <template #actions>
        <AppButton
          v-if="can('sales_order.create')"
          type="button"
          :disabled="busy"
          @click.capture="captureDialogOrigin('SalesOrdersView:form', $event)" @click="createOpen = true"
          variant="primary"
        >
          新建销售订单
        </AppButton>
      </template>
    </SalesDocumentList>
  </section>
</template>

<style scoped>
.contract-form {
  display: grid;
  gap: 12px;
  margin: 16px 0;
}
.contract-revision {
  border-top: 1px solid var(--border-color, #d8dce2);
  padding: 12px 0;
}
.contract-revision pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font: inherit;
}
</style>
