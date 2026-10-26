# 所有中转对话强制关闭上游会话保存

管理端对外的 Chat Completions（v1/v2）、Responses 和 Anthropic Messages 请求在转发时统一写入 `store: false`。客户端无需配置；即使传入 `store: true`，服务端也会覆盖。策略固定开启，没有管理端开关。

Responses 和 Anthropic 在协议转换时设置，Chat 在转发前设置；流式与非流式共用相同请求体。既有会话不删除，网关自身的用量日志不受影响。该策略作用于经过管理端的请求，直接访问 workbuddy2api 会绕过它。

2026-10-26 定点账号测试的十条 `store: false` 请求均成功，用户确认在 WorkBuddy 客户端看不到对应会话。该结果仅涉及客户端可见会话，上游后台的数据保留由上游决定。

回归测试：`server.tests.test_force_no_store` 覆盖未传、传 true 和传 false 的行为，以及两种协议转换。既有 Responses 过滤测试已同步更新。维护升级时保留这三个入口的强制策略，不能只在客户端或 Responses 输入中添加字段。
