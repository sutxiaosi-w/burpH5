# burph5

本地 HTTP Repeater 工具，包含：

- Vue 3 可视化界面
- FastAPI 后端 API
- Typer CLI
- MCP `stdio` 工具服务
- 本地 HTTP 代理抓包

适合本地调试、接口复测、历史留档和批量回归。

## 目录

- `frontend`：Vue 3 + Vite + Pinia + Vue Router
- `backend`：FastAPI + httpx + SQLite + Typer + MCP

## 环境要求

- Python 3.12+
- Node.js 和 npm（仅前端构建时需要）

## 快速启动

### 一体化启动

先安装 Python 依赖：

```powershell
python -m pip install -r requirements.txt
```

如果你要使用可视化界面，再构建前端：

```powershell
cd frontend
npm.cmd install
npm.cmd run build
```

然后回到仓库根目录启动：

```powershell
python app.py
```

Windows 下也可以直接双击：

- `启动burph5.bat`

默认访问地址：

- `http://127.0.0.1:8765`

## 后端开发启动

```powershell
cd backend
python -m pip install -e .[dev]
python -m burph5.cli serve
```

## 前端开发启动

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

## 代理

```powershell
cd backend
python -m burph5.cli proxy start --capture-https
```

默认监听 `127.0.0.1:8899`，支持：

- 明文 HTTP 抓取
- 基于本地根证书的 HTTPS MITM 抓取
- Windows 当前用户证书库自动安装本地 CA

证书相关命令：

```powershell
cd backend
python -m burph5.cli proxy ca ensure
python -m burph5.cli proxy ca install
python -m burph5.cli proxy ca reset
```

## 发包示例

下面这类原始 HTTP 数据包，可以直接拿来做重放、接口调用或 MCP 调用。

先把请求保存成 `backend\req.txt`，或者先 `cd backend` 再保存成当前目录下的 `req.txt`：

```http
GET http://localhost/vul/rce/rce_ping.php HTTP/1.1
Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7
Cookie: PHPSESSID=6ji8hu74ec2hphv88d5aqf646g
Referer: http://localhost/
Upgrade-Insecure-Requests: 1
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0
sec-ch-ua: "Chromium";v="146", "Not-A.Brand";v="24", "Microsoft Edge";v="146"
sec-ch-ua-mobile: ?0
sec-ch-ua-platform: "Windows"
```

### 用 CLI 发包

```powershell
cd backend
python -m burph5.cli replay --raw-file .\req.txt
```

如果原始请求是相对路径形式，例如 `GET /vul/rce/rce_ping.php HTTP/1.1`，再补一个默认协议：

```powershell
python -m burph5.cli replay --raw-file .\req.txt --default-scheme http
```

### 用 HTTP API 发包

先启动后端：

```powershell
cd backend
python -m burph5.cli serve
```

然后通过 `POST /api/replay` 调用：

```powershell
$raw = Get-Content -Raw .\req.txt
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8765/api/replay `
  -ContentType 'application/json' `
  -Body (@{
    raw_request = $raw
    source = 'api'
    persist = $true
    default_scheme = 'http'
  } | ConvertTo-Json -Depth 10)
```

如果你已经有结构化请求对象，也可以直接传 `request` 字段，而不是 `raw_request`。

### 用 MCP 发包

先启动 MCP：

```powershell
cd backend
python -m burph5.mcp_server
```

然后调用工具 `replay_request`：

```json
{
  "raw_request": "GET http://localhost/vul/rce/rce_ping.php HTTP/1.1\r\nAccept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7\r\nCookie: PHPSESSID=6ji8hu74ec2hphv88d5aqf646g\r\nReferer: http://localhost/\r\nUpgrade-Insecure-Requests: 1\r\nUser-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0\r\nsec-ch-ua: \"Chromium\";v=\"146\", \"Not-A.Brand\";v=\"24\", \"Microsoft Edge\";v=\"146\"\r\nsec-ch-ua-mobile: ?0\r\nsec-ch-ua-platform: \"Windows\"\r\n\r\n",
  "default_scheme": "http"
}
```

也可以先用 `parse_raw_request` 把原始包解析成结构化对象，再交给 `replay_request`。

## MCP

```powershell
cd backend
python -m burph5.mcp_server
```

工具：

- `replay_request`
- `parse_raw_request`
- `list_history`
- `get_history_item`
- `save_collection`
- `run_collection`

## 验证

```powershell
python -m pip install -r requirements.txt
python -m pip install pytest

cd backend
pytest -q

cd ../frontend
npm.cmd run build
```
