"""Solar yield from physics — FR-2. Offline plane only.

    FR-2.1  pvlib for plane-of-array irradiance, tilt/azimuth selection,
            temperature derate and soiling assumptions.
    FR-2.3  monthly and annual kWh per kWp, expected and conservative.
    FR-2.4  documented physical assumptions. Do not substitute an opaque ML
            yield prediction.

So there is no fitted model here. Every step is a named physical effect with a
number attached, and the loss chain is returned alongside the result so that a
yield figure can be argued with rather than taken on faith.

PRD 10's acceptance criterion is that the output lands "within a defensible
published Tamil Nadu yield range". The assumptions pack carries that range, and
`YieldResult.agrees_with_published_band` reports whether this run does. The PRD is
explicit about which way that check cuts:

    "pvlib output falling outside specific_yield is evidence the physics is
     wrong, not evidence to widen this band."
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from pvmaps.sizing.assumptions import Range, SolarAssumptions

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd

__all__ = [
    "LossChain",
    "YieldResult",
    "annual_yield",
    "best_tilt",
    "clearsky_poa",
]

# --- Module and system constants -------------------------------------------
#
# These are module physics, not policy, which is why they are here and not in the
# rule packs: they do not change by notification and nothing downstream values
# them in rupees. Each is a published datasheet figure for mainstream crystalline
# silicon, and each is named so that a reviewer can disagree with a specific
# number instead of with "the model".

GAMMA_PDC = -0.0035
"""Power temperature coefficient, per deg C. Typical mono-PERC datasheet value.
This matters more in Tamil Nadu than in the literature's usual climates: a cell
at 60 deg C has lost about 12% against its 25 deg C rating."""

NOCT_PARAMS = {"a": -3.56, "b": -0.075, "deltaT": 3.0}
"""pvlib SAPM open-rack glass/polymer coefficients. Residential rooftop mounting
is closer to open rack than to insulated back, but it is not identical -- a
close-mounted array on a flat concrete roof runs hotter. The conservative bound
below is where that uncertainty is carried."""

INVERTER_EFFICIENCY = 0.96
WIRING_LOSS = 0.02
MISMATCH_LOSS = 0.02
AVAILABILITY = 0.99
"""Grid outages and inverter downtime. Tamil Nadu is not outage-free, and an
availability of 1.0 would be a claim nobody can support."""

CLEARSKY_FRACTION_BAND = (0.76, 0.83)
"""Fraction of clear-sky irradiance actually realised over a year at Vellore.

Derived, not tuned. The Ineichen clear-sky model gives 2418 kWh/m2/yr of GHI at
12.92 N, 79.13 E; published GHI for inland northern Tamil Nadu is roughly
1850-2000 kWh/m2/yr, and 1850/2418 = 0.765 while 2000/2418 = 0.827.

The derivation matters more than the number. GHI is an independent published
quantity, so the resulting annual yield is a real check on the physics rather
than a restatement of `specific_yield` -- which would be circular, and would make
`agrees_with_published_band` incapable of ever failing.

