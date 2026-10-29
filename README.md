# activity-66-export

66th & 2nd 市集 —— **参展申请导出后台**（只读，独立服务）。

勾选 → 导出 **Excel**（三个 sheet）/ 打包下载 **ZIP**（Excel + 商家上传的原附件）。
**不写库、不动文件**，和采集服务完全隔离。

![登录](docs/screenshot-login.png)
![主界面](docs/screenshot-main.png)
![手机号展开](docs/screenshot-phone.png)
![导出二次确认](docs/screenshot-confirm.png)

---

## 1. 先看效果（不用数据库）

```bash
./run-demo.sh
```

脚本会自动建虚拟环境、装依赖、造 12 条假数据、启动服务。
想换端口：`PORT=8020 ./run-demo.sh`；服务器上允许外部访问：`HOST=0.0.0.0 ./run-demo.sh`。

也可以手动来：

```bash
pip install -r requirements.txt
python -m app.demo            # --port 8010 --host 127.0.0.1 可改
```

浏览器打开 **http://127.0.0.1:8010/?token=demo**

会自动造 12 条假报名 + 16 个假附件，直接能看到完整界面。想重造加 `--reset`。

---

## 2. 接到真实数据

```bash
cp .env.example .env
vim .env
```

必改三项：

```ini
DATABASE_URL=mysql://exporter:<密码>@127.0.0.1:3306/verifly_signup?charset=utf8mb4
UPLOAD_DIR=/data/uploads
EXPORT_TOKEN=<一个足够长的随机串>
```

然后：

```bash
docker compose up -d --build      # 或 docker run，见 docs/DEPLOY.md
```

打开 `https://export.你的域名.com`，输入 `EXPORT_TOKEN` 进入。

> 也支持直接把 token 拼在地址上：`https://export.域名.com/?token=xxx`，进入后会自动从地址栏抹掉。

---

## 3. 界面能做什么

| 区域 | 功能 |
|---|---|
| 顶部统计 | 报名总数 / 附件数量 / 附件总体积 |
| 筛选 | 提交时间范围、区域（A/B/C）、关键词（品牌/联系人/手机） |
| 表格 | ID、时间、品牌、联系人、**手机（默认脱敏，点「显示」才展开）**、城市、意向区域、经营品类、带货件数、**附件数与大小** |
| 勾选 | 单条勾选 / 全选本页；**达上限后其余复选框自动置灰** |
| 底部操作条 | `已选 3 / 10 条 · 合计 5.3 MB` + 「导出 Excel」「打包下载 ZIP（含附件）」 |
| 安全阀 | 附件合计超过 `MAX_EXPORT_MB` 时，打包按钮自动禁用 |
| 导出确认 | 点导出/打包先弹确认框：显示已选条数、附件数、体积，并提示「会读取线上库与附件目录，可能影响线上响应速度」 |

## 4. 导出产物

**Excel**（`.xlsx`，三个 sheet）

| Sheet | 内容 |
|---|---|
| 报名清单 | 一行一个商家：ID、时间、品牌、联系人、手机、微信、邮箱、城市、主体类型、是否首次、经营品类、意向区域、带货件数、价格区间、商品结构四项百分比、附件数与大小、来源 |
| 代表商品 | 一行一件代表商品：报名ID、品牌、商品及品牌、年代/系列、状态及来源、拟售价 |
| 附件清单 | 一行一个附件：报名ID、品牌、文件名、类型、大小、上传时间、**包内路径**、磁盘状态 |

表头加粗上色、冻结首行、自动筛选、隔行底色 —— 拿到就能直接用。

**ZIP**（Excel + 附件原件）

```
导出_20261029_1155/
├── 报名清单_20261029_1155.xlsx          ← 三个 sheet 的汇总表
├── 001_拾光中古/
│   └── 附件/
│       ├── 拾光中古_1.zip               ← 商家上传的原文件，一字节不改
│       ├── 拾光中古_2.zip
│       └── 拾光中古_3.zip
├── 002_旧物研究所/
│   └── 附件/
└── _缺失附件清单.txt                     ← 仅当库里有记录但磁盘缺口时才出现
```

打包是**流式**的：边读磁盘边发 HTTP，不落临时文件，内存恒定几 MB。

## 5. 配置项

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `DATABASE_URL` | — | 建议用**只读账号**（只给 `SELECT`） |
| `UPLOAD_DIR` | `/data/uploads` | 挂载时加 `:ro` |
| `EXPORT_TOKEN` | — | **必填**，不填则拒绝一切导出（503） |
| `LOGIN_MAX_ATTEMPTS` | `10` | 同 IP 连续输错几次锁 5 分钟 |
| `MAX_EXPORT_RECORDS` | `10` | 单次最多勾选几条 |
| `MAX_EXPORT_MB` | `300` | 单次附件合计上限 |
| `PAGE_SIZE` | `20` | 每页条数 |
| `MAX_PAGE_SIZE` | `100` | 接口允许的最大 page_size |
| `SITE_TITLE` | `66th 参展申请 · 导出后台` | 页面标题 |
| `ALLOWED_ORIGINS` | `*` | 跨域白名单 |

