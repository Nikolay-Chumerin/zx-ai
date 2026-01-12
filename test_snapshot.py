#!/usr/bin/env python3
"""
Test Z80 snapshot - just prints "HELLO" without keyboard input
"""

import sys
sys.path.insert(0, '/home/user/zx-ai')

from libz80 import Z80Builder
from buildz80snapshot import create_z80_snapshot
from buildz80tap import build_tap_data, build_tap_header

# Simple test program
b = Z80Builder(org=0x8000)

# Print "HELLO WORLD" and stop
b.label('START')
b.di()

# Print each character
for c in "HELLO WORLD":
    b.ld_a_n(ord(c))
    b.rst(0x10)  # RST 10h = print char

# Print newline
b.ld_a_n(13)
b.rst(0x10)

# Infinite loop
b.label('DONE')
b.jr('DONE')

b.resolve()

# Build TAP
tap_data = bytearray()
header = build_tap_header("TEST", 0x8000, len(b.code))
tap_data.extend(header)
data = build_tap_data(b.code)
tap_data.extend(data)

with open('test_print.tap', 'wb') as f:
    f.write(tap_data)

# Build Z80 snapshot
create_z80_snapshot(b.code, 0x8000, 'test_print.z80')

print("\nCreated test files:")
print("  test_print.tap - Load with: LOAD \"\" CODE / RANDOMIZE USR 32768")
print("  test_print.z80 - Load with: fuse test_print.z80")
print("\nShould print 'HELLO WORLD' and then hang (infinite loop)")
