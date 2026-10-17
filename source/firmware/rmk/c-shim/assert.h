/* Minimal assert for freestanding builds: a failed check stops the CPU instead of being ignored. */
#pragma once
#define assert(e) ((e) ? (void)0 : __builtin_trap())
