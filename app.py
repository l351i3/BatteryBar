#!/usr/bin/env python3

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from datetime import datetime

import rumps

from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
)
from PyObjCTools import AppHelper

from classifier import (
    category_label,
    category_sort_key,
)
from models import (
    power_state_label,
)
from provider_registry import (
    create_default_aggregator,
)
from snapshot_store import (
    SnapshotStoreError,
    write_snapshot_atomic,
)

from widget_snapshot_sync import (
    sync_widget_snapshot,
)


APP_NAME = "Battery Bar"
APP_TITLE = "🔋"
APP_VERSION = "2.1.2"
APP_BUNDLE_ID = (
    "io.github.l351i3.batterybar"
)
APP_COPYRIGHT = (
    "Copyright © 2026 l351i3. "
    "All rights reserved."
)

# 菜单栏图标路径（@2x 用于 Retina）
_RESOURCES_DIR = os.path.join(
    os.path.dirname(
        os.path.abspath(__file__)
    ),
    "resources",
)
# PyInstaller 打包后资源在 sys._MEIPASS/resources
if (
    getattr(sys, "frozen", False)
    and hasattr(sys, "_MEIPASS")
):
    _RESOURCES_DIR = os.path.join(
        sys._MEIPASS, "resources"
    )
_MENU_ICON_NORMAL = os.path.join(
    _RESOURCES_DIR, "MenuBarNormal@2x.png"
)
_MENU_ICON_LOW = os.path.join(
    _RESOURCES_DIR, "MenuBarLow@2x.png"
)
_MENU_ICON_FULL = os.path.join(
    _RESOURCES_DIR, "MenuBarFull@2x.png"
)
_MENU_ICON_CHARGING = os.path.join(
    _RESOURCES_DIR, "MenuBarCharging@2x.png"
)

AUTO_REFRESH_SECONDS = 300
CACHE_EXPIRY_SECONDS = 600

EMPTY_MESSAGE = "暂无可用的外设电量"
REFRESHING_MESSAGE = "正在刷新…"
NEVER_REFRESHED_MESSAGE = "尚未刷新"

COMPONENT_SUFFIXES = (
    " · 左耳",
    " · 右耳",
    " · 电池盒",
)

def _clean_text(value):
    return " ".join(
        str(value).split()
    )

def _menu_icon_path(state):
    """返回指定状态的菜单栏图标文件路径。

    state ∈ {"normal","low","full","charging"}。
    文件不存在时返回 None（调用方回退到 emoji 标题）。
    """
    table = {
        "normal": _MENU_ICON_NORMAL,
        "low": _MENU_ICON_LOW,
        "full": _MENU_ICON_FULL,
        "charging": _MENU_ICON_CHARGING,
    }
    path = table.get(state)
    if path and os.path.isfile(path):
        return path
    return None


def _device_group_name(device):
    name = _clean_text(
        device.name
    )

    for suffix in COMPONENT_SUFFIXES:
        if name.endswith(suffix):
            return name[
                :-len(suffix)
            ].rstrip()
    
    return name


def _device_component_label(device):
    name = _clean_text(
        device.name
    )

    for suffix in COMPONENT_SUFFIXES:
        if name.endswith(suffix):
            return suffix.replace(
                " · ",
                "",
            )
    
    return ""


def _format_level(device):
    text = f"{device.level}%"

    state = power_state_label(
        device.power_state
    )
    
    if state:
        text += f" · {state}"
    
    # 强化缓存标识：改为“已离线”并放在更显眼的位置
    if device.cached:
        text = f"[已离线] {text}"
    
    return text


def _format_device_title(device):
    component = (
        _device_component_label(
            device
        )
    )

    if component:
        name = component
    else:
        name = device.name
    
    return (
        f"{name}    "
        f"{_format_level(device)}"
    )


