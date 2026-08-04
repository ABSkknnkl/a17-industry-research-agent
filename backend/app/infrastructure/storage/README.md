# Artifact Storage

后端 C 负责。保存 JSON、图表、HTML 与 PDF，返回 ArtifactRef；禁止直接使用用户输入拼接路径，写入时计算校验和并进行项目隔离。

