# Lira — everything is generated from layout.py.
#   make / make all                    the whole pipeline (steps: see `all:` below)
#   make <step>                        one step, e.g. make pcb
# Working files: build/ ; finished files: ../production/ (written by publish.py).
KICAD ?= $(HOME)/Applications/KiCad/KiCad.app/Contents
KPY   := $(KICAD)/Frameworks/Python.framework/Versions/3.9/bin/python3
KCLI  := $(KICAD)/MacOS/kicad-cli
JAVA  ?= /opt/homebrew/opt/openjdk/bin/java
FREEROUTING := tools/freerouting-2.4.1.jar
FREEROUTING_URL := https://github.com/freerouting/freerouting/releases/download/v2.4.1/freerouting-2.4.1.jar
FREEROUTING_SHA := 251101c3eeac22d7e7dfcf6796603279e5d1000283eb82d8f093780f7afc6aa9
BLENDER ?= /Applications/Blender.app/Contents/MacOS/Blender
RENDER_SAMPLES ?= 128
RENDER_SCALE ?= 100
PY    := .venv/bin/python
# Fixed build timestamp (NEUTRAL_DATE 00:00:00) so a rebuild from the same sources is byte-identical;
# see sanitize.py.
NEUTRAL_DATE ?= 2026-10-15
# every recipe runs with pipefail, so a script that fails behind `| grep` still stops make (set in SHELL: the make 3.81
# that comes with macOS ignores .SHELLFLAGS)
SHELL := /bin/bash -o pipefail
QUIET := 2>&1 | { grep -v -e "traits" -e "assert" -e "Debug: Adding duplicate" || true; }
# a step that fails leaves no half-written target behind (it would look up to date to the next make)
.DELETE_ON_ERROR:

B := build
PCB := $(B)/pcb/lira
JACK_MODEL := lib/lira.3dshapes/Jack_3.5mm_PJ-320D-4A.step

.PHONY: all layout pcb schematic verify check plate fab case firmware renders review publish sanitize commit clean

# the whole pipeline
all: layout pcb schematic verify check fab case firmware renders review publish

layout:
	python3 layout.py
	./render.sh $(B)/layout.svg $(B)/layout.png 820 320

# placement + nets (unrouted) and the Specctra file for the autorouter
$(PCB)-placed.kicad_pcb: layout.py paths.py mount.py pcb/gen_pcb.py pcb/electronics.py pcb/circuit.py
	$(KPY) pcb/gen_pcb.py $(QUIET)
	mv $(PCB).kicad_pcb $(PCB)-placed.kicad_pcb

# written by gen_pcb.py along with the placed board: the pin map and ports (schematic, firmware, plate, case) and the
# Specctra file
$(B)/pcb/interface.json $(PCB).dsn: $(PCB)-placed.kicad_pcb ;

# Freerouting (61 MB) is not in git: downloaded once and checked against its SHA-256
$(FREEROUTING):
	curl -sSL -o $@.part $(FREEROUTING_URL)
	echo "$(FREEROUTING_SHA)  $@.part" | shasum -a 256 -c - && mv $@.part $@

$(PCB).ses: $(PCB)-placed.kicad_pcb pcb/route.py | $(FREEROUTING)
	JAVA=$(JAVA) python3 pcb/route.py $(PCB).dsn $(PCB).ses

# import the routes, pour ground, refill zones -> final board
$(PCB).kicad_pcb: $(PCB).ses pcb/finish_pcb.py pcb/repair.py
	$(KPY) pcb/finish_pcb.py $(PCB)-placed.kicad_pcb $(PCB).ses $(PCB).kicad_pcb $(QUIET)

pcb: $(PCB).kicad_pcb
	$(KCLI) pcb drc --severity-error --exit-code-violations -o $(B)/pcb/drc.rpt $(PCB).kicad_pcb || \
		(grep -E "^\[|violations|unconnected" $(B)/pcb/drc.rpt | head -40; exit 1)
	@grep -E "violations|unconnected" $(B)/pcb/drc.rpt

