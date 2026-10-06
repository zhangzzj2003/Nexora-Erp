<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { NDrawer, NDrawerContent } from 'naive-ui'
import IconCloseLine from '~icons/ri/close-line'
import IconSunLine from '~icons/ri/sun-line'
import IconMoonLine from '~icons/ri/moon-line'
import IconCheckLine from '~icons/ri/check-line'
import AppButton from './AppButton.vue'
import { useSettingsStore } from '../../store/settings-store'
import { useThemeStore } from '../../store/theme-store'
import { themeColorPresets } from '../../utils/theme-color'
import { titleBarHeight } from '../../../../shared/window-chrome'

const settings = useSettingsStore()
const theme = useThemeStore()
const { settingsOpen, locale } = storeToRefs(settings)
const { themeMode, themeColor } = storeToRefs(theme)
const { t, closeSettings, setLocale } = settings
const { selectTheme, setThemeColor } = theme
// Windows 原生窗口按钮始终位于网页之上，整个设置面板须从标题栏下方展开。
const drawerStyle = typeof window !== 'undefined' && window.nexora?.platform === 'win32'
  ? { top: `${titleBarHeight}px` } : undefined
// Naive UI 负责焦点圈定、Esc、遮罩和关闭后恢复焦点；不重建底层业务页面。
</script>

<template>
  <NDrawer id="app-settings-panel" :aria-label="t('设置')" :style="drawerStyle" v-model:show="settingsOpen" placement="right" width="min(400px, 100vw)"
    :auto-focus="true" :trap-focus="true" :close-on-esc="true" :mask-closable="true">
    <NDrawerContent :native-scrollbar="false" body-content-class="app-settings-body">
      <template #header>
        <div class="app-settings-heading">
          <div><h2>{{ t('设置') }}</h2><p>{{ t('让工作台更适合你的习惯') }}</p></div>
          <AppButton type="button" size="small" quaternary circle :aria-label="t('关闭设置')" :title="t('关闭设置')" @click="closeSettings">
            <template #icon><IconCloseLine aria-hidden="true" /></template>
          </AppButton>
        </div>
      </template>
      <section class="settings-section" aria-labelledby="settings-theme-title">
        <h3 id="settings-theme-title">{{ t('外观') }}</h3>
        <p>{{ t('选择你喜欢的主题') }}</p>
        <div class="settings-options">
          <AppButton class="settings-choice" :class="{ selected: themeMode === 'light' }" :aria-pressed="themeMode === 'light'" @click="selectTheme('light', $event)">
            <span class="theme-preview theme-preview--light" aria-hidden="true"><span /><i /><b /></span>
            <span class="settings-choice-label"><IconSunLine aria-hidden="true" />{{ t('浅色') }}<IconCheckLine v-if="themeMode === 'light'" class="settings-check" aria-hidden="true" /></span>
          </AppButton>
          <AppButton class="settings-choice" :class="{ selected: themeMode === 'dark' }" :aria-pressed="themeMode === 'dark'" @click="selectTheme('dark', $event)">
            <span class="theme-preview theme-preview--dark" aria-hidden="true"><span /><i /><b /></span>
            <span class="settings-choice-label"><IconMoonLine aria-hidden="true" />{{ t('深色') }}<IconCheckLine v-if="themeMode === 'dark'" class="settings-check" aria-hidden="true" /></span>
          </AppButton>
        </div>
      </section>
      <!-- 每个预设同时提供文字和选中标记，不依赖用户辨认颜色。 -->
      <section class="settings-section" aria-labelledby="settings-color-title">
        <h3 id="settings-color-title">{{ t('主题色') }}</h3>
        <p>{{ t('为按钮和导航选择强调色') }}</p>
        <div class="settings-colors">
          <AppButton v-for="preset in themeColorPresets" :key="preset.key" class="color-choice"
            :class="{ selected: themeColor === preset.key }" :aria-pressed="themeColor === preset.key"
            @click="setThemeColor(preset.key)">
            <span class="color-swatch" :style="{ backgroundColor: preset.primary }" aria-hidden="true">
              <IconCheckLine v-if="themeColor === preset.key" />
            </span>
            {{ t(preset.label) }}
          </AppButton>
        </div>
      </section>
      <section class="settings-section" aria-labelledby="settings-language-title">
        <h3 id="settings-language-title">{{ t('语言') }}</h3>
        <p>{{ t('选择界面显示语言') }}</p>
        <div class="settings-options">
          <AppButton class="language-choice" :class="{ selected: locale === 'zh-CN' }" :aria-pressed="locale === 'zh-CN'" lang="zh-CN" @click="setLocale('zh-CN')">简体中文<IconCheckLine v-if="locale === 'zh-CN'" aria-hidden="true" /></AppButton>
          <AppButton class="language-choice" :class="{ selected: locale === 'en-US' }" :aria-pressed="locale === 'en-US'" lang="en-US" @click="setLocale('en-US')">English<IconCheckLine v-if="locale === 'en-US'" aria-hidden="true" /></AppButton>
        </div>
        <p class="settings-language-note">{{ t('语言应用于设置、登录、引导和公共导航，业务表单暂保留中文。') }}</p>
      </section>
      <template #footer><p class="settings-saved"><IconCheckLine aria-hidden="true" />{{ t('更改即时生效，并自动保存在本机') }}</p></template>
    </NDrawerContent>
  </NDrawer>
