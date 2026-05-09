# 浙江财经大学东方学院校园网自动连接与保活脚本

这是一个面向浙江财经大学东方学院 Dr.COM 校园网认证网关的自动化连接脚本。

程序会周期性访问校园网认证网关，判断当前设备是否仍处于在线状态。如果在线，
程序只输出状态；如果掉线，程序会自动调用登录接口重新认证。它适合部署在服务器、
实验室主机、树莓派、NAS 等需要长期保持网络连通的设备上。

默认网关地址：

```text
http://10.1.60.100
```

如果网关发生变化，脚本也会自动尝试探测当前网关并回退到可用地址。

## 功能

- 自动检测 Dr.COM 校园网登录状态
- 掉线后自动重新登录
- 支持网关自动探测和网关回退
- 自动缓存最近一次可用网关
- 支持绑定源 IP 或网卡，便于有线和 Wi-Fi 分别认证
- 支持普通校园用户、电信、联通等账号后缀
- 支持环境变量、`.env` 文件和命令行参数
- Rust 单文件二进制，支持 macOS、Linux、Windows
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

程序不会主动注销，也不会在已经在线时重复登录。运行流程是：

1. 先尝试 `CAMPUS_BASE_URL` 的 `/drcom/chkstatus` 和 `/drcom/login`。
2. 如果失败，读取网关缓存并重试。
3. 如果仍失败，访问 `CAMPUS_PROBE_URL` 自动探测当前网关并重试。
4. 成功后缓存这次可用网关，后续优先复用。
5. 按配置间隔继续下一轮检测。

如果设置了 `CAMPUS_SOURCE_IP` 或 `CAMPUS_INTERFACE`，程序会让所有 HTTP 请求都从
指定地址发出。这适合有线和 Wi-Fi 需要分别认证的场景。

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
CAMPUS_PROBE_URL=http://example.com/
CAMPUS_GATEWAY_CACHE_FILE=.campus_gateway_cache
CAMPUS_SOURCE_IP=
CAMPUS_INTERFACE=
```

运行一次检测：

```bash
cargo run -- --once
```

长期运行：

```bash
cargo run --
```

构建发布版：

```bash
cargo build --release
./target/release/campus-drcom-keepalive --once
```

## 配置项

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `CAMPUS_BASE_URL` | `http://10.1.60.100` | 校园网认证网关地址 |
| `CAMPUS_PROBE_URL` | `http://example.com/` | 自动探测网关时访问的探测地址 |
| `CAMPUS_GATEWAY_CACHE_FILE` | `.campus_gateway_cache` | 最近一次可用网关缓存文件 |
| `CAMPUS_SOURCE_IP` | 空 | 绑定请求使用的本机 IPv4 地址 |
| `CAMPUS_INTERFACE` | 空 | 绑定请求使用的网卡名，例如 `enp7s0` |
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
campus-drcom-keepalive \
  --username '<你的账号>' \
  --password '<你的密码>' \
  --interval 60
```

指定配置文件：

```bash
campus-drcom-keepalive --env-file /etc/campus-keepalive.env
```

绑定到指定源地址：

```bash
campus-drcom-keepalive --source-ip 10.3.20.57 --once
```

绑定到指定网卡（Linux）：

```bash
campus-drcom-keepalive --interface enp7s0 --once
campus-drcom-keepalive --interface wlp0s20f3 --once
```

`--source-ip` 是跨平台主路径；`--interface` 使用系统网卡列表解析 IPv4 地址，适用于 macOS、Linux、Windows。

禁用网关自动探测（只使用你给定的网关）：

```bash
campus-drcom-keepalive --no-auto-discover-gateway
```

只检测一次：

```bash
campus-drcom-keepalive --once
```

## systemd 部署

仓库提供了示例服务文件：

```text
deploy/campus-keepalive.service.example
deploy/campus-keepalive@.service.example
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
sudo install -m 755 target/release/campus-drcom-keepalive /usr/local/bin/campus-drcom-keepalive
sudo cp deploy/campus-keepalive.service.example /etc/systemd/system/campus-keepalive.service
```

编辑其中的 `WorkingDirectory` 和 `ExecStart`，改成你的仓库路径。然后启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now campus-keepalive.service
sudo journalctl -u campus-keepalive.service -f
```

如果要分别保活有线和 Wi-Fi，可以使用模板服务：

```bash
sudo cp deploy/campus-keepalive@.service.example /etc/systemd/system/campus-keepalive@.service
sudo systemctl daemon-reload
sudo systemctl enable --now campus-keepalive@enp7s0.service
sudo systemctl enable --now campus-keepalive@wlp0s20f3.service
sudo journalctl -u 'campus-keepalive@*.service' -f
```

模板服务会读取 `/etc/campus-keepalive.env`，并额外读取
`/etc/campus-keepalive-<网卡名>.env` 作为覆盖配置；同时按网卡名分别写网关缓存，
避免两条链路互相覆盖缓存。

例如有线和 Wi-Fi 使用不同入口时：

```dotenv
# /etc/campus-keepalive-enp7s0.env
CAMPUS_BASE_URL=http://10.99.253.230
```

```dotenv
# /etc/campus-keepalive-wlp0s20f3.env
CAMPUS_BASE_URL=http://10.1.60.100
```

## 跨平台

Rust 版本面向 macOS、Linux、Windows。默认只使用 HTTP，因为当前 Dr.COM 认证入口就是 HTTP；
这样可以减少跨平台构建对 OpenSSL 或额外 C 编译器的依赖。如果后续需要 HTTPS 探测，可以再加
可选 TLS feature。

## 测试

运行单元测试：

```bash
cargo test
```

跨平台检查：

```bash
cargo check --target x86_64-unknown-linux-gnu
cargo check --target x86_64-pc-windows-msvc
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

这个网关的登录接口还对 URL query 参数顺序敏感。登录请求需要保持与前端页面相同
的顺序：`callback` 后先放账号、密码和登录表单字段，再放 `jsVersion`、`v`、
`lang` 这类通用字段。否则网关可能直接返回 203，而不是正常的 JSONP 登录结果。

如果登录接口也持续返回 203，请确认：

- 当前设备仍连接在校园网内，而不是切到了其他网络
- `.env` 中的账号和密码正确
- `CAMPUS_SERVICE` 是否需要填写 `@dx` 或 `@lt`
- 你手动指定的 `CAMPUS_BASE_URL` 是否有效

如果校园网网关经常变化，建议保留默认的自动探测逻辑，不要启用 `--no-auto-discover-gateway`。

## 安全说明

- 不要把真实密码提交到 GitHub。
- `.env` 已被 `.gitignore` 忽略，公开仓库只保留 `.env.example`。
- 该脚本只面向你自己有权使用的校园网账号和设备。
- 脚本不会尝试攻击、绕过或破坏认证系统，只做状态检测和掉线重连。

## 适用范围

这个仓库目前针对浙江财经大学东方学院的 `10.1.60.100` Dr.COM 网关整理和测试。
其他学校即使也使用 Dr.COM，接口路径和参数也可能不同，需要重新确认。
