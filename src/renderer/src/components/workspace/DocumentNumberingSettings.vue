<script setup lang="ts">
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { storeToRefs } from 'pinia'
import { NAlert, NRadioButton, NRadioGroup } from 'naive-ui'
import AppButton from '../app/AppButton.vue'
import AppStepper from '../app/AppStepper.vue'
import { useNumberingSteps } from '../../composables/use-numbering-steps'
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
async function save(): Promise<void> {
  if (disabled.value || !date.value) return
  await store.saveDocumentNumbering({ ...draft.value })
}
const steps = computed(() => [t('编号风格'), t('日期时区'), t('确认规则')])
const { step, direction, canContinue, back, submit } = useNumberingSteps(Boolean(props.initial), disabled,
  computed(() => Boolean(date.value)), save)
const stepTitles = ['选择编号风格', '设置编号日期时区', '确认编号规则'] as const
const zoneLabel = computed(() => draft.value.timezone_mode === 'specified' ? draft.value.timezone :
  zoneModes.value.find(value => value.value === draft.value.timezone_mode)?.label)
const example = computed(() => `${draft.value.style === 'pinyin' ? 'QTRK' : 'OIN'}-${date.value || 'YYYYMMDD'}-000001`)
// 保留服务端给出的偏移量，只改善 ISO 时间的阅读，不换算成客户端日期。
const serverTime = computed(() => config.value?.server_time.replace('T', ' ').replace(/\.\d+(?=[+-]|Z$)/, ''))
const panelHeading = ref<HTMLElement | null>(null)
function focusPanel(): void { if (props.initial) panelHeading.value?.focus({ preventScroll: true }) }
</script>