# schematic from pcb/circuit.py + the pin map of the placed PCB; then KiCad's ERC, netlist, SVG and PDF
schematic: $(B)/pcb/interface.json
	$(KPY) pcb/gen_schematic.py $(QUIET)
	cd $(B)/sch && $(KCLI) sch export netlist --format kicadsexpr -o netlist.net lira.kicad_sch 2>&1 | { grep -v Fontconfig || true; }
	cd $(B)/sch && ($(KCLI) sch erc --severity-all --format report -o erc.rpt lira.kicad_sch 2>&1 | { grep -v Fontconfig || true; })
	@{ grep -E "^\[" $(B)/sch/erc.rpt || true; } | sed -E 's/\(.*//' | sort | uniq -c | sort -rn | head -5
	@grep -E "ERC messages" $(B)/sch/erc.rpt
	@grep -q "Errors 0 " $(B)/sch/erc.rpt || (echo "ERC found errors: $(B)/sch/erc.rpt"; exit 1)
	cd $(B)/sch && $(KCLI) sch export svg --no-background-color -o svg lira.kicad_sch 2>&1 | { grep -v Fontconfig || true; }
	cd $(B)/sch && $(KCLI) sch export pdf -o lira-schematic.pdf lira.kicad_sch 2>&1 | { grep -v Fontconfig || true; }

# circuit.py == PCB == schematic, pin by pin; writes $(B)/netlist.json
verify: $(PCB).kicad_pcb $(B)/sch/netlist.net
	$(KPY) pcb/verify_netlist.py 2>&1 | { grep -v -e traits -e assert -e 'Debug:' || true; } > $(B)/verify-report.txt; \
		r=$${PIPESTATUS[0]}; cat $(B)/verify-report.txt; exit $$r

# independent checks of the circuit against the datasheets (pcb/check_circuit.py, written separately)
check: $(B)/netlist.json
	python3 pcb/check_circuit.py $(B)/netlist.json > $(B)/check-report.txt; r=$$?; grep -E "FAIL|WARN|SKIP|[Ss]ummary|PASS=|passed" $(B)/check-report.txt; exit $$r

plate: $(B)/pcb/interface.json
	$(KPY) pcb/gen_plate.py $(QUIET)

# files to upload to JLCPCB: gerbers+drill zip, BOM, CPL; plate gerbers + DXF
fab: pcb plate
	rm -rf $(B)/jlcpcb && mkdir -p $(B)/jlcpcb/pcb-gerbers $(B)/jlcpcb/plate-gerbers
	$(KCLI) pcb export gerbers --use-drill-file-origin -o $(B)/jlcpcb/pcb-gerbers/ \
		-l F.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts $(PCB).kicad_pcb >/dev/null
	$(KCLI) pcb export drill --drill-origin plot --excellon-separate-th -o $(B)/jlcpcb/pcb-gerbers/ $(PCB).kicad_pcb >/dev/null
	cd $(B)/jlcpcb/pcb-gerbers && zip -q ../lira-pcb-gerbers.zip *
	$(KPY) pcb/jlc_export.py $(PCB).kicad_pcb $(B)/jlcpcb $(QUIET)
	$(KCLI) pcb export gerbers -o $(B)/jlcpcb/plate-gerbers/ -l Edge.Cuts,F.Mask,B.Mask $(B)/plate/plate.kicad_pcb >/dev/null
	$(KCLI) pcb export drill -o $(B)/jlcpcb/plate-gerbers/ $(B)/plate/plate.kicad_pcb >/dev/null
	cd $(B)/jlcpcb/plate-gerbers && zip -q ../lira-plate-gerbers.zip *
	$(KCLI) pcb export dxf --mode-single --output-units mm -l Edge.Cuts -o $(B)/jlcpcb/plate.dxf $(B)/plate/plate.kicad_pcb >/dev/null

