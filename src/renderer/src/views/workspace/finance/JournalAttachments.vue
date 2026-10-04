<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { displayError, localTime } from '../../../utils/formatters'
import type { JournalAttachment } from '../../../../../shared/erp-api'

const props = defineProps<{ journalId: number }>()
const store = usePiniaAppStore()
const { user, connectionLost } = storeToRefs(store)
const { can, loadJournalAttachments, uploadJournalAttachment, reverseJournalAttachment,
  saveJournalAttachment } = store
const rows = ref<JournalAttachment[]>([])
const canModify = ref(false)
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const message = ref('')
const reason = ref('')
const reverseId = ref<number | null>(null)
const reverseReason = ref('')
let ticket = 0
const owner = (): string => `${user.value?.id}:${user.value?.permissions.join('|')}`
const columns = [
  { key: 'file_name', title: '文件' },
  { key: 'byte_count', title: '大小', width: '95' },
  { key: 'sha256', title: 'SHA-256', width: '170' },
  { key: 'created_at', title: '上传与依据', width: '250' },
  { key: 'status', title: '状态', width: '220' },
  { key: 'actions', title: '操作', width: '155' }
]

async function reload(): Promise<void> {
  if (!can('journal.view') || connectionLost.value) return
  const current = ++ticket
  loading.value = true
  error.value = ''
  try {
    const result = await loadJournalAttachments(props.journalId)
    if (current !== ticket) return
    rows.value = result.items
    canModify.value = result.can_modify
  } catch (cause) {
    if (current === ticket) error.value = displayError(cause)
  } finally {
    if (current === ticket) loading.value = false
  }
}

watch(owner, () => {
  ticket++
  rows.value = []
  canModify.value = false
  loading.value = false
  error.value = ''
  message.value = ''
  reason.value = ''
  reverseId.value = null
}, { flush: 'sync' })
watch(connectionLost, (lost) => {
  ticket++
  if (lost) loading.value = false
  if (!lost) void reload()
}, { flush: 'sync' })
onMounted(reload)
onUnmounted(() => { ticket++ })

async function upload(): Promise<void> {
  if (busy.value || connectionLost.value || !canModify.value || !can('journal.attachment') || !reason.value.trim()) return
  busy.value = true
  error.value = ''
  message.value = ''
  try {
    const result = await uploadJournalAttachment(props.journalId, reason.value.trim())
    if (result) {
      reason.value = ''
      message.value = `已保存附件 ${result.file_name}。`
      await reload()
    }
  } catch (cause) {
    error.value = displayError(cause)
  } finally {
    busy.value = false
  }
}

async function download(item: JournalAttachment): Promise<void> {
  if (busy.value || connectionLost.value || !can('journal.view')) return
  busy.value = true
  error.value = ''
  message.value = ''
  try {
    const saved = await saveJournalAttachment(props.journalId, item.id)
    if (saved) message.value = `已保存附件 ${item.file_name}。`
  } catch (cause) {
    error.value = displayError(cause)
  } finally {
    busy.value = false
  }
}

async function reverse(): Promise<void> {
  if (reverseId.value === null || busy.value || connectionLost.value || !canModify.value
    || !can('journal.attachment') || !reverseReason.value.trim()) return
  busy.value = true
  error.value = ''
  message.value = ''
  try {
    await reverseJournalAttachment(props.journalId, reverseId.value, reverseReason.value.trim())
    reverseId.value = null
    reverseReason.value = ''
    message.value = '附件已撤销，原文件与撤销记录仍可核对。'
    await reload()
  } catch (cause) {
    error.value = displayError(cause)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="stack journal-attachments">
    <div class="ledger-actions">
      <strong>凭证附件</strong>
      <AppButton variant="secondary" type="button" :disabled="loading || busy || connectionLost" @click="reload">刷新附件</AppButton>
    </div>
    <p class="muted">支持 PDF、PNG、JPEG，单文件不超过 5 MiB，最多 10 个有效附件。撤销只追加记录；已取消凭证或已结账期间不能改动附件。</p>
    <div v-if="can('journal.attachment') && canModify" class="ledger-actions">
      <label>上传依据<AppInput v-model.trim="reason" maxlength="200" placeholder="填写票据来源或补录原因" /></label>
      <AppButton variant="secondary" type="button" :disabled="busy || loading || connectionLost || !reason.trim()" @click="upload">选择文件并上传</AppButton>
    </div>
    <p v-else-if="can('journal.attachment') && !loading" class="muted">此凭证当前不允许新增或撤销附件。</p>
    <p v-if="message" role="status">{{ message }}</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <WorkspaceTable :columns="columns" :data="rows" :min-table-width="1050" title="附件留存记录">
      <template #cell-byte_count="{ row }">{{ (row.byte_count / 1024).toFixed(1) }} KiB</template>
      <template #cell-sha256="{ row }"><code :title="row.sha256">{{ row.sha256.slice(0, 16) }}…</code></template>
      <template #cell-created_at="{ row }">{{ localTime(row.created_at) }} · {{ row.created_by_name }}<br />{{ row.reason }}</template>
      <template #cell-status="{ row }">
        <span v-if="row.reversal">已撤销 · {{ localTime(row.reversal.created_at) }}<br />{{ row.reversal.created_by_name }}：{{ row.reversal.reason }}</span>
        <span v-else>有效</span>
      </template>
      <template #cell-actions="{ row }">
        <div class="ledger-actions">
          <AppButton variant="text" type="button" :disabled="busy || connectionLost" @click="download(row)">保存</AppButton>
          <AppButton v-if="!row.reversal && canModify && can('journal.attachment')" variant="text" type="button"
            :disabled="busy || connectionLost" @click="reverseId = row.id; reverseReason = ''">撤销</AppButton>
        </div>
      </template>
      <template #empty>{{ loading ? '正在读取附件…' : '暂无附件。' }}</template>
    </WorkspaceTable>
    <form v-if="reverseId !== null" class="ledger-actions" @submit.prevent="reverse">
      <label>撤销原因<AppInput v-model.trim="reverseReason" required maxlength="200" /></label>
      <AppButton variant="secondary" type="submit" :disabled="busy || connectionLost || !reverseReason.trim()">确认撤销</AppButton>
      <AppButton variant="text" type="button" :disabled="busy" @click="reverseId = null">返回</AppButton>
    </form>
  </div>
</template>
