#!/bin/sh
# usage: build.sh BASE out.bin   (inside the mipsel container, cwd = ra/src)
set -e
BASE=$1; OUT=$2
CC=mipsel-linux-gnu-gcc
CF="-Iinc -I. -march=r3000 -mtune=r3000 -mno-abicalls -fno-pic -G0 -mno-gpopt -msoft-float -Os -ffreestanding -fno-builtin -nostdlib -Wall -Wno-unused-function -fno-strict-aliasing -mno-check-zero-division"
mkdir -p obj
$CC $CF -c start.S -o obj/start.o
$CC $CF -c btb_ra.c -o obj/btb_ra.o
$CC $CF -c eval.c -o obj/eval.o
$CC $CF -c gen/set.c -o obj/set.o
$CC $CF -c gen/icon.c -o obj/icon.o
mipsel-linux-gnu-ld -T link.ld --defsym BASE=$BASE -o obj/ra.elf obj/start.o obj/btb_ra.o obj/eval.o obj/set.o obj/icon.o
mipsel-linux-gnu-objcopy -O binary -R .bss obj/ra.elf $OUT
mipsel-linux-gnu-nm -n obj/ra.elf > obj/ra.map
mipsel-linux-gnu-size obj/*.o obj/ra.elf
