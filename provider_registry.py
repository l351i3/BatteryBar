#!/usr/bin/env python3

from aggregator import (
    BatteryAggregator,
    ProviderSpec,
)
from bluetooth_provider import (
    discover_batteries as discover_bluetooth,
)
from hidpp_provider import (
    discover_batteries as discover_hidpp,
)
from system_provider import (
    discover_batteries as discover_system,
)


def create_default_aggregator(
    cache_expiry_seconds=3600.0,
):
    providers = (
        ProviderSpec(
            name="system",
            discover=discover_system,
        ),
        ProviderSpec(
            name="ble_standard",
            discover=discover_bluetooth,
        ),
        ProviderSpec(
            name="hidpp",
            discover=discover_hidpp,
        ),
    )

    return BatteryAggregator(
        providers=providers,
        cache_expiry_seconds=(
            cache_expiry_seconds
        ),
    )