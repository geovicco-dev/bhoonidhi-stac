"""The STAC API server: stac-fastapi-pgstac with scene counts added.

Run it with uvicorn:

    uvicorn bhoonidhi_stac.api.app:create_app --factory --host 0.0.0.0 --port 8080

Every stac-fastapi-pgstac setting applies (PGHOST and the other PG* variables,
ENABLED_EXTENSIONS, ...). The counts are the extension named ``aggregation``:
like every other extension, they are on when ENABLED_EXTENSIONS is unset and
otherwise only when it lists them.
"""

from __future__ import annotations

from fastapi import FastAPI
from stac_fastapi.extensions.aggregation import (
    AggregationConformanceClasses,
    AggregationExtension,
)
from stac_fastapi.pgstac.app import instantiate_api
from stac_fastapi.pgstac.models.extensions import Extensions

from bhoonidhi_stac.api.aggregation import AggregateGet, AggregatePost, SceneCountClient


def create_app() -> FastAPI:
    """Build the API with the Aggregation extension on top of the stock one."""
    counts = AggregationExtension(
        client=SceneCountClient(),
        conformance_classes=[
            AggregationConformanceClasses.AGGREGATION,
            # /aggregate takes the same CQL2 filter as /search.
            f"{AggregationConformanceClasses.AGGREGATION}#filter",
        ],
    )
    # Request models with the search filter and the period added; the
    # extension keeps its own class so the landing page links to it.
    counts.GET = AggregateGet
    counts.POST = AggregatePost
    return instantiate_api(extensions=Extensions(extra_map={"aggregation": counts})).app
