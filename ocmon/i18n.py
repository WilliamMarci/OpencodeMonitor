"""Tiny two-language string table (English / 简体中文)."""

from __future__ import annotations

import locale

_EN = {
    "refresh_now": "Refresh now",
    "settings": "Settings…",
    "display": "Display",
    "show_used": "Show used",
    "show_remaining": "Show remaining",
    "always_on_top": "Always on top",
    "quit": "Quit",
    "hide": "Hide",
    "show": "Show",
    "window_title": "opencode usage",
    "source": "Data source",
    "source_auto": "Auto (API, then local)",
    "source_api": "Zen / Go API",
    "source_local": "Local opencode data",
    "source_demo": "Demo (animated)",
    "api_base": "API base URL",
    "api_key": "API key",
    "api_key_hint": "leave empty to read from auth.json",
    "monthly_budget": "Monthly budget (USD)",
    "refresh_interval": "Refresh interval (s)",
    "opacity": "Window opacity (%)",
    "autostart": "Start with system",
    "language": "Language",
    "test": "Test",
    "test_ok": "OK – got {count} window(s) from {source}.",
    "test_fail": "Failed: {error}",
    "test_parsed": "Parsed: {detail}",
    "raw_response": "View raw response…",
    "raw_title": "Raw usage response",
    "save": "Save",
    "cancel": "Cancel",
    "budget_share": "5h / 1w limits are derived from the monthly budget "
                    "(20% / 50%) unless the API reports its own limits.",
    "status_live": "live",
    "status_demo": "demo",
    "status_error": "error",
    "tip_window": "{label}  used {used} / {limit}  ({percent}%)\n"
                   "resets in {reset}\ndouble-click: settings",
    "tip_no_data": "{label}  no data",
    "reset_in": "in {text}",
}


_ZH = {
    "refresh_now": "立即刷新",
    "settings": "设置…",
    "display": "显示",
    "show_used": "显示已用",
    "show_remaining": "显示剩余",
    "always_on_top": "窗口置顶",
    "quit": "退出",
    "hide": "隐藏",
    "show": "显示",
    "window_title": "opencode 用量",
    "source": "数据源",
    "source_auto": "自动（优先 API，其次本地）",
    "source_api": "Zen / Go API",
    "source_local": "本地 opencode 数据",
    "source_demo": "演示（动画）",
    "api_base": "API 地址",
    "api_key": "API 密钥",
    "api_key_hint": "留空则读取 auth.json",
    "monthly_budget": "每月预算（美元）",
    "refresh_interval": "刷新间隔（秒）",
    "opacity": "窗口不透明度（%）",
    "autostart": "开机自启",
    "language": "语言",
    "test": "测试",
    "test_ok": "成功 – 从 {source} 获取到 {count} 个窗口。",
    "test_fail": "失败：{error}",
    "test_parsed": "解析结果：{detail}",
    "raw_response": "查看原始响应…",
    "raw_title": "原始用量响应",
    "save": "保存",
    "cancel": "取消",
    "budget_share": "除非 API 返回自身的限额，5h / 1w 限额按每月预算的 "
                    "20% / 50% 计算。",
    "status_live": "实时",
    "status_demo": "演示",
    "status_error": "错误",
    "tip_window": "{label}  已用 {used} / {limit}（{percent}%）\n"
                   "重置倒计时 {reset}\n双击：设置",
    "tip_no_data": "{label}  暂无数据",
    "reset_in": "剩余 {text}",
}

_TABLES = {"en": _EN, "zh": _ZH}


def detect_language() -> str:
    try:
        name = locale.getlocale()[0] or ""
    except Exception:  # noqa: BLE001
        name = ""
    return "zh" if name.lower().startswith("zh") else "en"


class Translator:
    def __init__(self, language: str = "auto") -> None:
        self._lang = "en"
        self.set_language(language)

    def set_language(self, language: str) -> None:
        if language == "auto":
            language = detect_language()
        self._lang = language if language in _TABLES else "en"

    @property
    def language(self) -> str:
        return self._lang

    def __call__(self, key: str, **kwargs) -> str:
        table = _TABLES.get(self._lang, _EN)
        text = table.get(key, _EN.get(key, key))
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
