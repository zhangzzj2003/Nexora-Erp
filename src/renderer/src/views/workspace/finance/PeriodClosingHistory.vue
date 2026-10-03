<script setup lang="ts">
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
import AppCollapseItem from '../../../components/app/AppCollapseItem.vue'
import { NCollapse } from 'naive-ui'
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import type { PeriodClosingRecord } from '../../../../../shared/erp-api'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { financialSource, localTime } from '../../../utils/formatters'
import { afterSalesKind, afterSalesStatus } from '../sales/after-sales-display'

const { periodClosingHistory: records } = storeToRefs(usePiniaAppStore())
const selected = ref<PeriodClosingRecord | null>(null)
const evidence = computed(() => selected.value && 'ledger' in selected.value.evidence ? selected.value.evidence : null)
const columns = [ { key: 'id', title: '记录号' }, { key: 'action', title: '操作' },
  { key: 'period_version', title: '期间版本' }, { key: 'created_at', title: '时间' },
  { key: 'created_by_name', title: '操作者' }, { key: 'reason', title: '依据 / 原因' }, { key: 'actions', title: '证据' } ]
const balanceColumns = [ { key: 'code', title: '科目编码' }, { key: 'name', title: '名称' },
  { key: 'opening_debit', title: '期初借方' }, { key: 'opening_credit', title: '期初贷方' },
  { key: 'debit', title: '本期借方' }, { key: 'credit', title: '本期贷方' },
  { key: 'closing_debit', title: '期末借方' }, { key: 'closing_credit', title: '期末贷方' } ]
const inventoryColumns = [ { key: 'sku', title: '物料编码' }, { key: 'name', title: '名称' },
  { key: 'quantity', title: '期末数量' }, { key: 'amount', title: '金额（元）' }, { key: 'average_unit_cost', title: '平均单价' } ]
const movementColumns = [ { key: 'id', title: '流水号' }, { key: 'created_at', title: '时间（UTC）' },
  { key: 'material_id', title: '物料号' }, { key: 'source_type', title: '来源类型' },
  { key: 'source_id', title: '来源单号' }, { key: 'quantity', title: '数量' }, { key: 'amount', title: '金额（元）' } ]
const businessColumns = [ { key: 'kind', title: '往来类别' }, { key: 'party_name', title: '往来单位' },
  { key: 'source', title: '来源' }, { key: 'order_id', title: '订单号' }, { key: 'sku', title: '物料' },
  { key: 'amount', title: '金额（元）' }, { key: 'posted_at', title: '确认时间（UTC）' } ]
const paymentColumns = [ { key: 'id', title: '记录号' }, { key: 'kind', title: '往来类别' },
  { key: 'order_id', title: '订单号' }, { key: 'action', title: '操作' }, { key: 'amount', title: '金额（元）' },
  { key: 'reference', title: '依据' }, { key: 'reverses_id', title: '冲销原记录' }, { key: 'created_by', title: '操作者编号' } ]
const movementNames: Record<string, string> = { receipt: '采购入库', receipt_reversal: '采购入库冲销',
  purchase_return: '采购退货', purchase_return_reversal: '采购退货冲销', shipment: '销售出库', shipment_reversal: '销售出库冲销',
  sales_return: '销售退货', sales_return_reversal: '销售退货冲销', other_inbound: '其他入库', other_inbound_reversal: '其他入库冲销',
  other_outbound: '其他出库', other_outbound_reversal: '其他出库冲销', transfer_in: '调拨入库', transfer_out: '调拨出库',
  transfer_reversal_in: '调拨冲销入库', transfer_reversal_out: '调拨冲销出库', stocktake: '盘点', stocktake_reversal: '盘点冲销',
  adjustment: '库存调整', adjustment_reversal: '库存调整冲销', material_issue: '生产领料',
  material_issue_reversal: '生产领料冲销', material_return: '生产退料',
  production_completion: '生产完工', production_completion_reversal: '生产完工冲销' }
</script>

