<script setup lang="ts">
// 来源绑定在真实触发入口，键盘点击与鼠标点击共用同一回程位置。
import { captureDialogOrigin } from '../../../utils/dialog-origin'
import './sales-editors.css'
import SalesSectionTabs from './SalesSectionTabs.vue'
import AppStatusTag from '../../../components/app/AppStatusTag.vue'
import WorkspaceSearchFilters from '../../../components/workspace/WorkspaceSearchFilters.vue'
import WorkspaceSummaryFilters from '../../../components/workspace/WorkspaceSummaryFilters.vue'
import type {AppStatusTone} from '../../../components/app/AppStatusTag.vue'
import {useLocalPagination} from '../../../composables/use-local-pagination'
import AppModal from '../../../components/app/AppModal.vue'
// 页面只展示服务端保存的单号，原内部 ID 继续用于业务操作。
import {
  documentSearch,
  documentLabel,
  relatedDocumentLabel,
} from "../../../../../shared/document-numbering";
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";

import type {
  AfterSalesAction,
  AfterSalesEvidence,
  AfterSalesResponsibilityOutcome,
} from "../../../../../shared/after-sales-api";
import { usePiniaAppStore } from "../../../store/app-store";
import DocumentApprovalDialog from "../../../components/workspace/DocumentApprovalDialog.vue";
import AppButton from "../../../components/app/AppButton.vue";
import AppInput from "../../../components/app/AppInput.vue";
import WorkspaceSelect from "../../../components/workspace/WorkspaceSelect.vue";
import WorkspaceTable from "../../../components/workspace/WorkspaceTable.vue";
import type { WorkspaceTableColumn } from "../../../utils/table-columns";
import AfterSalesEditor from "./AfterSalesEditor.vue";
import AfterSalesEvidenceView from "./AfterSalesEvidence.vue";
import AfterSalesAttachments from "./AfterSalesAttachments.vue";
import AfterSalesLaborCost from "./AfterSalesLaborCost.vue";
import AfterSalesRepairMargin from "./AfterSalesRepairMargin.vue";
import {
  afterSalesActions,
  afterSalesKind,
  afterSalesStatus,
  afterSalesCommand,
  afterSalesReversalHint,
} from "./after-sales-display";
const store = usePiniaAppStore();
const {
  afterSalesOverview: overview,
  afterSalesDetail: detail,
  afterSalesLoading: loading,
  afterSalesError: failure,
  busy,
  user,
  server,
  connectionLost,
  error,
} = storeToRefs(store);
const mode = ref<"sources" | "records">("sources"),
  editor = ref(false),
  editorPending = ref(false),
  query = ref(""),
  preparing = ref(false),
  reason = ref(""),
  evidence = ref(""),
  inspection = ref<"pass" | "fail" | "">("");
const command = ref<{
  row: AfterSalesEvidence;
  action: AfterSalesAction;
} | null>(null);
const laborCommand = ref<{
    row: AfterSalesEvidence;
    entryId: number | null;
  } | null>(null),
  laborHours = ref("");
const responsibilityCommand = ref<AfterSalesEvidence | null>(null);
const responsibilityOutcome = ref<AfterSalesResponsibilityOutcome | "">(""),
  responsibilityBasis = ref("");
