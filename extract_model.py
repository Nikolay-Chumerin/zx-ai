#!/usr/bin/env python3
"""
Extract trained model from a prebuilt Z80 COM file

This reverse-engineers a .COM file to extract:
- Model architecture (layer sizes)
- Quantized weights (2-bit packed)
- Biases (16-bit signed integers)
- Character set

Outputs a PyTorch .pt checkpoint file compatible with feedme.py
"""

import sys
import struct
import torch
import numpy as np
from feedme import AutoregressiveModel


def unpack_2bit_weights(data: bytes, shape: tuple) -> np.ndarray:
    """Unpack 2-bit weights from bytes (4 per byte, LSB first)"""
    total_weights = shape[0] * shape[1]
    weights = []

    byte_idx = 0
    for i in range(total_weights):
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

    # Reshape to matrix
    weights = np.array(weights[:total_weights], dtype=np.int8)
    return weights.reshape(shape)


def find_pattern(data: bytes, pattern: bytes, start: int = 0) -> int:
    """Find byte pattern in data"""
    try:
        return data.index(pattern, start)
    except ValueError:
        return -1


def extract_charset_heuristic(data: bytes) -> str:
    """
    Extract charset using heuristic:
    Look for sequence of printable ASCII characters followed by 0x00 (EOS)
    """
    # Look for a table of printable ASCII (space to ~) followed by 0x00
    for i in range(len(data) - 64):
        # Check if we have a sequence of printable chars
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


def guess_architecture(data: bytes, charset_size: int = 64) -> list:
    """
    Guess model architecture by analyzing weight data patterns

    Look for sequences of bytes that match expected weight data sizes.
    For a layer of size M×N, we need ceil(M*N/4) bytes of packed weights.
    """
    # Try to detect based on data size
    # Rough heuristic: larger files = more layers/neurons
    data_size = len(data)

    if data_size > 45000:
        return [256, 192, 128, charset_size]
    elif data_size > 35000:
        return [256, 128, charset_size]
    elif data_size > 25000:
        return [256, 96, charset_size]
    else:
        return [256, charset_size]


