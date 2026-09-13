# 部署到公网,手机也能看

推荐用 [Railway](https://railway.app) —— 不用自己管服务器、不用配Nginx和SSL证书,五分钟能有一个 `https://xxx.up.railway.app` 的网址,手机直接打开就行。免费额度对个人这种小项目基本够用,超出后是按用量付费(通常几美元/月)。

## 前置:把项目放到 GitHub(Railway 靠这个自动部署)

如果你还没有 GitHub 仓库:

```bash
cd observation-station
git init
git add .
git commit -m "first commit"
```

然后去 github.com 建一个新仓库(比如叫 `observation-station`),按它提示的命令把本地代码推上去:

```bash
git remote add origin https://github.com/你的用户名/observation-station.git
git branch -M main
git push -u origin main
```

## 第一步:创建 Railway 项目

1. 打开 railway.app,用 GitHub 账号登录
2. 点 "New Project" → "Deploy from GitHub repo"
3. 选你刚推上去的 `observation-station` 仓库
4. **重要**:因为代码在 `backend/` 子目录下,部署设置里要把 "Root Directory" 设成 `backend`(在项目的 Settings 里能找到这个选项)

Railway 会自动识别到 `requirements.txt` 和 `Procfile`,不需要你手写 Dockerfile。

## 第二步:加一块持久化磁盘(否则数据每次重启就没了)

Railway 的容器默认是"无状态"的,重新部署就会清空文件系统,SQLite数据库文件会跟着消失。需要挂一个 Volume:

1. 进入你的服务(service),点 "Settings" → "Volumes" → "New Volume"
2. Mount path 填 `/data`
3. 回到 "Variables",加一个环境变量:
   ```
   OBSERVATION_DB_PATH=/data/observation.db
   ```

代码已经改好了,会自动读这个环境变量,没设置的话默认还是用本地当前目录(方便你本地开发时不受影响)。

## 第三步:确认启动命令

Railway 通常会自动用 `Procfile` 里的命令。如果它没识别到,手动在 Settings → Deploy 里填启动命令:

```
uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1
```

**`--workers 1` 千万别改成多个**——因为定时任务(APScheduler)是跑在应用进程里的,如果开多个worker,每个worker都会各自独立抓取一遍,数据库里会插入好几份重复数据。

## 第四步:部署 & 拿到网址

点 "Deploy",等一两分钟。部署完成后,在 "Settings" → "Networking" 里点 "Generate Domain",会给你一个类似 `observation-station-production.up.railway.app` 的网址。

打开这个网址(手机浏览器也行),应该能看到和本地一模一样的页面,而且是24小时自动抓取的。

## 关于国内网络访问的提醒

- CoinGecko、The Block 这些数据源是境外服务,Railway 的服务器本身也在境外,**服务器抓数据没问题**。
- 你手机/电脑**访问这个 railway.app 网址**是走你自己的网络出去连境外服务器,如果所在网络环境对境外网站不稳定,可能会偶尔慢或者连不上——这个和代码没关系,是网络链路问题。如果长期用着不稳定,后续可以考虑换成有国内节点的云服务商 + CDN,但这是"锦上添花"的优化,先不用管。

## 之后怎么更新代码

改完代码后:

```bash
git add .
git commit -m "说明这次改了什么"
git push
```

Railway 检测到 GitHub 有新提交会自动重新部署,不需要手动操作。

## 备用方案:如果不想用 GitHub

Railway 也支持命令行直接部署,不用建仓库:

```bash
npm install -g @railway/cli
railway login
cd observation-station/backend
railway init
railway up
```

同样需要按上面步骤加 Volume 和环境变量。
