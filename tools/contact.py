"""Tile screenshots into one contact sheet: python contact.py out.png a.png b.png ..."""
import sys
from PIL import Image, ImageDraw
files = sys.argv[2:]
cols = min(len(files), int(sys.argv[1].split('@')[1]) if '@' in sys.argv[1] else 6)
out = sys.argv[1].split('@')[0]
ims = [Image.open(f).convert('RGB') for f in files]
w, h = ims[0].size
rows = (len(ims) + cols - 1) // cols
sheet = Image.new('RGB', (cols * (w + 4), rows * (h + 16)), (40, 40, 40))
d = ImageDraw.Draw(sheet)
for i, (im, f) in enumerate(zip(ims, files)):
    x, y = (i % cols) * (w + 4), (i // cols) * (h + 16)
    sheet.paste(im, (x, y + 14))
    d.text((x + 2, y + 1), __import__('os').path.basename(f), fill=(255, 255, 0))
sheet.save(out)
