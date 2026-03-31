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
cd frontend
npm.cmd install
npm.cmd run dev -- --host 127.0.0.1 --port 5173
```

## 说明

- 前端主要给人工查看和重放使用
- 开发模式默认连接 `http://127.0.0.1:8765`
- 发布到本地一体化入口前，需要先执行 `npm.cmd run build`
