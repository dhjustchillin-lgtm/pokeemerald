#!/usr/bin/env python3
"""
metatile.py
Dumps metatile attributes from a pokeemerald checkout, adjusting for global secondary tileset offsets.

Usage:
    python metatile.py /path/to/pokeemerald
"""
import csv, os, re, struct, sys

def load_behavior_names(header):
    with open(header, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r'enum\s*\{(.*?)\};', text, re.S)
    if not m:
        raise RuntimeError("Couldn't find enum in metatile_behaviors.h")
    body = re.sub(r'/\*.*?\*/', '', m.group(1), flags=re.S)
    body = re.sub(r'//.*', '', body)
    value = 0
    out = {}
    for item in body.split(','):
        item = item.strip()
        if not item or not item.startswith("MB_"):
            continue
        if '=' in item:
            name, val = item.split('=', 1)
            name = name.strip()
            value = int(val.strip(), 0)
        else:
            name = item
        out[value] = name
        value += 1
    return out

def parse_attr(path):
    b = open(path, 'rb').read()
    for i in range(0, len(b), 2):
        raw = struct.unpack_from('<H', b, i)[0]
        yield i // 2, raw & 0xFF, (raw >> 8) & 0x1F, (raw >> 13) & 0x7, raw

def main():
    if len(sys.argv) != 2:
        print("Usage: python metatile.py <pokeemerald root>")
        return
    root = os.path.abspath(sys.argv[1])
    hdr = os.path.join(root, "include", "constants", "metatile_behaviors.h")
    tiles = os.path.join(root, "data", "tilesets")
    names = load_behavior_names(hdr)
    print("Loaded", len(names), "behavior names")
    
    with open("metatiles.csv", "w", newline="", encoding="utf8") as f:
        w = csv.writer(f)
        w.writerow(["Tileset", "MetatileID", "HexID", "BehaviorID", "BehaviorName", "Terrain", "Flags", "RawHex"])
        
        for cur, _, files in os.walk(tiles):
            if "metatile_attributes.bin" not in files: 
                continue
            
            rel = os.path.relpath(cur, tiles).replace("\\", "/")
            
            # Primary tilesets cover 0-511. Secondary tilesets cover 512-1023.
            offset = 512 if "secondary" in rel.lower() else 0
            
            for mid, bid, t, fl, raw in parse_attr(os.path.join(cur, "metatile_attributes.bin")):
                global_mid = mid + offset
                w.writerow([
                    rel, 
                    global_mid, 
                    f"0x{global_mid:04X}", 
                    bid, 
                    names.get(bid, f"UNKNOWN_{bid}"), 
                    t, 
                    fl, 
                    f"0x{raw:04X}"
                ])
    print("Done.")

if __name__ == "__main__":
    main()
