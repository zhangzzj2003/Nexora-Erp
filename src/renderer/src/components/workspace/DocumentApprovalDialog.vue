<script setup lang="ts">
import { computed } from "vue";
import { storeToRefs } from "pinia";
import WorkspaceDocumentDialog from "./WorkspaceDocumentDialog.vue";
import AppButton from "../app/AppButton.vue";
import AppStatusTag from "../app/AppStatusTag.vue";
import { documentApprovalLayout } from "../../utils/document-approval-layout";
import { usePiniaAppStore } from "../../store/app-store";
import DocumentApprovalPanel from "./DocumentApprovalPanel.vue";
import OtherInboundReopenTrace from "./OtherInboundReopenTrace.vue";
import WorkspaceMaterialName from './WorkspaceMaterialName.vue'
import { captureDialogOrigin } from '../../utils/dialog-origin';

// 审批复用查看详情的公共单据布局，业务内容始终来自服务端送审快照。
withDefaults(defineProps<{ title?: string; originKey?: string }>(), { title: "单据审批", originKey: "document-approval" });
// 业务状态操作统一在页脚承载：提示语、审批控件、页面业务按钮与关闭依次排开。
defineSlots<{
  default?: () => unknown;
  footerHint?: () => unknown;
  footerActions?: () => unknown;
}>();
const store = usePiniaAppStore();
const {
  documentApprovalTarget: target,
  documentApprovalRecord: record,
  busy,
  documentApprovalLoading: loading,
  documentApprovalError: error,
  connectionLost,
} = storeToRefs(store);
const disabled = computed(
  () => busy.value || loading.value || connectionLost.value,
);
// 列表可能仍保留旧权限；只有当前单据及意图的审批读取成功后才挂载业务操作。
// 不限制审批状态或 content_matches，保留草稿取消、编辑等各页面已有的业务规则。
const businessActionsReady = computed(
  () =>
    !loading.value && !error.value && !connectionLost.value &&
    !!target.value && !!record.value &&
    record.value.document_type === target.value.document_type &&
    record.value.document_id === target.value.document_id &&
    record.value.intent === target.value.intent,
);
const layout = computed(() => documentApprovalLayout(record.value));
const planLines = computed(() => record.value?.document_type === 'ProductionPlan'
  && layout.value.lines.length > 0 && layout.value.lines.every(item => !!item.production_plan_line));
// 仅完整结构化快照采用分列，旧服务摘要继续原文展示，避免按分隔符猜测产品名称。
const columns = computed(() => planLines.value ? [
  { key: 'sku', title: '产品编号', width: '180' }, { key: 'product', title: '产品名称', width: '240' },
  { key: 'bom', title: 'BOM 版本', width: '110' }, { key: 'quantity', title: '计划产量', width: '120' },
  { key: 'dates', title: '排期', width: '190' }, { key: 'warehouse', title: '完工仓库', width: '140' },
  { key: 'priority', title: '优先级', width: '110' }
] : [
  { key: "label", title: "物料编码 / 名称", width: "440" },
  { key: "value", title: "数量 / 单位", width: "140" },
]);
</script>

