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

// 批准与业务执行分开，审批入口复用共享 Pinia 和固定内容弹窗。
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
// 物料资料统一展示，候选范围和联动规则仍由当前业务决定。
import WorkspaceMaterialSelect from "../../../components/workspace/WorkspaceMaterialSelect.vue";
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
  materials,
  suppliers,
  purchaseOrders,
  purchaseForm,
  can,
  localTime,
  createPurchaseOrder,
  confirmPurchaseOrder,
  cancelPurchaseOrder,
} = useAppStore();

const store = usePiniaAppStore();

// 详情弹窗由审批目标驱动；页脚业务按钮按当前单据与意图（执行/冲销）展示。
const detailItem = computed(() =>
  findDocumentApprovalItem(store.documentApprovalTarget, "PurchaseOrder", purchaseOrders.value),
);
const detailIntent = computed(
  () => store.documentApprovalTarget?.intent ?? "execute",
);

// 保存失败时保留弹窗和草稿，方便直接修正后重试。
const createOpen = ref(false);
async function submitCreate(): Promise<void> {
  await submitCreateDialog(
    createPurchaseOrder,
    { busy, error, notice },
    createOpen,
  );
}
// 只筛选当前列表快照，原有单据状态与跨页面草稿保持不变。
const recordQuery = ref("");
const filteredRecords = computed(() =>
  purchaseOrders.value.filter((item) =>
    matchesRecordQuery(recordQuery.value, [
      documentSearch(item),
      item.id,
      item.supplier_name,
      item.created_by_name,
      item.reference,
      ...item.lines.map((line) => line.material_name),
    ]),
  ),
);
// 保留每个草稿行的引用，表格编辑不会改写成另一套临时表单。
const purchaseFormTotal = computed(() => sumMoney(purchaseForm.value.lines.map(line => line.unit_price === '' ? '' : line.line_total)))
const purchaseFormRows = computed(() => documentRows(purchaseForm.value.lines))
const purchaseFormColumns: readonly WorkspaceTableColumn[] = [
  { key: 'material', title: '物料 / 资料', width: '330' },
  { key: 'unit', title: '单位', width: '60' },
  { key: 'quantity', title: '数量', width: '110' },
  { key: 'unitPrice', title: '单价（元）', width: '150' },
  { key: 'actions', title: '操作', width: '80' },
  // 总价采用紧凑列宽，保留右侧固定；长金额可点击进入输入框查看和编辑。
  { key: 'lineTotal', title: '总价（元）', width: '120', fixed: 'right', align: 'right' },
]
// 新增或查看另一行时自动收起上一行；用对象引用避免删除中间行后展开错料。
const { activeLine, showLine, setCompact } = useDocumentMaterialDetails(() => purchaseForm.value.lines)
function addPricedMaterial(): void {
  if (busy.value || connectionLost.value || purchaseForm.value.lines.length >= 100) return
  const line = newPurchasePriceLine()
  purchaseForm.value.lines.push(line)
  showLine(purchaseForm.value.lines.at(-1)!)
}
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
        <WorkspaceDocumentDialog origin-key="PurchaseOrdersView:form" @invalidated="createOpen = false"
          material-supply
          v-if="can('purchase_order.create')"
          v-model:show="createOpen"
          title="新建采购订单"
          :data="purchaseFormRows"
          :columns="purchaseFormColumns"
          :amount-total="purchaseFormTotal"
          :busy="busy"
          :disabled="connectionLost"
          :submit-disabled="!suppliers.length || !materials.length"
          submit-label="保存草稿"
          :min-table-width="1200"
          :add-disabled="purchaseForm.lines.length >= 100"
          @add-material="addPricedMaterial"
          @submit="submitCreate"
        >
          <template #basicInfo
            ><label
              >供应商<WorkspaceSelect
                :disabled="busy || connectionLost"
                v-model="purchaseForm.supplier_id"
                required
                :options="[
                  { label: '选择供应商'.trim(), value: 0, disabled: true },
                  ...suppliers.map((item) => ({ label: item.name.trim(), value: item.id }))
                ]" /></label
            ><label
              >参考单号（可选）<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="purchaseForm.reference"
                maxlength="100"
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
                  { label: '选择物料'.trim(), value: 0, disabled: true },
                  ...materials.map((item) => ({
                    label: (item.sku + ' · ' + item.name).trim(),
                    value: item.id
                  }))
                ]" /></template>
          <!-- 隐藏数量步进箭头，仍保留原生数字类型、精度和范围校验。 -->
          <template #cell-quantity="{ row: { line, index } }"
            ><AppInput
                aria-label="数量"
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
            <WorkspacePurchasePriceInput field="unit_price" :line="line" :disabled="busy || connectionLost" required />
          </template>
          <template #cell-lineTotal="{ row: { line } }">
            <WorkspacePurchasePriceInput field="line_total" :line="line" :disabled="busy || connectionLost" required />
          </template>
          <template #cell-actions="{ row: { line, index } }"
            ><!-- 移除使用公共按钮的完整点击区域，原有禁用与删行规则保持。 -->
            <AppButton size="small"
              type="button"
              :disabled="busy || connectionLost || purchaseForm.lines.length === 1"
              @click="purchaseForm.lines.splice(index, 1)"
              variant="secondary"
            >
              移除
            </AppButton></template
          >
          <template #cell-unit="{ row: { line } }">{{
            materials.find((item) => item.id === line.material_id)?.unit ?? '—'
          }}</template>
        </WorkspaceDocumentDialog>
    <!-- 主标题由工作台提供，列表复用仓库管理的筛选区、状态和单元格布局。 -->
    <WorkspaceTable
      :show-title="false"
      title="采购订单"
      :data="filteredRecords"
      :columns="columns"
      :min-table-width="1100"
    >
      <template #actions>
        <AppButton
          v-if="can('purchase_order.create')"
          type="button"
          :disabled="busy || connectionLost"
          @click.capture="captureDialogOrigin('PurchaseOrdersView:form', $event)" @click="createOpen = true"
          variant="primary"
        >
          新建采购订单
        </AppButton>
      </template>
      <template #filters>
        <label>
          搜索采购订单
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
              store.openDocumentApproval({
                document_type: 'PurchaseOrder',
                document_id: item.id,
                intent: 'execute',
              })
            "
            >{{ documentLabel(item) }}</AppButton
          ><strong> · {{ item.supplier_name }}</strong>
          <span v-if="item.purchase_request_id" class="muted">
            · 采购申请 {{ relatedDocumentLabel(item, "purchase_request") }}
          </span>
          <p class="muted">
            {{ localTime(item.created_at) }} · 创建人
            {{ item.created_by_name }}
            <span v-if="item.reference">· {{ item.reference }}</span>
            · 总额 ¥{{ item.total_amount }}
          </p>
        </div>
      </template>
      <template #cell-status="{ row: item }">
        <span class="pill" :class="item.status">
          {{
            {
              draft: {
                submitted: "审批中",
                approved: "已批准待确认",
                rejected: "已驳回",
                withdrawn: "已撤回",
                draft: "待送审",
                executed: "已执行",
              }[item.approval?.status ?? "draft"],
              confirmed: "待入库",
              partially_received: "部分入库",
              received: "全部入库",
              cancelled: "已取消",
            }[item.status]
          }}
        </span>
      </template>
      <template #cell-details="{ row: item }">
        <div class="workspace-record-lines">
          <span v-for="line in item.lines" :key="line.id">
            {{ line.material_name }} 已入 {{ line.received_quantity }}/{{
              line.quantity
            }}
            {{ line.unit }} · 已退 {{ line.returned_quantity }} · 净入
            {{ line.net_received_quantity }} · ¥{{ line.unit_price }}/{{
              line.unit
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
            store.openDocumentApproval({
              document_type: 'PurchaseOrder',
              document_id: item.id,
              intent: 'execute',
            })
          "
          >查看</AppButton
        >
      </template>
      <template #empty>
        <strong>{{
          recordQuery ? "没有匹配的记录" : "暂无采购订单记录"
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
            tone="success"
            v-if="
              detailIntent === 'execute' &&
              detailItem.status === 'draft' &&
              detailItem.approval?.status === 'approved' &&
              can('purchase_order.confirm')
            "
            type="button"
            variant="primary"
            :disabled="busy || connectionLost"
            @click="confirmPurchaseOrder(detailItem.id)"
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
              can('purchase_order.cancel')
            "
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click="cancelPurchaseOrder(detailItem.id)"
            >取消订单</AppButton
          >
        </template>
      </template>
    </DocumentApprovalDialog>
  </section>
</template>
