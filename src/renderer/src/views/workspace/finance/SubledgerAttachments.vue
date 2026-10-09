<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import WorkspaceTable from '../../../components/workspace/WorkspaceTable.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { displayError, localTime } from '../../../utils/formatters'
import { auxiliaryText } from './auxiliary-display'
import { subledgerKindLabels } from './subledger-display'
import type { SubledgerAttachment, SubledgerAttachmentList } from '../../../../../shared/erp-api'

const props = defineProps<{openingId: number; openingVersion: number}>()
const store = usePiniaAppStore(), {user,server,connectionLost,busy:storeBusy} = storeToRefs(store)
const {can,loadSubledgerAttachments,uploadSubledgerAttachment,reverseSubledgerAttachment,saveSubledgerAttachment} = store
const data = ref<SubledgerAttachmentList | null>(null), loading = ref(false), busy = ref(false)
const error = ref(''), message = ref(''), reason = ref(''), lineId = ref<number | null>(null)
const correction = ref<SubledgerAttachment | null>(null), correctionReason = ref('')
const inspected = ref<SubledgerAttachment | null>(null)
let generation = 0, readTicket = 0, mounted = true
const owner = () => `${server.value?.id}:${server.value?.fingerprint}:${user.value?.id}:${user.value?.roles?.join('|')}:${user.value?.permissions.join('|')}:${props.openingId}:${props.openingVersion}`
const disabled = computed(() => loading.value || busy.value || storeBusy.value || connectionLost.value)
const canModify = computed(() => data.value?.can_modify && can('subledger_opening.attachment'))
const options = computed(() => (data.value?.lines ?? []).map(row => ({value:row.id,
  label:`${subledgerKindLabels[row.kind]} · ${row.party_name} · ${row.document_reference} · ${row.account_code}`})))
const selected = computed(() => data.value?.lines.find(row => row.id === lineId.value))
const columns = [{key:'source',title:'上传时的原单',width:'350'}, {key:'file_name',title:'原文件',width:'180'},
  {key:'created_at',title:'上传记录',width:'230'}, {key:'status',title:'状态与更正',width:'250'}, {key:'actions',title:'操作',width:'180'}]
function current(captured: number): boolean { return mounted && captured === generation && !connectionLost.value && can('subledger_opening.view') }
function clear(): void {
  generation++; readTicket++; data.value = null; inspected.value = null; correction.value = null
  correctionReason.value = ''; error.value = ''; message.value = ''; loading.value = false; busy.value = false
}
watch(owner, () => {clear(); reason.value = ''; lineId.value = null; void reload()}, {flush:'sync'})
watch(connectionLost, () => {clear(); if (!connectionLost.value) void reload()}, {flush:'sync'})
onMounted(() => {void reload()})
onUnmounted(() => {mounted = false; clear()})
async function reload(page = 1): Promise<void> {
  if (connectionLost.value || !can('subledger_opening.view')) return
  const captured = generation, ticket = ++readTicket
  loading.value = true; error.value = ''; data.value = null; inspected.value = null; correction.value = null
  try {
    const result = await loadSubledgerAttachments(props.openingId,page)
    if (!current(captured) || ticket !== readTicket) return
    data.value = result
    if (!result.lines.some(row => row.id === lineId.value)) lineId.value = null
  } catch (cause) { if (current(captured) && ticket === readTicket) error.value = displayError(cause) }
  finally { if (captured === generation && ticket === readTicket) loading.value = false }
}
async function write(kind: 'upload' | 'reverse' | 'download', row?: SubledgerAttachment): Promise<void> {
  if (disabled.value || !data.value || !can('subledger_opening.view')) return
  if (kind !== 'download' && (!canModify.value || kind === 'reverse' && !row?.can_reverse)) return
  if (kind === 'upload' && (!selected.value || !reason.value.trim())) return
  if (kind === 'reverse' && !correctionReason.value.trim()) return
  const captured = generation, id = props.openingId, version = data.value.opening_version, page = data.value.page
  busy.value = true; error.value = ''; message.value = ''
  try {
    const result = kind === 'upload' ? await uploadSubledgerAttachment(id,version,lineId.value!,reason.value.trim())
      : kind === 'reverse' ? await reverseSubledgerAttachment(id,version,row!.id,correctionReason.value.trim())
      : await saveSubledgerAttachment(id,row!.id)
    // 弹窗或请求迟到后不得恢复另一方案、账号或已撤权会话的内容与反馈。
    if (!current(captured)) return
    if (result) {
      message.value = kind === 'download' ? '原文件已保存。' : kind === 'upload' ? '附件已留存，上传时的原单来源已固定。' : '已追加撤销记录，原件仍可下载核对。'
      if (kind === 'upload') reason.value = ''
      correction.value = null; correctionReason.value = ''
      if (kind !== 'download') await reload(page)
    }
  } catch (cause) {
    if (current(captured)) {
      // 冲突后先刷新服务端来源与权限，保留输入供重新核对。
      await reload(page)
      if (current(captured)) error.value = displayError(cause)
    }
  } finally { if (captured === generation) busy.value = false }
}
</script>

