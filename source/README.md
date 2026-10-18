# source — the code that generates everything

Every file in `../production/` is produced from here. You edit the code, run `make`, and the PCB,
plate, case and firmware stay in sync.

## Commands

```sh
make all                      # the whole pipeline (plain `make` does the same)

# single steps, e.g. make pcb
make layout                   # layout preview
make pcb                      # PCB: generate, autoroute with Freerouting, check with DRC
make schematic                # KiCad schematic + ERC + PDF/SVG
make verify                   # circuit.py == PCB == schematic, pin by pin (writes netlist.json)
make check                    # circuit tests against the datasheets (pcb/check_circuit.py)
make plate                    # plate
make fab                      # files for JLCPCB
make case                     # case + 3D-printed plate (STL/STEP) + fit check
make firmware                 # RMK firmware (.uf2)
make renders                  # Blender Cycles renders of the keyboard + KiCad pictures of the PCB
make review                   # images + files + posts for a human design review (../production/review/, local: not in git)
make publish                  # copies the finished files into ../production/ and writes its README
make sanitize                 # pins the build timestamps for reproducible output
make commit m="..."           # commits with a fixed date (deterministic history)
```

Intermediate files live in `build/`; the finished ones are copied into `../production/`
by `publish.py`.

`make renders` exports the PCB and the plate from KiCad as GLB (with every 3D model), makes Cherry-profile keycaps
with KeyV2 (OpenSCAD) and the switch meshes from the kiswitch MX model (`case/render_parts.py`), then runs Blender
headless twice: `case/render.py` for the product shots (front, back, side, top, bottom, exploded, both sides of the
bare PCB) and `case/render_desk.py` for `desk.png`, the keyboard from above on a desk mat with a coiled cable, a mug,
a plant, a notebook, floppy disks and loose keycaps and switches. Pictures go to `build/img/`, the scenes to
`build/render/keyboard.blend` and `desk.blend`, to open in Blender. `RENDER_SAMPLES` sets the Cycles samples (default 128,
denoised); `RENDER_SCALE` the resolution in percent (default 100, e.g. `make renders RENDER_SCALE=25
RENDER_SAMPLES=16` for a quick draft). A full set takes about 20 minutes on an M4.

## Files