const disabled = computed(
  () => busy.value || loading.value || preparing.value || connectionLost.value,
);
const summary=ref('')
const searchFilters=ref({})
// 来源按是否仍可办理划分；记录按办理阶段划分，统计不受关键词影响。
function caseGroup(row:AfterSalesEvidence):string {
  return row.status==='closed'?'completed':['cancelled','reversed'].includes(row.status)?'inactive':['draft','submitted','approved','rejected'].includes(row.status)?'pending':'active'
}
function caseTone(row:AfterSalesEvidence):AppStatusTone {
  return row.status==='reversed'?'reversed':row.status==='rejected'?'danger':({completed:'success',inactive:'neutral',pending:'pending',active:'info'} as const)[caseGroup(row) as 'completed'|'inactive'|'pending'|'active']
}
const counts=computed(()=>mode.value==='sources' ? [
  {key:'',label:'全部来源',count:overview.value?.sources.length??0,hint:'全部可见的原出库明细'},
  {key:'available',label:'可办理',count:overview.value?.sources.filter(row=>Number(row.remaining_quantity)>0).length??0,hint:'仍有未退回且未占用数量'},
  {key:'used',label:'已用完',count:overview.value?.sources.filter(row=>Number(row.remaining_quantity)<=0).length??0,hint:'当前无剩余可办理数量'},
] : [{key:'',label:'全部售后'}, {key:'pending',label:'待处理'}, {key:'active',label:'办理中'}, {key:'completed',label:'已结案'}, {key:'inactive',label:'取消 / 更正'}]
  .map(group=>({...group,count:overview.value?.cases.filter(row=>!group.key||caseGroup(row)===group.key).length??0,hint:'全部可见售后记录，不随关键词筛选改变',tone:group.key==='completed'?'success' as const:group.key==='pending'?'pending' as const:'neutral' as const})))
const sources = computed(() =>
  (overview.value?.sources ?? []).filter((row) =>
    (!summary.value || (summary.value==='available'?Number(row.remaining_quantity)>0:Number(row.remaining_quantity)<=0)) && [
      documentSearch(row),
      row.shipment_id,
      row.sales_order_id,
      row.customer_name,
      row.sku,
      row.material_name,
    ]
      .join(" ")
      .toLowerCase()
      .includes(query.value.trim().toLowerCase()),
  ),
);
const records = computed(() =>
  (overview.value?.cases ?? []).filter((row) =>
    (!summary.value || caseGroup(row)===summary.value) && [
      documentSearch(row),
      row.reference,
      row.frozen_source.customer_name,
      row.frozen_source.sku,
      row.frozen_source.material_name,
      afterSalesKind[row.kind],
      afterSalesStatus[row.status],
    ]
      .join(" ")
      .toLowerCase()
      .includes(query.value.trim().toLowerCase()),
  ),
);
const filterKey=computed(()=>JSON.stringify([mode.value,query.value,summary.value]))
const sourcePages=useLocalPagination(sources,filterKey), recordPages=useLocalPagination(records,filterKey)
const sourceColumns:readonly WorkspaceTableColumn[]=[
  {key:'document',title:'原出库单',width:'220'}, {key:'customer_name',title:'客户',width:'200'},
  {key:'sku',title:'物料编码',width:'170'}, {key:'material_name',title:'物料名称',width:'220'},
  {key:'quantity',title:'出库数量',width:'130',align:'right'}, {key:'remaining_quantity',title:'剩余可办理',width:'140',align:'right'},
  {key:'unit',title:'单位',width:'80'}, {key:'order',title:'销售订单',width:'220'}, {key:'actions',title:'操作',width:'120'},
]
const recordColumns:readonly WorkspaceTableColumn[]=[
  {key:'document',title:'售后单号',width:'220'}, {key:'customer',title:'客户',width:'200'}, {key:'kind',title:'办理方式',width:'120'},
  {key:'stage',title:'办理阶段',width:'170'}, {key:'material',title:'物料名称',width:'220'}, {key:'quantity',title:'办理数量',width:'130',align:'right'},
  {key:'fee',title:'维修服务费（元）',width:'170',align:'right'}, {key:'reference',title:'售后依据',width:'200'},
  {key:'created_by_name',title:'创建人',width:'130'}, {key:'actions',title:'操作',width:'100',align:'center'},
]
const actions = (row: AfterSalesEvidence) =>
  afterSalesActions(row, user.value?.permissions ?? [], user.value?.id ?? 0);
