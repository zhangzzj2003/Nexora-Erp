<script setup lang="ts">
import { ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { NCheckbox, NModal, NUpload } from 'naive-ui'
import type { ContactImportPreview, ContactImportRow } from '../../../../../shared/crm-api'
import AppButton from '../../../components/app/AppButton.vue'
import AppInput from '../../../components/app/AppInput.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import { parseContactCsvBytes } from './contact-import'

const show = defineModel<boolean>('show', { required: true })
const store = usePiniaAppStore()
const { busy, connectionLost, user, error } = storeToRefs(store)
const rows = ref<ContactImportRow[]>([])
const preview = ref<ContactImportPreview | null>(null)
const reason = ref('')
const allowSimilar = ref(false)
const message = ref('')
const checking = ref(false)
let revision = 0

function clear(): void {
  revision++
  checking.value = false
  rows.value = []
  preview.value = null
  reason.value = ''
  allowSimilar.value = false
  message.value = ''
}
watch(show, open => { if (!open) clear() })
watch(() => `${user.value?.id}:${user.value?.permissions.join('|')}`, () => { show.value = false; clear() })
watch(connectionLost, lost => { if (lost) { show.value = false; clear() } })

async function selectFile(data: { file: { file?: File | null } }): Promise<void> {
  const file = data.file.file
  clear()
  if (!file) return
  const ticket = revision
  if (file.size > 256 * 1024) { message.value = 'CSV 文件不能超过 256 KiB。'; return }
  checking.value = true
  try {
    const parsed = parseContactCsvBytes(await file.arrayBuffer())
    if (!window.nexora) throw new Error('无法连接服务端')
    const checked = await window.nexora.callApi('contactImportPreview', { rows: parsed })
    if (ticket !== revision || !show.value) return
    rows.value = parsed
    preview.value = checked
  } catch (cause) {
    if (ticket === revision) message.value = store.displayError(cause)
  } finally {
    if (ticket === revision) checking.value = false
  }
}

async function submit(): Promise<void> {
  if (busy.value || checking.value || connectionLost.value || !store.can('crm_contact.manage')
    || !preview.value || !reason.value.trim()
    || (preview.value.requires_confirmation && !allowSimilar.value)) return
  message.value = ''
  const actor = user.value?.id
  const saved = await store.importContactRows([...rows.value], reason.value.trim(), allowSimilar.value)
  if (actor !== user.value?.id) return
  if (saved) show.value = false
  else message.value = error.value || '导入失败，请核对资料后重试。'
}
</script>

<template>
  <NModal v-model:show="show" preset="card" title="导入联系人 CSV"
    :mask-closable="!checking && !busy" :closable="!checking && !busy"
    :style="{width:'min(760px,calc(100vw - 32px))',maxHeight:'calc(100vh - 48px)',overflowY:'auto'}">
    <div class="stack">
      <p>使用 UTF-8 CSV，每次 1 至 100 位。首列为“客户编号,联系人姓名”或“customer_id,name”；可依次追加职务、电话、邮箱、备注四列。客户编号可在“客户资料”页查看，须属于当前可维护范围。导入仅建立启用联系人，不会合并已有资料。</p>
      <NUpload accept=".csv,text/csv" :default-upload="false" :show-file-list="false" :file-list="[]"
        :disabled="checking || busy || connectionLost" @change="selectFile">
        <AppButton type="button" :disabled="checking || busy || connectionLost">选择 CSV 文件</AppButton>
      </NUpload>
      <p v-if="checking" role="status">正在核对客户和联系人…</p>
      <p v-if="message" role="alert">{{ message }}</p>
      <template v-if="preview">
        <p>已核对 {{ preview.rows.length }} 条。客户名称仅用于核对，不从 CSV 修改客户资料。</p>
        <ol style="max-height:280px;overflow:auto">
          <li v-for="row in preview.rows" :key="row.row">
            第 {{ row.row }} 条：{{ row.customer_name }} (#{{ row.customer_id }}) · {{ row.name }}
            <span v-if="rows[row.row - 1]?.job_title"> · {{ rows[row.row - 1].job_title }}</span>
            <span v-if="rows[row.row - 1]?.phone"> · {{ rows[row.row - 1].phone }}</span>
            <span v-if="rows[row.row - 1]?.email"> · {{ rows[row.row - 1].email }}</span>
            <span v-if="rows[row.row - 1]?.note"> · {{ rows[row.row - 1].note }}</span>
            <span v-if="row.existing_contact_ids.length">；同名联系人 #{{ row.existing_contact_ids.join('、#') }}</span>
            <span v-if="row.batch_rows.length">；本批次第 {{ row.batch_rows.join('、') }} 条同名</span>
          </li>
        </ol>
        <NCheckbox v-if="preview.requires_confirmation" v-model:checked="allowSimilar">
          已核对同一客户下的同名人员，确认仍需分别建立
        </NCheckbox>
        <label>导入依据<AppInput v-model.trim="reason" required maxlength="200" placeholder="例如：已核对客户提供的联系人清单" /></label>
        <AppButton type="button" variant="primary"
          :disabled="busy || connectionLost || !reason.trim() || (preview.requires_confirmation && !allowSimilar)"
          @click="submit">{{ busy ? '正在导入…' : '确认导入' }}</AppButton>
      </template>
    </div>
  </NModal>
</template>
