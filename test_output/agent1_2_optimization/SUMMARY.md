## Agent1+Agent2 优化回归测试结果
**场景A(标准指标)**: status=completed; 全部 supported; 动态注入已验证(查询含毛利率等)
**场景B(长尾LLM路由)**: status=completed; semantic_accepted={'库存周转率': 'hithink_finance_query', '净资产收益率': 'hithink_finance_query'}; 全部 supported
**场景C(无法获取-原神股价)**: status=waiting_review error=requested_data_partial; 原神证据数=0(不补造); 单指标缺失走软路径 advisory
**场景D(Agent2 确定性公式)**: {'毛利率': 30.0, '销售净利率': 15.0, '研发费用率': 6.0, '销售费用率': 8.0, '管理费用率': 5.0, '海外收入占比': 40.0}; 与期望{'毛利率': 30.0, '销售净利率': 15.0, '研发费用率': 6.0, '销售费用率': 8.0, '管理费用率': 5.0, '海外收入占比': 40.0} 一致=True
**场景E(Agent2 软硬质量门)**: COMPLETED 条件 = quality.passed and not has_blocking_request

### Agent2 涉及文件与行为(静态核验)
- calculations.py: 毛利率/净利率/研发·销售·管理费用率/海外收入占比 均已加入 ratio_inputs
- service.py L311-319: 质量门软硬分级, 普通补充建议不阻断
