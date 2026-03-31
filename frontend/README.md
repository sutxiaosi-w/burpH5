# burph5 frontend

`burph5` 的可视化前端，提供这些页面：

- 历史记录
- 请求重放
- 请求集合
- 系统设置

技术栈：

- Vue 3
- Vite
- TypeScript
- Pinia
- Vue Router
- CodeMirror

## 启动

```powershell
cd D:\挖洞\burph5\frontend
npm.cmd install
npm.cmd run dev -- --host 127.0.0.1 --port 5173
```

## 说明

- 前端主要给人工查看和重放使用
- `qclaw` 本身通常不直接依赖前端页面
- 对 `qclaw` 来说，更关键的是后端 API、MCP，以及它自己的 `browser` 工具或补充的 `Chrome DevTools MCP`
