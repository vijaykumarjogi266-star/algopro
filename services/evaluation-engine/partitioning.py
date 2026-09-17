"""
Algo Lab — Stage 7 Temporal Partitioning & Chronological Guard Module
Enforces disjoint train, validation, and out-of-sample test split rules with zero overlap.
"""

from datetime import datetime, timedelta
from typing import List
from services.evaluation_engine.manifest import TemporalPartition, PartitionType, _parse_date


def create_disjoint_partitions(
    start_date: str,
    end_date: str,
    train_pct: float = 0.6,
    val_pct: float = 0.2,
    test_pct: float = 0.2,
) -> List[TemporalPartition]:
    """Creates disjoint train, validation, and test partitions across a date range."""
    s_dt = _parse_date(start_date)
    e_dt = _parse_date(end_date)

    if s_dt >= e_dt:
        raise ValueError(f"Invalid date range for partitioning: {start_date} >= {end_date}")

    total_pct = train_pct + val_pct + test_pct
    if abs(total_pct - 1.0) > 1e-4:
        raise ValueError(f"Partition percentages must sum to 1.0 (got {total_pct:.4f})")

    # If inputs are date-only strings (10 chars YYYY-MM-DD)
    is_date_only = len(str(start_date).strip()) == 10 and len(str(end_date).strip()) == 10

    if is_date_only:
        total_days = (e_dt.date() - s_dt.date()).days
        if total_days < 5:
            raise ValueError("Total date range is too short for 3-way partitioning.")

        train_days = max(1, int(total_days * train_pct))
        val_days = max(1, int(total_days * val_pct))

        train_end_d = s_dt.date() + timedelta(days=train_days - 1)
        val_start_d = train_end_d + timedelta(days=1)
        val_end_d = val_start_d + timedelta(days=val_days - 1)
        test_start_d = val_end_d + timedelta(days=1)
        test_end_d = e_dt.date()

        train_p = TemporalPartition(
            name="train",
            partition_type=PartitionType.TRAIN,
            start_date=s_dt.date().strftime("%Y-%m-%d"),
            end_date=train_end_d.strftime("%Y-%m-%d"),
        )
        val_p = TemporalPartition(
            name="validation",
            partition_type=PartitionType.VALIDATION,
            start_date=val_start_d.strftime("%Y-%m-%d"),
            end_date=val_end_d.strftime("%Y-%m-%d"),
        )
        test_p = TemporalPartition(
            name="final_test",
            partition_type=PartitionType.TEST,
            start_date=test_start_d.strftime("%Y-%m-%d"),
            end_date=test_end_d.strftime("%Y-%m-%d"),
        )
    else:
        total_seconds = (e_dt - s_dt).total_seconds()
        train_sec = total_seconds * train_pct
        val_sec = total_seconds * val_pct

        train_end = s_dt + timedelta(seconds=train_sec)
        val_start = train_end + timedelta(seconds=1)
        val_end = val_start + timedelta(seconds=val_sec)
        test_start = val_end + timedelta(seconds=1)
        test_end = e_dt

        fmt = "%Y-%m-%d %H:%M:%S"
        train_p = TemporalPartition(
            name="train",
            partition_type=PartitionType.TRAIN,
            start_date=s_dt.strftime(fmt),
            end_date=train_end.strftime(fmt),
        )
        val_p = TemporalPartition(
            name="validation",
            partition_type=PartitionType.VALIDATION,
            start_date=val_start.strftime(fmt),
            end_date=val_end.strftime(fmt),
        )
        test_p = TemporalPartition(
            name="final_test",
            partition_type=PartitionType.TEST,
            start_date=test_start.strftime(fmt),
            end_date=test_end.strftime(fmt),
        )

    partitions = [train_p, val_p, test_p]
    validate_partition_chronology(partitions)
    return partitions


def validate_partition_chronology(partitions: List[TemporalPartition]) -> None:
    """
    Validates that partitions are strictly chronological, disjoint, and correctly ordered.
    Enforces AT-13 through AT-17.
    """
    if not partitions:
        return

    type_order = {
        PartitionType.TRAIN: 1,
        PartitionType.VALIDATION: 2,
        PartitionType.TEST: 3,
        PartitionType.WALK_FORWARD: 2,
    }

    parsed = []
    for p in partitions:
        s = _parse_date(p.start_date)
        e = _parse_date(p.end_date)
        if s >= e:
            raise ValueError(f"Partition '{p.name}' has invalid bounds: {p.start_date} >= {p.end_date}")
        p_type = p.partition_type if isinstance(p.partition_type, PartitionType) else PartitionType(str(p.partition_type))
        parsed.append((p, p_type, s, e))

    for i in range(len(parsed)):
        p_curr, t_curr, s_curr, e_curr = parsed[i]
        for j in range(i + 1, len(parsed)):
            p_next, t_next, s_next, e_next = parsed[j]

            # Inverted type order check (e.g. TEST placed before TRAIN) (AT-17)
            if type_order.get(t_next, 0) < type_order.get(t_curr, 0):
                raise ValueError(
                    f"Chronologically inverted partitions: '{p_curr.name}' ({t_curr.value}) appears before '{p_next.name}' ({t_next.value})."
                )

            # Inverted timestamp order check (AT-17)
            if s_next < s_curr:
                raise ValueError(
                    f"Chronologically inverted partitions: '{p_next.name}' starts ({p_next.start_date}) before '{p_curr.name}' ({p_curr.start_date})."
                )

            # Overlap check (AT-14, AT-15, AT-16)
            if s_next <= e_curr:
                raise ValueError(
                    f"Partition overlap detected between '{p_curr.name}' (ends {p_curr.end_date}) and '{p_next.name}' (starts {p_next.start_date})."
                )
