import sys
import os
import csv
import json
import re
import argparse
import curses
from dataclasses import dataclass, field

# TERMUX COMPATIBLE: Standard ANSI colors 1-15.
ELEVATION_COLORS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]

BEHAVIOR_COLORS = {
    "grass": 2,    # Green
    "water": 4,    # Blue
    "jump": 6,     # Cyan
    "warp": 3,     # Yellow
    "door": 5,     # Magenta
    "ice": 14,     # Light Cyan
    "block": 1     # Red
}

@dataclass
class BrowserTile:
    tileset: str
    tile_id: int
    behavior_name: str

@dataclass
class Browser:
    visible: bool = False
    cursor: int = 0
    scroll: int = 0
    search: str = ""
    filtered_list: list[BrowserTile] = field(default_factory=list)

@dataclass
class Selection:
    active: bool = False
    start_x: int = 0
    start_y: int = 0

@dataclass
class Clipboard2D:
    width: int = 0
    height: int = 0
    tiles: list[int] = field(default_factory=list)

def parse_metatile(entry_int):
    tile_id = entry_int & 0x03FF
    elevation = (entry_int >> 10) & 0x0F
    h_flip = (entry_int >> 14) & 0x01
    v_flip = (entry_int >> 15) & 0x01
    return tile_id, elevation, h_flip, v_flip

def pack_metatile(tile_id, elevation, h_flip, v_flip):
    return (tile_id & 0x03FF) | ((elevation & 0x0F) << 10) | ((h_flip & 0x01) << 14) | ((v_flip & 0x01) << 15)

def normalize_tileset_name(ts_name):
    if ts_name.startswith("gTileset_"):
        ts_name = ts_name[len("gTileset_"):]
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', ts_name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

