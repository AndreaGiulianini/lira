MEMORY
{
  /* NOTE 1 K = 1 KiB = 1024 bytes */
  /* These values correspond to the nRF52840 WITH Adafruit nRF52 bootloader */
  FLASH : ORIGIN = 0x00001000, LENGTH = 1020K
  RAM : ORIGIN = 0x20000008, LENGTH = 255K

  /* These values correspond to the nRF52840 */
  /* FLASH : ORIGIN = 0x00000000, LENGTH = 1024K */
  /* RAM : ORIGIN = 0x20000000, LENGTH = 256K */
}

/* RMK keeps its storage (keymap changed from Vial, Bluetooth bonds) from 0xA0000 on (nRF52840 default): the program must
   stay below it. The Adafruit bootloader's reserved area starts at 0xED000. */
ASSERT(LOADADDR(.data) + SIZEOF(.data) <= 0xA0000, "the firmware reaches RMK's storage at 0xA0000")
