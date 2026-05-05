# 浙江财经大学东方学院 Dr.COM 校园网保活脚本

这是一个用于浙江财经大学东方学院校园网认证网关的 Dr.COM 保活/自动重连脚本。

适用场景：服务器已经接入校园网，但一段时间后 Dr.COM Web 认证会掉线，
导致服务器无法继续访问外网。脚本会周期性检查当前登录状态；如果仍在线，
只输出状态，不做任何操作；如果检测到离线，才会用配置的账号密码调用登录
接口重新认证。

默认网关地址是 `http://10.1.60.100`。

## Reversed Endpoints

- Status: `GET http://10.1.60.100/drcom/chkstatus`
- Login: `GET http://10.1.60.100/drcom/login`
- Response format: JSONP, for example `dr1002({...})`
- Current page bundle: `a41.js` loads `a40.js`; `a40.js` calls `/drcom/login`
  when `login_method == 0`.
- The older `/eportal/?c=ACSetting&a=Login` values are still present in page
  variables, but the active code path for this gateway is `/drcom/login`.

Login parameters used by the frontend:

```text
DDDDD=<username>
upass=<password>
0MKKey=123456
R1=
R2=
R3=
R6=0
para=
v6ip=
terminal_type=1
```

The script checks `/drcom/chkstatus` first. It only calls `/drcom/login` when
the status response is not online for the configured account.

## Run Once

```bash
export CAMPUS_USERNAME='<your student id>'
export CAMPUS_PASSWORD='<your password>'
python3 campus_keepalive.py --once
```

## Run Continuously

```bash
export CAMPUS_USERNAME='<your student id>'
export CAMPUS_PASSWORD='<your password>'
export CAMPUS_INTERVAL=60
python3 campus_keepalive.py
```

For carrier-specific accounts, set `CAMPUS_SERVICE`, for example `@dx` or
`@lt`. Leave it empty for the normal campus user option.

## systemd Example

Create `/etc/systemd/system/campus-keepalive.service` on the server:

```ini
[Unit]
Description=Campus Dr.COM keepalive
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Environment=CAMPUS_USERNAME=<your student id>
Environment=CAMPUS_PASSWORD=<your password>
Environment=CAMPUS_INTERVAL=60
WorkingDirectory=/path/to/this/directory
ExecStart=/usr/bin/python3 /path/to/this/directory/campus_keepalive.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now campus-keepalive.service
sudo journalctl -u campus-keepalive.service -f
```
