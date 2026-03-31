# burph5

本地 HTTP Repeater 工具，包含：

- Vue 3 可视化界面
- FastAPI 后端 API
- Typer CLI
- MCP `stdio` 工具服务
- 本地 HTTP 代理抓包

也可以配合 `qclaw` 使用：

- `qclaw` 内置 `browser` 工具：优先负责真实打开浏览器、点击页面功能、截图、监听点击前后的请求和响应
- `Chrome DevTools MCP`：当 `qclaw browser` 拿不到网络请求时，再补这一层
- `burph5`：负责请求重放、历史保存、集合批量复测、CLI/MCP/API 调用

授权页面探索、登录续测、抓包与漏洞挖掘流程统一使用：

- `C:\Users\niexiaoxiao\.qclaw\skills\vuln-hunter`

## 目录

- `frontend`：Vue 3 + Vite + Pinia + Vue Router
- `backend`：FastAPI + httpx + SQLite + Typer + MCP

## qclaw 使用建议

推荐优先级：

1. `qclaw` 自带 `browser` 工具，且能拿到网络请求
2. `qclaw` 自带 `browser` 工具，但拿不到网络请求时，补 `Chrome DevTools MCP`
3. `qclaw` 能调本地 `burph5 HTTP API`
4. `qclaw` 再按需要调 `burph5 MCP` 或 `CLI`

如果 `qclaw` 当前环境没有浏览器抓取能力：

- 不要凭空捏造接口
- 改用页面链接、表单 action、前端脚本、站内文档和已观察请求做枚举
- 再把确认过的请求送进 `burph5`

## 后端启动

```powershell
cd D:\挖洞\burph5\backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .[dev]
.\.venv\Scripts\python -m burph5.cli serve
```

## 前端启动

```powershell
cd D:\挖洞\burph5\frontend
npm.cmd install
npm.cmd run dev
```

## 代理

```powershell
cd D:\挖洞\burph5\backend
.\.venv\Scripts\python -m burph5.cli proxy start
```

默认监听 `127.0.0.1:8899`，只抓 HTTP 明文，请求通过 HTTPS 时仅做 `CONNECT` 透传。

## MCP

```powershell
cd D:\挖洞\burph5\backend
.\.venv\Scripts\python -m burph5.mcp_server
```

工具：

- `replay_request`
- `parse_raw_request`
- `list_history`
- `get_history_item`
- `save_collection`
- `run_collection`

## Chrome DevTools MCP

如果 `qclaw` 自带 `browser` 工具已经能拿到网络请求，一般不必额外安装。

如果 `qclaw browser` 只能打开网页、点击、截图，但拿不到点击当下的请求和响应，再补 `Chrome DevTools MCP`：

```powershell
cmd /c npx -y chrome-devtools-mcp@latest --help
```

常见做法是把它注册到客户端的 MCP 配置里，再让 `qclaw`：

- 打开目标页面
- 点击不同功能
- 点击前截图
- 点击前清空或标记网络请求
- 抓点击后新增的请求和响应
- 把主业务包交给 `burph5`

## 验证

```powershell
cd D:\挖洞\burph5\backend
.\.venv\Scripts\pytest -q

cd D:\挖洞\burph5\frontend
npm.cmd run build
```
