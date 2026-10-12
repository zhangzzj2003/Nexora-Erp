<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import WorkspaceSelect from '../../../components/workspace/WorkspaceSelect.vue'
import AppButton from '../../../components/app/AppButton.vue'
import { usePiniaAppStore } from '../../../store/app-store'
import type { ControlFundsOptions, ControlFundsQuery, FundsScopeChoice } from '../../../../../shared/control-balance-api'
import { displayError } from '../../../utils/formatters'
import { auxiliaryText } from './auxiliary-display'
import { controlGroupKey } from './control-balance-display'
import { cents } from './subledger-order-display'

const props = defineProps<{ query: ControlFundsQuery; action: 'settlement' | 'refund'; disabled?: boolean; modelValue?: FundsScopeChoice }>()
const emit = defineEmits<{ 'update:modelValue': [value: FundsScopeChoice | undefined]; ready: [value: boolean] }>()
const store = usePiniaAppStore(), { user, server, connectionLost } = storeToRefs(store)
const options = ref<ControlFundsOptions | null>(null), selected = ref(''), loading = ref(false), error = ref('')
let ticket = 0
const groups = computed(() => (options.value?.origin?.groups ?? []).filter(row => !row.blockers.length
  && (props.action === 'settlement' ? cents(row.outstanding_amount) > 0n : cents(row.outstanding_amount) < 0n)))
const group = computed(() => groups.value.find(row => controlGroupKey(row) === selected.value))
const accountLabel = (id: number) => {
  const account = options.value?.accounts?.find(row => row.id === id)
  return account ? `${account.code} · ${account.name}` : `科目 #${id}`
}
const choices = computed(() => [
  { value: '', label: options.value?.required ? '请选择真实余额组合（必选）' : '沿用原收付款流程', disabled: !!options.value?.required },
  ...groups.value.map(row => ({ value: controlGroupKey(row), label: `${accountLabel(row.account_id)} · ${auxiliaryText(row.auxiliary)} · 余额 ${row.outstanding_amount} 元` }))])
function update(): void {
  const row = group.value
  emit('update:modelValue', row ? { account_id: row.account_id, auxiliary: row.auxiliary.map(({ kind, id }) => ({ kind, id })), fingerprint: row.fingerprint } : undefined)
  emit('ready', !loading.value && !error.value && !!options.value && (!!row || !options.value.required))
}
watch(selected, update)
async function load(): Promise<void> {
  const current = ++ticket
  options.value = null; selected.value = ''; error.value = ''; loading.value = true; update()
  if (!props.query.source_id || connectionLost.value) { loading.value = false; update(); return }
  try {
    const result = await store.loadControlFundsOptions({ ...props.query })
    if (current === ticket) options.value = result
  } catch (cause) { if (current === ticket) error.value = displayError(cause) }
  finally { if (current === ticket) { loading.value = false; update() } }
}
watch(() => `${props.query.kind}:${props.query.source_type}:${props.query.source_id}:${props.action}:${server.value?.id}:${server.value?.fingerprint}:${user.value?.id}:${user.value?.roles?.join('|')}:${user.value?.permissions.join('|')}:${connectionLost.value}`, load, { immediate: true, flush: 'sync' })
onUnmounted(() => { ticket++ })
</script>

<template>
  <div class="ledger-editor">
    <p v-if="loading" role="status">正在核对最新资金组合…</p>
    <p v-if="error" role="alert">{{ error }} 请重新核对后登记资金。</p>
    <AppButton v-if="error" :disabled="disabled || loading || connectionLost" @click="load">重新核对资金组合</AppButton>
    <template v-if="options">
      <p v-if="options.required">此原单曾办理组合转账，必须选择本次资金的实际控制科目和完整辅助归属。</p>
      <label v-if="options.required || groups.length">实际资金组合<WorkspaceSelect v-model="selected" :options="choices" :disabled="disabled || loading" /></label>
      <p v-if="options.required && !groups.length" role="alert">当前没有可办理此资金动作的完整组合，请核对余额、资金执行和凭证过账。</p>
      <p v-if="options.origin?.blockers.length" role="alert">{{ options.origin.blockers.join('；') }}</p>
      <p v-if="group">所选组合余额 {{ group.outstanding_amount }} 元。批准后执行会再次核对额度，生成资金凭证沿用此组合。</p>
    </template>
  </div>
</template>
