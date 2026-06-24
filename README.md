# KouboAgent - 数字人视频制作工具

自动生成抖音口播数字人视频：抖音文案提取 → MiniMax 语音合成 → 婵镜数字人视频 → 成品输出。

## 项目结构

```
dige_koubo/
├── app.py                      # 主程序（PyQt6 GUI）
├── requirements.txt            # Python 依赖
├── build_windows.ps1           # Windows 编译脚本
├── run_app.ps1                 # 开发运行脚本
├── installer.iss               # Inno Setup 安装脚本
├── api_config.template.json    # API Keys 模板
├── dist/                       # 编译输出
│   ├── KouboAgent_api_keys_v9.exe
│   └── _internal/
│       ├── scripts/            # 辅助脚本
│       └── ...
└── installer_output/           # 安装包（编译后生成）
```

## 快速开始（开发者）

```powershell
pip install -r requirements.txt
python app.py
```

## 编译

```powershell
.\build_windows.ps1
```

## 制作安装包

用 [Inno Setup 6](https://jrsoftware.org/isinfo.php) 编译：

```
iscc installer.iss
```

## 用户安装

下载 Release 中的 `KouboAgent_v9.0_Setup.exe`，双击安装即可。

## API Keys 说明

| Key | 用途 | 获取地址 |
|-----|------|----------|
| `deepseek_api_key` | DeepSeek AI | https://platform.deepseek.com |
| `minimax_api_key` | MiniMax 语音合成 | https://api.minimaxi.com |
| `chanjing_app_id` | 婵镜数字人 | 婵镜平台 |
| `chanjing_secret_key` | 婵镜数字人 | 婵镜平台 |
| `zhiling_key` | 17知令抖音提取 | https://www.17zhiling.com |
