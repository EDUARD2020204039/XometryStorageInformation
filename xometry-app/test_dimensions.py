#!/usr/bin/env python3
"""
Script de test pentru a verifica procesarea dimensiunilor
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

# Simulează datele de la extensia Chrome
test_part_data = {
    "part_id": "635528abcmm.STEP",
    "part_name": "635528abcmm.STEP",
    "quantity": 1,
    "dimensions": {
        "length": 100.0,
        "width": 50.0,
        "height": 25.0,
        "unit": "mm"
    },
    "weight": 0.891,
    "processes": ["Laser Cutting", "Waterjet Cutting"],
    "material": "Stainless Steel 316L",
    "image_url": "https://example.com/image.jpg"
}

print("=== DATE DE LA EXTENSIA CHROME ===")
print(f"Part ID: {test_part_data['part_id']}")
print(f"Dimensions: {test_part_data['dimensions']}")
print(f"Weight: {test_part_data['weight']}")

# Simulează procesarea din server
print("\n=== PROCESAREA ÎN SERVER ===")
dimensions = test_part_data.get("dimensions", {})
length = dimensions.get("length") if dimensions else test_part_data.get("length")
width = dimensions.get("width") if dimensions else test_part_data.get("width")
height = dimensions.get("height") if dimensions else test_part_data.get("height")
weight = test_part_data.get("weight")

print(f"Length: {length}")
print(f"Width: {width}")
print(f"Height: {height}")
print(f"Weight: {weight}")

# Verifică condițiile din template
print("\n=== VERIFICAREA CONDIȚIILOR DIN TEMPLATE ===")
has_dimensions = length or width or height or (weight and weight > 0)
print(f"Are dimensiuni: {has_dimensions}")

if has_dimensions:
    print("Se va afișa în template:")
    if length:
        print(f"  📏 L: {length:.1f}mm")
    if width:
        print(f"  📐 W: {width:.1f}mm")
    if height:
        print(f"  📏 H: {height:.1f}mm")
    if weight:
        print(f"  ⚖️ {weight:.2f}kg")
else:
    print("Se va afișa: N/A")

