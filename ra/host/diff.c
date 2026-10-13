/*
	diff.c: ra/src/eval.c against stock rcheevos, frame by frame.

	    diff set.txt sessions frames seed

	Each session starts both evaluators fresh and runs random RAM for `frames` frames.
	The RAM is steered toward one achievement per session: its memory references get the
	constants they are compared with (or a neighbour) most frames, with noise on every other
	reference, values held for a few frames (hit counts), and nudged up and down (deltas).
	Every frame, the trigger state of every achievement must match (WAITING / ACTIVE or
	PRIMED / TRIGGERED), and so must the frames they trigger on.
*/
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "rc_runtime.h"
#include "rc_runtime_types.h"
#include "eval.h"

#define RAM 0x200000u
uint8_t* host_ram;

static uint32_t peek(uint32_t a, uint32_t n, void* ud) {
	const uint8_t* p = host_ram + a;
	(void)ud;
	if (a >= RAM || RAM - a < n) return 0;
	return n == 1 ? p[0] : n == 2 ? (uint32_t)(p[0] | p[1] << 8) : n == 3 ? (uint32_t)(p[0] | p[1] << 8 | p[2] << 16)
		: (uint32_t)(p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24);
}

static uint32_t rng = 1;
static uint32_t rnd(void) { rng ^= rng << 13; rng ^= rng >> 17; rng ^= rng << 5; return rng; }
static uint32_t below(uint32_t n) { return rnd() % n; }

/* op: part << 10 | memory reference (an operand without its kind) */
static uint32_t read_op(uint32_t op) {
	const uint32_t m = ra_mem[op & 0x3FF], part = op >> 10 & 15;
	const uint8_t* p = host_ram + (m & 0xFFFFFF);
	const uint32_t v = m & MEM_WORD ? (uint32_t)(p[0] | p[1] << 8) : p[0];
	switch (part) {
	case PART_ALL: return v;
	case PART_LOW4: return v & 15;
	case PART_HIGH4: return v >> 4 & 15;
	case PART_BITCOUNT: { uint32_t k, c = 0; for (k = 0; k < 8; k++) c += v >> k & 1; return c; }
	default: return v >> (part - PART_BIT0) & 1;
	}
}
static void write_op(uint32_t op, uint32_t v) {
	const uint32_t m = ra_mem[op & 0x3FF], part = op >> 10 & 15;
	uint8_t* p = host_ram + (m & 0xFFFFFF);
	switch (part) {
	case PART_ALL: p[0] = (uint8_t)v; if (m & MEM_WORD) p[1] = (uint8_t)(v >> 8); break;
	case PART_LOW4: p[0] = (uint8_t)((p[0] & 0xF0) | (v & 15)); break;
	case PART_HIGH4: p[0] = (uint8_t)((p[0] & 0x0F) | (v & 15) << 4); break;
	case PART_BITCOUNT: { uint8_t b = 0; uint32_t k; for (k = 0; k < (v & 15) && k < 8; k++) b |= (uint8_t)(1 << below(8)); p[0] = b; } break;
	default: { const uint8_t bit = (uint8_t)(1 << (part - PART_BIT0)); p[0] = (uint8_t)(v & 1 ? p[0] | bit : p[0] & ~bit); }
	}
}

static int map_state(int s) {
	switch (s) {
	case RC_TRIGGER_STATE_WAITING: return ST_WAITING;
	case RC_TRIGGER_STATE_ACTIVE: case RC_TRIGGER_STATE_PRIMED: return ST_ACTIVE;
	case RC_TRIGGER_STATE_TRIGGERED: return ST_TRIGGERED;
	default: return 100 + s;
	}
}

static int frame_no, rc_fired[256], nrc, per_ach[256];
static void ev(const rc_runtime_event_t* e) {
	if (e->type == RC_RUNTIME_EVENT_ACHIEVEMENT_TRIGGERED) rc_fired[nrc++] = (int)e->id;
}