<template>
  <!-- 未打开时不读取审批摘要，保持页面进入时审批内容按需加载的原行为。 -->
  <WorkspaceDocumentDialog
    :show="!!target"
    :origin-key="originKey"
    :ready="!!target && businessActionsReady"
    :load-error="error"
    read-only
    :busy="busy"
    class="document-approval-dialog"
    :data="target ? layout.lines : []"
    :columns="columns"
    :show-lines="!!target && layout.showLines"
    :min-table-width="planLines ? 1090 : 580"
    :lines-title="record?.document_type === 'ProductionPlan' ? '计划产品' : '物料明细'"
    :title="`${title}${target?.intent === 'reverse' ? (['OpeningBalance', 'SubledgerOpening'].includes(target.document_type) ? ' · 撤销审批' : ' · 冲销审批') : ''}${record?.document_no ? ` · ${record.document_no}` : ''}`"
    @update:show="
      (value) => {
        if (!value) store.closeDocumentApproval();
      }
    "
  >
    <template #beforeBasicInfo>
      <!-- 进度优先展示，单据正文与历史仍使用同一服务端快照。 -->
      <DocumentApprovalPanel part="progress" />
      <!-- 重开是独立业务事件，不伪装为原单审批步骤；两端可查看各自真实审批。 -->
      <OtherInboundReopenTrace
        v-if="record?.reopen_trace?.length"
        :links="record.reopen_trace"
        :current-id="record.document_id"
        :local-time="store.localTime"
        :disabled="disabled"
        @open="
          (id, event) => {
            captureDialogOrigin(originKey, event);
            store.openDocumentApproval({
              document_type: 'WarehouseInbound',
              document_id: id,
              intent: 'execute',
            });
          }
        "
      />
      <slot />
    </template>
    <template #basicInfo>
      <div
        v-for="(item, index) in layout.basic"
        :key="index"
        class="document-detail-field"
      >
        <!-- 原送审的物料名称与数量由公共名称组件承载，参数仍只是当前档案参考。 -->
        <WorkspaceMaterialName v-if="item.material_id" :name="item.label" :secondary="item.value" :material-id="item.material_id" :material="item.material" />
        <template v-else><span>{{ item.label }}</span><strong>{{ item.value }}</strong></template>
      </div>
    </template>
    <template #cell-label="{ row }"
      ><WorkspaceMaterialName :name="row.label" :material-id="row.material_id" :material="row.material" /></template
    >
    <template #cell-value="{ row }"
      ><span class="approval-value">{{ row.value }}</span></template
    >
    <!-- 名称与业务字段取原送审数据，“查看资料”仅提供当前参数参考。 -->
    <template #cell-sku="{ row }">{{ row.production_plan_line?.sku }}</template>
    <template #cell-product="{ row }">
      <WorkspaceMaterialName v-if="row.production_plan_line" :name="row.production_plan_line.name" :secondary="row.production_plan_line.sales_source" :material-id="row.material_id" :material="row.material" />
    </template>
    <template #cell-bom="{ row }">BOM V{{ row.production_plan_line?.bom_version }}</template>
    <template #cell-quantity="{ row }">{{ row.production_plan_line?.quantity }} {{ row.production_plan_line?.unit }}</template>
    <template #cell-dates="{ row }">{{ row.production_plan_line?.start_date }}<br />至 {{ row.production_plan_line?.end_date }}</template>
    <template #cell-warehouse="{ row }">{{ row.production_plan_line?.warehouse_name }}</template>
    <template #cell-priority="{ row }">
      <AppStatusTag v-if="row.production_plan_line" :label="({ normal: '普通', high: '优先', urgent: '紧急' } as const)[row.production_plan_line.priority]"
        :tone="({ normal: 'neutral', high: 'pending', urgent: 'danger' } as const)[row.production_plan_line.priority]" />
    </template>
    <template #afterLines>
      <DocumentApprovalPanel part="opinion" />
    </template>
    <template #footer>
      <!-- 页脚固定承载操作：提示语靠左，审批控件、业务按钮与关闭统一右对齐。 -->
      <p v-if="$slots.footerHint" class="approval-dialog-hint">
        <slot name="footerHint" />
      </p>
      <div class="approval-dialog-actions">
        <DocumentApprovalPanel part="actions" />
        <slot v-if="businessActionsReady" name="footerActions" />
        <!-- 读取或断线不锁住退出；仅写入期间阻止关闭，与标题栏及 store 保持一致。 -->
        <AppButton
          type="button"
          :disabled="busy"
          @click="store.closeDocumentApproval()"
          >关闭</AppButton
        >
      </div>
    </template>
  </WorkspaceDocumentDialog>
</template>

<style scoped>
/* 审批正文保留服务端快照的换行和长文本，操作控件与详情共享。 */
.approval-value {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.approval-dialog-hint {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
}
.approval-dialog-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  margin-left: auto;
}
/* 审批控件并入同一排按钮，沿用自身的显隐规则，不再独占一行。 */
.approval-dialog-actions :deep(.approval-footer) {
  width: auto;
}
</style>
