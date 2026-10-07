# Nexora FastAPI 服务

## 代码目录

`app/main.py` 组装 FastAPI 应用及路由；`app/server.py` 和 `app/backup.py` 保留桌面程序、命令行与打包程序使用的入口。业务实现按功能查找：

| 目录 | 主要代码 |
| --- | --- |
| `app/access/` | 账号登录、用户、角色、权限、导航图标配置及授权检查。 |
| `app/catalog/` | 供应商与物料基础资料。 |
| `app/core/` | 数据库迁移、静态 SQLAlchemy ORM 模型与统一会话事务边界。 |
| `app/purchase/` | 采购申请、采购订单、采购收货、入库单、采购退货。 |
| `app/inventory/` | 仓库、其他入出库、调拨、盘点、独立调整、库存余额、台账和按仓库预警。 |
| `app/sales/` | 客户、联系人、跟进、商机、独立审核报价与转销售草稿、销售订单及合同正文版本、出库、销售退货与售后退换修（含保修期限、内部工时成本核价与维修直接毛利）。 |
| `app/production/` | BOM、工单、领退料、报工、工单成本、完工批次结算、不合格品处置与返工、MRP 日期计划及设备维护接口。 |
| `app/finance/` | 应收应付、订单余额、手工收付款、人工银行流水勾对与余额调节、总账科目、会计期间、期初余额、手工及业务来源凭证与附件、损益结转、已过账报表、公司财务报表与固定归档、辅助核算及期间结账与重开。 |
| `app/reports/` | 采购执行、收退货、库存余额与收发存报表，及按原有权限返回的首页经营快照。 |
| `app/service/` | 服务状态、局域网发现、系统服务、备份恢复。 |

