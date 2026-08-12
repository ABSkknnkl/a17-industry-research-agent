# SkillHub 适配层

该目录是 Agent 1 与同花顺问财 SkillHub 之间的反腐层，不包含金融结论逻辑。

- `catalog.py`：P0/P1 逻辑技能名、Skill ID、通道与端点映射。
- `protocol.py`：可替换的 `SkillHubClient` 协议。
- `client.py`：异步真实客户端，含 Bearer 鉴权、Claw 请求头、分页、有界退避和结构化错误。
- `mock.py`：测试专用的确定性假实现。
- `registry.py`：将 11 个逻辑技能注册到共享 `ToolGateway`。

错误只向上游暴露安全码：`auth_required`、`permission_denied`、`rate_limited`、`provider_unavailable`、`request_rejected` 或 `invalid_provider_response`。供应商响应、Token 和原始异常不写入运行日志。

产业链是逻辑组合技能：适配层并行调用行业与经营能力，再返回带来源标记的行数据；不在这一层猜测产业链关系。

事件、经营、板块和产业链使用各自的专用主查询与最多两条受限备选查询。SkillHub 返回的大型结构化宽表不会被 ToolGateway 转换为截断字符串；普通自由文本工具仍执行字符上限，避免模型上下文和日志无界增长。
