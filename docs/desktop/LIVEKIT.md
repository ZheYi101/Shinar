# LiveKit 本机传输探针

当前交付是独立、可选的 RTC 技术探针，尚未接入桌面语音主路径。**严格 loopback 的服务监听和退出已验证；早期空 ICE 列表握手超时，随后空 URL entry 为无效配置。合法本机 URL 的唯一独立差异复验在首 client 连接约 44.9 秒后被总 deadline 取消，native 创建状态未观测。双参与者 PCM、真实 data 流、取消及重入尚未到达，不能记 RTC 通过。** 离线协议测试不能替代这些项目。

用户已决定文本功能通过后先做本机 LiveKit 探针；完整文本回复 1 秒继续作为优化目标。这不会把文本性能改记为通过，也不会把合成 PCM 到达称为首段可听语音。

## 安装与运行

Windows x64、Python ≥3.11；本次使用 Windows / CPython 3.13.5。基础安装不需要 LiveKit。开发工作树可运行：

```powershell
uv sync --dev --extra desktop --extra realtime
.venv\Scripts\python.exe -m pytest tests\realtime -q
.venv\Scripts\python.exe scripts\probe_livekit.py --download-server
```

已经缓存 server 后不再下载：

```powershell
.venv\Scripts\python.exe scripts\probe_livekit.py --output build/livekit-probe/results.json
```

默认 HTTP 为 `127.0.0.1:17880`，RTC UDP 为 `127.0.0.1:17882`；`--port-base 18880` 可改为 18880/18882。RTC TCP fallback 关闭。已有进程占用端口时失败退出，不停止别人的进程，不改防火墙。不支持把输出写到仓库 `build/` 之外。`--download-server` 只下载下表的固定官方资产，不安装 Windows service 或全局命令。进程均隐藏运行。

脚本返回 0 才表示其真实 RTC 断言全部通过；当前实测返回 1。结果仅包含版本、PID、socket 地址/端口、计数、耗时和安全错误类型，不含 token、secret、文本原文、音频或 SDK 原始日志。每次生成随机 server secret 和 5 分钟、限定房间/身份的 token；secret 只在临时配置和父子进程 stdin 中传递，配置在 `finally` 删除。探针不读取 `.env`、用户学习库或 AI 凭据，不调用 LLM/STT/TTS。

## 官方版本与 Windows 支持

2026-10-24 对官方 PyPI JSON 与 GitHub release 核对的固定版本如下。SDK API 以实际安装版本检查，不只照搬网页示例。

