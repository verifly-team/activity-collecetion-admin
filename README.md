# activity-66-export

66th & 2nd 市集 —— **参展申请导出后台**（只读，独立服务）。

勾选 → 导出清单 CSV / 打包下载 ZIP。**不写库、不动文件**，和采集服务完全隔离。

![登录](docs/screenshot-login.png)
![主界面](docs/screenshot-main.png)

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
| 表格 | ID、时间、品牌、联系人、手机、城市、意向区域、经营品类、带货件数、**附件数与大小** |
| 勾选 | 单条勾选 / 全选本页；**达上限后其余复选框自动置灰** |
| 底部操作条 | `已选 3 / 10 条 · 合计 5.3 MB` + 「导出清单 CSV」「打包下载 ZIP」 |
| 安全阀 | 附件合计超过 `MAX_EXPORT_MB` 时，打包按钮自动禁用 |

## 4. 导出产物

**CSV**（带 BOM，Excel 双击即开）

```
报名ID,提交时间,品牌/店铺,联系人,手机,微信,邮箱,城市,主体类型,首次参展,
经营品类,意向区域,预计带货件数,价格区间,商品结构,代表商品,附件数,附件大小(MB),来源
```

**ZIP**

```
导出_20261029_1057/
├── 报名清单.csv
├── 报名清单.json
├── 001_拾光中古/
│   ├── 报名信息.json
│   └── 附件/
│       └── 拾光中古_1.zip
├── 002_旧物研究所/
└── _缺失附件清单.txt     ← 库里有记录但磁盘找不到时才会出现
```

打包是**流式**的：边读磁盘边发 HTTP，不落临时文件，内存恒定几 MB。

---

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
| `GET` | `/api/v1/applications.csv?ids=1,2` | 导出清单 |
| `GET` | `/api/v1/bundle.zip?ids=1,2` | 打包下载 |

```bash
# 命令行导出（不走界面）
TOKEN=你的token
curl -H "Authorization: Bearer $TOKEN" \
  "https://export.域名.com/api/v1/applications.csv?ids=1,2,3" -o 报名.csv

curl -H "Authorization: Bearer $TOKEN" \
  "https://export.域名.com/api/v1/bundle.zip?ids=1,2,3" -o 打包.zip
```

---

## 7. 为什么它影响不到采集服务

| # | 措施 |
|---|---|
| 1 | 独立容器 / 独立域名 / 独立端口 8010 |
| 2 | 数据库账号**只有 SELECT**，物理上写不了 |
| 3 | 附件目录 `-v ...:ro` 只读挂载 |
| 4 | `--cpus=1 --memory=512m` 资源限额 |
| 5 | 不引用采集服务任何代码 |
| 6 | 单次限 10 条 / 300MB，打包流式且并发不失控 |

---

## 8. 开发

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
