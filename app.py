from __future__ import annotations

import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, Qt, QThreadPool, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QFont, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

try:
    from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PyQt6.QtMultimediaWidgets import QVideoWidget
except Exception:  # pragma: no cover - optional on some PyQt builds
    QAudioOutput = None
    QMediaPlayer = None
    QVideoWidget = None


ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", ROOT))
OUTPUT = ROOT / "output"
OUTPUT.mkdir(exist_ok=True)

FROZEN = getattr(sys, "frozen", False)
LOCAL_PYTHON = Path(r"C:\Users\47424\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe")
if FROZEN:
    PYTHON = LOCAL_PYTHON if LOCAL_PYTHON.exists() else Path("python")
else:
    PYTHON = Path(sys.executable)
PYTHON_RUNNER = [str(Path(sys.executable)), "--run-script"] if FROZEN else [str(PYTHON)]


def first_existing_path(*paths: Path) -> Path:
    for path in paths:
        if path.exists():
            return path
    return paths[0]


DOUYIN_SCRIPT = first_existing_path(
    RESOURCE_ROOT / "scripts" / "extract_douyin_copy.py",
    ROOT / "scripts" / "extract_douyin_copy.py",
    Path(r"C:\Users\47424\.codex\skills\douyin-copy-extractor\scripts\extract_douyin_copy.py"),
)
MINIMAX_SCRIPT = first_existing_path(
    RESOURCE_ROOT / "scripts" / "minimax_synthesize.py",
    ROOT / "scripts" / "minimax_synthesize.py",
    Path(r"C:\Users\47424\.codex\skills\minimax-voice\scripts\synthesize.py"),
)
DIGE_SCRIPT = first_existing_path(
    RESOURCE_ROOT / "scripts" / "create_dige_video.ps1",
    ROOT / "scripts" / "create_dige_video.ps1",
    Path(r"C:\Users\47424\.codex\skills\dige-video\scripts\create_dige_video.ps1"),
)
DEEPSEEK_ENDPOINT = "https://api.deepseek.com/chat/completions"
CONFIG_PATH = ROOT / "api_config.json"
DEFAULT_AVATAR_NAME = "\u9ed8\u8ba4\u6570\u5b57\u4eba\u5f62\u8c61\u56fe\u7247.png"
DEFAULT_AVATAR_IMAGE = next(
    (
        candidate
        for candidate in [
            ROOT / DEFAULT_AVATAR_NAME,
            RESOURCE_ROOT / DEFAULT_AVATAR_NAME,
            Path("D:/CODEX/\u6570\u5b57\u4ebaAPI") / DEFAULT_AVATAR_NAME,
        ]
        if candidate.exists()
    ),
    ROOT / DEFAULT_AVATAR_NAME,
)


def read_windows_user_env(name: str) -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value).strip()
    except OSError:
        return ""


API_CONFIG_FIELDS = {
    "deepseek_api_key": "DeepSeek API key",
    "minimax_api_key": "MiniMax API key",
    "chanjing_app_id": "Chanjing AppId",
    "chanjing_secret_key": "Chanjing SecretKey",
    "chanjing_person_id": "Chanjing PersonId",
    "zhiling_key": "17zhiling key",
}

REQUIRED_API_FIELDS = {
    key: label
    for key, label in API_CONFIG_FIELDS.items()
    if key != "chanjing_person_id"
}


def normalize_api_config(config: dict[str, str]) -> dict[str, str]:
    normalized = {key: str(config.get(key, "")).strip() for key in API_CONFIG_FIELDS}
    app_id = normalized.get("chanjing_app_id", "")
    if ":" in app_id:
        prefix, value = app_id.split(":", 1)
        if prefix.strip().lower().replace("_", "").replace("-", "") in {"appid", "app"}:
            app_id = value.strip()
    normalized["chanjing_app_id"] = app_id
    return normalized


def load_api_config() -> dict[str, str]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return normalize_api_config(data)
    except Exception:
        return {}


def save_api_config(config: dict[str, str]) -> None:
    payload = normalize_api_config(config)
    CONFIG_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def missing_api_fields(config: dict[str, str]) -> list[str]:
    return [label for key, label in REQUIRED_API_FIELDS.items() if not config.get(key, "").strip()]


@dataclass
class ProjectState:
    source_url: str = ""
    title: str = ""
    author: str = ""
    script: str = ""
    selected_script: str = ""
    audio_file: Path | None = None
    video_file: Path | None = None
    video_url: str = ""


class WorkerSignals(QObject):
    started = pyqtSignal(str)
    line = pyqtSignal(str)
    done = pyqtSignal(str, object)
    failed = pyqtSignal(str, str)


class CommandWorker(QRunnable):
    def __init__(self, task_id: str, command: list[str], parser, env: dict[str, str] | None = None):
        super().__init__()
        self.task_id = task_id
        self.command = command
        self.parser = parser
        self.env = env or os.environ.copy()
        self.signals = WorkerSignals()

    def run(self):
        self.signals.started.emit(self.task_id)
        try:
            popen_kwargs = {}
            if os.name == "nt":
                popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            process = subprocess.Popen(
                self.command,
                cwd=str(ROOT),
                env=self.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **popen_kwargs,
            )
            chunks: list[str] = []
            assert process.stdout is not None
            for line in process.stdout:
                chunks.append(line)
                self.signals.line.emit(line.rstrip())
            code = process.wait()
            output = "".join(chunks)
            if code != 0:
                self.signals.failed.emit(self.task_id, output or f"命令退出码 {code}")
                return
            self.signals.done.emit(self.task_id, self.parser(output))
        except Exception as exc:
            self.signals.failed.emit(self.task_id, str(exc))