def _format_update_time(timestamp):
    if timestamp is None:
        return NEVER_REFRESHED_MESSAGE

    try:
        value = float(timestamp)
        moment = datetime.fromtimestamp(
            value
        )
    except (
        TypeError,
        ValueError,
        OSError,
        OverflowError,
    ):
        return NEVER_REFRESHED_MESSAGE
    
    return moment.strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def _group_devices(devices):
    groups = {}

    for device in devices:
        groups.setdefault(
            device.category,
            [],
        ).append(device)
    
    return [
        (
            category,
            groups[category],
        )
        for category in sorted(
            groups,
            key=category_sort_key,
        )
    ]


def _group_physical_devices(devices):
    groups = {}
    order = []

    for device in devices:
        name = _device_group_name(
            device
        )
    
        if name not in groups:
            groups[name] = []
            order.append(name)
    
        groups[name].append(device)
    
    return [
        (
            name,
            groups[name],
        )
        for name in order
    ]


def build_menu_rows(snapshot):
    """
    将 BatterySnapshot 转换成菜单描述。

    返回值只包含普通 Python 数据，
    便于测试和后续 Widget 复用。
    """
    if snapshot is None:
        return [
            {
                "kind": "message",
                "title": (
                    NEVER_REFRESHED_MESSAGE
                ),
            }
        ]
    
    if not snapshot.devices:
        return [
            {
                "kind": "message",
                "title": EMPTY_MESSAGE,
            }
        ]
    
    rows = []
    
    for (
        category,
        category_devices,
    ) in _group_devices(
        snapshot.devices
    ):
        rows.append(
            {
                "kind": "category",
                "title": (
                    category_label(
                        category
                    )
                ),
            }
        )
    
        physical_groups = (
            _group_physical_devices(
                category_devices
            )
        )
    
        for (
            group_name,
            group_devices,
        ) in physical_groups:
            if (
                len(group_devices) == 1
                and not (
                    _device_component_label(
                        group_devices[0]
                    )
                )
            ):
                rows.append(
                    {
                        "kind": "device",
                        "title": (
                            _format_device_title(
                                group_devices[0]
                            )
                        ),
                        "device": (
                            group_devices[0]
                        ),
                    }
                )
                continue
    
            rows.append(
                {
                    "kind": "device_group",
                    "title": group_name,
                }
            )
    
            for device in group_devices:
                rows.append(
                    {
                        "kind": "component",
                        "title": (
                            _format_device_title(
                                device
                            )
                        ),
                        "device": device,
                    }
                )
    
    return rows