static char text[1 << 20];
int main(int argc, char** argv) {
	static uint32_t ids[256];
	static char* mem[256];
	static uint8_t out[256], target_mem[0x4000], nown[0x4000];
	static uint32_t own[0x4000][8], tops[0x4000];
	uint32_t ntops;
	int na = 0, s, sessions = atoi(argv[2]), frames = atoi(argv[3]);
	long triggers = 0, checked = 0;
	FILE* f = fopen(argv[1], "rb");
	size_t n = fread(text, 1, sizeof(text) - 1, f);
	char* l;
	fclose(f);
	text[n] = 0;
	rng = (uint32_t)atoi(argv[4]) * 2654435761u + 1;
	for (l = strtok(text, "\n"); l; l = strtok(NULL, "\n")) {
		char *q = l + 4, *t;
		if (strncmp(l, "ach\t", 4)) continue;
		ids[na] = strtoul(q, &q, 10); q++;
		strtoul(q, &q, 10); q++;
		t = strchr(q, '\t'); if (t) *t = 0;
		mem[na++] = q;
	}
	if (na != ra_nach) { printf("set.txt has %d achievements, the tables %u\n", na, ra_nach); return 1; }
	host_ram = calloc(RAM, 1);
	for (s = 0; s < sessions; s++) {
		rc_runtime_t rt;
		int i, fr, tgt = (int)below((uint32_t)na), hold = 0;
		const struct ra_ach* a = &ra_ach[tgt];
		uint32_t k, c;
		memset(host_ram, 0, RAM);
		memset(target_mem, 0, sizeof(target_mem));
		memset(nown, 0, sizeof(nown));
		/* the target's memory operands and the constants they are compared with */
		ntops = 0;
		for (c = 0; c < a->ngroups; c++) {
		  const uint8_t* cp = ra_code + ra_group[a->group + c].code;
		  uint32_t q;
		  for (q = 0; q < ra_group[a->group + c].count; q++) {
			struct ra_cond xx, *x = &xx;
			cp = ra_decode(cp, x);
			const uint32_t ol = x->lhs & 0x3FFF, orr = x->rhs & 0x3FFF;
			if (x->lhs >> 14 && !target_mem[ol]) { target_mem[ol] = 1; tops[ntops++] = ol; }
			if (x->rhs >> 14 && (x->type_op & 15) != CT_ADD_SOURCE && (x->type_op & 15) != CT_SUB_SOURCE && !target_mem[orr]) { target_mem[orr] = 1; tops[ntops++] = orr; }
			if (x->lhs >> 14 && !(x->rhs >> 14) && (x->type_op & 15) != CT_ADD_SOURCE && (x->type_op & 15) != CT_SUB_SOURCE && nown[ol] < 8)
				own[ol][nown[ol]++] = ra_const[x->rhs];
		  }
		}
		rc_runtime_init(&rt);
		for (i = 0; i < na; i++) rc_runtime_activate_achievement(&rt, ids[i], mem[i], NULL, 0);
		for (i = 0; i < na; i++) ra_st[i] = ST_WAITING;
		ra_eval_reset();
		for (k = 0; k < ntops; k++) {
			const uint32_t op = tops[k], part = op >> 10 & 15;
			write_op(op, part >= PART_BIT0 && part <= PART_BIT7 ? below(10) < 8 : nown[op] ? own[op][below(nown[op])] : 0);
		}
		for (fr = 0; fr < frames; fr++) {
			frame_no = fr;
			if (hold) hold--;
			else {
				int m = 1 + (int)below(3);
				hold = below(4) == 0 ? (int)below(20) : 0;
				while (m-- && ntops) {          /* change a few of the target's operands */
					const uint32_t r = below(100), op = tops[below(ntops)];
					if (r < 50 && nown[op]) {
						uint32_t v = own[op][below(nown[op])];
						const uint32_t d = below(10);
						if (d == 0) v++; else if (d == 1) v--;
						write_op(op, v);
					} else if (r < 65) write_op(op, read_op(op) + 1);
					else if (r < 75) write_op(op, read_op(op) - 1);
					else if (r < 85) write_op(op, ra_const[below(ra_nconst)]);
					else write_op(op, rnd());
				}
				if (below(3) == 0) {            /* and noise on the other references */
					const uint32_t r = below(ra_nmem);
					uint32_t t, mine = 0;
					for (t = 0; t < ntops; t++) mine |= (tops[t] & 0x3FF) == r;
					if (!mine) write_op(r, below(2) ? rnd() : ra_const[below(ra_nconst)]);
				}
			}
			nrc = 0;
			rc_runtime_do_frame(&rt, ev, peek, NULL, NULL);
			n = ra_eval_frame(out);
			for (k = 0; k < n; k++) {
				int hit = 0, j;
				for (j = 0; j < nrc; j++) hit |= rc_fired[j] == (int)ids[out[k]];
				if (!hit) { printf("session %d frame %d: we fired %u, rcheevos did not\n", s, fr, ids[out[k]]); return 1; }
			}
			if ((int)n != nrc) { printf("session %d frame %d: rcheevos fired %d, we %u\n", s, fr, nrc, (unsigned)n); return 1; }
			triggers += n;
			for (k = 0; k < n; k++) per_ach[out[k]]++;
			for (i = 0; i < na; i++) {
				const int r = map_state(rt.triggers[i].trigger->state);
				checked++;
				if (rt.triggers[i].id != ids[i]) { printf("order\n"); return 1; }
				if (r != ra_st[i]) {
					printf("session %d frame %d: achievement %u state rcheevos %d, ours %d (target %u)\n", s, fr, ids[i], r, ra_st[i], ids[tgt]);
					return 1;
				}
			}
		}
		rc_runtime_destroy(&rt);
	}
	{ int i; for (i = 0; i < na; i++) if (!per_ach[i]) printf("never triggered: %u\n", ids[i]); }
	printf("OK: %d sessions x %d frames, %ld triggers, %ld states compared\n", sessions, frames, triggers, checked);
	return 0;
}
