---
name: Nexora ERP 官网
description: 浅色银白实体窗口、WebGL 来源关系与可读文档；仅适用于 docs/site
colors:
  paper: "#fafbfc"
  stage: "#f8fafc"
  ink: "#182b35"
  muted: "#596873"
  teal: "#176f67"
  action: "#087f75"
  action-hover: "#06695f"
  selected: "#078579"
  linked: "#12bfa7"
  linked-row: "#e0f8f0"
  panel: "#fff"
  window-surface: "#fbfdff"
  sidebar-surface: "#f7fafc"
  chrome-shade: "#eaf0f5"
  window-frame: "#d6e2e9"
  stage-light: "#dfeaf078"
  placeholder: "#dfe9ef"
  rule: "#d9e0e4"
  field-rule: "#ccdbe5"
  field-focus: "#2ca998"
  field-ink: "#203440"
  secondary-ink: "#365d6a"
  stage-control-ink: "#47616d"
  status-bg: "#c9f6eb"
  status-ink: "#076f61"
  draft-bg: "#fcf1d5"
  draft-ink: "#7d5712"
  error: "#a2292f"
typography:
  display: {fontFamily: 'Inter, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif', fontSize: "clamp(64px,min(7.6vw,10.7svh),112px)", fontWeight: 750, lineHeight: 1.08, letterSpacing: "-.035em"}
  headline: {fontSize: "clamp(30px, 3.2vw, 45px)", fontWeight: 700, lineHeight: 1.3, letterSpacing: "-.025em"}
  window-title: {fontSize: "36px", lineHeight: 1.2, letterSpacing: "-.025em"}
  body: {fontSize: "16px", lineHeight: 1.9}
  sandbox: {fontSize: "16px", lineHeight: 1.45}
  sidebar: {fontSize: "17px"}
  field-label: {fontSize: "15px"}
  table: {fontSize: "15px", lineHeight: 1.5}
  amount: {fontSize: "46px", lineHeight: 1.25, letterSpacing: "-.03em"}
  code: {fontFamily: 'Consolas, "SFMono-Regular", monospace', fontSize: "13px", lineHeight: 1.8}
rounded:
  placeholder: "3px"
  field: "5px"
  sidebar-action: "6px"
  sheet: "8px"
  primary: "9px"
  window-content: "10px"
  window-chrome: "11px"
  window-base: "12px"
  window: "14px"
  step: "22px"
  step-track: "26px"
spacing:
  control-gap: "9px"
  field-label-gap: "7px"
  field-gap: "18px"
  sheet-inset: "23px"
  scene-horizontal: "32px"
components:
  button-primary: {backgroundColor: "{colors.action}", textColor: "{colors.panel}", rounded: "{rounded.primary}", padding: "13px 24px"}
  sandbox-primary: {backgroundColor: "{colors.action}", textColor: "{colors.panel}", rounded: "{rounded.field}", padding: "9px 13px"}
  sandbox-primary-hover: {backgroundColor: "{colors.action-hover}"}
  sandbox-secondary: {backgroundColor: "{colors.panel}", textColor: "{colors.secondary-ink}", rounded: "{rounded.field}", padding: "9px 13px"}
  field: {backgroundColor: "{colors.panel}", textColor: "{colors.field-ink}", rounded: "{rounded.field}", padding: "9px"}
  status-chip: {backgroundColor: "{colors.status-bg}", textColor: "{colors.status-ink}", rounded: "{rounded.field}", padding: "6px 11px"}
  status-chip-draft: {backgroundColor: "{colors.draft-bg}", textColor: "{colors.draft-ink}"}
  stage-button: {textColor: "{colors.stage-control-ink}", rounded: "{rounded.step}", padding: "8px 16px"}
  stage-button-selected: {backgroundColor: "{colors.selected}", textColor: "{colors.panel}"}
  demo-window: {rounded: "{rounded.window}"}
  window-viewport: {rounded: "{rounded.window}", padding: "1px"}
  receipt-sheet: {backgroundColor: "{colors.panel}", rounded: "{rounded.sheet}", padding: "23px"}