function newRecord(id: number): void {
  if (!disabled.value && store.startAfterSalesCase(id)) editor.value = true;
}
async function editRecord(id: number): Promise<void> {
  if (disabled.value) return;
  preparing.value = true; editorPending.value = true;
  try {
    if (await store.editAfterSalesCase(id) && editorPending.value) editor.value = true;
  } finally {
    preparing.value = false; editorPending.value = false;
  }
}
// 打开意图与业务结果分离，准备期间可取消，取消后不再采纳本次结果。
const commandPending = ref(false)
const responsibilityPending = ref(false)
const laborPending = ref(false)
watch(() => `${server.value?.id}:${server.value?.fingerprint}:${user.value?.id}:${user.value?.permissions.join('|')}`, () => { commandPending.value = false; responsibilityPending.value = false; laborPending.value = false }, { flush: 'sync' })
onUnmounted(() => { commandPending.value = false; responsibilityPending.value = false; laborPending.value = false })
async function prepare(id: number, action: AfterSalesAction): Promise<void> {
  if (disabled.value) return;
  commandPending.value = true; preparing.value = true;
  command.value = null;
  reason.value = "";
  evidence.value = "";
  inspection.value = "";
  error.value = "";
  try {
    if (
      (await store.loadAfterSalesDetail(id)) &&
      commandPending.value &&
      detail.value &&
      actions(detail.value).includes(action)
    )
      command.value = { row: detail.value, action };
  } finally {
    commandPending.value = false; preparing.value = false;
  }
}
async function execute(): Promise<void> {
  if (!command.value || disabled.value) return;
  const { row, action } = command.value;
  const current = overview.value?.cases.find((item) => item.id === row.id);
  // 弹窗打开后若另一人撤回审批或单据版本变化，保留输入并提示重新核对。
  if (
    !current ||
    current.version !== row.version ||
    !actions(current).includes(action)
  ) {
    error.value = "售后阶段或审批已变化，请重新读取证据后核对。";
    return;
  }
  if (
    await store.changeAfterSalesCase(
      current,
      action,
      reason.value,
      evidence.value,
      inspection.value || undefined,
    )
  )
    command.value = null;
}
async function prepareLabor(entryId: number | null): Promise<void> {
  if (disabled.value || !detail.value || !store.can("after_sales.labor"))
    return;
  const id = detail.value.id;
  laborPending.value = true; preparing.value = true;
  laborCommand.value = null;
  laborHours.value = "";
  reason.value = "";
  evidence.value = "";
  error.value = "";
  try {
    if (
      (await store.loadAfterSalesDetail(id)) &&
      laborPending.value &&
      detail.value &&
      detail.value.kind === "repair" &&
      ["received", "repaired"].includes(detail.value.status)
    ) {
      const active =
        entryId === null ||
        detail.value.labor.some(
          (entry) =>
            entry.id === entryId &&
            entry.action === "record" &&
            !detail.value!.labor.some(
              (reverse) => reverse.original_id === entryId,
            ),
        );
      if (active) laborCommand.value = { row: detail.value, entryId };
    }
  } finally {
    laborPending.value = false; preparing.value = false;
  }
}
async function executeLabor(): Promise<void> {
  if (!laborCommand.value) return;
  const { row, entryId } = laborCommand.value;
  const saved =
    entryId === null
      ? await store.recordAfterSalesLabor(
          row,
          laborHours.value,
          reason.value,
          evidence.value,
        )
      : await store.reverseAfterSalesLabor(
          row,
          entryId,
          reason.value,
          evidence.value,
        );
  if (saved) laborCommand.value = null;
}
function canAssess(row: AfterSalesEvidence): boolean {
  return (
    store.can("after_sales.review") &&
    store.can("after_sales.view") &&
    !row.author_ids.includes(user.value?.id ?? 0) &&
    [
      "submitted",
      "approved",
      "processing",
      "received",
      "repaired",
      "closed",
    ].includes(row.status)
  );
}
async function prepareResponsibility(id: number): Promise<void> {
  if (disabled.value) return;
  responsibilityPending.value = true; preparing.value = true;
  responsibilityCommand.value = null;
  reason.value = "";
  responsibilityOutcome.value = "";
  responsibilityBasis.value = "";
  error.value = "";
  try {
    if (
      (await store.loadAfterSalesDetail(id)) &&
      responsibilityPending.value &&
      detail.value &&
      canAssess(detail.value)
    ) {
      responsibilityCommand.value = detail.value;
      responsibilityOutcome.value = detail.value.responsibility?.outcome ?? "";
      responsibilityBasis.value = detail.value.responsibility?.basis ?? "";
    }
  } finally {
    responsibilityPending.value = false; preparing.value = false;
  }
}
async function executeResponsibility(): Promise<void> {
  if (!responsibilityCommand.value || !responsibilityOutcome.value) return;
  if (
    await store.assessAfterSalesResponsibility(
      responsibilityCommand.value,
      responsibilityOutcome.value,
      responsibilityBasis.value,
      reason.value,
    )
  )
    responsibilityCommand.value = null;
}
function selectMode(value: "sources" | "records"): void {
  if (busy.value) return;
  mode.value = value; summary.value = '';
  editor.value = false;
  query.value = "";
  store.clearAfterSalesDetail();
}
watch(
  () =>
    `${server.value?.id}:${server.value?.fingerprint}:${user.value?.id}:${user.value?.roles?.join("|")}:${user.value?.permissions.join("|")}`,
  () => {
    command.value = null;
    laborCommand.value = null;
    responsibilityCommand.value = null;
    editor.value = false; editorPending.value = false;
    if (!connectionLost.value && store.can("after_sales.view"))
      void store.loadAfterSales();
  },
);
watch(connectionLost, () => {
  command.value = null;
  laborCommand.value = null;
  responsibilityCommand.value = null;
  if (!connectionLost.value && store.can("after_sales.view"))
    void store.loadAfterSales();
});
onMounted(() => {
  void store.loadAfterSales();
});
onUnmounted(() => {editorPending.value=false;store.clearAfterSalesDetail()});
</script>
<template>
  <section class="stack after-workspace">
    <Teleport defer to="#workspace-page-summary"><WorkspaceSummaryFilters v-model="summary" :options="counts" /></Teleport>
    <SalesSectionTabs :model-value="mode" :disabled="busy" label="售后列表分类" :options="[{key:'sources',label:'原出库来源'},{key:'records',label:'售后记录'}]" @update:model-value="selectMode" />
    <p v-if="connectionLost" role="alert">
      服务端连接中断，旧证据及动作已失效。同账号未保存输入保留，恢复连接后刷新并核对版本。
    </p>
    <p v-if="failure" role="alert">{{ failure }} 请刷新来源与记录后重试。</p>
    <!-- 编辑表单与来源列表分开，关闭只收起弹窗，未保存输入仍由原 store 保留。 -->
    <AppModal class="sales-editor-dialog" preset="card" :show="editor || editorPending" :ready="!editorPending" :busy="busy" :load-error="failure"
      :title="store.afterSalesEdit ? '修订售后申请' : '编制售后申请'" :style="{width:'min(1100px,calc(100vw - 32px))',maxHeight:'calc(100vh - 48px)'}"
      @update:show="value=>{if(!value){editor=false;editorPending=false}}" @invalidated="editor=false;editorPending=false">
      <div class="after-workspace sales-editor-host">
    <AfterSalesEditor dialog
      v-if="editor && store.can('after_sales.create')"
      @close="editor = false"
      @saved="
        editor = false;
        mode = 'records';
      "
    />
      </div>
    </AppModal>
      <WorkspaceTable
        v-if="mode === 'sources'"
        title="售后出库来源"
        :show-title="false"
        :columns="sourceColumns"
        :data="sourcePages.rows.value" :pagination="{page:sourcePages.page.value,pageSize:sourcePages.pageSize.value,total:sourcePages.total.value}" @page-change="sourcePages.changePage"
        :min-table-width="1000"
        :loading="loading"
      >
        <!-- 列表功能统一放入公共筛选栏右侧，权限和事件沿用原按钮。 -->
        <template #actions>
          <AppButton :disabled="disabled" @click="store.loadAfterSales()">{{
          loading ? "正在读取…" : "刷新来源与记录"
        }}</AppButton>
        </template>
        <template #filters><WorkspaceSearchFilters v-model:query="query" v-model:filters="searchFilters" search-label="搜索原出库" search-placeholder="客户、订单、出库或物料" :reset-disabled="!query&&!summary" @reset="query='';summary=''" /></template>
        <template #cell-document="{row}">{{relatedDocumentLabel(row,'shipment')}}</template>
        <template #cell-order="{row}">{{relatedDocumentLabel(row,'sales_order')}}</template>
        <template #cell-actions="{ row }"
          ><AppButton
            v-if="store.can('after_sales.create')" size="small"
            :disabled="disabled || Number(row.remaining_quantity) <= 0"
            @click="newRecord(row.shipment_line_id)"
            >编制售后</AppButton
          ><span v-else>只读来源</span></template
        >
        <template #empty
          >没有可用的已确认出库来源，请先按销售流程交付；已冲销出库不能新增售后。</template
        >
      </WorkspaceTable>
      <WorkspaceTable
        v-else
        title="售后记录"
        :show-title="false"
        :columns="recordColumns"
        :data="recordPages.rows.value" :pagination="{page:recordPages.page.value,pageSize:recordPages.pageSize.value,total:recordPages.total.value}" @page-change="recordPages.changePage"
        :min-table-width="1100"
        :loading="loading"
      >
        <!-- 列表功能统一放入公共筛选栏右侧，权限和事件沿用原按钮。 -->
        <template #actions>
          <AppButton :disabled="disabled" @click="store.loadAfterSales()">{{
          loading ? "正在读取…" : "刷新来源与记录"
        }}</AppButton>
        </template>
        <template #filters><WorkspaceSearchFilters v-model:query="query" v-model:filters="searchFilters" search-label="搜索售后" search-placeholder="单号、客户、物料或阶段" :reset-disabled="!query&&!summary" @reset="query='';summary=''" /></template>
        <template #cell-document="{row}"><AppButton variant="text" :disabled="disabled" :aria-label="`查看单据 ${documentLabel(row)} 详情`" @click.capture="captureDialogOrigin('after-sales-detail',$event)" @click="store.loadAfterSalesDetail(row.id)">{{documentLabel(row)}}</AppButton></template>
        <template #cell-customer="{row}">{{row.frozen_source.customer_name}}</template>
        <template #cell-material="{row}">{{row.frozen_source.material_name}}</template>
        <template #cell-kind="{row}">{{afterSalesKind[row.kind as keyof typeof afterSalesKind]}}</template>
        <template #cell-quantity="{row}">{{row.quantity}} {{row.frozen_source.unit}}</template>
        <template #cell-fee="{row}">{{row.kind==='repair'?(row.charge_mode==='free'?'免费':row.fee_amount):'—'}}</template>
        <template #cell-stage="{row}"><AppStatusTag :label="afterSalesStatus[row.status as keyof typeof afterSalesStatus]" :tone="caseTone(row)" /></template>
        <!-- 行内只保留查看入口，阶段操作统一移入下方证据面板操作区。 -->
        <template #cell-actions="{ row }"
          ><AppButton
            type="button"
            variant="secondary"
            size="small"
            :disabled="disabled"
            :aria-label="`查看单据 ${documentLabel(row)} 详情`"
            @click.capture="captureDialogOrigin('after-sales-detail',$event)" @click="store.loadAfterSalesDetail(row.id)"
            >查看</AppButton
          ></template
        >
        <template #empty
          >尚无售后记录。选择原出库编制申请，提交后独立审核。</template
        >
      </WorkspaceTable>
      <!-- 售后证据和阶段操作集中在详情弹窗，不再堆叠在列表下方。 -->
      <AppModal origin-key="after-sales-detail" preset="card" title="售后详情" :show="!!detail && !editor && !editorPending" :busy="busy" :style="{width:'min(1200px,calc(100vw - 32px))',maxHeight:'calc(100vh - 48px)',overflowY:'auto'}"
        @update:show="value=>{if(!value)store.clearAfterSalesDetail()}" @invalidated="store.clearAfterSalesDetail()">
        <div class="after-workspace stack">
      <!-- 操作色与详情一致：更正/驳回为红色、取消为橙色、执行为绿色、编辑为蓝色。 -->
      <!-- 证据面板统一承载该售后单的阶段操作，行内不再堆叠按钮。 -->
      <div v-if="detail" class="section-heading after-detail-heading"><h3>基本资料</h3><div class="after-toolbar">
        <AppButton size="small"

          v-if="
            store.can('after_sales.create') &&
            ['draft', 'rejected'].includes(detail.status)
          "
          :disabled="disabled"
          @click="editRecord(detail.id)"
          >修订</AppButton
        ><AppButton size="small"

          :disabled="disabled"
          @click.capture="captureDialogOrigin('document-approval', $event)" @click="
            store.openDocumentApproval({
              document_type: 'AfterSalesCase',
              document_id: detail.id,
              intent: 'execute',
            })
          "
          >单据审批</AppButton
        ><AppButton size="small"
          tone="error"
          v-if="detail.status === 'closed' && store.can('after_sales.reverse')"
          :disabled="disabled"
          @click.capture="captureDialogOrigin('document-approval', $event)" @click="
            store.openDocumentApproval({
              document_type: 'AfterSalesCase',
              document_id: detail.id,
              intent: 'reverse',
            })
          "
          >结案更正审批</AppButton
        ><AppButton size="small"
          :tone="
            action === 'reverse' || action === 'reject'
              ? 'error'
              : action === 'cancel'
                ? 'warning'
                : action === 'submit' ? 'info' : 'success'
          "
          v-for="action in actions(detail)"
          :key="action"
          :disabled="disabled"
          @click.capture="captureDialogOrigin('AfterSalesView:command', $event)" @click="prepare(detail.id, action)"
          >{{ afterSalesCommand[action] }}</AppButton
        >
      </div></div>
      <AfterSalesEvidenceView v-if="detail" :row="detail" hide-heading />
      <AfterSalesLaborCost
        v-if="detail?.kind === 'repair' && store.can('after_sales.cost')"
        :row="detail"
      />
      <AfterSalesRepairMargin
        v-if="detail?.kind === 'repair' && store.can('after_sales.cost')"
        :row="detail"
      />
      <AfterSalesAttachments v-if="detail" :case-id="detail.id" />
      <div v-if="detail && canAssess(detail)" class="after-toolbar">
        <AppButton
          :disabled="disabled"
          @click.capture="captureDialogOrigin('AfterSalesView:responsibility', $event)" @click="prepareResponsibility(detail.id)"
          >{{
            detail.responsibility ? "更正责任核定" : "登记责任核定"
          }}</AppButton
        >
      </div>
      <div
        v-if="
          detail?.kind === 'repair' &&
          ['received', 'repaired'].includes(detail.status) &&
          store.can('after_sales.labor')
        "
        class="after-toolbar"
      >
        <AppButton :disabled="disabled" @click.capture="captureDialogOrigin('AfterSalesView:labor', $event)" @click="prepareLabor(null)"
          >登记实际维修工时</AppButton
        >
        <AppButton
          v-for="entry in detail.labor.filter(
            (item) =>
              item.action === 'record' &&
              !detail!.labor.some((reverse) => reverse.original_id === item.id),
          )"
          :key="entry.id"
          :disabled="disabled"
          @click.capture="captureDialogOrigin('AfterSalesView:labor', $event)" @click="prepareLabor(entry.id)"
          >更正工时 {{ documentLabel(entry) }}</AppButton
        >
      </div>
        </div>
      </AppModal>
    <DocumentApprovalDialog origin-key="document-approval" title="售后方案审批" />
    <AppModal :busy="busy" origin-key="AfterSalesView:command" @invalidated="commandPending = false; command = null" :ready="!commandPending && !!command" :load-error="failure"
      :show="commandPending || !!command"
      preset="card"
      :title="command ? afterSalesCommand[command.action] : ''"
      style="
        width: min(800px, calc(100vw - 48px));
        max-height: calc(100vh - 48px);
        overflow: auto;
      "
      :mask-closable="!busy"
      :closable="!busy"
      @update:show="
        (value) => {
          if (!value && !busy) command = null;
        }
      "
    >
      <form v-if="command" class="after-operation" @submit.prevent="execute">
        <AfterSalesEvidenceView :row="command.row" compact />
        <p v-if="command.action === 'process'">
          建立关联草稿后，退货须由仓库确认。换货销售订单在有效退货确认后才能继续；此操作不直接变动库存或金额。
        </p>
        <p v-if="command.action === 'receive'">
          登记实际收到的客户物品；公司耗材另建其他出库草稿，须按原流程确认，不把客户物品记为公司入库。
        </p>
        <p v-if="command.action === 'close'">
          依据实际交付结案。维修须先检验合格并交还客户；收费形成原订单维修应收，免费不形成收费来源。
        </p>
        <p v-if="command.action === 'cancel'">
          已办理关联草稿须先取消；已收件维修须填写实际交还依据，已使用的公司耗材记录继续保留。
        </p>
        <p v-if="command.action === 'reverse'">
          保留原结案及交接历史。{{ afterSalesReversalHint(command.row) }}
        </p>
        <label v-if="command.action === 'inspect'"
          >维修检验结果<WorkspaceSelect
            v-model="inspection"
            :options="[
              { label: '请选择检验结果', value: '', disabled: true },
              { label: '检验合格，可办理交还', value: 'pass' },
              { label: '检验不合格，继续维修', value: 'fail' },
            ]"
            :disabled="busy"
            required
        /></label>
        <p v-if="command.action === 'reverse'">
          更正原因采用已经批准的固定内容。
        </p>
        <label v-else
          >操作原因<AppInput
            v-model.trim="reason"
            maxlength="200"
            required
            :disabled="busy"
        /></label>
        <label
          >实际交接、检验或客户确认依据<AppInput
            v-model.trim="evidence"
            maxlength="400"
            :required="
              ['receive', 'inspect', 'close'].includes(command.action) ||
              (['received', 'repaired'].includes(command.row.status) &&
                command.action === 'cancel')
            "
            :disabled="busy"
        /></label>
        <p v-if="error" role="alert">
          {{ error }} 原因和依据已保留；请重新加载最新证据后核对。
        </p>
        <div class="after-toolbar">
          <AppButton
            type="submit"
            variant="primary"
            :tone="
              command.action === 'reverse' || command.action === 'reject'
                ? 'error'
                : command.action === 'cancel'
                  ? 'warning'
                  : command.action === 'submit' ? 'info' : 'success'
            "
            :disabled="
              busy ||
              connectionLost ||
              (command.action !== 'reverse' && !reason.trim()) ||
              (command.action === 'inspect' && !inspection)
            "
            >{{
              busy ? "正在处理…" : afterSalesCommand[command.action]
            }}</AppButton
          ><AppButton :disabled="busy" @click="command = null"
            >返回核对</AppButton
          >
        </div>
      </form>
    </AppModal>
    <AppModal :busy="busy" origin-key="AfterSalesView:responsibility" @invalidated="responsibilityPending = false; responsibilityCommand = null" :ready="!responsibilityPending && !!responsibilityCommand" :load-error="failure"
      :show="responsibilityPending || !!responsibilityCommand"
      preset="card"
      :title="
        responsibilityCommand?.responsibility ? '更正责任核定' : '登记责任核定'
      "
      style="width: min(700px, calc(100vw - 48px))"
      :mask-closable="!busy"
      :closable="!busy"
      @update:show="
        (value) => {
          if (!value && !busy) responsibilityCommand = null;
        }
      "
    >
      <form
        v-if="responsibilityCommand"
        class="after-operation"
        @submit.prevent="executeResponsibility"
      >
        <p>
          {{ responsibilityCommand.reference }} · v{{
            responsibilityCommand.version
          }}。结合合同、故障和检验资料人工核定；保修期限、收费方案及库存不会自动变化。
        </p>
        <label
          >责任结果<WorkspaceSelect
            v-model="responsibilityOutcome"
            :options="[
              { label: '请选择责任结果', value: '', disabled: true },
              { label: '本公司责任', value: 'company' },
              { label: '客户责任', value: 'customer' },
              { label: '第三方责任', value: 'third_party' },
              { label: '暂无法判定', value: 'undetermined' },
            ]"
            :disabled="busy"
            required
        /></label>
        <label
          >核定依据<AppInput
            v-model.trim="responsibilityBasis"
            maxlength="400"
            required
            :disabled="busy"
        /></label>
        <label
          >登记或更正原因<AppInput
            v-model.trim="reason"
            maxlength="200"
            required
            :disabled="busy"
        /></label>
        <p v-if="error" role="alert">
          {{ error }} 输入已保留；请重新加载证据核对。
        </p>
        <div class="after-toolbar">
          <AppButton
            type="submit"
            variant="primary"
            :disabled="
              disabled ||
              !responsibilityOutcome ||
              !responsibilityBasis.trim() ||
              !reason.trim()
            "
            >保存核定</AppButton
          ><AppButton :disabled="busy" @click="responsibilityCommand = null"
            >返回核对</AppButton
          >
        </div>
      </form>
    </AppModal>
    <AppModal :busy="busy" origin-key="AfterSalesView:labor" @invalidated="laborPending = false; laborCommand = null" :ready="!laborPending && !!laborCommand" :load-error="failure"
      :show="laborPending || !!laborCommand"
      preset="card"
      :title="laborCommand?.entryId ? '更正维修工时' : '登记实际维修工时'"
      style="width: min(700px, calc(100vw - 48px))"
      :mask-closable="!busy"
      :closable="!busy"
      @update:show="
        (value) => {
          if (!value && !busy) laborCommand = null;
        }
      "
    >
      <form
        v-if="laborCommand"
        class="after-operation"
        @submit.prevent="executeLabor"
      >
        <p>
          {{ laborCommand.row.reference }} · 净工时
          {{ laborCommand.row.labor_hours }} 小时 · v{{
            laborCommand.row.version
          }}
        </p>
        <p v-if="laborCommand.entryId">
          更正原记录 #{{ laborCommand.entryId }}
          将追加等量反向记录，保留原记录与证据。
        </p>
        <label v-else
          >实际维修小时<AppInput
            v-model.trim="laborHours"
            type="number"
            min="0.01"
            max="100000"
            step="0.01"
            required
            :disabled="busy"
        /></label>
        <label
          >原因<AppInput
            v-model.trim="reason"
            maxlength="200"
            required
            :disabled="busy"
        /></label>
        <label
          >实际依据<AppInput
            v-model.trim="evidence"
            maxlength="400"
            required
            :disabled="busy"
        /></label>
        <p>
          工时作为作业证据；财务可独立核定内部标准成本，不自动形成收费、应付或总账分录。
        </p>
        <p v-if="error" role="alert">
          {{ error }} 输入已保留；请重新加载最新证据后核对。
        </p>
        <div class="after-toolbar">
          <AppButton
            type="submit"
            variant="primary"
            :disabled="
              disabled ||
              !reason.trim() ||
              !evidence.trim() ||
              (!laborCommand.entryId && !laborHours.trim())
            "
            >确认记录</AppButton
          ><AppButton :disabled="busy" @click="laborCommand = null"
            >返回核对</AppButton
          >
        </div>
      </form>
    </AppModal>
  </section>
