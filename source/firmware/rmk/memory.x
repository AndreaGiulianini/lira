/* RP2040 with a 16 MB W25Q128JV QSPI flash (XIP at 0x10000000), as RMK 0.9's examples/use_config/rp2040.
   The first 256 bytes are boot2 (embassy-rp feature boot2-w25q080), which sets the flash up for XIP.
   RMK 0.9 opens the flash as 2 MB and keeps its storage (the keymap changed from Vial) from 1 MB on
   (rp2040 default [storage] start_addr = 0x100000): the assert below keeps the program out of it. */
MEMORY {
    BOOT2 : ORIGIN = 0x10000000, LENGTH = 0x100
    FLASH : ORIGIN = 0x10000100, LENGTH = 2048K - 0x100
    RAM   : ORIGIN = 0x20000000, LENGTH = 256K
}

EXTERN(BOOT2_FIRMWARE)

SECTIONS {
    /* ### Boot loader */
    .boot2 ORIGIN(BOOT2) :
    {
        KEEP(*(.boot2));
    } > BOOT2
} INSERT BEFORE .text;

ASSERT(LOADADDR(.data) + SIZEOF(.data) <= 0x10100000, "the firmware reaches RMK's storage at 0x10100000")