---

# Design System: Nexora ERP 官网

<!-- 归档当前源码中的设计；范围仅 docs/site，不覆盖 ERP 桌面应用，也不是整站验收证明。 -->

## Overview

**Creative North Star: "清晰的业务舞台"**

浅色舞台、银白实体应用窗、现代无衬线文字与青绿来源关系共同解释业务。窗口保持独立软件界面的宽高与桌面侧栏，整体缩小后形成明显透视；单层细边、同一地面上的漫射光池、掠光与接触阴影共同表达实体感；取消镀层高光与厚底边。保留用户批准的浅色方向与 Inter 字体，不恢复此前浅角度、窄长三列的构图。

本规范覆盖当前 WebGL 视觉层、原生 HTML 业务沙盒与平实文档。Nexora/联光 ERP 名称及品牌资源沿用项目资产；官网支持中英文，本地演示不连接 ERP 服务，也不代表桌面应用已支持双语。

**Key Characteristics:**

- 独占首屏的大标题封面，以一条青绿细线随滚动走向业务舞台。
- 独立银白应用窗使用单层细边，GPU 漫射光池、冷暖掠光与接触阴影建立地面层次，无内容倒影。
- 三窗共地平线；总览两侧为 30° / −30°，库存中窗为 4°。
- 应用逻辑画布整体缩放，桌面保留采购、库存、销售、生产、财务、系统文字。
- HTML 管理业务、表单与焦点；GPU 只承担视觉。
- 文档平实可读，手机与减少动态模式纵向排列并保留业务操作。

## Colors

前置 token 提取自 site.css 与 sandbox.css，记录实际局部覆盖。青绿是业务行动与来源关系的识别色；银灰和冷白只承担窗口材质，环境光不扩展成新的业务状态色。

### Primary

teal 用于官网链接与全局焦点，action 用于主行动，action-hover 用于业务主按钮悬停，selected 用于步骤选择。linked 与 linked-row 表达来源锚点及库存关联。已入库与草稿分别使用 status 与 draft 配对的浅底和文字；错误同时显示 error 色和字段说明。

### Neutral

paper 是文档纸面，stage 是首页底色，panel 是单据面板。window-surface、sidebar-surface 与 chrome-shade 保留应用内容、侧栏和标题栏的冷白层次；ink、muted 区分正文与说明，rule、field-rule 承担内容分隔和字段边界。

window-frame 是窗口单层 1px 冷灰细边与底线；stage-light 是舞台环境光，placeholder 是库存表中的装饰占位条。移除旧 silver token，sidecar 同步当前细边外观。GPU 来源带和光点颜色由着色器生成。

**The Business Accent Rule.** 品牌色强调操作与来源关系，不替代字段文字。

## Typography

