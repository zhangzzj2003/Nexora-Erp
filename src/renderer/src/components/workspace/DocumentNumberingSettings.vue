<script setup lang="ts">
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { storeToRefs } from 'pinia'
import { NAlert, NRadioButton, NRadioGroup } from 'naive-ui'
import AppButton from '../app/AppButton.vue'
import WorkspaceSelect from './WorkspaceSelect.vue'
import { usePiniaAppStore } from '../../store/app-store'
import { useSettingsStore } from '../../store/settings-store'
import { numberingDate } from '../../utils/document-numbering-preview'
import type { DocumentNumberingInput } from '../../../../shared/document-numbering'

const props = defineProps<{ initial?: boolean }>()
const store = usePiniaAppStore()
const { documentNumbering: config, busy, connectionLost, user } = storeToRefs(store)
const settings = useSettingsStore()
const { t } = settings
// 草稿留在组件内；保存失败和语言切换不能清空已经选择的实例规则。
const draft = ref<DocumentNumberingInput>({ style: settings.isEnglish ? 'english' : 'pinyin',
  timezone_mode: 'server', timezone: null, version: config.value?.version ?? 0 })
let initialized = false
watch(config, value => {
  if (!value) return
  draft.value.version = value.version
  if (value.configured && value.style && (!initialized || value.locked)) {
    draft.value = { style: value.style, timezone_mode: value.timezone_mode, timezone: value.timezone, version: value.version }
  }
  initialized = true
}, { immediate: true })
// 定期读取服务端当前时间和锁定状态，等待设置时跨午夜也能更新日期预览。
let refreshTimer: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  const refresh = () => { if (!busy.value) void store.loadDocumentNumbering().catch(() => {}) }
  refresh()
  refreshTimer = setInterval(refresh, 30000)
})
onUnmounted(() => clearInterval(refreshTimer))
const editable = computed(() => user.value?.roles.includes('admin') && !config.value?.locked)
const disabled = computed(() => busy.value || connectionLost.value || !editable.value)
const date = computed(() => config.value ? numberingDate(config.value, draft.value) : '')
const timezoneOptions = computed(() => config.value?.timezones.map(value => ({ value, label: value })) ?? [])
const zoneModes = computed(() => [
  { value: 'server' as const, label: t('跟随服务端本机时区') },
  { value: 'utc' as const, label: 'UTC' },
  { value: 'specified' as const, label: t('指定时区') }
])
function changeMode(): void {
  draft.value.timezone = draft.value.timezone_mode === 'specified' ? 'Asia/Shanghai' : null
}
async function submit(): Promise<void> {
  if (disabled.value || !date.value) return
  await store.saveDocumentNumbering({ ...draft.value })
}
</script>

<template>
  <section class="card numbering-settings">
    <h2>{{ t(initial ? '设置单据编号规则' : '单据编号规则') }}</h2>
    <p class="muted">{{ t('规则由服务端保存，所有客户端共用；新增单据时由服务端自动生成完整单号。') }}</p>
    <NAlert v-if="config?.locked" type="info" :show-icon="false">{{ t('已生成单号，编号风格和时区规则已锁定。') }}</NAlert>
    <NAlert v-else-if="initial" type="info" :show-icon="false">{{ t('请先完成设置。已有单据将在保存时补号，完成前业务数据只可查看。') }}</NAlert>
    <form v-if="config" class="numbering-form" @submit.prevent="submit">
      <label>{{ t('编号风格') }}</label>
      <NRadioGroup v-model:value="draft.style" :disabled="disabled" :aria-label="t('编号风格')">
        <NRadioButton value="pinyin">{{ t('拼音首字母') }}</NRadioButton>
        <NRadioButton value="english">{{ t('英文缩写') }}</NRadioButton>
      </NRadioGroup>
      <div class="numbering-examples">
        <span>{{ t('拼音示例') }} <strong>QTRK-{{ date || 'YYYYMMDD' }}-000001</strong></span>
        <span>{{ t('英文示例') }} <strong>OIN-{{ date || 'YYYYMMDD' }}-000001</strong></span>
      </div>
      <label>{{ t('编号日期时区') }}<WorkspaceSelect v-model="draft.timezone_mode" :options="zoneModes"
        :disabled="disabled" @change="changeMode" /></label>
      <label v-if="draft.timezone_mode === 'specified'">{{ t('指定时区') }}<WorkspaceSelect v-model="draft.timezone"
        :options="timezoneOptions" :disabled="disabled" required :aria-label="t('指定时区')" /></label>
      <dl class="numbering-time">
        <div><dt>{{ t('服务端当前时间') }}</dt><dd>{{ config.server_time }}</dd></div>
        <div><dt>{{ t('编号日期预览') }}</dt><dd>{{ date || t('请选择有效时区') }}</dd></div>
      </dl>
      <p v-if="draft.timezone_mode === 'server'" class="muted">{{ t('本机模式跟随服务端系统时区，客户端时区不影响编号。') }}</p>
      <p class="muted">{{ t('生成第一张单号或完成历史补号后锁定规则；原参考号和供应商批号保持不变。') }}</p>
      <p v-if="config.backfilled_count">{{ t('历史补号：{count} 张；日期缺失：{undated} 张。', { count: config.backfilled_count, undated: config.undated_count }) }}</p>
      <div class="numbering-actions">
        <AppButton v-if="editable" type="submit" :disabled="disabled || !date">{{ t(busy ? '正在保存…' : '保存编号规则') }}</AppButton>
        <AppButton v-if="initial" type="button" variant="secondary" :disabled="busy" @click="store.switchServer">{{ t('切换服务端') }}</AppButton>
      </div>
    </form>
    <p v-else role="status">{{ t('正在读取编号规则…') }}</p>
  </section>
</template>

<style scoped>
/* 两种风格和时间预览保持可读，窄窗口不让完整单号挤出表单。 */
.numbering-settings { max-width: 920px; }
.numbering-form { display: grid; gap: 16px; margin-top: 20px; }
.numbering-form > label { display: grid; gap: 8px; }
.numbering-form :deep(.n-radio-group) { display: flex; flex-wrap: wrap; }
.numbering-form :deep(.n-radio-button) { display: inline-flex; gap: 0; margin: 0; }
.numbering-examples { display: flex; flex-wrap: wrap; gap: 14px 28px; font-size: 13px; }
.numbering-examples strong { display: block; margin-top: 6px; overflow-wrap: anywhere; }
.numbering-time { display: grid; gap: 12px; }
.numbering-time div { display: grid; grid-template-columns: 160px 1fr; gap: 12px; }
.numbering-time dt { color: var(--workspace-field-muted); }
.numbering-time dd { margin: 0; overflow-wrap: anywhere; }
.numbering-actions { display: flex; flex-wrap: wrap; gap: 12px; }
@media (max-width: 600px) { .numbering-time div { grid-template-columns: 1fr; gap: 4px; } }
</style>
