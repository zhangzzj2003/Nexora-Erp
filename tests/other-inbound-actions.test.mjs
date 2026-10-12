import assert from "node:assert/strict";
import { test } from "node:test";
import { otherInboundActions } from "../src/renderer/src/views/workspace/warehouse/other-inbound-actions.ts";

const permissions = { create: true, post: true, cancel: true, reverse: true };
const keys = (record, allowed = permissions) =>
  otherInboundActions(record, allowed).map((item) => item.key);
// 覆盖审批与仓库终态组合，任何入口都不能跳过批准执行或重复冲销。
test("入库详情与列表共用状态操作，审批中不可取消、批准前不可入库", () => {
  assert.deepEqual(keys({ status: "draft" }), ["approval", "cancel"]);
  assert.deepEqual(
    keys({ status: "draft", approval: { status: "submitted" } }),
    ["approval"],
  );
  assert.deepEqual(
    keys({ status: "draft", approval: { status: "approved" } }),
    ["approval", "post", "lots"],
  );
  for (const status of ["rejected", "withdrawn"])
    assert.deepEqual(keys({ status: "draft", approval: { status } }), [
      "approval",
      "cancel",
    ]);
  assert.deepEqual(keys({ status: "posted" }), [
    "approval",
    "reversalApproval",
  ]);
  assert.deepEqual(
    keys({ status: "posted", reversal_approval: { status: "approved" } }),
    ["approval", "reversalApproval", "reverse"],
  );
  assert.deepEqual(
    keys({
      status: "posted",
      reversal_id: 1,
      reversal_approval: { status: "approved" },
    }),
    ["approval", "reopen"],
  );
  // 成功重开的原单只能看历史，部分冲销也可重开但不能再确认余量。
  for (const record of [
    { status: "cancelled" },
    { status: "posted", reversal_id: 1 },
    { status: "partially_posted", reversal_id: 1 },
  ]) {
    assert.deepEqual(keys({ ...record, reopened_as_id: 10 }), ["approval"]);
    assert.deepEqual(keys(record, { ...permissions, create: false }), [
      "approval",
    ]);
  }
  assert.equal(
    otherInboundActions({ status: "posted", reversal_id: 1 }, permissions).some(
      (item) => item.key === "reopen",
    ),
    true,
  );
  assert.deepEqual(
    keys({ status: "cancelled", approval: { status: "approved" } }),
    ["approval", "reopen"],
  );
});

test("缺少权限只展示记录入口，不能从详情获得额外操作权限", () => {
  const none = { create: false, post: false, cancel: false, reverse: false };
  assert.deepEqual(keys({ status: "cancelled" }, none), ["approval"]);
  assert.deepEqual(keys({ status: "draft" }, none), ["approval"]);
  assert.deepEqual(
    keys({ status: "draft", approval: { status: "approved" } }, none),
    ["approval"],
  );
  assert.deepEqual(
    keys({ status: "posted", reversal_approval: { status: "approved" } }, none),
    ["approval", "reversalApproval"],
  );
});
