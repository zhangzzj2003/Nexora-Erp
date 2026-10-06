<script setup lang="ts">
// 页面只展示服务端保存的单号，原内部 ID 继续用于业务操作。
import { relatedDocumentLabel } from '../../../../../shared/document-numbering'
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
import { computed, ref } from 'vue'
import { matchesRecordQuery } from '../../../utils/workspace-records'
import { storeToRefs } from 'pinia'
import { usePiniaAppStore } from '../../../store/app-store'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'

// 应收应付只负责汇总与订单核对，三个财务页面仍读取同一份服务端快照。
const store = usePiniaAppStore()
const { receivablesPayables, financeAccounts } = storeToRefs(store)
const { navigateToRoute } = store
const accountQuery = ref('')
const accountColumns = [
  { key: 'kind', title: '类别' },
  { key: 'party', title: '往来单位' },
  { key: 'order', title: '订单' },
  { key: 'business', title: '业务净额' },
  { key: 'settled', title: '收付款净额' },
  { key: 'outstanding', title: '未结金额' },
  { key: 'sources', title: '来源明细' }
]
const filteredAccounts = computed(() =>
  financeAccounts.value.filter((item) =>
    matchesRecordQuery(accountQuery.value, [item.order_id, item.party_name])
  )
)
</script>

<template>
  <section v-if="receivablesPayables" class="stack">
    <WorkspaceTable
      :show-title="false"
      title="订单核对"
      :columns="accountColumns"
      :data="filteredAccounts"
      :min-table-width="980"
    >
      <template #actions>
        <AppButton type="button" @click="navigateToRoute('financePayments')" variant="secondary"
          >收付款记录</AppButton
        >
        <AppButton type="button" @click="navigateToRoute('financeSources')" variant="secondary"
          >查看金额来源</AppButton
        >
      </template>
      <template #filters>
        <label>
          搜索订单
          <AppInput v-model="accountQuery" placeholder="输入编号或名称" />
        </label>
      </template>
      <template #beforeTable>
        <div class="summary-grid">
          <div class="metric">
            <span>业务应收净额</span>
            <strong>¥{{ receivablesPayables.receivable_amount }}</strong>
          </div>
          <div class="metric">
            <span>业务应付净额</span>
            <strong>¥{{ receivablesPayables.payable_amount }}</strong>
          </div>
          <div class="metric">
            <span>待定价明细</span>
            <strong>{{ receivablesPayables.unpriced_count }}</strong>
          </div>
        </div>
        <p class="muted">
          未结金额 = 已确认业务净额 − 收付款净额。负数表示应退客户或应收供应商退款。
        </p>
      </template>
      <template #cell-kind="{ row: item }">
        {{ item.kind === 'receivable' ? '应收' : '应付' }}
      </template>
      <template #cell-party="{ row: item }">{{ item.party_name }}</template>
      <template #cell-order="{ row: item }">{{ relatedDocumentLabel(item, 'order') }}</template>
      <template #cell-business="{ row: item }">¥{{ item.business_amount }}</template>
      <template #cell-settled="{ row: item }">¥{{ item.settled_amount }}</template>
      <template #cell-outstanding="{ row: item }">
        <strong>¥{{ item.outstanding_amount }}</strong>
      </template>
      <template #cell-sources="{ row: item }">{{ item.source_keys.length }} 笔</template>
      <template #empty>暂无可核对的订单金额。</template>
    </WorkspaceTable>
  </section>
</template>
