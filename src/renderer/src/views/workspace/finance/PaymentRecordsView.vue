<script setup lang="ts">
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
const { error, notice, busy, connectionLost, financeAccounts, paymentRecords, paymentForm, reversalReasons } = storeToRefs(store)
const { can, localTime, createPaymentRecord, reversePaymentRecord, paymentActionLabel } = store
const createOpen = ref(false)
async function submitCreate(): Promise<void> {
  // 断线或权限撤销时不提交；保存失败继续保留弹窗供修正。
  if (connectionLost.value || !can('finance.record')) return
  await submitCreateDialog(createPaymentRecord, { busy, error, notice }, createOpen)
}
const paymentQuery = ref('')
const paymentColumns = [
  { key: 'document', title: '收付款记录' },
  { key: 'actions', title: '操作', width: '300' }
]
const filteredPayments = computed(() =>
  paymentRecords.value.filter((item) =>
    matchesRecordQuery(paymentQuery.value, [
      item.id,
      item.order_id,
      item.party_name,
      item.reference,
      item.created_by_name
    ])
  )
)
</script>

<template>
  <section class="stack">
    <NModal
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
      <div class="section-heading">
        <div>
          <p class="eyebrow">PAYMENT RECORD</p>
          <h2>登记收付款</h2>
        </div>
      </div>
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
            >关联订单<WorkspaceSelect remote-dataset="financeAccounts" :remote-filters="{ kind: paymentForm.kind }"
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
          :disabled="busy || connectionLost"
          variant="primary"
        >
          登记收付款
        </AppButton>
      </form>
    </NModal>
    <!-- 冲销入口仍按原记录和反向记录判断，列表筛选不影响防重复冲销。 -->
    <WorkspaceTable dataset="paymentRecords" :query="paymentQuery"
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
          <strong>#{{ item.id }} · {{ paymentActionLabel(item) }} · {{ item.party_name }}</strong>
          <p class="muted">
            {{ localTime(item.created_at) }} ·
            {{ item.kind === 'receivable' ? '销售订单' : '采购订单' }} #{{ item.order_id }} · ¥{{
              item.amount
            }}
            · 参考号 {{ item.reference }} · 操作人
            {{ item.created_by_name }}
            <span v-if="item.reverses_id">· 冲销记录 #{{ item.reverses_id }}</span>
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
  </section>
</template>
