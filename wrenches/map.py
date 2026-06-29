import sys
import os
import csv
import curses
from dataclasses import dataclass, field

# 16 standard ANSI colors for map elevation rendering
ELEVATION_COLORS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]

# Keyword-based colors for the Browser rows
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

def load_metatiles_csv():
    csv_path = "metatiles.csv"
    if not os.path.exists(csv_path):
        print(f"Error: Missing '{csv_path}' in the current working directory.")
        sys.exit(1)
        
    tiles = []
    try:
        with open(csv_path, mode="r", encoding="utf8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                tiles.append(BrowserTile(
                    tileset=row.get("Tileset", "unknown"),
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
    return 7  # White fallback

def update_browser_filtering(all_tiles, browser):
    filtered = []
    s_term = browser.search.strip().lower()
    
    # Check if the search term represents an integer ID
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
            # Handle strict numeric matching alongside the standard textual fallback rules
            matches_numeric = search_is_numeric and (t.tile_id == search_numeric_val)
            matches_text = (s_term in t.behavior_name.lower() or s_term in t.tileset.lower() or s_term in str(t.tile_id))
            
            if not (matches_numeric or matches_text):
                continue
        filtered.append(t)
        
    browser.filtered_list = filtered
    if browser.cursor >= len(filtered):
        browser.cursor = max(0, len(filtered) - 1)

def curses_main(stdscr, filepath, width, metatiles):
    curses.use_default_colors()
    curses.curs_set(1)
    stdscr.keypad(True)
    
    # Initialize pairs for colors 0-15 over terminal default backgrounds
    for i in range(0, 16):
        curses.init_pair(i + 1, i, -1)
    curses.init_pair(100, curses.COLOR_BLACK, curses.COLOR_WHITE)  # Selection Focus Highlight

    all_browser_tiles = load_metatiles_csv()
    browser = Browser()
    update_browser_filtering(all_browser_tiles, browser)

    total_tiles = len(metatiles)
    cursor_idx = 0
    input_buffer = ""
    scroll_x, scroll_y = 0, 0
    search_mode = False

    while True:
        stdscr.erase()
        term_lines, term_cols = stdscr.getmaxyx()

        # Dynamic screen split rules
        map_split_weight = 0.70 if browser.visible else 1.0
        map_cols = int(term_cols * map_split_weight)
        browser_cols = term_cols - map_cols - 2 if browser.visible else 0

        height = (total_tiles + width - 1) // width
        c_x, c_y = cursor_idx % width, cursor_idx // width

        max_visible_cols = max(1, (map_cols - 4) // 6)
        max_visible_rows = max(1, term_lines - 12)

        # Camera scroll calculations
        if c_x < scroll_x: scroll_x = c_x
        elif c_x >= scroll_x + max_visible_cols: scroll_x = c_x - max_visible_cols + 1
        if c_y < scroll_y: scroll_y = c_y
        elif c_y >= scroll_y + max_visible_rows: scroll_y = c_y - max_visible_rows + 1

        # Application Headers
        stdscr.addstr(0, 0, "=== POKEEMERALD TERMINAL MAP EDITOR (Poorymap) ===", curses.color_pair(3))
        stdscr.addstr(1, 0, "Arrows: Move Map | [0-9]: ID Buffer | [F]: Flip | [J/K]: Elev +/- | [N]: Browser | Ctrl+S: Save")

        if scroll_y > 0:
            stdscr.addstr(2, 0, "     ^^^ (More rows above) ^^^")

        # Map Matrix Core Renderer
        for y in range(scroll_y, min(height, scroll_y + max_visible_rows)):
            screen_y = 3 + (y - scroll_y)
            if screen_y >= term_lines - 8: break
            
            stdscr.addstr(screen_y, 0, "< " if scroll_x > 0 else "  ")
            
            for x in range(scroll_x, min(width, scroll_x + max_visible_cols)):
                i = y * width + x
                if i >= total_tiles: break
                
                t_id, elev, hf, vf = parse_metatile(metatiles[i])
                
                if i == cursor_idx:
                    disp = input_buffer.ljust(4, '_') if input_buffer else f"{t_id:04d}"
                    stdscr.addstr(screen_y, 2 + (x - scroll_x) * 6, f"[{disp[:2]}{disp[2:]}]", curses.color_pair(100))
                else:
                    attr_color = curses.color_pair((elev % 16) + 1)
                    if hf: attr_color |= curses.A_UNDERLINE
                    if vf: attr_color |= curses.A_STANDOUT
                    stdscr.addstr(screen_y, 2 + (x - scroll_x) * 6, f" {t_id:04d} ", attr_color)
            
            if width > scroll_x + max_visible_cols:
                stdscr.addstr(screen_y, 2 + max_visible_cols * 6, ">")

        if height > scroll_y + max_visible_rows:
            stdscr.addstr(3 + max_visible_rows, 0, "     vvv (More rows below) vvv")

        # Live Map Metatile Metadata Readout Bar
        c_tile, c_elev, c_h, c_v = parse_metatile(metatiles[cursor_idx])
        flip_status = "None" if not (c_h or c_v) else ("Both" if (c_h and c_v) else ("Horiz" if c_h else "Vert"))
        stdscr.addstr(term_lines - 6, 0, f"Map Position -> X: {c_x:02d}, Y: {c_y:02d} | ID: {c_tile:04d} | Elev: {c_elev:02d} | Flips: {flip_status}", curses.color_pair(3))

        # Dynamic Side Browser Component Block
        if browser.visible:
            if browser.cursor < browser.scroll: browser.scroll = browser.cursor
            elif browser.cursor >= browser.scroll + max_visible_rows: browser.scroll = browser.cursor - max_visible_rows + 1

            stdscr.addstr(2, map_cols + 1, "TILE BROWSER".ljust(browser_cols), curses.A_REVERSE)
            
            for idx in range(browser.scroll, browser.scroll + max_visible_rows):
                b_scr_y = 3 + (idx - browser.scroll)
                if b_scr_y >= term_lines - 8: break
                
                if idx < len(browser.filtered_list):
                    tile = browser.filtered_list[idx]
                    row_txt = f"{tile.tile_id:04d} {tile.behavior_name[:10]} {tile.tileset[:10]}".ljust(browser_cols)[:browser_cols]
                    
                    if idx == browser.cursor:
                        stdscr.addstr(b_scr_y, map_cols + 1, row_txt, curses.color_pair(100))
                    else:
                        c_pair = get_row_color_pair(tile.behavior_name)
                        stdscr.addstr(b_scr_y, map_cols + 1, row_txt, curses.color_pair(c_pair + 1))

            # Bottom Metadata Status Row for Browser Node
            if browser.filtered_list and browser.cursor < len(browser.filtered_list):
                sel = browser.filtered_list[browser.cursor]
                status_str = f"Browser Selection -> ID: {sel.tile_id} | Name: {sel.behavior_name} | Tileset: {sel.tileset}"
                stdscr.addstr(term_lines - 4, 0, status_str[:term_cols - 1], curses.A_BOLD)

        # Footer Actions Hint Readout Map
        stdscr.addstr(term_lines - 2, 0, "Footer: [ENTER] Paste ID | [N] Toggle Browser | [/] Search | [Backspace] Clear Search", curses.A_DIM)

        if search_mode:
            stdscr.addstr(term_lines - 3, 0, f"SEARCH MODE (Mixed ID/Text): {browser.search}_", curses.color_pair(6))

        stdscr.refresh()
        
        # User input capture sequence
        ch = stdscr.getch()

        if ch == 19:  # Ctrl+S
            return "SAVE"
        elif ch in [3, 27]:  # Ctrl+C or Escape break fallback
            return "CANCEL"

        if search_mode:
            if ch in [curses.KEY_ENTER, 10, 13]:
                search_mode = False
            elif ch in [curses.KEY_BACKSPACE, 127, 8]:
                if browser.search:
                    browser.search = browser.search[:-1]
                    update_browser_filtering(all_browser_tiles, browser)
                else:
                    search_mode = False  # Backspacing an empty field cancels search
            elif 32 <= ch <= 126:
                browser.search += chr(ch)
                update_browser_filtering(all_browser_tiles, browser)
            continue

        # Global Action Router Mapping
        if ch in [ord('n'), ord('N')]:
            browser.visible = not browser.visible
            continue
        elif ch == ord('/'):
            if browser.visible:
                search_mode = True
            continue

        # Split Controls Delegation
        if browser.visible:
            if ch == curses.KEY_UP:
                browser.cursor = max(0, browser.cursor - 1)
                continue
            elif ch == curses.KEY_DOWN:
                browser.cursor = min(len(browser.filtered_list) - 1, browser.cursor + 1)
                continue
            elif ch == curses.KEY_PPAGE:
                browser.cursor = max(0, browser.cursor - 10)
                continue
            elif ch == curses.KEY_NPAGE:
                browser.cursor = min(len(browser.filtered_list) - 1, browser.cursor + 10)
                continue
            elif ch == curses.KEY_HOME:
                browser.cursor = 0
                continue
            elif ch == curses.KEY_END:
                browser.cursor = len(browser.filtered_list) - 1
                continue
            elif ch in [curses.KEY_ENTER, 10, 13]:  # Paste ID directly into active location
                if browser.filtered_list and browser.cursor < len(browser.filtered_list):
                    selected_tile = browser.filtered_list[browser.cursor]
                    _, el, hf, vf = parse_metatile(metatiles[cursor_idx])
                    metatiles[cursor_idx] = pack_metatile(selected_tile.tile_id, el, hf, vf)
                continue

        # Fallback Map Grid Navigation and Bitfield Operators Component Block
        if ord('0') <= ch <= ord('9') and len(input_buffer) < 4:
            input_buffer += chr(ch)
            continue
        elif ch == curses.KEY_UP and cursor_idx - width >= 0:
            cursor_idx -= width; input_buffer = ""
        elif ch == curses.KEY_DOWN and cursor_idx + width < total_tiles:
            cursor_idx += width; input_buffer = ""
        elif ch == curses.KEY_LEFT and cursor_idx % width > 0:
            cursor_idx -= 1; input_buffer = ""
        elif ch == curses.KEY_RIGHT and (cursor_idx % width) < (width - 1) and (cursor_idx + 1 < total_tiles):
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
            
        elif ch in [ord('j'), ord('J')]:
            t_id, el, hf, vf = parse_metatile(metatiles[cursor_idx])
            metatiles[cursor_idx] = pack_metatile(t_id, (el + 1) & 0x0F, hf, vf)
        elif ch in [ord('k'), ord('K')]:
            t_id, el, hf, vf = parse_metatile(metatiles[cursor_idx])
            metatiles[cursor_idx] = pack_metatile(t_id, (el - 1) & 0x0F, hf, vf)

def main():
    if len(sys.argv) < 3:
        print("Usage: python map.py <path/to/map.bin> <width>")
        sys.exit(1)
        
    filepath = sys.argv[1]
    try:
        width = int(sys.argv[2])
    except ValueError:
        print("Error: Width must be an integer.")
        sys.exit(1)
        
    if not os.path.exists(filepath):
        print(f"Error: File '{filepath}' not found.")
        sys.exit(1)

    metatiles = []
    with open(filepath, "rb") as f:
        while (byte_data := f.read(2)):
            if len(byte_data) == 2:
                metatiles.append(int.from_bytes(byte_data, byteorder='little'))

    if not metatiles:
        print("Error: Map file is empty.")
        sys.exit(1)

    action = curses.wrapper(curses_main, filepath, width, metatiles)

    if action == "SAVE":
        print("\nSaving map data back to file...")
        with open(filepath, "wb") as f:
            for entry_int in metatiles:
                f.write(entry_int.to_bytes(2, byteorder='little'))
        print("Saved successfully!")
    else:
        print("\nEditing cancelled. No changes saved.")

if __name__ == "__main__":
    main()
