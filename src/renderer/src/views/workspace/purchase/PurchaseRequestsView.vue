<script setup lang="ts">
// 来源绑定在真实触发入口，键盘点击与鼠标点击共用同一回程位置。
import { captureDialogOrigin } from '../../../utils/dialog-origin'
// 详情页脚按类型与 ID 双重定位，避免跨页面同号单据串单。
import { findDocumentApprovalItem } from "../../../utils/document-approval-item";
// 采购申请、转单与直接采购共用计价输入和十进制计算，保留原草稿行。
import WorkspacePurchasePriceInput from '../../../components/workspace/WorkspacePurchasePriceInput.vue'
import { sumMoney } from '../../../utils/money-summary'
import { newPurchasePriceLine, recalculatePurchasePrice } from '../../../utils/purchase-pricing'
import { useDocumentMaterialDetails } from '../../../composables/use-document-material-details'

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
import { computed, ref } from "vue";
import { storeToRefs } from "pinia";
import { NPopconfirm } from "naive-ui";
// 单据统一使用固定关闭区、基础信息和物料明细表格。
import { documentRows } from "../../../utils/document-rows";
import type { WorkspaceTableColumn } from "../../../utils/table-columns";
import WorkspaceDocumentDialog from "../../../components/workspace/WorkspaceDocumentDialog.vue";
import WorkspaceTable from "../../../components/workspace/WorkspaceTable.vue";
// 统一弹窗读取真实版本和审批历史，不在列表保留另一套批准操作。
import DocumentApprovalDialog from "../../../components/workspace/DocumentApprovalDialog.vue";
import type { PurchaseRequest } from "../../../../../shared/erp-api";
import { usePiniaAppStore } from "../../../store/app-store";
import { submitCreateDialog } from "../../../utils/create-dialog";

const store = usePiniaAppStore();
const {
  busy,
  error,
  notice,
  connectionLost,
  materials,
  suppliers,
  purchaseRequests,
  purchaseRequestForm,
  requestConversionForm,
} = storeToRefs(store);
const {
  can,
  localTime,
  editPurchaseRequest,
  savePurchaseRequest,
  cancelPurchaseRequest,
  selectRequestConversion,
  convertPurchaseRequest,
} = store;
const query = ref("");
const showForm = ref(false);
const conversionOpen = ref(false);
const filtered = computed(() =>
  purchaseRequests.value.filter((item) =>
    [
      documentSearch(item),
      item.id,
      item.reference,
      item.note,
      item.status,
      ...item.lines.map((line) => line.material_name),
    ]
      .join(" ")
      .toLowerCase()
      .includes(query.value.trim().toLowerCase()),
  ),
);
const selectedRequest = computed(() =>
  purchaseRequests.value.find(
    (item) => item.id === requestConversionForm.value.requestId,
  ),
);
// 详情弹窗由审批目标驱动；页脚业务按钮按当前单据与意图（执行/冲销）展示。
const detailItem = computed(() =>
  findDocumentApprovalItem(store.documentApprovalTarget, "PurchaseRequest", purchaseRequests.value),
);
const detailIntent = computed(
  () => store.documentApprovalTarget?.intent ?? "execute",
);
const columns: readonly WorkspaceTableColumn[] = [
  { key: "id", title: "申请" },
  { key: "status", title: "状态" },
  { key: "lines", title: "明细与待转数量" },
  { key: "actions", title: "查看", width: "72", align: "center" },
];
const statusName = {
  draft: "草稿",
  submitted: "待审批",
  approved: "已批准",
  rejected: "已驳回",
  cancelled: "已取消",
};

const approvalNames = {
  draft: "未送审",
  submitted: "审批中",
  approved: "已批准，待转单",
  rejected: "已驳回",
  withdrawn: "已撤回",
  executed: "已开始转单",
};
// 拆单可以继续消费同一份批准需求，每张新订单仍独立送审；缺少审批状态时不放行。
function canConvert(item: PurchaseRequest): boolean {
  return (
    item.status === "approved" &&
    ["approved", "executed"].includes(item.approval?.status ?? "") &&
    item.lines.some((line) => Number(line.remaining_quantity) > 0) &&
    can("purchase_order.create")
  );
}
const conversionAllowed = computed(
  () => !!selectedRequest.value && canConvert(selectedRequest.value),
);

function openEditor(requestId?: number): void {
  // 收起后再次打开同一份草稿不重新初始化；切换新单或其他申请才载入对应表单。
  if (purchaseRequestForm.value.requestId !== (requestId ?? null))
    editPurchaseRequest(requestId);
  showForm.value = true;
}

