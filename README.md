# Nexora ERP（联光 ERP）

面向企业内部的桌面 ERP。当前版本已具备用户与角色权限管理、物料与供应商、采购入库单、库存流水，以及局域网服务端的创建、发现和连接。

## 当前工作方式

首次打开客户端，可选择**手动连接**、**扫描局域网**或**在本机新建服务端**。服务端由 FastAPI 管理 SQLite 数据库和权限；其他客户端通过 HTTPS 访问同一个服务端。客户端重启后会尝试重连上次选择的服务端，但仍需登录账号。

创建服务端时填写实例名称、数据目录、监听端口和首位管理员账号。已有数据库不会被覆盖。关闭桌面窗口后，服务端留在托盘并继续运行；在设置或托盘中可停止服务。退出应用或操作系统登录会话后，服务停止。

首次连接其他电脑时，请将客户端展示的 SHA-256 指纹与服务端电脑“服务端已就绪”页面中的指纹完整核对，再输入账号密码。连接记录只保存地址、服务端身份和证书，不保存密码。证书变化时，自动重连会被阻止，需重新核验。

**当前数据集中保存在服务端。**远程客户端断网后不能继续编辑，也没有本地数据合并或离线同步。MySQL、跨设备数据同步、财务、销售、人力资源与 CRM 是后续阶段的工作。

## 开发

需要 Node.js 22.12+、Python 3.11+。在仓库根目录运行：

```bash
npm install
python3 -m pip install -r backend/requirements-dev.txt
npm run dev
```

Windows 可把 `python3` 改为 `python`。如果 Python 不在默认路径，可设置 `NEXORA_PYTHON` 指向解释器。桌面应用会在“新建服务端”时自动启动 Python 服务。单独调试后端见 [后端说明](backend/README.md)。

渲染页面已接入 Naive UI 和 Tailwind CSS 4。Vue 组件可从 `naive-ui` 按需导入；`App.vue` 的 `NConfigProvider` 统一提供中文语言与主题色。Tailwind 工具类可直接写在 Vue 模板中，入口为 `src/renderer/src/style.css`。项目保留原有基础样式，因此未启用 Tailwind Preflight 全局重置。

界面图标使用 [Remix Icon](https://icones.js.org/collection/ri)。在 Vue 组件中按需导入，例如 `import IconRefreshLine from '~icons/ri/refresh-line'`；构建时将 SVG 编入页面，运行时无需请求在线图标服务。

品牌标志使用 `resources/nexora-nexus-aurora-logo.png`。需要重新生成 macOS、Windows 和托盘图标时，安装 Pillow 后运行 `python3 scripts/create-icons.py`；页面页眉与侧栏使用生成的 `resources/icon.png`。

新增或修改前端界面时，请遵循 [前端 UI 开发规范](docs/frontend-ui-guidelines.md)。

常用检查：

```bash
PYTHONPATH=backend python3 -m pytest backend/tests -q
node --experimental-strip-types --test tests/backend.test.mjs
npm run build
```

## 内部安装包

在 Apple Silicon Mac 上安装 PyInstaller 和后端依赖后运行 `npm run dist:mac`；在 Windows x64 上运行 `npm run dist:win`。两个平台都需先执行 `npm install`。仓库中的 GitHub Actions 工作流可在 Windows runner 上构建并上传内部测试安装包。PyInstaller 必须在目标操作系统上分别构建服务程序。产物位于忽略 Git 的 `release/`。

内部包尚未签名或公证，macOS Gatekeeper 或 Windows SmartScreen 可能提示开发者身份未验证。macOS 首次扫描可能要求授予本地网络权限；Windows 应允许应用在专用网络通信。mDNS 受路由器或防火墙限制时，可改用手动地址连接。

## 安全与数据

- 首位管理员只能从服务端电脑本机创建；后续用户和角色由管理员管理。业务接口在服务端校验权限。
- 管理员可停用账号、重置密码并配置自定义角色的权限；修改密码后旧登录立即失效。系统始终保留至少一位启用的内置管理员。
- 服务端为每个实例生成独立 HTTPS 证书，私钥保存在数据目录。请备份整个目录，尤其是 `nexora.db`、`server.crt` 和 `server.key`；丢失私钥会要求客户端重新核验身份。
- 一张入库单只允许确认一次。确认状态与库存流水在同一个事务中写入，当前库存从流水汇总。
- 切换服务端会退出当前账号；不同服务端的数据保持独立，不会自动合并。

## English summary

Nexora ERP currently supports a LAN host and connected desktop clients, with FastAPI, SQLite, HTTPS certificate pinning, user and role administration, purchase receipts, and stock movements. A host can be created locally, discovered with mDNS, or connected by address. Remote clients require a live connection; offline synchronization and MySQL are future work. Internal macOS Apple Silicon and Windows x64 packaging scripts are included. Windows device acceptance is pending access to a Windows machine.
