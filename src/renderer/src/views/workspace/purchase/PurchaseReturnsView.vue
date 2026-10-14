<script setup lang="ts">
// 来源绑定在真实触发入口，键盘点击与鼠标点击共用同一回程位置。
import { captureDialogOrigin } from '../../../utils/dialog-origin'
// 详情页脚按类型与 ID 双重定位，避免跨页面同号单据串单。
import { findDocumentApprovalItem } from "../../../utils/document-approval-item";
// 退货只在批准后转出库；共用审批弹窗保留固定正文和完整历史。
import DocumentApprovalDialog from "../../../components/workspace/DocumentApprovalDialog.vue";
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
import WorkspaceTable from "../../../components/workspace/WorkspaceTable.vue";
import {
  recordColumns,
  matchesRecordQuery,
} from "../../../utils/workspace-records";
import type { WorkspaceTableColumn } from "../../../utils/table-columns";
import { computed, ref } from "vue";
import { useAppStore, usePiniaAppStore } from "../../../store/app-store";
import { submitCreateDialog } from "../../../utils/create-dialog";

// 页面直接使用共享状态与操作，切换标签时不会丢失正在填写的草稿。
const {
  error,
  notice,
  busy,
  connectionLost,
  receipts,
  purchaseReturns,
  purchaseReturnForm,
  purchaseReturnReversalReasons,
  can,
  selectedPurchaseReturnReceipt,
  localTime,
  choosePurchaseReturnReceipt,
  createPurchaseReturn,
  submitPurchaseReturn,
  cancelPurchaseReturn,
  reversePurchaseReturn,
} = useAppStore();
const approvalStore = usePiniaAppStore();

// 详情弹窗由审批目标驱动；页脚业务按钮按当前单据与意图（执行/冲销）展示。
const detailItem = computed(() =>
  findDocumentApprovalItem(approvalStore.documentApprovalTarget, "PurchaseReturn", purchaseReturns.value),
);
const detailIntent = computed(
  () => approvalStore.documentApprovalTarget?.intent ?? "execute",
);

// 冲销只能使用另行批准的固定原因，不能改用未审核的列表草稿。
async function reverseApproved(identifier: number): Promise<void> {
  if (
    !(await approvalStore.openDocumentApproval({
      document_type: "PurchaseReturn",
      document_id: identifier,
      intent: "reverse",
    }))
  )
    return;
  const record = approvalStore.documentApprovalRecord;
  if (record?.status !== "approved" || !record.reversal_reason) return;
  purchaseReturnReversalReasons.value[identifier] = record.reversal_reason;
  approvalStore.closeDocumentApproval();
  await reversePurchaseReturn(identifier);
}

// 保存失败时保留弹窗和草稿，方便直接修正后重试。
const createOpen = ref(false);
async function submitCreate(): Promise<void> {
  await submitCreateDialog(
    createPurchaseReturn,
    { busy, error, notice },
    createOpen,
  );
}
// 只筛选当前列表快照，原有单据状态与跨页面草稿保持不变。
const recordQuery = ref("");
const filteredRecords = computed(() =>
  purchaseReturns.value.filter((item) =>
    matchesRecordQuery(recordQuery.value, [
      documentSearch(item),
      item.id,
      item.supplier_name,
      item.warehouse_name,
      item.created_by_name,
      item.reason,
      ...item.lines.map((line) => line.material_name),
    ]),
  ),
);
// 保留每个草稿行的引用，表格编辑不会改写成另一套临时表单。
const purchaseReturnFormRows = computed(() =>
  documentRows(purchaseReturnForm.value.lines),
);
const purchaseReturnFormColumns = [
  { key: "material", title: "原入库物料", width: "300" },
  { key: "quantity", title: "退货数量", width: "150" },
  { key: "actions", title: "操作", width: "90" },
];
// 操作列只保留查看详情入口，业务操作统一移入详情页脚；其余列沿用公共单据列表布局。
const columns: readonly WorkspaceTableColumn[] = recordColumns.map(
  (column): WorkspaceTableColumn =>
    column.key === "actions"
      ? { key: "actions", title: "查看", width: "72", align: "center" }
      : column,
);
</script>

