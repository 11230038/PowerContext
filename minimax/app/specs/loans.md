# 借阅列表规格（v1）

本文件是 `loanboard` 业务工程的当前有效规格。实现与测试必须以本文件为准。

## SPEC-LOAN-001 列表排序

借阅列表必须按到期日 `due_date` 升序排列；同一到期日按 `loan_id` 字典序升序排列。

## SPEC-LOAN-002 状态筛选

`status` 只允许 `active` 或 `returned`，其他值必须抛出 `ValueError`。
`active` 表示 `returned_on` 为空，`returned` 表示已经归还。

## SPEC-LOAN-003 分页边界

`limit` 必须是 1 到 100 之间的整数，`offset` 必须是不小于 0 的整数；越界或类型错误必须抛出 `ValueError`。
`limit` 默认值为 50，`offset` 默认值为 0。分页在排序之后执行。

## SPEC-LOAN-004 逾期筛选

`list_loans` 必须支持布尔参数 `overdue_only`。
当 `overdue_only=True` 时，只返回 `returned_on` 为空且 `due_date` 早于 `as_of` 日期的借阅。
当 `overdue_only=False` 时不施加逾期筛选。
`as_of` 默认取当天，测试可以注入固定日期以保证结果可重复。

## SPEC-LOAN-005 组合筛选

`member_id` 不为空时只返回该会员的借阅。
`member_id`、`status`、`overdue_only` 可以组合使用，筛选条件的书写顺序不得影响结果。

## SPEC-LOAN-006 兼容性

现有调用方不传 `overdue_only` 时，行为必须与 v1 完全一致：排序、分页、`member_id` 筛选和 `status` 校验都不得改变。
已归还的借阅即使曾经逾期，也不得出现在 `overdue_only=True` 的结果中。
