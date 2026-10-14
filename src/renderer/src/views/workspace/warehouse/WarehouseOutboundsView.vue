<script setup lang="ts">
// 复用公共物料资料的单行展开状态，新增或重选时收起其他行。
import { useDocumentMaterialDetails } from "../../../composables/use-document-material-details";
// 详情页脚按类型与 ID 双重定位，避免跨页面同号单据串单。
import { findDocumentApprovalItem } from "../../../utils/document-approval-item";
// 普通出库和可选实物批次均先批准，使用同一服务端事务与审批记录。
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
import { computed, ref } from "vue";
import { storeToRefs } from "pinia";
// 单据统一使用固定关闭区、基础信息和物料明细表格。
import { documentRows } from "../../../utils/document-rows";
import type { WorkspaceTableColumn } from "../../../utils/table-columns";
import WorkspaceDocumentDialog from "../../../components/workspace/WorkspaceDocumentDialog.vue";
import WorkspaceTable from "../../../components/workspace/WorkspaceTable.vue";
// 全部批次单据共享标题、固定操作区与数量核对表。
import WorkspaceLotDialog from "../../../components/workspace/WorkspaceLotDialog.vue";
import WorkspaceLotLineEditor from "../../../components/workspace/WorkspaceLotLineEditor.vue";
import { usePiniaAppStore } from "../../../store/app-store";
import { submitCreateDialog } from "../../../utils/create-dialog";
import { displayError } from "../../../utils/formatters.ts";
import { receiptLotMilli } from "../../../../../shared/receipt-lot-api.ts";
import { outboundAvailableMilli } from "../../../../../shared/outbound-lot-api.ts";
import { physicalLotKindLabel } from "../../../../../shared/physical-lot-api.ts";
import type {
  OutboundLotLineInput,
  OutboundLotOptions,
} from "../../../../../shared/outbound-lot-api";
import type { WarehouseOutbound } from "../../../../../shared/erp-api";

