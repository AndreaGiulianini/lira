# RMK 

RMK is a feature-rich and easy-to-use keyboard firmware.

This project builds it for the wired Lira: an RP2040 with a 16 MB W25Q128JV flash and a 12 MHz crystal, USB only (set
up as RMK 0.9's `examples/use_config/rp2040`). `keyboard.toml` and `vial.json` are written by `../gen_firmware.py`
and copied here by `make firmware` in `source/`.

## uf2 support

The RP2040 has its UF2 bootloader in ROM: in boot mode it shows up as a USB drive called RPI-RP2, so no debugging probe
is needed to flash the firmware. RMK uses the `cargo-make` tool to generate .uf2 firmware, with the generation process
defined in the `Makefile.toml` (UF2 family `rp2040`, loaded at 0x10000000 with the flash's boot2 in front).

Follow these steps to generate and flash the .uf2 firmware with RMK:

1. Get `cargo-make` tool:
   ```shell
   cargo install --force cargo-make
   ```
2. Compile RMK and generates .uf2 firmware:
   ```shell
   cargo make uf2 --release
   ```
3. Flash

   - Put your board into boot mode. The RPI-RP2 drive will appear on your computer:
     - first time: a board with a blank flash starts in boot mode by itself, just plug the cable in;
     - with the firmware running: fn + Esc (`Bootloader`, on release; Vial's "reboot to bootloader" does the same);
     - always: hold BOOT while plugging the cable in (or hold BOOT and press RESET).
   - Drag and drop `lira.uf2` onto the drive. The RP2040 writes it and restarts into the keyboard.

`cargo run --release` flashes through an SWD probe instead (probe-rs, `.cargo/config.toml`).

### Storage

RMK keeps the keymap changed from Vial in the flash from 1 MB on (RMK's rp2040 default, `[storage] start_addr =
0x100000`); `memory.x` makes the link fail if the program ever grows into it. A new build of RMK starts again from the
keymap of `keyboard.toml` (RMK resets its storage when the build hash changes).
