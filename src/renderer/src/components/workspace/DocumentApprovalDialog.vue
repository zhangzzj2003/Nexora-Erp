<script setup lang="ts">
import { computed } from "vue";
import { storeToRefs } from "pinia";
import WorkspaceDocumentDialog from "./WorkspaceDocumentDialog.vue";
import AppButton from "../app/AppButton.vue";
import { documentApprovalLayout } from "../../utils/document-approval-layout";
import { usePiniaAppStore } from "../../store/app-store";
import DocumentApprovalPanel from "./DocumentApprovalPanel.vue";
import OtherInboundReopenTrace from "./OtherInboundReopenTrace.vue";

// 审批复用查看详情的公共单据布局，业务内容始终来自服务端送审快照。
withDefaults(defineProps<{ title?: string }>(), { title: "单据审批" });
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
const columns = [
  { key: "label", title: "物料编码 / 名称", width: "440" },
  { key: "value", title: "数量 / 单位", width: "140" },
];
</script>

<template>
  <!-- 未打开时不读取审批摘要，保持页面进入时审批内容按需加载的原行为。 -->
  <WorkspaceDocumentDialog
    :show="!!target"
    read-only
    :busy="busy"
    class="document-approval-dialog"
    :data="target ? layout.lines : []"
    :columns="columns"
    :show-lines="!!target && layout.showLines"
    :min-table-width="580"
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
          (id) =>
            store.openDocumentApproval({
              document_type: 'WarehouseInbound',
              document_id: id,
              intent: 'execute',
            })
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
        <span>{{ item.label }}</span
        ><strong>{{ item.value }}</strong>
      </div>
    </template>
    <template #cell-label="{ row }"
      ><strong class="approval-value">{{ row.label }}</strong></template
    >
    <template #cell-value="{ row }"
      ><span class="approval-value">{{ row.value }}</span></template
    >
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
