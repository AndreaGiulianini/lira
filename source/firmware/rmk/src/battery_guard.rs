//! Low-battery cut-off: when the cell reads below 3.40 V twice in a row (RMK samples it every 30 s) and there is no
//! USB power, the nRF52840 goes to System OFF, so a flat cell is not drained further (the cell's own protection then
//! never has to step in). Plugging the cable in wakes it up (VBUS detection is a System OFF wake-up source, nRF52840
//! PS 5.3.3) and the charger starts; the power switch (off and on again) or the reset button also restart it.

use embassy_nrf::pac;
use rmk::event::BatteryAdcEvent;
use rmk::macros::processor;

/// Cut-off voltage of the cell, in mV: about 5 % of a Li-Po's charge left, above its protection's 2.5-3.0 V.
const CUTOFF_MV: u32 = 3400;
/// Readings in a row below the cut-off before switching off (rides through one dip during a radio burst).
const READINGS: u8 = 2;

/// ADC counts -> cell voltage in mV. SAADC defaults (gain 1/6, 0.6 V reference, 12 bits): 1137.8 counts per volt
/// at the pin, which sees half the cell through the 10M / 10M divider: 568.9 counts per volt of the cell.
pub fn cell_mv(counts: u16) -> u32 {
    u32::from(counts) * 10_000 / 5_689
}

#[processor(subscribe = [BatteryAdcEvent])]
pub struct BatteryGuard {
    low: u8,
}

impl BatteryGuard {
    pub fn new() -> Self {
        Self { low: 0 }
    }

    async fn on_battery_adc_event(&mut self, event: BatteryAdcEvent) {
        let usb = pac::POWER.usbregstatus().read().vbusdetect();
        if cell_mv(event.0) < CUTOFF_MV && !usb {
            self.low = self.low.saturating_add(1);
        } else {
            self.low = 0;
        }
        if self.low >= READINGS {
            power_off();
        }
    }
}

/// Every GPIO back to its reset state (input, disconnected: the Caps Lock LED and the matrix columns would otherwise
/// keep their levels through System OFF), then System OFF. Wakes up only through a reset (VBUS, reset button).
fn power_off() -> ! {
    for (port, pins) in [(pac::P0, 32), (pac::P1, 16)] {
        for pin in 0..pins {
            port.pin_cnf(pin).write(|_| {}); // reset value: input, buffer disconnected
        }
    }
    embassy_nrf::power::set_system_off();
    loop {
        cortex_m::asm::wfe();
    }
}
