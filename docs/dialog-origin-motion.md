# 业务弹窗来源动画与详情准备

工作台业务弹窗统一使用 `components/app/AppModal.vue`。`WorkspaceDocumentDialog`、`WorkspaceLotDialog`、审批、库存详情和生产关联查询继续保留原有业务布局，通过公共壳管理准备、展开和关闭。Naive UI 继续负责焦点、键盘、遮罩及弹窗层级，业务状态与草稿仍由页面和 Pinia 管理。后端 API、单据载荷和权限规则不变。

## 来源与动画

打开入口必须显式调用 `captureDialogOrigin(key, event)`；`key` 与弹窗的 `origin-key` 一致，通常采用 `页面名:用途`。使用真实按钮或单元格的事件，键盘点击沿用同一入口。子组件发起打开时同步透传原事件，由父层登记目标窗口来源；不要使用异步回调后的 `event.currentTarget`，也不要保存全局最后一次鼠标坐标。

```vue
<!-- 在真正打开窗口的按钮上登记来源，点击关闭和刷新不会覆盖来源。 -->
<AppButton
  @click.capture="captureDialogOrigin('ExampleView:detail', $event)"
  @click="openDetail(row.id)"
>查看</AppButton>
<AppModal
  origin-key="ExampleView:detail"
  v-model:show="detailOpen"
  :ready="!detailLoading"
  :load-error="detailError"
  :busy="busy"
  @invalidated="detailOpen = false"
>
  <!-- 首屏只引用当前请求成功返回的业务数据。 -->
  <DetailContent v-if="detail" :detail="detail" />
</AppModal>
```

公共壳以 Web Animations API 同步控制位置、缩放、透明度及遮罩，正文分层淡入。圆角在起飞前固定为窗口外形，避免圆角插值连带长表格和阴影逐帧重绘；外壳与正文只在动画期间启用合成提示，完成或取消后释放。展开时关闭按钮直接呈现焦点配色，避免自动聚焦叠加背景颜色过渡。默认展开 360ms、关闭 280ms；关闭前重新测量入口，入口被删除、隐藏或移出视口时改用 140ms 淡出。系统开启减少动态效果时使用 80ms 短淡入淡出，不做位移缩放。动画中反向操作从当前画面接续，旧动画完成回调不能结束后一次动画。

嵌套窗口各自登记来源；父窗口保留在底层，关闭子窗口后回到父窗口中的实际入口。来源在正常关闭后释放，同一 key 的新登记不会被旧窗口的离场清理删除。

## 公共接口与生命周期

`AppModal` 继承原 `NModal` 公共属性、插槽与 `update:show` 契约，额外提供：

| 属性 | 默认值 / 作用 |
| --- | --- |
| `originKey` | 显式来源登记 key；模板写作 `origin-key` |
| `origin` | 可直接传入 `captureDialogOrigin` 返回的来源；优先于 key |
| `show` | 打开意图，允许在首次请求开始时设为 `true` |
| `ready` | 默认 `true`；必需数据尚未到齐时传 `false` |
| `loadError` | 默认空字符串；首次准备失败时通过公共消息反馈并取消打开 |
| `busy` | 默认 `false`；处理期间保留不可交互的完整画面并显示处理反馈，避免保存成功重置草稿后等待列表刷新时露出空正文；业务保存禁用规则仍由调用方控制 |
| `invalidationKey` | 可选的局部失效标识；变化后立即清理呈现状态 |

| 事件 | 时机与调用方责任 |
| --- | --- |
| `update:show` | 用户关闭或取消等待时请求更新打开意图 |
| `after-enter` | 完整展开动画结束 |
| `before-leave` | 正常关闭动画开始；准备阶段取消不播放回程 |
| `after-leave` | 正常关闭清理完成，或准备阶段取消完成；可释放仅供展示的数据 |
| `load-error` | 首次准备失败，参数为错误文案；同时请求关闭 |
| `invalidated` | 退出、切换服务端、撤权或局部失效时立即清理；调用方须无条件关闭本地意图，不能被 `busy` 拦截 |

正常关闭保留不可交互的离场画面，待动画结束释放。处理期间的画面使用同一隔离机制：成功关闭直接回程，失败或继续打开则恢复实时表单。副本保留原控件配色，通过 `inert`、移除标识和表单归属等约束禁止聚焦与提交，不形成第二套可编辑草稿。业务校验、点击和保存仍必须读取当前实时权限及状态。不要把展示快照重新写入 Pinia，也不要利用旧审批快照恢复按钮权限。

## 首屏准备与异步取消

公共呈现状态为 `idle → preparing → opening → open → closing`。准备期先不可见地挂载并测量正文，不显示空窗口或遮罩；来源入口标记等待状态，并提供取消等待。首屏正文、必需审批状态和必要历史全部准备好后才展开。

首屏内自行加载的子组件应调用 `useDialogPreparation(loading, error)`，将其加载状态注册到最近的弹窗。注册随子组件卸载自动释放，没有所属弹窗时不改变组件行为。使用 ref、computed 或 getter；应在首次挂载时立即启动必需请求，不能等待窗口展开事件再启动。可选采购参考、展开后才请求的附件或后续分页继续按需读取，不加入首次屏障。

