<script setup lang="ts">
// 页面只展示服务端保存的单号，原内部 ID 继续用于业务操作。
import { documentSearch, documentLabel, relatedDocumentLabel } from '../../../../../shared/document-numbering'
// 输入框统一外观，必填、长度与数字范围仍由真实输入元素校验。
import AppInput from '../../../components/app/AppInput.vue'
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from '../../../components/app/AppButton.vue'
// 下拉选择统一使用工作台组件，业务值与切换回调保持原有类型。
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import { computed, ref } from 'vue'
import { NModal } from 'naive-ui'
import { matchesRecordQuery } from '../../../utils/workspace-records'
import { submitCreateDialog } from '../../../utils/create-dialog'
import { storeToRefs } from 'pinia'
import { usePiniaAppStore } from '../../../store/app-store'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'

// 登记与冲销集中在记录页；切换页面保留 Pinia 中的付款草稿和冲销原因。
const store = usePiniaAppStore()
const { error, notice, busy, connectionLost, financeAccounts, paymentRecords, paymentForm, reversalReasons,
  orderSettlements, orderSettlementForm, orderSettlementReversalReasons } = storeToRefs(store)
const { can, localTime, createPaymentRecord, reversePaymentRecord, createOrderSettlement,
  reverseOrderSettlement, paymentActionLabel } = store
const createOpen = ref(false)
const transferOpen = ref(false)
async function submitCreate(): Promise<void> {
  // 断线或权限撤销时不提交；保存失败继续保留弹窗供修正。
  if (connectionLost.value || !can('finance.record')) return
  await submitCreateDialog(createPaymentRecord, { busy, error, notice }, createOpen)
}
async function submitTransfer(): Promise<void> {
  if (connectionLost.value || !can('finance.record')) return
  await submitCreateDialog(createOrderSettlement, { busy, error, notice }, transferOpen)
}
const creditSource = computed(() => financeAccounts.value.find(item =>
  item.kind === orderSettlementForm.value.kind && item.order_id === orderSettlementForm.value.from_order_id))
const creditOptions = computed(() => financeAccounts.value.filter(item =>
  item.kind === orderSettlementForm.value.kind && Number(item.outstanding_amount) < 0))
const debtOptions = computed(() => financeAccounts.value.filter(item =>
  item.kind === orderSettlementForm.value.kind && item.party_id === creditSource.value?.party_id
  && item.order_id !== creditSource.value?.order_id && Number(item.outstanding_amount) > 0))
const paymentQuery = ref('')
const paymentColumns = [
  { key: 'document', title: '收付款记录' },
  { key: 'actions', title: '操作', width: '300' }
]
const filteredPayments = computed(() =>
  paymentRecords.value.filter((item) =>
    matchesRecordQuery(paymentQuery.value, [documentSearch(item), item.id,
      item.order_id,
      item.party_name,
      item.reference,
      item.created_by_name
    ])
  )
)
const transferColumns = [
  { key: 'document', title: '订单间核销' },
  { key: 'actions', title: '操作', width: '300' }
]
</script>