| 组件 | 固定版本与来源 | 本轮用法 |
| --- | --- | --- |
| Python RTC | `livekit==1.1.21`，[PyPI](https://pypi.org/project/livekit/1.1.21/)、[官方 SDK](https://github.com/livekit/python-sdks) | 官方 Windows x64 wheel，Room、可靠 data、原始 AudioSource/AudioStream |
| Python API | `livekit-api==1.2.2`，[PyPI](https://pypi.org/project/livekit-api/1.2.2/) | 只在本机探针签短期 room token，不启动 API 服务 |
| SFU server | [v1.13.10](https://github.com/livekit/livekit/releases/tag/v1.13.10)，2026-10-14 发布 | `livekit_1.13.10_windows_amd64.zip`，19,616,198 bytes |
| server SHA256 | `fd4b7c2c3c1e4c71adaa4f6a046ad1c0abaaaf1e09fae904b35bf231ffae11d2` | 与[官方 checksums.txt](https://github.com/livekit/livekit/releases/download/v1.13.10/checksums.txt)及 release asset digest 一致 |

`realtime` extra 只引入 RTC/API SDK 和其依赖（包括 numpy、protobuf、aiohttp），没有 `livekit-agents`、模型插件、Redis、云数据库或模型权重。`uv.lock` 固定解析结果。基础 wheel 元数据将这两个 SDK 列为 extra，而不是强制依赖；`lingualoop.realtime` 的协议模块无需 SDK，只有实例化 `LiveKitTransport` 才加载它。正式分发 SDK/native library 时仍须保留其相应许可。

## loopback 控制与已知限制

HTTP 使用 `bind_addresses: [127.0.0.1]` 和 `--bind 127.0.0.1`。RTC 配置 `use_external_ip=false`、`node_ip=127.0.0.1`、`enable_loopback_candidate=true`、`ips.includes=[127.0.0.1/32, ::1/128]`，TURN 关闭。server 启动后先按其自有 PID 运行 `Get-NetTCPConnection` / `Get-NetUDPEndpoint`；TCP 只看监听状态，UDP 检查全部 endpoint。缺预期监听或发现任何非 loopback 地址均立刻终止该自有进程。真实 RTC 成功路径还会再查一次 server socket。

**`--bind` 不能单独证明 RTC socket 安全。** v1.13.10 固定依赖 [mediatransportutil f234b534b095 的 webrtc_config.go](https://github.com/livekit/mediatransportutil/blob/f234b534b095/pkg/rtcconfig/webrtc_config.go) 中 RTC TCP listener 只向 `net.ListenTCP` 传端口，没有 bind IP 参数。因此本探针关闭 `rtc.tcp_port=0`，不测试 TCP fallback；UDP mux 使用显式 IP filter。结论仍以 Windows 实际 socket 表为准，不以 ICE 广告地址代替绑定地址。

Python SDK 底层 Rust 的 `make_rtc_config_join` 在 `ice_servers=[]` 时继承 server 下发的 ICE 表；不能用空列表宣称没有公网 STUN。初版随后传入非空 `[IceServer(urls=[])]`，虽然阻断合并回退，却违反 libwebrtc 的非空 URI 校验，是本探针引入的配置错误。早期两次 ICE timeout 使用空列表，不能作为无公网 STUN 的证据；也没有抓包证据证明当时是否发出外部 STUN 请求。空 URL entry 的最终独立 ConnectError 不能作为 loopback 握手失败的证据。

修正后由脚本传 `ice_server_urls=("stun:127.0.0.1:17882",)`，端口取当前已审计 server UDP socket；非空合法 URL 阻断 server ICE 回退。`validate_probe_stun_url` 只允许 canonical literal `127.0.0.1` 与该精确端口，拒绝 hostname、公网、userinfo、query、fragment、替代端口和 TURN。不增加任何监听或 STUN 服务，不把这个端点说成已验证的通用 STUN 服务；它只限制 ICE 配置目的地。adapter 显式接收 URL，core 不受本机策略约束。配置合法不代表握手或音频成功。

静态证据已定位安装版 SDK：PyPI 1.1.21 的[发布来源](https://pypi.org/project/livekit/1.1.21/)为 python-sdks `cf9aa1226bcb3c5408360e191c277ba01a9aa352`，gitlink 锁定 Rust `5a656c4bc4bc5c4f7fad17ab69044db3b487dfeb`（FFI 0.12.80）。该版 [proto 转换](https://github.com/livekit/rust-sdks/blob/5a656c4bc4bc5c4f7fad17ab69044db3b487dfeb/livekit-ffi/src/conversion/room.rs)保留空项，[C++ 配置转换](https://github.com/livekit/rust-sdks/blob/5a656c4bc4bc5c4f7fad17ab69044db3b487dfeb/webrtc-sys/src/peer_connection.cpp)直接推入 WebRTC server 列表；[官方 WebRTC 校验](https://webrtc.googlesource.com/src/+/refs/heads/main/pc/ice_server_parsing.cc)对 `urls` / `uri` 同时为空返回 syntax error。实际安装 DLL SHA256 `6795bb63c0a72566d68243d3bd0b40ee5c2a122bbaf8f6db9021a8bbd8bc4e43` 含同一 `Empty uri` 校验字符串。这里是静态配置缺陷取证，未重跑旧错误配置，也不补造其原始异常文本。

Native SDK 的 `connect()` 取消后资源是否立即释放不能从 Python task 数推导。官方存在其他平台/旧版本的[取消握手 socket 泄漏 issue](https://github.com/livekit/rust-sdks/issues/1340)，它不是本机根因证明。最终脚本把 RTC exercise 放入隐藏子进程：业务等待上限 45 秒，父进程 60 秒硬截止，之后只关闭自己创建的子 PID，并核对该 PID 已退出且无 socket。server 也由 `finally` 关闭并核对。库内正常关闭按资源尽力清理，汇总错误而不跳过后续资源；这不等同于证明 SDK 取消握手无 native 泄漏。

历史空列表 ICE 超时的确切根因未确定；无效空 URL 候选应先排除，不能直接归因环境。SDK 的公开 `RtcConfiguration` 只有 transport policy、gathering policy、ICE server 三类选项，未找到 loopback 网卡收集开关；“底层未收集 loopback candidate”只是待证实假设。没有改网络设备、系统路由、firewall、管理员权限，也没有放宽为 LAN/公网监听。

异常仅在子进程内存中按白名单检查，结果输出固定 `error_phase` / `error_code` 枚举，例如 `client_connect` + `ice_config_empty_uri`、`ice_config_invalid`、`ice_handshake_timeout`、`signaling_connection` 或 `unknown_connect_error`；普通超时单独是 `operation_deadline`，不能自动认作 ICE 超时。不保存原始异常、URL query、token 或 SDK 日志；无法归类的错误保留 unknown，不能从 `ConnectError` 类型直接推断根因。

每次连接另记录 `connection_attempts[].elapsed_ms`、phase 和状态。`native_rtc_creation` 区分完成连接、在 ICE 前配置拒绝、从官方 `wait_pc_connection` 超时位置推断已越过创建，以及未观测；这是明确的证据等级，不声称 SDK 提供了底层创建回调。45 秒外层 deadline 只能记超时且 creation 未观测，不用耗时本身推导 native 创建成功。

## 应用和传输契约

实现位于 `src/lingualoop/realtime/`，不导入 backend、provider 或 `DialoguePreparation`。`RealtimeTransport` 协议允许未来替换实现；`LiveKitTransport` 只是 RTC adapter。业务仍负责完成消息的持久化、LLM 调度、用户确认和后台准备。Pro 预测只可作为异步参考，不能被 transport 改写为用户发言或变成 RTC 前置等待。

| API | 行为 |
| --- | --- |
| `connect(url, token)` | 加入一个已授权房间；本探针测试的是本机签发 token |
| `start_turn(TurnRef)` | 会话内 generation 必须递增；替换旧轮音轨和草稿 |
| `send_delta(ref, text)` | 包装已有 `on_delta(str)`，为每个事件带 ref 和 seq；不修改现有业务接口 |
| `complete_text(ref)` | 显式完成；没有此事件的草稿不能作为完成消息 |
| `send_audio(ref, PcmFrame)` | 连续提交 48kHz mono S16LE PCM；不是 WAV 文件轮询，也不负责录音或扬声器 |
| `request_cancel(ref)` | 首个 await 前关闭本地呈现门，再可靠发送取消请求 |
| `close()` | 先禁止回调新增任务，清队列/释放轨/停消费者/断房；清理错误不跳过其他资源 |

可靠 data topic 为 `lingualoop.turn.v1` / `lingualoop.control.v1`。每个事件含 `session_id`、`turn_id`、`generation`、`seq`；文本和 track 绑定使用同一单调序列。接收只信任配置的 peer identity。乱序、重复、旧代际、错会话和超限 payload 不呈现；文本总草稿有上限。

每个 generation 使用一条连续 PCM 音轨，由可靠 `audio_bind` 绑定 SID；一轮内逐帧持续发送，不按文本小片段反复发布轨。换轮使用新 SID，以便旧 RTP/解码缓冲帧不能冒充新轮。取消时接收侧立即清 draft/关闭旧 SID，发送侧同步标取消并清队列；在途 `capture_frame` 返回后再检查并清队列，释放旧轨后发送 `cancel_ack`。完成文本不代表音频已经播放完；本层没有设备播放回执。

取消或换代前已经呈现的内容无法撤销；取消后的旧文本/旧音轨不会继续交给呈现回调。若未来接入扬声器，还必须让播放设备队列消费同一代际 gate 并清空其缓冲。本探针没有验证扬声器、AEC、VAD、自然打断、设备切换、真人日语音质、STT/TTS 或断网自动恢复。显式 leave/rejoin 也不能称为自动网络恢复。

## 验证记录与证据边界

| 时间 UTC / 候选 | 实测 | 结论 |
| --- | --- | --- |
| 2026-10-24 04:13:21 / 初版 server 配置 | 发现非 loopback server socket，立即关闭；结果 `server_cleanup=true` | scope 检查有效。首 PID 和具体非 loopback 行未保留，不补造；未连接参与者 |
| 04:14:26 / 禁用 RTC TCP、UDP IP filter | PID 70384：仅 TCP `127.0.0.1:17880`、UDP `127.0.0.1:17882`；第一参与者 ICE 超时；server 清理通过 | `build/livekit-probe/results.json`（ignored）；未收到真实音频/文本。空 ICE 列表有上述回退证据限制 |
| 04:18:02 / 官方 single-peer 选项 | PID 65476：同样仅上述两监听；第一参与者 ICE 超时；server 清理通过 | `build/livekit-probe/final-results.json`（ignored）；single-peer 没有解决本机 ICE。该历史 JSON 的 `public_ice_servers=false` 不能当证据，最终代码已更正字段/行为 |
| 协议与 adapter 回归 / 首版冻结候选 | `pytest tests/realtime -q`：17 passed（实现者自验） | 覆盖 seq/代际、取消立即 gate、半段草稿、来源身份、在途 capture 清理、单资源失败继续关闭、disconnect 晚回调；全部离线，不证明 RTC 通过 |
| 04:23:38.524563 / 空 URL 候选、独立复验 | `research_services` 仅运行一次该候选脚本，exit 1、`ConnectError`；首 client connect 未完成，无 connected 指标。server PID 69988 仅 TCP `127.0.0.1:17880` / UDP `127.0.0.1:17882`；RTC 子 PID 27392 exit 1 | `build/livekit-probe/independent-results.json`（ignored）；server 清理、子进程退出/socket 清理均 true；研究员另查两 PID 均不存在，HTTP TCP / RTC UDP 端口均 0 个 endpoint。后查明候选含无效空 URL 配置，不能作为 loopback 不可用证据；未到 PCM/data/取消/重入 |
| 04:38:55.009312 / 合法 URL 修正、唯一独立差异复验 | `research_services` 运行冻结脚本，exit 1、`TimeoutError`，phase=`client_connect`、code=`operation_deadline`；连接 44899.859 ms 后 cancelled，native 创建 `not_observed`。server PID 56244 仅 TCP `127.0.0.1:17880` / UDP `127.0.0.1:17882`；子 PID 62060 exit 1 | `build/livekit-probe/independent-revision-results.json`（ignored）；server 清理、子进程退出/socket 清理、Python tasks/streams 清理均 true，cleanup/task errors 均 0。研究员另作 OS 复查：两 PID 不存在，对应 TCP/UDP endpoint 计数均 0，5 文件运行前后 hash 一致。不能从外层 deadline 推断已进入 ICE；未到双参与者/PCM/data/取消/重入，不再自动重跑 |
| 合法 URL 修正 / 最终离线候选 | `pytest tests/realtime -q`：45 passed（实现者自验）；独立诊断/adapter 子集 33 passed | 拒绝空 ICE URL、exact loopback/端口边界、phase/error 白名单、generic 超时不冒充 post-creation、R1/R2 与原代际/seq 回归；不代替真实 RTC |

最终独立复验已由 `research_services` 执行，完整结果见 [最终验收报告](../validation/text/TEXT_ACCEPTANCE_2026-10-24.md)。历史空 URL 候选全仓 138 passed / 1 skipped，旧 wheel 4 个 realtime 模块、19 个 backend 模块与对应源码逐字节一致，39 项桌面资源/隔离运行和屏蔽 LiveKit 导入后的基础业务 Mock 检查通过。旧 wheel 已保留于 `build/package-check/historical-rtc-invalid/`；这些结果不是合法 URL 修正后新包的验证。合法 URL 最终候选已独立全仓 **166 passed / 1 skipped（25.81 秒）**，包含第 5 个 realtime 模块 `diagnostics.py`；新 wheel 验证见独立报告。独立审查已复验关闭资源关闭异常和 disconnect 晚回调两项缺口。以上离线/打包结论不外推 RTC 连通。

合法 URL 修正最终 wheel 为 `build/package-check/lingualoop-0.1.0-py3-none-any.whl`，SHA256 **`5ae286b5304e3562d3c920fa47abb2f594069dec78a6710c44af1dcbb4b40916`**。独立检查确认 19 个 backend 模块、5 个 realtime 模块及 39 项 QML/SVG/license 与工作树逐字节一致，隔离 QML 加载、无原生标题栏及窗口控件检查通过。RTC/API SDK 仅在 extra；阻断 SDK 导入时业务 Mock 的 load/start/send 仍通过，构造 RTC adapter 给明确缺 extra 错误。新包不含 server 二进制、token、secret 或探针结果；历史无效配置旧包继续单独保留。

冻结前后 transport SHA256 为 `9367b95831b5782474cf82547b3b40be7a1d9477df28270dbfa381836048260d`，probe 脚本为 `a78e9c331a5191474c07e53aff707a138c34a88f22aabb77a84f275cd0612b37`；独立复验记录源码和脚本运行前后一致。该历史空 URL 候选的 `ConnectError` 只记录安全类型，未保留可能含 token URL 的原始异常，因此不能从该类型单独确定与早期 ICE timeout 是否同一根因，也不能据此排除配置或 native SDK 限制。

上述 hash 属于历史无效空 URL 候选。合法 URL 修正最终 transport SHA256 为 `afbc81ed4f4d7641d2fd59ef60a5df470cb42be236595645ccbb14943b9db3db`，probe 为 `b09067fd08c573a04ed986446cd280ac0e08413e281db050fa4958c760ffafa4`，diagnostics 为 `901937c37e9e8f9f9b58f9a29dd593317ee44b71d5e3a9ba0d4030d421caa3d1`；独立审查固定源码链和候选指纹详见 [代码审查记录](../validation/engineering/CODE_AUDIT_2026-10-24.md)。

输出脚本具备真实两参与者、至少数十非零 PCM 帧、文本顺序/完成、在真实 data channel 注入旧事件、取消后零旧帧呈现、换代恢复、显式退出/重入和资源释放断言；**目前这些真实断言因第一参与者连接失败而尚未到达**。保留历史失败，不再扩大网络范围或继续自动重试。

计时字段 `transport_connected_ms`、`text_first_delta`、`audio_first_frame`、`cancel_ack` 和 `last_old_delta_relative_cancel` 分别记录；最后一个为负值表示末次旧 delta 发生在取消前。没有 TTS/设备播放，`audio_first_frame` 只能称为首个 PCM 帧到达，不能称为“用户说完到首段可听语音”。当前未完成握手，后续帧/文本指标为空；不填 0 冒充低延迟。
