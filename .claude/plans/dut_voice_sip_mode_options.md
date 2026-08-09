# DUT 语音 SIP 模式选项修正计划

## 目标

- 在语音配置页现有 `SIP/UDP/TCP/TLS` 基础上增加ONT支持的 `IMSSIP`。
- 保持底层字段 `Device.Services.VoiceService.1.SIP.X_SDMC_SIPMode` 和原样下发方式不变。
- service二次校验允许 `SIP/IMSSIP/UDP/TCP/TLS`，防止绕过UI下发未知值。

## 实施步骤

1. 在语音service定义唯一的SIP模式选项并增加校验。
2. 语音Tab下拉框复用该选项，默认值继续为 `SIP`。
3. 补充UI选项、service拒绝非法值和core实际下发 `IMSSIP` 回归。
4. 同步README、项目状态、验收基线和开发记录。
5. 运行 `python scripts\verify_baseline.py` 和 `git diff --check`。

## 验收重点

- 下拉框按 `SIP、IMSSIP、UDP、TCP、TLS` 显示。
- 选择 `IMSSIP` 时主日志实际set参数包含 `X_SDMC_SIPMode=IMSSIP`。
- 原有 `UDP`、`TCP`、`TLS` 继续保留，未知值由service拒绝。
- DTMF、服务器、账号、编码、DigitMap及语音回读流程保持不变。