Inter、Segoe UI、PingFang SC、Microsoft YaHei、sans-serif 是既定现代无衬线体系。Inter 本地可变字体支持 100–900 字重及 font-display: swap；中文沿用回退字体。字体来自 [Inter 官方仓库](https://github.com/rsms/inter)，采用 SIL Open Font License 1.1，许可随 fonts/LICENSE.txt 分发。此前字体检测提示已随用户批准的字体选择保留在 sidecar。

前置的 sandbox、sidebar、table、window-title 和 amount 都是逻辑应用画布内的桌面字级；画布缩放后可见尺寸随窗口一起变化。总览的窗口标题局部为 35px，应付金额为 44px。手机标题为 23px、业务正文与字段为 12px、表格为 11px、应付金额为 34px；封面标题按视口宽高限制在 64–112px，760px 以下使用 clamp(40px,10.6vw,68px)，低于 620px 的视口使用 clamp(36px,min(6vw,11svh),68px)。说明由桌面 18px 降为手机 14px。

文档正文最大 75ch，720px 以下为 15px。业务数字采用等宽数字；代码采用 Consolas、SFMono-Regular、monospace。

**The Readable Documentation Rule.** 产品展示的密度与标题尺度不扩散到长文正文。

## Layout

首页封面独占 `100svh`，页眉在其顶部叠放；脚本测量页眉高度预留文字空间，CSS 默认状态同样保证首屏不露出业务窗口。标题、说明和两项行动居中，留白按视口高度收敛，底部提供原生舞台锚点。桌面大标题最大 112px，620px 临界高度采用约 66px 的标题与更少的留白，较长英文说明及滚动入口仍容纳在封面中。

`cover-motion.mjs` 用一条细青绿线从行动下方引向界面预览区域顶边，随滚动按弧长伸长；内容最多上移 28px、缩小 1.8%，不加循环浮动。进入界面预览区域后淡出封面线，避免长线穿过截图；没有预览区域时仍兼容原舞台落点。下方交互舞台保留原有业务来源连线。桌面额外使用一个按需 WebGL 线层，SVG 共用路径负责 GPU 失效及手机回退；减少动态和低高度视口使用静态短线。路径不接收输入，手动聚焦、快速离场、后台暂停和倒滚均保留清晰的状态边界。

页眉最大 1360px，桌面沙盒舞台最大 1440px，真实明细舞台最大 1680px。滚动场景为 340vh，粘性区域为 100svh、最小 620px。窗口区初始采用 calc(100svh - 220px)，最大 650px；进入总览时 JS 随窗口状态调整舞台高度。HTML 与 GPU 共用 scene-geometry.mjs，透视距离为 1400px，投影原点在各窗底部中心；窗下沿统一落在舞台底部上方 35px。

JS 按舞台标题、叙述、控制、状态及说明的实际高度与边距预留空间，额外留 8px；入库、聚焦和总览都受同一可用高度上限约束，620px 临界视口也不裁切顶部或底部内容。

初始入库的最小逻辑画布为 1100 × 590；总览的入库、库存、财务分别为 600 × 570、1000 × 585、600 × 550。初始入库的目标占宽为 85%，双窗目标占宽为 40% / 59%，三窗为 29% / 46% / 29%；这些是布局意图，实际宽度同时受可用高度及透视近侧限制。窗口保留逻辑宽高比，整体等比缩放，不将桌面界面挤成窄表单。

沙盒聚焦窗归正至 0°，逻辑宽统一为 1000px；入库、库存、财务的最小逻辑高度分别为 720px、650px、680px。实际高度按当前页内容、展开明细和字段错误适配，加上标题栏/窗底 43px，再沿同一镜头整体缩放。目标占宽仍为 85%，高度不足时等比缩小。其余窗移向两侧、透明度降至 .25，并退出交互。财务仅在启用桌面动态且聚焦时将来源摘要与付款表单分为两列；静态、手机与减少动态模式保持纵向布局。

桌面侧栏保持 148px，紧凑总览为 145px，并保留全部业务名称。仅在 760px 以下变为 40px 图标栏；手机窗口最大 600px、间距 54px，取消固定行程，表格变为带字段名的行卡片，长列表分页；只有页面自然滚动，窗口不建立横向或纵向滚动容器。减少动态模式同样取消透视及固定行程，纵向舞台最大 1100px。

文档最大 1210px，230px 目录、最大 840px 正文、70px 列距。1100px 以下为 190px 目录、35px 列距；720px 以下单列。打印恢复顺序内容流并隐藏画布、连线与地面光池。

**The Shared Ground Rule.** 三窗共用底部投影原点与同一地面，窗口内容沿逻辑宽高比整体缩放。

## Elevation & Depth

桌面原生 WebGL 使用两块透明画布。下层绘制漫射光池、低角度冷暖掠光与接触阴影，取消逐层银框和金属高光；上层以三角带绘制柔边来源线和光点。窗口内容仍是 HTML。画布 pointer-events:none 且 aria-hidden，不截获输入；父舞台保持 transform-style:flat，子窗使用底部中心的 perspective 与 rotateY。

不复制窗口内容。地面光场先用相同透视投影计算窗底两端、中心和跨度，再分层绘制冷灰漫射底色、冷暖光斑与掠光、短接触阴影。细微材质只在光照中显现；光斑扫动由滚动进度决定，窗口缩放与聚焦时仍贴合窗底，退场窗口不留下光池。GPU 失效时显示轻量 CSS 光池，手机与减少动态模式保持平面阅读。

切换先用约 80ms 淡出旧来源线，接近终态时淡入仍符合条件的关系。聚焦退场窗透明度 .25 不满足连线门槛 .55，屏外端点、顺序交叉或不同来源直接清除路径，不留下横穿操作区的线。CSS 窗口仍保留轻阴影（0 2px 3px #3d566429,0 18px 28px #29434f18）；GPU 失效时单层细边与这份阴影继续提供窗口外观。首页主行动使用柔和阴影（0 8px 22px #087f7518），文档依靠浅色层次与分隔线组织阅读。

**The Purposeful Depth Rule.** 空间感解释窗口关系，编辑时保证可点击与可读，文档保持平面阅读。

## Shapes

实体窗与内 viewport 使用柔和圆角（14px）；标题栏上角（11px）、内容下角（10px）与1px 底线下角（12px）组成同一轮廓。单据面板（8px）、字段、业务按钮和状态（5px）、侧栏选择（6px）保持软件界面的紧凑感。首页行动（9px）、步骤按钮（22px）、轨道（26px）与表格占位条（3px）按各自用途区分。边框通常为 1px；窗口 viewport 仅 1px padding，底线仅 1px 高，不再叠加角部镀层。

底线的 12px、内标题栏的 11px 和占位条的 3px 是当前源码中的实际 radius advisory，随用途归档，不将它们当成全站新增圆角档位的建议。

## Components

### Buttons and Fields

桌面逻辑画布内，普通沙盒按钮最小高 38px、字段最小高 39px；主按钮实心青绿、次按钮白底，禁用 opacity .5。字段焦点为 2px、外扩 1px；全局键盘焦点为 3px 青绿、外扩 5px。错误关联 aria-invalid、说明文本与状态播报；主动来源导航结束后聚焦目标标题，输入获得焦点仅中止当前放大补间，页面滚动仍立即接管镜头，未出现、离开舞台或聚焦后退到两侧的桌面窗 inert 且 aria-hidden。较多记录使用分页：物料及应付明细每页 2 行，库存流水每页 4 行，余额/付款记录每页 3 行。添加行打开末页，校验失败定位错误所在页，删除/筛选后的页码自动收敛；所有合计始终使用完整业务数据。默认示例和展开操作均不建立内部滚动容器。

### Application Navigation

采购、库存、财务按钮进入对应窗口的聚焦操作。销售、生产、系统是应用上下文标签，保留文字与图标但不可点击；不为演示添加不存在的业务入口。静态和手机模式的跳转滚动至对应窗，不附加桌面聚焦的两列样式。手机图标按钮保留 aria-label。

### Business Sandbox

本地沙盒支持新建/复制草稿、多物料入库、库存筛选、来源追溯、部分付款与付款历史。确认派生库存和应付，已确认单据只读，草稿不改余额。默认 DEMO-001 为数量 12、单价 ¥10.00、库存 +12、应付 ¥120.00；失败不替换旧状态。刷新/重置恢复默认，同标签页语言链接用一次性 sessionStorage 交接校验状态。库存的装饰占位行 aria-hidden，不表示额外业务记录。

### Stage and Source Connections

原生 scroll 与按需 requestAnimationFrame 驱动：20–38% 库存右进，52–70% 财务右进；34–43% / 66–76% 绘出两条线，85–95% 光点回看来源。阶段文字边界为 32%、63%、85%；分步按钮原生滚到 10%、45%、80%、92%，“返回总览”滚到 92%。聚焦约 450ms；任何页面滚动立即退出聚焦与编辑保持、取消未完成补间并采用实际进度，不提供暂停/恢复按钮，不插入恢复延迟。滚动只改镜头，不写业务。

手动切换每帧最多推进 34ms，慢帧延长过渡而不跳过大段位移；离屏和后台暂停后从已走时间与当前姿态接续。正常帧率保留约 450ms 聚焦行程；资源停帧不阻止页面继续滚动。

展示区使用 overflow-anchor:none，窗口适配和聚焦布局变化不触发浏览器滚动位置补偿。

曲线在真实 HTML 中测量逻辑锚点，再与窗口共用投影；入库起点为来源圆点中心，库存连接行边缘，SVG/GPU 端点和淡入淡出一致。手动过渡只插值预先测量的实体姿态与舞台高度，目标布局固定，内部画布随四边缩放，终态等比；快速切换接续当前帧，编辑可中止放大；页面滚动始终接管，并按实际姿态重算锚点和灯光。手机使用外缘 SVG 纵向连线，窗口以 18px / 400ms 轻微显现；减少动态效果取消位移、透视、显现与连线光晕，保留静态来源线和操作。高度低于 620px 同样取消固定舞台；宽度不超过 1000px 的低高度横屏采用手机行卡片，较宽低高度窗口保持桌面尺寸、纵向排列。离屏切换也立即清除旧实体尺寸与键盘锁定。静态偏好不初始化 WebGL；无脚本显示静态示例。

WebGL 首次桌面动态绘制才初始化，DPR 最高 2 并受 GPU 缓冲尺寸限制。初始化、编译失败或上下文丢失时回退 HTML/CSS/SVG，不重置业务数据；恢复时重建 GPU 资源并请求当前帧，卸载释放资源。静止、离屏和后台不维持连续循环。组件 sidecar 是自包含 HTML/CSS 外观预览，不运行 WebGL 或业务状态机，也不宣称完整舞台复现或整站视觉验收通过。

## Do's and Don'ts

### Do:

- **Do** 将规范限制在 docs/site，保留浅色银白实体窗与既定无衬线字体。
- **Do** 让 HTML 与 GPU 使用相同的 1400px 透视、底部中心原点和逻辑画布比例。
- **Do** 保留桌面侧栏文字、真实锚点、字段验证、键盘路径、滚动优先与 GPU 失效回退。
- **Do** 区分本地演示、桌面能力和计划，随字体保留 OFL 许可。

### Don't:

- **Don't** 恢复此前 7° 浅角度、窄长三列的构图，或旧卡片、深色概念图与衬线默认方案。
- **Don't** 用画布承载业务表单、截获输入，或在恢复 GPU 时重置业务数据。
- **Don't** 在编辑时移动镜头、以连线遮挡字段，或以滚动触发业务操作。
- **Don't** 将销售、生产、系统上下文标签伪装为可操作的演示功能。
- **Don't** 将本规范覆盖到 ERP 应用，把预览色阶当成生产 token，或把静态预览写成整站验收证明。

## Current Interface Previews

首屏保留桌面 ERP 定位与内部试用边界，宽屏两侧增加真实首页和物料卫星预览，中央加入四步业务路径；1180px 以下隐藏卫星，手机路径保持紧凑。封面之后五张浅色 1800 × 1200 真实 Vue 组件截图沿轨道逐站展开，桌面图文左右交替，760px 以下纵向阅读。图外编号作为未变形布局的实测节点，图片随滚动从两侧入场（最多 56px 横移、76px 下移、10° 透视和 0.9 缩放），中央阅读区恢复完整比例与不透明度，离场后轻退；倒滚复现同一姿态，说明保持平面。手机改为最多 28px 纵向位移和 0.965 缩放。键盘焦点所在卡片立即恢复完整可见，减少动态和打印使用完整静态图片。每图标注“当前界面预览 · 示例数据”。

`product-orbit.mjs` 用视口大小的透明 WebGL 画布贯穿封面、全部截图、三窗舞台、能力区与正文外缘；不分配整页高度的 GPU 纹理。首屏椭圆和路径使用三角带/光点，截图与文字仍由 HTML 展示；GPU 失效自动使用相同裁切几何的 SVG，手机不初始化 GPU、保留轻量滚动入场，减少动态保留完整静态图片与连线。路径按视口 76% 阅读线的弧长进度推进与回收，光点位于当前进度端；首屏椭圆光点同样绑定滚动，不再独立计时流动。每次滚动合并到下一动画帧，停止滚动即停绘，不使用 30fps 节流或追赶补间。先集中读取布局，再写姿态，编号不参与变形；三窗吸顶标题的入口以舞台自然位置测量，避免端点随 sticky 改变曲率。后台停帧，快速锚点跳转直接呈现新位置。旧 `cover-motion.mjs` 保留无全页轨道的兼容入口，当前首页不重复挂载。

三窗默认使用当前应用采购入库、库存台账、应收应付来源的完整工作台外壳，保留顶部导航、页面标签、侧栏和底栏。逻辑画布为 720 × 480，工作区内放大真实明细：左边距 18%、上边距 35%、宽度 79%，原始取景区域为 640 × 256。内容字体约为完整图的 2.2 倍；不另加官网大标题或青绿统计底栏，物料说明采用紧凑的工作区文案。三窗使用 5400 × 3600 无损 PNG，来自当前浏览器真实 DOM 和计算样式的三倍像素导出，不对小图插值放大；未将 DOM 导出描述成原生桌面截图。透视缩减至原镜头的 40%，三窗总览保留连线间隙，编号和说明不充当业务连线端点。

`source-details.mjs` 保存原图取景坐标、逐行高亮边界与图片内容版本。选择微控制器、电阻或电容时，三窗统一高亮同一物料：入库 200 / 2000 / 1000 个，库存 +200 / +2000 / +1000 个，应付 4000 / 400 / 400 元。连接凭据为 `receipt:101:行号`，不只比较单据编号。高亮矩形同时作为 HTML 与 WebGL/SVG 的端点，缩放和透视后仍落在实际行内。取景只改变显示范围，不改截图内容、不将图片控件伪装为可操作应用；点击明细打开完整原图。

760px 以下只放大所选行：入库保留物料与数量，库存保留来源与变动，应付保留物料与金额，完整外壳保留页面身份，工作区明确料号及数量/金额；视窗宽 340–440 原始像素，高 112px，关键字段保持单行取景。三窗纵向接续，页面无横向溢出。图片未加载或失败时隐藏高亮与关联线，显示错误说明并保留原图入口。取景依赖固定素材，更新图片必须重新核对坐标并同步版本。

切换“业务演示”恢复原有可操作沙盒和画布，切换不重置单据、付款或筛选。真实截图与沙盒分别标注。选择物料只更新预览高亮和说明，不写入沙盒或业务数据。

点击图片打开原生 dialog：关闭按钮自动聚焦，Esc 关闭、Tab 保持模态焦点，关闭恢复触发链接焦点。修饰键保留浏览器另开方式，无脚本或不支持 dialog 时直接打开原图。加载失败显示文本且保留原图入口；图片宽高固定以预留空间。小屏大图可在弹窗内部横向查看，页面本身不横向溢出。大图不增加动态效果，保留原有减少动态策略。

示例会话复用当前 App、真实 Pinia、顶部导航、页签、侧栏与共享表格，全部数据由回环预览入口隔离提供；截图不代表原生 Electron 服务连接验收。复现步骤见 `screenshots/README.md`。
