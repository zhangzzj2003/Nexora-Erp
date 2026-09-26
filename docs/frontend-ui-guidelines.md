# 前端 UI 开发规范

适用范围：`src/renderer/` 下的 Vue 3 + TypeScript 页面和组件。Electron 主进程、预加载脚本及 Python 后端不使用本规范中的 UI 依赖。

## 统一技术选型

| 用途 | 项目标准 | 使用方式 |
| --- | --- | --- |
| 交互组件 | Naive UI | 从 `naive-ui` 按需导入；表单、按钮、选择器、表格、弹窗和反馈优先使用它。 |
| 布局和样式 | Tailwind CSS 4 | 在 Vue 模板中使用工具类处理布局、间距、响应式和常规视觉样式。 |
| 图标 | [Icônes](https://icones.js.org/collection/ri) 的 Remix Icon（`ri`） | 从 `~icons/ri/<图标名>` 按需导入 Vue 组件。 |

不为新页面引入第二套组件库、图标库或在线图标 CDN。`icones.js.org` 用于查找图标名称；应用运行时使用构建进安装包的 SVG，不依赖该网站。

## Naive UI

- 新增交互控件优先选用对应的 Naive UI 组件。保留 HTML 的语义结构，例如页面标题、段落、链接和真正的表格数据；原生控件仅在 Naive UI 不适合或平台行为明确需要时使用，并说明原因。
- 使用组件的正确绑定接口，例如 `NInput` 使用 `v-model:value`。表单校验、禁用、加载和错误反馈应与实际业务状态一致。
- 沿用根组件 `App.vue` 中的 `NConfigProvider` 中文语言和主题色。需要调整全局主题时修改同一处配置，不在多个页面分别写一套相似颜色。
- 按需导入使用到的组件，不使用整库注册。只为具体场景引入 `NMessageProvider`、`NDialogProvider` 等上下文组件。

## Tailwind CSS

- 优先在模板中用工具类组合布局、间距、尺寸、响应式和状态样式。可复用的复杂视觉结构、动画或第三方组件覆盖规则放在局部 CSS 中，并加中文注释说明原因。
- Tailwind 入口是 `src/renderer/src/style.css`，由 `electron.vite.config.ts` 的渲染进程 Vite 插件处理。当前项目保留了原有基础样式，**未启用 Preflight 全局重置**；不得在其他入口重复导入 Tailwind。
- 不把动态值拼成 Tailwind 类名，例如 `bg-${color}-500`。使用完整的静态类名映射，确保构建时能识别。
- 避免在同一元素上让旧 CSS 类与 Tailwind 工具类设置相反的属性。现有未分层 CSS 的优先级可能高于 Tailwind 工具类；修改旧区域时应先检查实际渲染结果，再移除冲突规则。
- 常用颜色、字号与间距沿用现有界面；需要新增可复用值时集中定义，不在多个组件里散落不同的近似数值。不要用大量行内样式代替这套样式规则。

## Icônes / Remix Icon

- 在 [Remix Icon 图标集](https://icones.js.org/collection/ri) 中选图标，使用该页显示的 `ri:<name>` 名称，代码导入路径写为 `~icons/ri/<name>`。例如 `ri:refresh-line` 对应 `~icons/ri/refresh-line`。
- 统一使用 `ri` 集合，优先使用 `-line` 风格；同一组控件的图标尺寸、线条风格和颜色保持一致。不要用 emoji、Unicode 符号、图标字体或另一套图标库代替新图标。品牌字母、纯文字和数据符号不算图标。
- 图标随组件按需导入。`unplugin-icons` 和 `@iconify-json/ri` 是构建依赖；不要运行时向 Icônes 或 Iconify 发请求。
- 图标只作装饰时加 `aria-hidden="true"`，按钮仍保留可见文字。只有图标的按钮必须提供明确的 `aria-label`，并保留可见焦点与足够的点击区域。

```vue
<script setup lang="ts">
import { ref } from 'vue'
import { NButton, NInput } from 'naive-ui'
import IconSearchLine from '~icons/ri/search-line'

// 输入状态交给 Vue 管理；按钮图标使用本地打包的 Remix Icon。
const keyword = ref('')
</script>

<template>
  <div class="flex items-center gap-3">
    <NInput v-model:value="keyword" placeholder="搜索物料" />
    <NButton type="primary">
      <template #icon><IconSearchLine aria-hidden="true" /></template>
      搜索
    </NButton>
  </div>
</template>
```

## 现有页面与验收

当前 `App.vue` 和 `style.css` 仍包含项目早期的原生控件、独立 CSS 与少量字符图形。它们是待逐步整理的现状，不是新增代码的范例。修改相关区域时以本规范为目标，保持原有业务逻辑与交互；不要为了统一技术选型一次性重写无关页面。

前端改动至少运行 `npm run build`（包含类型检查），并在 Electron 桌面窗口检查实际改动的页面。涉及响应式布局、图标或交互状态时，检查窄窗口、键盘焦点、禁用与加载状态。构建通过不等同于桌面视觉验收，也不等同于真实服务端功能验收。
