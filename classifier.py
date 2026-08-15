#!/usr/bin/env python3

from dataclasses import dataclass
from typing import Optional

from models import (
    CATEGORY_CONTROLLER,
    CATEGORY_HEADPHONES,
    CATEGORY_KEYBOARD,
    CATEGORY_MICROPHONE,
    CATEGORY_MOUSE,
    CATEGORY_OTHER,
    CATEGORY_SPEAKER,
    CATEGORY_STYLUS,
    CATEGORY_TRACKPAD,
    VALID_CATEGORIES,
)


@dataclass(frozen=True)
class DeviceMetadata:
    name: str
    system_category: Optional[str] = None
    appearance: Optional[int] = None
    hid_usage_page: Optional[int] = None
    hid_usage: Optional[int] = None
    audio_input_channels: Optional[int] = None
    audio_output_channels: Optional[int] = None


@dataclass(frozen=True)
class Classification:
    category: str
    source: str


MODEL_OVERRIDES = (
    (
        "dji mic mini",
        CATEGORY_MICROPHONE,
    ),
)

NAME_RULES = (
    (
        CATEGORY_MICROPHONE,
        (
            "microphone",
            " mic ",
            "mic-",
            "mic_",
            "mic mini",
            "麦克风",
            "话筒",
        ),
    ),
    (
        CATEGORY_KEYBOARD,
        (
            "keyboard",
            "mx keys",
            "键盘",
        ),
    ),
    (
        CATEGORY_MOUSE,
        (
            "mouse",
            "mx master",
            "mx anywhere",
            "鼠标",
        ),
    ),
    (
        CATEGORY_TRACKPAD,
        (
            "trackpad",
            "touchpad",
            "触控板",
        ),
    ),
    (
        CATEGORY_STYLUS,
        (
            "stylus",
            "pencil",
            "触控笔",
            "手写笔",
        ),
    ),
    (
        CATEGORY_CONTROLLER,
        (
            "controller",
            "gamepad",
            "dualshock",
            "dualsense",
            "xbox wireless",
            "手柄",
        ),
    ),
    (
        CATEGORY_HEADPHONES,
        (
            "headphone",
            "headset",
            "earphone",
            "earbuds",
            "airpods",
            "耳机",
        ),
    ),
    (
        CATEGORY_SPEAKER,
        (
            "speaker",
            "音箱",
            "扬声器",
        ),
    ),
)

SYSTEM_CATEGORY_MAP = {
    "keyboard": CATEGORY_KEYBOARD,
    "mouse": CATEGORY_MOUSE,
    "microphone": CATEGORY_MICROPHONE,
    "headphone": CATEGORY_HEADPHONES,
    "headphones": CATEGORY_HEADPHONES,
    "headset": CATEGORY_HEADPHONES,
    "speaker": CATEGORY_SPEAKER,
    "trackpad": CATEGORY_TRACKPAD,
    "touchpad": CATEGORY_TRACKPAD,
    "stylus": CATEGORY_STYLUS,
    "controller": CATEGORY_CONTROLLER,
    "gamepad": CATEGORY_CONTROLLER,
}

HID_USAGE_MAP = {
    (0x01, 0x02): CATEGORY_MOUSE,
    (0x01, 0x05): CATEGORY_CONTROLLER,
    (0x01, 0x06): CATEGORY_KEYBOARD,
    (0x01, 0x07): CATEGORY_KEYBOARD,
    (0x0D, 0x02): CATEGORY_STYLUS,
    (0x0D, 0x05): CATEGORY_TRACKPAD,
}

BLE_APPEARANCE_MAP = {
    0x03C0: CATEGORY_KEYBOARD,
    0x03C1: CATEGORY_MOUSE,
    0x03C2: CATEGORY_MOUSE,
    0x03C3: CATEGORY_KEYBOARD,
    0x03C4: CATEGORY_KEYBOARD,
    0x03C5: CATEGORY_KEYBOARD,
    0x03C6: CATEGORY_MOUSE,
}


def _normalize_text(value):
    if value is None:
        return ""

    return " ".join(
        str(value).strip().lower().split()
    )


def _padded_name(value):
    normalized = _normalize_text(value)

    if not normalized:
        return ""
    
    return f" {normalized} "