<template>
  <section class="card numbering-settings" :class="{ 'numbering-settings--initial': initial }">
    <header v-if="initial" class="numbering-intro">
      <p class="eyebrow">NEXORA · SETUP</p>
      <h1>{{ t('开始使用联光 ERP') }}</h1>
      <p class="muted">{{ t('设置单据编号规则') }}</p>
    </header>
    <template v-else>
      <h2>{{ t('单据编号规则') }}</h2>
      <p class="muted">{{ t('规则由服务端保存，所有客户端共用；新增单据时由服务端自动生成完整单号。') }}</p>
    </template>
    <AppStepper v-if="initial" :steps="steps" :current="step" :disabled="disabled"
      :label="t('设置进度')" @select="back" />
    <NAlert v-if="config?.locked" type="info" :show-icon="false">{{ t('已生成单号，编号风格和时区规则已锁定。') }}</NAlert>
    <form v-if="config" class="numbering-form" @submit.prevent="submit">
      <Transition :name="initial ? `numbering-${direction}` : ''" mode="out-in" @after-enter="focusPanel">
        <div :key="initial ? step : 0" class="numbering-panel">
          <h2 v-if="initial" id="numbering-step-title" ref="panelHeading" tabindex="-1">{{ t(stepTitles[step] ?? stepTitles[0]) }}</h2>
          <template v-if="!initial || step === 0">
            <label v-if="!initial">{{ t('编号风格') }}</label>
            <NRadioGroup v-model:value="draft.style" :disabled="disabled" :aria-label="t('编号风格')">
              <NRadioButton value="pinyin"><span class="numbering-style-choice"><strong>{{ t('拼音首字母') }}</strong>
                <span v-if="initial">QTRK-{{ date || 'YYYYMMDD' }}-000001</span></span></NRadioButton>
              <NRadioButton value="english"><span class="numbering-style-choice"><strong>{{ t('英文缩写') }}</strong>
                <span v-if="initial">OIN-{{ date || 'YYYYMMDD' }}-000001</span></span></NRadioButton>
            </NRadioGroup>
            <div v-if="!initial" class="numbering-examples">
              <span>{{ t('拼音示例') }} <strong>QTRK-{{ date || 'YYYYMMDD' }}-000001</strong></span>
              <span>{{ t('英文示例') }} <strong>OIN-{{ date || 'YYYYMMDD' }}-000001</strong></span>
            </div>
            <p v-if="initial" class="muted">{{ t('规则由服务端保存，所有客户端共用；新增单据时由服务端自动生成完整单号。') }}</p>
          </template>
          <template v-if="!initial || step === 1">
            <label>{{ t('编号日期时区') }}<WorkspaceSelect v-model="draft.timezone_mode" :options="zoneModes"
              :disabled="disabled" :aria-label="t('编号日期时区')" @change="changeMode" /></label>
            <label v-if="draft.timezone_mode === 'specified'">{{ t('指定时区') }}<WorkspaceSelect v-model="draft.timezone"
              :options="timezoneOptions" :disabled="disabled" required :aria-label="t('指定时区')" /></label>
            <dl class="numbering-time">
              <div><dt>{{ t('服务端当前时间') }}</dt><dd>{{ serverTime }}</dd></div>
              <div><dt>{{ t('编号日期预览') }}</dt><dd>{{ date || t('请选择有效时区') }}</dd></div>
            </dl>
            <p v-if="draft.timezone_mode === 'server'" class="muted">{{ t('本机模式跟随服务端系统时区，客户端时区不影响编号。') }}</p>
          </template>
          <template v-if="initial && step === 2">
            <dl class="numbering-time numbering-review">
              <div><dt>{{ t('编号风格') }}</dt><dd>{{ t(draft.style === 'pinyin' ? '拼音首字母' : '英文缩写') }}</dd></div>
              <div><dt>{{ t('编号日期时区') }}</dt><dd>{{ zoneLabel }}</dd></div>
              <div><dt>{{ t('编号日期预览') }}</dt><dd>{{ date }}</dd></div>
            </dl>
            <div class="numbering-preview"><span>{{ t('其他入库单号示例') }}</span><strong>{{ example }}</strong></div>
            <NAlert type="info" :show-icon="false">{{ t('请先完成设置。已有单据将在保存时补号，完成前业务数据只可查看。') }}</NAlert>
          </template>
          <p v-if="!initial || step === 2" class="muted">{{ t('生成第一张单号或完成历史补号后锁定规则；原参考号和供应商批号保持不变。') }}</p>
          <p v-if="config.backfilled_count">{{ t('历史补号：{count} 张；日期缺失：{undated} 张。', { count: config.backfilled_count, undated: config.undated_count }) }}</p>
        </div>
      </Transition>
      <div class="numbering-actions">
        <AppButton v-if="initial && step > 0" type="button" :disabled="disabled" @click="back()">{{ t('上一步') }}</AppButton>
        <AppButton v-if="editable" type="submit" variant="primary" :disabled="!canContinue" :loading="busy">
          {{ t(busy ? '正在保存…' : initial && step < 2 ? '下一步' : '保存编号规则') }}
        </AppButton>
      </div>
    </form>
    <p v-else role="status">{{ t('正在读取编号规则…') }}</p>
    <div v-if="initial" class="numbering-switch"><AppButton type="button" variant="text" :disabled="busy" @click="store.switchServer">{{ t('切换服务端') }}</AppButton></div>
  </section>
</template>

