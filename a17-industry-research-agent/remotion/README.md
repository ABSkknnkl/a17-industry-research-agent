# 项目演示动画

本目录是使用 Remotion、React 和 TypeScript 制作项目介绍动画的独立工程；它不是主应用的前端。合成定义位于 `src/Root.tsx`，内容和版式位于 `src/compositions/`、`src/components/` 和 `src/theme/`。

在本目录执行：

```bash
npm ci
npm run dev                 # 打开 Remotion Studio
npm run lint                # ESLint 与 TypeScript 检查
npm run build               # 构建 Remotion bundle
```

`package.json` 提供 `render:overview`、`render:fetcher`、`render:interpreter`、`render:chart`、`render:writer`、`render:fusion`，以及依次执行这些任务的 `render:all`。渲染输出路径为项目的 `output/videos/`；运行前请确认路径和已有文件。渲染依赖及浏览器环境需按本机情况准备，本次文档更新未重新渲染视频。

动画中的系统事实、数字和演示画面应在发布前与实际运行结果核对。