function openConversion(requestId: number): void {
  const item = purchaseRequests.value.find((row) => row.id === requestId);
  if (!item || !canConvert(item) || busy.value || connectionLost.value) return;
  selectRequestConversion(requestId);
  conversionOpen.value = true;
}

async function submitConversion(): Promise<void> {
  // 弹窗打开后发生撤回或权限变化，也不能提交过期的批准。
  if (!conversionAllowed.value || busy.value || connectionLost.value) return;
  await submitCreateDialog(
    convertPurchaseRequest,
    { busy, error, notice },
    conversionOpen,
  );
}

async function save(): Promise<void> {
  await savePurchaseRequest();
  // 写入失败时保留输入；只有服务端刷新后的申请已存在才关闭表单。
  if (!store.error && !store.connectionLost) showForm.value = false;
}
// 保留每个草稿行的引用，表格编辑不会改写成另一套临时表单。
const purchaseRequestFormTotal = computed(() => sumMoney(purchaseRequestForm.value.lines.map(line => line.unit_price === '' ? '' : line.line_total)))
const purchaseRequestFormRows = computed(() => documentRows(purchaseRequestForm.value.lines))
const purchaseRequestFormColumns: readonly WorkspaceTableColumn[] = [
  { key: 'material', title: '物料 / 资料', width: '330' },
  { key: 'unit', title: '单位', width: '60' },
  { key: 'quantity', title: '申请数量', width: '110' },
  { key: 'unitPrice', title: '单价（元）', width: '150' },
  { key: 'actions', title: '操作', width: '80' },
  // 总价采用紧凑列宽，保留右侧固定；长金额可点击进入输入框查看和编辑。
  { key: 'lineTotal', title: '总价（元）', width: '120', fixed: 'right', align: 'right' },
]
// 保留每个草稿行的引用，表格编辑不会改写成另一套临时表单。
const requestConversionFormTotal = computed(() => sumMoney(requestConversionForm.value.lines.filter(line => Number(line.quantity) > 0).map(line => line.unit_price === '' ? '' : line.line_total)))
const requestConversionFormRows = computed(() => documentRows(requestConversionForm.value.lines))
const requestConversionFormColumns: readonly WorkspaceTableColumn[] = [
  { key: 'material', title: '物料', width: '300' },
  { key: 'quantity', title: '本次数量', width: '150' },
  { key: 'unitPrice', title: '单价（元）', width: '150' },
  // 总价采用紧凑列宽，保留右侧固定；长金额可点击进入输入框查看和编辑。
  { key: 'lineTotal', title: '总价（元）', width: '120', fixed: 'right', align: 'right' },
]
// 新增或查看另一行时自动收起上一行；用对象引用避免删除中间行后展开错料。
const { activeLine, showLine, setCompact } = useDocumentMaterialDetails(() => purchaseRequestForm.value.lines)
function addPricedMaterial(): void {
  if (busy.value || connectionLost.value || purchaseRequestForm.value.lines.length >= 100) return
  const line = newPurchasePriceLine()
  purchaseRequestForm.value.lines.push(line)
  showLine(purchaseRequestForm.value.lines.at(-1)!)
}
</script>

