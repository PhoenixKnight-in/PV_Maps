"""Offline preparation CLI. `docker/pipeline.Dockerfile` runs this module.

ARCHITECTURE.md 9.1:

    "Offline preparation is a separate command or profile."
    "The pipeline is never started during a judging demo."

    docker compose --profile pipeline run --rm pipeline seed
    docker compose --profile pipeline run --rm pipeline yield --all
    docker compose --profile pipeline run --rm pipeline iou --truth truth.geojson \\
                                                          --predicted pred.geojson

Every heavy import is inside the command that needs it, and the split that buys
is real rather than tidy:

    seed          rule packs and pilot roofs        psycopg           small image
    purge-runs    expired sizing runs, NFR-1        psycopg           small image
    roofs-import  hand-corrected roof GeoJSON       shapely, pyproj   pipeline
    yield         pvlib physics                     pvlib, pandas     pipeline
    iou           segmentation accuracy             shapely           pipeline

The first two are what somebody runs at 2am after recreating the demo database,
so `docker/seed.Dockerfile` runs them from an image holding psycopg and typer and
nothing else — no CUDA, no torch, no multi-gigabyte pull. The rest are roof
preparation and belong to `docker/pipeline.Dockerfile`, which ARCHITECTURE.md 9.1
says is never started during a demo.

Ask the small image for one of the latter and it says so in a sentence naming the
group to install, rather than raising ModuleNotFoundError four frames deep.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    # An operator running this at 2am wants a sentence, not a rich traceback.
    pretty_exceptions_enable=False,
    help="PV Maps offline preparation. Never run during a demo (ARCHITECTURE.md 9.1).",
)

VELLORE = (12.9202, 79.1325)


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        typer.secho(
            "DATABASE_URL is not set. The pipeline writes with the SYNCHRONOUS driver:\n"
            "  postgresql+psycopg://user:pass@host:5432/pvmaps",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)
    # docker-compose.yml hands the pipeline a SQLAlchemy-style URL; psycopg wants
    # a plain libpq one. Accept either rather than making the operator care.
    return url.replace("postgresql+psycopg://", "postgresql://").replace(
        "postgresql+asyncpg://", "postgresql://"
    )


def _require(module: str, group: str, command: str) -> None:
    """Fail with a sentence, not a traceback, when the small image is asked for a
    command that needs the big one.

    `docker/seed.Dockerfile` installs the `seed` group only -- psycopg and typer.
    Ask that image for `yield` and the honest answer is "this needs pvlib and it
    is not here", said in one line naming the fix. The alternative is a
    ModuleNotFoundError raised four frames into a physics module, which sends
    whoever is standing at the terminal at 2am looking for a broken install.
    """
    from importlib.util import find_spec

    if find_spec(module) is None:
        typer.secho(
            f"`{command}` needs {module}, from the `{group}` dependency group.\n"
            f"  uv sync --group {group}\n"
            f"or run it in the image that has it:\n"
            f"  docker compose --profile pipeline run --rm pipeline {command} --help",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)


def _connect() -> Any:
    """Resolve the URL BEFORE importing the driver.

    The other order means a missing DATABASE_URL is reported as
    ModuleNotFoundError on a machine without psycopg, which sends the operator
    looking for the wrong problem entirely.
    """
    url = _database_url()
    try:
        import psycopg
    except ImportError:
        typer.secho(
            "psycopg is not installed. The pipeline group provides it:\n"
            "  uv sync --group pipeline\n"
            "or run this inside the pipeline image:\n"
            "  docker compose --profile pipeline run --rm pipeline seed",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2) from None

    return psycopg.connect(url)


@app.command()
def seed(
    rules_only: Annotated[bool, typer.Option(help="Mirror the rule packs and stop.")] = False,
) -> None:
    """Load rule packs and hand-corrected pilot roofs. Idempotent."""
    from pvmaps.pipeline.seed import seed_pilot, seed_rule_packs

    with _connect() as conn:
        counts = seed_rule_packs(conn)
        if not rules_only:
            counts.update(seed_pilot(conn))

    for table, n in counts.items():
        typer.echo(f"  {table:24} {n}")

    from pvmaps.sizing.assumptions import load_assumptions, load_subsidy
    from pvmaps.tariff.schedule import load_schedule

    unverified = [
        pack.version
        for pack in (
            load_schedule("tn-domestic-2025-07-01"),
            load_assumptions(),
            load_subsidy(),
        )
        if not pack.is_verified
    ]
    if unverified:
        typer.secho(
            "\nUNVERIFIED RULE PACKS: " + ", ".join(unverified) + "\n"
            "Results will be labelled provisional and no rupee figure should be "
            "quoted to a household until these are checked against primary sources.",
            fg=typer.colors.YELLOW,
        )


@app.command("yield")
def yield_command(
    building_id: Annotated[str | None, typer.Option(help="One building. Omit for all.")] = None,
    lat: Annotated[float, typer.Option(help="Latitude for the fallback site.")] = VELLORE[0],
    lon: Annotated[float, typer.Option(help="Longitude for the fallback site.")] = VELLORE[1],
    tilt: Annotated[float | None, typer.Option(help="Degrees. Omit to scan for the best.")] = None,
    azimuth: Annotated[float, typer.Option(help="Degrees from north. 180 is due south.")] = 180.0,
    dry_run: Annotated[bool, typer.Option(help="Compute and print; write nothing.")] = False,
) -> None:
    """FR-2 — pvlib yield for pilot roofs, written to `roof_analyses`.

    Each building is sited at its own centroid, so a pilot area spanning a few
    kilometres still gets one solar geometry per roof rather than one for the
    whole ward.
    """
    _require("pvlib", "pipeline", "yield")

    from pvmaps.pipeline.yield_physics import annual_yield, as_roof_analysis_row
    from pvmaps.sizing.assumptions import load_assumptions

    assumptions = load_assumptions()

    targets: list[tuple[str, float, float]]
    if dry_run and building_id is None:
        targets = [("(dry-run)", lat, lon)]
    else:
        with _connect() as conn, conn.cursor() as cur:
            sql = (
                "SELECT id, ST_Y(ST_Centroid(geom)), ST_X(ST_Centroid(geom)) FROM buildings"
            )
            if building_id:
                cur.execute(f"{sql} WHERE id = %s", (building_id,))
            else:
                cur.execute(f"{sql} ORDER BY id")
            targets = [(r[0], float(r[1]), float(r[2])) for r in cur.fetchall()]

    if not targets:
        typer.secho("No buildings found. Run `seed` first.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    for bid, blat, blon in targets:
        result = annual_yield(blat, blon, assumptions, tilt=tilt, azimuth=azimuth)
        agrees = result.agrees_with_published_band(assumptions)
        typer.echo(
            f"  {bid:28} {result.conservative:7.1f} - {result.expected:7.1f} kWh/kWp/yr  "
            f"tilt {result.tilt_deg:>4.1f} deg  {result.irradiance_source}"
        )
        if not agrees:
            # PRD 10 (acceptance criteria): output outside the published band is evidence the physics
            # is wrong, not a reason to widen the band.
            typer.secho(
                f"    OUTSIDE the published band {assumptions.specific_yield}. "
                f"Check the physics before widening anything.",
                fg=typer.colors.RED,
            )
        if dry_run:
            continue

        row = as_roof_analysis_row(result, bid)
        from pvmaps.pipeline.seed import write_roof_analysis

        with _connect() as conn:
            write_roof_analysis(conn, row)


@app.command()
def iou(
    predicted: Annotated[Path, typer.Option(help="GeoJSON of predicted roof polygons.")],
    truth: Annotated[Path, typer.Option(help="GeoJSON of hand-drawn ground truth.")],
    out: Annotated[Path | None, typer.Option(help="Write the report as JSON.")] = None,
) -> None:
    """PRD 10 — segmentation IoU on held-out roofs. Reports the actual number.

    Features are paired by their `id` property, so a roof the model missed scores
    zero instead of vanishing from the denominator.
    """
    _require("shapely", "pipeline", "iou")

    from shapely.geometry import shape

    from pvmaps.pipeline.iou import evaluate

    def load(path: Path) -> dict[str, Any]:
        data = json.loads(path.read_text(encoding="utf-8"))
        features = data["features"] if data.get("type") == "FeatureCollection" else data
        return {
            str(f.get("properties", {}).get("id", i)): shape(f["geometry"])
            for i, f in enumerate(features)
        }

    pred, true = load(predicted), load(truth)
    from shapely.geometry import Polygon

    pairs = [(pred.get(key, Polygon()), geom) for key, geom in true.items()]
    report = evaluate(pairs)

    typer.echo(json.dumps(report.to_json(), indent=2))
    if out:
        out.write_text(json.dumps(report.to_json(), indent=2), encoding="utf-8")

    colour = typer.colors.GREEN if report.meets_criterion else typer.colors.YELLOW
    typer.secho(f"\n{report.verdict}", fg=colour)
    if not report.meets_criterion:
        # Non-zero exit so CI cannot go green on an unmet acceptance criterion,
        # but the number is printed either way.
        raise typer.Exit(code=1)


@app.command("roofs-import")
def roofs_import(
    footprints: Annotated[Path, typer.Option(help="GeoJSON of hand-corrected roof outlines.")],
    obstructions: Annotated[
        Path | None, typer.Option(help="GeoJSON of marked obstructions, keyed by building id.")
    ] = None,
    dry_run: Annotated[bool, typer.Option(help="Report the areas and write nothing.")] = False,
) -> None:
    """Grow the pilot area from hand-corrected roof GeoJSON — build order item 8.

    Areas are recomputed here in UTM 44N rather than read from the file, and the
    usable fraction of every roof is printed, because that fraction is the number
    a judge is most likely to challenge and the one most easily got wrong.

        pipeline roofs-import --footprints /data/ward-2.geojson \\
                              --obstructions /data/ward-2-obstructions.geojson
    """
    _require("shapely", "pipeline", "roofs-import")

    from pvmaps.pipeline.ingest import roofs_from_geojson
    from pvmaps.pipeline.seed import seed_pilot

    marks = None if obstructions is None else json.loads(obstructions.read_text(encoding="utf-8"))
    roofs = roofs_from_geojson(json.loads(footprints.read_text(encoding="utf-8")), marks)
    if not roofs:
        typer.secho(f"{footprints} holds no features.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    for roof in roofs:
        fraction = roof.usable_area_m2 / roof.roof_area_m2 if roof.roof_area_m2 else 0.0
        marked = len((roof.obstruction_geojson or {}).get("features", []))
        line = (
            f"  {roof.id:28} {roof.roof_area_m2:9.1f} m2 roof  "
            f"{roof.usable_area_m2:9.1f} m2 usable  ({fraction:.0%})  {marked} marked"
        )
        # A roof that keeps almost all of its footprint has usually had its
        # obstructions forgotten; one that keeps almost none usually has a bad
        # outline. Neither is refused — both are real roofs — but neither
        # should scroll past unremarked.
        if fraction > 0.9 or fraction < 0.25:
            typer.secho(line, fg=typer.colors.YELLOW)
        else:
            typer.echo(line)

    if dry_run:
        typer.echo("\ndry run: nothing written")
        return

    with _connect() as conn:
        counts = seed_pilot(conn, roofs)
    for table, n in counts.items():
        typer.echo(f"  {table:24} {n}")
    typer.secho(
        "\nRun `yield` next: these roofs have no roof_analyses row yet, so the API "
        "sizes them from the regional band and says so.",
        fg=typer.colors.YELLOW,
    )


@app.command("purge-runs")
def purge_runs() -> None:
    """Delete expired sizing runs — ARCHITECTURE.md 8, NFR-1.

    The rows hold no consumer number, name or address, but they do hold a
    household's monthly consumption, and `expires_at` is only a promise until
    something reads it. Safe to run on a schedule; safe to run during a demo.
    """
    from pvmaps.pipeline.seed import purge_expired_runs

    with _connect() as conn:
        deleted = purge_expired_runs(conn)
    typer.echo(f"  sizing_runs deleted      {deleted}")


@app.command("demo-fallback")
def demo_fallback() -> None:
    """Regenerate the browser's offline demo bundle (ARCHITECTURE.md 9.3)."""
    scripts = Path(__file__).resolve().parents[3] / "scripts"
    sys.path.insert(0, str(scripts))
    import build_demo_fallback

    build_demo_fallback.main()


if __name__ == "__main__":
    app()
