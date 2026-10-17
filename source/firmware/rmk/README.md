# RMK 

RMK is a feature-rich and easy-to-use keyboard firmware.

## uf2 support

If you’re using the Adafruit_nRF52_Bootloader (pre-installed on the nice!nano), you’re in luck! This bootloader supports the .uf2 firmware format, which eliminates the need for a debugging probe to flash your firmware. RMK uses the `cargo-make` tool to generate .uf2 firmware, with the generation process defined in the `Makefile.toml`.

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

   - Put your board into bootloader mode. A USB drive will appear on your computer.
   - Drag and drop the generated .uf2 firmware file onto the USB drive. The RMK firmware will be automatically flashed onto your microcontroller.

   For additional details on entering bootloader mode and flashing firmware, refer to the [nice!nano documentation](https://nicekeyboards.com/docs/nice-nano/getting-started#flashing-firmware-and-bootloaders)

### Tips for nRF52840

Most nice!nano compatible boards have bootloader with SoftDevice pre-flashed. Since v0.7.x, RMK will remove old SoftDevice Bluetooth stack and replace it with its own. So if you want to rollback to v0.6.x, or switch to firmwares that use SoftDevice stack(for example, zmk), you will need to [re-flash the bootloader](https://nicekeyboards.com/docs/nice-nano/troubleshooting#my-nicenano-seems-to-be-acting-up-and-i-want-to-re-flash-the-bootloader).

### Additional notes

RMK defaults to USB-priority mode if a USB cable is connected. After flashing, remember to disconnect the USB cable, or [switch to BLE-priority mode](https://rmk.rs/docs/features/wireless.html#multiple-profile-support) by pressing User6 (Switch Output: fn + R on Lira).

### Lira: the sound card follows the output

`src/audio_gate.rs` listens to RMK's connection status and drives P1.02, the enable pin of the load switch on the
sound card's 5 V: high (sound card on) only when the chosen output is USB and a USB host has set the keyboard up (or is
asleep); low in Bluetooth mode (also while the keyboard types over the cable because no Bluetooth host is
connected: fn + R selects USB), on a charger, and in the bootloader (a pull-down keeps the switch off). keyboard.toml
sets the subscriber slots of the connection status (`[event]`, written by `../gen_firmware.py`): the audio switch is
its only listener in this build (RMK adds its own slots when a display, rynk or a split is enabled). P1.02 uses
standard drive (`src/main.rs`; Nordic allows no more on this pin): switching off, it pulls the amplifier's EN down
through a Schottky from a 100 nF capacitor in under 0.1 ms, before the sound card's 5 V has fallen (about 0.2 ms), so
the amplifier is off before its source (no pop). While the host sleeps (USB suspend) the sound card stays powered and
enumerated: the codec suspends itself and its PDSW output switches the amplifier off through Q3 (hardware).

### Lira: low-battery cut-off

`src/battery_guard.rs` reads the battery measurements RMK takes every 30 s (`battery_adc.subs = 2` in `[event]`):
below 3.40 V twice in a row, with no USB power, it puts the nRF52840 into System OFF (every GPIO released first, so
the Caps Lock LED does not stay on). Plugging the cable in wakes it up (VBUS detection is a System OFF wake-up
source), as do the power switch (off and on) and the reset button.

### Lira: regulator

`dcdc_reg1 = true`: the E73 module has the REG1 DC/DC inductors inside (Ebyte datasheet p.7). The 32.768 kHz crystal
on the board is not used by this firmware: RMK 0.9 runs the Bluetooth stack on the internal RC oscillator (calibrated).
