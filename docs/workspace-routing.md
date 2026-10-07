# 工作台路由表

工作台页面统一登记在 `src/renderer/src/router/workspace-routes.ts`。侧栏分类、页面地址和进入页面所需的**查看权限**均从该表读取；`router/index.ts` 将路由键映射到 `views/workspace/` 下按业务分组的页面组件，`views/WorkspaceShell.vue` 使用 `RouterView` 显示页面，具体用途见 [工作台页面目录](../src/renderer/src/views/workspace/README.md)。Vue Router 使用 Hash 模式，保持原有 `#/workspace/...` 地址，桌面安装包从 `file://` 加载时也可在刷新后恢复当前模块。

| 分类 | 页面 | 地址 | 查看权限 |
| --- | --- | --- | --- |
| 工作台 | 工作台首页 | `#/workspace/home` | 已登录账号均可访问；真实统计按各业务查看权限返回 |
| 仓库管理 | 库存总览 | `#/workspace/stock` | `inventory.view` |
| 仓库管理 | 仓库调拨 | `#/workspace/transfers` | `inventory.view` |
| 仓库管理 | 库存盘点 | `#/workspace/stocktakes` | `inventory.view` |
| 基础资料 | 物料与供应商 | `#/workspace/catalog` | `inventory.view` |
| 采购管理 | 采购订单 | `#/workspace/purchase-orders` | `inventory.view` |
| 采购管理 | 采购入库 | `#/workspace/receipts` | `inventory.view` |
| 采购管理 | 采购退货 | `#/workspace/purchase-returns` | `inventory.view` |
| 基础资料 | 客户资料 | `#/workspace/customers` | `sales.view`，新增要求 `customer.manage` |
| 基础资料 | 生产 BOM | `#/workspace/boms` | `production.view` |
| 销售管理 | 销售订单 | `#/workspace/sales-orders` | `sales.view` |
| 销售管理 | 销售出库 | `#/workspace/shipments` | `sales.view` |
| 销售管理 | 销售退货 | `#/workspace/sales-returns` | `sales.view` |
| 财务管理 | 应收应付 | `#/workspace/finance` | `finance.view` |
| 财务管理 | 总账凭证 | `#/workspace/journals` | `journal.view`；各动作独立授权 |
| 财务管理 | 期初余额 | `#/workspace/opening-balances` | `opening_balance.view`；各动作独立授权 |
| 财务管理 | 总账报表 | `#/workspace/ledger-reports` | `journal.view` |
| 财务管理 | 财务报表 | `#/workspace/financial-statements` | `financial_statement.view` |
| 财务管理 | 总账科目 | `#/workspace/ledger-accounts` | `ledger_account.view`；维护要求 `ledger_account.manage` |
| 财务管理 | 会计期间 | `#/workspace/accounting-periods` | `accounting_period.view`；维护要求 `accounting_period.manage` |
| 财务管理 | 收付款记录 | `#/workspace/payment-records` | `finance.view`；登记、冲销分别要求 `finance.record`、`finance.reverse` |
| 财务管理 | 应收应付来源 | `#/workspace/financial-sources` | `finance.view` |
| 财务管理 | 库存计价 | `#/workspace/inventory-valuation` | `inventory_valuation.view` |
| 生产管理 | 生产工单 | `#/workspace/work-orders` | `production.view` |
| 生产管理 | 生产领料 | `#/workspace/material-issues` | `production.view` |
| 生产管理 | 生产退料 | `#/workspace/material-returns` | `production.view` |
| 生产管理 | 完工与质检 | `#/workspace/production-completions` | `production.view` |
| 生产管理 | 生产成本 | `#/workspace/production-costs` | `production_cost.view` |
| 系统管理 | 用户管理 | `#/workspace/users` | `users.manage` |
| 系统管理 | 权限管理 | `#/workspace/roles` | `users.manage` |
| 系统管理 | 连接与服务 | `#/workspace/settings` | 已登录账号均可访问 |

登录后，工作台依据服务端返回的权限显示导航。工作台首页是侧栏顶部的固定入口，登录账号均可访问。Vue Router 守卫检查地址访问，服务端权限刷新后还会重新核对当前页面；未知或无权访问的地址会替换为工作台首页。登录前输入的有效工作台地址会保留，取得权限后再决定是否允许访问。没有业务查看权限的账号仍可进入“连接与服务”管理自己的连接和密码。刷新桌面窗口页面时，客户端会核验主进程当前持有的会话，再恢复账号与工作台；服务端会话过期或退出登录后仍需重新登录。完全退出桌面程序会丢弃内存中的令牌，下次启动需重新登录。

工作台首页通过 `/api/v1/dashboard/query` 读取近 7/30 天的真实业务净额、趋势与有效单据构成，当前待办和库存不受日期限制。金额要求财务查看权限，数量按对应业务权限返回，缺价与未授权分别显示；更正按事件日期保留。展示逻辑在 `views/workspace/home/dashboard-data.ts`，完整口径和边界见 [首页统计规则](home-statistics.md)。

“用户管理”用于创建账号、分配角色以及管理账号状态和密码；“权限管理”用于创建自定义角色、为角色分配权限，以及维护权限目录中的中文名称。两个入口都要求 `users.manage`，具体写操作仍由服务端授权。权限代码和自动生成的自定义角色代码只作为内部标识；授权仍按固定代码校验，修改中文名称不会更改已有授权，也不能新增服务端未实现的权限。内置角色只读。

侧栏业务分类默认全部收起，工作台首页作为固定入口始终可见。点击分类标题展开页面入口，再次点击收起；展开另一分类时，之前的分类自动收起。展开与收起有短暂的高度和透明度过渡，箭头同步转动；系统启用“减少动态效果”时取消这些过渡。当前页面所属分类即使收起也会保留高亮提示。

工作台顶部的页面栏记录本次登录已打开的页面。侧栏、页面栏及地址历史切换都使用同一张路由表；重复访问不会新增标签。关闭当前标签时切到相邻的已打开页面，唯一标签不能关闭。权限被撤销时会移除对应标签；退出登录后清空页面栏，避免向下一位登录用户显示访问记录。标签过多时可横向滚动；打开或切换页面时，页面栏会自动滚动到当前标签。

路由表和 Vue Router 守卫只控制页面展示。创建、确认、冲销和其他写操作仍按各自权限由 FastAPI 服务端校验；客户端侧栏隐藏或页面拦截不能代替服务端授权。增加页面时，需要同步登记路由表、页面组件映射和测试。当前登录与初次连接流程仍由应用启动状态管理，不属于工作台路由。

物料需求计划入口为 `/workspace/material-planning`，属于生产管理，仅 `mrp.view` 可见。其公司范围来源读取与原单建单权限分开；编制、参数、审核、取消和转单逐项授权。转单再检查目标权限，详见 [MRP](material-planning.md)。

生产 BOM 归入基础资料，页面地址仍为 `#/workspace/boms`，查看权限仍为 `production.view`；创建、启用、停用与取消继续使用原生产业务权限，工单固定版本引用不变。新建版本复用公共单据弹窗，组件在物料明细表中搜索选择并编辑基准用量；保存失败或收起弹窗时保留 Pinia 草稿。
