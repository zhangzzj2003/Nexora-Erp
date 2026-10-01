<script setup lang="ts">
// 页面按钮统一复用 Naive UI 封装，显式区分表单提交与普通操作。
import AppButton from './AppButton.vue'
import { useId } from 'vue'
import { storeToRefs } from 'pinia'
import { useThemeStore } from '../../store/theme-store'

// 窄窗口的顶部账号区复用同一个图标按钮，避免侧栏收起后无法切换主题。
const theme = useThemeStore()
const { isDarkTheme } = storeToRefs(theme)
const { toggleTheme } = theme
// 顶部与侧栏同时存在按钮，SVG 遮罩必须各自唯一，避免相互引用。
const maskId = `theme-moon-${useId()}`
</script>

<template>
  <AppButton
    quaternary
    circle
    size="small"
    :aria-label="isDarkTheme ? '切换为浅色模式' : '切换为深色模式'"
    :title="isDarkTheme ? '切换为浅色模式' : '切换为深色模式'"
    @click="toggleTheme"
    class="theme-toggle"
    :class="{ 'theme-toggle--dark': isDarkTheme }"
    variant="secondary"
    type="button"
  >
    <template #icon>
      <!-- 同一个图形通过遮罩与光芒旋转变形，不再销毁重建两枚独立图标。 -->
      <svg class="theme-symbol" aria-hidden="true" viewBox="0 0 24 24">
        <mask :id="maskId"><rect width="24" height="24" fill="white" /><circle class="theme-moon-cutout" cx="40" cy="8" r="11" fill="black" /></mask>
        <circle class="theme-sun" cx="12" cy="12" r="11" :mask="`url(#${maskId})`" />
        <g class="theme-sun-rays">
          <line x1="12" y1="1" x2="12" y2="3" /><line x1="12" y1="21" x2="12" y2="23" />
          <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" /><line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
          <line x1="1" y1="12" x2="3" y2="12" /><line x1="21" y1="12" x2="23" y2="12" />
          <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" /><line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
        </g>
      </svg>
    </template>
  </AppButton>
</template>

<style scoped>
/* 参考 Vben 的太阳/月亮变形节奏（MIT，见 docs/third-party-notices.md）；保留本应用按钮尺寸和主题颜色。 */
.theme-moon-cutout { transform: translateX(-20px); transition: transform .5s cubic-bezier(0, 0, .3, 1); }
.theme-sun { fill: currentColor; transform: scale(1); transform-origin: center; transition: transform 1.6s cubic-bezier(.25, 0, .2, 1); }
.theme-sun-rays { stroke: currentColor; stroke-width: 2; opacity: 0; transform-origin: center; transition: transform 1.6s cubic-bezier(.5, 1.5, .75, 1.25), opacity .6s cubic-bezier(.25, 0, .3, 1); }
.theme-toggle--dark .theme-moon-cutout { transform: translateX(0); }
.theme-toggle--dark .theme-sun { transform: scale(.5); }
.theme-toggle--dark .theme-sun-rays { opacity: 1; transform: rotate(90deg); }
@media (prefers-reduced-motion: reduce) {
  .theme-moon-cutout, .theme-sun, .theme-sun-rays { transition: none; }
}
</style>
