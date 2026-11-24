from pathlib import Path
import struct
import zlib

size = 64
scale = 3
bars = [(20, 30, 3.8, 13), (27, 30, 3.8, 24), (34, 30, 3.8, 31), (41, 30, 3.8, 17)]
def pixel(x, y):
    dx = max(12 - x, 0, x - 52)
    dy = max(12 - y, 0, y - 52)
    if dx * dx + dy * dy > 11 * 11:
        return (0, 0, 0, 0)
    for cx, cy, width, height in bars:
        if abs(x - cx) <= width / 2 and abs(y - cy) <= height / 2:
            return (250, 246, 255, 255)
    fraction = (x + y) / 126
    return (int(100 - 68 * fraction), int(81 - 60 * fraction), int(202 - 112 * fraction), 255)

rows = bytearray()
for y in range(size):
    rows.append(0)
    for x in range(size):
        values = [pixel(x+(i+.5)/scale,y+(j+.5)/scale) for i in range(scale) for j in range(scale)]
        count = sum(v[3]>0 for v in values)
        if count:
            rows.extend(round(sum(v[i] for v in values)/count) for i in range(3))
            rows.append(round(255*count/(scale*scale)))
        else:
            rows.extend((0,0,0,0))
def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB",size,size,8,6,0,0,0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND",b"")
ico = struct.pack("<HHHBBBBHHII",0,1,1,size,size,0,0,1,32,len(png),22)+png
Path(__file__).with_name("tinggao.ico").write_bytes(ico)