`backend/launcher.py` 是安装包中的固定命令入口，`backend/tests/` 放对应业务和服务测试。新增功能先放入所属功能目录，再在 `app/main.py` 注册路由；已有 `app.server`、`app.backup` 命令路径保持可用。完整放置规则见 [后端项目树规范](../AGENTS.md#后端项目树规范)。

需要 Python 3.11+。开发环境从仓库根目录安装依赖：

```bash
python3 -m pip install -r backend/requirements-dev.txt
```

开发模式的桌面客户端在“新建服务端”时临时启动 `app.server`，并传入 SQLite 数据目录、实例名称和端口。安装版会复制打包后的服务程序到系统数据目录，注册 Windows 服务或 macOS LaunchDaemon；服务独立于桌面窗口和登录会话。单独调试服务时，可在仓库根目录运行：

```bash
cd backend
python3 -m app.server --data-dir /tmp/nexora-dev-data --name '开发服务端' --port 8000
```

正式数据请选持久化目录，不要使用临时目录。服务入口会迁移数据库、生成或复用实例证书，并通过 HTTPS 监听局域网。`GET /api/v1/health` 说明进程和数据库可用；`GET /api/v1/server/info` 提供公开的实例名称、身份、版本和初始化状态。

## 初始化与权限

首页 `POST /api/v1/dashboard/query` 从现有 ORM 模型生成单事务只读快照，只接受近 7/30 天。金额沿用 `finance.view`，销售数量沿用 `sales.view`，采购/库存沿用 `inventory.view`，生产数量沿用 `production.view`；未授权领域不查询并返回 null。UTC 日期、逐行金额、退货/冲销、缺价和当前待办口径见 [首页统计规则](../docs/home-statistics.md)。

只有来自本机环回地址的请求可调用 `POST /api/v1/setup/admin` 创建首位管理员。管理员密码至少 12 位。服务端已有用户时，该接口返回冲突；局域网设备不能抢注管理员。内置管理员、采购员、销售员、仓库员、查看员、财务员、生产计划员七种角色，权限在后端逐项校验。

管理员可通过 `/api/v1/users` 创建用户、调整角色，通过 `/api/v1/users/{id}/status` 启用或停用账号，并通过 `/api/v1/users/{id}/reset-password` 重置密码。`permissions` 表保存固定权限代码和可调整的中文名称；旧库升级时会为已有代码补齐名称。数据库升级到第 26 版时，还会将已保存为权限代码或“未命名权限”的已知权限名称补为中文，保留管理员自行修改的名称；服务端升级并重启后桌面端才能读取修正结果。数据库升级到第 27 版时会将模块和单据写入 `permission_groups` 表，并把每个操作权限的所属单据写入 `permissions.group_code`；`GET /api/v1/permissions` 从数据库读取中文名称和父子关系，为每个操作权限返回 `group_path`（模块、单据两级），供桌面端组成“模块 → 单据 → 操作”授权树。模块和单据节点只用于展示与批量勾选，角色实际保存的仍是操作权限代码；例如 `receipt.post` 与 `shipment.post` 可分别授权。采购申请已实现提交、批准和驳回，并通过独立权限校验；其他单据若增加审批，应先实现真实状态流转和服务端 `require(...)` 校验，再通过数据库迁移登记权限代码、中文名称和所属单据。`PUT /api/v1/permissions/{code}/label` 只修改已有权限的中文展示名称，要求 `users.manage`，不改变服务端授权代码或已分配的角色权限。新增可执行权限仍须由服务端实现并在迁移中登记，不能通过改名或客户端输入创造授权能力。`/api/v1/roles` 可创建自定义角色，`/api/v1/roles/{code}` 可修改其授权范围。桌面端“用户管理”负责账号与角色分配，“权限管理”负责自定义角色、角色授权与权限名称维护；新建角色的内部代码由桌面端自动生成。内置角色只读，最后一位启用的内置管理员不可停用或撤权。账号停用、管理员重置密码以及用户自行调用 `/api/v1/auth/change-password` 后，相关旧会话立即失效。角色和权限变化对现有会话立即生效。

物料、供应商和客户资料、采购申请与订单、分批收货及待入库确认、采购退货待出库确认、其他入出库、多仓库存、调拨、盘点、独立调整、库存台账与基础报表已实现。销售与生产原有单据继续使用。确认入库、出库、退货、调拨或有差异的盘点会在单个事务中生成库存流水；重复确认返回冲突。所有数据由服务端 SQLite 保存，远程客户端没有离线副本或自动同步。

## 实例级单据编号

数据库第 88 版为 29 类主单增加只读 `document_no`，并增加 `document_numbering_settings` 与 `document_number_sequences`。`app/core/document_types.py` 维护前缀白名单，`document_numbering.py` 提供时区换算与 ORM 同事务流水，`document_responses.py` 在已授权响应补充主单和来源编号；不改变历史快照或财务指纹。`app/service/document_numbering.py` 提供认证后的配置 GET 和管理员 PUT，并在全局依赖拒绝未配置的业务写入。升级后须由管理员选择规则再补号，启动不自动选择风格。

指定时区依赖 `tzdata` 并通过 PyInstaller 收集完整包，以统一 Windows、macOS 与独立服务的 IANA 数据。本机模式仍读取系统当前时区。详见 [编号规则、接口和升级边界](../docs/document-numbering.md)。

## 单据统一审批（实施中）

第 89 版迁移新增按单据类型保存的审批模板、模板变更、审批实例、追加事件与作者记录，默认一位独立批准人员，最多五步。模板读取接口为 `GET /api/v1/system/document-approvals` 和 `GET /{document_type}`；管理员通过 `PUT /{document_type}` 提交 `version`、`steps: [{name, role}]`。服务端固定审核权限，非法输入返回 422，非管理员修改返回 403，过期版本返回 409。模板变更仅影响下一次送审。

`app/core/document_approval.py` 提供共用事务服务，送审固定内容与模板，版本递增，建单/编辑/送审人员不能审核本单，各步骤由不同人员完成；执行核对批准内容，事件与业务事务共同回滚。模板和审批历史使用 ORM，审计记录禁止更新和删除。迁移不重写历史单据、金额、数量、单号或批次证据。

其他入库已接入 `GET /api/v1/system/document-approvals/WarehouseInbound/{id}` 和 `POST /{id}/submit|approve|reject|withdraw`，携带 `version`、`intent: execute|reverse` 及意见或冲销原因。查看、建单送审、独立审核、冲销送审分别沿用 `other_inbound.view`、`other_inbound.create`、`other_inbound.review`、`other_inbound.reverse`。普通确认和可选实物批次均须完成全部步骤，确认与审批执行事件在同一库存事务内提交；冲销单独审批固定原因，原批准不可复用。旧客户端直接确认未批准草稿返回 409。历史已执行单据保留原记录。

**当前处于需求分支开发阶段，其余业务入口尚未全部接入；不能据此认为原确认接口已全部实施新审批门槛。** 财务草稿状态、自动转单门槛、生产关联查询和可选批次仍待实施，详见 [实施与验收清单](../docs/document-approval-and-links.md)。

## 基础资料与供货关系

第 86 版增加供应商联系及结算资料，旧资料默认空值并保留编号、关系、版本和历史审计。`app/catalog/supplier_profiles.py` 维护完善状态及物料保存时的原子绑定；物料编辑可搜索已有供应商或从新名称创建待完善档案，联系人、电话、地址补齐后自动变为已完善。取消表单不创建，失败整体回滚；单独绑定也递增物料版本。字段、兼容与冲突规则见 [物料管理规则](../docs/material-catalog.md#供应商绑定与待完善档案)。客户端和服务端须同步升级。

第 87 版新增独立单位目录和变更表。`app/catalog/units.py` 提供 `GET/POST /api/v1/material-units`、`GET/PUT /api/v1/material-units/{id}` 与 `GET /api/v1/material-units/{id}/changes`；读取要求 `inventory.view`，写入要求 `catalog.manage`。编辑携带版本与原因；已引用名称不能修改，停用单位只允许原物料继续保留。升级收录原单位并预置常用单位，不改历史物料和数量；旧物料 API 仍可仅提交单位文字，新桌面提交目录编号核对，详见[单位兼容规则](../docs/material-catalog.md#升级与兼容边界)。

仓库提供 [50 条物料演示数据及本机导入工具](../scripts/demo/README.md)，覆盖电子、五金、塑料、包装与辅料。工具须在服务升级后显式指定目标实例、现有管理员和备份路径；整批 ORM 写入并记录审计，重复导入跳过已有示例档案，不在启动时自动生成数据。

客户关系与报价使用第 50 版的六张静态 ORM 模型表，路由及规则位于 `app/sales/crm.py`、`crm_quotes.py`、`crm_rules.py`。第 61 版增加客户负责人、版本和归属变更 ORM 表；第 65 版增加商机可空概率列及按可见客户范围的预测查询 `app/sales/crm_forecast.py`，`app/sales/customer_scope.py` 为 CRM 及销售单据提供统一服务端归属边界。旧客户保持未分配，由管理员凭依据分配；新客户默认归创建账号。提交报价冻结正文、独立审核、客户接受依据和双版本转单，原单与审计在同一事务内更新，详见 [客户关系规则](../docs/customer-relations.md)。第 76 版的 `app/sales/crm_record_attachments.py` 为联系人、跟进和商机提供 ORM 原文留存与追加式撤销；客户归属和 `crm.view` 限定读取，写入另需 `crm.attachment`，停用或终态只读。第 75 版的 `app/sales/crm_quote_attachments.py` 通过 ORM 留存报价附件原文、摘要、上传依据及追加式撤销；查看遵循客户归属和 `crm.view`，写入另需 `crm_quote.attachment`，取消或转单后只读。PDF、PNG、JPEG 单文件最多 5 MiB，每张报价最多 10 个有效附件；桌面通过受限 IPC 选择和保存文件。`app/sales/crm_quote_pdf.py` 使用只读 ORM 快照和随服务打包的 OFL 中文字体导出已批准或已转单报价；桌面固定 IPC 保存，不自动发送。CRM 联系信息要求独立 `crm.view` 权限，报价转销售草稿同时要求 `crm_quote.convert` 和 `sales_order.create`；转单不改变库存或财务金额。

客户新增前可通过 `POST /api/v1/customers/duplicate-candidates` 查询当前账号可见范围内的相似名称；候选来自客户 ORM 模型，仅读取并提示，不自动合并或阻止用户确认后的新增。接口要求 `customer.manage`，细则见 [客户关系规则](../docs/customer-relations.md)。

客户 CSV 导入的预检和提交路由位于 `app/sales/customer_import.py`，共享 `app/sales/customer_names.py` 的保守名称匹配规则。预检只显示账号可见候选，提交在单个 ORM 写事务内重核并创建客户及负责人审计；现只接受单列客户名称，详见 [客户关系规则](../docs/customer-relations.md)。

联系人 CSV 导入的预检和提交路由位于 `app/sales/contact_import.py`，通过现有 CRM 归属边界检查客户，用 ORM 模型在同一事务中建立联系人和逐条变更审计。导入只建立启用联系人，发现同客户同名时要求显式确认；列格式和限制见 [客户关系规则](../docs/customer-relations.md)。

商机 CSV 导入的预检和提交路由位于 `app/sales/opportunity_import.py`，使用 ORM 会话检查客户归属、启用负责人及客户联系人，并在同一写事务中建立初步接洽商机和逐条审计。同客户同名商机须显式确认；预估金额不生成销售单、收入或总账记录。列格式和限制见 [客户关系规则](../docs/customer-relations.md)。

物料、供应商、仓库分别通过 `/materials`、`/suppliers`、`/warehouses`（统一前缀 `/api/v1`）提供 GET 列表、POST 新增、PUT `/{id}` 修改和 DELETE `/{id}` 删除。查看要求 `inventory.view`，物料和供应商写入要求 `catalog.manage`，仓库写入要求 `warehouse.manage`。重复编码或名称冲突返回 409，记录不存在返回 404；被业务单据或库存引用的记录不能删除，默认 1 号主仓库也不能删除。修改名称会反映在引用该档案的历史查询中；物料资料有编辑版本与前后审计，供应商和仓库第 62 版增加版本、修改原因及新增/修改/删除的 ORM 审计，详见 [档案版本审计](../docs/master-data-audit.md)。

数据库第 28 版新增 `supplier_materials` 多对多关联表。GET `/supplier-materials` 返回供应商与物料编号；PUT `/suppliers/{supplier_id}/materials/{material_id}` 幂等绑定，DELETE 同路径解绑，写入要求 `catalog.manage`。同一物料可绑定多个供应商，供应商也可绑定多个物料；解绑不删除物料、不改动库存和采购记录。删除未被业务引用的资料会清理其绑定关系；删除失败时关系与资料一并回滚。不同规格使用不同物料编码维护，可在名称中填写规格型号。

桌面基础资料分为物料管理、供应商管理、仓库管理，支持列表搜索。供货关系用于供应商页检索和维护，目前不限制采购选料，不自动补全采购单，不记录报价或推算历史采购价格。客户端与服务端需一起升级，服务端重启时执行数据库迁移。

## 采购申请与采购订单

第 84 版起，`POST /api/v1/equipment/jobs/{id}/purchase-requests` 可从已批准或执行中的维护工单建立备件采购申请草稿，使用 `equipment.view` 和采购申请查看、创建权限。申请明细受工单计划耗材与未取消申请累计数量约束，采购页不能直接修订该来源申请；取消后可从工单重建。工单详情可追溯申请、订单、收货及仓库入库状态，实际采购仍走既有审批、转单和入库流程。规则见 [设备维护](../docs/equipment-maintenance.md)。

数据库第 29 版新增采购申请、申请明细和订单明细来源关联。`GET /api/v1/purchase-requests` 查询申请及每行已转、待转数量；`POST /purchase-requests` 建草稿，`PUT /purchase-requests/{id}` 修改草稿或驳回后的申请，`/submit` 提交审批，`/approve` 与 `/reject` 由有审批权限的人处理，驳回必须填写原因，`/cancel` 取消尚未被有效订单使用的申请。修改驳回申请会恢复为草稿，需重新提交。查看、建改、提交、审批、取消分别要求 `purchase_request.view`、`purchase_request.create`、`purchase_request.submit`、`purchase_request.review`、`purchase_request.cancel`；管理员默认可全部操作，采购员和仓库员默认可查看、建改、提交及取消，审批权限默认仅管理员拥有，也可授予自定义角色。审批不要求与建单人不同。

`POST /api/v1/purchase-orders` 可选传 `purchase_request_id`，并为每条明细传 `purchase_request_line_id`。服务端在写事务内校验申请已批准、物料匹配以及数量不超过待转量；未取消的订单草稿也占用申请额度，取消订单后释放。每张订单只关联一张申请，同一申请可按明细和数量拆成多张订单、分别选择供应商；不关联申请的直接采购继续可用。旧订单保留原样，不推断申请来源。申请和订单本身均不改变库存或应付。

`POST /api/v1/purchase-orders` 创建含供应商、物料、数量与单价的草稿；`POST /api/v1/purchase-orders/{id}/confirm` 确认后才能关联入库单；未入库的订单可调用 `/cancel` 取消。`GET /api/v1/purchase-orders` 返回订单金额、每行已入库与剩余数量。金额按每行数量乘单价后四舍五入到分；当前只按人民币展示。创建、确认和取消分别需要 `purchase_order.create`、`purchase_order.confirm`、`purchase_order.cancel` 权限。

数据库第 30 版新增采购收货单。`POST /api/v1/purchase-goods-receipts` 从已确认或部分入库的订单建立草稿，逐行记录合格实收、拒收数量与拒收原因；`GET` 查询单据，`/{id}/confirm` 确认收货，`/{id}/cancel` 取消草稿。确认时在同一写事务内重核订单剩余量及其他已确认收货生成的待入库数量；合格数量自动生成唯一的采购入库草稿，仓库再调用现有 `/receipts/{id}/post` 确认实物入库。全数拒收仅保留收货记录，不生成空入库单；拒收数量不占用订单余量。确认收货不增加库存或应付，入库确认后才增加；重复确认及并发超量返回 409。查看、创建、确认、取消分别要求 `purchase_receiving.view`、`purchase_receiving.create`、`purchase_receiving.confirm`、`purchase_receiving.cancel`；管理员与仓库员默认可确认，采购员默认可建单及取消。旧 `/receipts` 直接建单接口继续供旧客户端使用，桌面采购流程改从采购收货进入。

新入库单可选填 `purchase_order_id`。服务端核对供应商、物料及剩余数量，确认入库时在同一写事务内重新核算并更新订单为“部分入库”或“全部入库”，防止多个草稿使订单超量。旧入库单没有采购订单关联，仍可正常确认。已入库订单不可取消。管理员可用 `POST /api/v1/receipts/{id}/reverse` 填写原因，一次性冲销误确认入库：原仓库存须足够，所有已确认采购退货必须先冲销；随后追加关联原入库明细的负库存与负应付来源，订单已入库数量和状态按有效入库重新计算。原单和原流水保留，重复冲销返回 409；已冲销入库不可再创建或确认采购退货。历史无价入库的原应付及冲销仍显示未知金额。

`POST /api/v1/purchase-returns` 创建采购退货草稿，指定已确认的原入库单、入库明细、数量和原因。`GET /api/v1/purchase-returns` 查看记录；`POST /api/v1/purchase-returns/{id}/post` 确认退货，`/cancel` 取消草稿。服务端在建单和确认时核对累计未冲销的可退量；确认时在同一写事务内核对原入库仓库余额并写入负向库存流水。若货物已调走，须先调回原仓库。管理员可用 `POST /api/v1/purchase-returns/{id}/reverse` 填写原因，一次性追加回到原仓的正库存和正应付更正；重复冲销返回 409，原退货与原流水保留，可退数量和净入库恢复。关联采购订单时金额沿用原单价；历史自由入库无单价，原退货及冲销金额均保持未知。实际退款需在财务页另行登记。采购员可创建及取消草稿，仓库员可创建、确认及取消，管理员可执行全部操作。

## 应收应付来源

库存金额基础接口为 `GET /api/v1/inventory/valuation`，按同一公司全部仓库的物料流水顺序重放移动加权平均。关联采购订单的入库沿用订单单价；通常出库按发生时平均成本，生产退料冲销按原退料单价配对以保留更正金额；销售退货、生产退料和调拨入库沿用原出库成本。没有价格依据的正向流水会显示“待核价”，现存数量含未知成本时该物料及总库存金额均为 `null`，不会把未知金额当作零。`GET /api/v1/inventory/valuation/inputs` 可查全部人工核价修订；`POST /api/v1/inventory/valuation/inputs` 对允许人工核价的正向流水登记单价、依据编号和原因，后续修订追加记录并重算金额。查看和登记分别需要 `inventory_valuation.view`、`inventory_valuation.record`，默认授予管理员和财务员。未结期间修订可能改变已展示的历史成本；已结边界内的核价和完工分摊受锁定保护，见 [期间结账规则](../docs/period-closing.md)；已结算完工批次采用结算分摊金额；已被有效结算使用的核价来源禁止修订，须先冲销关联结算。业务来源凭证已提供采购价差及销售成本分录，详见 [业务凭证规则](../docs/business-journals.md)；完整成本价差分摊仍待实现。

`GET /api/v1/finance/receivables-payables` 逐行列出已确认销售出库形成的应收、采购入库形成的应付及销售、采购退货形成的负向调整。每笔记录包含往来单位、订单、来源单据与明细、物料、数量、原单价、确认人和确认时间。金额按每行数量乘原单价四舍五入到分，币种暂固定为人民币。草稿与取消单不产生金额；升级前的已确认单据同样从原记录推导，无需改写历史。没有采购订单单价的入库及其退货标记为待核价，不计入已知应付总额。此接口需要 `finance.view`，仅内置管理员和财务员默认拥有；其他角色需管理员显式授权。当前合计是业务净额；订单级收付款和未结金额由下述独立记录计算，税费和自动转总账尚未实现。

`GET /api/v1/finance/overview` 在同一读取事务中返回金额来源、订单余额、收付款记录和订单间核销，供桌面工作台显示。`GET /api/v1/finance/accounts` 也可单独按已发生业务的订单查询业务净额、收付款净额、未结金额和来源行编号；负未结额表示需退款的贷方余额。`GET /api/v1/finance/payment-records` 返回全部手工收付款与冲销记录。`POST /api/v1/finance/payment-records` 以 `kind`（`receivable` 或 `payable`）、`order_id`、`action`（`settlement` 收款/付款或 `refund` 退款）、正金额、外部 `reference` 和可选 `note` 登记。金额最多两位小数，不得超过当前订单未结金额或贷方余额；写事务同时核对余额，防止并行超额。同一订单、类别和动作的参考号不得重复。`POST /api/v1/finance/payment-records/{id}/reverse` 以原因新增等额反向记录；原记录保留，且只能冲销一次。查看需要 `finance.view`，登记和冲销分别需要 `finance.record`、`finance.reverse`；管理员和财务员默认拥有。系统仅记录人工录入的资金事实，不连接银行，也不自动证明资金已到账；无采购订单单价的旧入库目前无法在系统内登记对应付款，需后续补价流程。

第 85 版增加现有订单间贷方核销：`GET/POST /api/v1/finance/order-settlements` 查看、登记，`POST /{id}/reverse` 追加撤销；余额和权限规则见 [订单间贷方核销](../docs/order-settlements.md)。仅在同一客户或供应商的订单间转移分户贷方，不产生第二笔收付款。

## 生产 BOM

`POST /api/v1/boms` 创建成品物料的 BOM 草稿，记录基准产出数量、组件物料及基准用量；同一物料不能重复作为组件，也不能直接作为自身组件。服务端在写事务中按成品分配递增版本号。`GET /api/v1/boms` 返回含物料名称的全部历史版本；`POST /api/v1/boms/{id}/activate` 启用草稿，`/retire` 停用启用版本，`/cancel` 取消草稿。每个成品只允许一个启用版本，启用时检查其他启用 BOM 的组件链，阻止循环引用。停用和取消后的内容保留审计；修订需新建版本，不能改写历史。查看、创建、启用、停用和取消分别要求 `production.view`、`bom.create`、`bom.activate`、`bom.retire`、`bom.cancel`。管理员和生产计划员可管理，仓库员可查看。BOM 不影响库存。

## 生产工单

`POST /api/v1/work-orders` 使用启用的 BOM、目标报工数量及目标仓库创建草稿。服务端在写事务内固定 BOM 版本引用，并按目标数量与 BOM 基准产量计算每个组件的需求，向上取整到库存的三位精度。`GET /api/v1/work-orders` 返回工单、需料快照、净领料与剩余数量，以及已报工、合格、不合格和待报工数量；`POST /api/v1/work-orders/{id}/release` 下达草稿，BOM 已停用时拒绝下达，须取消草稿并按新版本建单；`/cancel` 可取消未发料的草稿或已下达工单。旧工单在 BOM 换版后仍保留原组件和数量。查看要求 `production.view`，创建、下达、取消分别要求 `work_order.create`、`work_order.release`、`work_order.cancel`；管理员与生产计划员默认拥有，仓库员可查看。工单创建和下达不锁定库存；目标仓库用于合格成品入库。

## 生产领料

`POST /api/v1/material-issues` 对已下达或生产中的工单建立分批领料草稿，指定源仓库及本次工单组件数量；`GET /api/v1/material-issues` 查看全部记录及每条已退、可退数量。`GET /api/v1/material-issues/{id}/available-lots` 以确认权限返回草稿各物料在源仓的可用实物批次；`POST /api/v1/material-issues/{id}/post` 可逐行提交 `lines: [{material_issue_line_id, lots: [{lot_id, quantity}]}]`。写事务重新核对工单剩余需料、源仓库存和批次余额，数量精确守恒后记录负向库存流水与原批次分配，工单进入“生产中”。旧客户端省略批次请求体仍可确认，但留下可见的批次差额。两个草稿可以并存，但后确认的草稿若超出剩余需料或库存会返回 409，整单不扣库存。`/cancel` 仅取消草稿；已确认领料保留原单据及流水；`POST /api/v1/material-issues/{id}/reverse` 要求必填原因，未结期间且没有有效报工、退料、人工核价或成本结算时，按原批次向原仓追加等量正向流水。冲销后不可再给原单或冲销流水补证；全部有效领料归零时工单回到“已下达”。查看要求 `production.view`；创建、确认、取消、冲销分别要求 `material_issue.create`、`material_issue.post`、`material_issue.cancel`、`material_issue.reverse`；冲销默认仅管理员可用。管理员可全部操作；计划员可创建和取消，仓库员可创建、确认和取消。材料金额按领料时库存移动平均成本读取；库存成本未知时可在成本页面人工核价。

## 生产退料更正

`POST /api/v1/material-returns` 指定生产中工单的已确认领料单、退料原因及原领料明细数量建立草稿；`GET /api/v1/material-returns` 查看记录。`GET /api/v1/material-returns/{id}/available-lots` 以确认权限返回原领料行已分配批次及扣除既往已确认退料的剩余可退量；`POST /api/v1/material-returns/{id}/post` 可逐行提交 `lines: [{return_line_id, lots: [{lot_id, quantity, supplier_lot, manufactured_on, expires_on}]}]`。选择原批次时核对归属与可退量；实物无法对应原批次时可登记独立标记的“退料新批次”，不伪造原来源。写事务重新核对累计可退数量和工单状态，向原领料仓库写入正向库存流水和批次分配。旧客户端省略请求体仍可确认，但留下可见差额。工单“已领”和“剩余”按已确认领料减已确认退料计算，退回后可重新领用；已用于确认报工的最低组件数量不能退回。多张草稿可以并存，但后确认的草稿若超量会返回 409，整单不入库。`/cancel` 仅取消草稿，已确认退料保留记录；已确认退料可通过 `POST /api/v1/material-returns/{id}/reverse` 提交必填原因整单冲销：仅生产中、未结算且无有效报工的工单允许；原退料及批次证据保留，追加原仓负向库存流水，原批次或现场补证批次足额且工单不因后续补领而超领时生效。原单与冲销流水的补证随后锁定。查看要求 `production.view`；创建、确认、取消、冲销分别要求 `material_return.create`、`material_return.post`、`material_return.cancel`、`material_return.reverse`；冲销默认仅管理员可用。管理员可全部操作；计划员可创建和取消，仓库员可创建、确认和取消。退料由操作员按实际退回事实登记，当前不含生产现场实物核验。

## 完工报工与基础质检

`POST /api/v1/production-completions` 为生产中的工单建立分批报工草稿，保存本批报工数量及可选参考号；`GET /api/v1/production-completions` 查看记录。`POST /api/v1/production-completions/{id}/inspect` 由有质检权限的操作员填写合格数量及质检说明，不合格数量由报工数减合格数计算。`/post` 仅确认已质检单据，在同一写事务中核对累计已确认报工不超过工单目标，并按累计报工数量核对每个组件的净领料是否达到 BOM 快照比例；仅合格品生成进入工单目标仓库的正向库存流水，可选提交 `lots: [{quantity, manufactured_on, expires_on}]` 固定合格品实物批次，数量之和须等于合格数量。整批不合格不产生库存流水或实物批次；旧客户端省略批次请求体仍按原行为确认，差额在批次核对页可见。全部目标报工确认后工单变为“已完工”。两个草稿可并存，但后确认的草稿若超出目标会返回 409。`/cancel` 可取消草稿或已质检但未入库的单据，已确认入库不能直接取消。查看要求 `production.view`；创建、质检、确认、取消分别要求 `production_completion.create`、`production_completion.inspect`、`production_completion.post`、`production_completion.cancel`。管理员有全部权限；计划员可创建和取消，仓库员可质检与确认。目标为报工总数，包含质检不合格数；不合格品不进入可用库存，不合格品处置与返工的基础规则见 [不合格品规则](../docs/quality-rework.md)；完工成本结算仍按工单来源和金额分配，与实物批次区分。这是记录数量与说明的基础质检，没有批次检验标准或现场实物核验。

`POST /api/v1/production-completions/{id}/reverse` 仅管理员可按原因冲销已确认完工单。服务端在一个写事务内检查目标仓库仍有足量合格成品，新增独立冲销记录；合格数量大于零时追加负向库存流水，已登记实物批次按原分配反向扣回，批次已被耗用则返回 409 并整单回滚；原报工、质检和入库流水不被改写。冲销后的报工、合格和不合格数量不再计入工单当前累计；若工单原已完工，则恢复“生产中”并允许重新报工。库存不足或重复冲销返回 409。原单查询会展示冲销原因、操作人和时间；当前不支持部分冲销；工单成本可在独立归集页面查询。

## 生产成本归集

`GET /api/v1/production-costs` 返回每个工单的材料已知金额、人工、制造费用、待核价领料条数和有效成本记录；任何净领料既没有库存成本也缺少有效人工核定单价时，`total_amount` 为 `null`，不会把未知成本当成零。`POST /api/v1/production-costs/material-valuations` 为一条已确认领料明细登记人工核定单价、依据编号和可选说明；每条明细只能有一个有效核价。材料金额按该明细已领减已退数量乘核定单价计算，并按人民币分位四舍五入。`POST /api/v1/production-costs/charges` 为已下达、生产中或已完工工单登记人工或制造费用；`POST /api/v1/production-costs/{id}/reverse` 按原因冲销原成本记录，原记录、依据和操作者保留，库存成本仍未知时，核价冲销后该领料恢复待核价状态，可重新核价。查看要求 `production_cost.view`，登记与冲销分别要求 `production_cost.record`、`production_cost.reverse`；管理员和财务员默认有全部权限，生产计划员默认只可查看。

材料成本优先读取领料流水发生时的库存移动平均单价，只有库存成本未知时允许人工领料核价。报告新增 `material_sources`，逐行返回净领数量、采用单价、金额、库存流水和人工成本记录编号；`entries[].included_in_current_cost` 表示人工记录是否用于当前成本。已结算工单的汇总与材料来源展示结算时快照。未完工工单显示截至当前的归集金额。

数据库第 39 版增加成本结算、分摊、来源依赖和独立冲销表。GET `/api/v1/production-costs/settlements` 查看历史；POST 同路径传入 `work_order_id`、`reference`、可选 `note`，仅可结算全部报工、无未处理草稿且净领料全部核价的工单。成本按合格入库数量累计比例分摊到各完工批次，以分为单位处理尾差；没有合格成品时拒绝结算。完工入库在库存计价中返回 `cost_source: production_settlement` 与 `settlement_id`，内部分摊金额不由四位展示单价倒算。POST `/{id}/reverse` 按原因冲销结算，原快照保留；有关联后续有效工单结算时拒绝冲销。结算冻结该工单费用、完工来源和有关核价依赖，先冲销后才能更正。结算、冲销分别要求 `production_cost.settle`、`production_cost.reopen`，默认授予管理员和财务员；查看沿用 `production_cost.view`。成本规则与边界见 [完工成本规则](../docs/production-cost-settlement.md)。

现有业务接口的数据读写均已使用 SQLAlchemy 2.0 声明式模型，包括账号权限、基础资料、采购、销售、仓库、库存计价、生产和成本结算、业务财务及报表；服务启动和备份身份核对也通过 ORM。本版使用 192 张静态模型表及第 89 版数据库，不通过运行时反射或 `create_all` 替换历史迁移。金额和数量继续用 Decimal 计算并以文本精确保存；一致读快照、写锁、提交、回滚和连接释放由统一会话处理。跨模块转单、数量额度、库存流水与审计在同一写事务中完成，异常后整体回滚，重复或超量操作仍返回冲突。备份身份检查独立只读打开指定文件并释放句柄；SQLite 结构迁移、连接设置、在线备份和完整性诊断保留必要的底层操作。转换范围及验证见 [ORM 迁移清单](../docs/backend-orm-migration.md)。供应商和仓库档案接口因版本审计新增字段，客户端与服务端需同时升级。

## 多仓库库存与调拨

数据库第 31 版新增 `/api/v1/warehouse-inbounds` 其他入库单，适用于期初补录、赠品及有明确说明的其他非采购来源。单据保存仓库、用途、说明、参考号和物料数量；`/post` 确认后在同一事务写入正向库存流水，可提交逐行实物批次分配，见下文；`/cancel` 仅取消草稿，管理员可用 `/reverse` 填写原因并在原仓库存充足时追加负向冲销流水，已登记批次时按原分配逐批扣回。重复确认、重复冲销和库存不足返回 409，原单及原流水留存。其他入库不生成采购应付。查看、创建、确认、取消、冲销分别要求 `other_inbound.view`、`other_inbound.create`、`other_inbound.post`、`other_inbound.cancel`、`other_inbound.reverse`；管理员和仓库员默认可处理草稿，冲销默认仅管理员可做。

数据库升级时自动建立 `MAIN` 主仓库，旧入库单和历史流水归入主仓库。新入库单可指定 `warehouse_id`；旧客户端省略时仍入主仓库。`GET /api/v1/warehouses` 查看仓库，`POST /api/v1/warehouses` 创建仓库。`GET /api/v1/stock` 返回所有仓库合计，添加 `warehouse_id` 查询参数可查看指定仓库；`GET /api/v1/movements` 返回带仓库、单据来源和操作者的有符号流水。

`POST /api/v1/transfers` 创建调拨草稿，`GET /api/v1/transfers/{id}/available-lots` 沿用 `transfer.post` 返回来源仓可用实物批次；`POST /api/v1/transfers/{id}/post` 可提交 `lines: [{transfer_line_id, lots: [{lot_id, quantity}]}]`，逐行核对数量后在同一 ORM 写事务中将原批次从来源仓转到目标仓，并生成等额双向库存流水。旧客户端省略批次请求体仍可确认，但两仓未分配数量会显示为批次差额。库存或批次不足、重复确认均返回 409。`POST /api/v1/transfers/{id}/reverse` 由管理员按原因一次性冲销已确认调拨；目标仓原批次仍足量时，两侧沿原分配反向移动。原目标仓库存或批次不足、重复冲销返回 409 并整单回滚；原单与原流水不改写。仓库管理、调拨创建、确认和冲销分别要求 `warehouse.manage`、`transfer.create`、`transfer.post`、`transfer.reverse` 权限；查看仍要求 `inventory.view`。

`POST /api/v1/stocktakes` 创建盘点草稿，保存指定仓库各物料的账面快照与实盘量；`GET /api/v1/stocktakes` 查看历史，`POST /api/v1/stocktakes/{id}/post` 确认差异，`/cancel` 取消草稿。确认时在写事务内重新核对账面量及最后一笔流水；若期间发生入库、出库或调拨，即使余额相抵未变也返回 409，须取消旧草稿并重新盘点。非零差异生成带盘点单、明细和操作者来源的有符号库存流水；零差异不生成流水。已确认盘点不可取消；`POST /api/v1/stocktakes/{id}/reverse` 由管理员填写原因后一次性冲销，原盘点及流水不改写，非零差异另记反向流水并关联冲销单与原明细。盘盈差异已被消耗、当前库存不足时返回 409，整单不冲销；零差异冲销保留原因但不生成流水。创建、确认、取消分别要求 `stocktake.create`、`stocktake.post`、`stocktake.cancel`，冲销要求 `stocktake.reverse`，查看要求 `inventory.view`。

## 销售订单、出库与退货

`POST /api/v1/customers` 创建客户资料，`GET /api/v1/customers` 查询。`POST /api/v1/sales-orders` 创建包含客户、物料、数量及单价的草稿；每条明细还可成对填写 `warranty_days`（1～36500）和 `warranty_basis`（合同或承诺依据），否则两项均留空。`/confirm` 确认后才能出库，未出库订单可调用 `/cancel` 取消。`GET /api/v1/sales-orders` 返回金额、每行已出库及剩余数量以及保修条款。第 79 版迁移给旧订单明细保留空白条款；对应出库创建售后时服务端自动带入，拒绝售后覆盖已登记的原订单条款。金额按每行数量乘单价后四舍五入到分，目前仅按人民币展示；税费和折扣尚未计入。应收在确认出库时形成，并随退货或冲销记录调整。

第 81 版提供 `GET/POST /api/v1/sales-orders/{id}/contract`，按客户可见范围读取与追加合同全文版本；写入须有 `sales_order.confirm` 及 `sales.view`，并提供当前版本、正文、客户确认依据和原因。历史保留，取消订单禁止新登记；正文不自动变更订单价格、保修条款或已形成的售后证据。第 82 版另提供按合同正文版本留存、下载及追加撤销的原件附件，沿用订单权限与客户范围，见[销售合同规则](../docs/sales-contracts.md)。

`POST /api/v1/shipments` 从已确认订单创建出库草稿并指定仓库；`POST /api/v1/shipments/{id}/post` 确认出库，`/cancel` 取消草稿。确认时在同一写事务内重新核对订单剩余量与仓库库存，写入带订单、出库单明细和操作者来源的负库存流水，并更新订单为部分或全部出库。库存不足、超量、重复确认返回 409。已出库不可取消。管理员可用 `POST /api/v1/shipments/{id}/reverse` 提交冲销原因，一次性在原出库仓追加正库存流水、负应收来源，并按有效出库量恢复订单状态与可出库数量。存在未冲销的已确认销售退货时须先冲销退货；已冲销出库不能再次冲销或新建、确认关联退货。原出库及流水保留，已收款时财务余额可能变为待退款，实际退款须另行登记。销售单据查看要求 `sales.view`，客户管理要求 `customer.manage`；销售订单创建、确认、取消和出库单创建、确认、取消分别由 `sales_order.*`、`shipment.*` 权限控制，冲销要求 `shipment.reverse`。销售员可创建订单和出库草稿，仓库员可确认出库，管理员可执行全部操作。

`POST /api/v1/sales-returns` 创建退货草稿，必须指定已确认的原出库单、该单的出库明细及数量、退回仓库与原因。`GET /api/v1/sales-returns` 查询退货记录；`POST /api/v1/sales-returns/{id}/post` 确认，`/cancel` 取消草稿。创建及确认时均核对原出库数量减去未冲销的已确认退货数量；确认在一个写事务中写入正向库存流水，两个并行草稿无法累计退超。管理员可用 `POST /api/v1/sales-returns/{id}/reverse` 提交冲销原因，在退回仓库存足够时一次性追加负库存流水和正应收更正来源；同一退货只可冲销一次，原单、原库存流水和原应收来源保留，可退数量恢复。实际退款需在财务页另行登记。销售员可创建及取消草稿，仓库员可创建、确认及取消，管理员可执行全部操作。

售后第 80 版新增 `POST /api/v1/after-sales/cases/{id}/responsibility`，由持有 `after_sales.review` 与查看权限且未参与本单编制的人员，对已提交且未取消或冲销的售后单人工登记 `outcome`（`company`、`customer`、`third_party`、`undetermined`）、`basis`、`reason` 与当前整数版本。每次更正追加一条 `AfterSalesResponsibility` ORM 记录并增加售后版本；读取售后证据返回最新核定及完整历史。已结期间限制历史核定。该结果不自动更改保修期限、方案审批、收费、库存或财务来源；业务规则见 [售后规则](../docs/after-sales.md)。

## 数据与证书

数据库路径由桌面程序设置为所选数据目录下的 `nexora.db`。独立运行或测试时可以用 `NEXORA_DB_PATH` 指定完整路径。服务端身份随数据库保存；证书和私钥位于相同数据目录的 `server.crt`、`server.key`。如果证书与数据库实例不匹配，服务拒绝启动。备份和恢复时应把整个目录作为一组保留。

服务端证书为每个实例独立生成的自签名证书。客户端首次连接时应通过服务端电脑或其他可信渠道核对 SHA-256 指纹；此后客户端固定该证书。当前设计只供单家公司内部局域网使用，不开放公网连接。

服务进程自行发布 `_nexora._tcp` 局域网发现记录；桌面窗口不承担广播。网卡尚未就绪或地址变化时会重试。客户端优先核验与当前非环回网卡同网段的广播地址，失败后再尝试其他局域网 IPv4 地址；只显示证书和实例身份一致且可连接的服务。这样可避免把可达的虚拟环回地址优先保存为常用连接。广播受网络隔离或防火墙限制时，仍可用局域网 IP 与端口手动连接，并照常核对证书指纹。

## 固定主机管理与升级

安装版的桌面设置提供系统服务状态、手动启停和使用当前安装包升级的入口。首次安装和手动启停需要操作系统管理员授权。服务配置位于 Windows `%PROGRAMDATA%\Nexora ERP\host.json` 或 macOS `/Library/Application Support/Nexora ERP/host.json`；其中不保存管理员账号密码。Windows 安装时会给 LocalSystem 授予所选实例数据目录及现有文件的访问权限，同时保留该目录原有的访问规则，以便服务在用户退出后继续使用数据库和证书。无控制台服务的运行日志写入同一系统目录的 `logs/host.out.log`，启动异常写入 `logs/host.err.log`；两者仅允许系统账户与管理员访问。旧版由 Electron 持有的主机在下一次点击“启动本机服务”时迁移到系统服务，并沿用原数据目录及证书。

升级先停服务，在上述系统目录的 `backups/` 中生成数据库与证书的成组备份，然后替换程序；程序替换或重新启动失败会恢复上一份程序。Windows 服务报告停止后，旧进程或扫描程序仍可能短暂占用程序目录；升级的目录替换仅对 Windows 的占用/访问错误等待最多 10 秒，不删除被占用目录、不放宽权限，持续失败保留原错误并按既有流程恢复旧服务。macOS 安装和升级会在 `launchctl bootstrap` 后短暂核验服务进程持续运行；若新版立即退出，先卸载新版作业再恢复旧程序并重新注册。该检查不能代替应用层连接与实机重启验收。若新版已经变更数据库结构，程序回退后可能还需使用升级前备份恢复数据库。恢复应先停止服务，再使用下面的 `restore` 命令恢复到新的目录，核验实例与证书后把 `host.json` 的 `data_dir` 指向新目录，再启动服务。请保留原目录作为额外回退点。Windows 和 macOS 的开机及升级流程仍需真实设备验收。

## 备份与恢复

从仓库根目录运行以下命令；打包后的 `nexora-server` 可直接使用相同的 `backup`、`restore` 子命令：

```bash
PYTHONPATH=backend python3 -m app.backup backup --data-dir /path/to/instance --output /path/to/instance.nexora-backup
PYTHONPATH=backend python3 -m app.backup restore --archive /path/to/instance.nexora-backup --data-dir /path/to/new-instance
```

备份使用 SQLite 在线快照，并把数据库、证书和私钥放在同一归档中；归档含敏感业务数据及私钥，应存放在受控位置。恢复会校验哈希、数据库完整性和证书身份，只写入尚不存在的新目录，不覆盖运行中的原实例。恢复后还需让服务端配置指向新目录，并在启动前确认旧服务已停止。

## 测试

从仓库根目录运行：

```bash
PYTHONPATH=backend python3 -m pytest backend/tests -q
```

测试覆盖身份持久化、远程首次管理员抢注拒绝、角色越权拒绝、账号停用与会话失效、自定义角色授权、最后管理员保护、旧数据库迁移、采购订单分批入库与超量拦截、采购退货累计数量与库存不足回滚、销售订单分批出库与库存不足拦截、销售退货累计数量与权限、应收应付来源和角色授权、收付款限额与冲销及退货退款、BOM 版本与循环引用、工单需料快照与下达状态、领料超量及库存不足回滚、退料累计上限及再次领用、分批报工的质检门槛、需料下限与成品入库来源、完工冲销、生产成本待核价与退料净额及成本冲销、多仓库调拨与库存不足拦截、盘点快照与差异流水、入库只确认一次、库存流水、成组备份恢复、发现广播与系统服务安装升级回退。

另有跨模块测试把采购组件入库、跨仓调拨、生产领料与质检入库、成品销售出库、工单成本及应收应付结清串在同一测试数据库中；这验证接口和库存来源的一致性，不代替真实设备或现场业务数据验收。

数据库第 32 版新增 `/api/v1/warehouse-outbounds`。其他出库草稿记录仓库、用途、原因及明细，`/post` 在仓库余额充足时原子扣减库存；其他用途出库和已提交采购退货可按实物批次逐行指定来源仓正余额，`/{id}/available-lots` 沿用 `other_outbound.post` 返回可选批次，冲销沿原分配回仓；`/cancel` 仅取消草稿，`/reverse` 追加冲销流水。重复操作返回 409，其他出库不产生采购应付。权限为 `other_outbound.view/create/post/cancel/reverse`。

数据库第 33 版将采购退货提交与仓库出库确认分离。`POST /api/v1/purchase-returns/{id}/submit` 创建唯一待出库单并占用原入库可退量；仓库通过 `/api/v1/warehouse-outbounds/{id}/post` 在同一事务重查原入库可退量和原仓余额，可逐行指定批次并固定在退货流水上，确认一次才写一组退货流水、确认退货及应付冲减。取消待出库退货释放占用。旧客户端的退货 `/post` 在同一事务补建并确认关联出库单；迁移仅为历史已确认退货补单据，不重放流水。

`POST /api/v1/inventory-ledger/query` 以仓库、物料、日期和来源筛选库存流水，返回每个仓库物料组合的期初、逐笔累计结余与期末。来源筛选后数量表示该来源范围内的累计变动；库存总览仍展示所有来源的实际余额。

数据库第 34 版新增独立 `/api/v1/stock-adjustments`。草稿必须填写原因及有符号调整量，依次提交、由非建单人批准、仓库确认后才追加增减库存流水；驳回、取消、重复操作和库存不足均不改库存。确认后可填写原因冲销，负向冲销仍须核对当前余额。权限为 `adjustment.view/create/submit/review/cancel/post/reverse`。

数据库第 35 版新增采购报表与库存报表权限。`POST /api/v1/reports/query` 支持 `purchase_requests`、`purchase_orders`、`receiving_returns`、`inventory_balance`、`stock_flow`，按可用的供应商、仓库、物料和日期筛选。响应同时包含列、行和由同一行集生成的带 UTF-8 BOM 的 CSV；日期按单据创建日期或库存流水日期筛选，库存余额按截至日期计算。采购类要求 `purchase_report.view`，库存类要求 `inventory_report.view`。

供应商主列表支持服务端分页搜索：`POST /api/v1/suppliers/query` 接收 `query`、`page`（从 1 开始）与 `page_size`（1–100，默认 20），返回 `items`、筛选后 `total`、有效 `page` 和 `page_size`；查看仍要求 `inventory.view`。总数与分页统一显示在表格底部，可选每页 10/20/50/100 条，搜索回到首页，删除造成的越界页自动回退。查询失败提供重试入口，过期响应不覆盖新结果。原 GET 供应商接口仍供业务选项使用，其他列表及供货物料明细尚未改为服务端分页。客户端与服务端需同时升级。


数据库第 37 版为用户添加 `full_name`（姓名，最多 60 字）、`employee_no`（工号，最多 40 字）和 `phone`（电话，最多 24 字）。旧账号默认空值；工号允许英文、数字、下划线及短横线，非空工号忽略大小写保持唯一。电话可为空或填写数字、国际区号及常见分隔符。创建用户时可填写资料，`PUT /api/v1/users/{id}` 在一个事务中更新资料与角色，沿用 `users.manage` 授权和最后管理员保护，失败不部分保存；变更前后快照及操作者写入 `user_profile_changes`，不含密码。用户查询和登录响应一并返回资料。客户端、服务端需同步升级。

## 导航图标管理

数据库第 38 版新增 `menu_icons` 和 `menu_icon_changes`，记录共享图标配置、版本与操作者。`GET /api/v1/menu-icons` 对已登录用户开放，供侧栏读取；`PUT /api/v1/menu-icons` 要求 `users.manage`，接收 `key`、`icon`、`version`。仅接受固定菜单键与内置图标，`icon: null` 恢复默认；首次保存版本为 0，成功后递增，过期版本返回 409，避免覆盖其他管理员修改。配置只影响图标，不改变名称、路由或授权。

客户端与服务端需一同升级。当前客户端保存成功后立即更新侧栏；其他客户端重新登录或刷新数据后读取新配置，不提供实时推送。菜单管理支持独立重新加载，读取失败时禁用编辑；冲突后关闭编辑器并重新加载即可取得最新版本。

## 总账基础资料

数据库第 40 版新增科目与会计期间基础资料及变更记录。接口放在 `app/finance/ledger.py`，桌面提供独立页面；管理员和财务员默认可维护。科目结构和期间日期固定，修改名称、启停须携带版本与原因；日志与资料同事务提交。期间禁止重叠。手工凭证另由 `app/finance/journals.py` 提供；正式期初余额另行提供；期间结账与历史成本锁定另行提供，详见 [总账基础规则](../docs/ledger-foundation.md)。

## 手工凭证

第 41 版新增手工凭证、分录与操作审计。`/api/v1/finance/journals` 提供建改、提交、独立批准/驳回、过账、取消及建立冲销草稿，各动作独立授权。金额精确到分且借贷平衡；任何建单、编辑或提交过此凭证的账号均不能审核，包括管理员。过账后保存科目快照；冲销交换原借贷，须再次独立审核过账，原凭证保留。所有写操作填写原因；建单从版本 1 开始，修改与状态操作校验旧版本并递增，冲销校验原版本但不改原记录，新冲销草稿为版本 1；事务内保留完整审计；并发或失败不部分写入。详见 [手工凭证规则](../docs/manual-journals.md)。不自动生成业务凭证，也不改变库存、应收应付或资金记录。

第 73 版的 `app/finance/journal_attachments.py` 为全部总账凭证提供附件元数据、原文读取、上传及追加式撤销接口，查看需要 `journal.view`，上传和撤销另需 `journal.attachment`。PDF、PNG、JPEG 单文件最多 5 MiB，每凭证最多 10 个有效附件；内容、SHA-256 和操作者通过 ORM 写入 SQLite，现有数据库备份包含原文。桌面文件路径只经系统对话框交给主进程；已取消凭证或已结账期间不允许改动附件。详见 [总账凭证附件](../docs/journal-attachments.md)。

## 已过账总账报表

已过账总账的科目明细和试算平衡见 [报表规则](../docs/ledger-reports.md)。`app/finance/ledger_reports.py` 使用 ORM 和 Decimal，接口为 `/api/v1/finance/ledger-reports/options`、`/query`，沿用 `journal.view`。日期范围包含首尾，期初由已确认启用余额加以前的已过账分录累计，冲销仅过账后计入；返回筛选、期间、行、合计和同快照 CSV。新增凭证 GET `/{id}` 支持下钻。正式期初录入见下节；期间结账及业务来源凭证草稿另行提供；数据库当前为第 74 版，客户端和服务端须同步升级。

## 正式期初余额

第 42 版新增 `opening_balances`、`opening_balance_lines`、`opening_balance_changes`。`app/finance/opening_balances.py` 使用 ORM，提供唯一启用方案、版本校验、独立审核、确认与启用前撤销。接口及规则见 [期初余额](../docs/opening-balances.md)。不存在过账凭证时可首次建立；确认后报表只计期初，不增加本期发生额；首次过账后不能重设期初。迁移不猜测历史余额，客户端和服务端须同步升级。

## 期间结账与历史成本锁定

第 43 版新增 `period_closings` 及三个独立权限。`app/finance/period_closing.py` 提供结束后的按序结账、倒序重开与完整业务证据归档；检查条件、接口和权限见 [期间结账规则](../docs/period-closing.md)。状态、快照与审计同一 ORM 写事务提交。`app/core/period_lock.py` 检查历史日期并由统一会话保护新增记录；库存核价、领料核价、历史费用冲销及历史完工分摊受锁定。后期业务可追加更正来源，原结账快照保留。默认管理员和财务员可查看证据、结账，重开默认仅管理员；普通期间查看权限不包含业务证据。结账本身不生成凭证；业务来源草稿由独立功能提供，损益结转草稿另行提供，公司项目编制的资产负债与利润报表由独立模块提供，法定报表格式仍未预置。

## 业务来源凭证

数据库第 44 版增加业务科目配置、配置审计和来源快照三个 ORM 模型。总账凭证页可核对已确认采购、销售、库存、生产费用及收付款来源，按配置生成草稿，再独立审核过账。生成时重算来源及分位金额，拒绝缺价、重复和过期快照；已过账来源更正前须过账关联冲销。启用范围内来源必须有效过账才能结账。权限、API、尾差、更正及限制详见 [业务凭证规则](../docs/business-journals.md)。

## 损益结转

第 45 版新增结转配置、配置审计与来源三个 ORM 模型。`app/finance/profit_transfers.py` 使用正式期初及已过账分录的 Decimal 累计余额，按收入、费用及公司明确选择的成本科目生成期间末草稿，盈利贷记/亏损借记本年利润；净额为零仍逐个清零。凭证不可手工编辑，须独立审核过账。统一会话保护已过账结转来源，更正须重开原期间并从较晚结转倒序冲销；结账归档包含当次范围及清零检查。选项、预览、版本配置、生成 API 与独立权限见 [损益结转规则](../docs/profit-transfers.md)。不提供正式利润表或利润分配。

## 公司财务报表

第 46 版新增公司报表配置、配置审计及固定归档三个 ORM 模型，第 46 版时静态模型共 95 张。`app/finance/statements.py` 提供资产负债与损益查询、逐科目及分录来源、同快照 CSV、版本配置和关闭期间归档。系统及显式分类的手工结转排除利润表发生额；未映射非零科目、未分类结转、不平衡及未关闭范围禁止归档。桌面提供独立权限入口、配置编辑、项目/科目/凭证下钻、归档查询与 CSV，接口及边界见 [报表规则](../docs/financial-statements.md)。

## 辅助核算

第 47 版新增辅助档案、档案审计、科目规则、规则审计及分录归属五张 ORM 表，静态模型共 100 张。`app/finance/auxiliary.py` 提供客户/供应商/部门/项目余额、原始来源、CSV、版本档案及必填规则；`auxiliary_rules.py` 负责编号核验和快照。凭证与正式期初支持辅助选择和组合拆分，业务生成按真实往来带入，损益按完整组合清零，冲销、报表和结账保留快照。独立权限、API、升级和边界见 [辅助核算规则](../docs/auxiliary-accounting.md)。客户端和服务端须同步升级。

## 历史未结单据分户期初

第 48 版新增分户方案、原单、审计及资金四张 ORM 表，此迁移后共 104 张静态模型表。历史明细与已确认总账期初逐完整辅助组合勾稽，由另一账号审核后启用；资金登记、追加冲销、业务凭证来源及结账快照沿用统一会话和期间锁定。路由模块 app/finance/subledger_openings.py 在 main.py 装配，跨模块约束由 subledger_rules.py 复用。独立权限、API、首次启用限制及升级见 [分户期初](../docs/subledger-openings.md)，客户端和服务端须同步升级。

## MRP 物料需求计划

第 49 版新增五张 ORM 表及独立权限，共 109 张静态表。`app/production/mrp.py` 装配日期计划、参数、固定结果、来源检查、独立审核和采购申请/工单转单接口；纯 Decimal 引擎在 `mrp_engine.py`，来源通过 `mrp_sources.py` 复用调用方会话。转单与关联、版本及审计原子提交，不记库存；计划员增加采购申请查看/建单/提交/取消权限。详细日期口径、草稿预计供给、目标仓库、容量和交期限制见 [MRP 规则](../docs/material-planning.md)。

## 不合格品处置与返工

第 51 版新增四张静态 ORM 表及结算携入金额字段，共 119 张模型表。`app/production/quality.py` 装配独立处置权限、版本操作与审批；`quality_rules.py` 在同一 ORM 会话核对数量、冻结证据、返工与成本依赖。与工单、报工、成本分配、业务凭证及锁期连接，详见 [不合格品规则](../docs/quality-rework.md)。旧结算不自动重算，客户端与服务端须同步升级。


## 售后退换修

第 52 版新增售后方案、审计和客户物品保管三张静态 ORM 表，共 122 张。路由与规则位于 `app/sales/after_sales.py`、`after_sales_labor.py`、`after_sales_labor_cost.py`、`after_sales_margin.py`、`after_sales_attachments.py` 和 `after_sales_rules.py`；业务 CRUD 均为 ORM。维修费与追加式更正进入原订单应收，客户物品不计公司库存；`repair_income` 须显式映射科目。第 64 版新增维修工时追加记录的静态 ORM 表；第 83 版新增独立权限的内部标准工时成本核价表，逐条核价、更正、撤销和已结期间固定归档均保留历史，不自动形成工资、应付或总账分录。`GET /api/v1/after-sales/cases/{id}/repair-margin` 要求售后查看与内部成本权限及客户可见范围，基于已结案服务费、有效工时核价和耗材移动平均计价只读计算人民币直接毛利；缺价或未结案时毛利为 `null`，不新增表或凭证，期间结账固定其证据并隔离成本权限。第 74 版新增售后附件及追加式撤销两张 ORM 表；按客户可见范围读取原文，上传和撤销另需 `after_sales.attachment`，结案、取消或更正后只读。独立审核、关联单据权限、版本、并发占用、锁期与固定归档见 [售后规则](../docs/after-sales.md)。

## 设备维护

第 53 版新增五张静态 ORM 表；第 63 版新增运行小时读数、小时计划及计划审计三张表。`app/production/equipment.py` 装配台账、日历计划、独立审核和验收、停机、耗材草稿及更正接口；`equipment_hours.py` 提供人工表计读数和按小时阈值计划，`equipment_attachments.py` 提供设备与维护工单附件的 ORM 留存和追加式撤销，输入与来源规则分别在 `equipment_inputs.py`、`equipment_rules.py`。桌面端已提供独立权限入口、读数登记及更正、四类资料编制、当前版本阶段操作、停机/耗材与审计证据；输入、事务、并发、写后故障回滚、升级及桌面边界均有测试。附件需设备查看权限，写入另需 `equipment.attachment`；每条资料最多 10 份有效 PDF、PNG、JPEG 文件，单份最多 5 MiB，终态仅供读取。权限、来源隐藏、取消与计划更正边界见 [设备维护规则](../docs/equipment-maintenance.md)。

## 电子生产物料档案

第 54 版增加物料分类、规格、封装、品牌、制造商料号及电子参数列，新增永久子类流水与物料审计两张表，共 129 张静态 ORM 表。`app/catalog/material_rules.py` 维护固定分类、编号和审计，`routes.py` 提供分类目录、资料回读和版本编辑。并发编号、失败回滚、旧物料保留与接口兼容边界见 [物料管理规则](../docs/material-catalog.md)。客户端和服务端须同步升级，旧客户端无版本编辑会返回冲突。

## 按仓库库存预警

第 55 版新增规则与修订证据两张静态 ORM 表，共 131 张。`app/inventory/warnings.py` 从已确认流水逐仓逐物料 Decimal 汇总，提供范围查询、详情与带版本阈值维护；沿用 `inventory.view`，新增 `inventory_warning.manage`。规则与审计同事务，过期版本返回 409，未配置不参与预警，停用差额返回 null。桌面窗口可定时读取并提示状态变化，失焦时由桌面应用显示系统通知；服务端约每 60 秒核对规则并用 ORM 留存首次异常、再次异常和恶化事件，桌面可翻阅历史；窗口关闭但托盘仍运行且保持登录时，桌面进程轮询服务端事件并显示系统通知。服务端不主动推送系统通知、邮件或预测。升级与使用见 [库存预警规则](../docs/inventory-warnings.md)。

## 银行流水勾对

第 69 版新增银行账户、流水、勾对及撤销四张 ORM 模型表；第 70 版增加 CSV 导入批次来源表及流水来源列。第 71 版增加账户绑定审计、总账分组勾对与撤销、余额调节表与复核六张表，第 72 版增加期初未达项、核销、核销来源和撤销四张表；第 73 版增加凭证附件和追加式撤销两张表；第 74 版增加售后附件和追加式撤销两张表；第 75 版增加报价附件及追加式撤销两张表；第 76 版增加联系人、跟进与商机共用附件及追加式撤销两张表，第 77 版增加设备维护附件及撤销两张表，共 176 张静态模型表。`app/finance/bank_reconciliation.py` 提供 `/api/v1/finance/bank-reconciliation/overview`、`/accounts`、`/lines/import`、`/imports/csv/preview`、`/imports/csv`、`/matches` 和 `/matches/{id}/reverse`；查看、账户维护、流水登记、勾对和撤销分别使用独立权限。桌面可登记账户、逐笔流水或上传 UTF-8 CSV 并查看来源批次和历史；CSV 文件最多 1 MiB、500 笔，预检后整批写入。账户内重复文件摘要或交易号均拒绝，整批回滚。精确金额和方向匹配订单及历史分户收付款，撤销追加证据。人工录入不等于银行原始凭据核实，不自动改变应收应付或总账；银行直连尚未实现。第 71 至 72 版的 `app/finance/bank_balance.py` 提供账户绑定、已过账分录的同向等额分组勾对、未达项预览、调节快照与独立复核；启用日须与已确认总账期初一致，期初差额须由迁入未达项调节相符。新增 `/api/v1/finance/bank-balance/overview`、`/preview`、`/reports` 及绑定、期初未达项核销与撤销、分组勾对和复核端点。规则及边界见[银行流水勾对与余额调节](../docs/bank-reconciliation.md)。

## 实物批次数据基础

第 56 版新增批次、历史未识别期初和流水分配三张静态 ORM 表；第 57 版新增历史批次补证记录表；第 58 版新增旧流水检查点和逐笔补证两张表；第 59 版新增成对补证关联表；第 60 版新增成组补证及配对关联两张表，当时共 140 张；第 61 版增加客户归属审计表；第 62 版增加供应商与仓库资料审计两张表；第 63 版增加三张运行小时维护表；第 64 版增加售后维修工时表；第 65 版增加商机概率列；第 66 版增加已确认领料冲销表；第 67 版增加已确认退料冲销表；第 68 版新增库存预警最近观测与事件两张表，第 68 版时共 151 张。升级只按逐仓净结存建立未识别期初，不伪造原采购/销售批号。`app/inventory/physical_lots.py` 提供沿用 `inventory.view` 的只读 `/api/v1/inventory/physical-lots/overview` 与 `/{lot_id}/history`，返回逐批余额、正式库存差额、历史期初及分配来源；桌面端可按仓库和物料筛选并核对流水。采购入库确认 `POST /api/v1/receipts/{id}/post` 可提交 `lines: [{receipt_line_id, lots: [{quantity, supplier_lot, manufactured_on, expires_on}]}]`；其他入库确认 `POST /api/v1/warehouse-inbounds/{id}/post` 同样可提交批次，只将明细键改为 `inbound_line_id`；合格完工入库确认 `POST /api/v1/production-completions/{id}/post` 可提交 `lots: [{quantity, manufactured_on, expires_on}]`，不伪造供应商批号。三类入库均按确认数量精确守恒；同一 ORM 写事务写库存流水、批次及分配，冲销反向引用原分配，实际批次不足时返回 409 并整体回滚。旧客户端省略请求体仍可确认，未登记数量明确成为批次差额；其他用途出库确认也可提交 `lines: [{outbound_line_id, lots: [{lot_id, quantity}]}]` 并逐行扣减可用批次，冲销回到原仓原批次。采购退货的关联仓库出库也可提交相同批次请求体；销售出库 `/shipments/{id}/post` 可提交 `lines: [{shipment_line_id, lots: [{lot_id, quantity}]}]`，`/{id}/available-lots` 沿用 `shipment.post`；仓库调拨 `/transfers/{id}/post` 可提交 `lines: [{transfer_line_id, lots: [{lot_id, quantity}]}]`，`/{id}/available-lots` 沿用 `transfer.post`。盘点 `/stocktakes/{id}/available-lots` 沿用 `stocktake.post`，`/{id}/post` 可逐行提交差异绝对值对应的 `lots`，盘亏选已有批次、盘盈可选已有批次或登记“盘点发现”新批次，零差异不产生分配；冲销沿原批次回写，余额不足整单回滚。库存调整 `/stock-adjustments/{id}/available-lots` 沿用 `adjustment.post`；已审批单 `/{id}/post` 可逐行指定已有批次，正向调整也可创建标为“调整新增”的新批次，负向只扣已有批次；冲销沿原分配，余额不足整单回滚。上述确认和冲销均固定原分配。销售退货 `/sales-returns/{id}/available-lots` 沿用 `sales_return.post` 返回原出库批次剩余可退量；`/{id}/post` 可逐行指定原批次或登记“退货新批次”，冲销沿本次实际回仓批次反向扣除。旧客户端省略请求体仍可确认并显示差额。生产领退料已接入，未来新增来源仍须逐项接入，详见 [批次基础与设计草案](../docs/physical-lot-tracing.md)。

第 57 版 `POST /api/v1/inventory/physical-lots/reclassifications` 要求 `physical_lot.reclassify`，提交历史未识别批次、仓库、精确数量、至少 10 字的现场依据及可选真实批号/日期。服务端在 ORM 写事务内核对旧批次现存量与正式库存差额，建立明确标为现场补证的新批次，保留转出/转入、操作人与时间；不改正式库存流水和移动加权成本。原批次及新批次历史均可下钻查看补证记录。`POST /api/v1/inventory/physical-lots/reclassifications/{id}/reverse` 可凭原因追加冲销，若新批次现存量不足或已冲销则拒绝。该接口只处理第 56 版迁移形成的历史未识别结存，不替代旧客户端未分配流水的逐笔补证。

第 58 版 `app/inventory/movement_evidence.py` 提供 `GET /api/v1/inventory/physical-lots/unallocated-movements`，按仓库和物料列出升级检查点之后未完整分配的流水，最多返回最近 100 笔。`POST /api/v1/inventory/physical-lots/movements/{id}/evidence` 要求 `physical_lot.movement_evidence`，提交精确正数量、至少 10 字的实物依据，以及已有批次或新建入库批次的来源信息；出库只能选本仓现存批次。写事务同时核对原流水未分配数量、本仓正式库存差额和批次余额。`POST /api/v1/inventory/physical-lots/movement-evidence/{id}/reverse` 凭原因追加相反记录，防止重复冲销和已耗用批次的出库。补证不改原库存流水、订单或移动平均成本。旧版没有保存空结存时的升级检查点；若第 57 版库没有历史期初，第 58 版保守地把升级前全部流水列为不可逐笔补证，避免把旧流水重复计入批次结存。

第 59 版 `POST /api/v1/inventory/physical-lots/evidence-pairs` 在同一 ORM 写事务中将升级检查点后同仓同物料、先入后出的两笔未分配正负流水按相同数量归属同一批次，允许两笔在正式库存中相抵为零。接口沿用 `physical_lot.movement_evidence`，提交两笔流水编号、精确正数量、至少 10 字核对依据和已有批次编号或新批次属性。服务端核对各自剩余未分配量；两笔证据及关联记录原子提交，不改正式流水或成本。`POST /api/v1/inventory/physical-lots/evidence-pairs/{id}/reverse` 凭原因整体追加反向证据，单条证据不能单独冲销，重复或存在后续依赖时返回 409。批次历史展示成对关联与冲销。

第 60 版 `POST /api/v1/inventory/physical-lots/evidence-groups` 接收 2 至 50 对 `pairs: [{inbound_movement_id, outbound_movement_id, quantity}]`，涉及至少三笔不同流水，并提交同一批次和现场依据。各对必须是升级检查点之后同仓同物料、先入后出的流水，数量不得超过各流水剩余未分配量；服务端在同一 ORM 写事务中创建逐对证据和整组关联，任一对失败即整组回滚。组内单对不能独立冲销；`POST /api/v1/inventory/physical-lots/evidence-groups/{id}/reverse` 逆序整体冲销，批次历史保留整组关联与操作人。补证不改变正式库存和移动平均成本。旧版无法确认检查点的流水、跨仓或跨物料流水，以及先出后入的流水不会自动匹配。

## 业务物料选项

报价 `/api/v1/crm/options`、售后 `/api/v1/after-sales`、设备维护 `/api/v1/equipment/overview`、质检 `/api/v1/production-quality` 与库存预警 `/api/v1/inventory/warnings` 的 `materials` 附带当前物料的分类、规格、封装、品牌、制造商料号、技术参数、合规信息及备注，并提供 `category_name` 中文分类名称。统一使用 `app.catalog.material_rules.material_choice_data` 的展示字段白名单；原接口权限保持不变，不要求额外取得库存查看权限，不返回编辑版本、供应商联系方式或业务价格。物料列表与 MRP 选项也提供中文分类名称；MRP 只在选项响应中补充，计算来源、指纹与固定快照保持原结构。此变更无数据库迁移，也不改变历史单据。