class DeepSeekWorker(QRunnable):
    def __init__(self, text: str, api_key: str):
        super().__init__()
        self.text = text
        self.api_key = api_key
        self.signals = WorkerSignals()

    def run(self):
        self.signals.started.emit("rewrite")
        try:
            key = self.api_key
            if not key:
                raise RuntimeError("DeepSeek API key is missing.")
            body = {
                "model": "deepseek-chat",
                "temperature": 0.75,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你是短视频 IP 博主的口播编导，擅长把普通文案改成适合真人口播的内容。"
                            "要求：开头必须有强钩子；语言自然、有画面感、适合讲解；保留原文事实；"
                            "不要夸大承诺；每个方案控制在原文长度的 80% 到 130%；只输出 JSON。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "请基于下面文案生成 3 个改写方案。"
                            "JSON 格式必须为："
                            "{\"variants\":[{\"name\":\"方案 A\",\"tone\":\"情绪共鸣\",\"body\":\"...\"},"
                            "{\"name\":\"方案 B\",\"tone\":\"专业讲解\",\"body\":\"...\"},"
                            "{\"name\":\"方案 C\",\"tone\":\"强钩子转化\",\"body\":\"...\"}]}"
                            "\n\n原文：\n" + self.text
                        ),
                    },
                ],
            }
            request = urllib.request.Request(
                DEEPSEEK_ENDPOINT,
                data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                method="POST",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json; charset=utf-8",
                },
            )
            with urllib.request.urlopen(request, timeout=90) as response:
                raw = response.read().decode("utf-8")
            payload = json.loads(raw)
            content = payload["choices"][0]["message"]["content"]
            variants_payload = json.loads(content)
            variants = []
            for item in variants_payload.get("variants", []):
                name = str(item.get("name", "")).strip() or f"方案 {chr(65 + len(variants))}"
                tone = str(item.get("tone", "")).strip() or "口播优化"
                body = str(item.get("body", "")).strip()
                if body:
                    variants.append((name, tone, body))
            if len(variants) < 3:
                variants = rewrite_variants(self.text)
            self.signals.done.emit("rewrite", variants[:3])
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            self.signals.failed.emit("rewrite", f"DeepSeek HTTP {exc.code}: {detail}")
        except Exception as exc:
            self.signals.failed.emit("rewrite", str(exc))


