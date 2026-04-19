# CommentRanking Demo（本周）

## 目标
- 做一个可跑通的 Demo：给定一场比赛视频 + ≥2 个同场解说源（文本/音频/两者），用户提交一次排序（ranking），系统落盘并可导出为数据集（JSONL/CSV）。

## 参考开源
- Chatbot Arena / FastChat：参考其“匿名对战 + 人类偏好收集 + Elo/胜率统计”的流程与交互（https://github.com/lm-sys/FastChat ，平台开源说明见 https://lmsys.org/blog/2024-03-01-policy/）。
- Label Studio：可直接参考/复用其 Pairwise 对比标注模板（https://labelstud.io/templates/pairwise_comparison），并扩展到多选排序。

## 架构（Demo 版）
- 前端：任务页（视频播放器 + 多解说面板/音频播放器 + 排序组件 + 提交/下一条）。
- 后端：任务分发与结果收集 API；静态资源服务（视频/音频/文本）。
- 存储：SQLite（推荐）+ 本地文件目录（视频/音频）；一键导出脚本生成训练数据文件。

## 数据组织（无需复杂 ETL）
- 本地数据目录 + manifest.json：一条 match 记录包含 video_path/URL、commentaries[]（id、type=text/audio/both、text_path、audio_path、语言、来源等）。
- 后端启动时读取 manifest 建任务池；前端按接口拿“下一条待标注任务”。

## 关键接口（最小闭环）
- GET /api/tasks/next：返回 match 信息与可选解说源列表（含文本内容或音频 URL，按后端策略可只给文本/只给音频/都给）。
- POST /api/judgments：提交一次排序结果（match_id、commentary_ids 排序数组、可选 reason/flag、user_id、耗时）。
- GET /api/export：导出 JSONL/CSV（行级：match_id、winner/loser 或 rank、commentary 元数据、时间戳、user_id）。

## 是否需要数据库
- 建议用 SQLite：避免并发写 JSON 文件冲突、便于统计进度/去重/回收任务；后续可平滑迁移到 Postgres。
- 若只做单机超小 Demo：也可先 append JSONL，但不利于去重与管理。

## 本周细化任务（按优先级）
1) 设计 manifest.json schema + 准备 5~20 场样例数据（视频 + 2~4 个解说源，文本/音频混合）。
2) 后端：读取 manifest、静态资源路由、tasks/next 与 judgments 入库、export 导出。
3) 前端：视频播放器、解说展示（文本区/音频播放器）、排序 UI（拖拽或“从好到坏”列表）、提交后自动下一条。
4) 任务策略：随机抽样 + 去重（同一用户不重复同一 match）；支持“只文本/只音频/两者”三种模式开关。
5) 统计页（可选）：已标注数、每场收集到的 judgment 数、导出预览。

## 1) manifest.json schema + 样例数据准备（详细）

### 目录约定
- data/manifest.json
- data/matches/{match_id}/video.mp4
- data/matches/{match_id}/commentary/{commentary_id}.wav（或 .mp3）
- data/matches/{match_id}/commentary/{commentary_id}.json（文本/分段文本）

实现：

```c
arena/data/
├── manifest.json              # 全局数据索引
└── matches/                   # 比赛原始素材
    └── test1/                 # Match ID: test1
        ├── video.mp4          # 26s 样例视频
        └── commentary/        # 多源解说文件
            ├── test1_audio1.wav    # 解说甲（由 m4a 转换）
            ├── test1_audio2.wav    # 解说乙（由 m4a 转换）
            ├── test1_audio3.wav    # 解说丙（由 m4a 转换）
            ├── test1_streamerA.json # 文本源 A (segments 格式)
            ├── test1_streamerB.json # 文本源 B
            └── test1_streamerC.json # 文本源 C
```

### manifest schema（核心字段）
- version：字符串
- matches[]：每场比赛一条
  - match_id：全局唯一；建议 date_teamA_teamB（或赛事ID）
  - title/league/date/length_sec：可选元信息
  - video：{path,url,sha256} 三选一或组合
  - commentaries[]（≥2）
    - commentary_id：全局唯一
    - type：text | audio | both
    - language：zh/en/…
    - source：如“官方解说/主播A/字幕转写v1”
    - text：{path,format}；format=plain | segments
    - audio：{path,url,format,sample_rate_hz}；format=wav | mp3
    - alignment：可选 {has_timestamps, start_offset_ms}
- constraints：Demo 默认“同一 match 下 commentary_id 不重复；视频与解说至少一种可访问；文本与音频路径相对 data/”

### 文本文件格式建议
- plain：整段文本
- segments：JSON 数组 [{t_ms, text}]，便于后续做对齐/截取

### 样例数据准备步骤（5~20 场）
1) 先做 5 场最小集：每场 2~3 个解说源（至少 1 文本 + 1 音频），覆盖三种 type 组合。
2) 统一格式：视频 mp4；音频优先 wav（16k/48k 均可，先不强制）；文本 UTF-8。
3) 生成 ID 与文件落盘：按目录约定放置；写 manifest.json 并确保路径可解析。
4) 质量检查清单：能播放视频；每场 commentaries≥2；音频可播放；文本非空；同一 match 的解说内容确属同场（容许少量时间偏移）。
5) 扩到 20 场：优先增加“同场多风格解说”（专业/娱乐/弹幕风），让 ranking 更有区分度。

## 后端代码编写计划（按你当前接口约定：/api/tasks/next、/api/judgments、/api/export，且读取 manifest+静态资源）：

1) 工程骨架  
- 选一个轻量框架FastAPI，拆模块：config、manifest、db、services、routes。  
- 配置项：DATA_DIR、MANIFEST_PATH、DB_PATH、MODE(text/audio/both)、PORT。

2) Manifest 加载与校验  
- 启动时读取 data/manifest.json，做 schema 校验：match_id 唯一、commentary_id 唯一、commentaries≥2、path/url 至少可用一个。  
- 将 manifest 解析为内存索引：match_by_id、commentary_by_id、可抽样 match 列表。

3) SQLite 表设计与初始化（启动时自动建表）  
- matches(match_id,title,meta_json,video_path,video_url)  
- commentaries(commentary_id,match_id,type,language,source,text_path,audio_path,meta_json)  
- judgments(id,match_id,user_id,ranking_json,mode,latency_ms,created_at)  
- assignments(id,match_id,user_id,status,created_at) 用于去重与进度（可选但推荐）。

