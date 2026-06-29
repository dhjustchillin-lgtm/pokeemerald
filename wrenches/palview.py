import sys
import os

def parse_jasc_pal(file_path):
    """Parses a JASC-PAL file and returns a list of (R, G, B) tuples."""
    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' not found.")
        sys.exit(1)
        
    colors = []
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]
        
    if len(lines) < 3 or lines[0] != "JASC-PAL" or lines[1] != "0100":
        print("Error: Not a valid JASC-PAL file.")
        sys.exit(1)
        
    try:
        num_colors = int(lines[2])
        for line in lines[3:3 + num_colors]:
            parts = line.split()
            if len(parts) >= 3:
                r, g, b = map(int, parts[:3])
                colors.append((r, g, b))
    except ValueError:
        print("Error: Failed to parse color data.")
        sys.exit(1)
        
    return colors

def display_palette_terminal(colors):
    """Displays colors directly in the terminal using ANSI escape codes."""
    print("\n--- Palette Colors ---")
    for index, (r, g, b) in enumerate(colors):
        hex_color = f"#{r:02x}{g:02x}{b:02x}"
        
        # ANSI escape code for background color: \033[48;2;R;G;Bm
        # We print a few spaces with that background to create a "block"
        color_block = f"\033[48;2;{r};{g};{b}m      \033[0m"
        
        print(f"[{index:02d}] {color_block}  HEX: {hex_color} | RGB: ({r:3}, {g:3}, {b:3})")
    print("----------------------\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python palview_term.py <path_to_palette.pal>")
        sys.exit(1)
        
    pal_path = sys.argv[1]
    palette_colors = parse_jasc_pal(pal_path)
    display_palette_terminal(palette_colors)
