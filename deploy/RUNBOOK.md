# 运维手册 · 66th 参展申请采集 + 导出

> 本文是**从零到上线再到日常运维**的完整流程。所有命令可直接复制执行。

---

## 0. 为什么审计日志不建表

**结论：不建表。** 三条理由：

1. **导出服务的数据库账号是只读的**
   建表 = 要给它 `INSERT` 权限 = 打破"导出服务物理上改不了数据"这条底线。
   一个只读服务被攻破，损失可恢复；一个能写的被攻破，数据可能被改被删。

2. **审计日志不需要事务**
   它只追加、不改、不查详情，用日志文件就够。写数据库反而引入锁竞争。

3. **日志量很小**
   一行约 150 字节。一天导 100 次 = 15KB。
   容器日志已配 `max-size=20m --max-file=3`，能存 **约 40 万条记录**，
   按每天 100 次算够用十年。

**那怎么查？** 用 `deploy/audit.sh`，见第 4 节。

> 如果将来真的要审计表（比如给第三方出具证明），正确做法是：
> 另起一个**只写审计库**的小服务，或由采集服务（有写权限）落表，
> 而不是给导出服务开写权限。

---

## 1. 系统组成

```
商家手机/电脑
     │  填报名表
     ▼
┌─────────────────────────┐      ┌──────────────────┐
│ 采集服务 server         │─────▶│ MySQL            │
│ :8000  可写             │      │ verifly_signup   │
│ 上传附件 → /opt/verifly │      │ application/file │
└─────────────────────────┘      └────────┬─────────┘
                                          │ 只读账号 + :ro 挂载
                                 ┌────────▼─────────┐
                                 │ 导出服务 export  │
                                 │ :8010  只读      │
                                 │ 运营用，需 token │
                                 └──────────────────┘
```

| 服务 | 目录 | 端口 | 权限 |
|---|---|---|---|
| 采集 | `verifly-activity/server` | 8000 | MySQL 读写 + 附件目录读写 |
| 导出 | `verifly-activity/export-service` | 8010 | MySQL **只读** + 附件目录 **只读** |

---

## 2. 首次上线（一次性）

### 2.1 本地验证

```bash
cd ~/Documents/mvp/verifly/verifly-activity/export-service
./run-demo.sh                 # 造 12 条假数据，浏览器看效果
pytest -q                     # 23 个用例应全绿
ruff check app tests
```

采集服务同理：

```bash
cd ~/Documents/mvp/verifly/verifly-activity/server
pytest -q                     # 14 个用例
```

### 2.2 服务器准备数据库

```sql
-- 用 root 登进 MySQL
CREATE DATABASE IF NOT EXISTS verifly_signup
  DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 采集服务用：读写
CREATE USER 'verifly'@'127.0.0.1' IDENTIFIED BY '<强密码A>';
GRANT SELECT, INSERT, UPDATE ON verifly_signup.* TO 'verifly'@'127.0.0.1';

-- 导出服务用：只读（关键！）
CREATE USER 'exporter'@'127.0.0.1' IDENTIFIED BY '<强密码B>';
GRANT SELECT ON verifly_signup.* TO 'exporter'@'127.0.0.1';

FLUSH PRIVILEGES;
```

建表用 `server/app/schema_mysql.sql`。

### 2.3 目录与权限

```bash
mkdir -p /opt/verifly/uploads
chown -R 10001:10001 /opt/verifly/uploads   # 采集容器用户
mkdir -p /opt/verifly/export
chmod 700 /opt/verifly/export
mkdir -p /opt/verifly/audit        # 审计日志落盘目录
```

### 2.4 配置文件

`/opt/verifly/export.env`（**权限必须 600**）：

```ini
DATABASE_URL=mysql://exporter:<强密码B>@127.0.0.1:3306/verifly_signup?charset=utf8mb4
EXPORT_TOKEN=<40位随机串>
MAX_EXPORT_RECORDS=10
MAX_EXPORT_MB=300
EXPORT_PER_MIN=30
MAX_CONCURRENT_EXPORTS=2
ENABLE_DOCS=0
```

```bash
chmod 600 /opt/verifly/export.env
head -c 30 /dev/urandom | base64 | tr -d '/+=' | head -c 40   # 生成 token
```

### 2.5 构建并推送镜像

```bash
cd ~/Documents/mvp/verifly/verifly-activity/export-service
docker login crpi-quxtxo1i28qk1e0c.cn-guangzhou.personal.cr.aliyuncs.com
./deploy/build-push.sh 1.3.2
```

### 2.6 服务器启动

```bash
# 拉镜像
docker pull crpi-quxtxo1i28qk1e0c.cn-guangzhou.personal.cr.aliyuncs.com/arceus/activity-66-export:1.3.2

# 启动（自动处理端口占用、只读挂载、资源限额、健康检查）
cd ~/verifly-activity/export-service
./deploy/run.sh /opt/verifly/export.env
```

预期输出：

```
Up 5 seconds (healthy)
{"ok":true}
页面： http://<服务器IP>:8010/?token=<EXPORT_TOKEN>
```

### 2.7 验收清单