def first_json_object(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("没有找到 JSON 输出")
    return json.loads(text[start : end + 1])


def repair_mojibake(text: str) -> str:
    if not text:
        return ""
    markers = ("\u93c2", "\u9359", "\u6d93", "\u951b", "\u7ecc", "\u95c6", "\u6b7f", "\ufffd")
    if not any(marker in text for marker in markers):
        return text

    def bad_score(value: str) -> int:
        return sum(value.count(marker) for marker in markers)

    candidates = [text]
    for encoding in ("gb18030", "gbk"):
        try:
            candidates.append(text.encode(encoding).decode("utf-8"))
        except UnicodeError:
            pass
    return min(candidates, key=bad_score)


def parse_extract(output: str) -> dict:
    payload = first_json_object(output)
    data = payload.get("data") or {}
    script = ""
    title = ""
    author = ""
    video_id = ""
    task_id = ""

    if isinstance(data, dict):
        script = repair_mojibake((data.get("content") or data.get("resultText") or "").strip())
        title = repair_mojibake((data.get("title") or data.get("videoDesc") or "").strip())
        author = repair_mojibake((data.get("author") or data.get("nickname") or "").strip())
        video_id = str(data.get("awemeId") or data.get("videoId") or data.get("video_id") or "").strip()
        task_id = str(data.get("id") or data.get("taskId") or "").strip()

    return {
        "script": script,
        "title": title,
        "author": author,
        "video_id": video_id,
        "task_id": task_id,
    }


def infer_meta_from_share_text(source: str, script: str = "") -> dict[str, str]:
    text = source.strip()
    author = ""
    title = ""
    author_patterns = [
        r"@([\w\-\u4e00-\u9fff\u00b7]{1,40})",
        r"([\w\-\u4e00-\u9fff\u00b7]{1,40})\s*在抖音发布",
        r"作者[:：]\s*([^\n，,]{1,40})",
    ]
    for pattern in author_patterns:
        match = re.search(pattern, text)
        if match:
            author = match.group(1).strip()
            break

    candidates = []
    for raw_line in re.split(r"[\r\n]+", text):
        line = re.sub(r"https?://\S+", "", raw_line).strip()
        line = re.sub(r"^[\d.]+\s*", "", line).strip()
        if not line:
            continue
        if any(skip in line for skip in ["复制", "打开抖音", "点击链接", "http", "分享", "在抖音发布"]):
            continue
        candidates.append(line)
    if candidates:
        title = compact_text(candidates[0], 48)
    elif script:
        title = compact_text(script, 32)
    return {"title": title or "已提取口播文案", "author": author or "未获取到作者"}


def parse_audio(output: str) -> dict:
    return first_json_object(output)


def friendly_error(task: str, message: str) -> str:
    text = repair_mojibake(message)
    lower = text.lower()
    if task == "audio" and ("insufficient_balance" in lower or '"status_code": 1008' in lower or "status_code:1008" in lower):
        return (
            "MiniMax 语音合成失败：当前 MiniMax API 账号余额或额度不足。\n\n"
            "请登录 MiniMax 控制台检查余额、套餐额度或充值状态，然后再重新生成语音。\n\n"
            f"原始错误：{compact_text(text, 600)}"
        )
    if task == "video" and ("access_token failed" in lower or "app" in lower and "secretkey" in lower):
        return (
            "Chanjing 视频合成失败：获取 access_token 未通过。\n\n"
            "请检查设置里的 Chanjing AppId 和 SecretKey。AppId 只填写纯 ID，不要带 appid: 前缀；SecretKey 不要带多余空格。\n\n"
            f"原始错误：{compact_text(text, 600)}"
        )
    if task == "video" and ("select_person" in lower or "该数字人不存在" in text or "personid" in lower):
        return (
            "Chanjing 视频合成失败：当前账号没有可用的定制数字人，或设置中的 PersonId 不属于当前 AppId。\n\n"
            "请在蝉镜后台确认当前 AppId 已开通可用的定制数字人，并在软件设置中填写该数字人的 PersonId。"
            "如果不填写，软件会尝试自动选择当前账号列表里的第一个可用定制数字人。\n\n"
            f"原始错误：{compact_text(text, 800)}"
        )
    return text


def parse_video(output: str) -> dict:
    return first_json_object(output)


def compact_text(text: str, max_chars: int = 120) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= max_chars else text[: max_chars - 1] + "..."


def rewrite_variants(text: str) -> list[tuple[str, str, str]]:
    clean = text.strip()
    if not clean:
        return [
            ("方案 A", "情绪共鸣", "等待提取文案后自动生成方案。"),
            ("方案 B", "专业讲解", "等待提取文案后自动生成方案。"),
            ("方案 C", "强钩子转化", "等待提取文案后自动生成方案。"),
        ]
    sentences = re.split(r"(?<=[。！？!?])\s*", clean)
    short = "".join(sentences[: max(2, min(4, len(sentences)))])
    professional = (
        "如果你也遇到过这个问题，先别急着下结论。\n"
        + clean
        + "\n我建议你把这几个关键点记下来，真正做选择的时候会清醒很多。"
    )
    conversion = (
        "很多人卡住，不是因为不会做，而是第一步就想错了。\n"
        + clean
        + "\n从今天开始，先抓住一个最小动作去执行。收藏起来，回头照着复盘一遍。"
    )
    return [
        ("方案 A", "原文优化", clean),
        ("方案 B", "专业讲解", professional),
        ("方案 C", "强钩子转化", conversion if len(conversion) < 1800 else short),
    ]


def probe_video_size(path: Path) -> tuple[int, int] | None:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=s=x:p=0",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        raw = result.stdout.strip()
        if "x" not in raw:
            return None
        width, height = [int(part) for part in raw.split("x", 1)]
        return width, height
    except Exception:
        return None


class Card(QFrame):
    def __init__(self, title: str | None = None):
        super().__init__()
        self.setObjectName("card")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(14, 14, 14, 14)
        self.layout.setSpacing(10)
        if title:
            label = QLabel(title)
            label.setObjectName("cardTitle")
            self.layout.addWidget(label)


class ApiSettingsDialog(QDialog):
    def __init__(self, config: dict[str, str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("API Settings")
        self.inputs: dict[str, QLineEdit] = {}
        layout = QVBoxLayout(self)
        form = QGridLayout()
        for row, (key, label) in enumerate(API_CONFIG_FIELDS.items()):
            form.addWidget(QLabel(label), row, 0)
            edit = QLineEdit()
            edit.setText(config.get(key, ""))
            edit.setEchoMode(QLineEdit.EchoMode.Password)
            if key == "chanjing_person_id":
                edit.setPlaceholderText("Optional. Leave empty to auto-pick an available Chanjing digital person.")
            edit.setMinimumWidth(420)
            self.inputs[key] = edit
            form.addWidget(edit, row, 1)
        layout.addLayout(form)
        tip = QLabel("Keys are saved only on this computer in api_config.json. Do not commit that file to GitHub.")
        tip.setWordWrap(True)
        layout.addWidget(tip)
        actions = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        actions.addStretch()
        actions.addWidget(save_btn)
        actions.addWidget(cancel_btn)
        layout.addLayout(actions)

    def values(self) -> dict[str, str]:
        return {key: edit.text().strip() for key, edit in self.inputs.items()}


class VideoPreviewDialog(QDialog):
    def __init__(self, video_file: Path, parent=None):
        super().__init__(parent)
        self.video_file = video_file
        self.setWindowTitle("\u6210\u7247\u9884\u89c8")
        self.player = None
        self.audio_output = None

        layout = QVBoxLayout(self)
        self.video_widget = QVideoWidget()
        layout.addWidget(self.video_widget, 1)

        controls = QHBoxLayout()
        self.play_btn = QPushButton("\u64ad\u653e")
        self.play_btn.clicked.connect(self.toggle_play)
        stop_btn = QPushButton("\u505c\u6b62")
        stop_btn.clicked.connect(self.stop)
        save_btn = QPushButton("\u4fdd\u5b58\u89c6\u9891")
        save_btn.clicked.connect(self.save_video)
        close_btn = QPushButton("\u5173\u95ed")
        close_btn.clicked.connect(self.close)
        controls.addWidget(self.play_btn)
        controls.addWidget(stop_btn)
        controls.addStretch()
        controls.addWidget(save_btn)
        controls.addWidget(close_btn)
        layout.addLayout(controls)

        if QMediaPlayer and QAudioOutput:
            self.player = QMediaPlayer(self)
            self.audio_output = QAudioOutput(self)
            self.player.setAudioOutput(self.audio_output)
            self.player.setVideoOutput(self.video_widget)
            self.player.setSource(QUrl.fromLocalFile(str(self.video_file)))
            self.player.playbackStateChanged.connect(self._sync_button)

        self._resize_for_video()

    def _resize_for_video(self):
        size = probe_video_size(self.video_file)
        if size:
            width, height = size
            if width >= height:
                self.resize(1120, 720)
            else:
                self.resize(620, 980)
        else:
            self.resize(1000, 700)

    def toggle_play(self):
        if not self.player:
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def stop(self):
        if self.player:
            self.player.stop()

    def _sync_button(self, *_):
        if self.player and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.play_btn.setText("\u6682\u505c")
        else:
            self.play_btn.setText("\u64ad\u653e")

    def save_video(self):
        target, _ = QFileDialog.getSaveFileName(
            self,
            "\u4fdd\u5b58\u751f\u6210\u89c6\u9891",
            str(OUTPUT / self.video_file.name),
            "MP4 (*.mp4)",
        )
        if not target:
            return
        if not target.lower().endswith(".mp4"):
            target += ".mp4"
        shutil.copy2(self.video_file, target)


class VariantCard(QFrame):
    selected = pyqtSignal(str)

    def __init__(self, name: str, tone: str, body: str, checked: bool = False):
        super().__init__()
        self.body = body
        self.setObjectName("variantCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        top = QHBoxLayout()
        self.radio = QRadioButton()
        self.radio.setChecked(checked)
        title = QLabel(f"{name}  {tone}")
        title.setObjectName("variantTitle")
        top.addWidget(self.radio)
        top.addWidget(title)
        top.addStretch()
        layout.addLayout(top)
        preview = QLabel(compact_text(body, 170))
        preview.setWordWrap(True)
        preview.setObjectName("variantPreview")
        layout.addWidget(preview)
        tags = QLabel(f"语气  {tone}    推荐  {92 if checked else 88}")
        tags.setObjectName("tag")
        layout.addWidget(tags)
        self.radio.toggled.connect(self._emit_if_checked)
        self.mousePressEvent = self._click

    def _click(self, _event):
        self.radio.setChecked(True)

    def _emit_if_checked(self, checked: bool):
        self.setProperty("checked", checked)
        self.style().unpolish(self)
        self.style().polish(self)
        if checked:
            self.selected.emit(self.body)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.state = ProjectState()
        self.api_config = load_api_config()
        self.pool = QThreadPool.globalInstance()
        self.player = None
        self.audio_output = None
        self.video_player = None
        self.video_audio_output = None
        self.audio_player = None
        self.audio_player_output = None
        self.video_dialog = None
        self.video_widget = None
        if QMediaPlayer and QAudioOutput:
            self.audio_player = QMediaPlayer(self)
            self.audio_player_output = QAudioOutput(self)
            self.audio_player.setAudioOutput(self.audio_player_output)
        self.variant_group = QButtonGroup(self)
        self.variant_group.setExclusive(True)

        self.setWindowTitle("口播智能体")
        self.resize(1500, 860)
        self._build_ui()
        self._apply_style()
        self._set_status("本地服务已连接")
        self._set_variants("")

    def _build_ui(self):
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(14, 10, 14, 0)
        outer.setSpacing(12)

        header = QHBoxLayout()
        logo = QLabel("🎙")
        logo.setObjectName("logo")
        name = QLabel("口播智能体")
        name.setObjectName("appName")
        self.status = QLabel()
        self.status.setObjectName("statusPill")
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.setTextVisible(False)
        self.busy.setFixedWidth(130)
        self.busy.setVisible(False)
        header.addWidget(logo)
        header.addWidget(name)
        header.addWidget(self.status)
        header.addWidget(self.busy)
        header.addStretch()
        settings = QToolButton()
        settings.setText("设置")
        settings.setIcon(QIcon.fromTheme("settings"))
        settings.clicked.connect(self.open_api_settings)
        help_btn = QToolButton()
        help_btn.setText("帮助")
        header.addWidget(settings)
        header.addWidget(help_btn)
        outer.addLayout(header)

        input_card = Card()
        input_row = QHBoxLayout()
        input_label = QLabel("视频链接")
        input_label.setObjectName("fieldLabel")
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("请输入视频链接，如：https://v.douyin.com/xxxx/")
        self.extract_btn = QPushButton("文案提取")
        self.extract_btn.setObjectName("primary")
        self.extract_btn.clicked.connect(self.extract_copy)
        input_row.addWidget(input_label)
        input_row.addWidget(self.url_input, 1)
        input_row.addWidget(self.extract_btn)
        input_card.layout.addLayout(input_row)
        outer.addWidget(input_card)

        splitter = QSplitter()
        splitter.setOrientation(Qt.Orientation.Horizontal)
        splitter.addWidget(self._left_panel())
        splitter.addWidget(self._middle_panel())
        splitter.addWidget(self._right_panel())
        splitter.setSizes([440, 440, 600])
        outer.addWidget(splitter, 1)

        self.log_card = Card("任务日志")
        log_header = QHBoxLayout()
        log_header.addStretch()
        clear_btn = QToolButton()
        clear_btn.setText("清空日志")
        log_header.addWidget(clear_btn)
        self.log_card.layout.insertLayout(1, log_header)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("任务进度会显示在这里。")
        clear_btn.clicked.connect(self.log.clear)
        self.log_card.layout.addWidget(self.log)
        self.log_card.setMaximumHeight(118)
        outer.addWidget(self.log_card)

        self.setCentralWidget(root)

    def _left_panel(self) -> QWidget:
        panel = Card("提取内容")
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("标题")
        self.author_edit = QLineEdit()
        self.author_edit.setPlaceholderText("作者")
        self.script_edit = QTextEdit()
        self.script_edit.setPlaceholderText("提取出的口播文案会显示在这里，也可以直接粘贴或修改。")
        self.script_edit.textChanged.connect(self._sync_selected_text)
        counter = QLabel("0/5000")
        counter.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.script_edit.textChanged.connect(lambda: counter.setText(f"{len(self.script_edit.toPlainText())}/5000"))
        panel.layout.addWidget(QLabel("标题"))
        panel.layout.addWidget(self.title_edit)
        panel.layout.addWidget(QLabel("作者"))
        panel.layout.addWidget(self.author_edit)
        panel.layout.addWidget(QLabel("文案"))
        panel.layout.addWidget(self.script_edit, 1)
        panel.layout.addWidget(counter)
        return panel

    def _middle_panel(self) -> QWidget:
        panel = Card("AI改写方案")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.variant_container = QWidget()
        self.variant_stack = QVBoxLayout(self.variant_container)
        self.variant_stack.setContentsMargins(0, 0, 0, 0)
        self.variant_stack.setSpacing(10)
        scroll.setWidget(self.variant_container)
        panel.layout.addWidget(scroll, 2)

        panel.layout.addWidget(QLabel("用于语音合成"))
        self.selected_script_edit = QTextEdit()
        self.selected_script_edit.setPlaceholderText("选择或采用一个 AI 改写方案后，这里会显示用于语音合成的文案。左侧提取原文不会被修改。")
        self.selected_script_edit.setMinimumHeight(145)
        self.selected_script_edit.textChanged.connect(self._sync_voice_script)
        panel.layout.addWidget(self.selected_script_edit, 1)

        bottom = QHBoxLayout()
        regen = QPushButton("重新生成")
        regen.clicked.connect(lambda: self.generate_rewrites(self.script_edit.toPlainText()))
        adopt = QPushButton("采用此方案")
        adopt.setObjectName("primary")
        adopt.clicked.connect(self.adopt_variant)
        polish = QPushButton("人工微调")
        polish.clicked.connect(lambda: self.selected_script_edit.setFocus())
        bottom.addWidget(regen)
        bottom.addWidget(adopt)
        bottom.addWidget(polish)
        panel.layout.addLayout(bottom)
        return panel

    def _right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self._voice_panel())
        layout.addWidget(self._video_panel(), 1)
        return panel

    def _voice_panel(self) -> QWidget:
        card = Card("\u8bed\u97f3\u751f\u6210")
        row = QHBoxLayout()
        row.addWidget(QLabel("\u58f0\u97f3\uff1a"))
        self.voice_box = QComboBox()
        self.voice_box.addItems(["\u8fea\u54e5\u97f3\u8272", "\u6e29\u6696\u5973\u58f0", "\u6c89\u7a33\u7537\u58f0"])
        row.addWidget(self.voice_box)
        row.addWidget(QLabel("\u8bed\u901f\uff1a"))
        self.speed = QSlider(Qt.Orientation.Horizontal)
        self.speed.setRange(80, 140)
        self.speed.setValue(110)
        self.speed_value = QLabel("1.10x")
        self.speed.valueChanged.connect(lambda value: self.speed_value.setText(f"{value / 100:.2f}x"))
        row.addWidget(self.speed, 1)
        row.addWidget(self.speed_value)
        row.addWidget(QLabel("\u60c5\u611f\uff1a"))
        self.emotion_box = QComboBox()
        self.emotion_box.addItems(["happy", "neutral", "sad", "angry", "fearful", "surprised"])
        row.addWidget(self.emotion_box)
        card.layout.addLayout(row)

        actions = QHBoxLayout()
        self.audio_btn = QPushButton("\u751f\u6210\u8bed\u97f3")
        self.audio_btn.setObjectName("primary")
        self.audio_btn.clicked.connect(self.generate_audio)
        self.play_audio_btn = QPushButton("\u64ad\u653e")
        self.play_audio_btn.clicked.connect(self.play_audio)
        self.stop_audio_btn = QPushButton("\u505c\u6b62")
        self.stop_audio_btn.clicked.connect(self.stop_audio)
        self.audio_info = QLabel("\u7b49\u5f85\u751f\u6210")
        self.audio_info.setObjectName("muted")
        actions.addWidget(self.audio_btn)
        actions.addWidget(self.play_audio_btn)
        actions.addWidget(self.stop_audio_btn)
        actions.addWidget(self.audio_info, 1)
        card.layout.addLayout(actions)

        progress = QHBoxLayout()
        self.audio_progress = QSlider(Qt.Orientation.Horizontal)
        self.audio_progress.setRange(0, 0)
        self.audio_progress.sliderMoved.connect(self.seek_audio)
        self.audio_time = QLabel("00:00 / 00:00")
        progress.addWidget(self.audio_progress, 1)
        progress.addWidget(self.audio_time)
        card.layout.addLayout(progress)

        if self.audio_player:
            self.audio_player.positionChanged.connect(self._on_audio_position)
            self.audio_player.durationChanged.connect(self._on_audio_duration)
        return card

    def _video_panel(self) -> QWidget:
        card = Card("\u6570\u5b57\u4eba\u89c6\u9891")
        grid = QGridLayout()
        grid.addWidget(QLabel("\u6570\u5b57\u4eba\uff1a"), 0, 0)
        grid.addWidget(self._choice_button("dige", True), 0, 1)
        grid.addWidget(QLabel("\u80cc\u666f\uff1a"), 1, 0)
        grid.addWidget(self._choice_button("\u9ed8\u8ba4\u80cc\u666f", True), 1, 1)
        grid.addWidget(QLabel("\u753b\u9762\u6bd4\u4f8b\uff1a"), 2, 0)
        ratio_row = QHBoxLayout()
        self.ratio_buttons = {}
        for label in ["9:16", "16:9", "1:1"]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(label == "16:9")
            self.ratio_buttons[label] = btn
            ratio_row.addWidget(btn)
        grid.addLayout(ratio_row, 2, 1, 1, 2)
        card.layout.addLayout(grid)

        self.preview_stack = QStackedWidget()
        self.avatar_preview = QLabel()
        self.avatar_preview.setObjectName("preview")
        self.avatar_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar_preview.setMinimumHeight(360)
        if DEFAULT_AVATAR_IMAGE.exists():
            pixmap = QPixmap(str(DEFAULT_AVATAR_IMAGE))
            if not pixmap.isNull():
                self.avatar_preview.setPixmap(pixmap.scaled(360, 640, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            else:
                self.avatar_preview.setText("\u9ed8\u8ba4\u6570\u5b57\u4eba\u5f62\u8c61")
        else:
            self.avatar_preview.setText("\u9ed8\u8ba4\u6570\u5b57\u4eba\u5f62\u8c61")
        self.preview_stack.addWidget(self.avatar_preview)

        if QVideoWidget and QMediaPlayer and QAudioOutput:
            self.video_widget = QVideoWidget()
            self.preview_stack.addWidget(self.video_widget)
            self.video_player = QMediaPlayer(self)
            self.video_audio_output = QAudioOutput(self)
            self.video_player.setAudioOutput(self.video_audio_output)
            self.video_player.setVideoOutput(self.video_widget)
        card.layout.addWidget(QLabel("\u5f53\u524d\u9009\u62e9\u7684\u6570\u5b57\u4eba\u5f62\u8c61\u9884\u89c8"))
        card.layout.addWidget(self.preview_stack, 1)

        actions = QHBoxLayout()
        export_text = QPushButton("\u5bfc\u51fa\u6587\u6848")
        export_text.clicked.connect(self.export_script)
        save_project = QPushButton("\u4fdd\u5b58\u9879\u76ee")
        save_project.clicked.connect(self.save_project)
        self.video_btn = QPushButton("\u5408\u6210\u89c6\u9891")
        self.video_btn.setObjectName("primary")
        self.video_btn.clicked.connect(self.generate_video)
        self.play_video_btn = QPushButton("\u64ad\u653e\u6210\u7247")
        self.play_video_btn.clicked.connect(self.play_video)
        download = QPushButton("\u4fdd\u5b58\u751f\u6210\u89c6\u9891")
        download.clicked.connect(self.save_generated_video)
        actions.addWidget(export_text)
        actions.addWidget(save_project)
        actions.addWidget(self.video_btn)
        actions.addWidget(self.play_video_btn)
        actions.addWidget(download)
        card.layout.addLayout(actions)
        return card

    def _choice_button(self, text: str, checked: bool) -> QPushButton:
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setChecked(checked)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return btn

    def _set_status(self, text: str):
        self.status.setText(f"●  {text}")

    def _set_variants(self, text: str):
        while self.variant_stack.count():
            item = self.variant_stack.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.variant_group = QButtonGroup(self)
        self.variant_group.setExclusive(True)
        variants = text if isinstance(text, list) else rewrite_variants(text)
        first_body = ""
        for index, (name, tone, body) in enumerate(variants):
            card = VariantCard(name, tone, body, checked=index == 0)
            self.variant_group.addButton(card.radio)
            card.selected.connect(self._select_script)
            self.variant_stack.addWidget(card)
            if index == 0:
                self.state.selected_script = body
                first_body = body
        self.variant_stack.addStretch()
        if first_body and hasattr(self, "selected_script_edit"):
            self.selected_script_edit.blockSignals(True)
            self.selected_script_edit.setPlainText(first_body)
            self.selected_script_edit.blockSignals(False)

    def _select_script(self, body: str):
        self.state.selected_script = body
        if hasattr(self, "selected_script_edit"):
            self.selected_script_edit.blockSignals(True)
            self.selected_script_edit.setPlainText(body)
            self.selected_script_edit.blockSignals(False)

    def _sync_selected_text(self):
        self.state.script = self.script_edit.toPlainText()
        if not self.state.selected_script:
            self.state.selected_script = self.state.script

    def _sync_voice_script(self):
        self.state.selected_script = self.selected_script_edit.toPlainText().strip()

    def _add_log(self, message: str):
        timestamp = time.strftime("%H:%M:%S")
        self.log.append(f"[{timestamp}] {message}")

    def _run(self, worker: CommandWorker):
        worker.signals.started.connect(lambda task: self._task_started(task))
        worker.signals.line.connect(self._add_log)
        worker.signals.done.connect(self._task_done)
        worker.signals.failed.connect(self._task_failed)
        self.pool.start(worker)

    def _run_rewrite(self, text: str):
        worker = DeepSeekWorker(text, self.api_config.get("deepseek_api_key", ""))
        worker.signals.started.connect(lambda task: self._task_started(task))
        worker.signals.done.connect(self._task_done)
        worker.signals.failed.connect(self._task_failed)
        self.pool.start(worker)

    def _task_started(self, task: str):
        labels = {
            "extract": "文案提取中...",
            "rewrite": "AI 改写中...",
            "audio": "语音合成中...",
            "video": "视频合成中...",
        }
        self._set_status(labels.get(task, "任务运行中..."))
        self._add_log(labels.get(task, task))
        self.busy.setVisible(True)
        self._set_buttons(False)

    def _task_done(self, task: str, result: object):
        self._set_buttons(True)
        self.busy.setVisible(False)
        if task == "extract":
            data = result
            assert isinstance(data, dict)
            meta = infer_meta_from_share_text(self.state.source_url, data.get("script") or "")
            self.title_edit.setText(data.get("title") or meta["title"])
            self.author_edit.setText(data.get("author") or meta["author"])
            self.script_edit.setPlainText(data.get("script") or "")
            self._set_status("文案提取完成")
            self._add_log("文案提取完成")
            if data.get("task_id"):
                self._add_log(f"17zhiling taskId: {data.get('task_id')}")
            self.generate_rewrites(data.get("script") or "")
        elif task == "rewrite":
            assert isinstance(result, list)
            self._set_variants(result)
            if result:
                self.state.selected_script = result[0][2]
            self._set_status("AI 改写完成")
            self._add_log("DeepSeek 已生成口播改写方案")
        elif task == "audio":
            data = result
            assert isinstance(data, dict)
            self.state.audio_file = Path(data["output_file"])
            if not self.state.audio_file.exists():
                self._task_failed(task, f"语音接口返回成功，但文件不存在：{self.state.audio_file}")
                return
            duration = data.get("duration_sec") or data.get("api_audio_length_ms")
            self.audio_info.setText(f"已生成：{self.state.audio_file.name}  {duration or ''}")
            self._set_status("语音生成完成")
            self._add_log(f"语音文件：{self.state.audio_file}")

        elif task == "video":
            data = result
            assert isinstance(data, dict)
            if not data.get("ok"):
                self._task_failed(task, json.dumps(data, ensure_ascii=False, indent=2))
                return

            local_file = Path(str(data.get("local_file") or ""))
            if not local_file.exists():
                local_file = self._find_latest_video_file()

            self.state.video_file = local_file if local_file and local_file.exists() else None
            self.state.video_url = data.get("video_url", "")
            if not self.state.video_file:
                self._task_failed(task, "视频合成已完成，但未在输出目录找到 MP4 文件。")
                return

            self._set_status("视频合成完成")
            self._add_log(f"视频文件：{self.state.video_file}")
            self.load_video_preview()

    def _find_latest_video_file(self) -> Path | None:
        candidates = list(OUTPUT.glob("*.mp4"))
        if not candidates:
            return None
        started_at = getattr(self, "video_task_started_at", 0)
        recent = [p for p in candidates if p.stat().st_mtime >= started_at - 10]
        pool = recent or candidates
        return max(pool, key=lambda p: p.stat().st_mtime)

    def _task_failed(self, task: str, message: str):
        message = friendly_error(task, message)
        self._set_buttons(True)
        self.busy.setVisible(False)
        if task == "rewrite":
            self._set_variants(self.script_edit.toPlainText())
            self._set_status("AI 改写失败，已使用本地方案")
            self._add_log(message)
            return
        self._set_status("任务失败")
        self._add_log(message)
        QMessageBox.critical(self, "任务失败", compact_text(message, 1000))

    def _set_buttons(self, enabled: bool):
        self.extract_btn.setEnabled(enabled)
        self.audio_btn.setEnabled(enabled)
        self.video_btn.setEnabled(enabled)

    def open_api_settings(self) -> bool:
        dialog = ApiSettingsDialog(self.api_config, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        self.api_config = normalize_api_config(dialog.values())
        save_api_config(self.api_config)
        missing = missing_api_fields(self.api_config)
        if missing:
            QMessageBox.warning(self, "API settings incomplete", "Missing: " + ", ".join(missing))
            return False
        self._set_status("API keys saved")
        return True

    def ensure_api_config(self) -> bool:
        self.api_config = normalize_api_config(self.api_config)
        missing = missing_api_fields(self.api_config)
        if not missing:
            return True
        QMessageBox.information(self, "API settings required", "Please fill in API keys before using this function.")
        return self.open_api_settings()

    def generate_rewrites(self, text: str):
        if not self.ensure_api_config():
            return
        text = text.strip()
        if not text:
            self._set_variants("")
            return
        self._set_variants([
            ("方案 A", "生成中", "DeepSeek 正在润色文案，请稍等。"),
            ("方案 B", "生成中", "会加强开头钩子，让内容更适合 IP 博主口播。"),
            ("方案 C", "生成中", "会保留事实信息，同时提升吸引力和讲解感。"),
        ])
        self._run_rewrite(text)

    def extract_copy(self):
        if not self.ensure_api_config():
            return
        source = self.url_input.text().strip()
        if not source:
            QMessageBox.warning(self, "缺少链接", "请输入抖音视频链接或分享文本。")
            return
        self.state.source_url = source
        self.state.audio_file = None
        self.audio_info.setText("等待生成")
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        command = [
            *PYTHON_RUNNER,
            str(DOUYIN_SCRIPT),
            source,
            "--key",
            self.api_config.get("zhiling_key", ""),
            "--json",
            "--out-dir",
            str(OUTPUT),
        ]
        self._run(CommandWorker("extract", command, parse_extract, env))

    def adopt_variant(self):
        if self.state.selected_script:
            self.selected_script_edit.setPlainText(self.state.selected_script)
            self._add_log("已采用当前方案作为语音合成文案，左侧提取原文保持不变")

    def current_script(self) -> str:
        voice_text = self.selected_script_edit.toPlainText().strip() if hasattr(self, "selected_script_edit") else ""
        text = voice_text or self.state.selected_script or self.script_edit.toPlainText().strip()
        return text.strip()

    def generate_audio(self):
        if not self.ensure_api_config():
            return
        text = self.current_script()
        if not text:
            QMessageBox.warning(self, "缺少文案", "请先提取或输入口播文案。")
            return
        stamp = time.strftime("%Y%m%d_%H%M%S")
        text_file = OUTPUT / f"script_{stamp}.txt"
        text_file.write_text(text, encoding="utf-8")
        out_file = OUTPUT / f"minimax_voice_{stamp}.mp3"
        self.state.audio_file = None
        self.audio_info.setText("生成中...")
        self._add_log(f"提交语音合成文案：{len(text)} 字")
        command = [
            *PYTHON_RUNNER,
            str(MINIMAX_SCRIPT),
            "--text-file",
            str(text_file),
            "--api-key",
            self.api_config.get("minimax_api_key", ""),
            "--out",
            str(out_file),
            "--speed",
            f"{self.speed.value() / 100:.2f}",
            "--emotion",
            self.emotion_box.currentText(),
        ]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        self._run(CommandWorker("audio", command, lambda output, expected=out_file: {**parse_audio(output), "output_file": str(expected)}, env))

    def generate_video(self):
        if not self.ensure_api_config():
            return
        if not self.state.audio_file or not self.state.audio_file.exists():
            QMessageBox.warning(self, "\u7f3a\u5c11\u97f3\u9891", "\u8bf7\u5148\u751f\u6210\u8bed\u97f3\uff0c\u6216\u9009\u62e9\u4e00\u4e2a\u672c\u5730\u97f3\u9891\u6587\u4ef6\u3002")
            path, _ = QFileDialog.getOpenFileName(self, "\u9009\u62e9\u97f3\u9891", str(OUTPUT), "Audio (*.mp3 *.wav *.m4a)")
            if not path:
                return
            self.state.audio_file = Path(path)
        self.video_task_started_at = time.time()
        ratio = self.selected_video_ratio()
        screen_width, screen_height = self.video_size_for_ratio(ratio)
        self._add_log(f"\u4f7f\u7528\u8bed\u97f3\u6587\u4ef6\u5408\u6210 {ratio} \u6570\u5b57\u4eba\u89c6\u9891\uff1a{self.state.audio_file}")
        command = [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(DIGE_SCRIPT),
            "-AppId",
            self.api_config.get("chanjing_app_id", ""),
            "-SecretKey",
            self.api_config.get("chanjing_secret_key", ""),
            "-PersonId",
            self.api_config.get("chanjing_person_id", ""),
            "-AudioPath",
            str(self.state.audio_file),
            "-OutputDir",
            str(OUTPUT),
            "-ScreenWidth",
            str(screen_width),
            "-ScreenHeight",
            str(screen_height),
            "-PollSeconds",
            "5",
            "-MaxPolls",
            "180",
        ]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        self._run(CommandWorker("video", command, parse_video, env))

    def selected_video_ratio(self) -> str:
        for ratio, button in getattr(self, "ratio_buttons", {}).items():
            if button.isChecked():
                return ratio
        return "16:9"

    def video_size_for_ratio(self, ratio: str) -> tuple[int, int]:
        if ratio == "9:16":
            return 1080, 1920
        if ratio == "1:1":
            return 1080, 1080
        return 1920, 1080

    def _format_ms(self, value: int) -> str:
        seconds = max(0, value // 1000)
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def _on_audio_duration(self, duration: int):
        if hasattr(self, "audio_progress"):
            self.audio_progress.setRange(0, max(0, duration))
            self.audio_time.setText(f"00:00 / {self._format_ms(duration)}")

    def _on_audio_position(self, position: int):
        if hasattr(self, "audio_progress") and not self.audio_progress.isSliderDown():
            self.audio_progress.setValue(position)
        duration = self.audio_player.duration() if self.audio_player else 0
        if hasattr(self, "audio_time"):
            self.audio_time.setText(f"{self._format_ms(position)} / {self._format_ms(duration)}")

    def seek_audio(self, position: int):
        if self.audio_player:
            self.audio_player.setPosition(position)

    def stop_audio(self):
        if self.audio_player:
            self.audio_player.stop()
            if hasattr(self, "audio_progress"):
                self.audio_progress.setValue(0)
            if hasattr(self, "audio_time"):
                self.audio_time.setText("00:00 / 00:00")

    def play_audio(self):
        if not self.state.audio_file or not self.state.audio_file.exists():
            QMessageBox.information(self, "\u6682\u65e0\u97f3\u9891", "\u8fd8\u6ca1\u6709\u53ef\u64ad\u653e\u7684\u97f3\u9891\u6587\u4ef6\u3002")
            return
        if not self.audio_player:
            QMessageBox.information(self, "\u64ad\u653e\u5931\u8d25", "\u5f53\u524d Qt \u73af\u5883\u4e0d\u652f\u6301\u5185\u7f6e\u97f3\u9891\u64ad\u653e\u3002")
            return
        self.audio_player.setSource(QUrl.fromLocalFile(str(self.state.audio_file)))
        self.audio_player.play()
        self._add_log("\u6b63\u5728\u64ad\u653e\u97f3\u9891")

    def load_video_preview(self):
        if not self.state.video_file or not self.state.video_file.exists():
            return
        self.show_video_dialog(auto_play=True)

    def play_video(self):
        if not self.state.video_file or not self.state.video_file.exists():
            QMessageBox.information(self, "\u6682\u65e0\u6210\u7247", "\u89c6\u9891\u5408\u6210\u5b8c\u6210\u540e\u53ef\u4ee5\u5728\u8fd9\u91cc\u64ad\u653e\u3002")
            return
        self.show_video_dialog(auto_play=True)

    def show_video_dialog(self, auto_play: bool = False):
        if not self.state.video_file or not self.state.video_file.exists():
            return
        if not QVideoWidget or not QMediaPlayer or not QAudioOutput:
            QMessageBox.information(self, "\u64ad\u653e\u5931\u8d25", "\u5f53\u524d Qt \u73af\u5883\u4e0d\u652f\u6301\u5185\u7f6e\u89c6\u9891\u64ad\u653e\u3002")
            return
        self.video_dialog = VideoPreviewDialog(self.state.video_file, self)
        self.video_dialog.show()
        self.video_dialog.raise_()
        self.video_dialog.activateWindow()
        if auto_play and self.video_dialog.player:
            self.video_dialog.player.play()

    def save_generated_video(self):
        if not self.state.video_file or not self.state.video_file.exists():
            QMessageBox.information(self, "\u6682\u65e0\u6210\u7247", "\u89c6\u9891\u5408\u6210\u5b8c\u6210\u540e\u53ef\u4ee5\u5728\u8fd9\u91cc\u4fdd\u5b58\u3002")
            return
        target, _ = QFileDialog.getSaveFileName(self, "\u4fdd\u5b58\u751f\u6210\u89c6\u9891", str(OUTPUT / self.state.video_file.name), "MP4 (*.mp4)")
        if not target:
            return
        if not target.lower().endswith(".mp4"):
            target += ".mp4"
        shutil.copy2(self.state.video_file, target)
        self._add_log(f"\u751f\u6210\u89c6\u9891\u5df2\u4fdd\u5b58\uff1a{target}")

    def export_script(self):
        text = self.script_edit.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "暂无文案", "没有可导出的文案。")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出文案", str(OUTPUT / "script.txt"), "Text (*.txt)")
        if path:
            Path(path).write_text(text, encoding="utf-8")
            self._add_log(f"文案已导出：{path}")

    def save_project(self):
        payload = {
            "source_url": self.url_input.text().strip(),
            "title": self.title_edit.text().strip(),
            "author": self.author_edit.text().strip(),
            "script": self.script_edit.toPlainText(),
            "audio_file": str(self.state.audio_file or ""),
            "video_file": str(self.state.video_file or ""),
            "video_url": self.state.video_url,
        }
        path, _ = QFileDialog.getSaveFileName(self, "保存项目", str(OUTPUT / "project.json"), "JSON (*.json)")
        if path:
            Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self._add_log(f"项目已保存：{path}")

    def _apply_style(self):
        self.setStyleSheet(
            """
            QWidget { font-family: "Microsoft YaHei UI", "Segoe UI"; font-size: 14px; color: #171b26; }
            QMainWindow, QWidget { background: #f6f8fb; }
            #logo { background: #246bfe; color: white; border-radius: 10px; padding: 7px 10px; font-size: 19px; }
            #appName { font-size: 22px; font-weight: 700; }
            #statusPill { color: #15803d; background: #edfdf3; border: 1px solid #c9f1d7; border-radius: 7px; padding: 7px 14px; }
            #card { background: white; border: 1px solid #dce3ee; border-radius: 8px; }
            #cardTitle { font-size: 18px; font-weight: 700; }
            #fieldLabel { font-weight: 700; font-size: 16px; }
            QLineEdit, QTextEdit, QComboBox { background: white; border: 1px solid #d5deea; border-radius: 6px; padding: 9px 10px; }
            QTextEdit { line-height: 1.5; }
            QPushButton, QToolButton { background: #ffffff; border: 1px solid #d5deea; border-radius: 6px; padding: 9px 15px; font-weight: 600; }
            QPushButton:hover, QToolButton:hover { border-color: #246bfe; }
            QPushButton#primary { color: white; background: #246bfe; border-color: #246bfe; }
            QPushButton#primary:disabled { background: #9db8ff; border-color: #9db8ff; }
            QProgressBar { border: 1px solid #cfe0ff; border-radius: 5px; background: #eef5ff; height: 10px; }
            QProgressBar::chunk { background: #246bfe; border-radius: 5px; }
            #variantCard { background: white; border: 1px solid #dce3ee; border-radius: 8px; }
            #variantCard[checked="true"] { border: 2px solid #246bfe; background: #fbfdff; }
            #variantTitle { color: #1d5be3; font-weight: 700; }
            #variantPreview { color: #2d3648; line-height: 1.5; }
            #tag { color: #15803d; background: #f3faf5; border: 1px solid #daeade; border-radius: 5px; padding: 4px 8px; }
            #muted { color: #657184; }
            #preview { background: #151923; color: white; border-radius: 8px; min-height: 250px; font-size: 22px; }
            QSplitter::handle { background: #eef2f7; width: 8px; }
            """
        )



def run_script_mode() -> bool:
    if len(sys.argv) < 3 or sys.argv[1] != "--run-script":
        return False
    script = Path(sys.argv[2]).resolve()
    sys.argv = [str(script), *sys.argv[3:]]
    runpy.run_path(str(script), run_name="__main__")
    return True


def main():
    if run_script_mode():
        return
    app = QApplication(sys.argv)
    app.setApplicationName("口播智能体")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