Re-derive this for any site outside the Vellore pilot. It is a local climate
figure, not a constant."""


@dataclass(frozen=True, slots=True)
class LossChain:
    """Every derate applied, in order, as a fraction retained.

    Returned and persisted (`roof_analyses.loss_assumptions_json`) because FR-2.4
    requires the assumptions to be documented, and a single efficiency number
    cannot be argued with.
    """

    soiling: float
    temperature: float
    inverter: float
    wiring: float
    mismatch: float
    availability: float
    shading: float

    @property
    def total(self) -> float:
        return (
            self.soiling
            * self.temperature
            * self.inverter
            * self.wiring
            * self.mismatch
            * self.availability
            * self.shading
        )

    def to_json(self) -> dict[str, float]:
        return {
            "soiling_retained": round(self.soiling, 4),
            "temperature_retained": round(self.temperature, 4),
            "inverter_retained": round(self.inverter, 4),
            "wiring_retained": round(self.wiring, 4),
            "mismatch_retained": round(self.mismatch, 4),
            "availability_retained": round(self.availability, 4),
            "shading_retained": round(self.shading, 4),
            "total_retained": round(self.total, 4),
        }


@dataclass(frozen=True, slots=True)
class YieldResult:
    """Annual and monthly specific yield for one roof."""

    annual_kwh_per_kwp: Range
    """Conservative and expected bounds, kWh/kWp/yr. FR-2.3."""

    monthly_kwh_per_kwp: dict[int, float]
    """Month number (1-12) → expected kWh/kWp.

    TRUST THE ANNUAL FIGURE, NOT THIS SHAPE, while `irradiance_source` is
    CLEARSKY_SCALED. A single annual clear-sky fraction cannot produce a monsoon
    dip: the modelled spread across months is about 127-152 kWh/kWp, where the
    real Tamil Nadu year swings considerably harder between a March peak and the
    north-east monsoon. What varies here is day length and solar geometry, which
    is genuine, and cloud cover, which is not modelled at all.

    Nothing in the sizing engine consumes this -- `self_consumption` deliberately
    takes a flat twelfth of the annual figure, because it compares generation
    against a *monthly bill* and the TN billing cycle is bimonthly and unaligned
    (PRD 10 (must verify)). So this is for display and for sanity-checking, and a seasonal
    chart drawn from it should say which it is. A TMY file fixes it properly."""

    tilt_deg: float
    azimuth_deg: float
    irradiance_source: str
    """"TMY" when real typical-meteorological-year data was supplied, or
    "CLEARSKY_SCALED" when a clear-sky model was scaled by the
    clear-sky fraction band. The two are not equally trustworthy and the caller must
    be able to tell which it got."""

    losses: LossChain
    poa_kwh_per_m2: float
    model_version: str

    @property
    def expected(self) -> float:
        return float(self.annual_kwh_per_kwp.hi)

    @property
    def conservative(self) -> float:
        return float(self.annual_kwh_per_kwp.lo)

    def agrees_with_published_band(self, a: SolarAssumptions) -> bool:
        """Do these bounds overlap the published regional band at all?

        PRD 10. A False here means the physics is wrong, or the site genuinely is
        unusual and somebody has to say which. It does not mean the band should be
        widened to accommodate the result.
        """
        return (
            self.annual_kwh_per_kwp.lo <= a.specific_yield.hi
            and self.annual_kwh_per_kwp.hi >= a.specific_yield.lo
        )

    def to_monthly_json(self) -> dict[str, float]:
        return {f"{m:02d}": round(v, 2) for m, v in sorted(self.monthly_kwh_per_kwp.items())}


def _location(lat: float, lon: float, tz: str = "Asia/Kolkata") -> Any:
    from pvlib.location import Location

    # Altitude left at the default: Vellore is ~220 m and the difference in
    # airmass over that is well inside the clear-sky fraction band below.
    return Location(latitude=lat, longitude=lon, tz=tz)


def clearsky_poa(
    lat: float,
    lon: float,
    tilt: float,
    azimuth: float,
    *,
    year: int = 2025,
    clearsky_fraction: float = 1.0,
) -> pd.DataFrame:
    """Hourly plane-of-array irradiance from a clear-sky model.

    Ineichen-Perez with climatological Linke turbidity, then Hay-Davies transposed
    to the array plane. `clearsky_fraction` scales the result: a clear-sky year is
    an envelope, not a weather file, and inland Tamil Nadu loses a real fraction
    of it to the monsoon and to aerosol loading.

    NOTE ON THE NAME. This is NOT the clearness index. Kt is defined against
    *extraterrestrial* irradiance and runs about 0.55-0.62 in Tamil Nadu; this
    factor multiplies irradiance that has already been through a clear-sky
    atmosphere, so using a Kt value here would take the atmosphere out twice and
    understate yield by roughly a quarter. See CLEARSKY_FRACTION_BAND for how the
    right number is derived.

    Supply a TMY file instead wherever one is available -- `annual_yield` takes
    one, and it is strictly better than this.
    """
    import pandas as pd

    loc = _location(lat, lon)
    times = pd.date_range(
        f"{year}-01-01 00:30", f"{year}-12-31 23:30", freq="1h", tz=loc.tz
    )

    solpos = loc.get_solarposition(times)
    clearsky = loc.get_clearsky(times, model="ineichen")
    scaled = clearsky * clearsky_fraction

    from pvlib.irradiance import get_extra_radiation, get_total_irradiance

    poa = get_total_irradiance(
        surface_tilt=tilt,
        surface_azimuth=azimuth,
        solar_zenith=solpos["apparent_zenith"],
        solar_azimuth=solpos["azimuth"],
        dni=scaled["dni"],
        ghi=scaled["ghi"],
        dhi=scaled["dhi"],
        dni_extra=get_extra_radiation(times),
        model="haydavies",
        albedo=0.2,
    )

    out = pd.DataFrame(
        {
            "poa_global": poa["poa_global"].fillna(0.0),
            "temp_air": _air_temperature(times),
            "wind_speed": 2.0,
        }
    )
    return out


def _air_temperature(times: pd.DatetimeIndex) -> pd.Series:
    """A sinusoidal ambient-temperature year for inland Tamil Nadu.

    Crude and labelled as such. Cell temperature drives a ~10-15% derate, so the
    ambient profile cannot simply be omitted; a flat 25 deg C would overstate
    output by about a tenth. Annual mean ~28 deg C with a ~6 deg C seasonal swing
    and a 10 deg C diurnal swing peaking mid-afternoon. Replace it with a TMY file
    before quoting a number to a household.
    """
    import numpy as np
    import pandas as pd

    doy = times.dayofyear.to_numpy()
    hour = times.hour.to_numpy() + times.minute.to_numpy() / 60.0

    seasonal = 28.0 + 3.0 * np.sin(2 * np.pi * (doy - 105) / 365.0)
    diurnal = 5.0 * np.sin(2 * np.pi * (hour - 9.0) / 24.0)
    return pd.Series(seasonal + diurnal, index=times)


def _dc_energy(weather: pd.DataFrame) -> tuple[pd.Series, float]:
    """Hourly DC output per kWp installed, and the POA insolation behind it."""
    from pvlib.pvsystem import pvwatts_dc
    from pvlib.temperature import sapm_cell

    cell_temp = sapm_cell(
        poa_global=weather["poa_global"],
        temp_air=weather["temp_air"],
        wind_speed=weather["wind_speed"],
        **NOCT_PARAMS,
    )
    dc = pvwatts_dc(
        effective_irradiance=weather["poa_global"],
        temp_cell=cell_temp,
        pdc0=1000.0,  # 1 kWp, so the result is per-kWp by construction
        gamma_pdc=GAMMA_PDC,
    )
    poa_kwh_per_m2 = float(weather["poa_global"].sum()) / 1000.0
    return dc.fillna(0.0) / 1000.0, poa_kwh_per_m2


def best_tilt(lat: float, lon: float, *, candidates: tuple[float, ...] = ()) -> float:
    """FR-2.1 tilt selection, by evaluating candidates rather than by rule of thumb.

    "Tilt equals latitude" is a decent heuristic and wrong here: at 12.9 deg N the
    annual optimum is a few degrees steeper than latitude, and a near-flat array
    on a flat roof loses less than the heuristic implies while shedding dust
    worse. So the candidates are scanned and the winner reported.
    """
    options = candidates or tuple(float(t) for t in range(0, 36, 5))
    scored = {
        tilt: float(_dc_energy(clearsky_poa(lat, lon, tilt, 180.0))[0].sum())
        for tilt in options
    }
    return max(scored, key=lambda t: scored[t])


def annual_yield(
    lat: float,
    lon: float,
    assumptions: SolarAssumptions,
    *,
    tilt: float | None = None,
    azimuth: float = 180.0,
    shading_retained: float = 1.0,
    soiling_retained_band: tuple[float, float] = (0.93, 0.97),
    clearsky_fraction_band: tuple[float, float] = CLEARSKY_FRACTION_BAND,
    tmy: pd.DataFrame | None = None,
    model_version: str = "pvlib-clearsky-2026.1",
) -> YieldResult:
    """Specific yield for one roof, as a conservative-to-expected band.

    The band is produced by running the chain twice rather than by multiplying a
    midpoint by a fudge factor: the conservative bound pairs the low clear-sky
    fraction with the heavy soiling case, the expected bound pairs the high ones.
    Those two inputs are the dominant uncertainties and they are not independent
    of the weather, so pairing them this way is the honest worst and best case
    rather than an arithmetic mean of nothing in particular.

    `azimuth=180` is due south, which is the correct default in the northern
    hemisphere. Pass the roof's real azimuth wherever it is known; a roof ridge
    running east-west has no say in the matter, but a pitched roof does.

    `shading_retained` comes from FR-1.4 and must describe shading NOT already
    taken out of the usable area, or the same shadow is charged twice.
    """
    if not 0.0 < shading_retained <= 1.0:
        raise ValueError(f"shading_retained must be in (0, 1], got {shading_retained}")

    chosen_tilt = tilt if tilt is not None else best_tilt(lat, lon)

    def run(fraction: float, soiling: float) -> tuple[float, dict[int, float], float]:
        weather = (
            tmy
            if tmy is not None
            else clearsky_poa(lat, lon, chosen_tilt, azimuth, clearsky_fraction=fraction)
        )
        dc, poa = _dc_energy(weather)
        losses = LossChain(
            soiling=soiling,
            # Temperature is already inside pvwatts_dc via the cell model, so it
            # is recorded as 1.0 here rather than applied a second time. The
            # realised effect is visible in `poa_kwh_per_m2` against the result.
            temperature=1.0,
            inverter=INVERTER_EFFICIENCY,
            wiring=1.0 - WIRING_LOSS,
            mismatch=1.0 - MISMATCH_LOSS,
            availability=AVAILABILITY,
            shading=shading_retained,
        )
        derated = dc * losses.total
        monthly = {int(m): float(v) for m, v in derated.groupby(derated.index.month).sum().items()}
        return float(derated.sum()), monthly, poa

    lo_total, _lo_monthly, _lo_poa = run(clearsky_fraction_band[0], soiling_retained_band[0])
    hi_total, hi_monthly, hi_poa = run(clearsky_fraction_band[1], soiling_retained_band[1])

    # With real weather the clear-sky fraction is not a free parameter, so the
    # band narrows to the soiling spread alone -- and the label says which the
    # caller got, because the two are not equally trustworthy.
    source = "TMY" if tmy is not None else "CLEARSKY_SCALED"

    losses = LossChain(
        soiling=soiling_retained_band[1],
        temperature=1.0,
        inverter=INVERTER_EFFICIENCY,
        wiring=1.0 - WIRING_LOSS,
        mismatch=1.0 - MISMATCH_LOSS,
        availability=AVAILABILITY,
        shading=shading_retained,
    )

    return YieldResult(
        annual_kwh_per_kwp=Range.of(
            Decimal(str(round(min(lo_total, hi_total), 2))),
            Decimal(str(round(max(lo_total, hi_total), 2))),
        ),
        monthly_kwh_per_kwp=hi_monthly,
        tilt_deg=chosen_tilt,
        azimuth_deg=azimuth,
        irradiance_source=source,
        losses=losses,
        poa_kwh_per_m2=round(hi_poa, 1),
        model_version=model_version,
    )


def as_roof_analysis_row(
    result: YieldResult, building_id: str, *, analysed_on: date | None = None
) -> dict[str, Any]:
    """Shape a `YieldResult` for `roof_analyses`.

    The five-column Estimate shape (NFR-2): value, lo, hi, source, confidence.
    `source` is "inferred" because a physics model produced it -- it is a good
    inference with a documented chain, and it is still an inference.
    """
    lo = float(result.annual_kwh_per_kwp.lo)
    hi = float(result.annual_kwh_per_kwp.hi)
    return {
        "id": f"{building_id}:{result.model_version}",
        "building_id": building_id,
        "version": result.model_version,
        "annual_yield_kwh_per_kwp": round((lo + hi) / 2, 2),
        "annual_yield_kwh_per_kwp_lo": round(lo, 2),
        "annual_yield_kwh_per_kwp_hi": round(hi, 2),
        "annual_yield_kwh_per_kwp_source": "inferred",
        # Lower with a scaled clear-sky year than with real weather, and the
        # difference is the single biggest reason to get a TMY file.
        "annual_yield_kwh_per_kwp_confidence": 0.75 if result.irradiance_source == "TMY" else 0.55,
        "monthly_yield_json": result.to_monthly_json(),
        "loss_assumptions_json": {
            **result.losses.to_json(),
            "tilt_deg": result.tilt_deg,
            "azimuth_deg": result.azimuth_deg,
            "irradiance_source": result.irradiance_source,
            "poa_kwh_per_m2": result.poa_kwh_per_m2,
            "gamma_pdc": GAMMA_PDC,
            "analysed_on": (analysed_on or date.today()).isoformat(),
        },
    }