| # | 检查 | 命令 / 操作 | 期望 |
|---|---|---|---|
| 1 | 健康检查 | `curl localhost:8010/healthz` | `{"ok":true}` |
| 2 | 页面能开 | 浏览器 `http://IP:8010/?token=...` | 看到统计数字和列表 |
| 3 | 手机号脱敏 | 看列表 | 显示 `138****8000` |
| 4 | 点眼睛 | 点手机号后的眼睛 | 变完整号码 |
| 5 | 导出 Excel | 勾 2 条 → 导出 | 3 个 sheet 正确 |
| 6 | 打包下载 | 勾 2 条 → 打包 | zip 里 xlsx + 附件目录 |
| 7 | 审计有记录 | `./deploy/audit.sh` | 能看到刚才的操作 |
| 8 | 只读验证 | 见下方 | 写操作被 MySQL 拒绝 |

```bash
# 只读验证：应该报 INSERT command denied
docker exec -it verifly-export python -c "
import os,pymysql
u=os.environ['DATABASE_URL'].split('//')[1]
c=pymysql.connect(host='127.0.0.1',user='exporter',password='<密码B>',database='verifly_signup')
c.cursor().execute('DELETE FROM application WHERE id=0')
"
```

---

## 3. 日常运维

### 3.1 看服务状态

```bash
docker ps --filter name=verifly-export
docker logs --tail 50 verifly-export
curl -s localhost:8010/healthz
```

### 3.2 审计查询

**方式一：页面（推荐）** —— 顶栏点「审计日志」，可筛选操作类型。

**方式二：命令行**

```bash
./deploy/audit.sh                # 汇总
./deploy/audit.sh zip            # 谁打包过
./deploy/audit.sh aborted        # 哪些包没下完
./deploy/audit.sh ids 12         # 谁动过 12 号报名
./deploy/audit.sh today          # 今天的操作统计
```

**方式三：直接看文件**

```bash
tail -50 /opt/verifly/audit/audit.jsonl
```

审计数据写两份：容器 stdout（长期）+ `/opt/verifly/audit/audit.jsonl`（页面读这个）。
`run.sh` 会自动创建并挂载该目录，容器重建不丢。

### 3.3 清理孤儿附件

商家上传了文件但没提交报名，文件会留在磁盘：

```bash
cd ~/verifly-activity/server
docker compose exec signup python -m app.cleanup --hours 24 --dry-run   # 先看
docker compose exec signup python -m app.cleanup --hours 24             # 真删
```

### 3.4 备份

```bash
# 数据库（每天凌晨）
mysqldump -u root -p verifly_signup | gzip > /backup/db-$(date +%F).sql.gz

# 附件（每周）
tar czf /backup/uploads-$(date +%F).tar.gz -C /opt/verifly uploads
```

### 3.5 升级版本

```bash
# 本地
./deploy/build-push.sh 1.3.3
# 服务器
docker pull .../activity-66-export:1.3.3
IMAGE=.../activity-66-export:1.3.3 ./deploy/run.sh /opt/verifly/export.env
```

`run.sh` 会自动删旧容器，**中断时间 < 5 秒**。

### 3.6 回滚

```bash
IMAGE=.../activity-66-export:1.3.1 ./deploy/run.sh /opt/verifly/export.env
```

---

## 4. 故障处理

| 现象 | 原因 | 处理 |
|---|---|---|
| 容器起不来 `No module named 'openpyxl'` | 镜像版本旧 | 用 `1.3.x` |
| `/healthz` 返回 503 | 连不上 MySQL | 查 `DATABASE_URL`、账号权限、`--network host` |
| 页面白屏 | 地址少 token | `/?token=xxx` |
| 打包一直 429 | 有卡死的任务 | 等 2 分钟自动释放；急则 `docker restart verifly-export` |
| 附件 404 / 缺失 | 磁盘文件没了 | 看 zip 里的 `_缺失附件清单.txt`；查备份 |
| `Address already in use` | 端口被占 | `PORT=8020 ./deploy/run.sh ...` |
| 日志里 `token=***` | 正常 | 已脱敏，不是 bug |

**查卡死任务**：

```bash
docker logs verifly-export 2>&1 | grep export_zip | tail -5
# 有 export_zip 但没有对应的 export_zip_done → 任务卡住了
```

---

## 5. 安全基线（部署后自查）

```bash
# 1. /docs 必须 404
curl -s -o /dev/null -w "%{http_code}\n" localhost:8010/docs

# 2. 安全响应头
curl -sI localhost:8010/ | grep -iE "x-frame|nose|referrer|content-security"

# 3. 未带 token 必须 401
curl -s -o /dev/null -w "%{http_code}\n" localhost:8010/api/v1/applications

# 4. 附件目录是只读挂载
docker inspect verifly-export | grep -A3 '"Source"'

# 5. 配置文件权限
stat -c "%a %n" /opt/verifly/export.env    # 应该是 600

# 6. 容器非 root
docker exec verifly-export id -u            # 应该是 10002（容器内用户 exporter）
```

---

## 6. 变更记录

| 版本 | 内容 |
|---|---|
| 1.4.0 | 审计日志页面 + JSONL 落盘持久化 |
| 1.3.2 | 导出审计日志（`export_xlsx` / `export_zip` / `export_zip_done`） |
| 1.3.1 | 修复中断下载导致打包名额泄漏（会永久锁死打包功能） |
| 1.3.0 | 安全加固 6 项：Excel 注入、token 泄漏、限流、响应头、docs 开关、锁版本 |
| 1.2.0 | 品牌 logo/favicon、手机号接口级脱敏、移动端自适应、导出确认弹窗 |
| 1.1.0 | 改为只导出 Excel + 附件（去掉 JSON/CSV） |