def _ensure_login_item():
    """
    首次启动时自动添加到登录项。
    """
    try:
        exe_path = os.path.abspath(
            sys.executable
        )
        app_path = os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    exe_path
                )
            )
        )

        result = subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "System Events" '
                "to get the name of every login item",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    
        if APP_NAME in result.stdout:
            return
    
        subprocess.run(
            [
                "osascript",
                "-e",
                f'tell application "System Events" '
                f"to make login item at end "
                f'with properties {{path:"{app_path}", '
                f"hidden:true}}",
            ],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass


class BatteryBarApp(
    rumps.App
):
    def __init__(self):
        icon_path = _menu_icon_path(
            "normal"
        )
        if icon_path is not None:
            # 核心修复：这里绝对不能传递 template=True！
            # 如果在初始化时传递了 template=True，rumps 在底层会将整个 NSStatusItem 
            # 永久标记为模板模式，之后任何设置图标的操作都会被强制黑白化。
            # 我们必须在初始化时将其设为 False，然后在图标更新方法 _update_menu_icon 
            # 中对普通图标动态手动开启 setTemplate_(True)，而对低电量红色图标不开启。
            super().__init__(
                APP_NAME,
                icon=icon_path,
                template=False,
                quit_button=None,
            )
        else:
            super().__init__(
                APP_NAME,
                title=APP_TITLE,
                quit_button=None,
            )
        self._icon_enabled = (
            icon_path is not None
        )

        self.aggregator = (
            create_default_aggregator(
                cache_expiry_seconds=(
                    CACHE_EXPIRY_SECONDS
                )
            )
        )
    
        self.refresh_lock = (
            threading.Lock()
        )
        self.latest_snapshot = None
        self.refresh_started_at = None
        self.last_snapshot_error = None
    
        self.refresh_item = rumps.MenuItem(
            "立即刷新",
            callback=self.on_refresh,
        )
        self.updated_item = (
            rumps.MenuItem(
                "上次刷新："
                + NEVER_REFRESHED_MESSAGE
            )
        )
        self.updated_item.set_callback(
            None
        )
    
        self.provider_item = (
            rumps.MenuItem(
                "数据源状态"
            )
        )
        self.provider_item.set_callback(
            None
        )
    
        self.about_item = (
            rumps.MenuItem(
                "关于 Battery Bar",
                callback=self.on_about,
            )
        )
        self.quit_item = (
            rumps.MenuItem(
                "退出",
                callback=self.on_quit,
            )
        )
    
        self.timer = rumps.Timer(
            self.on_timer,
            AUTO_REFRESH_SECONDS,
        )
    
        self._render_menu()
    
    def _set_item_enabled(
        self,
        item,
        enabled,
    ):
        """
        同时设置 rumps 回调和底层 NSMenuItem 状态。
    
        只依赖 set_callback(None) 时，AppKit 菜单验证可能在
        菜单重建后重新计算显示状态，造成同一信息项偶尔灰白不一。
        """
        if not isinstance(enabled, bool):
            raise TypeError(
                "enabled must be a bool"
            )
    
        menu_item = getattr(
            item,
            "_menuitem",
            None,
        )
    
        if menu_item is not None:
            menu_item.setEnabled_(
                enabled
            )
    
        return item
    
    def _make_disabled_item(
        self,
        title,
    ):
        item = rumps.MenuItem(
            title
        )
        item.set_callback(None)
    
        return self._set_item_enabled(
            item,
            False,
        )
    
    def _make_device_item(
        self,
        title,
    ):
        """
        创建醒目的设备信息项。
    
        rumps 会把无回调项目显示为灰色，因此设备行使用
        无操作回调保持白色；点击不会执行任何业务操作。
        """
        item = rumps.MenuItem(
            title,
            callback=self.on_device_item,
        )
    
        return self._set_item_enabled(
            item,
            True,
        )
    
    def _make_provider_submenu(
        self,
        snapshot,
    ):
        item = rumps.MenuItem(
            "数据源状态"
        )
    
        if snapshot is None:
            item.add(
                self._make_disabled_item(
                    NEVER_REFRESHED_MESSAGE
                )
            )
            return item
    
        for status in (
            snapshot.provider_statuses
        ):
            if status.succeeded:
                title = (
                    f"{status.name}：正常"
                    f"（{status.device_count} 条，"
                    f"{status.duration_seconds:.2f}s）"
                )
            else:
                title = (
                    f"{status.name}：失败"
                )
    
            item.add(
                self._make_disabled_item(
                    title
                )
            )
    
            if status.error:
                item.add(
                    self._make_disabled_item(
                        "  " + status.error
                    )
                )
    
        if self.last_snapshot_error:
            item.add(
                rumps.separator
            )
            item.add(
                self._make_disabled_item(
                    "快照写入失败："
                    + self.last_snapshot_error
                )
            )
    
        return item
    
    def _render_menu(self):
        menu_items = []
    
        if self.refresh_lock.locked():
            menu_items.append(
                self._make_disabled_item(
                    REFRESHING_MESSAGE
                )
            )
        else:
            for row in build_menu_rows(
                self.latest_snapshot
            ):
                kind = row["kind"]
                title = row["title"]
    
                if kind == "category":
                    menu_items.append(
                        self._make_disabled_item(
                            title
                        )
                    )
                elif kind == "device_group":
                    menu_items.append(
                        self._make_device_item(
                            title
                        )
                    )
                elif kind == "component":
                    menu_items.append(
                        self._make_device_item(
                            "  " + title
                        )
                    )
                elif kind == "device":
                    # 核心修改：如果是缓存设备，使用 _make_disabled_item 渲染为灰色
                    if row["device"].cached:
                        menu_items.append(
                            self._make_disabled_item(title)
                        )
                    else:
                        menu_items.append(
                            self._make_device_item(title)
                        )
    
        menu_items.append(
            rumps.separator
        )
    
        if self.latest_snapshot is None:
            updated_text = (
                NEVER_REFRESHED_MESSAGE
            )
        else:
            updated_text = (
                _format_update_time(
                    self.latest_snapshot
                    .updated_at
                )
            )
    
        self.updated_item = (
            self._make_disabled_item(
                "上次刷新："
                + updated_text
            )
        )
    
        self.provider_item = (
            self._make_provider_submenu(
                self.latest_snapshot
            )
        )
    
        menu_items.extend(
            [
                self.updated_item,
                self.refresh_item,
                self.provider_item,
                rumps.separator,
                self.about_item,
                self.quit_item,
            ]
        )
    
        self.menu.clear()
    
        for item in menu_items:
            self.menu.add(item)
    
    def request_refresh(self):
        if not self.refresh_lock.acquire(
            blocking=False
        ):
            return False
    
        self.refresh_started_at = (
            time.time()
        )
        self.refresh_item.title = (
            REFRESHING_MESSAGE
        )
        self.refresh_item.set_callback(
            None
        )
        self._set_item_enabled(
            self.refresh_item,
            False,
        )
        self._render_menu()
    
        worker = threading.Thread(
            target=self._refresh_worker,
            name="BatteryBarRefresh",
            daemon=True,
        )
        worker.start()
    
        return True
    
    def _refresh_worker(self):
        snapshot = None
        error = None
    
        try:
            try:
                snapshot = self.aggregator.refresh()
            except Exception as caught:
                error = f"{type(caught).__name__}: {caught}"
    
            if snapshot is not None:
                try:
                    write_snapshot_atomic(snapshot)
                    self.last_snapshot_error = None
                except Exception as caught:
                    self.last_snapshot_error = f"{type(caught).__name__}: {caught}"
                else:
                    try:
                        sync_widget_snapshot()
                    except Exception:
                        pass
        finally:
            AppHelper.callAfter(
                self._finish_refresh,
                snapshot,
                error,
            )
    
    def _select_menu_icon(self, snapshot):
        """根据快照设备状态选择菜单栏图标状态。
    
        返回 "normal"/"low"/"full"/"charging"。
        优先级采用安全第一（Safety-First）原则：
        1. 存在未充电的低电量外设（<=20%） → low （最高优先级安全警告）
        2. 存在正在充电的外设（且该设备不属于未充电的低电量威胁状态） → charging
        3. 所有设备电量 >=95% → full
        4. 其他 → normal
    
        快照为 None 或无设备时保持 normal。
        """
    
        if (
            snapshot is None
            or not snapshot.devices
        ):
            return "normal"
    
        has_unplugged_low = False
        has_charging = False
        all_full = True
        
        for dev in snapshot.devices:
            # --- 核心修复开始 ---
            # 逻辑隔离：已断开（缓存）的设备不参与菜单栏图标的状态判定
            if dev.cached:
                continue 
            # --- 核心修复结束 ---
            
            is_charging = (
                dev.charging is True
                and dev.power_state != "charged"
            )
            if is_charging:
                has_charging = True
             
            # 核心修复：彻底取消对 dev.category == 'internal' 的分类过滤限制！
            # 无论内置电池还是任何连接的外设/附件（如蓝牙键盘、鼠标、AirPods），只要未在充电且电量 <= 20%，均能触发低电量图标
            # 同时加入类型转换防御，防止因底层电量解析异常（如非数字）导致程序中断
            try:
                level_val = int(dev.level)
            except (TypeError, ValueError):
                level_val = 100
            
            # 仅在设备低电量且未处于充电状态时，才触发低电量威胁警告
            if dev.level <= 20 and not is_charging:
                has_unplugged_low = True
    
            if dev.level < 95:
                all_full = False


        if has_unplugged_low:
            return "low"
        elif has_charging:
            return "charging"
        elif all_full:
            return "full"
        else:
            return "normal"
    
    def _update_menu_icon(self, snapshot):
        """
        切换菜单栏图标。
        逻辑：仅在 'normal' 状态下启用 Template 模式（黑白自适应），
        其余状态（low, charging, full）强制使用原始彩色渲染。
        """
        if not self._icon_enabled:
            return  # emoji 模式，不切换
        
        state = self._select_menu_icon(snapshot)
        path = _menu_icon_path(state)
        if path is None:
            return
            
        try:
            # 1. 更新基础图标路径
            self.icon = path
            
            # 2. 获取底层的 NSButton 对象进行高级渲染控制
            if hasattr(self, '_app') and hasattr(self._app, 'nsstatusitem'):
                button = self._app.nsstatusitem.button()
                if button:
                    from AppKit import NSImage
                    
                    # 强制重新加载图片以绕过 AppKit 内部缓存
                    new_image = NSImage.alloc().initByReferencingFile_(path)
                    if new_image:
                        # 核心逻辑：只有 normal 状态使用模板以适配深/浅色模式
                        # low (红), charging (绿), full (金) 全部关闭模板
                        is_template = (state == 'normal')
                        new_image.setTemplate_(is_template)
                        
                        # 应用新生成的图像实例
                        button.setImage_(new_image)
                        button.setNeedsDisplay_(True)
        except Exception as e:
            # 静默处理异常，确保不影响主进程
            pass
           
    def _finish_refresh(
        self,
        snapshot,
        error,
    ):
        if snapshot is not None:
            self.latest_snapshot = snapshot
    
        if error is not None:
            rumps.notification(
                APP_NAME,
                "刷新失败",
                error,
            )
    
        self.refresh_started_at = None
    
        if self.refresh_lock.locked():
            self.refresh_lock.release()
    
        self.refresh_item.title = (
            "立即刷新"
        )
        self.refresh_item.set_callback(
            self.on_refresh
        )
        self._set_item_enabled(
            self.refresh_item,
            True,
        )
        self._render_menu()
        self._update_menu_icon(snapshot)
    
    def on_device_item(
        self,
        sender=None,
    ):
        """
        设备行只用于显示。
    
        保留有效回调是为了让 macOS 以正常白色文本渲染，
        点击设备行不会触发任何操作。
        """
        return None
    
    def on_refresh(
        self,
        sender=None,
    ):
        self.request_refresh()
    
    def on_timer(
        self,
        sender=None,
    ):
        self.request_refresh()
    
    def on_about(
        self,
        sender=None,
    ):
        # 核心修改：动态计算分钟数
        refresh_minutes = AUTO_REFRESH_SECONDS // 60
        
        rumps.alert(
            title=APP_NAME,
            message=(
                f"版本 {APP_VERSION}\n"
                f"{APP_COPYRIGHT}\n\n"
                "统一显示 macOS 外设电量。\n\n"
                "支持AirPods 分部件电量、"
                "标准 BLE Battery Service "
                "和 Logitech HID++。\n\n"
                f"自动刷新间隔：{refresh_minutes} 分钟。\n\n"  # 此处变为动态获取
                "https://github.com/l351i3/BatteryBar"
            ),
            ok="确定",
        )
    
    def on_quit(
        self,
        sender=None,
    ):
        rumps.quit_application()
    
    def run(self, **options):
        application = (
            NSApplication
            .sharedApplication()
        )
        application \
            .setActivationPolicy_(
                NSApplicationActivationPolicyAccessory
            )
    
        _ensure_login_item()
    
        self.timer.start()
    
        AppHelper.callAfter(
            self.request_refresh
        )
    
        super().run(**options)

def main():
    BatteryBarApp().run()

if __name__ == "__main__":
    main()