改完重启容器生效，不用重新构建。

---

## 6. 接口

除 `/healthz` 与 `/` 外都需要鉴权：`Authorization: Bearer <EXPORT_TOKEN>` 或 `?token=<EXPORT_TOKEN>`。

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/healthz` | 健康检查（含 DB ping） |
| `POST` | `/api/v1/auth` | 校验 token，返回限制配置 |
| `GET` | `/api/v1/summary` | 总览统计 |
| `GET` | `/api/v1/applications` | 列表，支持 `keyword` / `zone` / `date_from` / `date_to` / `with_files` / `page` |
| `GET` | `/api/v1/applications.xlsx?ids=1,2` | 导出 Excel（三个 sheet） |
| `GET` | `/api/v1/bundle.zip?ids=1,2` | 打包下载（Excel + 附件原件） |

```bash
# 命令行导出（不走界面）
TOKEN=你的token
curl -H "Authorization: Bearer $TOKEN" \
  "https://export.域名.com/api/v1/applications.xlsx?ids=1,2,3" -o 报名清单.xlsx

curl -H "Authorization: Bearer $TOKEN" \
  "https://export.域名.com/api/v1/bundle.zip?ids=1,2,3" -o 打包.zip
```

---

## 7. 三种启动方式

### ① 本地预览（造数据，不用连库）

```bash
./run-demo.sh                                   # → http://127.0.0.1:8010/?token=demo
PORT=8020 ./run-demo.sh                         # 换端口
HOST=0.0.0.0 ./run-demo.sh                      # 服务器上对外预览
```

> 端口被占用时会**自动打印并结束占用进程**（先 `kill`，2 秒不退再 `kill -9`）。
> 不想让它动别的进程就加 `NO_KILL=1 ./run-demo.sh`，此时只报错退出。

### ② 本地连真实库

```bash
pip install -r requirements.txt
DATABASE_URL='mysql://exporter:密码@127.0.0.1:3306/verifly_signup?charset=utf8mb4' \
UPLOAD_DIR=/opt/verifly/uploads \
EXPORT_TOKEN=你的token \
uvicorn app.main:app --host 127.0.0.1 --port 8010
```

### ③ 服务器（Docker）

```bash
# 构建推送
./deploy/build-push.sh 1.1.0

# 启动（自动带 :ro 只读挂载、资源限额、健康检查）
./deploy/run.sh /opt/verifly/export.env
```

`/opt/verifly/export.env` 至少要有：

```ini
DATABASE_URL=mysql://exporter:<密码>@127.0.0.1:3306/verifly_signup?charset=utf8mb4
EXPORT_TOKEN=<长随机串>
```

---

## 8. 启动失败怎么查

先看容器/进程日志：

```bash
docker logs --tail 30 verifly-export      # Docker
# 或直接跑前台看报错
python -m uvicorn app.main:app --port 8010
```

| 报错 | 原因 | 处理 |
|---|---|---|
| `ModuleNotFoundError: No module named 'openpyxl'` | **镜像太旧**（1.0.0 没有 Excel 依赖） | 重新 `docker build`，用 `1.1.0` |
| `ModuleNotFoundError: No module named 'app'` | 不在项目根目录跑 | `cd` 到 `export-service/` 目录 |
| `服务未配置 EXPORT_TOKEN，已禁用导出`（503） | `.env` 没填 token | 填上 `EXPORT_TOKEN` 再重启 |
| `/healthz` 返回 503 | 数据库连不上 | 查 `DATABASE_URL`、账号权限、网络 |
| `Address already in use` | 端口被占 | 换端口：`PORT=8020` 或 `--port 8020` |
| 页面白屏 | 地址少了 token | 用 `/?token=xxx`，或先在登录框输入 |
| 打包 413 | 勾选附件合计超上限 | 减少勾选，或调大 `MAX_EXPORT_MB` |

---

## 9. 为什么它影响不到采集服务

| # | 措施 |
|---|---|
| 1 | 独立容器 / 独立域名 / 独立端口 8010 |
| 2 | 数据库账号**只有 SELECT**，物理上写不了 |
| 3 | 附件目录 `-v ...:ro` 只读挂载 |
| 4 | `--cpus=1 --memory=512m` 资源限额 |
| 5 | 不引用采集服务任何代码 |
| 6 | 单次限 10 条 / 300MB，打包流式且并发不失控 |

---

## 10. 开发

```bash
pip install -r requirements-dev.txt
pytest -q                 # 9 个用例
ruff check app tests
ruff format --check app tests
python -m app.demo        # 本地预览
```

```
app/
├── main.py     接口 + 静态页
├── db.py       只读查询（SQLite / MySQL）
├── export.py   CSV + 流式 ZIP
├── auth.py     token 鉴权与失败锁定
├── config.py   环境变量
└── demo.py     假数据 + 一键启动
static/index.html   后台页面（单文件，无构建）
```
