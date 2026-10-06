# 物料演示数据

`materials.json` 包含 50 条虚构物料档案：电子类 24 条、五金类 14 条、塑料类 5 条、包装类 4 条、其他类 3 条，覆盖当前服务端全部物料子类。线材、线束使用现有 `EL-WR` 子类，辅料使用 `OT-OT`；本数据不新增分类。

每条记录包含名称、单位、规格、封装或外形、示例制造商及稳定演示料号；电子参数按物料用途填写，五金、塑料与包装不填无关电气参数。名称以“示例”开头，备注带 `NEXORA-DEMO-MATERIALS-V1` 标记。参数均用于演示，不作为采购或工程依据。

记录遵循现有 `POST /api/v1/materials` 输入契约，省略 `sku`、ID 和版本；实际物料编码由目标服务端按分类分配。数据中不包含库存数量、价格、采购、入出库或财务单据。

`import_materials.py` 是显式运行的本机维护工具，不在应用启动时执行，也不增加网络接口。先更新目标 ERP 服务并验证健康状态，再运行导入。工具要求现有实例的绝对数据目录、已核对的实例 ID、具备物料管理权限的启用管理员 ID，以及尚不存在的备份路径；它先保留数据库、证书和私钥的成组备份，再用现有 ORM 写事务一次性新增物料、分配编码并追加操作者审计。运行者须有该数据库及证书文件的本机访问权，不创建、重置账号或登录会话。

以稳定演示料号识别已导入档案；重跑只跳过，不覆盖用户后续编辑。演示料号若与不带示例标记的档案冲突，或任何编码/审计写入失败，整批回滚。物料资料之外的库存、业务单据与财务数据不变。本工具不执行数据库迁移，升级应先通过现有服务升级流程完成。

从仓库根目录运行，按实际实例替换占位值；备份包含私钥，应放在受控位置：

```text
PYTHONPATH=backend .venv/bin/python scripts/demo/import_materials.py \
  --data-dir /absolute/path/to/instance \
  --instance-id <已核对的实例ID> \
  --actor-user-id <现有管理员ID> \
  --backup /absolute/protected/path/before-demo.nexora-backup
```

验证：

```text
node --experimental-strip-types --test tests/demo-materials.test.mjs
PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/test_demo_materials.py -q
```
