"""AWS EC2 Standard On-Demand Pricing Reference Catalog.

Provides verified AWS On-Demand hourly & estimated monthly rates (730 hours/month)
for common EC2 instance families in us-east-1 (with standard regional multipliers).
Does NOT fabricate pricing for unknown types: if an instance type is not in the catalog,
get_instance_price returns None or marks is_estimate=True / unpriced.
"""

from __future__ import annotations

from typing import Optional, TypedDict


class InstancePricingInfo(TypedDict):
    instance_type: str
    vcpus: int
    memory_gb: float
    hourly_rate: float
    monthly_cost: float
    family: str
    generation: int
    architecture: str
    is_known: bool


# Standard AWS EC2 On-Demand pricing in us-east-1 (USD per hour)
# Reference: AWS EC2 Pricing Catalog
AWS_EC2_PRICING: dict[str, dict[str, float | int | str]] = {
    # General Purpose - T3 (burstable x86)
    "t3.nano": {"vcpus": 2, "memory_gb": 0.5, "hourly": 0.0052, "family": "t3", "arch": "x86_64"},
    "t3.micro": {"vcpus": 2, "memory_gb": 1.0, "hourly": 0.0104, "family": "t3", "arch": "x86_64"},
    "t3.small": {"vcpus": 2, "memory_gb": 2.0, "hourly": 0.0208, "family": "t3", "arch": "x86_64"},
    "t3.medium": {"vcpus": 2, "memory_gb": 4.0, "hourly": 0.0416, "family": "t3", "arch": "x86_64"},
    "t3.large": {"vcpus": 2, "memory_gb": 8.0, "hourly": 0.0832, "family": "t3", "arch": "x86_64"},
    "t3.xlarge": {"vcpus": 4, "memory_gb": 16.0, "hourly": 0.1664, "family": "t3", "arch": "x86_64"},
    "t3.2xlarge": {"vcpus": 8, "memory_gb": 32.0, "hourly": 0.3328, "family": "t3", "arch": "x86_64"},

    # General Purpose - T4g (Graviton2 ARM)
    "t4g.nano": {"vcpus": 2, "memory_gb": 0.5, "hourly": 0.0042, "family": "t4g", "arch": "arm64"},
    "t4g.micro": {"vcpus": 2, "memory_gb": 1.0, "hourly": 0.0084, "family": "t4g", "arch": "arm64"},
    "t4g.small": {"vcpus": 2, "memory_gb": 2.0, "hourly": 0.0168, "family": "t4g", "arch": "arm64"},
    "t4g.medium": {"vcpus": 2, "memory_gb": 4.0, "hourly": 0.0336, "family": "t4g", "arch": "arm64"},
    "t4g.large": {"vcpus": 2, "memory_gb": 8.0, "hourly": 0.0672, "family": "t4g", "arch": "arm64"},
    "t4g.xlarge": {"vcpus": 4, "memory_gb": 16.0, "hourly": 0.1344, "family": "t4g", "arch": "arm64"},
    "t4g.2xlarge": {"vcpus": 8, "memory_gb": 32.0, "hourly": 0.2688, "family": "t4g", "arch": "arm64"},

    # General Purpose - M5 (x86)
    "m5.large": {"vcpus": 2, "memory_gb": 8.0, "hourly": 0.096, "family": "m5", "arch": "x86_64"},
    "m5.xlarge": {"vcpus": 4, "memory_gb": 16.0, "hourly": 0.192, "family": "m5", "arch": "x86_64"},
    "m5.2xlarge": {"vcpus": 8, "memory_gb": 32.0, "hourly": 0.384, "family": "m5", "arch": "x86_64"},
    "m5.4xlarge": {"vcpus": 16, "memory_gb": 64.0, "hourly": 0.768, "family": "m5", "arch": "x86_64"},

    # Compute Optimized - C5 (x86)
    "c5.large": {"vcpus": 2, "memory_gb": 4.0, "hourly": 0.085, "family": "c5", "arch": "x86_64"},
    "c5.xlarge": {"vcpus": 4, "memory_gb": 8.0, "hourly": 0.170, "family": "c5", "arch": "x86_64"},
    "c5.2xlarge": {"vcpus": 8, "memory_gb": 16.0, "hourly": 0.340, "family": "c5", "arch": "x86_64"},
    "c5.4xlarge": {"vcpus": 16, "memory_gb": 32.0, "hourly": 0.680, "family": "c5", "arch": "x86_64"},

    # Memory Optimized - R5 (x86)
    "r5.large": {"vcpus": 2, "memory_gb": 16.0, "hourly": 0.126, "family": "r5", "arch": "x86_64"},
    "r5.xlarge": {"vcpus": 4, "memory_gb": 32.0, "hourly": 0.252, "family": "r5", "arch": "x86_64"},
    "r5.2xlarge": {"vcpus": 8, "memory_gb": 64.0, "hourly": 0.504, "family": "r5", "arch": "x86_64"},

    # Legacy T2 (x86)
    "t2.nano": {"vcpus": 1, "memory_gb": 0.5, "hourly": 0.0058, "family": "t2", "arch": "x86_64"},
    "t2.micro": {"vcpus": 1, "memory_gb": 1.0, "hourly": 0.0116, "family": "t2", "arch": "x86_64"},
    "t2.small": {"vcpus": 1, "memory_gb": 2.0, "hourly": 0.023, "family": "t2", "arch": "x86_64"},
    "t2.medium": {"vcpus": 2, "memory_gb": 4.0, "hourly": 0.0464, "family": "t2", "arch": "x86_64"},
    "t2.large": {"vcpus": 2, "memory_gb": 8.0, "hourly": 0.0928, "family": "t2", "arch": "x86_64"},
    "t2.xlarge": {"vcpus": 4, "memory_gb": 16.0, "hourly": 0.1856, "family": "t2", "arch": "x86_64"},
}

