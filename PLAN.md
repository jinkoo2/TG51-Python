# TG51-python plan

A PyQt5 desktop app that runs AAPM TG-51 reference dosimetry with `pylinac.calibration.tg51`. This file is the plan the app implements.

Reference copies of the protocol sit in `_ref_docs`:

| File | What it is | Source |
| --- | --- | --- |
| `AAPM_TG-51_1999.pdf` (1,765,836 bytes) | AAPM Report 067, Almond et al., Med. Phys. 26:1847–1870 (1999). This is the AAPM-hosted PDF, which corrects equation 8A on page 16 of the journal version and includes the fillable worksheets. | https://prod.aapm.org/docs/wwwlibraries/report-files/reports/rpt-67.pdf |
| `AAPM_TG-51_Addendum_2014.pdf` (377,567 bytes) | AAPM Report 067.A1, McEwen et al., Med. Phys. 41:041501 (2014). New photon \(k_Q\) data, more chambers, and the uncertainty budget. Pylinac’s photon class uses this addendum. | https://www.aapm.org/pubs/reports/RPT_67_Addendum.pdf |

Pylinac API reference: https://pylinac.readthedocs.io/en/latest/calibration_docs.html

AAPM Report 374 (WGTG51, 2022) is later guidance and is out of scope for the first version.

## What the app does

The physicist keeps three catalogs, then records a calibration against one energy of one machine.

- **Users.** People who perform a calibration. The selected user is the pylinac `physicist` string.
- **Ion chambers.** The lab’s chambers: a pylinac chamber model (or a custom fit), plus the calibration-lab values pylinac does not store (\(N_{D,w}\), \(P_{elec}\), electrometer, serial number, lab, date).
- **Machines.** Each machine owns a list of energies. An energy is photon or electron, a nominal value (MV or MeV), and, for photons, whether the beam is FFF.
- **Calibration cases.** For the selected machine energy, create, edit, duplicate, and delete TG-51 cases. Each case stores the raw readings, runs pylinac, and keeps the calculated result.

## Layout

Follow the sibling apps (`CTQA-MPC-python`, `BeamDataViewer`): setuptools, Python ≥ 3.10, PyQt5, pytest, one console script.

```
TG51-python/
  PLAN.md
  pyproject.toml          # name tg51-python, script `tg51` → tg51app.cli:main
  settings.sample.json    # committed template, JSONC comments allowed
  settings.json           # live file, gitignored
  .gitignore              # /settings.json and **/_*  (same as CTQA-MPC-python)
  _ref_docs/              # local protocol PDFs, gitignored by **/_*
  _cases/                 # one JSON file per calibration, gitignored by **/_*
  tg51app/
    __init__.py
    cli.py
    app_settings.py
    models.py             # catalogs and case records
    calc.py               # builds and runs the pylinac classes
    gui.py
  tests/
```

The import package is `tg51app` so it does not shadow `pylinac.calibration.tg51`.

`settings.json` holds Institution, Font, Users, IonChambers, and Machines. Measurement cases go in `_cases/{machine_id}/{energy_id}/{case_id}.json`. A year’s readings do not belong in the settings file. `settings.sample.json` ships empty lists and commented examples. Load and save with the same JSONC strip the sibling apps use (`//` and `/* */` comments).

## Theme

Match the sibling heading and the BeamDataViewer font rule.

- Heading bar: background `#1f3a5f`, labels `#f8fafc`, buttons `#34547a` (hover `#456894`, disabled text `#94a3b8` on `#2a4a6e`). Title 16px, weight 600. Window title `TG-51`.
- Toolbar / secondary panels: `#f3f4f6`. Hint text `#64748b`.
- Font: `Font.family` and `Font.size` from settings. Empty family and size `0` mean the platform font plus 3 pt, with a 13 pt floor.

## Screens

One window, four pages from the heading bar: **Calibrations**, **Machines**, **Ion Chambers**, **Users**.

**Calibrations** is the home page.

- Left: machines, each expanded to its energies. The label is the nominal energy, modality, and `FFF` when set (`6 MV FFF`, `9 MeV`).
- Right: a table of cases for the selected energy (date, physicist, chamber, \(k_Q\), dose/MU at dmax, status). Buttons: New, Edit, Duplicate, Delete, Open PDF.
- The case editor is a dialog. Sections: setup, chamber, readings, beam quality, then a read-only results panel. **Calculate** runs pylinac and fills the results. **Save** writes the case only after a successful calculation, and also allows saving a draft that has not been calculated (status `draft` vs `calculated`). **Save PDF** calls `publish_pdf` on the pylinac object and records the path.

**Machines, Ion Chambers, and Users** are ordinary tables with New / Edit / Delete. Deleting a machine, energy, chamber, or user that a saved case still references is refused; the message names the case. Energies are edited inside the machine dialog, not as a separate catalog.

## Catalog fields

**User:** `id`, `name`, `email`.

**Ion chamber:**