const store = usePiniaAppStore();
const {
  error,
  notice,
  busy,
  connectionLost,
  materials,
  warehouses,
  warehouseOutbounds,
  otherOutboundForm,
  otherOutboundReversalReasons,
} = storeToRefs(store);
const {
  can,
  localTime,
  createOtherOutbound,
  loadAvailableOutboundLots,
  postWarehouseOutbound,
  cancelOtherOutbound,
  reverseOtherOutbound,
} = store;
// 详情弹窗由审批目标驱动；页脚业务按钮按当前单据与意图（执行/冲销）展示。
const detailItem = computed(() =>
  findDocumentApprovalItem(store.documentApprovalTarget, "WarehouseOutbound", warehouseOutbounds.value),
);
const detailIntent = computed(
  () => store.documentApprovalTarget?.intent ?? "execute",
);
const showForm = ref(false);
const activeOutboundId = ref(0);
const lotOptions = ref<OutboundLotOptions | null>(null);
const lotDrafts = ref<OutboundLotLineInput[]>([]);
const lotLoading = ref(false);
const lotLoadError = ref("");
let loadTicket = 0;
const activeOutbound = computed(
  () =>
    warehouseOutbounds.value.find(
      (item) =>
        item.id === activeOutboundId.value &&
        item.status === "draft" &&
        item.approval?.status === "approved",
    ) ?? null,
);
const query = ref("");
const filtered = computed(() =>
  warehouseOutbounds.value.filter((item) =>
    [
      documentSearch(item),
      item.id,
      item.reference,
      item.warehouse_name,
      item.note,
      ...item.lines.map((line) => line.material_name),
    ]
      .join(" ")
      .toLowerCase()
      .includes(query.value.trim().toLowerCase()),
  ),
);
const reasonName = {
  scrap: "报废",
  sample: "样品",
  other: "其他",
  purchase_return: "采购退货",
};
const columns: readonly WorkspaceTableColumn[] = [
  { key: "document", title: "单据" },
  { key: "source", title: "仓库与来源" },
  { key: "lines", title: "物料明细" },
  { key: "actions", title: "查看", width: "72", align: "center" },
];
// 写入失败时保留表单，成功后才关闭弹窗。
async function submitCreate(): Promise<void> {
  await submitCreateDialog(
    createOtherOutbound,
    { busy, error, notice },
    showForm,
  );
}
function closeLotPost(): void {
  loadTicket++;
  activeOutboundId.value = 0;
  lotOptions.value = null;
  lotDrafts.value = [];
}
async function startLotPost(outbound: WarehouseOutbound): Promise<void> {
  // 审批撤回或连接失效时不能继续提交已打开的实物分配草稿。
  if (
    outbound.approval?.status !== "approved" ||
    busy.value ||
    connectionLost.value
  )
    return;
  const ticket = ++loadTicket;
  activeOutboundId.value = outbound.id;
  lotOptions.value = null;
  lotDrafts.value = [];
  lotLoadError.value = "";
  lotLoading.value = true;
  try {
    const result = await loadAvailableOutboundLots(outbound.id);
    if (ticket !== loadTicket || activeOutboundId.value !== outbound.id) return;
    if (
      result.warehouse_id !== outbound.warehouse_id ||
      result.lines.length !== outbound.lines.length ||
      result.lines.some(
        (line) =>
          !outbound.lines.some(
            (item) =>
              item.id === line.outbound_line_id &&
              item.material_id === line.material_id &&
              item.quantity === line.quantity,
          ),
      )
    )
      throw Error("可用批次与当前出库单不匹配，请刷新单据。");
    lotOptions.value = result;
    lotDrafts.value = outbound.lines.map((line) => ({
      outbound_line_id: line.id,
      lots: [{ lot_id: 0, quantity: line.quantity }],
    }));
  } catch (cause) {
    if (ticket === loadTicket) lotLoadError.value = displayError(cause);
  } finally {
    if (ticket === loadTicket) lotLoading.value = false;
  }
}
function addLot(line: OutboundLotLineInput): void {
  if (line.lots.length < 20) line.lots.push({ lot_id: 0, quantity: "" });
}
const lotIssue = computed(() => {
  const outbound = activeOutbound.value,
    options = lotOptions.value;
  if (!outbound || !options || lotDrafts.value.length !== outbound.lines.length)
    return "可用批次尚未读取。";
  for (const line of outbound.lines) {
    const draft = lotDrafts.value.find(
      (item) => item.outbound_line_id === line.id,
    );
    const available = options.lines.find(
      (item) => item.outbound_line_id === line.id,
    );
    if (!draft || !available || !draft.lots.length || draft.lots.length > 20)
      return "每条出库明细至少指定一个实物批次。";
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
  const outbound = activeOutbound.value;
  if (!outbound || lotIssue.value || busy.value || connectionLost.value) return;
  await postWarehouseOutbound(
    outbound.id,
    lotDrafts.value.map((line) => ({
      outbound_line_id: line.outbound_line_id,
      lots: line.lots.map((part) => ({
        lot_id: part.lot_id,
        quantity: part.quantity,
      })),
    })),
  );
  if (
    !warehouseOutbounds.value.some(
      (item) => item.id === outbound.id && item.status === "draft",
    )
  )
    closeLotPost();
}
// 保留每个草稿行的引用，表格编辑不会改写成另一套临时表单。
const otherOutboundFormRows = computed(() =>
  documentRows(otherOutboundForm.value.lines),
);
const otherOutboundFormColumns = [
  { key: "material", title: "物料 / 资料", width: "470" },
  { key: "unit", title: "单位", width: "70" },
  { key: "quantity", title: "数量", width: "150" },
  { key: "actions", title: "操作", width: "90" },
];

async function reverseApproved(identifier: number): Promise<void> {
  // 读取固定冲销原因后执行，服务端仍会在原写事务内再次核对批准正文。
  if (
    !(await store.openDocumentApproval({
      document_type: "WarehouseOutbound",
      document_id: identifier,
      intent: "reverse",
    }))
  )
    return;
  const record = store.documentApprovalRecord;
  if (record?.status !== "approved" || !record.reversal_reason) return;
  otherOutboundReversalReasons.value[identifier] = record.reversal_reason;
  store.closeDocumentApproval();
  await reverseOtherOutbound(identifier);
}
// 资料展示绑定原草稿行引用，删除中间行不会展开到另一项物料。
const { activeLine, showLine, setCompact } = useDocumentMaterialDetails(() => otherOutboundForm.value.lines)
</script>

<template>
  <section class="stack">
    <WorkspaceTable
      :show-title="false"
      :data="filtered"
      title="仓库出库"
      :columns="columns"
      :min-table-width="900"
    >
      <template #actions>
        <AppButton
          v-if="can('other_outbound.create')"
          :disabled="busy || connectionLost"
          @click="showForm = true"
          variant="primary"
          type="button"
          >新建仓库出库</AppButton
        >
      </template>
      <template #filters>
        <label
          >搜索出库单<AppInput v-model="query" placeholder="单号、仓库或物料"
        /></label>
      </template>
      <template #beforeTable>
        <!-- 共用基础信息与物料表格布局；行对象仍指向原 Pinia 草稿，保留业务字段和来源约束。 -->
        <WorkspaceDocumentDialog
          material-supply
          v-if="showForm && can('other_outbound.create')"
          v-model:show="showForm"
          title="新建仓库出库"
          :data="otherOutboundFormRows"
          :columns="otherOutboundFormColumns"
          :busy="busy"
          :disabled="connectionLost"
          :submit-disabled="connectionLost"
          submit-label="保存草稿"
          :min-table-width="1000"
          :add-disabled="otherOutboundForm.lines.length >= 100"
          @add-material="
            otherOutboundForm.lines.push({ material_id: 0, quantity: '1' })
          "
          @submit="submitCreate"
        >
          <template #basicInfo
            ><label
              >仓库<WorkspaceSelect
                :disabled="busy || connectionLost"
                v-model="otherOutboundForm.warehouse_id"
                required
                :options="[
                  ...warehouses.map((item) => ({
                    label: item.name,
                    value: item.id,
                  })),
                ]"
            /></label>
            <label
              >用途<WorkspaceSelect
                :disabled="busy || connectionLost"
                v-model="otherOutboundForm.reason"
                required
                :options="[
                  { label: '报废', value: 'scrap' },
                  { label: '样品', value: 'sample' },
                  { label: '其他', value: 'other' },
                ]"
            /></label>
            <label
              >参考号<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="otherOutboundForm.reference"
                maxlength="100"
            /></label>
            <label
              >出库说明<AppInput
                :disabled="busy || connectionLost"
                v-model.trim="otherOutboundForm.note"
                required
                maxlength="200"
            /></label>

            <div class="document-basic-extra">
              <p class="muted">确认后才扣减库存；其他出库不产生采购应付。</p>
            </div></template
          >
          <template #cell-material="{ row: { line, index } }"
            ><!-- 标题由表头统一展示，控件保留逐行无障碍名称。 -->
            <WorkspaceMaterialSelect
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
                  { label: '选择物料', value: 0, disabled: true },
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
          <template #cell-actions="{ row: { line, index } }"
            ><!-- 移除使用公共按钮的完整点击区域，原有禁用与删行规则保持。 -->
            <AppButton size="small"
              type="button"
              :disabled="
                busy || connectionLost || otherOutboundForm.lines.length === 1
              "
              @click="otherOutboundForm.lines.splice(index, 1)"
              variant="secondary"
              >移除</AppButton
            ></template
          >
          <template #cell-unit="{ row: { line } }">{{
            materials.find((item) => item.id === line.material_id)?.unit ?? "—"
          }}</template>
        </WorkspaceDocumentDialog>
      </template>
      <template #cell-document="{ row: item }"
        ><!-- 单号直接打开只读详情，与操作列「查看」并存两个入口。 -->
        <AppButton
          type="button"
          variant="text"
          :disabled="busy || connectionLost"
          :aria-label="`查看单据 ${documentLabel(item)} 详情`"
          @click="
            store.openDocumentApproval({
              document_type: 'WarehouseOutbound',
              document_id: item.id,
              intent: 'execute',
            })
          "
          >{{ documentLabel(item) }}</AppButton
        ><small
          >{{ localTime(item.created_at) }} · {{ item.created_by_name }}</small
        ><small>{{
          item.status === "draft"
            ? {
                submitted: "审批中",
                approved: "已批准待出库",
                rejected: "已驳回",
                withdrawn: "已撤回",
                draft: "待送审",
                executed: "已执行",
              }[item.approval?.status ?? "draft"]
            : item.status === "cancelled"
              ? "已取消"
              : item.purchase_return_reversal_id
                ? "采购退货已冲销"
                : item.reversal_id
                  ? "已冲销"
                  : "已出库"
        }}</small
        ><small v-if="item.reversal_reason"
          >冲销：{{ item.reversal_reason }}</small
        ></template
      >
      <template #cell-source="{ row: item }"
        >{{ item.warehouse_name }} · {{ reasonName[item.reason]
        }}<small>{{ item.note }}</small
        ><small v-if="item.reference">{{ item.reference }}</small
        ><small v-if="item.purchase_return_id"
          >采购退货单 {{ relatedDocumentLabel(item, "purchase_return") }}</small
        ></template
      >
      <template #cell-lines="{ row: item }"
        ><div v-for="line in item.lines" :key="line.id">
          {{ line.material_name }} × {{ line.quantity }} {{ line.unit }}
          <small
            v-if="item.status === 'posted' && line.physical_lots?.length"
            class="outbound-lot-proof"
          >
            实物批次：{{
              line.physical_lots
                ?.map(
                  (lot) =>
                    `${lot.code}（${lot.quantity}；${physicalLotKindLabel(lot.source_kind)}）`,
                )
                .join("、")
            }}
          </small>
          <small v-else-if="item.status === 'posted'" class="outbound-lot-proof"
            >普通出库，未指定实物批次。</small
          >
        </div></template
      >
      <template #cell-actions="{ row: item }"
        ><AppButton
          type="button"
          variant="secondary"
          size="small"
          :disabled="busy || connectionLost"
          :aria-label="`查看单据 ${documentLabel(item)} 详情`"
          @click="
            store.openDocumentApproval({
              document_type: 'WarehouseOutbound',
              document_id: item.id,
              intent: 'execute',
            })
          "
          >查看</AppButton
        ></template
      >
      <template #empty>{{
        query ? "没有匹配的出库单。" : "暂无仓库出库单。"
      }}</template>
    </WorkspaceTable>
    <!-- 批次登记统一使用公共弹窗和明细表，各业务仍保留原确认与校验逻辑。 -->
    <WorkspaceLotDialog
      v-if="activeOutbound && can('other_outbound.post')"
      :show="true"
      :title="
        activeOutbound.source_kind === 'purchase_return'
          ? '采购退货出库 · 批次选择'
          : '其他出库 · 批次选择'
      "
      :document-number="documentLabel(activeOutbound)"
      :hint="
        '从 ' +
        activeOutbound.warehouse_name +
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
      <WorkspaceLotLineEditor
        v-for="line in lotDrafts"
        :key="line.outbound_line_id"
        :lots="line.lots"
        :sku="
          activeOutbound.lines.find((item) => item.id === line.outbound_line_id)
            ?.sku
        "
        :material-name="
          activeOutbound.lines.find((item) => item.id === line.outbound_line_id)
            ?.material_name
        "
        :unit="
          activeOutbound.lines.find((item) => item.id === line.outbound_line_id)
            ?.unit
        "
        :expected="
          activeOutbound.lines.find((item) => item.id === line.outbound_line_id)
            ?.quantity ?? ''
        "
        expected-label="应出库"
        quantity-label="出库数量"
        :selectable="true"
        :options="[
          { label: '选择批次', value: 0, disabled: true },
          ...(
            lotOptions?.lines.find(
              (item) => item.outbound_line_id === line.outbound_line_id,
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
    </WorkspaceLotDialog>
    <!-- 业务操作统一在详情页脚办理；审批控件与关闭由公共弹窗承载。 -->
    <DocumentApprovalDialog>
      <template #footerActions>
        <!-- 操作色表达业务含义：冲销红色、取消橙色、确认绿色、查看与编辑蓝色。 -->
        <template v-if="detailItem">
          <AppButton
            tone="success"
            v-if="
              detailIntent === 'execute' &&
              detailItem.status === 'draft' &&
              detailItem.approval?.status === 'approved' &&
              can('other_outbound.post')
            "
            type="button"
            variant="primary"
            :disabled="busy || connectionLost"
            @click="postWarehouseOutbound(detailItem.id)"
            >确认出库</AppButton
          >
          <AppButton
            tone="info"
            v-if="
              detailIntent === 'execute' &&
              detailItem.status === 'draft' &&
              detailItem.approval?.status === 'approved' &&
              can('other_outbound.post')
            "
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click="startLotPost(detailItem)"
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
              detailItem.source_kind === 'other' &&
              can('other_outbound.cancel')
            "
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click="cancelOtherOutbound(detailItem.id)"
            >取消</AppButton
          >
          <AppButton
            tone="error"
            v-if="
              detailIntent === 'execute' &&
              detailItem.status === 'posted' &&
              detailItem.source_kind === 'other'
            "
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click="
              store.openDocumentApproval({
                document_type: 'WarehouseOutbound',
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
            @click="
              store.openDocumentApproval({
                document_type: 'WarehouseOutbound',
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
              can('other_outbound.reverse')
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

<style scoped>
.outbound-lot-proof {
  display: block;
  color: var(--workspace-field-muted);
  overflow-wrap: anywhere;
}
</style>
