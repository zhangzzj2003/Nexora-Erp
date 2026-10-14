<script setup lang="ts">
import { useRouter } from 'vue-router';
import { routeByKey } from '../../../router/workspace-routes';
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
import WorkspaceTable from "../../../components/workspace/WorkspaceTable.vue";
import DocumentApprovalDialog from "../../../components/workspace/DocumentApprovalDialog.vue";
// 全部批次单据共享标题、固定操作区与数量核对表。
import WorkspaceLotDialog from "../../../components/workspace/WorkspaceLotDialog.vue";
import WorkspaceLotLineEditor from "../../../components/workspace/WorkspaceLotLineEditor.vue";
import { matchesRecordQuery } from "../../../utils/workspace-records";
import type { WorkspaceTableColumn } from "../../../utils/table-columns";
import { computed, ref } from "vue";
import { storeToRefs } from "pinia";
import { usePiniaAppStore } from "../../../store/app-store";
import { submitCreateDialog } from "../../../utils/create-dialog";
import { displayError } from "../../../utils/formatters.ts";
import { receiptLotMilli } from "../../../../../shared/receipt-lot-api.ts";
import { outboundAvailableMilli } from "../../../../../shared/outbound-lot-api.ts";
import { physicalLotKindLabel } from "../../../../../shared/physical-lot-api.ts";
import type {
  MaterialIssueLotLineInput,
  MaterialIssueLotOptions,
} from "../../../../../shared/material-issue-lot-api";
import type { MaterialIssue } from "../../../../../shared/erp-api";

// 页面直接使用共享状态与操作，切换标签时不会丢失正在填写的草稿。
const store = usePiniaAppStore();
const router = useRouter();
const {
  error,
  notice,
  busy,
  connectionLost,
  workOrders,
  materialIssues,
  warehouses,
  materialIssueForm,
  selectedIssueOrder,
} = storeToRefs(store);
const {
  can,
  localTime,
  selectIssueOrder,
  createMaterialIssue,
  loadAvailableMaterialIssueLots,
  postMaterialIssue,
  cancelMaterialIssue,
  reverseMaterialIssue,
  selectReturnIssue,
} = store;

const activeIssueId = ref(0);
const lotOptions = ref<MaterialIssueLotOptions | null>(null);
const lotDrafts = ref<MaterialIssueLotLineInput[]>([]);
const lotLoading = ref(false);
const lotLoadError = ref("");
let loadTicket = 0;
const activeIssue = computed(
  () =>
    materialIssues.value.find(
      (item) =>
        item.id === activeIssueId.value &&
        item.status === "draft" &&
        item.approval?.status === "approved",
    ) ?? null,
);

function closeLotPost(): void {
  loadTicket++;
  activeIssueId.value = 0;
  lotOptions.value = null;
  lotDrafts.value = [];
}

async function startLotPost(issue: MaterialIssue): Promise<void> {
  const ticket = ++loadTicket;
  activeIssueId.value = issue.id;
  lotOptions.value = null;
  lotDrafts.value = [];
  lotLoadError.value = "";
  lotLoading.value = true;
  try {
    const result = await loadAvailableMaterialIssueLots(issue.id);
    if (ticket !== loadTicket || activeIssueId.value !== issue.id) return;
    if (
      result.warehouse_id !== issue.warehouse_id ||
      result.lines.length !== issue.lines.length ||
      result.lines.some(
        (line) =>
          !issue.lines.some(
            (item) =>
              item.id === line.material_issue_line_id &&
              item.component_material_id === line.material_id &&
              item.quantity === line.quantity,
          ),
      )
    )
      throw Error("可用批次与当前生产领料单不匹配，请刷新单据。");
    lotOptions.value = result;
    lotDrafts.value = issue.lines.map((line) => ({
      material_issue_line_id: line.id,
      lots: [{ lot_id: 0, quantity: line.quantity }],
    }));
  } catch (cause) {
    if (ticket === loadTicket) lotLoadError.value = displayError(cause);
  } finally {
    if (ticket === loadTicket) lotLoading.value = false;
  }
}

function addLot(line: MaterialIssueLotLineInput): void {
  if (line.lots.length < 20) line.lots.push({ lot_id: 0, quantity: "" });
}