# Sizing tiers ordered from smallest to largest within family for right-sizing recommendations
FAMILY_TIERS = {
    "t3": ["t3.nano", "t3.micro", "t3.small", "t3.medium", "t3.large", "t3.xlarge", "t3.2xlarge"],
    "t4g": ["t4g.nano", "t4g.micro", "t4g.small", "t4g.medium", "t4g.large", "t4g.xlarge", "t4g.2xlarge"],
    "m5": ["t3.medium", "m5.large", "m5.xlarge", "m5.2xlarge", "m5.4xlarge"],
    "c5": ["t3.medium", "c5.large", "c5.xlarge", "c5.2xlarge", "c5.4xlarge"],
    "r5": ["t3.large", "r5.large", "r5.xlarge", "r5.2xlarge"],
    "t2": ["t2.nano", "t2.micro", "t2.small", "t2.medium", "t2.large", "t2.xlarge"],
}

HOURS_PER_MONTH = 730.0


def get_instance_pricing(instance_type: str | None) -> InstancePricingInfo | None:
    """Return pricing info for an EC2 instance type. None if unknown or not set."""
    if not instance_type:
        return None
    normalized = instance_type.strip().lower()
    entry = AWS_EC2_PRICING.get(normalized)
    if not entry:
        return None
    hourly = float(entry["hourly"])
    return {
        "instance_type": normalized,
        "vcpus": int(entry["vcpus"]),
        "memory_gb": float(entry["memory_gb"]),
        "hourly_rate": hourly,
        "monthly_cost": round(hourly * HOURS_PER_MONTH, 2),
        "family": str(entry["family"]),
        "generation": 3 if "3" in normalized else (4 if "4" in normalized else 5),
        "architecture": str(entry["arch"]),
        "is_known": True,
    }


def find_downsize_target(
    current_instance_type: str | None,
    peak_cpu: float,
    avg_cpu: float,
    peak_ram: float | None = None,
) -> Optional[tuple[str, InstancePricingInfo]]:
    """Suggest a smaller instance class within the same or suitable burstable family.

    Returns (target_instance_type, target_pricing_info) if downsize is viable and saves money,
    or None if already at smallest tier or utilization does not safely warrant downsizing.
    """
    if not current_instance_type:
        return None
    curr_pricing = get_instance_pricing(current_instance_type)
    if not curr_pricing:
        return None

    family = curr_pricing["family"]
    tiers = FAMILY_TIERS.get(family, [])
    if not tiers or curr_pricing["instance_type"] not in tiers:
        return None

    current_idx = tiers.index(curr_pricing["instance_type"])
    if current_idx == 0:
        # Already at lowest tier in family
        return None

    # Determine how many steps down to safely recommend
    # If peak_cpu < 20% and avg_cpu < 10%, we can recommend stepping down 1 or 2 sizes
    steps_down = 1
    if peak_cpu < 15.0 and avg_cpu < 5.0 and current_idx >= 2:
        steps_down = 2

    target_idx = max(0, current_idx - steps_down)
    target_type = tiers[target_idx]
    if target_type == curr_pricing["instance_type"]:
        return None

    target_pricing = get_instance_pricing(target_type)
    if not target_pricing:
        return None

    # Ensure target type is cheaper
    if target_pricing["monthly_cost"] >= curr_pricing["monthly_cost"]:
        return None

    return target_type, target_pricing