异步入口需遵守以下约束：

1. 请求开始前设定本次打开意图、清空本次读取错误并递增请求代次，随后标记 `loading`。
2. 返回时同时核对请求代次、目标及稳定会话签名；同一单据关闭后重开也属于新请求，不能只比较单据 ID。
3. 取消等待、切页、退出及切换服务端后废弃对应代次；旧请求的 `finally` 也不能解除新请求的加载状态。
4. 首次失败保留错误反馈，不能把空正文作为成功结果展开。保存失败继续保留原业务草稿，保存错误不能被当作下一次详情准备错误。
5. 刷新已打开的详情时保留上次正文和窗口尺寸，成功后整体替换；刷新中及失败后禁用业务操作。当前权限、网络、版本和审批归属仍需实时检查。

根组件根据会话和服务端身份及权限变化调用全局呈现失效。局部窗口通过 `invalidated` 无条件关闭其 `show` 或业务目标；共享审批、库存与生产关联目标同时由对应 store 清理。失效不等待关闭动画，也不能重新展示旧会话数据。网络中断与退出账号分别处理：原本允许离线查看的已加载只读详情保持该业务约束。

## 页面接入与验证

外层弹窗保持稳定挂载，用 `show` 控制打开关闭；仅保留权限等安全门禁的 `v-if`。不要用 `v-if="show"` 或 `v-if="activeRecord"` 直接销毁公共壳。可以在壳内部用 `v-if="activeRecord"` 守卫正文，并为标题、表格数据和其他属性提供空态安全值。

单据弹窗保留固定标题、固定页脚、独立正文滚动和现有草稿引用；批次窗口仍由原页面构造载荷及校验数量。表格、下拉气泡和系统原生文件选择框不属于本次弹窗来源动画。

验证应覆盖来源重测、连续开关与动画反转、同单取消重开、错误与迟到响应、会话失效、保存成功重置和失败保留，以及只读快照不能启用旧权限。页面回归见 `tests/dialog-view-preparation.test.mjs`；公共动画和实际界面证据按对应测试、浏览器及 Electron 验收记录核对。本文不代表完整构建、跨平台或已安装客户端验收已经完成。

### 可复现的隔离验收

运行 `NEXORA_PREVIEW_PORT=8771 npm run docs:preview-ui` 后，打开 `http://127.0.0.1:8771/scripts/site-preview/index.html?qa=dialogs&delay=1800#/workspace/warehouse-inbounds`。此入口使用真实业务页面和 Pinia，但桥接仅返回虚构只读数据；不会连接正式服务，保存、审批、入库等写入明确拒绝。`delay` 模拟请求等待（最多 10 秒），`fail=documentApproval` 模拟首屏失败，`failAfter=2` 可让第二次读取失败以验证刷新保留正文，`theme=dark` 用于深色取景。其他入库的两个示例单据分别覆盖草稿详情和已批准的批次登记入口。访问 `#/workspace/production-dispatches` 可验收生产发料的详情、审批与工单摘要联合准备；`fail=workOrderMaterialFlow` 或 `fail=materialFlowLots` 分别模拟摘要与可用批次失败。

纯逻辑和页面回归使用 `node --experimental-strip-types --test tests/*.test.mjs`。公共动画另有 `tests/dialog-motion-browser.mjs`，通过 `NEXORA_PLAYWRIGHT_MODULE` 指向已安装的 Playwright 入口运行；`NEXORA_DIALOG_ENGINE=electron` 使用本仓库 Electron 依赖和独立临时用户目录运行同一组件验收。自动化组件验收、浏览器业务页面验收、正式安装客户端及真实业务服务验收是不同范围，不能互相替代。

### 动画性能取样

`tests/dialog-motion-performance-browser.mjs` 使用真实公共壳、主题样式和 250 行 × 10 列表格，记录三轮展开/收回的 CDP Paint、Layout、主线程派发耗时和帧间隔。与组件行为验收一样，通过 `NEXORA_PLAYWRIGHT_MODULE` 指定已安装 Playwright，直接使用 Node 运行。默认 CPU 限速 4 倍，可用 `NEXORA_DIALOG_CPU_RATE` 调整；用 `NEXORA_DIALOG_BASELINE_REF=dad7862` 加载修复前动画实现，保持取样场景一致。`NEXORA_DIALOG_EVIDENCE_DIR` 保存 JSON 与首轮追踪，`NEXORA_DIALOG_PERF_LABEL` 区分前后结果。

性能验收同时核对动画只包含 transform/opacity、动画结束释放合成提示、长表格滚动位置保留，以及离场副本不向普通单元格批量写入 tabindex。时延统计包含挂载/副本布局，`maxMotionFrameGap` 仅统计动画启动后的取样帧；主线程取样不能等同于显示器或 GPU 实际帧率，也不能代替正式安装客户端的主观验收。
