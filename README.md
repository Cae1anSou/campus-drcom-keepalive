# 浙江财经大学东方学院校园网自动连接与保活脚本

这是一个面向浙江财经大学东方学院 Dr.COM 校园网认证网关的自动化连接脚本。

脚本会周期性访问校园网认证网关，判断当前设备是否仍处于在线状态。如果在线，
脚本只输出状态；如果掉线，脚本会自动调用登录接口重新认证。它适合部署在服务器、
实验室主机、树莓派、NAS 等需要长期保持网络连通的设备上。

默认网关地址：

```text
http://10.1.60.100
```

## 功能

- 自动检测 Dr.COM 校园网登录状态
- 掉线后自动重新登录
- 支持普通校园用户、电信、联通等账号后缀
- 支持环境变量、`.env` 文件和命令行参数
- 无第三方依赖，只需要 Python 3
- 适合配合 systemd 在服务器上长期运行

## 工作原理

当前网关页面使用 Dr.COM Web 认证。根据前端请求流程整理后，核心接口如下：

| 用途 | 接口 |
| --- | --- |
| 查询在线状态 | `GET http://10.1.60.100/drcom/chkstatus` |
| 登录认证 | `GET http://10.1.60.100/drcom/login` |

接口返回 JSONP，例如：

```text
dr1002({"result":1,"uid":"..."});
```

登录参数与前端页面保持一致：

```text
DDDDD=<账号>
upass=<密码>
0MKKey=123456
R1=
R2=
R3=
R6=0
para=
v6ip=
terminal_type=1
```

脚本不会主动注销，也不会在已经在线时重复登录。运行流程是：

1. 调用 `/drcom/chkstatus` 查询状态。
2. 如果 `result=1` 且账号匹配，认为当前在线。
3. 如果离线，调用 `/drcom/login` 重新登录。
4. 按配置间隔继续下一轮检测。

## 快速开始

克隆仓库后进入目录：

```bash
git clone https://github.com/Cae1anSou/campus-drcom-keepalive.git
cd campus-drcom-keepalive
```

复制示例配置：

```bash
cp .env.example .env
```

编辑 `.env`：

```dotenv
CAMPUS_USERNAME=<你的学号或账号>
CAMPUS_PASSWORD=<你的密码>
CAMPUS_SERVICE=
CAMPUS_INTERVAL=60
```

运行一次检测：

```bash
python3 campus_keepalive.py --once
```

长期运行：

```bash
python3 campus_keepalive.py
```

## 配置项

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `CAMPUS_BASE_URL` | `http://10.1.60.100` | 校园网认证网关地址 |
| `CAMPUS_USERNAME` | 空 | 校园网账号 |
| `CAMPUS_PASSWORD` | 空 | 校园网密码 |
| `CAMPUS_SERVICE` | 空 | 运营商后缀，普通校园用户留空 |
| `CAMPUS_INTERVAL` | `60` | 检测间隔，单位秒 |
| `CAMPUS_TIMEOUT` | `10` | 单次请求超时，单位秒 |
| `CAMPUS_ENV_FILE` | `.env` | 配置文件路径 |

运营商后缀示例：

| 类型 | `CAMPUS_SERVICE` |
| --- | --- |
| 校园用户 | 留空 |
| 校园电信 | `@dx` |
| 校园联通 | `@lt` |

## 命令行参数

环境变量和 `.env` 之外，也可以直接传参数：

```bash
python3 campus_keepalive.py \
  --username '<你的账号>' \
  --password '<你的密码>' \
  --interval 60
```

指定配置文件：

```bash
python3 campus_keepalive.py --env-file /etc/campus-keepalive.env
```

只检测一次：

```bash
python3 campus_keepalive.py --once
```

## systemd 部署

仓库提供了示例服务文件：

```text
deploy/campus-keepalive.service.example
```

推荐把真实账号密码放在 `/etc/campus-keepalive.env`：

```dotenv
CAMPUS_USERNAME=<你的学号或账号>
CAMPUS_PASSWORD=<你的密码>
CAMPUS_SERVICE=
CAMPUS_INTERVAL=60
```

复制服务文件：

```bash
sudo cp deploy/campus-keepalive.service.example /etc/systemd/system/campus-keepalive.service
```

编辑其中的 `WorkingDirectory` 和 `ExecStart`，改成你的仓库路径。然后启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now campus-keepalive.service
sudo journalctl -u campus-keepalive.service -f
```

## 测试

运行单元测试：

```bash
python3 -m unittest tests/test_campus_keepalive.py
```

语法检查：

```bash
python3 -m py_compile campus_keepalive.py tests/test_campus_keepalive.py
```

## 常见问题

### `Error code: 203 Bad request(2)`

如果断网后运行脚本，状态接口有时会返回 HTML 错误页，而不是正常的 JSONP：

```text
<html><body>
Error code: 203 Bad request(2)
</body></html>
```

这通常表示当前设备已经不在认证在线状态，网关没有按正常在线状态接口返回数据。
脚本会把这种状态查询异常当作“离线”处理，并继续尝试调用登录接口。

如果登录接口也持续返回 203，请确认：

- 当前设备仍连接在校园网内，而不是切到了其他网络
- `.env` 中的账号和密码正确
- `CAMPUS_SERVICE` 是否需要填写 `@dx` 或 `@lt`
- 网关地址是否仍是 `http://10.1.60.100`

## 安全说明

- 不要把真实密码提交到 GitHub。
- `.env` 已被 `.gitignore` 忽略，公开仓库只保留 `.env.example`。
- 该脚本只面向你自己有权使用的校园网账号和设备。
- 脚本不会尝试攻击、绕过或破坏认证系统，只做状态检测和掉线重连。

## 适用范围

这个仓库目前针对浙江财经大学东方学院的 `10.1.60.100` Dr.COM 网关整理和测试。
其他学校即使也使用 Dr.COM，接口路径和参数也可能不同，需要重新确认。