</template>

<style scoped>
/* 抽屉使用根主题变量，窄窗口按可用宽度显示，不挤压登录表单。 */
.app-settings-heading { display: flex; justify-content: space-between; align-items: center; gap: 16px; width: 100%; }
.app-settings-heading h2 { margin: 0; font-size: 20px; color: var(--workspace-field-text); }
.app-settings-heading p, .settings-section p { margin: 6px 0 0; font-size: 12px; line-height: 1.7; color: var(--workspace-field-muted); }
.settings-section { padding: 4px 0 28px; }
.settings-section + .settings-section { padding-top: 24px; border-top: 1px solid var(--workspace-field-border); }
.settings-section h3 { margin: 0; font-size: 14px; color: var(--workspace-field-text); }
.settings-options { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 16px; }
.settings-choice { height: auto; padding: 10px; }
.settings-choice :deep(.n-button__content) { display: flex; flex-direction: column; width: 100%; gap: 12px; }
.settings-choice.selected, .language-choice.selected, .color-choice.selected { box-shadow: inset 0 0 0 1px var(--workspace-field-accent); }
.theme-preview { width: 100%; height: 74px; border-radius: 5px; border: 1px solid #dfe6ed; position: relative; overflow: hidden; background: #f3f5f9; }
.theme-preview span { position: absolute; inset: 0 auto 0 0; width: 22%; background: #fff; border-right: 1px solid #dfe6ed; }
.theme-preview i { position: absolute; left: 29%; top: 14px; width: 39%; height: 5px; border-radius: 2px; background: var(--app-accent-light-preview); }
.theme-preview b { position: absolute; left: 29%; right: 10%; top: 28px; bottom: 12px; border-radius: 4px; background: #fff; }
.theme-preview--dark { background: #0e1727; border-color: #33445f; }
.theme-preview--dark span, .theme-preview--dark b { background: #1b2a40; border-color: #33445f; }
.theme-preview--dark i { background: var(--app-accent-dark-preview); }
.settings-choice-label { display: flex; align-items: center; gap: 7px; width: 100%; font-size: 13px; }
.settings-choice-label svg, .language-choice svg, .settings-saved svg { width: 16px; height: 16px; flex: none; }
.settings-check { margin-left: auto; color: var(--workspace-field-accent); }
/* 三列色卡保持紧凑；文字和色块都能通过键盘所在按钮选择。 */
.settings-colors { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-top: 16px; }
.color-choice { min-width: 0; height: 78px; padding: 10px 4px; }
.color-choice :deep(.n-button__content) { flex-direction: column; gap: 8px; font-size: 12px; }
.color-swatch { width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center; color: #fff; }
.color-swatch svg { width: 17px; height: 17px; }
.language-choice { min-width: 0; }
.language-choice :deep(.n-button__content) { gap: 8px; }
.settings-section .settings-language-note { margin-top: 14px; }
.settings-saved { display: flex; align-items: center; gap: 8px; margin: 0; font-size: 12px; line-height: 1.7; color: var(--workspace-field-muted); }
.settings-saved svg { color: var(--workspace-field-accent); }
@media (prefers-reduced-motion: reduce) {
  /* 系统减少动态效果时抽屉直接显隐，与现有主题降级行为一致。 */
  :global(.n-drawer), :global(.n-drawer-mask) { transition-duration: .01ms !important; }
}
</style>