</template>
<style scoped>
/* 详情标题与小号操作同排，完整业务资料紧随其后。 */
.after-detail-heading {flex-wrap:wrap;gap:12px}
.after-detail-heading h3 {font-size:15px;margin:0}

.after-workspace {
  --after-secondary: #50667d;
}
:global(:root[data-theme="dark"] .after-workspace) {
  --after-secondary: #9aadc5;
}
.after-workspace :deep(.after-toolbar),
.after-operation .after-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.after-workspace :deep(.after-secondary) {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  color: var(--after-secondary);
  overflow-wrap: anywhere;
}
/* 明细按钮聚焦由页面承接滚动，避免隐藏视口的纵向偏移裁掉表头。 */
.after-workspace :deep(.vxe-table--viewport-wrapper) {
  overflow: clip;
}
.after-operation {
  display: grid;
  gap: 18px;
}
.after-workspace :deep(.after-wide) {
  grid-column: 1/-1;
}
.after-workspace :deep(.after-material) {
  display: grid;
  grid-template-columns: minmax(240px, 2fr) minmax(150px, 1fr) auto;
  gap: 12px;
  align-items: end;
  margin-top: 12px;
}
@media (max-width: 1000px) {
  .after-workspace :deep(.form-grid) {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .after-workspace :deep(.after-material) {
    grid-template-columns: minmax(0, 1fr) minmax(120px, 1fr);
  }
  .after-workspace :deep(.after-material button) {
    justify-self: start;
  }
}
</style>
