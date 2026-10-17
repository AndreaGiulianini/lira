/* Minimal libc header for the C part of the BLE crypto (p256-cortex-m4): Homebrew's arm-none-eabi-gcc has no
 * newlib. The functions themselves come from Rust's compiler_builtins at link time. */
#pragma once
#include <stddef.h>
void *memcpy(void *dst, const void *src, size_t n);
void *memmove(void *dst, const void *src, size_t n);
void *memset(void *dst, int c, size_t n);
int memcmp(const void *a, const void *b, size_t n);
