//! Audio power gate: drives the enable pin of the codec's 5 V load switch from RMK's connection status.
//! High = codec powered (USB mode), low = codec off (BLE mode, no host, charger only).

use embassy_nrf::gpio::Output;
use rmk::event::{ConnectionStatus, ConnectionStatusChangeEvent, ConnectionType};
use rmk::macros::processor;
use rmk::types::connection::UsbState;

/// Audio is allowed only when the user-selected output is USB *and* a USB host has configured the keyboard.
/// `Suspended` (host asleep) keeps audio on so the codec does not re-enumerate on every host sleep/wake.
pub fn audio_allowed(s: &ConnectionStatus) -> bool {
    let usb_up = matches!(s.usb, UsbState::Configured | UsbState::Suspended);
    usb_up && s.preferred == ConnectionType::Usb && s.decide_active() == Some(ConnectionType::Usb)
}

#[processor(subscribe = [ConnectionStatusChangeEvent])]
pub struct AudioGate {
    pin: Output<'static>,
}

impl AudioGate {
    /// `pin` must be created low (codec off) - the external pull-down keeps it off before this runs.
    pub fn new(pin: Output<'static>) -> Self {
        Self { pin }
    }

    async fn on_connection_status_change_event(&mut self, event: ConnectionStatusChangeEvent) {
        if audio_allowed(&event.0) {
            self.pin.set_high();
        } else {
            self.pin.set_low();
        }
    }
}
