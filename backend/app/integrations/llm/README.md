# LLM Adapter

后端 B 负责。通过 OpenAI 兼容接口支持 Qwen/DeepSeek 切换，业务代码不得直接实例化厂商 SDK。真实实现必须有 Mock、结构化输出校验、超时和用量记录。

当前Agent 2和Agent 4各使用自己的最小业务协议：

- `MockAnalysisModel`用于测试和无密钥开发；
- `OpenAICompatibleAnalysisModel`使用LangChain结构化输出；
- `create_analysis_model(settings)`根据`LLM_USE_MOCK`选择实现。
- `MockChapterWritingModel`按固定大纲生成可重复的章节测试数据；
- `OpenAICompatibleChapterModel`通过`ChapterWritingModel`协议输出`ChapterDraft`；
- `create_chapter_writing_model(settings)`与Agent 2共用供应商配置，但不共用业务输出模型。

其他智能体应定义自己的业务协议，或在确有相同语义时复用后续公共聊天模型适配层；不得为了统一调用方式而强迫不同Agent共用`AnalysisDraft`或`ChapterDraft`。