<template>
  <section class="stack subledger-attachments" aria-label="历史原单票据附件">
    <div class="ledger-actions"><h3>历史原单票据附件</h3>
      <AppButton variant="secondary" type="button" :disabled="disabled" @click="reload(data?.page ?? 1)">刷新附件</AppButton>
    </div>
    <p class="muted">支持 PDF、PNG、JPEG，单文件不超过 5 MiB，每张原单最多 10 个有效附件。原件及上传时的科目、金额、完整辅助永久留存；更正只追加撤销记录。</p>
    <p v-if="connectionLost" role="status">连接已断开，附件操作暂停；恢复连接后自动重新读取。</p>
    <p v-if="data?.changed_count" role="alert">{{ data.changed_count }} 个有效附件的原单已修改或移除。请核对原来源，追加撤销并重新上传正确票据后再送审。</p>
    <form v-if="canModify" class="ledger-editor" @submit.prevent="write('upload')">
      <label>选择已保存的原单<WorkspaceSelect v-model="lineId" :options="options" required :disabled="disabled" aria-label="附件所属原单" /></label>
      <p v-if="selected" class="muted">{{ selected.document_date }} · {{ selected.account_code }} {{ selected.account_name }} · 借 {{ selected.debit }} / 贷 {{ selected.credit }} 元；{{ auxiliaryText(selected.auxiliary) }}</p>
      <label>上传依据<AppInput v-model.trim="reason" maxlength="200" required :disabled="disabled" placeholder="票据来源或补录原因" /></label>
      <div class="ledger-actions"><AppButton variant="secondary" type="submit" :disabled="disabled || !selected || !reason.trim()">选择文件并上传</AppButton></div>
    </form>
    <p v-else-if="data && can('subledger_opening.attachment')" class="muted">审批期间、方案已撤销或日期已锁定时，附件仅供查看。</p>
    <p v-if="data?.opening_status === 'confirmed'" class="muted">方案已确认：补录仅追加当前日期的证据；原批准附件不可撤销，旧批准正文与期间归档保持固定。</p>
    <p v-if="message" role="status">{{ message }}</p><p v-if="error" role="alert">{{ error }}</p>
    <WorkspaceTable :columns="columns" :data="data?.items ?? []" :min-table-width="1190" title="原单附件留存记录">
      <template #cell-source="{row}">{{ row.source.document_reference }} · {{ row.source.party_name }}<br />{{ row.source.document_date }} · {{ row.source.account_code }} {{ row.source.account_name }}<br />借 {{ row.source.debit }} / 贷 {{ row.source.credit }} 元</template>
      <template #cell-file_name="{row}">{{ row.file_name }}<br />{{ (row.byte_count / 1024).toFixed(1) }} KiB</template>
      <template #cell-created_at="{row}">{{ localTime(row.created_at) }} · {{ row.created_by_name }}<br />{{ row.reason }}</template>
      <template #cell-status="{row}">
        <span v-if="row.reversal">已撤销 · {{ localTime(row.reversal.created_at) }}<br />{{ row.reversal.created_by_name }}：{{ row.reversal.reason }}</span>
        <span v-else>{{ row.approved_original ? '原批准附件' : '有效' }}<br />{{ {matched:'来源一致',changed:'原单来源已变化',missing:'原单已移除'}[row.source_status] }}</span>
      </template>
      <template #cell-actions="{row}"><div class="ledger-actions">
        <AppButton variant="text" type="button" :disabled="disabled" @click="write('download',row)">保存原件</AppButton>
        <AppButton variant="text" type="button" :disabled="disabled" @click="inspected = row">来源与摘要</AppButton>
        <AppButton v-if="row.can_reverse && canModify" variant="text" type="button" :disabled="disabled" @click="correction = row; correctionReason = ''">撤销附件</AppButton>
      </div></template>
      <template #empty>{{ loading ? '正在读取附件…' : error ? '附件读取失败，请刷新重试。' : connectionLost ? '连接已断开。' : '暂无原单附件。选择已保存的原单后可上传票据。' }}</template>
    </WorkspaceTable>
    <div v-if="data && data.total" class="ledger-actions" aria-label="附件分页">
      <span>第 {{ data.page }} 页 · 共 {{ data.total }} 条 / {{ data.active_count }} 个有效附件</span>
      <AppButton variant="secondary" type="button" :disabled="disabled || data.page <= 1" @click="reload(data.page - 1)">上一页</AppButton>
      <AppButton variant="secondary" type="button" :disabled="disabled || data.page * data.page_size >= data.total" @click="reload(data.page + 1)">下一页</AppButton>
    </div>
    <section v-if="inspected" class="stack" aria-label="附件固定来源">
      <div class="ledger-actions"><strong>{{ inspected.file_name }} · 上传时的原单来源</strong><AppButton type="button" variant="text" @click="inspected = null">收起来源</AppButton></div>
      <p>{{ subledgerKindLabels[inspected.source.kind] }} · {{ inspected.source.party_name }} · {{ inspected.source.document_reference }} · {{ inspected.source.document_date }}；{{ inspected.source.account_code }} {{ inspected.source.account_name }}；借 {{ inspected.source.debit }} / 贷 {{ inspected.source.credit }} 元。</p>
      <p>{{ auxiliaryText(inspected.source.auxiliary) }}；期初生效日 {{ inspected.source.effective_date }}；币种 {{ inspected.source.currency }}；上传时方案版本 v{{ inspected.source.opening_version }}。</p>
      <p class="attachment-digest">SHA-256：<code>{{ inspected.sha256 }}</code></p>
    </section>
    <form v-if="correction" class="ledger-editor" @submit.prevent="write('reverse',correction)">
      <p>撤销 {{ correction.file_name }} · 原单 {{ correction.source.document_reference }}。原件与更正依据仍会保留。</p>
      <label>撤销原因<AppInput v-model.trim="correctionReason" maxlength="200" required :disabled="disabled" /></label>
      <div class="ledger-actions"><AppButton type="submit" variant="secondary" :disabled="disabled || !correctionReason.trim()">确认撤销附件</AppButton>
        <AppButton type="button" variant="text" :disabled="busy" @click="correction = null">返回</AppButton></div>
    </form>
  </section>
</template>

<style scoped>
.subledger-attachments { min-width: 0; margin-top: 24px; }
.subledger-attachments h3 { margin: 0; }
.subledger-attachments .ledger-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
.subledger-attachments p.muted { color: var(--workspace-field-text); }
.attachment-digest { overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
</style>
