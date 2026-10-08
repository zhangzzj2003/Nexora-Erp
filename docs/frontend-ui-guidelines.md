# 前端 UI 开发规范

适用范围：`src/renderer/` 下的 Vue 3 + TypeScript 页面和组件。Electron 主进程、预加载脚本及 Python 后端不使用本规范中的 UI 依赖。

## 统一技术选型

| 用途 | 项目标准 | 使用方式 |
| --- | --- | --- |
| 交互组件 | Naive UI | 从 `naive-ui` 按需导入；表单、按钮、选择器、表格、弹窗和反馈优先使用它。 |
| 跨页面状态 | Pinia | 新模块使用 `defineStore`；组件解构响应式状态时使用 `storeToRefs`，操作方法直接从 store 获取。 |
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

根组件 `App.vue` 只装配全局环境；启动流程、登录与工作台页面分别位于 `views/`，工作台页面再按业务领域分组。公共状态底栏与主题按钮位于 `components/app/`，消息提供器与反馈桥接位于 `components/feedback/`，侧栏、账号卡片和标签栏位于 `components/workspace/`；会话状态和业务操作位于 `store/`，地址与权限规则位于 `router/`，辅助逻辑位于 `utils/`。公共底栏左侧显示当前服务端名称和版本，右侧显示连接状态；工作台侧栏底部是紧凑账号栏，显示当前用户与角色。账号信息悬停时渐变高亮，点击后打开退出登录菜单；右侧 Naive UI 图标按钮以月亮和太阳表示可切换的明暗主题。窄窗口侧栏收起后，账号和主题按钮显示在顶部。主题选择保存在本地，`App.vue` 的 `NConfigProvider` 与 `light-theme.css`、`dark-theme.css` 同步使用它；浅色整页保持灰白，深色整页使用深蓝，切换时表面、文字和边框平滑过渡。启动向导、登录页和工作台均随主题变化。当前 `style.css` 与部分页面仍保留早期原生控件和独立 CSS，后续修改应逐页整理，不把旧控件作为新增页面的范例。

登录及首次管理员设置时不显示工作台侧栏，标题左侧展示与侧栏相同的品牌 Logo，表单卡片在可用窗口区域居中，公共状态底栏铺满窗口。进入工作台后侧栏从左侧滑入，内容与底栏随侧栏列展开向右收缩；退出登录时反向恢复。系统启用“减少动态效果”时取消这段过渡。

前端改动至少运行 `npm run build`（包含类型检查），并在 Electron 桌面窗口检查实际改动的页面。涉及响应式布局、图标或交互状态时，检查窄窗口、键盘焦点、禁用与加载状态。构建通过不等同于桌面视觉验收，也不等同于真实服务端功能验收。

## 业务列表与标题层级

- 仓库、基础资料、采购、销售、财务、生产和系统列表复用 `components/workspace/WorkspaceTable.vue`，不再为单据单独堆叠卡片。筛选面板、行间距、按钮换行、空状态和明暗主题由共享组件维护。
- 公共表格默认将配置列宽作为最小值，均分容器剩余空间；缩小列宽后表头和数据行仍铺满。窄窗口保留最小列宽、横向滚动及原固定列；确需固定宽度时可显式设置 `stretchColumns=false`。
- 表头列间边界显示常驻分割线，最右侧外框不重复画线；横向滚动与右侧固定列交界处仅保留固定列的分割线，避免滚到末端出现双线。悬停时高亮，支持拖动调宽（64–2400px）；分割线随明暗主题变化。拖动时表头、数据行和冻结区实时重排，不显示宽度数值浮层；松手后保存，按 Esc 或窗口失焦则恢复本次拖动前布局。公共表格显式注册并启用中文语言包，内置文案不回退为语言键。手动设置按页面、表格名称和字段保存在本机，下次打开自动恢复；不跨设备同步。调整后可点击“恢复默认列宽”。存储不可用时当前窗口仍可调整，损坏或过期字段配置忽略；所有列都手动调整后仍保留一列分配余量，默认铺满能力不会丢失。
- 页面外部标题由 `WorkspaceShell.vue` 展示；页面说明集中在 `utils/workspace-page-copy.ts`，紧随大标题。主列表使用 `showTitle=false`，避免卡片再重复页面名称；辅助列表保留有意义的分区标题。
- 业务单元格保留原有状态、权限、表单约束和事件参数。可见字段搜索使用 `utils/workspace-records.ts`，不得把密码等隐藏草稿加入搜索。权限树与设置表单保持适合自身功能的布局。
- 其他入库的物料摘要按内容宽度展示两行，“+N 项”以 8px 间距紧随摘要；加宽列不会把标签推到列尾，窄列继续省略长文本并保留余项标签和完整悬停说明。
- 其他入库的行操作按列内空间及实际按钮宽度实时展开，放得下时直接展示全部按钮，仅将放不下的操作收进“更多”；极窄列可只保留菜单入口。常用操作保持优先，权限、禁用状态和业务确认流程不变；详情仍展示完整操作区。

- 列表的 `filters` 与 `actions` 共用一条工具栏；查询等筛选提交按钮放在 `filterActions`，与新建、导出等操作一起靠右。条件按可用宽度换行，按钮组整体移到末行；仅有操作且没有筛选的辅助表格仍保留标题栏操作。

供应商主列表支持服务端分页搜索：`POST /api/v1/suppliers/query` 接收 `query`、`page`（从 1 开始）与 `page_size`（1–100，默认 20），返回 `items`、筛选后 `total`、有效 `page` 和 `page_size`；查看仍要求 `inventory.view`。总数与分页统一显示在表格底部，可选每页 10/20/50/100 条，搜索回到首页，删除造成的越界页自动回退。查询失败提供重试入口，过期响应不覆盖新结果。原 GET 供应商接口仍供业务选项使用，其他列表及供货物料明细尚未改为服务端分页。客户端与服务端需同时升级。
