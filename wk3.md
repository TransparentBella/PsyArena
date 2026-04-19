## wk3：远程服务器部署与 Git 同步规划（Mars_2228）

### 0. 核心原则
- 本地（Windows）只负责开发与提交代码。
- 远程（Ubuntu 18.04）只负责运行服务与对外提供访问。
- 本地和远程各自维护独立虚拟环境，不跨平台拷贝 `.venv`。

---

### 1. 本地项目需要新增/确认的文件

#### 1.1 `.gitignore`（必须）
目标：保持仓库干净，避免上传虚拟环境、缓存、临时文件、数据库。

建议至少包含：

```gitignore
# venv
.venv/
.venv-arena/
venv/

# python cache
__pycache__/
*.py[cod]

# sqlite/runtime
*.db
*.db-wal
*.db-shm

# system/temp
.DS_Store
*.log
*.lock

# optional: 如数据体积大且不走 Git 管理
# data/
```

> 当前仓库已有 `.gitignore`，需确认规则覆盖上述关键项。

#### 1.2 `requirements.txt`（必须）
目标：让远程可复现 Python 依赖。

- 你当前项目已存在 `requirements.txt`。
- 建议本地重新生成并提交：
  - `pip freeze > requirements.txt`

#### 1.3 `.env.example`（建议）
目标：描述环境变量模板，不提交真实密钥。

建议示例字段：
- `DATA_DIR`
- `DB_PATH`
- `MANIFEST_PATH`
- `MODE`
- 未来如有：第三方 API Key

同时将真实 `.env` 加入 `.gitignore`。

#### 1.4 可选：`.vscode/sftp.json`
如果采用 SFTP 同步代码（不是首选），在 VS Code 配置远程目录与忽略规则。

---

### 2. 远程服务器需要创建的基础设施

### 2.1 目录结构（建议）
```bash
/opt/commentranking/
  app/           # 代码工作目录
  venv/          # Linux 虚拟环境
  shared/data/   # 线上数据与数据库（持久化）
  logs/          # 日志
```

### 2.2 Python 虚拟环境（必须）
```bash
cd /opt/commentranking
python3 -m venv venv
source venv/bin/activate
pip install -U pip
pip install -r app/requirements.txt
```

### 2.3 进程守护（systemd，必须）
- 在 `/etc/systemd/system/commentranking.service` 创建服务。
- 能力要求：
  - 开机自启
  - 异常自动重启
  - 与 shell 会话解耦

### 2.4 Nginx 反向代理（建议）
- 配置文件：`/etc/nginx/sites-available/commentranking`
- 入口：`80/443 -> 127.0.0.1:8010`
- 处理静态资源与反向代理头。

---

### 3. 本地与远程职责对照

| 维度 | 本地（Local） | 远程（Mars_2228） |
| :--- | :--- | :--- |
| 源码 | 开发、提交、分支管理 | 拉取/接收代码副本 |
| Python 环境 | Windows `.venv-arena` | Linux `/opt/commentranking/venv` |
| 数据库 | 本地测试数据库 | 线上 `shared/data/app.db` |
| 访问入口 | 本机 `127.0.0.1:8010` | Nginx 暴露 IP/域名 |
| 进程管理 | 手动运行可接受 | 必须 systemd 常驻 |

---

### 4. 代码同步方案选择

### 方案 A：Git 远程仓库 + 服务器 `git pull`（通用）
- 本地推送到 GitHub/GitLab。
- 服务器 `git pull` 更新。

优点：标准、易理解。缺点：服务器需要访问代码托管平台。

### 方案 B：本地直接 `git push` 到服务器裸仓库（推荐）
- 服务器建裸仓库：`/opt/commentranking/repo.git`
- 本地新增 remote 指向该裸仓库。
- 用 `post-receive` hook 自动部署到 `/opt/commentranking/app` 并重启服务。

优点：不依赖第三方托管，推送即部署；更适合你当前 SSH 直连环境。

---

### 5. 面向你当前环境的执行顺序（Ubuntu 18.04）

1) SSH 连通验证
```bash
ssh Mars_2228 "echo ok"
```

2) 远程创建目录
```bash
ssh Mars_2228 "mkdir -p /opt/commentranking/{app,shared/data,logs}"
```

3) 首次同步代码（任选其一）
- 方案A：服务器 `git clone` 到 `/opt/commentranking/app`
- 方案B：配置裸仓库后，本地 `git push mars main`

4) 创建远程 venv 并安装依赖
```bash
ssh Mars_2228
cd /opt/commentranking
python3 -m venv venv
source venv/bin/activate
pip install -U pip
pip install -r /opt/commentranking/app/requirements.txt
```

5) 先前台验证一次
```bash
cd /opt/commentranking/app
/opt/commentranking/venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8010
```

6) 配置 systemd + Nginx，切到后台服务运行。

7) 发布验收
- `curl http://127.0.0.1:8010/healthz`
- 打开 `/ui/login/` 验证页面
- 检查 `journalctl -u commentranking -f`

---

### 6. systemd 服务配置模板（建议）

`/etc/systemd/system/commentranking.service`

```ini
[Unit]
Description=CommentRanking Service
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/commentranking/app
Environment=DATA_DIR=/opt/commentranking/shared/data
Environment=DB_PATH=/opt/commentranking/shared/data/app.db
Environment=MANIFEST_PATH=/opt/commentranking/shared/data/manifest.json
Environment=MODE=both
ExecStart=/opt/commentranking/venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target
```

启用命令：
```bash
systemctl daemon-reload
systemctl enable --now commentranking
systemctl status commentranking
```

---

### 7. Nginx 配置要点（建议）

- `server_name` 用你的域名或服务器 IP。
- `location /` 反代到 `http://127.0.0.1:8010`。
- 配置 `proxy_set_header`：`Host`、`X-Real-IP`、`X-Forwarded-For`。
- 后续加 HTTPS（Let’s Encrypt）。

---

### 8. 发布、回滚、排障 SOP

### 8.1 发布 SOP
1. 本地开发并提交
2. 推送到远程（A: push 平台 + pull；B: push 到裸仓库）
3. 重启服务（或 hook 自动）
4. 健康检查与页面验收

### 8.2 回滚 SOP
- 回滚到上一个稳定 commit：
  - `git reset --hard <commit>`
- 重启：`systemctl restart commentranking`

### 8.3 常见故障点
- 依赖没装全（`requirements.txt` 过旧）
- `MANIFEST_PATH`/`DATA_DIR` 错误
- 8010 端口被占用
- Nginx upstream 配置错误导致 502
- 权限问题导致读不到 `shared/data`

---

### 9. 立即待办（你现在就可以做）
1. 本地重新生成并提交 `requirements.txt`。
2. 在仓库补充 `.env.example`。
3. 选定同步方案（建议 B：push 即部署）。
4. 按第 5 节顺序执行首次部署。

---

### 10. 备注
- Ubuntu 18.04 较旧，建议确认 `python3 --version`。若版本过低，优先升级 Python 运行时（至少 3.10）。
- 若暂时不升级系统，建议固定依赖版本并保存可工作的 `requirements.txt`，避免后续安装漂移。