<template>
  <section class="stack">
    <!-- 业务操作统一在详情页脚办理；审批控件与关闭由公共弹窗承载。 -->
    <DocumentApprovalDialog origin-key="document-approval">
      <template #footerActions>
        <!-- 操作色表达业务含义：冲销红色、取消橙色、确认绿色、查看与编辑蓝色。 -->
        <template v-if="detailItem">
          <AppButton
            tone="info"
            v-if="
              detailIntent === 'execute' &&
              ['draft', 'rejected'].includes(detailItem.status) &&
              can('purchase_request.create')
            "
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click.capture="captureDialogOrigin('PurchaseRequestsView:form', $event)" @click="openEditor(detailItem.id)"
            >修改</AppButton
          >
          <AppButton
            tone="info"
            v-if="detailIntent === 'execute' && canConvert(detailItem)"
            type="button"
            variant="primary"
            :disabled="busy || connectionLost"
            @click.capture="captureDialogOrigin('PurchaseRequestsView:conversion', $event)" @click="openConversion(detailItem.id)"
            >转订单</AppButton
          >
          <NPopconfirm
            v-if="
              detailIntent === 'execute' &&
              detailItem.status !== 'cancelled' &&
              !['submitted', 'approved'].includes(
                detailItem.approval?.status ?? '',
              ) &&
              can('purchase_request.cancel')
            "
            positive-text="确认"
            negative-text="返回"
            @positive-click="cancelPurchaseRequest(detailItem.id)"
          >
            <template #trigger
              ><AppButton
            tone="warning"
                :disabled="busy || connectionLost"
                variant="secondary"
                type="button"
                >取消申请</AppButton
              ></template
            >
            已关联有效订单的申请无法取消。确认取消这张申请？
          </NPopconfirm>
        </template>
      </template>
    </DocumentApprovalDialog>
    <!-- 列表保留操作与筛选，页面标题在卡片外统一显示。 -->
    <WorkspaceTable
      :show-title="false"
      :data="filtered"
      title="采购申请"
      :columns="columns"
      :min-table-width="940"
    >
      <template #actions>
        <AppButton
          v-if="can('purchase_request.create')"
          :disabled="busy || connectionLost || !materials.length"
          @click.capture="captureDialogOrigin('PurchaseRequestsView:form', $event)" @click="openEditor()"
          variant="primary"
          type="button"
          >新建采购申请</AppButton
        >
      </template>
      <template #filters>
        <label
          >搜索申请<AppInput v-model="query" placeholder="单号、物料或状态"
        /></label>
      </template>
      <template #beforeTable>
        <!-- 共用基础信息与物料表格布局；行对象仍指向原 Pinia 草稿，保留业务字段和来源约束。 -->
        <WorkspaceDocumentDialog origin-key="PurchaseRequestsView:form" @invalidated="showForm = false"
          material-supply
          v-if="can('purchase_request.create')"
          v-model:show="showForm"
          :title="
            purchaseRequestForm.requestId ? '修改采购申请' : '新建采购申请'
          "
          :data="purchaseRequestFormRows"
          :columns="purchaseRequestFormColumns"
          :amount-total="purchaseRequestFormTotal"
          :busy="busy"
          :disabled="connectionLost"
          :submit-disabled="connectionLost"
          submit-label="保存草稿"
          :min-table-width="1200"
          :add-disabled="purchaseRequestForm.lines.length >= 100"
          @add-material="addPricedMaterial"
          @submit="save"
        >
          <template #basicInfo
            ><label
              >参考单号<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="purchaseRequestForm.reference"
                maxlength="100"
            /></label>
            <label
              >采购说明<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="purchaseRequestForm.note"
                maxlength="500"
            /></label>
          </template>
          <template #cell-material="{ row: { line, index } }"
            ><!-- 标题由表头统一展示，控件保留逐行无障碍名称。 -->
            <WorkspaceMaterialSelect
                :aria-label="`第 ${index + 1} 行物料`"
                :disabled="busy || connectionLost"
                :materials="materials"
                :categories="store.materialCategories"
                v-model="line.material_id"
                :compact="activeLine !== line"
                @update:compact="(value) => setCompact(line, value)"
                @change="showLine(line)"
                required
                :options="[
                  { label: '选择物料', value: 0, disabled: true },
                  ...materials.map((item) => ({
                    label: (item.sku + ' · ' + item.name).trim(),
                    value: item.id,
                  })),
                ]" /></template>
          <!-- 隐藏数量步进箭头，仍保留原生数字类型、精度和范围校验。 -->
          <template #cell-quantity="{ row: { line, index } }"
            ><AppInput
                aria-label="申请数量"
                :disabled="busy || connectionLost"
                :model-value="line.quantity"
                @update:model-value="(value) => { line.quantity = value; recalculatePurchasePrice(line) }"
                type="number"
                hide-number-controls
                min="0.001"
                max="1000000"
                step="0.001"
                required /></template>
          <template #cell-unitPrice="{ row: { line } }">
            <WorkspacePurchasePriceInput field="unit_price" :line="line" :disabled="busy || connectionLost" />
          </template>
          <template #cell-lineTotal="{ row: { line } }">
            <WorkspacePurchasePriceInput field="line_total" :line="line" :disabled="busy || connectionLost" />
          </template>
          <template #cell-actions="{ row: { line, index } }"
            ><!-- 移除使用公共按钮的完整点击区域，原有禁用与删行规则保持。 -->
            <AppButton size="small"
              type="button"
              :disabled="
                busy || connectionLost || purchaseRequestForm.lines.length === 1
              "
              @click="purchaseRequestForm.lines.splice(index, 1)"
              variant="secondary"
              >移除</AppButton
            ></template
          >
          <template #cell-unit="{ row: { line } }">{{
            materials.find((item) => item.id === line.material_id)?.unit ?? "—"
          }}</template>
        </WorkspaceDocumentDialog>
        <!-- 共用基础信息与物料表格布局；行对象仍指向原 Pinia 草稿，保留业务字段和来源约束。 -->
        <WorkspaceDocumentDialog origin-key="PurchaseRequestsView:conversion" @invalidated="conversionOpen = false"
          material-supply
          v-if="can('purchase_order.create')"
          v-model:show="conversionOpen"
          :title="`申请 ${selectedRequest ? documentLabel(selectedRequest) : ''} 转采购订单`"
          :data="requestConversionFormRows"
          :columns="requestConversionFormColumns"
          :amount-total="requestConversionFormTotal"
          :busy="busy"
          :disabled="connectionLost"
          :submit-disabled="
            busy ||
            connectionLost ||
            !conversionAllowed ||
            !requestConversionForm.lines.some(
              (line) => Number(line.quantity) > 0,
            )
          "
          submit-label="生成订单草稿"
          :min-table-width="1000"
          :show-add="false"
          empty-text="请先选择来源单据，系统将载入可处理的物料明细。"
          @submit="submitConversion"
        >
          <template #basicInfo
            ><label
              >供应商<WorkspaceSelect
                :disabled="busy || connectionLost"
                v-model="requestConversionForm.supplier_id"
                required
                :options="[
                  { label: '选择供应商', value: 0, disabled: true },
                  ...suppliers.map((item) => ({
                    label: item.name,
                    value: item.id,
                  })),
                ]"
            /></label>
            <label
              >参考单号<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="requestConversionForm.reference"
                maxlength="100"
            /></label>
            <div class="document-basic-extra">
              <p class="muted">
                本批不采购的明细填 0；可再次从剩余数量生成其他订单。
              </p>
            </div>
          </template>
          <template #cell-material="{ row: { line, index } }"
            ><span>{{
              selectedRequest?.lines.find(
                (item) => item.id === line.purchase_request_line_id,
              )?.material_name
            }}</span></template
          >
          <!-- 隐藏数量步进箭头，仍保留原生数字类型、精度和范围校验。 -->
          <template #cell-quantity="{ row: { line, index } }"
            ><AppInput
                aria-label="本次数量"
                :disabled="busy || connectionLost"
                :model-value="line.quantity"
                @update:model-value="(value) => { line.quantity = value; recalculatePurchasePrice(line) }"
                type="number"
                hide-number-controls
                min="0"
                max="1000000"
                step="0.001"
                required /></template>
          <template #cell-unitPrice="{ row: { line } }">
            <WorkspacePurchasePriceInput field="unit_price" :line="line" :disabled="busy || connectionLost || Number(line.quantity) === 0" required />
          </template>
          <template #cell-lineTotal="{ row: { line } }">
            <WorkspacePurchasePriceInput field="line_total" :line="line" :disabled="busy || connectionLost || Number(line.quantity) === 0" required />
          </template>
        </WorkspaceDocumentDialog>
      </template>
      <template #cell-id="{ row: item }"
        ><!-- 单号直接打开只读详情，与操作列「查看」并存两个入口。 -->
        <AppButton
          type="button"
          variant="text"
          :disabled="busy || connectionLost"
          :aria-label="`查看单据 ${documentLabel(item)} 详情`"
          @click.capture="captureDialogOrigin('document-approval', $event)" @click="
            store.openDocumentApproval({
              document_type: 'PurchaseRequest',
              document_id: item.id,
              intent: 'execute',
            })
          "
          >{{ documentLabel(item) }}</AppButton
        ><small v-if="item.reference">{{ item.reference }}</small
        ><small
          >{{ localTime(item.created_at) }} · {{ item.created_by_name }}</small
        ></template
      >
      <template #cell-status="{ row: item }"
        ><span class="pill" :class="item.status">{{
          statusName[item.status]
        }}</span
        ><small>{{ approvalNames[item.approval?.status ?? "draft"] }}</small>
        <small v-if="item.review_reason">{{
          item.review_reason
        }}</small></template
      >
      <template #cell-lines="{ row: item }"
        ><div v-for="line in item.lines" :key="line.id">
          {{ line.material_name }}：申请 {{ line.quantity }}
          {{ line.unit }}，待转
          {{ line.remaining_quantity }}
          <span v-if="line.unit_price != null"> · 单价 ¥{{ line.unit_price }} · 总价 ¥{{ line.line_total }}</span>
        </div></template
      >
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
              document_type: 'PurchaseRequest',
              document_id: item.id,
              intent: 'execute',
            })
          "
          >查看</AppButton
        >
      </template>
      <template #empty>{{
        query ? "没有匹配的采购申请。" : "暂无采购申请。"
      }}</template>
    </WorkspaceTable>
  </section>
</template>
