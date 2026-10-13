/* eval.c: see eval.h */
#include "eval.h"

#ifdef RA_RAM_DECL
RA_RAM_DECL
#endif
#ifndef RA_RAM
#define RA_RAM ((const volatile uint8_t*)0x80000000u)
#endif

static uint32_t read_mem(uint32_t m) {
	const volatile uint8_t* p = RA_RAM + (m & 0x1FFFFFu);
	return m & MEM_WORD ? p[0] | (uint32_t)p[1] << 8 : p[0];
}

static uint32_t operand(uint32_t o) {
	const uint32_t i = o & 0x3FF;
	uint32_t v;
	switch (o >> 14) {
	case OPK_VALUE: v = ra_val[i]; break;
	case OPK_DELTA: v = ra_dlt[i]; break;
	default: return ra_const[o & 0x3FFF];
	}
	switch (o >> 10 & 15) {
	case PART_ALL: return v;
	case PART_LOW4: return v & 15;
	case PART_HIGH4: return v >> 4 & 15;
	case PART_BITCOUNT:
		v = (v & 0x55) + (v >> 1 & 0x55);
		v = (v & 0x33) + (v >> 2 & 0x33);
		return (v & 15) + (v >> 4 & 15);
	default: return v >> ((o >> 10 & 15) - PART_BIT0) & 1;
	}
}

static int compare(uint32_t op, uint32_t a, uint32_t b) {
	switch (op) {
	case OP_EQ: return a == b;
	case OP_NE: return a != b;
	case OP_LT: return a < b;
	case OP_LE: return a <= b;
	case OP_GT: return a > b;
	case OP_GE: return a >= b;
	default: return 0;
	}
}

const uint8_t* ra_decode(const uint8_t* p, struct ra_cond* c) {
	const uint32_t t = p[0] & 15;
	c->type_op = p[0];
	c->lhs = (uint16_t)(p[1] | p[2] << 8);
	if (t == CT_ADD_SOURCE || t == CT_SUB_SOURCE) { c->rhs = 0; c->hits = 0; return p + 3; }
	c->rhs = (uint16_t)(p[3] | p[4] << 8);
	c->hits = p[5];
	return p + 6;
}

static int has_hits, was_reset;
/* A pure achievement's result depends on this frame's values and deltas only: when no
   memory reference changed in this frame nor in the last one, both are the same as last
   frame and so is the result (which didn't trigger), and its state stays as it is. */
static int changed_prev = 1;

/* rc_test_condset */
static int test_group(const struct ra_group* g, int pure) {
	uint32_t k, acc = 0;
	int is_true = 1, and_next = 1, or_next = 0, reset_next = 0;
	int32_t add_hits = 0;
	const uint8_t* p = ra_code + g->code;
	for (k = 0; k < g->count; k++) {
		struct ra_cond cc, *c = &cc;
		uint32_t type;
		uint8_t* h = &ra_hit[g->hit + k];
		p = ra_decode(p, c);
		type = c->type_op & 15;
		int valid;
		if (type == CT_ADD_SOURCE) { acc += operand(c->lhs); continue; }
		if (type == CT_SUB_SOURCE) { acc -= operand(c->lhs); continue; }
		valid = compare(c->type_op >> 4, acc + operand(c->lhs), operand(c->rhs));
		acc = 0;
		/* rc_condset_evaluate_condition_no_add_hits */
		if (reset_next) {
			*h = 0;
			valid = 0;
		} else {
			valid = (valid & and_next) | or_next;
			if (valid) {
				has_hits = 1;
				if (c->hits == 0) { if (*h != 0xFF) ++*h; }
				else if (*h < c->hits) { ++*h; valid = *h == c->hits; }
			} else if (*h) {
				has_hits = 1;
				valid = *h == c->hits;
			}
		}
		and_next = 1; or_next = 0;
		switch (type) {
		case CT_AND_NEXT: and_next = valid; continue;
		case CT_OR_NEXT: or_next = valid; continue;
		case CT_RESET_NEXT_IF: reset_next = valid; continue;
		case CT_ADD_HITS: add_hits += *h; reset_next = 0; continue;
		case CT_SUB_HITS: add_hits -= *h; reset_next = 0; continue;
		default: break;
		}
		/* rc_condset_evaluate_condition: the AddHits total */
		if (add_hits != 0 && c->hits != 0) {
			const int32_t t = (int32_t)*h + add_hits;
			valid = (t >= 0 ? (uint32_t)t : 0) >= c->hits;
			add_hits = 0;
		}
		reset_next = 0;
		if (type == CT_RESET_IF) {
			if (valid) { was_reset = 1; is_true = 0; }
		} else {
			is_true &= valid;
			if (!is_true && pure) return 0;     /* nothing else to update: stop at the first false one */
		}
	}
	return is_true;
}

static void clear_hits(const struct ra_ach* a) {
	const struct ra_group* g = &ra_group[a->group];
	uint32_t k;
	for (k = g->hit; k < (uint32_t)g[a->ngroups - 1].hit + g[a->ngroups - 1].count; k++) ra_hit[k] = 0;
}

void ra_eval_reset(void) {
	uint32_t i;
	changed_prev = 1;
	for (i = 0; i < ra_nmem; i++) ra_val[i] = ra_dlt[i] = 0;
	for (i = 0; i < ra_ncond; i++) ra_hit[i] = 0;
	for (i = 0; i < ra_nach; i++) { if (ra_st[i] != ST_OFF) ra_st[i] = ST_WAITING; ra_hh[i] = 0; }
}

uint32_t ra_eval_frame(uint8_t* out) {
	uint32_t i, n = 0, changed = 0;
	int skip_pure;
	for (i = 0; i < ra_nmem; i++) {
		const uint32_t v = read_mem(ra_mem[i]);
		changed |= v ^ ra_val[i];
		ra_dlt[i] = ra_val[i]; ra_val[i] = (uint16_t)v;
	}
	skip_pure = !changed && !changed_prev;
	changed_prev = changed != 0;
	for (i = 0; i < ra_nach; i++) {
		const struct ra_ach* a = &ra_ach[i];
		uint32_t j;
		int ret, sub = 0;
		if (ra_st[i] >= ST_TRIGGERED || (skip_pure && a->pure)) continue;
		has_hits = was_reset = 0;
		ret = test_group(&ra_group[a->group], a->pure);
		if (a->ngroups > 1 && !(a->pure && !ret)) {
			for (j = 1; j < a->ngroups && !(sub && a->pure); j++) sub |= test_group(&ra_group[a->group + j], a->pure);
			ret &= sub;
		}
		if (was_reset) {
			clear_hits(a);
			if (ra_hh[i]) { ra_hh[i] = 0; continue; }       /* state unchanged */
			ra_st[i] = ST_ACTIVE;
		} else if (ret) {
			if (ra_st[i] == ST_WAITING) { clear_hits(a); ra_hh[i] = 0; continue; }
			ra_st[i] = ST_TRIGGERED;
			out[n++] = (uint8_t)i;
		} else {
			ra_hh[i] = (uint8_t)has_hits;
			ra_st[i] = ST_ACTIVE;
		}
	}
	return n;
}