# case, 3D-printable plate (case/gen_plate_print.py) + test fit against the final PCB and plate
# (case/check_fit.py; report in $(B)/case/check-fit.txt)
case: $(PCB).kicad_pcb plate
	$(KPY) pcb/export_parts.py $(QUIET)
	$(PY) case/gen_case.py
	$(PY) case/gen_plate_print.py
	$(PY) case/check_fit.py | { grep -E "^(FAIL|WARN)|FAIL, " || true; }

# RMK firmware: keyboard.toml + vial.json from layout.py and the PCB pin map, then the .uf2 to drag onto the board
CARGO_PATH := PATH=$(HOME)/.cargo/bin:/opt/homebrew/opt/rustup/bin:/opt/homebrew/bin:$$PATH
# (keyboard.toml and vial.json from build/firmware/ are copied into the RMK project before building)
firmware: layout $(B)/pcb/interface.json
	python3 firmware/gen_firmware.py
	test -d firmware/rmk || $(CARGO_PATH) rmkit create --keyboard-toml-path $(B)/firmware/keyboard.toml \
		--vial-json-path $(B)/firmware/vial.json --target-dir firmware/rmk
	cp $(B)/firmware/keyboard.toml $(B)/firmware/vial.json firmware/rmk/
	cd firmware/rmk && $(CARGO_PATH) cargo make uf2 --release
	cp firmware/rmk/lira.uf2 $(B)/firmware/lira.uf2

# pictures of the assembled keyboard and of the bare PCB, rendered with Blender Cycles (case/render.py); the PCB and
# the plate go to Blender as GLB with every 3D model, keycaps and switches are meshed by case/render_parts.py
# (keycaps: KeyV2 in tools/ run by OpenSCAD; switch: kiswitch MX model). Then the desk scene (case/render_desk.py),
# with CC0 assets from Poly Haven downloaded once into assets/ (case/fetch_assets.py).
renders: $(PCB).kicad_pcb $(JACK_MODEL)
	mkdir -p $(B)/img $(B)/render
	test -f tools/KeyV2/includes.scad || git submodule update --init tools/KeyV2
	python3 case/fetch_assets.py
	KCLI=$(KCLI) $(PY) case/render_parts.py
	$(BLENDER) -b --factory-startup --python-exit-code 1 -P case/render.py -- $(B) $(RENDER_SAMPLES) $(RENDER_SCALE) 2>&1 | \
		{ grep -E "^(wrote|ERROR|Error)|^Traceback|Error:" || true; }
	$(BLENDER) -b --factory-startup --python-exit-code 1 -P case/render_desk.py -- $(B) $(RENDER_SAMPLES) $(RENDER_SCALE) \
		2>&1 | { grep -E "^(wrote|ERROR|Error)|^Traceback|Error:" || true; }

# the headset jack's 3D model (KiCad has none): made once, again only when its script changes
$(JACK_MODEL): case/jack_model.py
	$(PY) case/jack_model.py

# images and files for a human design review (pcb/review_package.py), published in ../production/review/
review: $(PCB).kicad_pcb $(JACK_MODEL)
	KCLI=$(KCLI) python3 pcb/review_package.py

# copy the finished files into ../production/ with readable names, plus its README, then pin the build
# timestamps for a reproducible result (see sanitize.py)
publish:
	python3 publish.py
	NEUTRAL_DATE=$(NEUTRAL_DATE) python3 sanitize.py --mtime ../production

# pin the build timestamps in build/, ../production/ and the generated 3D asset (run inside publish)
sanitize:
	NEUTRAL_DATE=$(NEUTRAL_DATE) python3 sanitize.py $(B) lib/lira.3dshapes
	NEUTRAL_DATE=$(NEUTRAL_DATE) python3 sanitize.py --mtime ../production

# commit with a fixed, deterministic date; use: make commit m="message"
commit:
	git add -A
	GIT_AUTHOR_DATE="$(NEUTRAL_DATE)T00:00:00" GIT_COMMITTER_DATE="$(NEUTRAL_DATE)T00:00:00" \
		git commit -m "$(m)"
	git reflog expire --expire=now --all
	git gc --prune=now --quiet

clean:
	rm -rf $(B)
