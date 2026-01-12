#!/usr/bin/env python3
"""
Simple model extractor that doesn't require PyTorch

Extracts and displays model information from COM files.
For full extraction to .pt format, use extract_model.py (requires PyTorch).
"""

import sys
import struct
import json


def unpack_2bit_weights(data: bytes, count: int) -> list:
    """Unpack 2-bit weights from bytes (4 per byte, LSB first)"""
    weights = []
    byte_idx = 0

    for i in range(count):
        if i % 4 == 0:
            if byte_idx >= len(data):
                break
            packed = data[byte_idx]
            byte_idx += 1

        # Extract 2 bits
        val = packed & 0x03
        packed >>= 2

        # Map back: 0→-2, 1→-1, 2→0, 3→+1
        weight = val - 2
        weights.append(weight)

    return weights[:count]


def extract_charset_heuristic(data: bytes) -> str:
    """Extract charset by finding printable ASCII sequence followed by 0x00"""
    for i in range(len(data) - 64):
        candidate = []
        j = i
        while j < len(data) and j < i + 100:
            c = data[j]
            if c == 0:  # EOS marker
                if len(candidate) >= 60:  # Reasonable charset size
                    return ''.join(candidate) + '\x00'
                break
            elif 32 <= c <= 126:  # Printable ASCII
                candidate.append(chr(c))
                j += 1
            else:
                break

    return None


def guess_architecture(data_size: int) -> list:
    """Guess model architecture based on file size"""
    if data_size > 45000:
        return [256, 192, 128, 64]
    elif data_size > 35000:
        return [256, 128, 64]
    elif data_size > 25000:
        return [256, 96, 64]
    else:
        return [256, 64]


def analyze_com_file(com_file: str, architecture: list = None, show_weights: bool = False):
    """Analyze COM file and display model information"""

    print(f"Analyzing {com_file}...")
    with open(com_file, 'rb') as f:
        data = f.read()

    print(f"File size: {len(data)} bytes ({len(data)/1024:.1f} KB)")

    # Extract charset
    print("\n=== CHARSET ===")
    charset = extract_charset_heuristic(data)

    if not charset:
        charset = " !?,.'-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdefghijklmnopqrstuvwxyz" + '\x00'
        print("Using default charset (could not auto-detect)")

    charset_size = len(charset)
    print(f"Size: {charset_size} characters")
    print(f"Characters: {repr(charset[:-1])}")
    print(f"EOS marker: \\x00")

    # Architecture
    print("\n=== ARCHITECTURE ===")
    if architecture is None:
        architecture = guess_architecture(len(data))
        print("Auto-detected (may not be accurate):")
    else:
        print("User-specified:")

    print(f"  {' → '.join(map(str, architecture))}")

    num_layers = len(architecture) - 1
    print(f"Layers: {num_layers}")

    # Calculate expected sizes
    print("\n=== WEIGHT DATA ===")
    weight_sizes = []
    bias_sizes = []
    total_params = 0

    for i in range(num_layers):
        m, n = architecture[i+1], architecture[i]
        weight_count = m * n
        weight_bytes = (weight_count + 3) // 4  # Packed 2-bit
        bias_bytes = m * 2  # 16-bit signed

        weight_sizes.append(weight_bytes)
        bias_sizes.append(bias_bytes)
        total_params += weight_count + m

        print(f"Layer {i+1}: {n} → {m}")
        print(f"  Weights: {weight_count:,} params, {weight_bytes:,} bytes (packed)")
        print(f"  Biases:  {m:,} params, {bias_bytes:,} bytes")

    total_weight_bytes = sum(weight_sizes)
    total_bias_bytes = sum(bias_sizes)

    print(f"\nTotal parameters: {total_params:,}")
    print(f"Total weight data: {total_weight_bytes:,} bytes")
    print(f"Total bias data: {total_bias_bytes:,} bytes")
    print(f"Total model data: {total_weight_bytes + total_bias_bytes:,} bytes")

    # Estimate code size
    code_size = len(data) - total_weight_bytes - total_bias_bytes
    print(f"\nEstimated code size: {code_size:,} bytes ({code_size/1024:.1f} KB)")

    # Try to locate and extract a sample
    if show_weights:
        print("\n=== WEIGHT SAMPLE ===")
        # Find potential weight data near end
        search_start = len(data) - (total_weight_bytes + total_bias_bytes) - 1000
        search_start = max(0, search_start)

        # Show first layer weights (sample)
        offset = search_start
        weight_bytes = weight_sizes[0]
        sample_size = min(32, architecture[1] * architecture[0])  # First 32 weights

        print(f"Attempting to extract first {sample_size} weights from layer 1...")
        print(f"Reading from offset {offset} (0x{offset:04X})")

        if offset + weight_bytes <= len(data):
            weight_data = data[offset:offset + min(weight_bytes, 8)]  # First 8 bytes = 32 weights
            weights = unpack_2bit_weights(weight_data, sample_size)

            print(f"Sample weights: {weights[:16]}")
            print(f"Weight distribution:")
            from collections import Counter
            dist = Counter(weights)
            for w in [-2, -1, 0, 1]:
                count = dist.get(w, 0)
                pct = 100 * count / len(weights)
                print(f"  {w:+2d}: {count:3d} ({pct:5.1f}%)")

    return {
        'file_size': len(data),
        'charset_size': charset_size,
        'charset': charset,
        'architecture': architecture,
        'num_layers': num_layers,
        'total_params': total_params,
        'weight_bytes': total_weight_bytes,
        'bias_bytes': total_bias_bytes,
    }


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='Analyze Z80 COM file and display model information',
        epilog='For full extraction to .pt file, use extract_model.py (requires PyTorch)'
    )
    parser.add_argument('com_file', help='Input .COM file')
    parser.add_argument('--arch', '-a', type=str, default=None,
                        help='Architecture as comma-separated sizes (e.g., "256,192,128,64")')
    parser.add_argument('--weights', '-w', action='store_true',
                        help='Show weight samples')
    parser.add_argument('--json', '-j', action='store_true',
                        help='Output as JSON')

    args = parser.parse_args()

    # Parse architecture if provided
    architecture = None
    if args.arch:
        try:
            architecture = [int(x.strip()) for x in args.arch.split(',')]
        except ValueError:
            print(f"ERROR: Invalid architecture format: {args.arch}")
            print("Use format: 256,192,128,64")
            sys.exit(1)

    info = analyze_com_file(args.com_file, architecture, args.weights)

    if args.json:
        # Output JSON for programmatic use
        print("\n" + json.dumps(info, indent=2))