4) 静态资源服务  
- 以 /static 映射 DATA_DIR，视频/音频通过 URL 直接访问；文本可按需内联或通过 /static 取。

5) GET /api/tasks/next  
- 入参：user_id(从 cookie/header)、mode(可选覆盖全局)。  
- 策略：从未被该 user 标注过的 match 随机挑 1 个；写入 assignments。  
- 返回：match 元信息 + video URL + commentaries 列表（按 mode 过滤；若需要内联文本则读取 text_path 返回 text 或 segments）。

6) POST /api/judgments  
- 校验：ranking 覆盖本任务返回的 commentary_id 且无重复；match_id 合法；长度≥2。  
- 写 judgments；更新 assignments=done；记录 latency_ms。

7) GET /api/export  
- 读取 judgments 联表 commentaries/matches，导出 JSONL/CSV（支持按时间/数量过滤）。  
- 输出字段：match_id、ranking、commentary 元数据、video 引用、user_id、created_at、mode。

8) 最小保障  
- CORS、基础限流（可选）、错误码规范（400/404/409）。  
- 本地自检：启动后跑一个“读 manifest→拿 next→提交 judgments→导出”流程脚本。

## 前端代码规划（任务页）
1) 技术选型与目录  
- 采用 Vite + React + TypeScript（开发快）；目录：src/api、src/pages、src/components、src/state、src/styles。  
- API 封装：getNextTask、postJudgment、exportData；统一处理 X-Assigned-User-Id 作为 user_id。

2) 页面布局（两栏）  
- 左侧边栏：当前 match 信息（title/league/date）、模式切换（text/audio/both）、进度（本地计数）。  
- 左侧边栏底部固定按钮：上一条 / 下一条（不影响“提交后自动下一条”，用于回看与跳过）。
- 右侧主区：顶部视频播放器；下方解说排序区（拖拽列表）。

3) 排序组件（核心交互）  
- 推荐“未排序池 + 已排序列表”：用户点击卡片“加入排序”，并在已排序区拖拽调整；减少解说源较多时的误操作。  
- 数据结构：items = [{commentary_id, type, source, text?, audio_url?}]；ranked = commentary_id[]；unranked = commentary_id[]。  
- UI：已排序区卡片显示序号（index+1）；每次拖拽/增删后立刻重算并更新数字。  
- 防错：提交前强校验 ranked 长度必须等于 commentaries 长度，否则置灰提交并提示“请先排序完所有解说”。  
- 实现：优先用 dnd-kit Sortable；时间不够就先用“上下移动按钮”保底可用。

4) 解说卡片渲染规则  
- type=audio：展示 audio 播放器；type=text：展示文本（支持 segments 渲染为可滚动列表）；type=both：两者都显示。  
- 长文本：默认折叠/展开；segments 以时间排序展示（t_ms 可显示为 mm:ss）。

5) 媒体控制（重要体验）  
- 播放策略：默认“点哪个播哪个”（Solo-Listen），同一时刻仅允许一个解说音频非静音；切换解说时自动静音其他音频。  
- 全局控制：提供“全局播放/暂停”，控制视频与当前选中的解说音频；可选“跟随视频进度”。  
- 时戳跳转：segments 点击某一行时，视频与当前选中音频 seek 到对应 t_ms（容许 start_offset_ms）。

6) 任务流与状态管理  
- 初始化：GET /api/tasks/next 拉取任务并写入 history 栈（用于上一条）。  
- 提交：POST /api/judgments（match_id + order 数组 + latency_ms）；成功后自动 next 并 push history。  
- 上一条：从 history 弹出并恢复当时 order（仅前端回看，不回滚后端）。  
- 下一条：若当前未提交视为“skip”，直接再请求 next（在 flags 里记录 skipped=true）。  
- 预取：用户标注 match A 时，后台预拉一次 next 作为候选 B，并预加载视频首帧/音频头部（利用浏览器缓存）。

7) 接口配合（小改动但很值）  
- GET /api/tasks/next 增加 remaining_count（进度条/剩余任务提示）。  
- POST /api/judgments 增加 browser_info（设备/浏览器信息，便于排查播放卡顿导致的数据质量问题）。

8) 可靠性与体验  
- Loading/错误态：no_tasks、no_tasks_for_mode 友好提示；断网重试。  
- 防重复提交：提交按钮在请求中禁用；返回后再启用。  

组件树（建议）
App → TaskPage → Sidebar(Progress/Mode/PrevNext) + MainArea(VideoPlayer + SortingArea + ActionFooter) → CommentaryCard(AudioDisplay/TextDisplay)

### 实现：

已按 plan.md:L122-L166 的功能要求把前端做成“零构建静态页面”，由后端直接托管（不依赖 Node/Vite），打开即可用。

入口与访问

- 现在访问 http://127.0.0.1:8010/ 会 307 跳转到 http://127.0.0.1:8010/ui/
- Swagger 仍可用： http://127.0.0.1:8010/docs
已实现的前端功能

- 两栏布局：左侧信息栏 + 右侧视频/排序区
- 排序交互：未排序池 + 已排序区；点击“加入排序/移出”；已排序支持拖拽换位（并提供上移/下移保底）；卡片序号实时更新
- 媒体控制：默认“点哪个播哪个”(Solo-Listen)，自动静音其他音频；全局播放/暂停按钮；segments 文本点击跳转 t_ms（视频+当前音频）
- 任务流：提交后自动下一条；左侧底部“上一条/下一条”可回看/跳过；后台预取下一条
- 数据提交：调用 POST /api/judgments （跳过会带 flags.skipped=true ）
代码位置

- UI 静态文件： ui/index.html 、 ui/app.js 、 ui/style.css
- 后端托管 /ui ： main.py （startup 时 mount /ui ，根路径重定向到 /ui/ ）


## 统计页代码规划
### 目标与路由
- /ui/stats/：统计页（卡片网格）
- /ui/stats/match.html?match_id=xxx：单场详情页（按 mode 分组展示 judgments）

### 后端接口补充（最小够用）
1) GET /api/stats/matches
- 返回 matches 列表：match_id、title、league、date、video_url、cover_url、counts{audio,text,both,total}
- cover_url 生成策略：优先使用 video 的第一帧截图（后续可离线生成 jpg），Demo 先用 video_url 作为预览占位或返回同目录 cover.jpg（若存在）。