<template>
  <div class="stack period-closing-history">
    <WorkspaceTable title="结账与重开记录" :columns="columns" :data="records" :min-table-width="900">
      <template #cell-action="{ row }">{{ row.action === 'close' ? '结账' : '重开' }}</template>
      <template #cell-created_at="{ row }">{{ localTime(row.created_at) }}</template>
      <template #cell-actions="{ row }"><AppButton v-if="row.action === 'close'" @click="selected = row" variant="text" type="button">查看余额快照</AppButton><span v-else class="muted">保留原结账</span></template>
      <template #empty>暂无结账记录。结账后保存余额、来源与操作者，不覆盖原记录。</template>
    </WorkspaceTable>
    <template v-if="evidence">
      <p>结账记录 {{ selected?.id }} · {{ evidence.period.start_date }} 至 {{ evidence.period.end_date }} · 保存于 {{ localTime(selected?.created_at ?? '') }}</p>
      <p class="muted">这是当次结账保存的证据。重开或后续业务不会覆盖它；金额按人民币，业务时间按 UTC。{{ evidence.opening_balance_id ? `正式期初来源：期初-${evidence.opening_balance_id}` : '当次没有正式期初来源。' }}</p>
      <WorkspaceTable title="总账余额快照（元）" :columns="balanceColumns" :data="evidence.ledger.rows" :min-table-width="920" />
      <p v-if="evidence.profit_transfer">损益结转检查：{{ evidence.profit_transfer.required ? '已纳管，损益余额已清零' : '沿用历史范围或没有待结损益' }}；配置版本 {{ evidence.profit_transfer.policy.version }}；{{ evidence.profit_transfer.journal_id ? `结转凭证记-${evidence.profit_transfer.journal_id}` : '没有有效生成结转凭证' }}。</p>
      <WorkspaceTable title="库存余额快照" :columns="inventoryColumns" :data="evidence.inventory.materials" :min-table-width="760" />
      <WorkspaceTable title="库存金额来源" :columns="movementColumns" :data="evidence.inventory.movements" :min-table-width="960"><template #cell-source_type="{ row }">{{ movementNames[row.source_type] ?? '库存流水' }}</template></WorkspaceTable>
      <p>业务应收来源净额 {{ evidence.business_sources.receivable_amount }} 元；应付来源净额 {{ evidence.business_sources.payable_amount }} 元；无价来源 {{ evidence.business_sources.unpriced_count }} 笔。收付款记录 {{ evidence.payments.length }} 笔，已过账凭证 {{ evidence.posted_journal_ids.length }} 张。</p>
      <NCollapse><AppCollapseItem name="sources" title="往来、收付款与凭证来源明细"><div class="stack">
        <WorkspaceTable title="往来来源快照" :columns="businessColumns" :data="evidence.business_sources.entries" :min-table-width="940">
          <template #cell-kind="{ row }">{{ row.kind === 'receivable' ? '应收' : '应付' }}</template>
          <template #cell-source="{ row }">{{ financialSource(row) }}</template>
          <template #cell-amount="{ row }">{{ row.amount ?? '待核价' }}</template>
        </WorkspaceTable>
        <WorkspaceTable title="收付款记录快照" :columns="paymentColumns" :data="evidence.payments" :min-table-width="940">
          <template #cell-kind="{ row }">{{ row.kind === 'receivable' ? '应收' : '应付' }}</template>
          <template #cell-action="{ row }">{{ row.action === 'settlement' ? '收付款' : row.action === 'refund' ? '退款' : '冲销' }}</template>
        </WorkspaceTable>
        <p>已过账凭证编号：{{ evidence.posted_journal_ids.length ? evidence.posted_journal_ids.join('、') : '无' }}</p>
      </div></AppCollapseItem>
      <AppCollapseItem v-if="evidence.after_sales" name="after-sales" title="售后方案与客户物品保管快照">
        <div v-for="item in evidence.after_sales" :key="item.case.id" class="stack">
          <h3>{{ item.case.reference }} · {{ afterSalesKind[item.case.kind] }} · {{ afterSalesStatus[item.case.status] }}</h3>
          <p>{{ item.source.customer_name }} · {{ item.source.sku }} {{ item.source.material_name }} · 办理数量 {{ item.case.quantity }} {{ item.source.unit }}；期末客户物品保管 {{ item.custody_quantity }} {{ item.source.unit }}。</p>
          <p>方案：{{ item.case.solution }}；客户同意依据：{{ item.case.customer_acceptance }}。</p>
          <p v-if="item.case.kind === 'repair'">收费选择：{{ item.case.charge_mode === 'charge' ? `服务费 ${item.case.fee_amount} 元` : '免费' }}。客户物品不计入公司库存。</p>
          <p v-for="event in item.custody" :key="event.id">{{ localTime(event.created_at) }} · {{ event.action === 'receive' ? '接收' : '交还' }} {{ event.quantity }} {{ item.source.unit }} · {{ event.created_by_name }} · {{ event.evidence }}</p>
        </div>
        <p v-if="!evidence.after_sales.length" class="muted">截至本期期末没有售后记录。</p>
      </AppCollapseItem></NCollapse>
    </template>
  </div>
</template>

<style scoped>
/* 展开证据后由弹窗承接纵向滚动，避免浏览器把聚焦行滚进 vxe 隐藏视口并裁掉表头。 */
.period-closing-history :deep(.vxe-table--viewport-wrapper) { overflow: clip; }
</style>