| File | What it does |
|---|---|
| `layout.py` | **Single source of truth** for the key arrangement and the matrix |
| `paths.py` | Where the files go: working files in `build/`, finished files in `../production/` |
| `pcb/circuit.py` | **The circuit as data**: every component with its pins and the net of each pin. The PCB connections, the schematic and the netlist for the checks all come from here. The RP2040 and its minimum circuit after Raspberry Pi's "Hardware design with RP2040", with the list of differences from the wireless board (branch `main`); the sound card (`audio()`: CH334P hub, CM108B codec, headset jack) after C-Media's demo board |
| `pcb/gen_pcb.py` | Places switches, diodes, stabilizers, mounting holes and the outline; net classes (0.2 mm for the RP2040's 0.4 mm-pitch pads) |
| `pcb/electronics.py` | Places the RP2040 with its flash, crystal and capacitors, USB-C, hub, regulator, BOOT / RESET buttons, test pads, sound card and jack; assigns the RP2040's GPIOs to the matrix and the LED; draws the USB high-speed pair (receptacle → ESD array → hub) and the ground connections the autorouter cannot find (RP2040 exposed pad, codec and amplifier ground pins) |
| `pcb/gen_schematic.py`, `pcb/kicad_sym.py` | KiCad schematic generated from `circuit.py` (symbols taken from the KiCad libraries) |
| `pcb/verify_netlist.py` | Pin-by-pin check: `circuit.py` == PCB == schematic; writes `netlist.json` |
| `pcb/check_circuit.py` | Circuit tests against the datasheets, (the designer must not edit it) |
| `pcb/route.py` | Automatic routing with Freerouting (deterministic: one run) |
| `pcb/repair.py` | Completes what Freerouting leaves: deletes crossing or too close segments and joins open connections with a small grid router (A*, both layers, vias) |
| `pcb/finish_pcb.py` | Imports the tracks, runs `repair.py`, drops single-layer vias, adds the ground pours, region-aware stitching vias (fine in the electronics strip, coarse in the key field) and teardrops |
| `pcb/gen_plate.py` | Plate outline: FR4 from JLCPCB (gerbers) or laser cut (DXF, in mm) |
| `pcb/jlc_export.py` | Bill of materials (BOM) and placement file (CPL) for JLCPCB |
| `mount.py` | Top mount: the plate's ears and back tabs and where its screws go (used by the plate, the case and the fit check) |
| `case/gen_case.py` | Parametric case (build123d), split into printable pieces; top mount: the plate is screwed to the top frame, the PCB hangs from the switches |
| `case/gen_plate_print.py` | 3D-printable plate in two pieces (1.5 mm where the switches clip in, 4 mm ribs), same outline, ears and holes as the FR4 plate (`mount.py`) |
| `case/check_fit.py` | Fit check: PCB, components, plate, keys, screws and ports against the printed pieces, assembly paths, thicknesses, print overhangs (report in `build/case/check-fit.txt`) |
| `pcb/review_package.py` | Images for a human review (schematic on white, one copper layer per image, close-ups, straight-down 3D), copied with `reviews/review-request.md` (where and what to post) to `../production/review/` |
| `pcb/export_parts.py` | Exports the component positions and outlines from KiCad, plus the plate cut-outs, for the fit check |
| `case/render_parts.py` | Everything the renders need: PCB and plate as GLB from KiCad (placed by `kicad_origin` in `parts.json`), finer case meshes, Cherry-profile keycaps (KeyV2, per row and size), the MX switch split by material, the desk mat print, `scene.json` |
| `case/jack_model.py` | 3D model of the headset jack (KiCad has none for the PJ-320D-4A), into `lib/lira.3dshapes/` |
| `case/render.py` | Blender scene + Cycles renders of the assembled keyboard (case, plate, PCB, switches, keycaps with legends) and an exploded view |
| `case/render_desk.py` | The desk scene (top-down photo of the keyboard on a desk, with props modelled in the script) |
| `case/deskmat.py` | The desk mat's print: a technical drawing of the keyboard (dimensions, Cherry rows, MX cut-out, key matrix) |
| `case/fetch_assets.py` | Downloads the desk's oak texture and the potted plant from Poly Haven (CC0) into `assets/`, once |
| `firmware/gen_firmware.py` | RMK's `keyboard.toml` and `vial.json` (pins from the PCB, layout from `layout.py`, default keymap) |
| `firmware/rmk/` | RMK project for the RP2040 (no bootloader to add: the RP2040's boot ROM takes the `.uf2` over USB) |
| `publish.py` | Copies the finished files into `../production/` and writes its README |
| `sanitize.py` | Pins the build timestamps in `build/` and `../production/` to a fixed instant so a rebuild from the same sources is byte-identical (run by `make publish`) |
| `lib/` | Footprints and 3D models: [kiswitch](https://github.com/kiswitch/kiswitch) (CC-BY-SA 4.0; the hotswap socket and stabilizer models in `lib/3dmodels/`, found through `KICAD6_3RD_PARTY`) and components from LCSC |
| `tools/` | Freerouting; [KeyV2](https://github.com/rsheldiii/KeyV2) (GPL-3.0, parametric keycaps, pinned commit 19f0d2f) |
| `assets/` | Poly Haven CC0 assets of the desk scene (downloaded by `case/fetch_assets.py`) |

## Tools

- KiCad 10 in `~/Applications/KiCad` (its Python runs the `pcb/` scripts)
- Java (Homebrew `openjdk`) for Freerouting
- `.venv` (Python 3.12 with build123d) for the case
- Rust (target `thumbv6m-none-eabi`), rmkit, cargo-make, flip-link for the firmware
- Google Chrome for the layout preview (`render.sh`)
- Blender 5.1 or later in `/Applications/Blender.app` for the renders (`case/render.py`, run headless by
  `make renders`)
- OpenSCAD with the Manifold backend (Homebrew `openscad@snapshot`) for the KeyV2 keycaps