2) GET /api/stats/match?match_id=xxx
- 返回该 match 的 judgments 明细：按 mode=audio/text/both 分组；每条包含 created_at、user_id、ranking（commentary_id 顺序）、可选 reason/flags。

3) 导出
- 继续复用 GET /api/export?format=jsonl/csv；统计页提供“导出预览”先拉 limit=50 展示。

### 前端实现步骤（零构建方案）
1) 新增静态页面
- ui/stats/index.html + ui/stats/stats.js：渲染卡片网格
- ui/stats/match.html + ui/stats/match.js：渲染单场详情

2) 统计页 UI（卡片网格）
- 每个小窗格（card）展示：video 封面（img 或 video poster）、match_id、title（可选）、counts（audio/text/both/total）。
- 点击卡片跳转到 match.html?match_id=…。
- 顶部筛选：按 league/date 搜索；按 counts 排序（可选）。

3) 详情页 UI（单场）
- 顶部：封面/视频预览 + match_id + 导航返回统计页。
- 三个 Tab：仅文本 / 仅音频 / 混合；每个 Tab 列表展示 judgments（时间、user_id、ranking 序列）。
- ranking 展示：不要只显示 [c1,c2,c3]；改为“阶梯/箭头流”可视化，如：1. 官方解说 → 2. 播主A → 3. AI转写；同时保留原 commentary_id（便于对齐数据集）。
- 一致性分析：在详情页顺便计算该 match 的简单偏好统计：
  - 以“名次越靠前越好”为信号，给每个 commentary 统计 Top-1% 与平均名次（AvgRank）。
  - 若需要更接近二元胜率，可将每条 ranking 转为两两比较，统计每个 commentary 的 pairwise win-rate（对其他解说赢的比例）。
- 预览导出：拉 /api/export?format=jsonl&limit=50 并在页面内展示（折叠显示）。
- 导出按钮：直接打开 /api/export?format=jsonl 与 /api/export?format=csv（两按钮）。

### 导出格式建议（面向数据集）
- 推荐主格式 JSONL：天然支持嵌套字段（match 元信息、commentary 元数据、ranking 数组、mode、flags），适合后续训练/评测流水线。
- 同时提供 CSV：方便 Excel 快速查看与抽样检查；但 CSV 对 ranking 数组/嵌套字段表达不友好，仅作辅助。

### 后端实现微调（挂载与导出快照）
- 挂载建议：/ui 继续托管“任务页+统计页”全部静态文件；如后续引入 Vite 打包产物，可再挂 /app 指向 dist。
- JSONL 导出增强（快照化）：导出时除 id 外，带上当时的“自解释快照”，避免未来 manifest 变更导致旧标注失效：
  - ranking 数组改为 [{rank,id,source,language,type,text_snapshot,audio_url_or_path}]；text_snapshot 建议截断（如前 300 字或前 N 条 segments）。
  - meta 带 match 的 league/date/title/video 引用；保留 mode、labeler_id(user_id)、latency_ms、flags。

## 任务完成态（UI/交互规划）
- 触发条件：GET /api/tasks/next 返回 no_tasks（或 stats.remaining_count=0）；前端停止自动 next，并进入完成态。
- 展示内容：全屏居中“Completion Card”，包含完成徽章、已完成任务数/总数、可选耗时统计、数据导出入口（JSONL/CSV）与“进入统计页”按钮。
- 视觉风格：暗色玻璃拟态卡片（渐变边框+柔光阴影）、大标题+副标题、主按钮高亮（primary）、次按钮幽灵样式；背景使用轻微噪点/渐变，不要花哨动效。
- 交互：提供“重新开始（清空 user_id）”“继续标注（若新增任务）”两种按钮；完成态下禁用排序区与提交按钮，避免误操作。

## 登录与角色（管理员/普通用户）规划

现在开始规划登录角色，管理员和普通角色。管理员可以查看统计页和查看排序数据并导出。普通角色只负责标注数据。设置6个管理员和若干普通角色。管理员角色名分别为wsq, hjn, sy, csk, mjz, xyc，初始密码为123456，普通角色注册昵称必须全局唯一，注册需要管理员同意。根据功能要求初步规划所需步骤，前后端需要什么技术支持，是否需要数据库等

### 目标
- 管理员：可访问统计页、查看排序数据、导出；可审批普通用户注册。
- 普通用户：仅可做标注任务，不可访问统计/导出。

### 是否需要数据库
- 需要：必须用数据库保存用户、密码哈希、角色、注册申请状态、审批记录、会话 token/撤销等。SQLite 足够；未来可迁移 Postgres。

### 后端技术与实现步骤（FastAPI）
1) 用户表设计（SQLite）
- users(id, username UNIQUE, password_hash, role['admin'|'user'], status['pending'|'active'|'disabled'], created_at, approved_by, approved_at)
- sessions(id, user_id, token_hash, expires_at, created_at) 或用 JWT(短期) + refresh token(可撤销)。
- audit_logs(id, actor_user_id, action, target, meta_json, created_at)（审批/禁用/导出行为可追溯）。

2) 密码与安全
- 初始管理员账号：wsq/hjn/sy/csk/mjz/xyc，初始密码 123456（首次登录强制改密：必须实现）。
- 密码存储：bcrypt/argon2 哈希；禁止明文与日志输出；登录限流与失败计数。

