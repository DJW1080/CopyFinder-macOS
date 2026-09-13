"""Compatible CSV and JSON reports built from current review state."""

import csv
import io
import json
from datetime import datetime, timezone

NANOSECONDS_PER_SECOND = 1_000_000_000
CSV_FIELDS = ('GroupId', 'Role', 'Selected', 'Size', 'Hash', 'ImageWidth',
              'ImageHeight', 'Modified', 'NetworkPath', 'DeleteStatus', 'Path')


def report_rows(groups, network_classifier):
    for group in groups:
        for row in group.rows:
            record = row.record
            yield {
                'GroupId': group.group_id,
                'Role': 'Keep' if row.is_kept else 'Duplicate',
                'IsSelected': row.selected,
                'Size': record.size,
                'Hash': record.digest,
                'ImageWidth': record.width,
                'ImageHeight': record.height,
                'LastWriteTime': datetime.fromtimestamp(
                    record.modified_ns / NANOSECONDS_PER_SECOND, timezone.utc
                ).astimezone().isoformat(),
                'Path': record.path,
                'IsNetworkPath': network_classifier(record.path),
                'DeleteStatus': 'Kept' if row.is_kept else 'Selected' if row.selected else 'Not selected',
            }


def build_json(groups, network_classifier):
    return json.dumps(list(report_rows(groups, network_classifier)), indent=2, ensure_ascii=True) + '\n'


def build_csv(groups, network_classifier):
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for row in report_rows(groups, network_classifier):
        row['Selected'] = row.pop('IsSelected')
        row['Modified'] = row.pop('LastWriteTime')
        row['NetworkPath'] = row.pop('IsNetworkPath')
        writer.writerow(row)
    return output.getvalue()
