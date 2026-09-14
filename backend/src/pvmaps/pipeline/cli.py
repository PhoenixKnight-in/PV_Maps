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


def _roof_targets(pilot: bool, building_id: str | None) -> list[tuple[str, float, float]]:
    """`(id, lat, lon)` per roof, from `PILOT_ROOFS` or from the database.

    Both `yield` and `segment` site a roof at its own centroid, and they have to
    agree about where that is: a yield computed for one point and a mask cut
    around another describe different roofs while looking like one result.
    """
    if pilot:
        from pvmaps.pipeline.seed import PILOT_ROOFS

        return [
            (r.building_id, r.lat, r.lon)
            for r in PILOT_ROOFS
            if building_id is None or r.building_id == building_id
        ]

    with _connect() as conn, conn.cursor() as cur:
        sql = "SELECT id, ST_Y(ST_Centroid(geom)), ST_X(ST_Centroid(geom)) FROM buildings"
        if building_id:
            cur.execute(f"{sql} WHERE id = %s", (building_id,))
        else:
            cur.execute(f"{sql} ORDER BY id")
        return [(r[0], float(r[1]), float(r[2])) for r in cur.fetchall()]


@app.command("yield")
def yield_command(
    building_id: Annotated[str | None, typer.Option(help="One building. Omit for all.")] = None,
    pilot: Annotated[
        bool, typer.Option(help="Take the roofs from PILOT_ROOFS instead of the database.")
    ] = False,
    lat: Annotated[float, typer.Option(help="Latitude for the fallback site.")] = VELLORE[0],
    lon: Annotated[float, typer.Option(help="Longitude for the fallback site.")] = VELLORE[1],
    tilt: Annotated[float | None, typer.Option(help="Degrees. Omit to scan for the best.")] = None,
    azimuth: Annotated[float, typer.Option(help="Degrees from north. 180 is due south.")] = 180.0,
    dry_run: Annotated[bool, typer.Option(help="Print; write no database row.")] = False,
    out: Annotated[
        Path | None, typer.Option(help="Also write the rows as JSON, for `seed` to load.")
    ] = None,
) -> None:
    """FR-2 — pvlib yield for pilot roofs, written to `roof_analyses`.

    Each building is sited at its own centroid, so a pilot area spanning a few
    kilometres still gets one solar geometry per roof rather than one for the
    whole ward.

    `--pilot` reads the centroids from `pipeline.seed.PILOT_ROOFS` — the same
    tuple the seeder writes — so the physics can be run on a machine that has a
    GPU image but no database, which is the usual order in which those two
    appear. Combined with `--out` it regenerates the committed fixture:

        pipeline yield --pilot --dry-run --out src/pvmaps/pipeline/analyses/pilot_roof_analyses.json
    """
    _require("pvlib", "pipeline", "yield")

    from pvmaps.pipeline.yield_physics import annual_yield, as_roof_analysis_row
    from pvmaps.sizing.assumptions import load_assumptions

    assumptions = load_assumptions()

    targets: list[tuple[str, float, float]]
    if not pilot and dry_run and building_id is None:
        targets = [("(dry-run)", lat, lon)]
    else:
        targets = _roof_targets(pilot, building_id)

    if not targets:
        typer.secho("No buildings found. Run `seed` first.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    rows: list[dict[str, Any]] = []
    for bid, blat, blon in targets:
        result = annual_yield(blat, blon, assumptions, tilt=tilt, azimuth=azimuth)
        agrees = result.agrees_with_published_band(assumptions)
        typer.echo(
            f"  {bid:28} {result.conservative:7.1f} - {result.expected:7.1f} kWh/kWp/yr  "
            f"tilt {result.tilt_deg:>4.1f} deg  {result.irradiance_source}"
        )
        if not agrees:
            # PRD 10 (acceptance criteria): output outside the published band is
            # evidence the physics is wrong, not a reason to widen the band.
            typer.secho(
                f"    OUTSIDE the published band {assumptions.specific_yield}. "
                f"Check the physics before widening anything.",
                fg=typer.colors.RED,
            )
        rows.append(as_roof_analysis_row(result, bid))

    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
        typer.echo(f"\nwrote {len(rows)} rows to {out}")

    if dry_run:
        return

    # One connection for the batch. Reopening per roof was harmless at five and
    # is not the shape to grow a ward into.
    from pvmaps.pipeline.seed import write_roof_analysis

    with _connect() as conn:
        for row in rows:
            write_roof_analysis(conn, row)


@app.command()
def segment(
    building_id: Annotated[str | None, typer.Option(help="One building. Omit for all.")] = None,
    pilot: Annotated[
        bool, typer.Option(help="Take the roofs from PILOT_ROOFS instead of the database.")
    ] = False,
    checkpoint: Annotated[
        Path, typer.Option(help="SAM2 weights (.pt). See `fetch-checkpoint`.")
    ] = Path("/checkpoints/sam2.1_hiera_small.pt"),
    model_cfg: Annotated[
        str, typer.Option(help="SAM2 hydra config name, matched to the checkpoint.")
    ] = "configs/sam2.1/sam2.1_hiera_s.yaml",
    zoom: Annotated[int, typer.Option(help="Tile zoom. FR-1.1 wants 19-20.")] = 19,
    radius_tiles: Annotated[int, typer.Option(help="Tiles around centre; 1 gives 3x3.")] = 1,
    data_dir: Annotated[Path, typer.Option(help="Imagery cache root.")] = Path("/data"),
    out: Annotated[Path | None, typer.Option(help="Write predicted roofs as GeoJSON.")] = None,
    min_area_m2: Annotated[float, typer.Option(help="Ignore masks smaller than this.")] = 20.0,
) -> None:
    """FR-1.1 — SAM2 roof masks on the GPU. The only GPU-bound command here.

    This is the caller `roofs.propose_masks` never had. The chain is:

        imagery.mosaic      tiles around the centroid, EPSG:3857 + Affine
        roofs.propose_masks SAM2 automatic mask generation          <- GPU
        roofs.mask_to_polygons  raster mask -> vector, in 3857
        imagery.to_wgs84_polygons   -> 4326, the storage CRS

    PRD 9 is explicit that segmentation is precomputed and never run live on
    stage, so this writes a file; nothing in the request path can reach it.

    **Mask selection is a placeholder and says so.** FR-1.1 calls for a
    roof/not-roof classifier to rank SAM2's proposals. There isn't one, so this
    picks the smallest mask that contains the roof centroid and is larger than
    `--min-area-m2` — a geometric heuristic, not a classifier. It is good enough
    to produce candidate outlines for a person to correct, which is the workflow
    PRD 12 already prescribes, and it is NOT good enough to report an IoU against.
    """
    _require("torch", "pipeline", "segment")
    _require("rasterio", "pipeline", "segment")

    from shapely.geometry import Point, mapping

    from pvmaps.pipeline.imagery import mosaic, to_web_mercator, to_wgs84_polygons
    from pvmaps.pipeline.roofs import (
        area_m2,
        build_image_predictor,
        mask_to_polygons,
        masks_at_point,
    )

    if not checkpoint.exists():
        typer.secho(
            f"No SAM2 checkpoint at {checkpoint}.\n"
            f"  pipeline fetch-checkpoint --out {checkpoint}\n"
            f"and make sure --model-cfg matches the weights you fetched.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)

    targets = _roof_targets(pilot, building_id)
    if not targets:
        typer.secho("No buildings found. Run `seed` first.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        # Not refused -- it works, it is just slow enough that somebody should
        # know they are doing it before they wait.
        typer.secho(
            "CUDA is not available; SAM2 will run on CPU and take minutes per roof.",
            fg=typer.colors.YELLOW,
        )
    else:
        typer.echo(f"  device  {torch.cuda.get_device_name(0)}")

    # One model load for the whole run, not one per roof.
    predictor = build_image_predictor(str(checkpoint), model_cfg)

    features = []
    for bid, lat, lon in targets:
        image, transform = mosaic(
            lat, lon, z=zoom, radius_tiles=radius_tiles, data_dir=data_dir
        )
        centre = Point(*to_web_mercator(lon, lat))
        px, py = ~transform @ (centre.x, centre.y)
        scored = masks_at_point(predictor, image, px, py)

        # SAM2 offers the same point at three scales. Keep the polygon that
        # actually covers the surveyed point and clears the area floor, then let
        # the model's own score break the tie -- smallest-first would
        # systematically prefer a single roof PLANE over the roof.
        candidates = []
        for mask, score in scored:
            for poly in mask_to_polygons(mask, transform):
                if not poly.contains(centre):
                    continue
                wgs = to_wgs84_polygons([poly])[0]
                m2 = area_m2(wgs)
                if m2 >= min_area_m2:
                    candidates.append((score, m2, wgs))

        if not candidates:
            typer.secho(
                f"  {bid:18} nothing at the surveyed point above {min_area_m2} m2 "
                f"({len(scored)} masks offered)",
                fg=typer.colors.YELLOW,
            )
            continue

        # EVERY qualifying scale is emitted, not the best-scoring one.
        #
        # Measured against the hand-corrected pilot areas, picking one by SAM2's
        # own score lands between 0.1x and 84x of the truth (STATUS.md 12): the
        # score says how cleanly a region was segmented, not whether the region
        # is a roof. Emitting a single winner would dress that up as an answer.
        # Emitting all three, ranked and measured, is what the hand-correction
        # workflow in PRD 12 can actually use -- a person picks in one glance,
        # and nothing here pretends to have picked for them.
        candidates.sort(key=lambda c: -c[0])
        summary = ", ".join(f"{m2:.0f}" for _, m2, _ in candidates)
        typer.echo(
            f"  {bid:18} {len(candidates)} scales at the surveyed point: "
            f"{summary} m2  (best score {candidates[0][0]:.3f})"
        )
        for rank, (score, m2, geom) in enumerate(candidates, start=1):
            features.append(
                {
                    "type": "Feature",
                    "geometry": mapping(geom),
                    "properties": {
                        "id": bid,
                        "rank": rank,
                        "area_m2": round(m2, 2),
                        "source": "SAM2_POINT_PROMPTED",
                        "sam2_score": round(score, 4),
                        "selection": (
                            "one of several scales at the surveyed point; "
                            "UNRANKED BY ROOFNESS -- pick by hand (no classifier)"
                        ),
                        "model_cfg": model_cfg,
                        "checkpoint": checkpoint.name,
                        "zoom": zoom,
                    },
                }
            )

    if out and features:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps({"type": "FeatureCollection", "features": features}, indent=2),
            encoding="utf-8",
        )
        typer.echo(f"\nwrote {len(features)} predicted roofs to {out}")

    typer.secho(
        "\nThese are PROPOSALS. PRD 12: hand-correct them before seeding, and do "
        "not report an IoU computed against anything but hand-drawn ground truth.",
        fg=typer.colors.YELLOW,
    )


@app.command("fetch-checkpoint")
def fetch_checkpoint(
    out: Annotated[Path, typer.Option(help="Where to write the .pt file.")] = Path(
        "/checkpoints/sam2.1_hiera_small.pt"
    ),
    url: Annotated[
        str, typer.Option(help="Source. Defaults to Meta's published SAM2.1 small.")
    ] = "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_small.pt",
) -> None:
    """Download SAM2 weights. Explicit, because weights are not in the image.

    `docker/pipeline.Dockerfile` installs the SAM2 *code* from Meta's repository
    but not the *weights*, which are hundreds of megabytes and would be baked
    into every rebuild. `.gitignore` excludes `checkpoints/` and `*.pt` for the
    same reason. So this is a separate, deliberate step rather than something
    that happens silently the first time `segment` runs.

    Small is the default because the pilot GPU has 6 GB: hiera_large wants more
    than that at z19 with a 768 px mosaic.
    """
    if out.exists() and out.stat().st_size > 0:
        typer.echo(f"{out} already present ({out.stat().st_size / 1e6:.0f} MB)")
        return

    import requests

    out.parent.mkdir(parents=True, exist_ok=True)
    typer.echo(f"fetching {url}")
    with requests.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        written = 0
        with out.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
                written += len(chunk)
    typer.echo(f"wrote {out} ({written / 1e6:.0f} MB)")


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
