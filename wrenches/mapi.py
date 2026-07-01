import sys
import os
import csv
import json
import re
import argparse
from io import BytesIO
from http.server import BaseHTTPRequestHandler, HTTPServer
from PIL import Image

# Global State Variables to anchor runtime properties across the local connection
CONFIG = {
    "root_dir": "",
    "map_name": "",
    "layout_id": "",
    "width": 20,
    "height": 20,
    "primary_tileset": "",
    "secondary_tileset": "",
    "map_bin_path": "",
    "border_bin_path": "",
    "layouts_json_path": "",
    "metatiles": [],
    "border_blocks": [],
    "allowed_tilesets": [],
    "secondary_offset": 512
}

def normalize_tileset_name(ts_name):
    if not ts_name: return ""
    if ts_name.startswith("gTileset_"): 
        ts_name = ts_name[len("gTileset_"):]
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', re.sub('(.)([A-Z][a-z]+)', r'\1_\2', ts_name)).lower()

def load_jasc_pal(pal_path):
    if not os.path.exists(pal_path):
        return [i for i in range(256) for _ in range(3)]
    with open(pal_path, 'r') as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]
    if not lines or lines[0] != "JASC-PAL":
        return [i for i in range(256) for _ in range(3)]
    num_colors = int(lines[2])
    palette = []
    for line in lines[3:3 + num_colors]:
        palette.extend(list(map(int, line.split())))
    if len(palette) < 768:
        palette += [0] * (768 - len(palette))
    return palette

def get_tileset_texture_bytes(tileset_name, palette_id="00"):
    ts_clean = normalize_tileset_name(tileset_name)
    img_path = os.path.join(CONFIG["root_dir"], "data", "tilesets", "primary", ts_clean, "tiles.png")
    pal_path = os.path.join(CONFIG["root_dir"], "data", "tilesets", "primary", ts_clean, "palettes", f"{palette_id}.pal")
    
    if not os.path.exists(img_path):
        img_path = os.path.join(CONFIG["root_dir"], "data", "tilesets", "secondary", ts_clean, "tiles.png")
        pal_path = os.path.join(CONFIG["root_dir"], "data", "tilesets", "secondary", ts_clean, "palettes", f"{palette_id}.pal")

    if not os.path.exists(pal_path):
        pal_path = re.sub(r"\d+\.pal$", "00.pal", pal_path)

    if not os.path.exists(img_path):
        empty_img = Image.new("RGB", (128, 256), (40, 40, 40))
        out = BytesIO()
        empty_img.save(out, format="PNG")
        return out.getvalue()

    try:
        palette = load_jasc_pal(pal_path)
        src_img = Image.open(img_path)
        src_img.putpalette(palette)
        src_img = src_img.convert("RGB")
        
        out = BytesIO()
        src_img.save(out, format="PNG")
        return out.getvalue()
    except Exception:
        empty_img = Image.new("RGB", (128, 256), (255, 0, 0))
        out = BytesIO()
        empty_img.save(out, format="PNG")
        return out.getvalue()

class PoorymapWebBackend(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_GET(self):
        if self.path.startswith("/?"):
            self.path = "/"

        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            
            csv_path = os.path.join(os.getcwd(), "metatiles.csv")
            behavior_map = []
            if os.path.exists(csv_path):
                try:
                    with open(csv_path, mode="r", encoding="utf-8") as f:
                        for r in csv.DictReader(f):
                            ts_base = r.get("Tileset", "unknown").split('/')[-1]
                            if ts_base in CONFIG["allowed_tilesets"]:
                                behavior_map.append({
                                    "id": int(r.get("MetatileID", 0)),
                                    "behavior": r.get("BehaviorName", "UNKNOWN"),
                                    "tileset": ts_base
                                })
                except Exception: pass

            html_template = """
            <!DOCTYPE html>
            <html>
            <head>
                <title>Poorymap 16x16 metatile calibration environment</title>
                <style>
                    body { background-color: #121212; color: #e0e0e0; font-family: 'Segoe UI', Tahoma, monospace; margin: 0; padding: 20px; display: flex; gap: 20px; height: 95vh; box-sizing: border-box; }
                    .pane { background: #1e1e1e; border: 1px solid #333; border-radius: 6px; padding: 15px; display: flex; flex-direction: column; overflow: hidden; }
                    #map-pane { flex: 2; }
                    #sidebar-pane { flex: 1; max-width: 480px; }
                    .grid-container { overflow: auto; background: #000; border: 1px solid #444; border-radius: 4px; padding: 5px; flex-grow: 1; position: relative; }
                    
                    .matrix { display: grid; gap: 1px; background-color: #2a2a2a; width: fit-content; }
                    
                    /* Main map viewport cells are now sized around 16x16 metatile blocks (scaled up 4x) */
                    .tile { width: 64px; height: 64px; background-color: #151515; cursor: pointer; user-select: none; border: 1px solid transparent; position: relative; overflow: hidden; display: block; }
                    .tile img { position: absolute; image-rendering: pixelated; transform-origin: top left; transform: scale(4); pointer-events: none; }
                    .tile:hover { border-color: #5bc0de; z-index: 10; }
                    .tile.active { border-color: #fff !important; box-shadow: inset 0 0 5px #fff; z-index: 11; }
                    .tile.selected-range { background-color: rgba(0, 180, 255, 0.3); border-color: #00b4ff; }
                    
                    .toolbar { display: flex; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
                    button { background: #2c3e50; color: #fff; border: 1px solid #34495e; padding: 6px 12px; border-radius: 4px; cursor: pointer; font-family: monospace; font-size: 12px; }
                    button:hover { background: #34495e; }
                    
                    .meta-readout { background: #151515; padding: 10px; border-radius: 4px; border: 1px solid #2a2a2a; font-size: 12px; font-family: monospace; margin-top: 10px; line-height: 1.5; }
                    
                    .giant-sheet-box { overflow: auto; background: #050505; border: 2px solid #333; border-radius: 4px; flex-grow: 1; position: relative; user-select: none; }
                    .sheet-wrapper { position: relative; width: 512px; display: block; line-height: 0; }
                    .sheet-img { width: 512px; image-rendering: pixelated; display: block; margin: 0; padding: 0; }
                    
                    /* The red selector box targets a complete 16x16 metatile cell (64x64px layout bounds) */
                    #calibration-tracker {
                        position: absolute;
                        width: 64px;
                        height: 64px;
                        border: 2px solid #ff3333;
                        box-sizing: border-box;
                        background: rgba(255, 51, 51, 0.2);
                        cursor: grab;
                        z-index: 100;
                        box-shadow: 0 0 8px #ff3333;
                    }
                    #calibration-tracker:active { cursor: grabbing; }
                    .badge { background: #34495e; padding: 2px 6px; border-radius: 3px; font-size: 11px; font-weight: bold; color: #5bc0de; }
                </style>
                <script>
                    window.primaryHeightCalculated = 0;
                </script>
            </head>
            <body>

                <div class="pane" id="map-pane">
                    <div class="toolbar">
                        <button id="btn-save" onclick="saveToDisk()">Ctrl+S: Save</button>
                        <button id="btn-border" onclick="toggleBorderMode()">Toggle Border Layer (B)</button>
                        <button id="btn-select" onclick="toggleSelectionMode()">Selection Tool (S)</button>
                        <button id="btn-copy" onclick="copySelection()">Copy (C)</button>
                        <button id="btn-paste" onclick="pasteSelection()">Paste (V)</button>
                        <button id="btn-pal" onclick="togglePalette()">Palette (P)</button>
                        <span style="align-self: center; font-size:12px; margin-left:auto;" id="layer-indicator">Layer: Map Structure</span>
                    </div>
                    <div class="grid-container">
                        <div id="map-matrix" class="matrix"></div>
                    </div>
                </div>

                <div class="pane" id="sidebar-pane">
                    <h3>16x16 Metatile Atlas Inspector</h3>
                    
                    <div class="giant-sheet-box" id="giant-container">
                        <div class="sheet-wrapper" id="sheet-wrapper-el">
                            <div id="calibration-tracker"></div>
                            <img id="primary-sheet-view" class="sheet-img" src="/primary_tiles.png?pal=00" alt="Primary Blocks" onload="window.primaryHeightCalculated = this.clientHeight; updateReadout();">
                            <img id="secondary-sheet-view" class="sheet-img" src="/secondary_tiles.png?pal=00" alt="Secondary Blocks">
                        </div>
                    </div>
                    
                    <div class="meta-readout" id="readout-box">
                        Focus Grid Data Details...
                    </div>
                </div>

                <script>
                    const CONFIG = __CONFIG_DATA__;
                    const BEHAVIORS = __BEHAVIOR_DATA__;
                    
                    let state = {
                        borderMode: false,
                        selectionActive: false,
                        selectionStart: null,
                        cursorIdx: 0,
                        clipboard: null,
                        currentPalette: 0,
                        isDraggingTracker: false
                    };

                    function parseMetatile(val) {
                        return {
                            id: val & 0x03FF,
                            elevation: (val >> 10) & 0x0F,
                            hFlip: (val >> 14) & 0x01,
                            vFlip: (val >> 15) & 0x01
                        };
                    }
                    
                    function packMetatile(id, elev, hf, vf) {
                        return (id & 0x03FF) | ((elev & 0x0F) << 10) | ((hf & 0x01) << 14) | ((vf & 0x01) << 15);
                    }

                    function renderMatrixGrid() {
                        const grid = document.getElementById("map-matrix");
                        grid.innerHTML = "";
                        
                        let width = state.borderMode ? 2 : CONFIG.width;
                        let tiles = state.borderMode ? CONFIG.border_blocks : CONFIG.metatiles;
                        let padPal = String(state.currentPalette).padStart(2, '0');
                        
                        grid.style.gridTemplateColumns = `repeat(${width}, 64px)`;
                        
                        tiles.forEach((entry, idx) => {
                            let meta = parseMetatile(entry);
                            let cell = document.createElement("div");
                            cell.className = "tile";
                            cell.id = `tile-${idx}`;
                            
                            let isSecondary = meta.id >= CONFIG.secondary_offset;
                            let adjustedId = isSecondary ? (meta.id - CONFIG.secondary_offset) : meta.id;
                            
                            // 128px wide atlas / 16px metatiles = Exactly 8 metatiles per line row
                            let tilesPerRow = 8;
                            let blockX = (adjustedId % tilesPerRow) * 16;
                            let blockY = Math.floor(adjustedId / tilesPerRow) * 16;
                            let baseSrc = isSecondary ? "/secondary_tiles.png" : "/primary_tiles.png";
                            
                            let img = document.createElement("img");
                            img.src = `${baseSrc}?pal=${padPal}`;
                            img.style.left = `-${blockX * 4}px`;
                            img.style.top = `-${blockY * 4}px`;
                            cell.appendChild(img);
                            
                            if (idx === state.cursorIdx) cell.classList.add("active");
                            
                            if (state.selectionActive && state.selectionStart !== null) {
                                let cX = idx % width, cY = Math.floor(idx / width);
                                let sX = state.selectionStart % width, sY = Math.floor(state.selectionStart / width);
                                let curX = state.cursorIdx % width, curY = Math.floor(state.cursorIdx / width);
                                
                                if (cX >= Math.min(sX, curX) && cX <= Math.max(sX, curX) &&
                                    cY >= Math.min(sY, curY) && cY <= Math.max(sY, curY)) {
                                    cell.classList.add("selected-range");
                                }
                            }
                            
                            cell.onclick = () => {
                                state.cursorIdx = idx;
                                renderMatrixGrid();
                                updateReadout();
                            };
                            grid.appendChild(cell);
                        });
                    }

                    function updateReadout() {
                        let width = state.borderMode ? 2 : CONFIG.width;
                        let tiles = state.borderMode ? CONFIG.border_blocks : CONFIG.metatiles;
                        let activeTile = tiles[state.cursorIdx];
                        if (activeTile === undefined) return;
                        
                        let meta = parseMetatile(activeTile);
                        let isSecondary = meta.id >= CONFIG.secondary_offset;
                        let adjustedId = isSecondary ? (meta.id - CONFIG.secondary_offset) : meta.id;
                        
                        let cX = state.cursorIdx % width, cY = Math.floor(state.cursorIdx / width);
                        let padPal = String(state.currentPalette).padStart(2, '0');
                        
                        let tilesPerRow = 8;
                        let tilePixelSize = 64; // 16x16 metatiles scaled 4x
                        
                        let localX = (adjustedId % tilesPerRow) * tilePixelSize;
                        let localY = Math.floor(adjustedId / tilesPerRow) * tilePixelSize;
                        let displayY = localY;
                        
                        if (isSecondary) {
                            localY += window.primaryHeightCalculated || 0;
                        }

                        const tracker = document.getElementById("calibration-tracker");
                        if (tracker && !state.isDraggingTracker) {
                            tracker.style.left = `${localX}px`;
                            tracker.style.top = `${localY}px`;
                        }

                        document.getElementById("readout-box").innerHTML = `
                            <span style="color:#5bc0de; font-weight:bold;">=== CALIBRATION TELEMETRY ===</span><br>
                            <strong>Position Matrix:</strong> X: ${cX}, Y: ${cY}<br>
                            <strong>Decoded Metatile ID:</strong> ${meta.id} (00-indexed)<br>
                            <strong>Target Layer:</strong> ${isSecondary ? "Secondary Sheet" : "Primary Sheet"}<br>
                            <strong>Sheet Local Index:</strong> ${adjustedId}<br>
                            <strong>16x16 Coordinates:</strong> Col: ${adjustedId % tilesPerRow}, Row: ${Math.floor(adjustedId / tilesPerRow)}<br>
                            <strong>Atlas Offset Coordinates:</strong> X: ${localX}px, Y: ${displayY}px<br>
                            <strong>Active Palette Index:</strong> <span class="badge">${padPal}.pal</span>
                        `;
                    }

                    // Setup Mouse Drag Listeners on the Tracker Box overlay
                    const trackerEl = document.getElementById("calibration-tracker");
                    const wrapperEl = document.getElementById("sheet-wrapper-el");

                    trackerEl.addEventListener("mousedown", (e) => {
                        state.isDraggingTracker = true;
                        e.preventDefault();
                    });

                    window.addEventListener("mousemove", (e) => {
                        if (!state.isDraggingTracker) return;
                        
                        let rect = wrapperEl.getBoundingClientRect();
                        let rawX = e.clientX - rect.left;
                        let rawY = e.clientY - rect.top;
                        
                        // Snap selection values down cleanly onto 16x16 boundaries (64 CSS pixels block sizes)
                        let gridX = Math.floor(rawX / 64) * 64;
                        let gridY = Math.floor(rawY / 64) * 64;
                        
                        gridX = Math.max(0, Math.min(512 - 64, gridX));
                        gridY = Math.max(0, gridY);

                        trackerEl.style.left = `${gridX}px`;
                        trackerEl.style.top = `${gridY}px`;

                        let col = gridX / 64;
                        let row = gridY / 64;
                        let localIdx = (row * 8) + col; 
                        
                        let finalCalculatedId = localIdx;
                        let isSec = false;
                        
                        if (window.primaryHeightCalculated && gridY >= window.primaryHeightCalculated) {
                            let adjustedRow = (gridY - window.primaryHeightCalculated) / 64;
                            let secLocalIdx = (adjustedRow * 8) + col;
                            finalCalculatedId = secLocalIdx + CONFIG.secondary_offset;
                            isSec = true;
                        }

                        let tiles = state.borderMode ? CONFIG.border_blocks : CONFIG.metatiles;
                        let oldMeta = parseMetatile(tiles[state.cursorIdx]);
                        tiles[state.cursorIdx] = packMetatile(finalCalculatedId, oldMeta.elevation, oldMeta.hFlip, oldMeta.vFlip);

                        renderMatrixGrid();
                        
                        document.getElementById("readout-box").innerHTML = `
                            <span style="color:#ff3333; font-weight:bold;">--- LIVE DRAG CALIBRATION ---</span><br>
                            <strong>Hovering Metatile Col:</strong> ${col}, Row: ${row}<br>
                            <strong>Recalculated Local Index:</strong> ${isSec ? localIdx - CONFIG.secondary_offset : localIdx}<br>
                            <strong>Resulting Metatile Global ID:</strong> ${finalCalculatedId}<br>
                            <strong>Active Selection Grid Index:</strong> ${state.cursorIdx}<br>
                            <em>Release mouse to fix selection position.</em>
                        `;
                    });

                    window.addEventListener("mouseup", () => {
                        if (state.isDraggingTracker) {
                            state.isDraggingTracker = false;
                            renderMatrixGrid();
                            updateReadout();
                        }
                    });

                    function togglePalette() {
                        state.currentPalette = (state.currentPalette + 1) % 16;
                        renderMatrixGrid();
                        updateReadout();
                    }

                    function toggleBorderMode() {
                        state.borderMode = !state.borderMode;
                        state.cursorIdx = 0;
                        state.selectionActive = false;
                        document.getElementById("layer-indicator").innerText = state.borderMode ? "Layer: Border Blocks" : "Layer: Map Structure";
                        renderMatrixGrid();
                        updateReadout();
                    }

                    function toggleSelectionMode() {
                        state.selectionActive = !state.selectionActive;
                        state.selectionStart = state.selectionActive ? state.cursorIdx : null;
                        renderMatrixGrid();
                    }

                    function copySelection() {
                        if (!state.selectionActive || state.selectionStart === null) return;
                        let width = state.borderMode ? 2 : CONFIG.width;
                        let sX = state.selectionStart % width, sY = Math.floor(state.selectionStart / width);
                        let curX = state.cursorIdx % width, curY = Math.floor(state.cursorIdx / width);
                        let x1 = Math.min(sX, curX), x2 = Math.max(sX, curX);
                        let y1 = Math.min(sY, curY), y2 = Math.max(sY, curY);
                        let tiles = state.borderMode ? CONFIG.border_blocks : CONFIG.metatiles;
                        
                        state.clipboard = { w: x2 - x1 + 1, h: y2 - y1 + 1, blocks: [] };
                        for(let y=y1; y<=y2; y++) {
                            for(let x=x1; x<=x2; x++) {
                                state.clipboard.blocks.push(tiles[y * width + x]);
                            }
                        }
                        state.selectionActive = false;
                        renderMatrixGrid();
                    }

                    function pasteSelection() {
                        if (!state.clipboard) return;
                        let width = state.borderMode ? 2 : CONFIG.width;
                        let height = Math.ceil((state.borderMode ? CONFIG.border_blocks : CONFIG.metatiles).length / width);
                        let tiles = state.borderMode ? CONFIG.border_blocks : CONFIG.metatiles;
                        let startX = state.cursorIdx % width, startY = Math.floor(state.cursorIdx / width);
                        
                        for(let y=0; y<state.clipboard.h; y++) {
                            if (startY + y >= height) break;
                            for(let x=0; x<state.clipboard.w; x++) {
                                if (startX + x >= width) break;
                                tiles[(startY + y) * width + (startX + x)] = state.clipboard.blocks[y * state.clipboard.w + x];
                            }
                        }
                        renderMatrixGrid();
                        updateReadout();
                    }

                    function saveToDisk() {
                        fetch('/save', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: json.stringify({
                                metatiles: CONFIG.metatiles,
                                border_blocks: CONFIG.border_blocks
                            })
                        })
                        .then(res => res.json())
                        .then(data => alert(data.status));
                    }

                    window.addEventListener("keydown", (e) => {
                        let width = state.borderMode ? 2 : CONFIG.width;
                        let maxLen = (state.borderMode ? CONFIG.border_blocks : CONFIG.metatiles).length;
                        let height = Math.ceil(maxLen / width);
                        let cX = state.cursorIdx % width, cY = Math.floor(state.cursorIdx / width);
                        
                        if (e.key === "ArrowUp" && cY > 0) state.cursorIdx -= width;
                        else if (e.key === "ArrowDown" && cY < height - 1) state.cursorIdx += width;
                        else if (e.key === "ArrowLeft" && cX > 0) state.cursorIdx -= 1;
                        else if (e.key === "ArrowRight" && cX < width - 1) state.cursorIdx += 1;
                        else if (e.key.toLowerCase() === "s" && e.ctrlKey) { e.preventDefault(); saveToDisk(); return; }
                        else if (e.key.toLowerCase() === "s") { toggleSelectionMode(); return; }
                        else if (e.key.toLowerCase() === "c") { copySelection(); return; }
                        else if (e.key.toLowerCase() === "v") { pasteSelection(); return; }
                        else if (e.key.toLowerCase() === "b") { toggleBorderMode(); return; }
                        else if (e.key.toLowerCase() === "p") { togglePalette(); return; }
                        else return;
                        
                        renderMatrixGrid();
                        updateReadout();
                    });

                    renderMatrixGrid();
                </script>
            </body>
            </html>
            """.replace("__CONFIG_DATA__", json.dumps(CONFIG)).replace("__BEHAVIOR_DATA__", json.dumps(behavior_map))
            
            self.wfile.write(html_template.encode('utf-8'))

        elif "/primary_tiles.png" in self.path or "/secondary_tiles.png" in self.path:
            pal_match = re.search(r"pal=(\d+)", self.path)
            pal_id = pal_match.group(1) if pal_match else "00"
            target_ts = CONFIG["secondary_tileset"] if "secondary" in self.path else CONFIG["primary_tileset"]
            
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(get_tileset_texture_bytes(target_ts, pal_id))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/save":
            content_length = int(self.headers['Content-Length'])
            post_data = json.loads(self.rfile.read(content_length).decode('utf-8'))
            
            CONFIG["metatiles"] = post_data.get("metatiles", CONFIG["metatiles"])
            CONFIG["border_blocks"] = post_data.get("border_blocks", CONFIG["border_blocks"])
            
            try:
                with open(CONFIG["map_bin_path"], "wb") as f:
                    for entry in CONFIG["metatiles"]:
                        f.write(entry.to_bytes(2, byteorder='little'))
                        
                if os.path.exists(CONFIG["border_bin_path"]):
                    with open(CONFIG["border_bin_path"], "wb") as f:
                        for entry in CONFIG["border_blocks"]:
                            f.write(entry.to_bytes(2, byteorder='little'))
                
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "Changes written cleanly back to layout files!"}).encode('utf-8'))
                print("\n[SUCCESS] Local modifications flushed back to binary formats cleanly.")
            except Exception as e:
                self.send_response(500)
                self.end_headers()

def main():
    parser = argparse.ArgumentParser(description="Pokeemerald Full-Stack HTML Native Map Editor Portal")
    parser.add_argument("root_dir", help="Path location to the pokeemerald repository root folder")
    parser.add_argument("map_name", help="Unique context folder string for your targeted map layout name")
    args = parser.parse_args()

    CONFIG["root_dir"] = args.root_dir
    CONFIG["map_name"] = args.map_name
    CONFIG["layouts_json_path"] = os.path.join(args.root_dir, "data", "layouts", "layouts.json")

    map_json_path = os.path.join(args.root_dir, "data", "maps", args.map_name, "map.json")
    if not os.path.exists(map_json_path) or not os.path.exists(CONFIG["layouts_json_path"]):
        print("[ERROR] Required pokeemerald setup configuration files missing.")
        sys.exit(1)

    with open(map_json_path, "r", encoding="utf-8") as f:
        CONFIG["layout_id"] = json.load(f).get("layout", "")

    with open(CONFIG["layouts_json_path"], "r", encoding="utf-8") as f:
        for item in json.load(f).get("layouts", []):
            if item.get("id") == CONFIG["layout_id"]:
                CONFIG["width"] = int(item.get("width", 20))
                CONFIG["height"] = int(item.get("height", 20))
                CONFIG["primary_tileset"] = item.get("primary_tileset", "")
                CONFIG["secondary_tileset"] = item.get("secondary_tileset", "")
                
                if CONFIG["primary_tileset"]: CONFIG["allowed_tilesets"].append(CONFIG["primary_tileset"].split('/')[-1])
                if CONFIG["secondary_tileset"]: CONFIG["allowed_tilesets"].append(CONFIG["secondary_tileset"].split('/')[-1])
                break

    layout_clean = CONFIG["layout_id"].replace("LAYOUT_", "").title().replace("_", "")
    layout_dir_path = os.path.join(args.root_dir, "data", "layouts", layout_clean)
    
    CONFIG["map_bin_path"] = os.path.join(layout_dir_path, "map.bin")
    CONFIG["border_bin_path"] = os.path.join(layout_dir_path, "border.bin")

    if os.path.exists(CONFIG["border_bin_path"]):
        with open(CONFIG["border_bin_path"], "rb") as f:
            while (byte_data := f.read(2)): CONFIG["border_blocks"].append(int.from_bytes(byte_data, byteorder='little'))

    if os.path.exists(CONFIG["map_bin_path"]):
        with open(CONFIG["map_bin_path"], "rb") as f:
            while (byte_data := f.read(2)): CONFIG["metatiles"].append(int.from_bytes(byte_data, byteorder='little'))

    try:
        server = HTTPServer(('0.0.0.0', 8080), PoorymapWebBackend)
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nSession shutdown cleanly. Goodbye!")

if __name__ == "__main__":
    main()