def _non_negative_count(value):
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= 0
    )


def _classify_by_name(normalized_name):
    padded_name = _padded_name(
        normalized_name
    )

    for category, fragments in NAME_RULES:
        for fragment in fragments:
            normalized_fragment = (
                fragment.lower()
            )
    
            if (
                normalized_fragment.startswith(" ")
                or normalized_fragment.endswith(" ")
            ):
                matched = (
                    normalized_fragment
                    in padded_name
                )
            else:
                matched = (
                    normalized_fragment
                    in normalized_name
                )
    
            if matched:
                return Classification(
                    category=category,
                    source="name_rule",
                )
    
    return None


def classify_device(metadata):
    if not isinstance(
        metadata,
        DeviceMetadata,
    ):
        raise TypeError(
            "metadata must be DeviceMetadata"
        )

    normalized_name = _normalize_text(
        metadata.name
    )
    
    # 型号修正规则拥有最高优先级。
    # DJI Mic Mini 即使被 macOS 标记成耳机，
    # 也必须识别为麦克风。
    for fragment, category in MODEL_OVERRIDES:
        if fragment in normalized_name:
            return Classification(
                category=category,
                source="model_override",
            )
    
    input_channels = (
        metadata.audio_input_channels
    )
    output_channels = (
        metadata.audio_output_channels
    )
    
    input_known = _non_negative_count(
        input_channels
    )
    output_known = _non_negative_count(
        output_channels
    )
    
    if input_known and output_known:
        if (
            input_channels > 0
            and output_channels == 0
        ):
            return Classification(
                category=CATEGORY_MICROPHONE,
                source="audio_capability",
            )
    
        if (
            output_channels > 0
            and input_channels == 0
        ):
            name_result = _classify_by_name(
                normalized_name
            )
    
            if (
                name_result is not None
                and name_result.category
                in {
                    CATEGORY_HEADPHONES,
                    CATEGORY_SPEAKER,
                }
            ):
                return name_result
    
            return Classification(
                category=CATEGORY_HEADPHONES,
                source="audio_capability",
            )
    
    hid_category = HID_USAGE_MAP.get(
        (
            metadata.hid_usage_page,
            metadata.hid_usage,
        )
    )
    
    if hid_category is not None:
        return Classification(
            category=hid_category,
            source="hid_usage",
        )
    
    appearance_category = (
        BLE_APPEARANCE_MAP.get(
            metadata.appearance
        )
    )
    
    if appearance_category is not None:
        return Classification(
            category=appearance_category,
            source="ble_appearance",
        )
    
    system_category = SYSTEM_CATEGORY_MAP.get(
        _normalize_text(
            metadata.system_category
        )
    )
    
    if system_category is not None:
        return Classification(
            category=system_category,
            source="system_category",
        )
    
    name_result = _classify_by_name(
        normalized_name
    )
    
    if name_result is not None:
        return name_result
    
    return Classification(
        category=CATEGORY_OTHER,
        source="fallback",
    )


def category_label(category):
    labels = {
        CATEGORY_KEYBOARD: "键盘",
        CATEGORY_MOUSE: "鼠标",
        CATEGORY_MICROPHONE: "麦克风",
        CATEGORY_HEADPHONES: "耳机",
        CATEGORY_SPEAKER: "音箱",
        CATEGORY_TRACKPAD: "触控板",
        CATEGORY_STYLUS: "触控笔",
        CATEGORY_CONTROLLER: "游戏控制器",
        CATEGORY_OTHER: "其他设备",
    }

    if category not in VALID_CATEGORIES:
        raise ValueError(
            f"unsupported category: {category}"
        )
    
    return labels[category]


def category_sort_key(category):
    order = {
        CATEGORY_KEYBOARD: 0,
        CATEGORY_MOUSE: 1,
        CATEGORY_MICROPHONE: 2,
        CATEGORY_HEADPHONES: 3,
        CATEGORY_SPEAKER: 4,
        CATEGORY_TRACKPAD: 5,
        CATEGORY_STYLUS: 6,
        CATEGORY_CONTROLLER: 7,
        CATEGORY_OTHER: 8,
    }

    if category not in order:
        raise ValueError(
            f"unsupported category: {category}"
        )
    
    return order[category]