- `id`, `name` (how the lab refers to it), `serial`
- `model`: a pylinac `IonChambers` name such as `PTW 30013`, resolved with `IonChambers.from_name`. `model` may instead be `custom`.
- Custom only: photon coefficients (`a`, `b`, `c`, and the primed set when the chamber supports TPR) and electron coefficients (`kq_ecal`, `a`, `b`, `c`). Missing coefficients are `null`. Pylinac’s `IonChamber` is built from these at calculation time. Photon \(k_Q\) in pylinac is for cylindrical chambers.
- Lab values, copied onto a case and overridable there: `n_dw` (Gy/nC), `p_elec`, `electrometer`, `calibration_lab`, `calibration_date`.

**Machine:** `id`, `name`, `manufacturer`, `model`, `serial`, `comment`.

**Energy** (owned by the machine): `id`, `modality` (`photon` or `electron`), `nominal` (number), `fff` (photons only; stored false for electrons).

## Case fields

Shared, mapped straight onto the pylinac constructor:

| App field | Pylinac |
| --- | --- |
| Institution from settings | `institution` |
| Selected user name | `physicist` |
| Machine name | `unit` |
| Measurement date | `measurement_date` |
| Temperature | `temp` in °C. The form also accepts °F and converts with `fahrenheit2celsius`. |
| Pressure | `press` in kPa. The form also accepts mmHg or mbar and converts with `mmHg2kPa` / `mbar2kPa`. |
| Chamber model or custom `IonChamber` | `chamber` |
| \(N_{D,w}\), \(P_{elec}\), electrometer | `n_dw`, `p_elec`, `electrometer` |
| Reference and reduced voltage | `voltage_reference`, `voltage_reduced` |
| Readings | `m_reference`, `m_opposite`, `m_reduced`. Each is a list; pylinac averages it. The form starts with one row and can add repeats. |
| Monitor units | `mu` |
| Optional adjusted M reading | `m_reference_adjusted` |
| Tissue correction | `tissue_correction`, default 1.0 |

**Photon** (`TG51Photon`): `energy` (the nominal MV, int), `fff`, `measured_pdd10`, `clinical_pdd10`, `lead_foil` (`LeadFoil.NONE`, `50cm`, or `30cm`). Pylinac turns the measured PDD(10) into PDD(10)x. Show that intermediate value (`pddx`) in the results.

**Electron** has two pylinac classes. The case stores `electron_method`:

- `legacy` → `TG51ElectronLegacy`. Official TG-51. Requires `k_ecal` and `m_gradient` (\(P_{gr}\)). This is the default, because it is the published protocol.
- `modern` → `TG51ElectronModern`. Muir & Rogers \(k_Q\) from \(R_{50}\) and the chamber. No \(k_{ecal}\) and no \(P_{gr}\). The dialog states pylinac’s warning in the form: these values are expected in a future addendum, they are not official, and they can differ by up to 1%.

Both electron classes also take `clinical_pdd`, `cone`, and `i_50` (the ionization depth used for \(R_{50}\)).

Results stored with the case after Calculate, plus `pylinac_version`, so a later pylinac upgrade does not silently change a signed record. Recalculate overwrites the stored result and stamps the new version.

| Class | Stored outputs |
| --- | --- |
| Photon | `pddx`, `kq`, `dose_mu_10`, `dose_mu_dmax`, and the `_adjusted` pair when an adjusted reading was entered |
| Electron | `r_50`, `dref`, `kq`, `dose_mu_dref`, `dose_mu_dmax`, the `_adjusted` pair, and for legacy also `pq_gr` |

Also store the correction factors pylinac exposes on the object when they are present (`p_tp`, `p_ion`, `p_pol`, `m_corrected`), so the worksheet on screen matches the protocol without a second implementation of the equations.

## Checks before Calculate

Block Calculate, with a specific message, when:

- temperature, pressure, voltages, MU, \(N_{D,w}\), \(P_{elec}\), or a required beam-quality field is missing
- any of the three reading groups is empty
- reduced voltage is greater than or equal to the reference voltage
- a custom chamber is missing the coefficients for the selected modality
- a photon chamber has no photon \(k_Q\) fit, or an electron chamber has no electron fit
- legacy electron is missing \(k_{ecal}\) or \(P_{gr}\)

Warn, and still allow Calculate, when temperature is outside 17–27 °C or pressure is outside 91–111 kPa. Those are the ranges pylinac documents for the correction polynomials. The warning stays visible on the saved case.

## Tests

`pytest -p no:cacheprovider` from the project directory. Qt tests use an offscreen `qapp` fixture. Do not construct `QPrinter` (this machine raises COM `0x80040155`).

- Settings round-trip: JSONC comments, missing file falls back to the sample defaults, font defaults.
- A photon case built from the numbers in the pylinac TG-51 photon example produces the same `kq`, `dose_mu_10`, and `dose_mu_dmax` as calling `TG51Photon` directly.
- One legacy electron case and one modern electron case likewise match pylinac.
- Unit conversion: 760 mmHg and 22 °C land on the kPa and °C values pylinac’s helpers return.
- Delete is refused when a case still points at the record.
- Case JSON written under a temp `_cases` directory reloads with the same ids and readings.

## Explicitly later

DocuForms push, TRS-398, uncertainty budgets from the addendum, and worksheet Word export. The first version calculates, stores, and writes the pylinac PDF.
