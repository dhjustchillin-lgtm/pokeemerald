from PIL import Image
import sys

png = sys.argv[1]
palfile = sys.argv[2]
outfile = sys.argv[3]

#
# Read JASC-PAL
#
with open(palfile) as f:
    lines = [x.strip() for x in f if x.strip()]

count = int(lines[2])
newpal = [tuple(map(int, x.split())) for x in lines[3:3 + count]]

img = Image.open(png)

oldraw = img.getpalette()
oldpal = [tuple(oldraw[i:i+3]) for i in range(0, len(oldraw), 3)]

#
# Find closest palette entry
#
def color_distance(c1, c2):
    dr = c1[0] - c2[0]
    dg = c1[1] - c2[1]
    db = c1[2] - c2[2]
    return dr*dr + dg*dg + db*db

#
# Build lookup:
# old index -> closest new index
#
lookup = {}

for old_index, color in enumerate(oldpal):
    best_index = 0
    best_dist = None

    for new_index, new_color in enumerate(newpal):
        dist = color_distance(color, new_color)
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_index = new_index

    lookup[old_index] = best_index

#
# Rewrite indices
#
pix = list(img.getdata())
pix = [lookup[i] for i in pix]
img.putdata(pix)

#
# Install new palette
#
flat = []

for c in newpal:
    flat.extend(c)

flat.extend([0] * (768 - len(flat)))

img.putpalette(flat)

img.save(outfile)
