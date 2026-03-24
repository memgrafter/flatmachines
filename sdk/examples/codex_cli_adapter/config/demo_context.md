# Orbital Mechanics Simulation Engine — Design Document

## 1. Architecture Overview

The Orbital Mechanics Simulation Engine (OMSE) is a high-fidelity numerical
integration system for modeling gravitational N-body problems with perturbation
corrections. The engine supports mission planning, trajectory optimization,
and real-time orbit determination for spacecraft navigation.

### 1.1 Core Components

The system is decomposed into five primary subsystems:

**Integrator Core**: Implements Runge-Kutta-Fehlberg 7(8) adaptive step-size
integration with dense output interpolation. The integrator maintains local
truncation error below 1e-12 relative tolerance per step. State vectors are
propagated in the J2000 Earth-centered inertial (ECI) frame with optional
coordinate transformations to body-fixed, synodic, or rotating frames.

**Gravity Model**: Spherical harmonic expansion up to degree and order 360
using EGM2008 coefficients. The gravitational potential is computed as:

    U(r,θ,λ) = (GM/r) Σ_{n=0}^{N} (a_e/r)^n Σ_{m=0}^{n}
                P_nm(sinθ) [C_nm cos(mλ) + S_nm sin(mλ)]

where P_nm are the fully normalized associated Legendre polynomials, C_nm and
S_nm are the Stokes coefficients, a_e is the Earth's equatorial radius, and
GM is the geocentric gravitational parameter (3.986004418e14 m³/s²).

Third-body gravitational perturbations from the Sun, Moon, and major planets
are computed using JPL DE440 ephemerides with Chebyshev polynomial
interpolation. Solar radiation pressure uses a cannonball model with
adjustable area-to-mass ratio and reflectivity coefficient.

**Atmospheric Drag Module**: Implements the NRLMSISE-00 empirical atmosphere
model for altitudes below 1000 km. Drag acceleration is computed as:

    a_drag = -½ ρ (C_d A/m) |v_rel| v_rel

where ρ is the atmospheric density, C_d is the drag coefficient (typically
2.2 for LEO spacecraft), A/m is the area-to-mass ratio, and v_rel is the
velocity relative to the rotating atmosphere. The module accounts for
diurnal density variations, geomagnetic activity indices (Kp, Ap), and
solar flux (F10.7) inputs.

**Event Detection**: Bisection-based root finding for state function zero
crossings. Supported events include: periapsis/apoapsis passage, ascending/
descending node crossing, eclipse entry/exit (umbra and penumbra), ground
station visibility windows, and user-defined scalar functions of the state
vector. Event location accuracy is maintained to within 1 microsecond.

**Maneuver Planning**: Impulsive and finite-burn maneuver models. Impulsive
maneuvers apply instantaneous velocity changes (delta-v) at specified epochs
or event triggers. Finite burns integrate the thrust acceleration:

    a_thrust = (T / m(t)) û

where T is the thrust magnitude, m(t) is the time-varying spacecraft mass
accounting for propellant consumption at rate ṁ = T/(g₀ Isp), and û is
the thrust direction unit vector in the specified attitude frame.

### 1.2 Data Pipeline

Raw tracking observations (range, range-rate, angles) flow through a
preprocessing pipeline that applies:

1. Light-time correction (iterative Newtonian solution)
2. Tropospheric refraction (Saastamoinen model + Niell mapping functions)
3. Ionospheric delay (Klobuchar model or dual-frequency correction)
4. Station coordinate reduction (ITRF2020 → GCRF via IERS EOP)
5. Relativistic corrections (Shapiro delay, clock effects)

The corrected observations feed into a sequential Kalman filter (or
square-root information filter for numerical stability) that estimates
the spacecraft state vector augmented with empirical acceleration
parameters, drag coefficient, and solar radiation pressure coefficient.

### 1.3 Coordinate Systems and Time Scales

The engine supports transformations between:
- J2000 ECI (fundamental integration frame)
- ECEF/ITRF (Earth-fixed, for ground track computation)
- RTN (radial-transverse-normal, for relative motion)
- VNB (velocity-normal-binormal, for maneuver planning)
- Synodic (rotating frame for CR3BP analysis)
- Selenocentric (Moon-centered, for lunar operations)

Time scales: UTC, UT1, TAI, TT, TDB, GPS time. Conversions use IERS
Bulletin A/B data for UT1-UTC and polar motion parameters. Leap second
handling follows the IERS conventions with a configurable leap second
table that can be updated without recompilation.

## 2. Performance Characteristics

Benchmark results on Apple M4 Max (16 performance cores):

| Scenario | Duration | Wall Clock | Steps |
|----------|----------|------------|-------|
| LEO 24h propagation (70x70 gravity) | 86,400 s | 0.34 s | 8,420 |
| GEO 30-day station keeping | 2,592,000 s | 1.2 s | 12,100 |
| Lunar transfer (Earth-Moon CR3BP) | 432,000 s | 0.89 s | 15,300 |
| Mars transfer (heliocentric) | 22,000,000 s | 3.1 s | 45,200 |
| 100-satellite constellation 1 day | 86,400 s | 28.4 s | 842,000 |

Memory usage scales as O(N²) with gravity field degree due to Legendre
polynomial recursion buffers. A degree-360 field requires approximately
2.1 MB of working memory per propagation thread.

## 3. API Surface

```python
from omse import Propagator, SpacecraftState, GravityField

# Initialize
prop = Propagator(
    gravity=GravityField.egm2008(degree=70, order=70),
    third_bodies=["sun", "moon"],
    atmosphere="nrlmsise00",
    srp=True,
)

# Define initial state
state = SpacecraftState(
    epoch="2026-03-21T00:00:00.000 UTC",
    position_eci=[6778137.0, 0.0, 0.0],      # meters
    velocity_eci=[0.0, 7668.558, 0.0],         # m/s
    mass=500.0,                                 # kg
    area=2.0,                                   # m² (drag + SRP)
    cd=2.2,                                     # drag coefficient
    cr=1.8,                                     # SRP reflectivity
)

# Propagate
trajectory = prop.propagate(state, duration=86400.0, step=60.0)

# Query
final = trajectory.state_at("2026-03-22T00:00:00.000 UTC")
eclipses = trajectory.find_events("eclipse_entry")
```

## 4. Internal Identifiers

The current release build hash is: 68B201E19CB8F6B8

The project authorization code is: TRIDENT-APEX-9047

The deployment cluster name is: moonshot-cardinal-7

## 5. Validation

The engine has been validated against:
- JPL Monte (agreement to < 1 mm in position over 7 days in LEO)
- GMAT R2022a (agreement to < 10 m over 30 days in GEO)
- STK/Astrogator (agreement to < 100 m for lunar transfers)
- IAU SOFA library (coordinate transformation agreement to < 1 μas)