def load_metatiles_csv(allowed_tilesets=None):
    csv_path = "metatiles.csv"
    if not os.path.exists(csv_path):
        return []
        
    tiles = []
    try:
        with open(csv_path, mode="r", encoding="utf8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts_name = row.get("Tileset", "unknown")
                ts_base = ts_name.split('/')[-1] if '/' in ts_name else ts_name
                
                if allowed_tilesets is not None and ts_base not in allowed_tilesets:
                    continue
                tiles.append(BrowserTile(
                    tileset=ts_base,
                    tile_id=int(row.get("MetatileID", 0)),
                    behavior_name=row.get("BehaviorName", "UNKNOWN")
                ))
    except Exception:
        return []
    return tiles

def get_row_color_pair(behavior_name):
    name_lower = behavior_name.lower()
    for keyword, color_idx in BEHAVIOR_COLORS.items():
        if keyword in name_lower:
            return color_idx
    return 7

def update_browser_filtering(all_tiles, browser):
    filtered = []
    s_term = browser.search.strip().lower()
    
    search_is_numeric = False
    search_numeric_val = -1
    if s_term:
        try:
            search_numeric_val = int(s_term)
            search_is_numeric = True
        except ValueError:
            search_is_numeric = False

    for t in all_tiles:
        if s_term:
            matches_numeric = search_is_numeric and (t.tile_id == search_numeric_val)
            matches_text = (s_term in t.behavior_name.lower() or s_term in t.tileset.lower() or s_term in str(t.tile_id))
            if not (matches_numeric or matches_text):
                continue
        filtered.append(t)
        
    browser.filtered_list = filtered
    if len(filtered) == 0:
        browser.cursor = 0
    elif browser.cursor >= len(filtered):
        browser.cursor = max(0, len(filtered) - 1)

def prompt_user_input(stdscr, prompt_text, term_lines):
    curses.echo()
    curses.curs_set(1)
    stdscr.addstr(term_lines - 3, 0, " " * (stdscr.getmaxyx()[1] - 1))
    stdscr.addstr(term_lines - 3, 0, prompt_text, curses.color_pair(4))
    stdscr.refresh()
    input_bytes = stdscr.getstr(term_lines - 3, len(prompt_text), 10)
    curses.noecho()
    try:
        return int(input_bytes.decode('utf-8').strip())
    except:
        return None

def resize_map_matrix(old_width, old_height, new_width, new_height, old_metatiles, border_blocks):
    new_metatiles = []
    b_width, b_height = 2, 2
    
    for y in range(new_height):
        for x in range(new_width):
            if x < old_width and y < old_height:
                old_idx = y * old_width + x
                new_metatiles.append(old_metatiles[old_idx])
            else:
                if border_blocks:
                    b_x = x % b_width
                    b_y = y % b_height
                    b_idx = b_y * b_width + b_x
                    if b_idx < len(border_blocks):
                        new_metatiles.append(border_blocks[b_idx])
                    else:
                        new_metatiles.append(border_blocks[0])
                else:
                    new_metatiles.append(pack_metatile(0, 0, 0, 0))
    return new_metatiles

def curses_main(stdscr, filepath, width, metatiles, allowed_tilesets, border_blocks):
    curses.use_default_colors()
    curses.curs_set(1)
    stdscr.keypad(True)
    
    for i in range(0, 16):
        text_color = curses.COLOR_WHITE if i == 0 else i
        curses.init_pair(i + 1, text_color, -1)
        
    curses.init_pair(100, curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(101, curses.COLOR_BLACK, curses.COLOR_CYAN) # Selection highlight

    all_browser_tiles = load_metatiles_csv(allowed_tilesets)
    browser = Browser()
    update_browser_filtering(all_browser_tiles, browser)

    selection = Selection()
    clip_2d = Clipboard2D()

    cursor_idx = 0
    border_cursor_idx = 0
    input_buffer = ""
    scroll_x, scroll_y = 0, 0
    search_mode = False
    border_mode = False
    
    current_width = width if width else 20
    total_tiles = len(metatiles)
    current_height = (total_tiles + current_width - 1) // current_width if total_tiles else 20

    while True:
        try:
            stdscr.erase()
            term_lines, term_cols = stdscr.getmaxyx()

            map_split_weight = 0.65 if browser.visible else 0.85
            map_cols = int(term_cols * map_split_weight)
            side_panel_cols = term_cols - map_cols - 2

            active_tiles = border_blocks if border_mode else metatiles
            active_width = 2 if border_mode else current_width
            active_height = (len(border_blocks) + 1) // 2 if border_mode else current_height
            active_cursor = border_cursor_idx if border_mode else cursor_idx

            c_x, c_y = active_cursor % active_width, active_cursor // active_width

            max_visible_cols = max(1, (map_cols - 4) // 6)
            max_visible_rows = max(1, term_lines - 12)

            if c_x < scroll_x: scroll_x = c_x
            elif c_x >= scroll_x + max_visible_cols: scroll_x = c_x - max_visible_cols + 1
            if c_y < scroll_y: scroll_y = c_y
            elif c_y >= scroll_y + max_visible_rows: scroll_y = c_y - max_visible_rows + 1

            if term_lines > 0:
                title_prefix = f"[SELECTING] " if selection.active else ("[BORDER MODE] " if border_mode else "")
                stdscr.addstr(0, 0, f"=== {title_prefix}POKEEMERALD TERMINAL MAP EDITOR (Poorymap) ===", curses.color_pair(3))
            if term_lines > 1:
                stdscr.addstr(1, 0, "Arrows: Move | J/K: Elev | F: Flip | S: Select Block | C/V: Copy/Paste Area | -: Sequential Fill | R: Resize")

            if scroll_y > 0 and term_lines > 2:
                stdscr.addstr(2, 0, "     ^^^ (More rows above) ^^^")

            active_elevations = sorted(list({parse_metatile(t)[1] for t in active_tiles}))

            # Establish math boundaries for 2D visual checking loops
            x_min, x_max = (min(selection.start_x, c_x), max(selection.start_x, c_x)) if selection.active else (c_x, c_x)
            y_min, y_max = (min(selection.start_y, c_y), max(selection.start_y, c_y)) if selection.active else (c_y, c_y)

            for y in range(scroll_y, min(active_height, scroll_y + max_visible_rows)):
                screen_y = 3 + (y - scroll_y)
                if screen_y >= term_lines - 8: break
                
                stdscr.addstr(screen_y, 0, "< " if scroll_x > 0 else "  ")
                
                for x in range(scroll_x, min(active_width, scroll_x + max_visible_cols)):
                    i = y * active_width + x
                    if i >= len(active_tiles): break
                    
                    t_id, elev, hf, vf = parse_metatile(active_tiles[i])
                    is_in_selection = selection.active and (x_min <= x <= x_max) and (y_min <= y <= y_max)
                    
                    if i == active_cursor:
                        disp = input_buffer.ljust(4, '_') if input_buffer else f"{t_id:04d}"
                        stdscr.addstr(screen_y, 2 + (x - scroll_x) * 6, f"[{disp[:2]}{disp[2:]}]", curses.color_pair(100))
                    elif is_in_selection:
                        stdscr.addstr(screen_y, 2 + (x - scroll_x) * 6, f" {t_id:04d} ", curses.color_pair(101))
                    else:
                        pal_idx = ELEVATION_COLORS[elev % len(ELEVATION_COLORS)]
                        attr_color = curses.color_pair(pal_idx)
                        if hf: attr_color |= curses.A_UNDERLINE
                        if vf: attr_color |= curses.A_STANDOUT
                        stdscr.addstr(screen_y, 2 + (x - scroll_x) * 6, f" {t_id:04d} ", attr_color)
                
                if active_width > scroll_x + max_visible_cols and (2 + max_visible_cols * 6) < term_cols:
                    stdscr.addstr(screen_y, 2 + max_visible_cols * 6, ">")

            target_footer_y = 3 + max_visible_rows
            if active_height > scroll_y + max_visible_rows and target_footer_y < (term_lines - 7):
                stdscr.addstr(target_footer_y, 0, "     vvv (More rows below) vvv")

            current_behavior_name = "UNKNOWN"
            if browser.visible and browser.filtered_list and browser.cursor < len(browser.filtered_list):
                b_tile = browser.filtered_list[browser.cursor]
                current_behavior_name = f"{b_tile.behavior_name} [ID: {b_tile.tile_id:04d}] [Tileset: {b_tile.tileset}]"
            elif active_cursor < len(active_tiles):
                c_tile, c_elev, c_h, c_v = parse_metatile(active_tiles[active_cursor])
                for t in all_browser_tiles:
                    if t.tile_id == c_tile:
                        current_behavior_name = t.behavior_name
                        break
                
            if active_cursor < len(active_tiles):
                c_tile, c_elev, c_h, c_v = parse_metatile(active_tiles[active_cursor])
                flip_status = "None" if not (c_h or c_v) else ("Both" if (c_h and c_v) else ("Horiz" if c_h else "Vert"))
                clip_status = "Empty" if clip_2d.width == 0 else f"{clip_2d.width}x{clip_2d.height} Block"
                if term_lines - 6 >= 0:
                    mode_label = "Border" if border_mode else "Map"
                    stdscr.addstr(term_lines - 6, 0, f"{mode_label} -> X: {c_x:02d}, Y: {c_y:02d} | Size: {active_width}x{active_height} | ID: {c_tile:04d} | Elev: {c_elev:02d} | Flips: {flip_status} | Clip: {clip_status}", curses.color_pair(3))

            if term_lines - 4 >= 0:
                stdscr.addstr(term_lines - 4, 0, "Active Elevs: ")
                curr_col = 14
                for e_idx in active_elevations:
                    if curr_col + 6 >= term_cols: break
                    c_pair = ELEVATION_COLORS[e_idx % len(ELEVATION_COLORS)]
                    stdscr.addstr(term_lines - 4, curr_col, f" [{e_idx:02d}] ", curses.color_pair(c_pair))
                    curr_col += 6

            browser_start_y = 2 

            if browser.visible:
                if browser.filtered_list:
                    if browser.cursor < browser.scroll: browser.scroll = browser.cursor
                    elif browser.cursor >= browser.scroll + (max_visible_rows - 2): browser.scroll = browser.cursor - (max_visible_rows - 2) + 1
                else:
                    browser.scroll = 0
                    browser.cursor = 0

                if browser_start_y < term_lines - 8 and (map_cols + 1) < term_cols:
                    stdscr.addstr(browser_start_y, map_cols + 1, "TILE BROWSER".ljust(side_panel_cols), curses.A_REVERSE)
                
                end_browser_idx = min(len(browser.filtered_list), browser.scroll + max(1, max_visible_rows - 2))
                for idx in range(browser.scroll, end_browser_idx):
                    b_scr_y = browser_start_y + 1 + (idx - browser.scroll)
                    if b_scr_y >= term_lines - 8: break
                    
                    if (map_cols + 1) < term_cols:
                        tile = browser.filtered_list[idx]
                        row_txt = f"{tile.tile_id:04d} {tile.behavior_name[:8]} [{tile.tileset[:6]}]".ljust(side_panel_cols)[:side_panel_cols]
                        
                        if idx == browser.cursor:
                            stdscr.addstr(b_scr_y, map_cols + 1, row_txt, curses.color_pair(100))
                        else:
                            c_pair = get_row_color_pair(tile.behavior_name)
                            stdscr.addstr(b_scr_y, map_cols + 1, row_txt, curses.color_pair(c_pair))

            if term_lines - 2 >= 0:
                if browser.visible:
                    stdscr.addstr(term_lines - 2, 0, "Footer: [ENTER] Paste ID | [N] Toggle Browser | [/] Search | [Ctrl+S] Save & Close", curses.A_DIM)
                else:
                    stdscr.addstr(term_lines - 2, 0, "Footer: [S] Area Selection Tool | [C] Copy | [V] Paste Area Matrix | [-] Sequential Fill | [Ctrl+S] Save", curses.A_DIM)

            if term_lines - 5 >= 0:
                stdscr.addstr(term_lines - 5, 0, f"Selected Tile Behavior: {current_behavior_name}".ljust(term_cols - 1), curses.color_pair(11))

            if search_mode and (term_lines - 3 >= 0):
                stdscr.addstr(term_lines - 3, 0, f"SEARCH MODE: {browser.search}_", curses.color_pair(6))

            stdscr.refresh()
            ch = stdscr.getch()

            if ch == 19:  # Ctrl+S
                return "SAVE", current_width, metatiles
            elif ch in [3, 27]:  # Ctrl+C or Escape
                return "CANCEL", current_width, metatiles

            if search_mode:
                if ch in [curses.KEY_ENTER, 10, 13]:
                    search_mode = False
                elif ch in [curses.KEY_BACKSPACE, 127, 8]:
                    if browser.search:
                        browser.search = browser.search[:-1]
                        update_browser_filtering(all_browser_tiles, browser)
                    else:
                        search_mode = False
                elif 32 <= ch <= 126:
                    browser.search += chr(ch)
                    update_browser_filtering(all_browser_tiles, browser)
                continue

            if ch in [ord('n'), ord('N')]:
                browser.visible = not browser.visible
                continue
            elif ch == ord('/'):
                if browser.visible:
                    search_mode = True
                continue

            if ch in [ord('b'), ord('B')]:
                border_mode = not border_mode
                scroll_x, scroll_y = 0, 0
                input_buffer = ""
                selection.active = False
                continue

            if ch in [ord('s'), ord('S')]:
                selection.active = not selection.active
                if selection.active:
                    selection.start_x = c_x
                    selection.start_y = c_y
                continue

            if ch in [ord('r'), ord('R')]:
                if border_mode: continue
                new_w = prompt_user_input(stdscr, "Enter New Map Width: ", term_lines)
                new_h = prompt_user_input(stdscr, "Enter New Map Height: ", term_lines)
                curses.curs_set(1)
                
                if new_w and new_h and new_w > 0 and new_h > 0:
                    metatiles = resize_map_matrix(current_width, current_height, new_w, new_h, metatiles, border_blocks)
                    current_width = new_w
                    current_height = new_h
                    cursor_idx = 0
                    scroll_x, scroll_y = 0, 0
                continue

            if ch in [ord('c'), ord('C')]:
                # Perform continuous block chunk reading 
                w_sel = x_max - x_min + 1
                h_sel = y_max - y_min + 1
                clip_2d.width = w_sel
                clip_2d.height = h_sel
                clip_2d.tiles = []
                for sy in range(y_min, y_max + 1):
                    for sx in range(x_min, x_max + 1):
                        idx_map = sy * active_width + sx
                        clip_2d.tiles.append(active_tiles[idx_map])
                selection.active = False # Reset layout selection bounds visually
                continue
                
            elif ch in [ord('v'), ord('V')]:
                if clip_2d.width > 0:
                    for offset_y in range(clip_2d.height):
                        target_y = c_y + offset_y
                        if target_y >= active_height: break
                        for offset_x in range(clip_2d.width):
                            target_x = c_x + offset_x
                            if target_x >= active_width: break
                            
                            src_idx = offset_y * clip_2d.width + offset_x
                            dest_idx = target_y * active_width + target_x
                            active_tiles[dest_idx] = clip_2d.tiles[src_idx]
                continue

            elif ch == ord('-'):
                if selection.active:
                    start_id = prompt_user_input(stdscr, "Enter Start Metatile ID: ", term_lines)
                    curses.curs_set(1)
                    if start_id is not None:
                        elev = prompt_user_input(stdscr, "Enter Elevation: ", term_lines)
                        curses.curs_set(1)
                        if elev is not None:
                            current_id = start_id
                            for sy in range(y_min, y_max + 1):
                                for sx in range(x_min, x_max + 1):
                                    idx = sy * active_width + sx
                                    active_tiles[idx] = pack_metatile(current_id, elev, 0, 0)
                                    current_id += 1
                            selection.active = False
                continue

            if ch in [ord('j'), ord('J')]:
                # Apply modification properties across bounding box areas if selection state is active
                for sy in range(y_min, y_max + 1):
                    for sx in range(x_min, x_max + 1):
                        idx = sy * active_width + sx
                        t_id, el, hf, vf = parse_metatile(active_tiles[idx])
                        active_tiles[idx] = pack_metatile(t_id, max(0, el - 1), hf, vf)
                continue
            elif ch in [ord('k'), ord('K')]:
                for sy in range(y_min, y_max + 1):
                    for sx in range(x_min, x_max + 1):
                        idx = sy * active_width + sx
                        t_id, el, hf, vf = parse_metatile(active_tiles[idx])
                        active_tiles[idx] = pack_metatile(t_id, min(15, el + 1), hf, vf)
                continue

            if browser.visible and browser.filtered_list:
                if ch == curses.KEY_UP:
                    browser.cursor = max(0, browser.cursor - 1)
                    continue
                elif ch == curses.KEY_DOWN:
                    browser.cursor = min(len(browser.filtered_list) - 1, browser.cursor + 1)
                    continue
                elif ch in [curses.KEY_ENTER, 10, 13]:
                    if browser.cursor < len(browser.filtered_list):
                        selected_tile = browser.filtered_list[browser.cursor]
                        for sy in range(y_min, y_max + 1):
                            for sx in range(x_min, x_max + 1):
                                idx = sy * active_width + sx
                                _, el, hf, vf = parse_metatile(active_tiles[idx])
                                active_tiles[idx] = pack_metatile(selected_tile.tile_id, el, hf, vf)
                    continue

            if ord('0') <= ch <= ord('9') and len(input_buffer) < 4:
                input_buffer += chr(ch)
                continue
            elif ch == curses.KEY_UP and c_y > 0:
                if border_mode: border_cursor_idx -= active_width
                else: cursor_idx -= active_width
                input_buffer = ""
            elif ch == curses.KEY_DOWN and c_y < active_height - 1:
                if border_mode: border_cursor_idx += active_width
                else: cursor_idx += active_width
                input_buffer = ""
            elif ch == curses.KEY_LEFT and c_x > 0:
                if border_mode: border_cursor_idx -= 1
                else: cursor_idx -= 1
                input_buffer = ""
            elif ch == curses.KEY_RIGHT and c_x < active_width - 1:
                if border_mode: border_cursor_idx += 1
                else: cursor_idx += 1
                input_buffer = ""
                
            elif ch in [curses.KEY_ENTER, 10, 13]:
                if input_buffer:
                    new_id = int(input_buffer)
                    if new_id <= 1023:
                        for sy in range(y_min, y_max + 1):
                            for sx in range(x_min, x_max + 1):
                                idx = sy * active_width + sx
                                _, el, hf, vf = parse_metatile(active_tiles[idx])
                                active_tiles[idx] = pack_metatile(new_id, el, hf, vf)
                    input_buffer = ""
            elif ch in [curses.KEY_BACKSPACE, 127, 8]:
                input_buffer = input_buffer[:-1]
                
            elif ch in [ord('f'), ord('F')]:
                for sy in range(y_min, y_max + 1):
                    for sx in range(x_min, x_max + 1):
                        idx = sy * active_width + sx
                        t_id, el, hf, vf = parse_metatile(active_tiles[idx])
                        if hf == 0 and vf == 0: hf, vf = 1, 0
                        elif hf == 1 and vf == 0: hf, vf = 0, 1
                        elif hf == 0 and vf == 1: hf, vf = 1, 1
                        else: hf, vf = 0, 0
                        active_tiles[idx] = pack_metatile(t_id, el, hf, vf)
        except KeyboardInterrupt:
            return "CANCEL", current_width, metatiles

def handle_interactive_creation(root_dir, map_name):
    print(f"\n--- Porymap Initialization Wizard: {map_name} ---")
    
    group = input("Map Group (e.g., MAP_GROUP_LITTLEROOT_TOWN): ").strip()
    try:
        width = int(input("Map Width (in blocks, e.g., 20): ").strip())
        height = int(input("Map Height (in blocks, e.g., 20): ").strip())
    except ValueError:
        print("Invalid dimensions entered. Exiting wizard."); sys.exit(1)
        
    p_tileset = input("Primary Tileset (e.g., gTileset_General): ").strip()
    s_tileset = input("Secondary Tileset (e.g., gTileset_Littleroot): ").strip()
    map_type = input("Map Type (e.g., MAP_TYPE_TOWN): ").strip()
    pokenav_loc = input("PokeNav Region Location ID (e.g., REGION_MAP_LITTLEROOT_TOWN): ").strip()
    bgm = input("Map Music Song (e.g., MUS_RG_PALLET): ").strip()
    
    def get_bool(prompt_str):
        return "true" if input(prompt_str + " (y/n): ").strip().lower() in ['y', 'yes'] else "false"

    allow_fly = get_bool("Can player Fly here?")
    show_loc = get_bool("Show location pop-up banner text on entry?")
    allow_run = get_bool("Can player Run inside this map environment?")
    allow_bike = get_bool("Can player ride a Bicycle here?")
    allow_escape = get_bool("Allow usage of Escape Rope / Dig items here?")

    layout_id = f"LAYOUT_{map_name.upper()}"
    layout_folder_name = map_name.replace("_", "").title()
    
    map_dir = os.path.join(root_dir, "data", "maps", map_name)
    layout_dir = os.path.join(root_dir, "data", "layouts", layout_folder_name)
    layouts_json_path = os.path.join(root_dir, "data", "layouts", "layouts.json")
    
    os.makedirs(map_dir, exist_ok=True)
    os.makedirs(layout_dir, exist_ok=True)

    map_bin_path = os.path.join(layout_dir, "map.bin")
    border_bin_path = os.path.join(layout_dir, "border.bin")
    
    default_tile = pack_metatile(0, 0, 0, 0).to_bytes(2, byteorder='little')
    with open(map_bin_path, "wb") as f:
        f.write(default_tile * (width * height))
    with open(border_bin_path, "wb") as f:
        f.write(default_tile * 4)

    map_json_data = {
        "id": f"MAP_{map_name.upper()}",
        "name": f"{map_name.replace('_', ' ').title()}",
        "layout": layout_id,
        "music": bgm,
        "region_map_section": pokenav_loc,
        "requires_flash": "false",
        "weather": "WEATHER_NONE",
        "map_type": map_type,
        "allow_cycling": allow_bike,
        "allow_escaping": allow_escape,
        "allow_running": allow_run,
        "show_map_name": show_loc,
        "battle_scene": "MAP_BATTLE_SCENE_NORMAL",
        "connections": None,
        "object_events": [],
        "warp_events": [],
        "coord_events": [],
        "bg_events": []
    }
    with open(os.path.join(map_dir, "map.json"), "w", encoding="utf-8") as f:
        json.dump(map_json_data, f, indent=4)

    if os.path.exists(layouts_json_path):
        try:
            with open(layouts_json_path, "r", encoding="utf-8") as f:
                layouts_config = json.load(f)
            
            layouts_config["layouts"] = [l for l in layouts_config.get("layouts", []) if l.get("id") != layout_id]
            
            layouts_config["layouts"].append({
                "id": layout_id,
                "name": layout_id,
                "width": width,
                "height": height,
                "primary_tileset": p_tileset,
                "secondary_tileset": s_tileset
            })
            with open(layouts_json_path, "w", encoding="utf-8") as f:
                json.dump(layouts_config, f, indent=4)
        except Exception as e:
            print(f"Warning: Map context built, but failed indexing layouts.json layout: {e}")

    print(f"\nSuccessfully populated base configurations inside engine structure paths!")
    print(f"Map binaries saved under: {layout_dir}")

def main():
    parser = argparse.ArgumentParser(description="Pokeemerald Terminal Map Editor (Poorymap Edition)")
    parser.add_argument("--new", action="store_true", help="Launch Porymap wizard to generate new engine layouts")
    parser.add_argument("root_dir", help="Path directory location to the Pokeemerald root decomp engine project")
    parser.add_argument("map_name", help="Target unique structural identity mapping handle (e.g., gve_town_test)")
    args = parser.parse_args()

    if args.new:
        handle_interactive_creation(args.root_dir, args.map_name)
        sys.exit(0)

    root_dir = args.root_dir
    map_name = args.map_name
    
    map_json_path = os.path.join(root_dir, "data", "maps", map_name, "map.json")
    layouts_json_path = os.path.join(root_dir, "data", "layouts", "layouts.json")
    
    if not os.path.exists(map_json_path) or not os.path.exists(layouts_json_path):
        print("Error: Required map configuration system files missing. Use --new to create them.")
        sys.exit(1)
        
    try:
        with open(map_json_path, "r", encoding="utf-8") as f:
            layout_id_name = json.load(f).get("layout", "")
    except Exception as e:
        print(f"Error parsing map layout key: {e}"); sys.exit(1)

    width = None
    allowed_tilesets = set()
    try:
        with open(layouts_json_path, "r", encoding="utf-8") as f:
            layouts_data = json.load(f)
            for item in layouts_data.get("layouts", []):
                if item.get("id") == layout_id_name:
                    width = int(item.get("width", 0))
                    p_ts = item.get("primary_tileset", "")
                    s_ts = item.get("secondary_tileset", "")
                    if p_ts: allowed_tilesets.add(normalize_tileset_name(p_ts))
                    if s_ts: allowed_tilesets.add(normalize_tileset_name(s_ts))
                    break
    except Exception as e:
        print(f"Error parsing global layouts configurations: {e}"); sys.exit(1)

    layout_name_clean = layout_id_name.replace("LAYOUT_", "").title().replace("_", "")
    layout_dir_path = os.path.join(root_dir, "data", "layouts", layout_name_clean)
    if not os.path.exists(layout_dir_path):
        layout_dir_path = os.path.join(root_dir, "data", "layouts", map_name)
        
    filepath = os.path.join(layout_dir_path, "map.bin")
    border_path = os.path.join(layout_dir_path, "border.bin")

    border_blocks = []
    if os.path.exists(border_path):
        with open(border_path, "rb") as f:
            while (byte_data := f.read(2)):
                if len(byte_data) == 2:
                    border_blocks.append(int.from_bytes(byte_data, byteorder='little'))

    metatiles = []
    if os.path.exists(filepath):
        with open(filepath, "rb") as f:
            while (byte_data := f.read(2)):
                if len(byte_data) == 2:
                    metatiles.append(int.from_bytes(byte_data, byteorder='little'))

    try:
        action, final_width, final_metatiles = curses.wrapper(
            curses_main, filepath, width, metatiles, allowed_tilesets, border_blocks
        )
    except KeyboardInterrupt:
        action = "CANCEL"

    if action == "SAVE":
        final_height = (len(final_metatiles) + final_width - 1) // final_width
        print(f"\nSaving layout alterations back to {final_width}x{final_height}...")
        
        with open(filepath, "wb") as f:
            for entry_int in final_metatiles:
                f.write(entry_int.to_bytes(2, byteorder='little'))
                
        if os.path.exists(border_path) and border_blocks:
            with open(border_path, "wb") as f:
                for entry_int in border_blocks:
                    f.write(entry_int.to_bytes(2, byteorder='little'))
                    
        try:
            with open(layouts_json_path, "r", encoding="utf-8") as f:
                layouts_config = json.load(f)
            
            for item in layouts_config.get("layouts", []):
                if item.get("id") == layout_id_name:
                    item["width"] = final_width
                    item["height"] = final_height
                    break
                    
            with open(layouts_json_path, "w", encoding="utf-8") as f:
                json.dump(layouts_config, f, indent=4)
            print("Successfully saved data and updated engine project configuration files!")
        except Exception as e:
            print(f"Map saved, but failed to write dimensions update to layouts.json: {e}")
    else:
        print("\nEditing session cancelled cleanly. No changes saved.")

if __name__ == "__main__":
    main()