<template>
  <section class="stack">
    <!-- 共用基础信息与物料表格布局；行对象仍指向原 Pinia 草稿，保留业务字段和来源约束。 -->
    <WorkspaceDocumentDialog origin-key="PurchaseReturnsView:form" @invalidated="createOpen = false"
      material-supply
      v-if="can('purchase_return.create')"
      v-model:show="createOpen"
      title="新建采购退货"
      :data="purchaseReturnFormRows"
      :columns="purchaseReturnFormColumns"
      :busy="busy"
      :disabled="connectionLost"
      :submit-disabled="!purchaseReturnForm.lines.length"
      submit-label="保存草稿"
      :min-table-width="800"
      :show-add="false"
      empty-text="请先选择来源单据，系统将载入可处理的物料明细。"
      @submit="submitCreate"
    >
      <template #basicInfo
        ><label
          >原入库单<WorkspaceSelect
            :disabled="busy || connectionLost"
            v-model="purchaseReturnForm.receipt_id"
            required
            @change="choosePurchaseReturnReceipt"
            :options="[
              { label: '选择可退货的入库单', value: 0, disabled: true },
              ...receipts
                .filter(
                  (entry) =>
                    entry.status === 'posted' &&
                    entry.lines.some(
                      (line) => Number(line.returnable_quantity) > 0,
                    ),
                )
                .map((item) => ({
                  label: (
                    ' #' +
                    item.id +
                    ' · ' +
                    item.supplier_name +
                    ' · ' +
                    item.warehouse_name
                  ).trim(),
                  value: item.id,
                })),
            ]" /></label
        ><label
          >退货原因<AppInput
            :disabled="busy || connectionLost"
            v-model.trim="purchaseReturnForm.reason"
            required
            maxlength="200"
        /></label>
        <div class="document-basic-extra">
          <p class="muted">
            退货从原入库仓库扣减。若货物已调走，请先调回；未关联采购订单的历史入库单不显示退货金额。
          </p>
        </div>
      </template>
      <template #cell-material="{ row: { line, index } }"
        ><label
          >原入库物料<AppInput
            :model-value="
              selectedPurchaseReturnReceipt?.lines.find(
                (item) => item.id === line.receipt_line_id,
              )?.material_name
            "
            disabled /></label
      ></template>
      <template #cell-quantity="{ row: { line, index } }"
        ><label
          >退货数量（最多
          {{
            selectedPurchaseReturnReceipt?.lines.find(
              (item) => item.id === line.receipt_line_id,
            )?.returnable_quantity
          }}）<AppInput
            :disabled="busy || connectionLost"
            v-model.trim="line.quantity"
            type="number"
            min="0.001"
            :max="
              selectedPurchaseReturnReceipt?.lines.find(
                (item) => item.id === line.receipt_line_id,
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
          @click="purchaseReturnForm.lines.splice(index, 1)"
          variant="secondary"
        >
          移除
        </AppButton></template
      >
    </WorkspaceDocumentDialog>
    <!-- 主标题由工作台提供，列表复用仓库管理的筛选区、状态和单元格布局。 -->
    <WorkspaceTable
      :show-title="false"
      title="采购退货"
      :data="filteredRecords"
      :columns="columns"
      :min-table-width="1100"
    >
      <template #actions>
        <AppButton
          v-if="can('purchase_return.create')"
          type="button"
          :disabled="busy"
          @click.capture="captureDialogOrigin('PurchaseReturnsView:form', $event)" @click="createOpen = true"
          variant="primary"
        >
          新建采购退货
        </AppButton>
      </template>
      <template #filters>
        <label>
          搜索采购退货
          <AppInput v-model="recordQuery" placeholder="单号、名称或物料" />
        </label>
      </template>

      <template #cell-document="{ row: item }">
        <div>
          <!-- 单号直接打开只读详情，与操作列「查看」并存两个入口。 -->
          <AppButton
            type="button"
            variant="text"
            :disabled="busy || connectionLost"
            :aria-label="`查看单据 ${documentLabel(item)} 详情`"
            @click.capture="captureDialogOrigin('document-approval', $event)" @click="
              approvalStore.openDocumentApproval({
                document_type: 'PurchaseReturn',
                document_id: item.id,
                intent: 'execute',
              })
            "
            >{{ documentLabel(item) }}</AppButton
          ><strong>
            · {{ item.supplier_name }} · {{ item.warehouse_name }}</strong
          >
          <p class="muted">
            {{ localTime(item.created_at) }} · 原入库单
            {{ relatedDocumentLabel(item, "receipt") }} · {{ item.reason }} ·
            创建人 {{ item.created_by_name }} · 原价金额
            {{
              item.total_amount === null ? "待核对" : `¥${item.total_amount}`
            }}
            <span v-if="item.reversal_id">
              · 冲销 #{{ item.reversal_id }}（{{ item.reversal_reason }} ·
              {{ item.reversed_by_name }}）
            </span>
          </p>
        </div>
      </template>
      <template #cell-status="{ row: item }">
        <span class="pill" :class="item.status">
          {{
            item.reversal_id
              ? "已冲销"
              : item.status === "posted"
                ? "已退供应商"
                : item.status === "cancelled"
                  ? "已取消"
                  : item.outbound_id && item.approval?.status === "executed"
                    ? `待仓库出库 ${relatedDocumentLabel(item, "outbound")}`
                    : {
                        submitted: "审批中",
                        approved: "已批准待转出库",
                        rejected: "已驳回",
                        withdrawn: "已撤回",
                        draft: "待送审",
                        executed: "已转出库",
                      }[item.approval?.status ?? "draft"]
          }}
        </span>
      </template>
      <template #cell-details="{ row: item }">
        <div class="workspace-record-lines">
          <span v-for="line in item.lines" :key="line.id">
            {{ line.material_name }} × {{ line.quantity }} {{ line.unit }} ·
            {{
              line.line_total === null ? "金额待核对" : `¥${line.line_total}`
            }}
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
            approvalStore.openDocumentApproval({
              document_type: 'PurchaseReturn',
              document_id: item.id,
              intent: 'execute',
            })
          "
          >查看</AppButton
        >
      </template>
      <template #empty>
        <strong>{{
          recordQuery ? "没有匹配的记录" : "暂无采购退货记录"
        }}</strong>
        <span>
          {{
            recordQuery
              ? "可调整单号、名称或物料关键词后重新搜索。"
              : "业务记录生成后，可在这里查看明细与处理状态。"
          }}
        </span>
      </template>
    </WorkspaceTable>
    <!-- 业务操作统一在详情页脚办理；审批控件与关闭由公共弹窗承载。 -->
    <DocumentApprovalDialog origin-key="document-approval">
      <template #footerActions>
        <!-- 操作色表达业务含义：冲销红色、取消橙色、确认绿色、查看与编辑蓝色。 -->
        <template v-if="detailItem">
          <AppButton
            tone="info"
            v-if="
              detailIntent === 'execute' &&
              detailItem.status === 'draft' &&
              detailItem.approval?.status === 'approved' &&
              can('purchase_return.submit')
            "
            type="button"
            variant="primary"
            :disabled="busy || connectionLost"
            @click="submitPurchaseReturn(detailItem.id)"
            >生成出库草稿</AppButton
          >
          <AppButton
            tone="warning"
            v-if="
              detailIntent === 'execute' &&
              detailItem.status === 'draft' &&
              !['submitted', 'approved'].includes(
                detailItem.approval?.status ?? '',
              ) &&
              !['submitted', 'approved'].includes(
                detailItem.outbound_approval?.status ?? '',
              ) &&
              can('purchase_return.cancel')
            "
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click="cancelPurchaseReturn(detailItem.id)"
            >取消</AppButton
          >
          <AppButton
            tone="error"
            v-if="detailIntent === 'execute' && detailItem.status === 'posted'"
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click.capture="captureDialogOrigin('document-approval', $event)" @click="
              approvalStore.openDocumentApproval({
                document_type: 'PurchaseReturn',
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
              approvalStore.openDocumentApproval({
                document_type: 'PurchaseReturn',
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
              detailItem.status === 'posted' &&
              !detailItem.reversal_id &&
              detailItem.reversal_approval?.status === 'approved' &&
              can('purchase_return.reverse')
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
  </section>
</template>
