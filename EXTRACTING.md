# Extracting Models from Prebuilt COM Files

Yes, you can extract trained models from prebuilt `.COM` files! The weights and biases are embedded as data in the binary.

## Tools

### Quick Analysis: `extract_model_simple.py`

Analyze a COM file without needing PyTorch:

```bash
./extract_model_simple.py GUESS.COM
```

Shows:
- Charset (character set)
- Architecture (layer sizes)
- Parameter counts
- Weight/bias data sizes
- Code size estimate

**Example output:**
```
File size: 38951 bytes (38.0 KB)
Charset: 70 characters
Architecture: 256 → 128 → 64
Total parameters: 41,152
Total model data: 10,624 bytes
Estimated code size: 27.7 KB
```

**Options:**
```bash
# Show weight samples
./extract_model_simple.py GUESS.COM --weights

# Specify architecture if auto-detection is wrong
./extract_model_simple.py GUESS.COM --arch "256,192,128,64"

# Output as JSON
./extract_model_simple.py GUESS.COM --json
```

### Full Extraction: `extract_model.py`

Extract to PyTorch `.pt` file (requires PyTorch):

```bash
./extract_model.py GUESS.COM --output extracted.pt
```

This creates a `.pt` checkpoint file compatible with `feedme.py`, `buildz80com.py`, and `buildz80tap.py`.

**Options:**
```bash
# Specify architecture
./extract_model.py GUESS.COM --arch "256,128,64" -o model.pt

# Extract and rebuild for different platform
./extract_model.py GUESS.COM -o model.pt
./buildz80tap.py -m model.pt -o GUESS.TAP  # Now for ZX Spectrum!
```

## How It Works

### COM File Structure

```
┌─────────────────────────┐ 0x0100
│ Z80 Machine Code        │ ~5-28 KB
│ (Inference engine)      │
├─────────────────────────┤
│ Variables & Buffers     │ ~1-2 KB
├─────────────────────────┤
│ Character Table         │ ~64 bytes
├─────────────────────────┤
│ Weights Layer 1 (packed)│ 2-bit, 4 per byte
├─────────────────────────┤
│ Biases Layer 1          │ 16-bit signed
├─────────────────────────┤
│ Weights Layer 2 (packed)│
├─────────────────────────┤
│ Biases Layer 2          │
├─────────────────────────┤
│ ...                     │
└─────────────────────────┘
```

### Weight Encoding

Weights are stored as **2-bit quantized values** packed 4 per byte:

```
Byte: 0b11_00_01_10

Bits [1:0] → 10 (2) → -2+2 = 0
Bits [3:2] → 01 (1) → -2+1 = -1
Bits [5:4] → 00 (0) → -2+0 = -2
Bits [7:6] → 11 (3) → -2+3 = +1
```

**Value mapping:**
- `00` → -2 (strong negative)
- `01` → -1 (weak negative)
- `10` →  0 (zero)
- `11` → +1 (positive)

### Biases

Stored as 16-bit signed little-endian integers:

```
Bytes: [0x20, 0x00] → 0x0020 → +32
Bytes: [0xE0, 0xFF] → 0xFFE0 → -32 (two's complement)
```

## Use Cases

### 1. Convert CP/M → ZX Spectrum

```bash
# Extract from CP/M COM file
./extract_model.py CHAT.COM -o model.pt

# Rebuild for ZX Spectrum
./buildz80tap.py -m model.pt -o CHAT.TAP
```

### 2. Analyze Prebuilt Models

```bash
# What's inside this COM file?
./extract_model_simple.py mystery.COM --weights
```

### 3. Port to Other Platforms

Once extracted to `.pt`, you can:
- Retrain with new data
- Build for different Z80 systems
- Export to other formats
- Analyze with Python/PyTorch tools

### 4. Archive Models

Save the `.pt` file separately from binaries:

```bash
./extract_model.py GUESS.COM -o guess_model_v1.pt

# Later, rebuild if needed
./buildz80com.py -m guess_model_v1.pt -o GUESS_NEW.COM
```

## Limitations

### Architecture Detection

Auto-detection guesses based on file size:

| File Size | Guessed Architecture |
|-----------|---------------------|
| > 45 KB   | 256 → 192 → 128 → 64 |
| > 35 KB   | 256 → 128 → 64 |
| > 25 KB   | 256 → 96 → 64 |
| < 25 KB   | 256 → 64 |

**If wrong, specify manually:**
```bash
./extract_model.py CHAT.COM --arch "256,192,128,64"
```

### Charset Detection

The extractor tries to find the character table automatically. If it fails, it uses a default charset.

**You may need to verify:**
- Check extracted charset matches expected
- Compare with original training data
- Rebuild and test if charset is critical

### Compressed/Obfuscated Files

If the COM file:
- Uses compression
- Has encrypted data
- Is significantly modified

...extraction may fail. This works best with files built by `buildz80com.py` or `buildfastz80com.py`.

## Verification

After extraction, verify the model works:

```bash
# Extract
./extract_model.py ORIGINAL.COM -o extracted.pt

# Rebuild
./buildz80com.py -m extracted.pt -o REBUILT.COM

# Compare sizes (should be similar)
ls -l ORIGINAL.COM REBUILT.COM

# Test functionality
cpm REBUILT.COM
```

## Advanced: Manual Extraction

If automatic extraction fails, you can manually locate the data:

### Find Weight Data

```bash
# View hex dump
hexdump -C CHAT.COM | tail -100

# Look for patterns:
# - Weights: packed bytes with ~50% zeros (0x00, 0x55, 0xAA, 0xFF common)
# - Biases: pairs of bytes, often small values
```

### Calculate Offsets

For architecture `256 → 128 → 64`:

```
Layer 1 weights: 256 * 128 / 4 = 8,192 bytes
Layer 1 biases:  128 * 2 = 256 bytes
Layer 2 weights: 128 * 64 / 4 = 2,048 bytes
Layer 2 biases:  64 * 2 = 128 bytes
Total: 10,624 bytes
```

Weights should be in last ~11 KB of file.

### Extract with Python

```python
import struct

with open('CHAT.COM', 'rb') as f:
    data = f.read()

# Find start (heuristic: file_size - model_data_size - 500)
offset = len(data) - 10624 - 500

# Extract layer 1 weights
layer1_weights = data[offset:offset+8192]

# Extract layer 1 biases
offset += 8192
layer1_biases = []
for i in range(128):
    bias = struct.unpack('<h', data[offset:offset+2])[0]
    layer1_biases.append(bias)
    offset += 2

# ... continue for other layers
```

## Further Reading

- [buildz80com.py](buildz80com.py) - See how weights are packed
- [feedme.py](feedme.py) - Model training and quantization
- [ZX-SPECTRUM.md](ZX-SPECTRUM.md) - Platform-specific builds

## License

Same as main project: MIT or Apache-2.0
