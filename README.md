# KouboAgent - 数字人视频制作工具

自动生成抖音口播数字人视频：抖音文案提取 → MiniMax 语音合成 → 婵镜数字人视频 → 成品输出。

## 安装

1. 下载 `installer_output/KouboAgent_v9.0_Setup.exe`
2. 双击安装（自动创建桌面快捷方式）
3. 运行程序，填入你的 API Key

## API Keys 说明

| Key | 用途 | 获取地址 |
|-----|------|----------|
| `deepseek_api_key` | DeepSeek AI | https://platform.deepseek.com |
| `minimax_api_key` | MiniMax 语音合成 | https://api.minimaxi.com |
| `chanjing_app_id` | 婵镜数字人 | 婵镜平台 |
| `chanjing_secret_key` | 婵镜数字人 | 婵镜平台 |
| `zhiling_key` | 17知令抖音提取 | https://www.17zhiling.com |

## 源码

- `_internal/scripts/extract_douyin_copy.py` — 抖音文案提取
- `_internal/scripts/minimax_synthesize.py` — MiniMax 语音合成
- `installer.iss` — Inno Setup 安装脚本
- `api_config.template.json` — 配置文件模板
