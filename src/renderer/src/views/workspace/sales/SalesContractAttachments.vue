<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import type { SalesOrderContractAttachment } from '../../../../../shared/erp-api'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { displayError, localTime } from '../../../utils/formatters'

const props = defineProps<{ orderId: number; revisionId: number; version: number }>()
const store = usePiniaAppStore()
const { user, connectionLost } = storeToRefs(store)
const expanded = ref(false)
const rows = ref<SalesOrderContractAttachment[]>([])
const canModify = ref(false)
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const message = ref('')
const reason = ref('')
const reverseId = ref<number | null>(null)
const reverseReason = ref('')
let ticket = 0
const owner = (): string => `${user.value?.id}:${user.value?.permissions.join('|')}:${connectionLost.value}`
const columns = [
  { key: 'file_name', title: '文件' },
  { key: 'byte_count', title: '大小', width: '95' },
  { key: 'sha256', title: 'SHA-256', width: '170' },
  { key: 'created_at', title: '上传与依据', width: '250' },
  { key: 'status', title: '状态', width: '220' },
  { key: 'actions', title: '操作', width: '155' }
]

async function reload(): Promise<void> {
  if (!expanded.value || !store.can('sales.view') || connectionLost.value) return
  const current = ++ticket
  loading.value = true
  error.value = ''
  try {
    const result = await store.loadSalesContractAttachments(props.orderId, props.revisionId)
    if (current !== ticket) return
    rows.value = result.items
    canModify.value = result.can_modify
  } catch (cause) {
    if (current === ticket) error.value = displayError(cause)
  } finally {
    if (current === ticket) loading.value = false
  }
}

function reset(): void {
  ticket++
  expanded.value = false
  rows.value = []
  canModify.value = false
  loading.value = false
  error.value = ''
  message.value = ''
  reason.value = ''
  reverseId.value = null
  reverseReason.value = ''
}

function toggle(): void {
  expanded.value = !expanded.value
  if (expanded.value) void reload()
}

watch(owner, reset, { flush: 'sync' })
watch(() => `${props.orderId}:${props.revisionId}`, reset, { flush: 'sync' })
onUnmounted(() => { ticket++ })

async function upload(): Promise<void> {
  if (busy.value || connectionLost.value || !canModify.value || !store.can('sales_order.confirm') || !reason.value.trim()) return
  busy.value = true
  error.value = ''
  message.value = ''
  const current = ticket
  const orderId = props.orderId
  const revisionId = props.revisionId
  try {
    const result = await store.uploadSalesContractAttachment(orderId, revisionId, reason.value.trim())
    if (current !== ticket || orderId !== props.orderId || revisionId !== props.revisionId) return
    if (result) {
      reason.value = ''
      message.value = `已保存第 ${props.version} 版附件 ${result.file_name}。`
      await reload()
    }
  } catch (cause) {
    if (current === ticket) error.value = displayError(cause)
  } finally {
    busy.value = false
  }
}

async function download(item: SalesOrderContractAttachment): Promise<void> {
  if (busy.value || connectionLost.value || !store.can('sales.view')) return
  busy.value = true
  error.value = ''
  message.value = ''
  const current = ticket
  const orderId = props.orderId
  const revisionId = props.revisionId
  try {
    const saved = await store.saveSalesContractAttachment(orderId, revisionId, item.id)
    if (current !== ticket || orderId !== props.orderId || revisionId !== props.revisionId) return
    if (saved) message.value = `已保存附件 ${item.file_name}。`
  } catch (cause) {
    if (current === ticket) error.value = displayError(cause)
  } finally {
    busy.value = false
  }
}

async function reverse(): Promise<void> {
  if (reverseId.value === null || busy.value || connectionLost.value || !canModify.value
    || !store.can('sales_order.confirm') || !reverseReason.value.trim()) return
  busy.value = true
  error.value = ''
  message.value = ''
  const current = ticket
  const orderId = props.orderId
  const revisionId = props.revisionId
  try {
    await store.reverseSalesContractAttachment(orderId, revisionId, reverseId.value, reverseReason.value.trim())
    if (current !== ticket || orderId !== props.orderId || revisionId !== props.revisionId) return
    reverseId.value = null
    reverseReason.value = ''
    message.value = '附件已撤销，原文件与撤销记录仍可核对。'
    await reload()
  } catch (cause) {
    if (current === ticket) error.value = displayError(cause)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="contract-attachments" :aria-label="`合同第 ${version} 版附件`">
    <AppButton type="button" variant="secondary" :disabled="connectionLost" @click="toggle">
      {{ expanded ? '收起' : '查看' }}第 {{ version }} 版原件附件
    </AppButton>
    <template v-if="expanded">
      <p>支持 PDF、PNG、JPEG，单文件不超过 5 MiB，每版最多 10 个有效附件。文件留存不等于签名真实性验证。</p>
      <div v-if="store.can('sales_order.confirm') && canModify" class="contract-attachment-toolbar">
        <label>上传依据<AppInput v-model.trim="reason" maxlength="200" placeholder="填写原件来源与核对依据" /></label>
        <AppButton type="button" :disabled="busy || loading || connectionLost || !reason.trim()" @click="upload">选择文件并上传</AppButton>
      </div>
      <p v-if="message" role="status">{{ message }}</p>
      <p v-if="error" role="alert">{{ error }}</p>
      <WorkspaceTable :columns="columns" :data="rows" :min-table-width="1050" title="合同版本附件">
        <template #cell-byte_count="{ row }">{{ (row.byte_count / 1024).toFixed(1) }} KiB</template>
        <template #cell-sha256="{ row }"><code :title="row.sha256">{{ row.sha256.slice(0, 16) }}…</code></template>
        <template #cell-created_at="{ row }">{{ localTime(row.created_at) }} · {{ row.created_by_name }}<br />{{ row.reason }}</template>
        <template #cell-status="{ row }">
          <span v-if="row.reversal">已撤销 · {{ localTime(row.reversal.created_at) }}<br />{{ row.reversal.created_by_name }}：{{ row.reversal.reason }}</span>
          <span v-else>有效</span>
        </template>
        <template #cell-actions="{ row }"><div class="contract-attachment-toolbar">
          <AppButton type="button" :disabled="busy || connectionLost" @click="download(row)">保存</AppButton>
          <AppButton v-if="!row.reversal && canModify && store.can('sales_order.confirm')" type="button"
            :disabled="busy || connectionLost" @click="reverseId = row.id; reverseReason = ''">撤销</AppButton>
        </div></template>
        <template #empty>{{ loading ? '正在读取附件…' : '暂无附件。' }}</template>
      </WorkspaceTable>
      <form v-if="reverseId !== null" class="contract-attachment-toolbar" @submit.prevent="reverse">
        <label>撤销原因<AppInput v-model.trim="reverseReason" maxlength="200" required /></label>
        <AppButton type="submit" :disabled="busy || connectionLost || !reverseReason.trim()">确认撤销</AppButton>
        <AppButton type="button" :disabled="busy" @click="reverseId = null">返回</AppButton>
      </form>
    </template>
  </section>
</template>

<style scoped>
.contract-attachments { display: grid; gap: 10px; margin-top: 12px; }
.contract-attachment-toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
</style>
