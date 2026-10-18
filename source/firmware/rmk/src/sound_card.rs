//! Sound card power, from RMK's USB state and from VBUS:
//!   GPIO12 (AUD_EN)  the TPS22919 load switch: the sound card's 5 V (codec and amplifier), 100k pull-down on the board;
//!   GPIO13 (AMP_ON)  the headphone amplifier's EN, through 100k (1M pull-down on the board);
//!   GPIO29 (ADC3)    VBUS through 22k / 27k (0.551 x VBUS), 1 nF.
//!
//! - The sound card is on once the host has configured the keyboard, and stays on while the host is asleep (USB
//!   suspend): switching the codec off would disconnect it from the hub, and the host would see it leave or be woken.
//! - The amplifier goes on 200 ms after the sound card (its supply's soft start and the codec's start-up), off in USB
//!   suspend (2.1 mA of the suspend budget) and off at once when VBUS starts to fall - the cable being pulled - so it
//!   is off before the codec's supply goes and the codec's outputs, which then step, never reach the headphones.
//! - While the amplifier is on, VBUS is read every 50 us (one ADC reading takes 2 us); unplugged, VBUS falls at about
//!   4 mV/us (~0.1 A out of ~25 uF), so the amplifier is off within ~0.3 V of the fall. Otherwise every 10 ms.
//! A fall is VBUS below 4.3 V, or 0.35 V below its recent average (a host port may sit at 4.4-5.25 V); VBUS is good
//! again after 100 ms above 4.5 V.

use rmk::embassy_futures::select::{select, Either};
use embassy_rp::adc::{Adc, Blocking, Channel};
use embassy_rp::gpio::Output;
use embassy_time::{Duration, Instant, Timer};
use rmk::core_traits::Runnable;
use rmk::event::{ConnectionStatusChangeEvent, EventSubscriber, SubscribableEvent};
use rmk::processor::Processor;
use rmk::types::connection::UsbState;

/// VBUS in mV from a 12-bit reading: 3.3 V full scale, divider 27k / (22k + 27k).
fn vbus_mv(raw: u16) -> u32 {
    raw as u32 * 3300 * 49 / (4095 * 27)
}

const FLOOR_MV: u32 = 4300;
const DROP_MV: u32 = 350;
const GOOD_MV: u32 = 4500;
const GOOD_FOR: Duration = Duration::from_millis(100);
const AMP_DELAY: Duration = Duration::from_millis(200);
const FAST: Duration = Duration::from_micros(50);
const SLOW: Duration = Duration::from_millis(10);

pub struct SoundCard {
    aud_en: Output<'static>,
    amp_on: Output<'static>,
    adc: Adc<'static, Blocking>,
    vbus: Channel<'static>,
    usb: UsbState,
    /// VBUS good since (None: not good, or fell)
    good_since: Option<Instant>,
    vbus_ok: bool,
    avg_mv: u32,
    aud_since: Option<Instant>,
}

impl SoundCard {
    /// Both pins must be created low (sound card off): the board's pull-downs keep them off before this runs.
    pub fn new(aud_en: Output<'static>, amp_on: Output<'static>, adc: Adc<'static, Blocking>, vbus: Channel<'static>) -> Self {
        Self { aud_en, amp_on, adc, vbus, usb: UsbState::Disabled, good_since: None, vbus_ok: false, avg_mv: 0, aud_since: None }
    }

    fn read_vbus(&mut self) -> u32 {
        self.adc.blocking_read(&mut self.vbus).map(vbus_mv).unwrap_or(0)
    }

    /// Reads VBUS and updates `vbus_ok`; a fall turns the amplifier off before anything else.
    fn watch_vbus(&mut self) {
        let mv = self.read_vbus();
        let now = Instant::now();
        if self.vbus_ok {
            if mv < FLOOR_MV || mv + DROP_MV < self.avg_mv {
                self.amp_on.set_low();
                self.vbus_ok = false;
                self.good_since = None;
            } else {
                self.avg_mv = (self.avg_mv * 63 + mv) / 64; // ~3 ms at 50 us, ~0.6 s at 10 ms
            }
        } else if mv >= GOOD_MV {
            let since = *self.good_since.get_or_insert(now);
            if now - since >= GOOD_FOR {
                self.vbus_ok = true;
                self.avg_mv = mv;
            }
        } else {
            self.good_since = None;
        }
    }

    /// Sets both pins from the USB state, VBUS and the time the sound card has been on.
    fn apply(&mut self) {
        let host = matches!(self.usb, UsbState::Configured | UsbState::Suspended);
        if host && self.vbus_ok {
            if self.aud_since.is_none() {
                self.aud_en.set_high();
                self.aud_since = Some(Instant::now());
            }
        } else {
            self.amp_on.set_low();
            self.aud_en.set_low();
            self.aud_since = None;
        }
        let settled = self.aud_since.is_some_and(|t| Instant::now() - t >= AMP_DELAY);
        if self.usb == UsbState::Configured && self.vbus_ok && settled {
            self.amp_on.set_high();
        } else {
            self.amp_on.set_low();
        }
    }
}

impl Processor for SoundCard {
    type Event = ConnectionStatusChangeEvent;

    fn subscriber() -> impl EventSubscriber<Event = Self::Event> {
        <ConnectionStatusChangeEvent as SubscribableEvent>::subscriber()
    }

    async fn process(&mut self, event: Self::Event) {
        self.usb = event.0.usb;
        self.apply();
    }

    /// The USB state's events, interleaved with the VBUS watch (fast while the amplifier is on).
    async fn process_loop(&mut self) -> ! {
        let mut sub = Self::subscriber();
        loop {
            let period = if self.amp_on.is_set_high() { FAST } else { SLOW };
            match select(Timer::after(period), sub.next_event()).await {
                Either::First(_) => {
                    self.watch_vbus();
                    self.apply();
                }
                Either::Second(event) => self.process(event).await,
            }
        }
    }
}

impl Runnable for SoundCard {
    async fn run(&mut self) -> ! {
        self.process_loop().await
    }
}
