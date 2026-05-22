from __future__ import annotations

import csv
from io import StringIO

from django.http import HttpResponse


def tabular_to_csv_response(*, filename: str, columns: list[str], rows: list[dict]) -> HttpResponse:
    sio = StringIO()
    writer = csv.writer(sio)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([row.get(col, "") for col in columns])

    resp = HttpResponse(sio.getvalue(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp

