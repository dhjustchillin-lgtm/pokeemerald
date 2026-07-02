import sys
import os
import csv
import json
import re
import argparse
import io
from http.server import BaseHTTPRequestHandler, HTTPServer

try:
    from PIL import Image, ImageOps
except ImportError:
    print("[CRITICAL] 'Pillow' library is required. Run: pip install Pillow")
    sys.exit(1)

STUDIO = {
    "root_dir": "",
    "allowed_tilesets": [],
    "secondary_offset": 512,
    "palettes": {}, 
    "maps": {}      
}

def normalize_tileset_name(ts_name):
    if not ts_name: return ""
    if ts_name.startswith("gTileset_"): 
        ts_name = ts_name[len("gTileset_"):]
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', re.sub('(.)([A-Z][a-z]+)', r'\1_\2', ts_name)).lower()

def load_gba_pal_file(filepath):
    colors = []
    if not os.path.exists(filepath): return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                match = re.match(r'^(\d+)\s+(\d+)\s+(\d+)$', line.strip())
                if match:
                    colors.append((int(match.group(1)), int(match.group(2)), int(match.group(3))))
        return colors if len(colors) >= 16 else None
    except Exception: return None

def load_tileset_palettes(root_dir, domain, ts_folder):
    domain_pals = {}
    pal_dir = os.path.join(root_dir, "data", "tilesets", domain, ts_folder, "palettes")
    if os.path.exists(pal_dir):
        for file in os.listdir(pal_dir):
            if file.endswith(".pal"):
                num_match = re.search(r'(\d+)', file)
                if num_match:
                    pal_idx = int(num_match.group(1))
                    colors = load_gba_pal_file(os.path.join(pal_dir, file))
                    if colors: domain_pals[pal_idx] = colors
    return domain_pals

def stage_map_into_studio(root_dir, map_name):
    if map_name in STUDIO["maps"]: return True
    
    map_json_path = os.path.join(root_dir, "data", "maps", map_name, "map.json")
    layouts_json_path = os.path.join(root_dir, "data", "layouts", "layouts.json")
    if not os.path.exists(map_json_path) or not os.path.exists(layouts_json_path):
        return False

    try:
        with open(map_json_path, "r", encoding="utf-8") as f:
            layout_id = json.load(f).get("layout", "")

        width, height, p_ts, s_ts = 20, 20, "", ""
        with open(layouts_json_path, "r", encoding="utf-8") as f:
            for item in json.load(f).get("layouts", []):
                if item.get("id") == layout_id:
                    width = int(item.get("width", 20))
                    height = int(item.get("height", 20))
                    p_ts = item.get("primary_tileset", "")
                    s_ts = item.get("secondary_tileset", "")
                    break

        p_folder = normalize_tileset_name(p_ts)
        s_folder = normalize_tileset_name(s_ts)

        if "primary" not in STUDIO["palettes"]: STUDIO["palettes"]["primary"] = {}
        if "secondary" not in STUDIO["palettes"]: STUDIO["palettes"]["secondary"] = {}

        if p_folder and p_folder not in STUDIO["palettes"]["primary"]:
            STUDIO["palettes"]["primary"][p_folder] = load_tileset_palettes(root_dir, "primary", p_folder)
        if s_folder and s_folder not in STUDIO["palettes"]["secondary"]:
            STUDIO["palettes"]["secondary"][s_folder] = load_tileset_palettes(root_dir, "secondary", s_folder)

        layout_clean = layout_id.replace("LAYOUT_", "").title().replace("_", "")
        layout_dir_path = os.path.join(root_dir, "data", "layouts", layout_clean)
        
        map_bin = os.path.join(layout_dir_path, "map.bin")
        border_bin = os.path.join(layout_dir_path, "border.bin")

        metatiles, border_blocks = [], []
        if os.path.exists(map_bin):
            with open(map_bin, "rb") as f:
                while (b := f.read(2)): metatiles.append(int.from_bytes(b, byteorder='little'))
        if os.path.exists(border_bin):
            with open(border_bin, "rb") as f:
                while (b := f.read(2)): border_blocks.append(int.from_bytes(b, byteorder='little'))

        STUDIO["maps"][map_name] = {
            "map_name": map_name, "layout_id": layout_id, "width": width, "height": height,
            "p_folder": p_folder, "s_folder": s_folder, "map_bin_path": map_bin, "border_bin_path": border_bin,
            "metatiles": metatiles, "border_blocks": border_blocks,
            "primary_tiles_png": os.path.join(root_dir, "data", "tilesets", "primary", p_folder, "tiles.png"),
            "primary_metatiles_bin": os.path.join(root_dir, "data", "tilesets", "primary", p_folder, "metatiles.bin"),
            "secondary_tiles_png": os.path.join(root_dir, "data", "tilesets", "secondary", s_folder, "tiles.png"),
            "secondary_metatiles_bin": os.path.join(root_dir, "data", "tilesets", "secondary", s_folder, "metatiles.bin")
        }
        return True
    except Exception as e:
        print(f"[ERROR] Failed staging map {map_name}: {e}")
        return False

def force_disk_commit(map_name, map_data):
    root = STUDIO["root_dir"]
    layouts_json = os.path.join(root, "data", "layouts", "layouts.json")
    
    if os.path.exists(layouts_json):
        try:
            with open(layouts_json, "r", encoding="utf-8") as f:
                idx = json.load(f)
            for item in idx.get("layouts", []):
                if item.get("id") == map_data["layout_id"]:
                    item["width"] = map_data["width"]
                    item["height"] = map_data["height"]
            with open(layouts_json, "w", encoding="utf-8") as f:
                json.dump(idx, f, indent=4)
        except Exception as e:
            print(f"[ERROR] Layout JSON config update failed: {e}")

    try:
        with open(map_data["map_bin_path"], "wb") as f:
            for entry in map_data["metatiles"]:
                f.write(int(entry).to_bytes(2, byteorder='little'))
        if os.path.exists(map_data["border_bin_path"]):
            with open(map_data["border_bin_path"], "wb") as f:
                for entry in map_data["border_blocks"]:
                    f.write(int(entry).to_bytes(2, byteorder='little'))
        print(f"[SUCCESS] Saved '{map_name}' files directly to decomp repository.")
        return True
    except Exception as e:
        print(f"[ERROR] IO Write breakdown on {map_name}: {e}")
        return False

class PoorymapWebBackend(BaseHTTPRequestHandler):
    def log_message(self, format, *args): return

    def compile_tile(self, map_context, global_metatile_id):
        m = STUDIO["maps"].get(map_context)
        if not m: return None
        is_secondary = global_metatile_id >= STUDIO["secondary_offset"]
        
        if is_secondary:
            local_id = global_metatile_id - STUDIO["secondary_offset"]
            metatiles_bin = m["secondary_metatiles_bin"]
            tiles_png_path = m["secondary_tiles_png"]
            pals = STUDIO["palettes"]["secondary"].get(m["s_folder"], {})
        else:
            local_id = global_metatile_id
            metatiles_bin = m["primary_metatiles_bin"]
            tiles_png_path = m["primary_tiles_png"]
            pals = STUDIO["palettes"]["primary"].get(m["p_folder"], {})

        if not os.path.exists(metatiles_bin) or not os.path.exists(tiles_png_path):
            return Image.new("RGBA", (16, 16), (40, 40, 40, 255))

        try:
            with open(metatiles_bin, "rb") as f: metatiles_buffer = f.read()
            src_png = Image.open(tiles_png_path).convert("P")
            tiles_per_row = src_png.width // 8
            
            p_png = Image.open(m["primary_tiles_png"])
            primary_tile_count = (p_png.width // 8) * (p_png.height // 8)
            
            canvas = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
            offset = local_id * 16
            if offset + 16 > len(metatiles_buffer): return None
            
            grid_positions = [(0, 0), (8, 0), (0, 8), (8, 8)]
            for layer in range(2):
                for i in range(4):
                    byte_offset = offset + (layer * 8) + (i * 2)
                    tile_value = int.from_bytes(metatiles_buffer[byte_offset:byte_offset+2], byteorder='little')
                    
                    tile_id = tile_value & 0x03FF
                    x_flip = bool(tile_value & 0x0400)
                    y_flip = bool(tile_value & 0x0800)
                    palette_num = (tile_value >> 12) & 0x0F

                    if tile_id == 0 and layer == 1: continue
                    if is_secondary:
                        tile_id -= primary_tile_count
                        if tile_id < 0: tile_id = 0

                    s_row = tile_id // tiles_per_row
                    s_col = tile_id % tiles_per_row
                    tile_img_indexed = src_png.crop((s_col * 8, s_row * 8, (s_col + 1) * 8, (s_row + 1) * 8))
                    
                    tile_rgba = tile_img_indexed.convert("RGBA")
                    pixels = tile_rgba.load()
                    active_pal = pals.get(palette_num, None)
                    
                    if active_pal:
                        for y_px in range(8):
                            for x_px in range(8):
                                idx_color = tile_img_indexed.getpixel((x_px, y_px))
                                if idx_color % 16 == 0: pixels[x_px, y_px] = (0, 0, 0, 0)
                                else:
                                    p_idx = idx_color % 16
                                    if p_idx < len(active_pal):
                                        r, g, b = active_pal[p_idx]
                                        pixels[x_px, y_px] = (r, g, b, 255)

                    if x_flip: tile_rgba = ImageOps.mirror(tile_rgba)
                    if y_flip: tile_rgba = ImageOps.flip(tile_rgba)
                    canvas.alpha_composite(tile_rgba, grid_positions[i])
            return canvas
        except Exception: return None

    def do_GET(self):
        if self.path.startswith("/?"): self.path = "/"

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
                            behavior_map.append({"id": int(r.get("MetatileID", 0)), "behavior": r.get("BehaviorName", "UNKNOWN")})
                except Exception: pass

            html_template = """
            <!DOCTYPE html>
            <html>
            <head>
                <title>Pokeemerald Studio Environment</title>
                <style>
                    body { background-color: #0b0b0b; color: #00ff66; font-family: 'Courier New', monospace; margin: 0; padding: 15px; display: flex; gap: 15px; height: 98vh; box-sizing: border-box; }
                    .pane { background: #121212; border: 1px solid #00ff66; border-radius: 4px; padding: 12px; display: flex; flex-direction: column; overflow: hidden; }
                    #map-pane { flex: 2; }
                    #sidebar-pane { flex: 1; max-width: 440px; }
                    .grid-container { overflow: auto; background: #000; border: 1px solid #003311; border-radius: 2px; padding: 5px; flex-grow: 1; position: relative; }
                    .matrix { display: grid; gap: 1px; background-color: #051505; width: fit-content; }
                    .tile { width: 40px; height: 40px; background-color: #111; cursor: pointer; user-select: none; border: 1px solid #002208; display: flex; align-items: center; justify-content: center; box-sizing: border-box; position: relative; }
                    .tile img { width: 100%; height: 100%; image-rendering: pixelated; }
                    .tile:hover { border-color: #00ff66; z-index: 2; }
                    .tile.active { border-color: #ffffff !important; box-shadow: 0 0 6px #ffffff; z-index: 3; }
                    .tile.selected-range { background-color: #002244; border-color: #0088ff; opacity: 0.8; }
                    .atlas-visual-matrix { display: grid; grid-template-columns: repeat(8, 1fr); gap: 4px; padding: 2px; overflow-y: auto; flex-grow: 1; }
                    .atlas-cell { background: #181818; border: 1px solid #002208; padding: 2px; text-align: center; cursor: pointer; box-sizing: border-box; position: relative; aspect-ratio: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; }
                    .atlas-cell img { width: 100%; height: auto; image-rendering: pixelated; max-height: 30px; object-fit: contain; }
                    .atlas-cell .cell-id-tag { position: absolute; bottom: 1px; right: 2px; font-size: 8px; color: #00ff66; background: rgba(0,0,0,0.7); padding: 0 2px; }
                    .atlas-cell:hover { border-color: #00ff66; }
                    .atlas-cell.tracker-highlight { border-color: #ff3333 !important; box-shadow: inset 0 0 4px #ff3333; background: #200505; }
                    .toolbar { display: flex; gap: 6px; margin-bottom: 8px; flex-wrap: wrap; background: #050505; padding: 6px; border: 1px solid #002208; border-radius: 2px; }
                    button { background: #001104; color: #00ff66; border: 1px solid #00ff66; padding: 4px 10px; border-radius: 2px; cursor: pointer; font-family: monospace; font-size: 11px; text-transform: uppercase; }
                    button:hover { background: #003311; color: #fff; }
                    button.active-toggle { background: #330000; border-color: #ff3333; color: #ff3333; }
                    .tabs { display: flex; gap: 4px; margin-bottom: -1px; z-index: 2; position: relative; overflow-x: auto; }
                    .tab { background: #1c1c1c; color: #888; border: 1px solid #003311; padding: 6px 12px; border-radius: 4px 4px 0 0; cursor: pointer; font-size: 11px; white-space: nowrap; }
                    .tab.active { background: #121212; color: #00ff66; border-bottom: 1px solid #121212; font-weight: bold; }
                    .meta-readout { background: #000; padding: 10px; border-radius: 2px; border: 1px solid #002208; font-size: 11px; margin-top: 8px; line-height: 1.5; color: #00ff66; }
                    .section-title { font-weight: bold; color: #fff; border-bottom: 1px solid #002208; margin-bottom: 4px; padding-bottom: 2px; }
                    .property-row { display: flex; gap: 4px; margin-top: 6px; align-items: center; }
                    select, input[type="number"] { background: #000; color: #00ff66; border: 1px solid #00ff66; font-family: monospace; font-size: 11px; padding: 2px; border-radius: 2px; }
                </style>
            </head>
            <body>
                <div class="pane" id="map-pane">
                    <div class="tabs" id="map-tabs-container"></div>
                    <div class="toolbar">
                        <button onclick="saveCurrentMap()" style="font-weight: bold; border-color: #fff;" title="Ctrl+S">Save Studio</button>
                        <button id="btn-border" onclick="toggleBorderMode()" title="B">Border</button>
                        <button id="btn-select" onclick="toggleSelectionMode()" title="S">Select Range</button>
                        <button id="btn-hand" class="active-toggle" onclick="setTool('hand')" title="H">Hand (H)</button>
                        <button id="btn-draw" onclick="setTool('draw')" title="D">Draw (D)</button>
                        <button id="btn-picker" onclick="setTool('picker')" title="I">Eyedropper (I)</button>
                        <button onclick="copySelection()" title="C">Copy</button>
                        <button onclick="pasteSelection()" title="V">Paste</button>
                        <button onclick="promptOpenMap()">+ Load Tab</button>
                    </div>
                    <div class="grid-container"><div id="map-matrix" class="matrix"></div></div>
                    
                    <div class="toolbar" style="margin-top:8px; margin-bottom:0;">
                        <span style="font-size:11px; align-self:center; color:#fff; margin-right:8px;">SELECTION ATTRIBUTES:</span>
                        <button onclick="modifySelectionProperty('hFlip')" title="X">Flip H (X)</button>
                        <button onclick="modifySelectionProperty('vFlip')" title="Y">Flip V (Y)</button>
                        <div class="property-row" style="margin-top:0;">
                            <label>Elev:</label>
                            <input type="number" id="prop-elevation" min="0" max="15" value="0" onchange="applyPropertyField('elevation', this.value)">
                        </div>
                        <div class="property-row" style="margin-top:0; margin-left:8px;">
                            <label>Pal:</label>
                            <input type="number" id="prop-palette" min="0" max="15" value="0" onchange="applyPropertyField('palette', this.value)">
                        </div>
                        <div class="property-row" style="margin-top:0; margin-left:8px;">
                            <label>Bounds W:</label>
                            <input type="number" id="prop-width" min="1" max="128" style="width:45px;" onchange="resizeMapDimensions('width', this.value)">
                            <label>H:</label>
                            <input type="number" id="prop-height" min="1" max="128" style="width:45px;" onchange="resizeMapDimensions('height', this.value)">
                        </div>
                    </div>
                </div>

                <div class="pane" id="sidebar-pane">
                    <div class="toolbar">
                        <button id="btn-atlas-p" onclick="changeAtlasView('primary')" title="P">Primary Atlas</button>
                        <button id="btn-atlas-s" onclick="changeAtlasView('secondary')" title="O">Secondary Atlas</button>
                    </div>
                    <div class="grid-container" style="display: flex; flex-direction: column;"><div id="atlas-container" class="atlas-visual-matrix"></div></div>
                    <div class="meta-readout" id="readout-box">Select elements to initialize tracking properties.</div>
                </div>

                <script>
                    let STUDIO = __STUDIO_DATA__;
                    let BEHAVIORS = __BEHAVIOR_DATA__;
                    let activeMapName = Object.keys(STUDIO.maps)[0] || "";
                    
                    let state = {
                        borderMode: false, selectionActive: false, selectionStart: null,
                        cursorIdx: 0, clipboard: null, atlasView: 'primary', currentTool: 'hand',
                        lastActiveTool: 'hand', selectedPaletteBlock: 0
                    };

                    function parseMetatile(val) {
                        return { id: val & 0x03FF, elevation: (val >> 10) & 0x0F, hFlip: (val >> 14) & 0x01, vFlip: (val >> 15) & 0x01, palette: (val >> 12) & 0x0F };
                    }
                    function packMetatile(id, elev, hf, vf, pal) {
                        return (id & 0x03FF) | ((elev & 0x0F) << 10) | ((hf & 0x01) << 14) | ((vf & 0x01) << 15) | ((pal & 0x0F) << 12);
                    }

                    function renderTabs() {
                        const container = document.getElementById("map-tabs-container");
                        container.innerHTML = "";
                        Object.keys(STUDIO.maps).forEach(name => {
                            let tab = document.createElement("div");
                            tab.className = "tab" + (name === activeMapName ? " active" : "");
                            tab.innerText = name;
                            tab.onclick = () => { switchMapTab(name); };
                            container.appendChild(tab);
                        });
                    }

                    function switchMapTab(name) {
                        activeMapName = name;
                        state.cursorIdx = 0;
                        state.selectionActive = false;
                        state.selectionStart = null;
                        
                        let m = STUDIO.maps[activeMapName];
                        document.getElementById("prop-width").value = m.width;
                        document.getElementById("prop-height").value = m.height;
                        
                        renderTabs();
                        renderMatrixGrid();
                        buildVisualAtlas();
                        updateReadout();
                    }

                    function setTool(toolName) {
                        if (state.currentTool !== 'picker') state.lastActiveTool = state.currentTool;
                        state.currentTool = toolName;
                        document.getElementById("btn-hand").classList.toggle("active-toggle", toolName === 'hand');
                        document.getElementById("btn-draw").classList.toggle("active-toggle", toolName === 'draw');
                        document.getElementById("btn-picker").classList.toggle("active-toggle", toolName === 'picker');
                    }

                    function getSelectedIndices() {
                        let m = STUDIO.maps[activeMapName];
                        let width = state.borderMode ? 2 : m.width;
                        if (!state.selectionActive || state.selectionStart === null) return [state.cursorIdx];
                        
                        let sX = state.selectionStart % width, sY = Math.floor(state.selectionStart / width);
                        let curX = state.cursorIdx % width, curY = Math.floor(state.cursorIdx / width);
                        let x1 = Math.min(sX, curX), x2 = Math.max(sX, curX);
                        let y1 = Math.min(sY, curY), y2 = Math.max(sY, curY);
                        
                        let indices = [];
                        for (let y = y1; y <= y2; y++) {
                            for (let x = x1; x <= x2; x++) { indices.push(y * width + x); }
                        }
                        return indices;
                    }

                    function renderMatrixGrid() {
                        const grid = document.getElementById("map-matrix"); grid.innerHTML = "";
                        let m = STUDIO.maps[activeMapName]; if (!m) return;
                        
                        let width = state.borderMode ? 2 : m.width;
                        let tiles = state.borderMode ? m.border_blocks : m.metatiles;
                        grid.style.gridTemplateColumns = `repeat(${width}, 40px)`;
                        
                        tiles.forEach((entry, idx) => {
                            let meta = parseMetatile(entry);
                            let cell = document.createElement("div"); cell.className = "tile"; cell.id = `tile-${idx}`;
                            let img = document.createElement("img"); img.src = `/render_tile?map=${activeMapName}&id=${meta.id}`;
                            cell.appendChild(img);
                            
                            if (idx === state.cursorIdx) cell.classList.add("active");
                            if (state.selectionActive && state.selectionStart !== null) {
                                let cX = idx % width, cY = Math.floor(idx / width);
                                let sX = state.selectionStart % width, sY = Math.floor(state.selectionStart / width);
                                let curX = state.cursorIdx % width, curY = Math.floor(state.cursorIdx / width);
                                if (cX >= Math.min(sX, curX) && cX <= Math.max(sX, curX) && cY >= Math.min(sY, curY) && cY <= Math.max(sY, curY)) cell.classList.add("selected-range");
                            }
                            
                            cell.onclick = () => {
                                state.cursorIdx = idx;
                                if (state.currentTool === 'picker') {
                                    state.selectedPaletteBlock = meta.id;
                                    state.atlasView = (meta.id >= STUDIO.secondary_offset) ? 'secondary' : 'primary';
                                    setTool(state.lastActiveTool);
                                    buildVisualAtlas();
                                } else if (state.currentTool === 'draw') {
                                    applyTileToSelection(state.selectedPaletteBlock);
                                }
                                renderMatrixGrid(); updateReadout();
                            };
                            grid.appendChild(cell);
                        });
                    }

                    function buildVisualAtlas() {
                        const container = document.getElementById("atlas-container"); container.innerHTML = "";
                        let startId = state.atlasView === 'primary' ? 0 : STUDIO.secondary_offset;
                        let endId = startId + 512;
                        
                        document.getElementById("btn-atlas-p").classList.toggle("active-toggle", state.atlasView === 'primary');
                        document.getElementById("btn-atlas-s").classList.toggle("active-toggle", state.atlasView === 'secondary');

                        for (let blockId = startId; blockId < endId; blockId++) {
                            let cell = document.createElement("div"); cell.className = "atlas-cell"; cell.id = `atlas-cell-${blockId}`;
                            let img = document.createElement("img"); img.src = `/render_tile?map=${activeMapName}&id=${blockId}`; cell.appendChild(img);
                            if (blockId === state.selectedPaletteBlock) cell.classList.add("tracker-highlight");
                            
                            cell.onclick = () => {
                                state.selectedPaletteBlock = blockId;
                                buildVisualAtlas();
                                if (state.currentTool === 'draw') applyTileToSelection(blockId);
                            };
                            container.appendChild(cell);
                        }
                    }

                    function applyTileToSelection(blockId) {
                        let m = STUDIO.maps[activeMapName];
                        let tiles = state.borderMode ? m.border_blocks : m.metatiles;
                        let targets = getSelectedIndices();
                        
                        targets.forEach(idx => {
                            if (idx < tiles.length) {
                                let oldMeta = parseMetatile(tiles[idx]);
                                tiles[idx] = packMetatile(blockId, oldMeta.elevation, oldMeta.hFlip, oldMeta.vFlip, oldMeta.palette);
                            }
                        });
                        renderMatrixGrid(); updateReadout();
                    }

                    function modifySelectionProperty(type) {
                        let m = STUDIO.maps[activeMapName];
                        let tiles = state.borderMode ? m.border_blocks : m.metatiles;
                        let targets = getSelectedIndices();
                        
                        targets.forEach(idx => {
                            if (idx < tiles.length) {
                                let meta = parseMetatile(tiles[idx]);
                                if (type === 'hFlip') meta.hFlip = meta.hFlip ? 0 : 1;
                                if (type === 'vFlip') meta.vFlip = meta.vFlip ? 0 : 1;
                                tiles[idx] = packMetatile(meta.id, meta.elevation, meta.hFlip, meta.vFlip, meta.palette);
                            }
                        });
                        renderMatrixGrid(); updateReadout();
                    }

                    function applyPropertyField(field, val) {
                        let m = STUDIO.maps[activeMapName];
                        let tiles = state.borderMode ? m.border_blocks : m.metatiles;
                        let targets = getSelectedIndices();
                        let intVal = parseInt(val) || 0;
                        
                        targets.forEach(idx => {
                            if (idx < tiles.length) {
                                let meta = parseMetatile(tiles[idx]);
                                meta[field] = intVal;
                                tiles[idx] = packMetatile(meta.id, meta.elevation, meta.hFlip, meta.vFlip, meta.palette);
                            }
                        });
                        renderMatrixGrid(); updateReadout();
                    }

                    function changeAtlasView(type) { state.atlasView = type; buildVisualAtlas(); updateReadout(); }

                    function resizeMapDimensions(dim, val) {
                        if (state.borderMode) return;
                        let m = STUDIO.maps[activeMapName];
                        let newV = parseInt(val) || 20;
                        let oldW = m.width, oldH = m.height;
                        let newW = (dim === 'width') ? newV : oldW;
                        let newH = (dim === 'height') ? newV : oldH;
                        
                        let newTiles = new Array(newW * newH).fill(0);
                        for (let y = 0; y < Math.min(oldH, newH); y++) {
                            for (let x = 0; x < Math.min(oldW, newW); x++) {
                                newTiles[y * newW + x] = m.metatiles[y * oldW + x];
                            }
                        }
                        m.width = newW; m.height = newH; m.metatiles = newTiles;
                        renderMatrixGrid();
                    }

                    function updateReadout() {
                        let m = STUDIO.maps[activeMapName];
                        let tiles = state.borderMode ? m.border_blocks : m.metatiles;
                        let meta = parseMetatile(tiles[state.cursorIdx] || 0);
                        let match = BEHAVIORS.find(b => b.id === meta.id);
                        
                        document.getElementById("prop-elevation").value = meta.elevation;
                        document.getElementById("prop-palette").value = meta.palette;

                        document.getElementById("readout-box").innerHTML = `
                            <div class="section-title">ELEMENT CONFIGURATION</div>
                            <strong>Current Target:</strong> ${activeMapName}<br>
                            <strong>Global Metatile ID:</strong> ${meta.id}<br>
                            <strong>Hardware Palette:</strong> Bank ${meta.palette}<br>
                            <strong>Flags:</strong> H-Flip: ${meta.hFlip} | V-Flip: ${meta.vFlip}<br>
                            <strong>Active Tool:</strong> ${state.currentTool.toUpperCase()}<br>
                            <strong>Behavior Match:</strong> ${match ? match.behavior : "UNKNOWN"}
                        `;
                    }

                    function toggleBorderMode() {
                        state.borderMode = !state.borderMode; state.cursorIdx = 0; state.selectionActive = false;
                        document.getElementById("btn-border").classList.toggle("active-toggle", state.borderMode);
                        renderMatrixGrid(); updateReadout();
                    }
                    function toggleSelectionMode() { state.selectionActive = !state.selectionActive; state.selectionStart = state.selectionActive ? state.cursorIdx : null; document.getElementById("btn-select").classList.toggle("active-toggle", state.selectionActive); renderMatrixGrid(); }
                    
                    function copySelection() {
                        if (!state.selectionActive || state.selectionStart === null) return;
                        let m = STUDIO.maps[activeMapName];
                        let width = state.borderMode ? 2 : m.width;
                        let sX = state.selectionStart % width, sY = Math.floor(state.selectionStart / width);
                        let curX = state.cursorIdx % width, curY = Math.floor(state.cursorIdx / width);
                        let x1 = Math.min(sX, curX), x2 = Math.max(sX, curX), y1 = Math.min(sY, curY), y2 = Math.max(sY, curY);
                        let tiles = state.borderMode ? m.border_blocks : m.metatiles;
                        
                        state.clipboard = { w: x2 - x1 + 1, h: y2 - y1 + 1, blocks: [] };
                        for(let y=y1; y<=y2; y++) { for(let x=x1; x<=x2; x++) { state.clipboard.blocks.push(tiles[y * width + x]); } }
                        state.selectionActive = false; document.getElementById("btn-select").classList.remove("active-toggle"); renderMatrixGrid();
                    }
                    
                    function pasteSelection() {
                        if (!state.clipboard) return;
                        let m = STUDIO.maps[activeMapName];
                        let width = state.borderMode ? 2 : m.width;
                        let height = Math.ceil((state.borderMode ? m.border_blocks : m.metatiles).length / width);
                        let tiles = state.borderMode ? m.border_blocks : m.metatiles;
                        let startX = state.cursorIdx % width, startY = Math.floor(state.cursorIdx / width);
                        
                        for(let y=0; y<state.clipboard.h; y++) {
                            if (startY + y >= height) break;
                            for(let x=0; x<state.clipboard.w; x++) { if (startX + x >= width) break; tiles[(startY + y) * width + (startX + x)] = state.clipboard.blocks[y * state.clipboard.w + x]; }
                        }
                        renderMatrixGrid(); updateReadout();
                    }

                    function promptOpenMap() {
                        let name = prompt("Enter map directory name inside 'data/maps/':");
                        if (name) {
                            fetch(`/open_map?name=${name}`).then(res => res.json()).then(data => {
                                if (data.status === "success") {
                                    STUDIO.maps[name] = data.payload;
                                    switchMapTab(name);
                                } else alert("Failed to stage target folder structure.");
                            });
                        }
                    }

                    function saveCurrentMap() {
                        let m = STUDIO.maps[activeMapName];
                        fetch('/save', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ map_name: activeMapName, width: m.width, height: m.height, metatiles: m.metatiles, border_blocks: m.border_blocks }) })
                        .then(res => res.json()).then(data => alert(data.message));
                    }

                    window.addEventListener("keydown", (e) => {
                        let m = STUDIO.maps[activeMapName]; if(!m) return;
                        let width = state.borderMode ? 2 : m.width;
                        let maxLen = (state.borderMode ? m.border_blocks : m.metatiles).length;
                        
                        if (e.key === "ArrowUp" && state.cursorIdx >= width) state.cursorIdx -= width;
                        else if (e.key === "ArrowDown" && state.cursorIdx + width < maxLen) state.cursorIdx += width;
                        else if (e.key === "ArrowLeft" && state.cursorIdx % width > 0) state.cursorIdx -= 1;
                        else if (e.key === "ArrowRight" && state.cursorIdx % width < width - 1) state.cursorIdx += 1;
                        else if (e.key.toLowerCase() === "s" && e.ctrlKey) { e.preventDefault(); saveCurrentMap(); return; }
                        else if (e.key.toLowerCase() === "s") { toggleSelectionMode(); return; }
                        else if (e.key.toLowerCase() === "c") { copySelection(); return; }
                        else if (e.key.toLowerCase() === "v") { pasteSelection(); return; }
                        else if (e.key.toLowerCase() === "b") { toggleBorderMode(); return; }
                        else if (e.key.toLowerCase() === "h") { setTool('hand'); return; }
                        else if (e.key.toLowerCase() === "d") { setTool('draw'); return; }
                        else if (e.key.toLowerCase() === "i") { setTool('picker'); return; }
                        else if (e.key.toLowerCase() === "x") { modifySelectionProperty('hFlip'); return; }
                        else if (e.key.toLowerCase() === "y") { modifySelectionProperty('vFlip'); return; }
                        else if (e.key.toLowerCase() === "p") { changeAtlasView('primary'); return; }
                        else if (e.key.toLowerCase() === "o") { changeAtlasView('secondary'); return; }
                        else return;
                        renderMatrixGrid(); updateReadout();
                    });

                    switchMapTab(activeMapName);
                </script>
            </body>
            </html>
            """.replace("__STUDIO_DATA__", json.dumps(STUDIO)).replace("__BEHAVIOR_DATA__", json.dumps(behavior_map))
            self.wfile.write(html_template.encode('utf-8'))
            
        elif self.path.startswith("/render_tile"):
            params = re.findall(r'map=([^&]+)', self.path)
            map_ctx = params[0] if params else ""
            id_params = re.findall(r'id=(\d+)', self.path)
            global_id = int(id_params[0]) if id_params else 0
            
            tile_img = self.compile_tile(map_ctx, global_id)
            if tile_img:
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                buf = io.BytesIO()
                tile_img.save(buf, format="PNG")
                self.wfile.write(buf.getvalue())
            else:
                self.send_response(404)
                self.end_headers()

        elif self.path.startswith("/open_map"):
            name_param = re.findall(r'name=([^&]+)', self.path)
            target_map = name_param[0] if name_param else ""
            success = stage_map_into_studio(STUDIO["root_dir"], target_map)
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            if success:
                self.wfile.write(json.dumps({"status": "success", "payload": STUDIO["maps"][target_map]}).encode('utf-8'))
            else:
                self.wfile.write(json.dumps({"status": "error"}).encode('utf-8'))

    def do_POST(self):
        if self.path == "/save":
            content_length = int(self.headers['Content-Length'])
            data = json.loads(self.rfile.read(content_length).decode('utf-8'))
            name = data.get("map_name")
            
            if name in STUDIO["maps"]:
                m = STUDIO["maps"][name]
                m["width"] = data.get("width", m["width"])
                m["height"] = data.get("height", m["height"])
                m["metatiles"] = data.get("metatiles", m["metatiles"])
                m["border_blocks"] = data.get("border_blocks", m["border_blocks"])
                
                if force_disk_commit(name, m):
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"message": f"Successfully committed updates for '{name}' straight to file system paths."}).encode('utf-8'))
                    return
            self.send_response(500)
            self.end_headers()

def main():
    parser = argparse.ArgumentParser(description="Pokeemerald Unified Workspace Framework")
    parser.add_argument("root_dir", help="Path to pokeemerald repository root directory")
    parser.add_argument("map_name", help="Default entry map directory identifier to instantiate")
    args = parser.parse_args()

    STUDIO["root_dir"] = args.root_dir

    if not stage_map_into_studio(args.root_dir, args.map_name):
        print(f"[CRITICAL] Error parsing initial map files: {args.map_name}")
        sys.exit(1)

    server = HTTPServer(('0.0.0.0', 8080), PoorymapWebBackend)
    print(f"Workspace studio engine active: http://localhost:8080")
    try: server.serve_forever()
    except KeyboardInterrupt: print("\nClean termination.")

if __name__ == "__main__":
    main()