def extract_model_from_com(com_file: str, output_file: str = 'extracted_model.pt',
                           architecture: list = None):
    """
    Extract model from COM file

    Args:
        com_file: Path to .COM file
        output_file: Output .pt file path
        architecture: Optional architecture [256, hidden..., 64], or None to auto-detect
    """

    print(f"Reading {com_file}...")
    with open(com_file, 'rb') as f:
        data = f.read()

    print(f"File size: {len(data)} bytes")

    # Extract charset
    print("\nExtracting charset...")
    charset = extract_charset_heuristic(data)

    if not charset:
        print("Could not auto-detect charset. Using default.")
        # Default charset from tinychat
        charset = " !?,.'-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdefghijklmnopqrstuvwxyz" + '\x00'

    charset_size = len(charset)
    print(f"Charset ({charset_size} chars): {repr(charset[:-1])} + EOS")

    # Guess or use provided architecture
    if architecture is None:
        print("\nAuto-detecting architecture...")
        architecture = guess_architecture(data, charset_size)

    print(f"Using architecture: {' → '.join(map(str, architecture))}")

    num_layers = len(architecture) - 1
    layer_sizes = architecture

    # Find weight data (heuristic: look near end of file)
    # Weights are stored after all the code and variables

    # Calculate expected sizes
    weight_sizes = []
    bias_sizes = []
    for i in range(num_layers):
        m, n = layer_sizes[i+1], layer_sizes[i]
        weight_bytes = (m * n + 3) // 4  # Packed 2-bit
        bias_bytes = m * 2  # 16-bit signed
        weight_sizes.append(weight_bytes)
        bias_sizes.append(bias_bytes)

    total_weight_bytes = sum(weight_sizes)
    total_bias_bytes = sum(bias_sizes)

    print(f"\nExpected data sizes:")
    print(f"  Total weights: {total_weight_bytes} bytes")
    print(f"  Total biases: {total_bias_bytes} bytes")
    print(f"  Total: {total_weight_bytes + total_bias_bytes} bytes")

    # Start searching from the end backwards
    # The structure is typically: WTS1, BIAS1, WTS2, BIAS2, ..., WTSn, BIASn

    # Find the start of weight data (rough heuristic)
    # Weight data should be near the end, leaving room for biases
    search_start = len(data) - (total_weight_bytes + total_bias_bytes) - 1000
    search_start = max(0, search_start)

    print(f"\nSearching for weight data starting at offset {search_start}...")

    # Try to find a reasonable starting point by looking for data patterns
    # Weights are packed bytes, biases are 16-bit little-endian

    best_offset = None
    min_remaining = float('inf')

    # Scan for potential weight data start
    for offset in range(search_start, len(data) - total_weight_bytes - total_bias_bytes):
        remaining = len(data) - offset
        expected = total_weight_bytes + total_bias_bytes

        if abs(remaining - expected) < min_remaining:
            min_remaining = abs(remaining - expected)
            best_offset = offset

    if best_offset is None:
        print("ERROR: Could not locate weight data in COM file")
        print("Try specifying architecture with --arch parameter")
        return False

    print(f"Found potential weight data at offset {best_offset} (0x{best_offset:04X})")
    print(f"Remaining bytes: {len(data) - best_offset}")

    # Extract weights and biases
    params = {}
    offset = best_offset

    for i in range(num_layers):
        layer_name = f'layer{i}'

        # Extract weights
        m, n = layer_sizes[i+1], layer_sizes[i]
        weight_bytes = weight_sizes[i]

        print(f"\nLayer {i+1}: {n} → {m}")
        print(f"  Weights: {weight_bytes} bytes at offset {offset} (0x{offset:04X})")

        if offset + weight_bytes > len(data):
            print(f"ERROR: Not enough data for weights")
            return False

        weight_data = data[offset:offset + weight_bytes]
        weights = unpack_2bit_weights(weight_data, (m, n))
        params[f'{layer_name}_weight'] = weights
        offset += weight_bytes

        # Extract biases
        bias_bytes = bias_sizes[i]
        print(f"  Biases: {bias_bytes} bytes at offset {offset} (0x{offset:04X})")

        if offset + bias_bytes > len(data):
            print(f"ERROR: Not enough data for biases")
            return False

        biases = np.zeros(m, dtype=np.int16)
        for j in range(m):
            biases[j] = struct.unpack('<h', data[offset:offset+2])[0]
            offset += 2

        params[f'{layer_name}_bias'] = biases

    print(f"\nExtracted {len(params)} parameter arrays")

    # Create model and load parameters
    print("\nCreating PyTorch model...")

    hidden_sizes = layer_sizes[1:-1]
    model = AutoregressiveModel(
        input_size=layer_sizes[0],
        hidden_sizes=hidden_sizes,
        num_chars=charset_size
    )

    # Convert numpy arrays to PyTorch tensors and load
    state_dict = {}
    layer_idx = 0
    for key in model.state_dict().keys():
        if 'weight' in key:
            layer_name = f'layer{layer_idx}'
            state_dict[key] = torch.from_numpy(params[f'{layer_name}_weight'].astype(np.float32))
        elif 'bias' in key:
            layer_name = f'layer{layer_idx}'
            state_dict[key] = torch.from_numpy(params[f'{layer_name}_bias'].astype(np.float32))
            layer_idx += 1
        elif 'max_accum_seen' in key:
            # Initialize overflow tracking buffer to 0
            state_dict[key] = torch.tensor(0.0)

    model.load_state_dict(state_dict)

    # Save checkpoint
    print(f"\nSaving model to {output_file}...")
    checkpoint = {
        'model_state': model.state_dict(),
        'architecture': {
            'input_size': layer_sizes[0],
            'hidden_sizes': hidden_sizes,
        },
        'charset': charset,
        'extracted_from': com_file,
    }

    torch.save(checkpoint, output_file)

    print(f"\n✓ Successfully extracted model!")
    print(f"  Architecture: {' → '.join(map(str, layer_sizes))}")
    print(f"  Charset: {charset_size} characters")
    print(f"  Output file: {output_file}")
    print(f"\nYou can now use this model with:")
    print(f"  ./buildz80com.py -m {output_file} -o NEW.COM")
    print(f"  ./buildz80tap.py -m {output_file} -o NEW.TAP")

    return True


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Extract model from Z80 COM file')
    parser.add_argument('com_file', help='Input .COM file')
    parser.add_argument('--output', '-o', default='extracted_model.pt',
                        help='Output .pt file (default: extracted_model.pt)')
    parser.add_argument('--arch', '-a', type=str, default=None,
                        help='Architecture as comma-separated sizes (e.g., "256,192,128,64")')

    args = parser.parse_args()

    # Parse architecture if provided
    architecture = None
    if args.arch:
        try:
            architecture = [int(x.strip()) for x in args.arch.split(',')]
            print(f"Using specified architecture: {architecture}")
        except ValueError:
            print(f"ERROR: Invalid architecture format: {args.arch}")
            print("Use format: 256,192,128,64")
            sys.exit(1)

    success = extract_model_from_com(args.com_file, args.output, architecture)

    sys.exit(0 if success else 1)