3) 认证与授权
- 登录接口：POST /api/auth/login → 设置 HttpOnly cookie（session）或返回 Bearer token。
- 登出接口：POST /api/auth/logout（撤销 session）。
- 角色校验中间件：admin-only 保护 /ui/stats/*、/api/stats/*、/api/export。
- 标注接口：/api/tasks/next、/api/judgments 允许 active 的 user/admin；匿名模式可关闭（Demo 默认关闭匿名）。

4) 注册与审批
- 普通用户注册：POST /api/auth/register {username,nickname,password}；nickname 全局唯一；状态=pending。
- 管理员审批：GET /api/admin/pending_users；POST /api/admin/approve {user_id}；POST /api/admin/reject {user_id,reason}。

5) 导出权限
- /api/export 增加 admin 校验；导出记录写入 audit_logs（谁导出、过滤条件、时间）。

### 前端技术与实现步骤（零构建）
1) 登录页 /ui/login/
- username+password；成功后跳转任务页；失败提示。
- 首次登录改密弹窗（管理员初始密码强制改密）。

2) 注册页 /ui/register/
- 输入昵称（nickname）、密码；提交后显示“等待管理员审批”。

3) 管理员页
- /ui/stats/ 与统计按钮仅对 admin 显示；若非 admin 访问则提示无权限并跳回任务页。
- /ui/admin/（可选）：审批列表（通过/拒绝），展示 pending 用户。

### 账号初始化
- 启动时自动 seed 6 个管理员（若不存在则创建），role=admin,status=active；并强制 first_login_change_password=true。

### 落地建议（适用且推荐）
1) Session 优先（不选 JWT）
- 采用 HttpOnly + SameSite=Lax Cookie 存 Session ID（UUID）；sessions 表可撤销/封禁即时生效（禁用用户时删除其 sessions）。

2) 密码哈希与强制改密
- 使用 passlib[bcrypt]（或 argon2）存 password_hash；新增 needs_password_reset 字段，管理员初始密码登录后必须走改密接口才能继续标注/访问管理页。

3) judgments 与 users 关联
- judgments.user_id 存 users.id（整数/UUID），避免字符串漂移；同时保留 labeler_nickname 快照字段用于导出稳定性（可选）。

4) 鉴权接口与前端可见性控制（零构建）
- 增加 GET /api/auth/me → {role,status,nickname,needs_password_reset}，前端用它控制 .admin-only 的显示/隐藏，未登录跳 /ui/login/。

5) 审计与风控
- audit_logs 记录审批/禁用/导出；登录接口增加基础防爆破（失败计数+指数退避或最小 1s 延迟），并限制同 IP/同账号频率（Demo 可先简单实现）。

6) 配置与密钥
- 不在代码硬编码密钥；使用环境变量（如 SESSION_SECRET/COOKIE_KEY）；本地用 .env（不提交仓库）加载。

### 任务清单（账户系统与安全）
- DB Migration：创建 users/sessions/audit_logs，完成管理员 seed。
- Auth Middleware：基于 Cookie 的鉴权依赖（require_user / require_admin）。
- First-Login：needs_password_reset 拦截 + 改密接口 + 前端强制改密提示。
- Register Flow：register → pending → admin approve/reject + 审计。
- Admin Console（可选）：/ui/admin/ 审批面板；统计/导出入口对非 admin 隐藏。

已按 plan.md:L239-L270 和 plan.md:L285-L310 把“用户系统 + 角色权限 + 注册审批 + 首登强制改密 + Session Cookie”落到代码里了。

后端（FastAPI + SQLite）

- 新增表与逻辑（users/sessions/audit_logs + 密码哈希 + 管理员 seed）： db.py
- 新增认证/管理接口与权限控制、并把标注接口改为必须登录：
  
  - GET /api/auth/me
  - POST /api/auth/login （写入 HttpOnly Cookie： cr_session ）
  - POST /api/auth/logout
  - POST /api/auth/register （创建 pending 用户，昵称全局唯一）
  - POST /api/auth/change_password （needs_password_reset 时可直接改密）
  - GET /api/admin/pending_users （admin）
  - POST /api/admin/approve （admin）
  - POST /api/admin/reject （admin）
  - /api/tasks/next 、 /api/judgments ：仅 active 用户可用
  - /api/stats/* 、 /api/export* ：仅 admin 可用（并写 audit export 记录）
  - UI 路由访问拦截：未登录访问 /ui/ 自动跳 /ui/login/ ；非 admin 访问 /ui/stats/ 、 /ui/admin/ 会被跳回 /ui/
  - 代码位置： main.py
- 管理员初始化（若不存在则创建，needs_password_reset=1）： wsq,hjn,sy,csk,mjz,xyc ，初始密码 123456 （仅存哈希，不存明文）
前端（零构建静态页）

- 登录页： /ui/login/ （包含“首次登录强制改密”流程）
- 注册页： /ui/register/ （提交后等待审批）
- 管理员审批页： /ui/admin/
- 任务页已接入鉴权：未登录会跳转；统计/导出按钮仅 admin 可见： app.js 、 index.html 、 style.css
使用方式

- 启动后先访问 /ui/login/ ，用管理员 wsq / 123456 登录，会提示改密；改密后进入任务页
- 普通用户在 /ui/register/ 注册后为 pending，需要管理员到 /ui/admin/ 审批通过才能登录标注
- 管理员才能访问 /ui/stats/ 、导出 /api/export

## 管理员端页面与消息中心（规划）
### 可见页面（除登录页外均带统一左侧边栏）
- /ui/stats/：统计页（默认落地页），边栏含：统计页、消息中心、退出登录。
- /ui/admin/ 或 /ui/inbox/：消息中心（注册申请 + 广播消息），边栏含：统计页、消息中心、退出登录。
- /ui/stats/match.html：单场详情页（统计子页），同样使用统一边栏。

### 左侧边栏规范（Admin Layout）
- 固定区域：顶部显示管理员昵称/账号；中部导航按钮；底部固定“Log out”按钮。
- Log out 行为：调用 POST /api/auth/logout，清 cookie，跳转 /ui/login/。
- 导航按钮：
  - 统计页：跳 /ui/stats/
  - 消息中心：跳 /ui/inbox/（或复用 /ui/admin/）

### 消息中心功能
1) 注册申请队列
- 展示 pending 用户列表（昵称、申请时间）；每条有“同意/驳回”按钮；操作完成后从列表移除。

2) 广播消息（管理员间同步）
- 目标：当任一管理员处理申请后，所有管理员消息中心都能看到一条事件：“{admin} 处理了 {nickname} 的注册申请：同意/驳回”。
- 最小实现（Demo）：后端写 audit_logs(action=approve_user/reject_user)；消息中心轮询 GET /api/admin/messages?since_id=xxx 获取新增事件。
- 进阶实现（更实时）：SSE /api/admin/stream（EventSource）推送 audit 事件到所有管理员；前端消息中心订阅并实时追加。

### 后端接口补充（Admin）
- GET /api/admin/messages?after_id=xxx：返回 audit_logs 中与审批相关的事件列表（含 id、actor、action、target、created_at、meta）。
- POST /api/admin/approve 与 /api/admin/reject：在审批成功后写入 audit_logs（已有），并作为消息中心事件源。

### 前端落地步骤（零构建）
1) 抽一个复用的 sidebar.js（Admin-only）负责：渲染边栏、绑定 logout、导航高亮、加载 /api/auth/me。
2) stats 页与 match 详情页：引用 sidebar.js 并用同一 DOM 结构包裹主内容。
3) inbox 页：展示 pending_users + messages 流；实现轮询或 SSE，支持 after_id 增量拉取。

管理员端页面与消息中心（规划）
1. 页面布局与侧边栏规范
除登录页外，管理员端页面（统计页、详情页、消息中心）采用统一侧边栏（Sidebar）布局：

常驻元素：

Header: 管理员昵称 (e.g., Admin: wsq)。

Nav Group: 统计页 (Icon: Chart)、消息中心 (Icon: Bell，含未处理申请数红点)。

Footer: Log out 按钮（红色醒目）。

交互逻辑：

Log out: 调用 POST /api/auth/logout 清除 Session，强制跳转至 /ui/login/。

零构建实现：通过 sidebar.js 动态插入 HTML 到页面的 #sidebar-root 容器，利用 URLSearchParams 保持子页面导航高亮。

2. 消息中心 (Inbox) 核心逻辑
消息中心承载“审批流”与“操作审计广播”两大功能：

注册申请处理：

展示 status='pending' 的用户列表。

管理员操作：点击“同意”或“驳回”，触发 POST /api/admin/approve 或 reject。

操作广播 (Audit Broadcast)：

数据源：从 audit_logs 表提取 approve_user / reject_user 动作。

展现形式：时间轴消息流。例如：“管理员 xyc 处理了 user_test 的申请：同意 (2026-04-08 10:00)”。

同步机制：

前端：页面加载时拉取全量，随后每 30s 轮询 GET /api/admin/messages?after_id=xxx。

后端：审批接口在修改 users 表状态后，必须同步向 audit_logs 插入包含操作员 ID 和结果的记录。

3. 后端接口补充 (Admin-Only)
GET /api/admin/pending_users: 返回待审批用户。

GET /api/admin/messages:

查询 audit_logs 表中 target_type='user_registration' 的记录。

支持 after_id 过滤，确保前端仅增量获取最新的审批动态。

POST /api/admin/approve(reject):

核心逻辑：update users set status=... + insert into audit_logs ...。

4. 前端落地要点
共享脚本 sidebar.js：

JavaScript
// 初始化侧边栏并检查权限
async function initAdminSidebar() {
    const user = await fetch('/api/auth/me').then(r => r.json());
    if (user.role !== 'admin') window.location.href = '/app/task'; // 越权重定向
    // 动态注入 DOM 并绑定 Logout 逻辑
}
Inbox 渲染：使用 template 标签或原生字符串拼接实现申请卡片与广播消息的列表渲染。

💡 针对该规划的“避坑”建议：
防止重复处理：由于是广播机制，当 A 管理员点击同意时，B 管理员的页面可能还没刷新。后端 approve 接口需校验用户状态，若已被处理则返回 409 Conflict，前端提示“该申请已被处理”。

红点提醒：在侧边栏的“消息中心”按钮旁加一个数字红点，实时性要求不高的话，可以随导航栏初始化请求一次 pending_users 的 count 即可。

这套“零构建”方案非常适合你现在的开发节奏。你打算先写 sidebar.js 的通用模板，还是先去后端实现 audit_logs 的存储逻辑？

### 实现

已实现的管理员端页面结构

- 统一 Admin Sidebar（除登录/注册页外）：统计页、单场详情页、消息中心都带左侧边栏（统计页/消息中心/Log out + pending 红点数）
- Log out：调用 POST /api/auth/logout 后跳转 /ui/login/
消息中心（/ui/admin/）

- 待审批用户列表：同意/驳回（若已被其他管理员处理会返回 409，并提示“已被处理”）
- 广播动态：轮询 GET /api/admin/messages?after_id=... ，显示“{admin} 处理了 {nickname} 的注册申请：同意/驳回（含原因）”，所有管理员都可看到
后端新增/更新

- 审批幂等：重复处理返回 409（ db.py + main.py ）
- 广播消息接口： GET /api/admin/messages?after_id= （ main.py ）
- 消息源：audit_logs（approve_user/reject_user）
前端新增/更新

- 统一边栏脚本： sidebar.js
- 统计页套 Admin Shell： stats/index.html
- 单场详情套 Admin Shell： stats/match.html
- 消息中心升级为“审批 + 广播”双栏： admin/index.html 、 admin.js
- Admin Shell 样式追加在： style.css
你重启后端后，用管理员登录会进入：

- 统计页： /ui/stats/
- 消息中心： /ui/admin/

## 管理员端实现完善（适用建议与待办）
### 关键检查（适用）
1) Cookie Path
- 登录接口 set_cookie 必须 path="/"（避免在 /ui/stats/ 与 /ui/admin/ 间丢 Session）；当前实现已设置 path="/"，后续不要改成子路径。

2) 轮询风暴与 DOM 增长
- 消息中心轮询只做 after_id 增量；前端追加广播消息时限制最多保留最近 50 条（超出则删除旧节点），避免长时间挂页内存上涨。

3) 越权闪烁（FOUC）
- Admin 页面在 sidebar.js 鉴权完成前先隐藏 body（或加 loading class）；确认 admin 后再显示，非 admin 直接重定向。

### 细节优化（建议做）
1) 红点同步
- GET /api/admin/messages 返回体附带 pending_count（或单独 /api/admin/pending_count）；sidebar.js 用同一次请求更新红点，避免多接口/多轮询。

2) 409 后 UI 一致性
- approve/reject 返回 409 时，前端应立即从 pending 列表移除该卡片（并提示“已被其他管理员处理”），避免用户反复点击。

3) 广播自解释（快照）
- audit_logs.meta 里写入 nickname 快照（approve/reject 时从 users 表取出或由前端提交），广播消息用 nickname 展示，避免后续数据清理导致“未知用户”。

### Demo 演示脚本（建议）
- 用 Chrome/Edge 分别登录 wsq 与 hjn，打开 /ui/admin/；用一个新注册用户触发 pending；A 通过后，B 轮询后收到广播；B 再点同一用户触发 409，界面自动移除并提示。

### debug

先判断是否真 bug（高概率是“同浏览器共享 Cookie”导致的正常现象）

在 wsq 页面点击“通过”前，先在该页面手动打开 GET /api/auth/me（新标签也行），确认返回的 username 是否仍是 wsq；如果已经变成 hjn，说明 wsq 页实际带的是 hjn 的会话 Cookie。
复现与定位步骤

同一浏览器/同一配置文件：先登录 wsq，再登录 hjn（任意标签页），回到 wsq 页审批一次，看广播是否显示 hjn。
打开开发者工具 Network：看 wsq 页调用 /api/admin/approve 请求头里的 Cookie: cr_session=...，以及两次登录 /api/auth/login 响应里的 Set-Cookie 是否把 cr_session 覆盖成同一个值。
查库核对：查看 sessions 表该 token_hash 对应的 username，以及 audit_logs 里该条记录的 actor_username，确认“广播显示谁”完全等于后端判定的当前用户。
如何正确做“双管理员同时在线”测试

用不同浏览器（Chrome + Edge）或同浏览器不同 Profile/无痕窗口分别登录 hjn/wsq；因为 Cookie 以“域名维度”共享，同域下无法在两个 tab 维持两个独立登录态。
如果要产品级避免误解（可选改进方向）

管理后台显著展示当前登录账号（并提供“一键切换账号/退出”），审批前再调用一次 /api/auth/me 做二次确认并在按钮旁显示将以谁的身份操作。

## 普通角色端功能重规划（修复当前 3 个问题）
### 目标行为
1) 未登录用户与管理员：统一停留在 /ui/login/（管理员登录后进 /ui/stats/，普通用户登录后按是否有待标注任务分流）。
2) 普通用户登录后：
- 若存在未标注任务：直接进入标注页 /ui/，开始标注“该用户未标注的数据”；左侧边栏仅提供 Log out（不出现统计页入口）。
- 若无未标注任务：进入消息中心 /ui/user/（普通用户专用），展示“最近一次新增任务时间 + 新增条数/待标注条数”，并提供“去标注”按钮（当有新任务时出现）。

### 页面/路由
- /ui/login/：登录（admin/user 共用）；登录成功后前端先调用 /api/auth/me 判断角色。
- /ui/：标注页（仅 user）；页面加载时先请求 /api/tasks/next：
  - 200：渲染并进入标注流程；
  - 404 no_tasks：自动跳转 /ui/user/（不显示“全部完成”的错误状态）。
- /ui/user/：消息中心（仅 user）；展示：
  - pending_count（当前待标注条数）
  - last_manifest_updated_at（任务池最近更新时间）
  - last_seen_at（用户上次查看消息中心的时间，用于计算“新增 x 条”）
  - 动作：Log out；当 pending_count>0 显示“去标注”跳转 /ui/

### 接口最小增补（建议）
- GET /api/user/inbox（user-only）：返回 pending_count、last_manifest_updated_at、last_seen_at、new_since_last_seen；同时可选提供 POST /api/user/inbox/seen 更新 last_seen_at。
  - pending_count 计算逻辑与 /api/tasks/next 一致：manifest.matches - judgments(match_id,user_id)。
  - last_manifest_updated_at 可在后端启动/同步 manifest 时写入 settings 或 db 表。

### 修复现有 3 个问题的落点
1) “新用户显示已完成”：标注页启动必须以 /api/tasks/next 结果为准；无任务则跳 /ui/user/，有任务则直接开始，不依赖本地缓存状态。
2) “重新开始跳注册页”：重新开始仅清理本地 localStorage（历史/排序草稿）并跳回 /ui/；不触碰 /ui/register/。
3) “普通用户显示统计按钮”：前端按钮渲染以 me.role 严格控制；普通用户侧边栏只有 Log out，不注入 admin sidebar。

### 补充建议 1：路由守卫“硬核化”（后端同步收紧）
- 原则：前端 me.role 只负责体验，权限必须由后端兜底。
- API：所有 /api/stats/*、/api/export、/api/admin/* 在 Python 端强制校验 user.role=='admin'，否则直接 403（避免通过地址栏/抓包绕过 UI）。
- UI：/ui/stats/*、/ui/admin/* 在服务端重定向层面也要做 admin 校验（避免先渲染再跳转造成信息闪烁）。

### 补充建议 2：解决“任务抢占/重复分发”（多用户同时在线）
- 目标：提高覆盖率，尽量避免同一时间大量用户拿到同一个 match；但不改变“每个用户最终都要标完整个任务池”的目标，只影响分发顺序。
- 方案：在 /api/tasks/next 引入“软锁”分配：
  - assignments 记录：{user_id, match_id, status='assigning', expires_at=now+1min}；提交 judgment 时将其置为 done。
  - 选题时排除：已被该用户标注的 match + 当前被其他用户 assign 且未过期的 match（过期自动可重新分配）。
  - 实现要点：对 (match_id) 加唯一约束或用事务保证“插入成功才算拿到锁”，失败则重挑。

### Bug 归因：新用户“显示已全部标注”的真实原因（与他人是否标注无关）
- 现象：新注册/新批准的普通用户进入后提示“全部完成/无待标注”，但 manifest 明明有数据。
- 根因（高概率）：历史版本在无登录态时允许用任意 user_id 写 judgments（如 anon/浏览器生成 id）；而 judgments.user_id 目前不是外键，不保证只来自 users 表。若新用户注册的 nickname/username 恰好与历史 judgments.user_id 相同，则后端按“已标注集合=SELECT DISTINCT match_id FROM judgments WHERE user_id=?” 计算，会把旧数据当成该新用户的标注结果，pending_count 直接变 0。
- 快速验证：在 SQLite 执行 `SELECT COUNT(*) FROM judgments WHERE user_id='<新用户名>';` 若 >0，则该用户并非“新”，而是与旧匿名数据撞名。
- 修复方向：将 users.username 改为不可猜的内部 id（uuid），nickname 仅展示；或为 judgments.user_id 增加外键约束并迁移旧数据（匿名标注统一归档到固定账号）。

但除了撞名，从系统工程角度看，还有 **3 个极高概率的潜在 Bug 诱因**：

### 1. 其他可能的 Bug 原因

* **SQL 逻辑错误（聚合漏算）**：
    后端在计算 `pending_count` 时，可能错误地使用了 `INNER JOIN` 关联了 `assignments` 或 `judgments` 表。如果新用户在这些表里**没有记录**，关联查询的结果集会直接返回空，导致后端逻辑误判为“数据池已干涸”。
* **缓存穿透/初始化失败**：
    前端可能在 `localStorage` 或全局状态中缓存了 `isFinished: true` 的标记。如果新用户登录后，前端没能成功触发 `/api/tasks/next` 的初次拉取，或者接口因为权限校验延迟返回了 `401/403`，前端逻辑可能默认退避到了“任务已完成”的兜底状态。
* **Manifest 加载作用域问题**：
    后端在启动时是否正确地将 `manifest.json` 加载到了每个用户可见的“任务池”中？如果 `tasks/next` 的逻辑是基于内存中某个被修改过的 `list`，而这个 `list` 在之前的测试中被全局标记为了 `done`（没做用户隔离），那么新用户看到的也是“残羹冷饭”。

---

### 2. 补充至 `plan.md` 的内容

你可以将以下分析追加到 `plan.md` 的 **“Bug Log & Fix”** 章节中：

## Bug 归因：新用户“显示已全部标注”的深度分析

### 1. 核心原因：ID 碰撞与数据污染
- **逻辑**： judgments 表中的 `user_id` 字段缺乏外键约束，且早期匿名测试占用了大量简单字符串 ID（如 `guest`, `123`）。
- **后果**：新用户若注册了相同的 ID，后端执行 `NOT IN (SELECT match_id FROM judgments WHERE user_id=?)` 时会直接命中历史垃圾数据，导致任务池被错误置空。

### 2. 次要原因：SQL 关联查询陷阱
- **逻辑**：在计算 `pending_count` 时，若使用了 `SELECT count(*) FROM matches m JOIN assignments a ON ...`。
- **后果**：对于没有任何 assignment 记录的新用户，`JOIN` 结果为空，导致 `count` 结果为 0，触发前端“无任务”跳转。

### 3. 修复与防御策略
- **数据层**：
  - [ ] **UUID 化**：将 `users.id` 改为内部生成的 UUID，`judgments.user_id` 必须引用此主键。
  - [ ] **清理**：清空所有 `user_id` 不在 `users` 表中的历史垃圾数据。
- **逻辑层**：
  - [ ] **左连接查询**：确保 `pending_count` 的 SQL 使用 `LEFT JOIN` 或独立的 `NOT EXISTS` 子查询。
  - [ ] **启动校验**：后端启动时打印 `manifest` 总数与 `judgments` 总数，确保基数正确。

---

### 3. 归因验证小贴士



你可以在数据库里跑一下这个“灵魂拷问” SQL：
```sql
-- 看看有多少 judgments 是属于不存在的用户的
SELECT user_id, COUNT(*) FROM judgments 
WHERE user_id NOT IN (SELECT id FROM users)
GROUP BY user_id;
```
如果结果不为空，那就说明你的数据库里确实住着很多“幽灵”，它们吞掉了新用户的任务。

**你的 `judgments` 表现在是用 `username` 还是 `id` 关联的？如果是 `username`，建议立刻按上述规划改为不可重复的内部 ID。**

### 跳转界面 Bug（新用户仍停留在“任务已完成”浮层）
- 现象：新用户登录后仍看到旧的“任务已全部完成（0/0）”浮层，且不按新逻辑跳转 /ui/user/ 或进入标注页。
- 排查结论：这不是后端 pending_count 的问题，而是前端页面被浏览器缓存/回退缓存（bfcache）恢复了“上一次会话的 DOM 状态”，导致 JS 初始化逻辑（checkAuth→loadFirstTask→按 404/409 跳转）没有重新执行，页面停留在旧浮层。
- 如何确认：打开 DevTools→Network 看是否完全没有请求 /ui/app.js 与 /api/tasks/next；或在 /ui/app.js 中对比当前代码是否包含“404/409 直接跳 /ui/user/”逻辑。
- 修复：对 /ui/*.js 与 /ui/*.html 强制 no-store 响应头；并在 app.js 监听 pageshow（e.persisted=true 时强制 reload），确保从 bfcache 恢复时也会重新跑鉴权与分流逻辑。

## 变更：取消“软锁”机制（只要没被自己标注就可领取）
### 目标
- 不考虑“是否被其他人标注/占用”，任务分发仅按“当前用户是否已标注 judgments”决定。
- 结果：多用户同时在线允许拿到同一个 match（顺序/覆盖率不再优化），但不会出现 all_tasks_locked/409 导致新用户无任务可做。

### 需要修改的代码位置（检查清单）
1) 后端任务分发
- 文件：app/main.py
- 修改点：GET /api/tasks/next
  - 移除：cleanup_expired_assignments、try_lock_assignment、get_active_assignment、expires_at、409 all_tasks_locked 分支
  - 保留/恢复：按 judged 集合过滤 candidates，随机挑选一个返回；必要时可写入 assignments 仅作“访问记录”（不参与分发逻辑）

2) 后端 DB/迁移（可选最小化）
- 文件：app/db.py
- 修改点：
  - assignments 表仍可保留（历史兼容），但不再创建/依赖 “assigning + expires_at + 唯一锁索引” 作为分发前提
  - 可删除/停用函数：cleanup_expired_assignments、try_lock_assignment、get_active_assignment（或保留但不再被调用）

3) 普通用户前端分流
- 文件：ui/app.js
- 修改点：
  - 移除对 409 all_tasks_locked 的特殊跳转（/ui/user/?reason=locked）
  - 仅保留：404 no_tasks → /ui/user/（表示该用户已全部标完）
- 文件：ui/user/user.js
  - 移除 reason=locked 提示文案（因为不再会出现“被他人占用而无任务”）

### 验证步骤（手动）
- 用两个普通用户同时打开 /ui/：
  - 两人都应能拿到任务（可能是同一个 match，属于预期）
  - 当某个用户自己把全部 match 都标完后：/api/tasks/next 返回 404 no_tasks，该用户应跳转 /ui/user/ 并显示 pending_count=0

### Bug 归因：点“去标注”仍看到“已标注完成”浮层
- 对照 L564-573 三类可能性：
  - SQL 聚合漏算：当前 pending_count 与 /api/tasks/next 都不依赖 INNER JOIN 聚合，因此不符合该类特征。
  - 缓存穿透/初始化失败（命中）：/ui/ 入口实际路径是 /ui/（不是 /ui/index.html），先前只对 *.html/*.js 加 no-store，导致 /ui/ 的 HTML 有机会被缓存或被 bfcache 恢复成“浮层已显示”的 DOM；同时若 app.js 没重新执行（或执行的是旧版本），就会一直停留在“已完成 0/0”。
  - Manifest 作用域问题：manifest/matches 在 DB 中存在且 commentaries>=2（可领任务），因此不是任务池被清空。
- 真正问题：/ui/ HTML 未被强制 no-store + 前端未在启动时强制隐藏 completionOverlay，导致旧 DOM 状态残留。
- 修复：后端对所有 /ui/ 返回的 text/html/text/javascript 统一加 no-store；前端启动立刻 `completionOverlay.hidden=true`，确保即使页面被恢复也会复位。
（实现备注）当前实现已将 no-store 扩展为所有 /ui/* 响应，并在 app.js 中提供 uiReset() 于启动与 DOMContentLoaded 复位浮层状态。

通过分析你提供的 `main.py` 代码，我发现了导致新用户一进入就显示“已全部标注完成”的**致命逻辑漏洞**。

问题的核心在于 `get_next_task` 函数中对“候选任务”的过滤逻辑，以及数据查询时的“短路”行为。

---

### 1. 致命 Bug 定位：`insert_assignment` 的位置错误

在你的 `get_next_task` 函数中（约 L467-L485）：

```python
with connect(settings.db_path) as conn:
    judged = list_judged_match_ids(conn, str(user["username"])) # 1. 获取已标 ID
    candidates = [m for m in manifest.matches if m.match_id not in judged] # 2. 过滤
    
    if not candidates:
        raise HTTPException(status_code=404, detail="no_tasks") # 3. 如果没候选，报 404

    match = random.choice(candidates) # 4. 随机选一个
    # ... 过滤解说词逻辑 ...
    
    # --- BUG 就在这里 ---
    insert_assignment(conn, match.match_id, str(user["username"]), "assigned") 
```

#### 为什么会导致“全部标注完成”？
1. **数据库连接的作用域限制**：你的 `with connect(...) as conn` 块在执行完 `insert_assignment` 后就结束并**提交（Commit）**了。
2. **前端并发/重复请求**：新用户进入页面时，前端通常会触发 `get_next_task`。
3. **软锁（Assignment）变成了硬锁**：虽然你引入了方案一的 `assignments` 表，但你的**过滤逻辑（Step 2）根本没有排除掉已分配但未完成的任务**。
4. **真正的 Bug 触发点**：如果你在 `db.py` 里的 `list_judged_match_ids` 函数逻辑写得不严谨（比如它同时查询了 `judgments` 表和 `assignments` 表），或者前端在加载过程中触发了多次请求，就会发生以下链式反应：
   - 第一次请求：成功分配 Match A，写入 `assignments`。
   - 第二次请求（或页面刷新）：由于某种逻辑原因，系统认为 Match A 已经是“处理中”，如果 SQL 过滤不当，新用户就会陷入“无任务可选”的境地。

---

### 2. 更隐蔽的原因：SQL 过滤逻辑“撞名”

检查你的 `app/db.py`（虽然你没发这个文件，但根据 `main.py` 的调用可以推断）：

如果 `list_judged_match_ids(conn, str(user["username"]))` 的内部实现是：
`SELECT match_id FROM assignments WHERE user_id = ?` 
而不是 
`SELECT match_id FROM judgments WHERE user_id = ?`

**那么 Bug 就实锤了：**
一旦 `get_next_task` 被调用，它会立即往 `assignments` 塞入一条记录。如果用户此时网络抖动刷新了页面，第二次请求调用 `list_judged_match_ids` 时，刚才分配给他的任务就会出现在“已完成/已排除”列表里。

对于一个只有 1 场比赛的测试环境，新用户点进去的一瞬间，唯一的任务就被标记为 `assigned` 并被过滤掉了，于是直接弹出“全部标注完成”。

---

### 3. 补充至 `plan.md` 的内容

## Bug 归因：新用户进入即显示“标注完成”

### 1. 核心原因：任务分发与过滤逻辑的“时差”冲突
- **现象**：新用户请求 `next` 接口后，后端立即写入 `assignments` 表，但过滤逻辑 `list_judged_match_ids` 可能错误地包含了“已分配”的任务。
- **后果**：用户在任务提交（Judgment）之前，只要刷新页面或触发二次请求，刚分配的任务就会因为“已在分配表中”而被 `candidates` 排除。若任务池较小，会导致 `candidates` 瞬间为空。

### 2. 实现层面的漏洞
- **SQL 过滤不彻底**：`get_next_task` 仅排除了 `judgments` 表（已提交），未正确处理 `assignments`（处理中）的幂等性。
- **缺乏“断点续传”**：当用户已经有一个 `assigned` 状态的任务时，接口没有优先返回这个任务，而是尝试找新任务并再次触发排除逻辑。

### 3. 修复方案
- [ ] **重构过滤 SQL**：明确区分 `judged`（已标）和 `assigning`（正在标）。
- [ ] **优先返回已有任务**：在 `get_next_task` 顶部增加逻辑：若该用户在 `assignments` 中有未过期的 `assigned` 任务，直接返回该任务，不再随机挑选。
- [ ] **清理过期锁**：增加定时或即时的过期检查，确保异常退出的任务能重回池子。

---

### 💡 建议修复代码片段：

在 `main.py` 的 `get_next_task` 中，你应该先查有没有“正在标”的：

```python
# 1. 看看有没有还没标完的“老任务”，有就直接还给他
existing_task = get_unfinished_assignment(conn, str(user["username"]))
if existing_task:
    match = manifest.match_by_id.get(existing_task)
    # ... 直接返回 ...

# 2. 如果没有老任务，再去 candidates 里挑，挑的时候记得避开别人正在标的
# (即你方案一的软锁逻辑)
```

**你现在 `db.py` 里的 `list_judged_match_ids` 是不是把 `assignments` 表的数据也查出来了？如果是，请把它改回只查 `judgments`。**