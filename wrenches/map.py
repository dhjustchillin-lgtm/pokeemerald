import sys
import os
import csv
import json
import re
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
        print(f"Error: Missing '{csv_path}' in current working directory.")
        sys.exit(1)
        
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
                    tileset=ts_name,
                    tile_id=int(row.get("MetatileID", 0)),
                    behavior_name=row.get("BehaviorName", "UNKNOWN")
                ))
    except Exception as e:
        print(f"Error parsing '{csv_path}': {e}")
        sys.exit(1)
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

    all_browser_tiles = load_metatiles_csv(allowed_tilesets)
    browser = Browser()
    update_browser_filtering(all_browser_tiles, browser)

    cursor_idx = 0
    input_buffer = ""
    scroll_x, scroll_y = 0, 0
    search_mode = False
    
    # Global Clipboard for Full Block Copy/Pasting
    clipboard_packed_tile = None
    
    current_width = width
    total_tiles = len(metatiles)
    current_height = (total_tiles + current_width - 1) // current_width

    while True:
        try:
            stdscr.erase()
            term_lines, term_cols = stdscr.getmaxyx()

            map_split_weight = 0.70 if browser.visible else 1.0
            map_cols = int(term_cols * map_split_weight)
            browser_cols = term_cols - map_cols - 2 if browser.visible else 0

            c_x, c_y = cursor_idx % current_width, cursor_idx // current_width

            max_visible_cols = max(1, (map_cols - 4) // 6)
            max_visible_rows = max(1, term_lines - 12)

            if c_x < scroll_x: scroll_x = c_x
            elif c_x >= scroll_x + max_visible_cols: scroll_x = c_x - max_visible_cols + 1
            if c_y < scroll_y: scroll_y = c_y
            elif c_y >= scroll_y + max_visible_rows: scroll_y = c_y - max_visible_rows + 1

            if term_lines > 0:
                stdscr.addstr(0, 0, "=== POKEEMERALD TERMINAL MAP EDITOR (Poorymap) ===", curses.color_pair(3))
            if term_lines > 1:
                stdscr.addstr(1, 0, "Arrows: Move | J/K: Elev | F: Flip | C/V: Copy/Paste Tile | R: Resize | N: Browser")

            if scroll_y > 0 and term_lines > 2:
                stdscr.addstr(2, 0, "     ^^^ (More rows above) ^^^")

            # Map Matrix Core Renderer
            for y in range(scroll_y, min(current_height, scroll_y + max_visible_rows)):
                screen_y = 3 + (y - scroll_y)
                if screen_y >= term_lines - 8: break
                
                stdscr.addstr(screen_y, 0, "< " if scroll_x > 0 else "  ")
                
                for x in range(scroll_x, min(current_width, scroll_x + max_visible_cols)):
                    i = y * current_width + x
                    if i >= len(metatiles): break
                    
                    t_id, elev, hf, vf = parse_metatile(metatiles[i])
                    
                    if i == cursor_idx:
                        disp = input_buffer.ljust(4, '_') if input_buffer else f"{t_id:04d}"
                        stdscr.addstr(screen_y, 2 + (x - scroll_x) * 6, f"[{disp[:2]}{disp[2:]}]", curses.color_pair(100))
                    else:
                        pal_idx = ELEVATION_COLORS[elev % len(ELEVATION_COLORS)]
                        attr_color = curses.color_pair(pal_idx)
                        if hf: attr_color |= curses.A_UNDERLINE
                        if vf: attr_color |= curses.A_STANDOUT
                        stdscr.addstr(screen_y, 2 + (x - scroll_x) * 6, f" {t_id:04d} ", attr_color)
                
                if current_width > scroll_x + max_visible_cols and (2 + max_visible_cols * 6) < term_cols:
                    stdscr.addstr(screen_y, 2 + max_visible_cols * 6, ">")

            target_footer_y = 3 + max_visible_rows
            if current_height > scroll_y + max_visible_rows and target_footer_y < (term_lines - 7):
                stdscr.addstr(target_footer_y, 0, "     vvv (More rows below) vvv")

            if cursor_idx < len(metatiles):
                c_tile, c_elev, c_h, c_v = parse_metatile(metatiles[cursor_idx])
                flip_status = "None" if not (c_h or c_v) else ("Both" if (c_h and c_v) else ("Horiz" if c_h else "Vert"))
                clip_status = "Empty" if clipboard_packed_tile is None else "Loaded"
                if term_lines - 6 >= 0:
                    stdscr.addstr(term_lines - 6, 0, f"Map -> X: {c_x:02d}, Y: {c_y:02d} | Size: {current_width}x{current_height} | ID: {c_tile:04d} | Elev: {c_elev:02d} | Flips: {flip_status} | Clip: {clip_status}", curses.color_pair(3))

            # Dynamic Side Browser Component Block
            if browser.visible:
                if browser.filtered_list:
                    if browser.cursor < browser.scroll: browser.scroll = browser.cursor
                    elif browser.cursor >= browser.scroll + max_visible_rows: browser.scroll = browser.cursor - max_visible_rows + 1
                else:
                    browser.scroll = 0
                    browser.cursor = 0

                if term_lines > 2 and (map_cols + 1) < term_cols:
                    stdscr.addstr(2, map_cols + 1, "TILE BROWSER".ljust(browser_cols), curses.A_REVERSE)
                
                end_browser_idx = min(len(browser.filtered_list), browser.scroll + max_visible_rows)
                for idx in range(browser.scroll, end_browser_idx):
                    b_scr_y = 3 + (idx - browser.scroll)
                    if b_scr_y >= term_lines - 8: break
                    
                    if (map_cols + 1) < term_cols:
                        tile = browser.filtered_list[idx]
                        row_txt = f"{tile.tile_id:04d} {tile.behavior_name[:10]}".ljust(browser_cols)[:browser_cols]
                        
                        if idx == browser.cursor:
                            stdscr.addstr(b_scr_y, map_cols + 1, row_txt, curses.color_pair(100))
                        else:
                            c_pair = get_row_color_pair(tile.behavior_name)
                            stdscr.addstr(b_scr_y, map_cols + 1, row_txt, curses.color_pair(c_pair))

            if term_lines - 2 >= 0:
                stdscr.addstr(term_lines - 2, 0, "Footer: [ENTER] Paste ID | [N] Toggle Browser | [/] Search | [Ctrl+S] Save & Close", curses.A_DIM)

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

            if ch in [ord('r'), ord('R')]:
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

            # SINGLE KEY COPY / PASTE (No Control modifiers)
            if ch in [ord('c'), ord('C')]:
                if cursor_idx < len(metatiles):
                    clipboard_packed_tile = metatiles[cursor_idx]
                continue
            elif ch in [ord('v'), ord('V')]:
                if clipboard_packed_tile is not None and cursor_idx < len(metatiles):
                    metatiles[cursor_idx] = clipboard_packed_tile
                continue

            # J / K ELEVATION CHANGER
            if ch in [ord('j'), ord('J')]:
                t_id, el, hf, vf = parse_metatile(metatiles[cursor_idx])
                el = max(0, el - 1)
                metatiles[cursor_idx] = pack_metatile(t_id, el, hf, vf)
                continue
            elif ch in [ord('k'), ord('K')]:
                t_id, el, hf, vf = parse_metatile(metatiles[cursor_idx])
                el = min(15, el + 1)
                metatiles[cursor_idx] = pack_metatile(t_id, el, hf, vf)
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
                        _, el, hf, vf = parse_metatile(metatiles[cursor_idx])
                        metatiles[cursor_idx] = pack_metatile(selected_tile.tile_id, el, hf, vf)
                    continue

            if ord('0') <= ch <= ord('9') and len(input_buffer) < 4:
                input_buffer += chr(ch)
                continue
            elif ch == curses.KEY_UP and cursor_idx - current_width >= 0:
                cursor_idx -= current_width; input_buffer = ""
            elif ch == curses.KEY_DOWN and cursor_idx + current_width < len(metatiles):
                cursor_idx += current_width; input_buffer = ""
            elif ch == curses.KEY_LEFT and cursor_idx % current_width > 0:
                cursor_idx -= 1; input_buffer = ""
            elif ch == curses.KEY_RIGHT and (cursor_idx % current_width) < (current_width - 1) and (cursor_idx + 1 < len(metatiles)):
                cursor_idx += 1; input_buffer = ""
                
            elif ch in [curses.KEY_ENTER, 10, 13]:
                if input_buffer:
                    new_id = int(input_buffer)
                    if new_id <= 1023:
                        _, el, hf, vf = parse_metatile(metatiles[cursor_idx])
                        metatiles[cursor_idx] = pack_metatile(new_id, el, hf, vf)
                    input_buffer = ""
            elif ch in [curses.KEY_BACKSPACE, 127, 8]:
                input_buffer = input_buffer[:-1]
                
            elif ch in [ord('f'), ord('F')]:
                t_id, el, hf, vf = parse_metatile(metatiles[cursor_idx])
                if hf == 0 and vf == 0: hf, vf = 1, 0
                elif hf == 1 and vf == 0: hf, vf = 0, 1
                elif hf == 0 and vf == 1: hf, vf = 1, 1
                else: hf, vf = 0, 0
                metatiles[cursor_idx] = pack_metatile(t_id, el, hf, vf)
        except KeyboardInterrupt:
            return "CANCEL", current_width, metatiles

def main():
    if len(sys.argv) < 3:
        print("Usage: python map.py <path/to/pokeemerald_root/> <map_name>")
        sys.exit(1)
        
    root_dir = sys.argv[1]
    map_name = sys.argv[2]
    
    map_json_path = os.path.join(root_dir, "data", "maps", map_name, "map.json")
    layouts_json_path = os.path.join(root_dir, "data", "layouts", "layouts.json")
    
    if not os.path.exists(map_json_path) or not os.path.exists(layouts_json_path):
        print("Error: Required map configuration system files missing.")
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

