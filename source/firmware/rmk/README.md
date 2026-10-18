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

### Lira: the sound card's power (`src/sound_card.rs`)

The RP2040 switches the sound card: GPIO12 turns on its 5 V (the TPS22919 load switch, soft start), GPIO13 the
headphone amplifier (its EN, through 100 kΩ); both have pull-downs on the board, so the sound card stays off while the
RP2040 starts and in the boot ROM. GPIO29 (ADC3) reads VBUS through 22 kΩ / 27 kΩ. From RMK's USB state:

- the sound card goes on once the host has configured the keyboard and stays on while the host is asleep (USB
  suspend): switching the codec off would disconnect it from the hub, and the host would see it leave or be woken;
- the amplifier goes on 200 ms later, off in USB suspend (2.1 mA less), and off at once when VBUS starts to fall, the
  cable being pulled: VBUS is read every 50 µs while the amplifier is on, and a reading under 4.3 V or 0.35 V under its
  recent average turns it off before the codec's supply goes (no click in the headphones).

`main.rs` registers it with RMK (`#[register_processor(event)]`); `../gen_firmware.py` checks that the pins in
`main.rs` are the board's (`pcb/circuit.py`).

### Lira: the RMK patch and the async matrix

`../patch_rmk.py` builds RMK 0.9.0 with three changes (Cargo.toml's `[patch.crates-io]`): after each column, and
after waking on a key, the matrix waits until every row reads low (the RP2040's pull-downs are weak and the rows long:
without it a held key could also appear in the next column); USB asks for 100 mA instead of 450 mA. The `async_matrix`
feature makes the matrix wait for a key on the rows' interrupts when none is held, instead of scanning all the time:
the RP2040 sleeps between events, while typing and in USB suspend.
