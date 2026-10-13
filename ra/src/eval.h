/*
	eval.h: a small RetroAchievements trigger evaluator.

	It covers the condition features the Beyond the Beyond set uses (achievements.py
	refuses any other) and follows rcheevos 12 (trigger.c, condset.c):
	  - memory references: 8/16-bit, bit 0-7, upper/lower nibble, bit count;
	    value and delta (last frame's value);
	  - flags: AddSource, SubSource, AndNext, OrNext, ResetNextIf, AddHits, SubHits,
	    ResetIf, Measured (no Measured progress is kept), Trigger;
	  - hit counts, core group plus alt groups;
	  - the WAITING state: a trigger that is true when it is activated (or right after
	    it was reset) fires only after it has been false once.
	rcheevos tests the conditions of a group in a different order (ResetIf first, ...),
	but without PauseIf the result is the same: a frame where any ResetIf is true resets
	all hit counts and never triggers, and on other frames every condition is tested.
	ra/host/diff.c checks it against rcheevos frame by frame.
*/
#pragma once
#include <stdint.h>

/* memory reference: address (21 bits) | 1 << 24 for a 16-bit word, else a byte */
#define MEM_WORD (1u << 24)

/* operand: kind << 14 | part << 10 | index (memory reference or constant) */
#define OPK_CONST 0
#define OPK_VALUE 1
#define OPK_DELTA 2
enum { PART_ALL, PART_BIT0, PART_BIT7 = PART_BIT0 + 7, PART_LOW4, PART_HIGH4, PART_BITCOUNT };

enum { CT_STANDARD, CT_ADD_SOURCE, CT_SUB_SOURCE, CT_AND_NEXT, CT_OR_NEXT, CT_RESET_NEXT_IF,
       CT_ADD_HITS, CT_SUB_HITS, CT_RESET_IF, CT_MEASURED, CT_TRIGGER };
enum { OP_NONE, OP_EQ, OP_NE, OP_LT, OP_LE, OP_GT, OP_GE };

/* a condition in the code stream: type | op << 4, lhs (u16, little endian), then for all
   but AddSource / SubSource: rhs (u16), hit target (u8) */
struct ra_cond { uint8_t type_op, hits; uint16_t lhs, rhs; };
/* group: its first byte in ra_code, its first hit count (one per condition), conditions */
struct ra_group { uint16_t code, hit; uint8_t count, pad; };
/* pure: no hit targets, ResetIf, AddHits/SubHits or ResetNextIf, so the result depends on
   this frame's memory only and testing may stop at the first false condition */
struct ra_ach { uint16_t group; uint8_t ngroups, pure; };

/* the compiled set (gen/set.c) */
extern const uint16_t ra_nmem, ra_nconst, ra_ncond, ra_nach;
extern const uint32_t ra_mem[];
extern const uint16_t ra_const[];
extern const uint8_t ra_code[];
extern const struct ra_group ra_group[];
extern const struct ra_ach ra_ach[];

/* state, per memory reference / condition / achievement */
#define ST_WAITING   0
#define ST_ACTIVE    1
#define ST_TRIGGERED 2
#define ST_OFF       3   /* unlocked earlier: not evaluated */
extern uint16_t ra_val[], ra_dlt[];
extern uint8_t ra_hit[];                      /* saturates at 255 (only > 0 and == target matter) */
extern uint8_t ra_st[], ra_hh[];

void ra_eval_reset(void);                     /* all achievements WAITING, hits 0, memory refs 0 */
/* one frame: update the memory references, test every achievement; returns how many
   triggered (their indices in out[]) */
uint32_t ra_eval_frame(uint8_t* out);
const uint8_t* ra_decode(const uint8_t* p, struct ra_cond* c);