<template>
  <section class="stack">
    <NModal title="登记收付款"
      v-if="can('finance.record')"
      v-model:show="createOpen"
      preset="card"
      :mask-closable="!busy"
      :style="{
        width: 'min(900px, calc(100vw - 32px))',
        maxHeight: 'calc(100vh - 48px)',
        overflowY: 'auto'
      }"
    >
      <p class="muted">
        选择订单后登记真实发生的收付款。退款只在退货产生贷方余额时允许；录错请在下方冲销并重新登记。
      </p>
      <form @submit.prevent="submitCreate">
        <div class="form-grid">
          <label
            >往来类别<WorkspaceSelect
              v-model="paymentForm.kind"
              @change="paymentForm.order_id = 0"
              :options="[
                { label: '客户应收', value: 'receivable' },
                { label: '供应商应付', value: 'payable' }
              ]"
          /></label>
          <label
            >关联订单<WorkspaceSelect
              v-model="paymentForm.order_id"
              required
              :options="[
                { label: '选择已发生业务的订单', value: 0, disabled: true },
                ...financeAccounts
                  .filter((entry) => entry.kind === paymentForm.kind)
                  .map((item) => ({
                    label: (
                      ' #' +
                      item.order_id +
                      ' · ' +
                      item.party_name +
                      ' · 未结 ¥' +
                      item.outstanding_amount
                    ).trim(),
                    value: item.order_id
                  }))
              ]"
          /></label>
          <label
            >业务动作<WorkspaceSelect
              v-model="paymentForm.action"
              :options="[
                {
                  label: (paymentForm.kind === 'receivable' ? '收到客户款' : '支付供应商').trim(),
                  value: 'settlement'
                },
                {
                  label: (paymentForm.kind === 'receivable' ? '退还客户' : '收到供应商退款').trim(),
                  value: 'refund'
                }
              ]"
          /></label>
          <label
            >金额（元）<AppInput
              v-model.trim="paymentForm.amount"
              type="number"
              min="0.01"
              max="1000000000000"
              step="0.01"
              required
          /></label>
          <label
            >银行或收据参考号<AppInput
              v-model.trim="paymentForm.reference"
              required
              maxlength="100"
          /></label>
          <label>备注（可选）<AppInput v-model.trim="paymentForm.note" maxlength="200" /></label>
        </div>
        <AppButton
          type="submit"
          :disabled="busy || connectionLost || !financeAccounts.length"
          variant="primary"
        >
          登记收付款
        </AppButton>
      </form>
    </NModal>
    <NModal title="订单间核销"
      v-if="can('finance.record')"
      v-model:show="transferOpen"
      preset="card"
      :mask-closable="!busy"
      :style="{ width: 'min(820px, calc(100vw - 32px))', maxHeight: 'calc(100vh - 48px)', overflowY: 'auto' }"
    >
      <p class="muted">将同一客户或供应商订单的可用贷方余额核销到另一张未结订单。此操作不登记新的收付款。</p>
      <form @submit.prevent="submitTransfer">
        <div class="form-grid">
          <label>往来类别<WorkspaceSelect v-model="orderSettlementForm.kind"
            @change="orderSettlementForm.from_order_id = 0; orderSettlementForm.to_order_id = 0"
            :options="[{ label: '客户应收', value: 'receivable' }, { label: '供应商应付', value: 'payable' }]" /></label>
          <label>贷方来源订单<WorkspaceSelect v-model="orderSettlementForm.from_order_id" required
            @change="orderSettlementForm.to_order_id = 0"
            :options="[{ label: '选择可用贷方订单', value: 0, disabled: true },
              ...creditOptions.map(item => ({ label: `${relatedDocumentLabel(item, 'order')} · ${item.party_name} · 可用 ¥${item.outstanding_amount.slice(1)}`, value: item.order_id }))]" /></label>
          <label>待结目标订单<WorkspaceSelect v-model="orderSettlementForm.to_order_id" required
            :options="[{ label: '选择同一往来对象的未结订单', value: 0, disabled: true },
              ...debtOptions.map(item => ({ label: `${relatedDocumentLabel(item, 'order')} · 未结 ¥${item.outstanding_amount}`, value: item.order_id }))]" /></label>
          <label>核销金额（元）<AppInput v-model.trim="orderSettlementForm.amount" type="number"
            min="0.01" max="1000000000000" step="0.01" required /></label>
          <label>核销参考号<AppInput v-model.trim="orderSettlementForm.reference" maxlength="100" required /></label>
          <label>核销依据<AppInput v-model.trim="orderSettlementForm.reason" maxlength="200" required /></label>
        </div>
        <AppButton type="submit" variant="primary" :disabled="busy || connectionLost || !debtOptions.length">登记核销</AppButton>
      </form>
    </NModal>
    <!-- 冲销入口仍按原记录和反向记录判断，列表筛选不影响防重复冲销。 -->
    <WorkspaceTable
      :show-title="false"
      title="收付款与冲销记录"
      :columns="paymentColumns"
      :data="filteredPayments"
      :min-table-width="900"
    >
      <template #actions>
        <AppButton
          v-if="can('finance.record')"
          type="button"
          :disabled="busy || connectionLost"
          @click="createOpen = true"
          variant="primary"
        >
          登记收付款
        </AppButton>
      </template>
      <template #filters>
        <label>
          搜索收付款记录
          <AppInput v-model="paymentQuery" placeholder="输入编号或名称" />
        </label>
      </template>
      <template #cell-document="{ row: item }">
        <div>
          <strong>{{ documentLabel(item) }} · {{ paymentActionLabel(item) }} · {{ item.party_name }}</strong>
          <p class="muted">
            {{ localTime(item.created_at) }} ·
            {{ item.kind === 'receivable' ? '销售订单' : '采购订单' }} {{ relatedDocumentLabel(item, 'order') }} · ¥{{
              item.amount
            }}
            · 参考号 {{ item.reference }} · 操作人
            {{ item.created_by_name }}
            <span v-if="item.reverses_id">· 冲销记录 {{ relatedDocumentLabel(item, 'reverses') }}</span>
            <span v-if="item.note">· {{ item.note }}</span>
          </p>
        </div>
      </template>
      <template #cell-actions="{ row: item }">
        <form
          v-if="
            item.action !== 'reversal' &&
            !paymentRecords.some((entry) => entry.reverses_id === item.id) &&
            can('finance.reverse')
          "
          class="inline-form"
          @submit.prevent="reversePaymentRecord(item.id)"
        >
          <label>
            冲销原因
            <AppInput v-model.trim="reversalReasons[item.id]" required maxlength="200" />
          </label>
          <AppButton
            type="submit"
            :disabled="busy || connectionLost"
            variant="secondary"
            size="small"
            >冲销此记录</AppButton
          >
        </form>
      </template>
      <template #empty>{{ paymentQuery ? '没有匹配的记录。' : '暂无收付款记录。' }}</template>
    </WorkspaceTable>
    <WorkspaceTable title="订单间核销与撤销" :columns="transferColumns" :data="orderSettlements" :min-table-width="900">
      <template #actions>
        <AppButton v-if="can('finance.record')" type="button" variant="primary"
          :disabled="busy || connectionLost || !creditOptions.length" @click="transferOpen = true">订单间核销</AppButton>
      </template>
      <template #cell-document="{ row: item }">
        <div>
          <strong>{{ documentLabel(item) }} · {{ item.reverses_id ? '撤销核销' : '订单间核销' }} · {{ item.party_name }}</strong>
          <p class="muted">{{ localTime(item.created_at) }} · {{ item.kind === 'receivable' ? '销售' : '采购' }}订单
            {{ relatedDocumentLabel(item, 'from_order') }} → {{ relatedDocumentLabel(item, 'to_order') }} · ¥{{ item.amount }} · 参考号 {{ item.reference }}
            · 依据 {{ item.reason }} · 操作人 {{ item.created_by_name }}
            <span v-if="item.reverses_id"> · 原核销 {{ relatedDocumentLabel(item, 'reverses') }}</span></p>
        </div>
      </template>
      <template #cell-actions="{ row: item }">
        <form v-if="!item.reverses_id && !orderSettlements.some(record => record.reverses_id === item.id)
          && can('finance.reverse')" class="inline-form" @submit.prevent="reverseOrderSettlement(item.id)">
          <label>撤销原因<AppInput v-model.trim="orderSettlementReversalReasons[item.id]" required maxlength="200" /></label>
          <AppButton type="submit" variant="secondary" size="small" :disabled="busy || connectionLost">撤销核销</AppButton>
        </form>
      </template>
      <template #empty>暂无订单间核销记录。</template>
    </WorkspaceTable>
  </section>
</template>