const lotIssue = computed(() => {
  const issue = activeIssue.value,
    options = lotOptions.value;
  if (!issue || !options || lotDrafts.value.length !== issue.lines.length)
    return "可用批次尚未读取。";
  for (const line of issue.lines) {
    const draft = lotDrafts.value.find(
      (item) => item.material_issue_line_id === line.id,
    );
    const available = options.lines.find(
      (item) => item.material_issue_line_id === line.id,
    );
    if (!draft || !available || !draft.lots.length || draft.lots.length > 20)
      return "每条领料明细至少指定一个实物批次。";
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
  const issue = activeIssue.value;
  if (!issue || lotIssue.value || busy.value || connectionLost.value) return;
  await postMaterialIssue(
    issue.id,
    lotDrafts.value.map((line) => ({
      material_issue_line_id: line.material_issue_line_id,
      lots: line.lots.map((part) => ({
        lot_id: part.lot_id,
        quantity: part.quantity,
      })),
    })),
  );
  if (
    !materialIssues.value.some(
      (item) => item.id === issue.id && item.status === "draft",
    )
  )
    closeLotPost();
}

// 保存失败时保留弹窗和草稿，方便直接修正后重试。
const createOpen = ref(false);
async function submitCreate(): Promise<void> {
  await submitCreateDialog(
    createMaterialIssue,
    { busy, error, notice },
    createOpen,
  );
}
// 只筛选当前列表快照，原有单据状态与跨页面草稿保持不变。
const recordQuery = ref("");
const filteredRecords = computed(() =>
  materialIssues.value.filter((item) =>
    matchesRecordQuery(recordQuery.value, [
      documentSearch(item),
      item.id,
      item.warehouse_name,
      item.created_by_name,
      item.reference,
      ...item.lines.map((line) => line.material_name),
    ]),
  ),
);
// 保留每个草稿行的引用，表格编辑不会改写成另一套临时表单。
const materialIssueFormRows = computed(() =>
  documentRows(materialIssueForm.value.lines),
);
const materialIssueFormColumns = [
  { key: "material", title: "原单物料", width: "300" },
  { key: "remaining", title: "剩余需料", width: "130" },
  { key: "quantity", title: "本次领料数量", width: "160" },
  { key: "actions", title: "操作", width: "100" },
];
// 执行时重读服务端批准内容，禁止临时原因替换固定冲销依据。
async function reverseApproved(identifier: number): Promise<void> {
  if (
    !(await store.openDocumentApproval({
      document_type: "MaterialIssue",
      document_id: identifier,
      intent: "reverse",
    }))
  )
    return;
  const record = store.documentApprovalRecord;
  if (record?.status !== "approved" || !record.reversal_reason) return;
  store.closeDocumentApproval();
  await reverseMaterialIssue(identifier, record.reversal_reason);
}
// 详情弹窗由审批目标驱动；页脚业务按钮按当前单据与意图（执行/冲销）展示。
const detailItem = computed(() =>
  findDocumentApprovalItem(store.documentApprovalTarget, "MaterialIssue", materialIssues.value),
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
</script>

<template>
  <section class="stack">
    <!-- 旧入口保留历史证据，新业务统一进入工单关联的四类物料流程。 -->
    <div v-if="can('material_flow.view')" class="card"><p class="muted">此处保留历史直接领退料记录。新业务在生产工单与仓库四类页面办理。</p><AppButton @click="store.navigateToRoute('productionReceipts')">前往生产领料签收</AppButton></div>
    <!-- 业务操作统一在详情页脚办理；审批控件与关闭由公共弹窗承载。 -->
    <DocumentApprovalDialog>
      <template #footerActions>
        <AppButton v-if="detailItem && can('production.view')" @click="router.push({ path: routeByKey('workOrders').path, query: { document_id: detailItem.work_order_id } })">返回生产工单</AppButton>
        <!-- 操作色表达业务含义：冲销红色、取消橙色、确认绿色、查看与编辑蓝色。 -->
        <template v-if="detailItem">
          <AppButton
            tone="success"
            v-if="
              detailIntent === 'execute' &&
              detailItem.status === 'draft' &&
              detailItem.approval?.status === 'approved' &&
              can('material_issue.post')
            "
            type="button"
            variant="primary"
            :disabled="busy || connectionLost"
            @click="postMaterialIssue(detailItem.id)"
            >确认领料</AppButton
          >
          <AppButton
            tone="info"
            v-if="
              detailIntent === 'execute' &&
              detailItem.status === 'draft' &&
              detailItem.approval?.status === 'approved' &&
              can('material_issue.post')
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
              can('material_issue.cancel')
            "
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click="cancelMaterialIssue(detailItem.id)"
            >取消</AppButton
          >
          <AppButton
            tone="info"
            v-if="
              detailIntent === 'execute' &&
              detailItem.status === 'posted' &&
              detailItem.lines.some(
                (line) => Number(line.returnable_quantity) > 0,
              ) &&
              can('material_return.create')
            "
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click="selectReturnIssue(detailItem.id)"
            >创建退料单</AppButton
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
            @click="
              store.openDocumentApproval({
                document_type: 'MaterialIssue',
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
              can('material_issue.reverse')
            "
            type="button"
            variant="secondary"
            :disabled="busy || connectionLost"
            @click="
              store.openDocumentApproval({
                document_type: 'MaterialIssue',
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
            @click="
              store.openDocumentApproval({
                document_type: 'MaterialIssue',
                document_id: detailItem.id,
                intent: 'execute',
              })
            "
            >查看领料审批</AppButton
          >
          <AppButton
            tone="error"
            v-if="
              detailIntent === 'reverse' &&
              detailItem.status === 'posted' &&
              can('material_issue.reverse') &&
              detailItem.reversal_approval?.status === 'approved'
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
    <!-- 共用基础信息与物料表格布局；行对象仍指向原 Pinia 草稿，保留业务字段和来源约束。 -->
    <WorkspaceDocumentDialog
      v-if="can('material_issue.create')"
      v-model:show="createOpen"
      title="新建领料单"
      :data="materialIssueFormRows"
      :columns="materialIssueFormColumns"
      :busy="busy"
      :disabled="connectionLost"
      :submit-disabled="!materialIssueForm.lines.length || !warehouses.length"
      submit-label="保存领料草稿"
      :min-table-width="800"
      :show-add="false"
      empty-text="请先选择来源单据，系统将载入可处理的物料明细。"
      @submit="submitCreate"
    >
      <template #basicInfo
        ><label
          >生产工单<WorkspaceSelect
            :disabled="busy || connectionLost"
            v-model="materialIssueForm.work_order_id"
            required
            @change="selectIssueOrder(materialIssueForm.work_order_id)"
            :options="[
              { label: '选择已下达工单', value: 0, disabled: true },
              ...workOrders
                .filter(
                  (entry) =>
                    (entry.status === 'released' ||
                      entry.status === 'in_progress') &&
                    entry.lines.some(
                      (line) => Number(line.remaining_quantity) > 0,
                    ),
                )
                .map((item) => ({
                  label: (
                    ' #' +
                    item.id +
                    ' · ' +
                    item.product_name +
                    ' · ' +
                    item.target_quantity +
                    ' ' +
                    item.product_unit
                  ).trim(),
                  value: item.id,
                })),
            ]" /></label
        ><label
          >领料源仓库<WorkspaceSelect
            :disabled="busy || connectionLost"
            v-model="materialIssueForm.warehouse_id"
            required
            :options="[
              ...warehouses.map((item) => ({
                label: item.name,
                value: item.id,
              })),
            ]" /></label
        ><label
          >参考号（可选）<AppInput
            :disabled="busy || connectionLost"
            v-model.trim="materialIssueForm.reference"
            maxlength="100"
        /></label>
        <div class="document-basic-extra">
          <p class="muted">
            按工单剩余需料分批建单。草稿不预留库存；确认时服务端再次检查源仓库存与剩余需料。
          </p>
        </div>
      </template>
      <template #cell-material="{ row: { line } }">{{
        selectedIssueOrder?.lines.find(
          (item) => item.id === line.work_order_line_id,
        )?.material_name
      }}</template>
      <template #cell-remaining="{ row: { line } }">{{
        selectedIssueOrder?.lines.find(
          (item) => item.id === line.work_order_line_id,
        )?.remaining_quantity
      }}</template>
      <template #cell-quantity="{ row: { line } }"
        ><label
          >本次领料数量<AppInput
            :disabled="busy || connectionLost"
            v-model.trim="line.quantity"
            type="number"
            min="0.001"
            :max="
              selectedIssueOrder?.lines.find(
                (item) => item.id === line.work_order_line_id,
              )?.remaining_quantity
            "
            step="0.001"
            required /></label
      ></template>
      <template #cell-actions="{ row: { line, index } }"
        ><AppButton
          type="button"
          :disabled="busy || connectionLost || busy"
          @click="
            materialIssueForm.lines = materialIssueForm.lines.filter(
              (item) => item.work_order_line_id !== line.work_order_line_id,
            )
          "
          variant="text"
        >
          本次不领
        </AppButton></template
      >
    </WorkspaceDocumentDialog>
    <!-- 主标题由工作台提供，列表复用仓库管理的筛选区、状态和单元格布局。 -->
    <WorkspaceTable
      :show-title="false"
      title="生产领料"
      :data="filteredRecords"
      :columns="columns"
      :min-table-width="1100"
    >
      <template #actions>
        <AppButton
          v-if="can('material_flow.view') && can('material_dispatch.create')"
          type="button"
          :disabled="busy"
          @click="store.navigateToRoute('productionDispatches')"
          variant="primary"
        >
          前往工单发料
        </AppButton>
      </template>
      <template #filters>
        <label>
          搜索生产领料
          <AppInput v-model="recordQuery" placeholder="单号、名称或物料" />
        </label>
      </template>

      <template #cell-document="{ row: item }">
        <div>
          <strong
            ><!-- 单号直接打开只读详情，与操作列「查看」并存两个入口。 -->
            <AppButton
              type="button"
              variant="text"
              :disabled="busy || connectionLost"
              :aria-label="`查看单据 ${documentLabel(item)} 详情`"
              @click="
                store.openDocumentApproval({
                  document_type: 'MaterialIssue',
                  document_id: item.id,
                  intent: 'execute',
                })
              "
              >{{ documentLabel(item) }}</AppButton
            >
            · 工单 {{ relatedDocumentLabel(item, "work_order") }} ·
            {{ item.warehouse_name }}</strong
          >
          <p class="muted">
            {{ localTime(item.created_at) }} · 创建人
            {{ item.created_by_name }}
            <span v-if="item.reference">· {{ item.reference }}</span>
          </p>
        </div>
      </template>
      <template #cell-status="{ row: item }">
        <span class="pill" :class="item.status">
          {{
            {
              draft: approvalLabels[item.approval?.status ?? "draft"],
              posted: "已确认",
              cancelled: "已取消",
              reversed: "已冲销",
            }[item.status]
          }}
        </span>
        <small v-if="item.receipt_mode" class="muted">{{ item.receipt_mode === 'historical_direct' ? '历史直接领料' : '仓库发出，生产另行签收' }}</small>
        <small v-if="item.reversal_reason" class="muted">
          {{ item.reversed_at ? localTime(item.reversed_at) : "" }} ·
          冲销原因：{{ item.reversal_reason }}
        </small>
      </template>
      <template #cell-details="{ row: item }">
        <div class="workspace-record-lines">
          <span v-for="line in item.lines" :key="line.id">
            <!-- 草稿只描述申请数量；实际退料与可退量仅属于已确认领料。 -->
            {{ line.material_name }} · 领料数量 {{ line.quantity }}
            {{ line.unit }}
            <template v-if="['posted', 'reversed'].includes(item.status)">
              · 已退 {{ line.returned_quantity }} · 可退
              {{ line.returnable_quantity }} {{ line.unit }}
            </template>
            <small
              v-if="
                ['posted', 'reversed'].includes(item.status) &&
                line.physical_lots.length
              "
              class="issue-lot-proof"
            >
              实物批次：{{
                line.physical_lots
                  .map(
                    (lot) =>
                      `${lot.code}（${lot.quantity}；${physicalLotKindLabel(lot.source_kind)}）`,
                  )
                  .join("、")
              }}
            </small>
            <small
              v-else-if="['posted', 'reversed'].includes(item.status)"
              class="issue-lot-proof"
              >普通确认未指定实物批次，查看批次核对页确认差额。</small
            >
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
          @click="
            store.openDocumentApproval({
              document_type: 'MaterialIssue',
              document_id: item.id,
              intent: 'execute',
            })
          "
          >查看</AppButton
        >
      </template>
      <template #empty>
        <strong>{{
          recordQuery ? "没有匹配的记录" : "暂无生产领料记录"
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
    <!-- 批次登记统一使用公共弹窗和明细表，各业务仍保留原确认与校验逻辑。 -->
    <WorkspaceLotDialog
      v-if="activeIssue && can('material_issue.post')"
      :show="true"
      title="生产领料 · 批次选择"
      :document-number="documentLabel(activeIssue)"
      :hint="
        '从 ' +
        activeIssue.warehouse_name +
        ' 的实际可用批次逐行选择；历史未识别期初会明确标记。'
      "
      :busy="busy"
      :disabled="connectionLost"
      :issue="lotIssue"
      submit-label="确认领料"
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
        :key="line.material_issue_line_id"
        :lots="line.lots"
        :sku="
          activeIssue.lines.find(
            (item) => item.id === line.material_issue_line_id,
          )?.sku
        "
        :material-name="
          activeIssue.lines.find(
            (item) => item.id === line.material_issue_line_id,
          )?.material_name
        "
        :unit="
          activeIssue.lines.find(
            (item) => item.id === line.material_issue_line_id,
          )?.unit
        "
        :expected="
          activeIssue.lines.find(
            (item) => item.id === line.material_issue_line_id,
          )?.quantity ?? ''
        "
        expected-label="应领料"
        quantity-label="领料数量"
        :selectable="true"
        :options="[
          { label: '选择批次', value: 0, disabled: true },
          ...(
            lotOptions?.lines.find(
              (item) =>
                item.material_issue_line_id === line.material_issue_line_id,
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
  </section>
</template>

<style scoped>
.issue-lot-proof {
  display: block;
  color: var(--workspace-field-muted);
  overflow-wrap: anywhere;
}
</style>