<style scoped>
/* 首次设置采用独立的居中卡片，常规系统设置仍使用同一份草稿与保存逻辑。 */
.numbering-settings { max-width: 920px; }
.numbering-settings--initial { width: min(100%, 640px); padding: clamp(22px, 3vw, 32px); border-radius: 24px; }
.numbering-intro { text-align: center; }
.numbering-intro h1 { margin: 10px 0 0; font-size: clamp(24px, 2.4vw, 30px); line-height: 1.3; letter-spacing: -.035em; }
.numbering-intro .muted { margin: 10px 0 24px; }
.numbering-form { display: grid; gap: 20px; margin-top: 20px; }
.numbering-panel { display: grid; align-content: start; gap: 16px; min-width: 0; }
.numbering-settings--initial .numbering-panel { min-height: 204px; }
.numbering-panel h2 { margin: 0; font-size: 18px; line-height: 1.4; outline: none; }
.numbering-panel p { margin: 0; }
.numbering-panel > label { display: grid; gap: 8px; }
.numbering-form :deep(.n-radio-group) { display: flex; flex-wrap: wrap; }
.numbering-form :deep(.n-radio-button) { display: inline-flex; gap: 0; margin: 0; }
.numbering-settings--initial :deep(.n-radio-group) { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; height: auto; }
/* 单选组自带的分隔节点不占网格位置，内部标签也解除默认的单行高度。 */
.numbering-settings--initial :deep(.n-radio-group__splitor) { display: none; }
/* Naive UI 的连体按钮只绘制组外侧边框；独立卡片需补齐四边，并保留选中态主题色。 */
.numbering-settings--initial :deep(.n-radio-button) { height: auto; min-height: 80px; min-width: 0; border: 1px solid var(--n-button-border-color); border-radius: 10px; }
.numbering-settings--initial :deep(.n-radio-button.n-radio-button--checked) { border-color: var(--n-button-border-color-active); }
.numbering-settings--initial :deep(.n-radio__label) { height: auto; width: 100%; padding: 12px 14px; line-height: normal; }
.numbering-settings--initial :deep(.n-radio-button__state-border) { border-radius: 10px; }
.numbering-style-choice { display: grid; gap: 10px; padding: 5px 0; min-width: 0; }
.numbering-style-choice strong { font-size: 14px; }
.numbering-style-choice > span { font: 600 11px/1.6 'SFMono-Regular', Consolas, monospace; overflow-wrap: anywhere; white-space: normal; }
.numbering-examples { display: flex; flex-wrap: wrap; gap: 14px 28px; font-size: 13px; }
.numbering-examples strong { display: block; margin-top: 6px; overflow-wrap: anywhere; }
.numbering-time { display: grid; gap: 12px; margin: 0; font-size: 13px; line-height: 1.6; }
.numbering-time div { display: grid; grid-template-columns: 136px minmax(0, 1fr); gap: 12px; }
.numbering-time dt { color: var(--workspace-field-muted); }
.numbering-time dd { margin: 0; overflow-wrap: anywhere; }
.numbering-review { gap: 8px; }
.numbering-preview { display: grid; gap: 8px; padding: 14px 16px; background: var(--app-accent-tint); border-radius: 12px; color: var(--workspace-field-accent); }
.numbering-preview > span { font-size: 12px; }
.numbering-preview > strong { font: 700 18px/1.5 'SFMono-Regular', Consolas, monospace; overflow-wrap: anywhere; }
.numbering-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 12px; }
.numbering-settings--initial .numbering-actions { padding-top: 18px; border-top: 1px solid var(--workspace-field-border); }
.numbering-switch { display: flex; justify-content: center; margin-top: 14px; }
/* 短距离左右切换提示前进或返回；减少动效偏好下直接切换内容。 */
.numbering-next-enter-active, .numbering-next-leave-active, .numbering-back-enter-active, .numbering-back-leave-active { transition: opacity .16s ease, transform .16s ease; }
.numbering-next-enter-from, .numbering-back-leave-to { opacity: 0; transform: translateX(12px); }
.numbering-next-leave-to, .numbering-back-enter-from { opacity: 0; transform: translateX(-12px); }
@media (max-width: 520px) { .numbering-time div { grid-template-columns: 1fr; gap: 2px; } .numbering-preview > strong { font-size: 15px; } }
@media (prefers-reduced-motion: reduce) { .numbering-next-enter-active, .numbering-next-leave-active, .numbering-back-enter-active, .numbering-back-leave-active { transition: none; } }
</style>
