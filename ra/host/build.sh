#!/bin/sh
# host build of diff.c (w64devkit gcc); RCHEEVOS = rcheevos 12 checkout
RC=${RCHEEVOS:-/e/projects/nds-bootstrap-ra/external/rcheevos}
cd "$(dirname "$0")"
PATH=/c/w64devkit/bin:$PATH gcc -O2 -std=gnu99 -Wall -Wno-unused-function -DRA_RAM=host_ram -include stdint.h -I$RC/include -I$RC/src -I$RC/src/rcheevos -I../src \
  -D'RA_RAM_DECL=extern uint8_t* host_ram;' diff.c ../src/eval.c ../src/gen/set.c \
  $RC/src/rcheevos/alloc.c $RC/src/rcheevos/format.c $RC/src/rcheevos/lboard.c $RC/src/rcheevos/operand.c \
  $RC/src/rcheevos/richpresence.c $RC/src/rcheevos/runtime.c $RC/src/rcheevos/value.c $RC/src/rc_util.c \
  $RC/src/rc_compat.c $RC/src/rhash/md5.c $RC/src/rcheevos/memref.c $RC/src/rcheevos/condset.c \
  $RC/src/rcheevos/condition.c $RC/src/rcheevos/trigger.c -lm -o diff.exe
