/*
	btb_ra.c: built-in RetroAchievements for Beyond the Beyond (the PS1 side).

	The set (RetroAchievements game 11415) is compiled on the PC into the tables of
	eval.h (ra/compile_set.py); eval.c tests them every vblank the way rcheevos does.
	All of this lives in 0x800D5A88..0x800D9E88, the buffers of libgpu's debug font,
	which only a debug menu would open (achievements.py disables FntOpen and keeps
	the startup code from clearing the range; the exe grows to load it).

	  - every vblank (ra_vblank): evaluate, show the unlock popup, save;
	  - boot (ra_boot): read the achievements file of both memory card slots;
	  - field menu "Achievements" (ra_items, ra_page): the list;
	  - the achievements file is its own save, BASCUS-94702ACH, outside the game's
	    file names (BASCUS-947020..2). An unlock rewrites the sector holding our block
	    with the BIOS's queued sector write, so the game doesn't stop.
*/
#include <stdint.h>
#include "eval.h"
#include "meta.h"

void* memset(void* d, int c, unsigned n) { uint8_t* p = d; while (n--) *p++ = (uint8_t)c; return d; }
void* memcpy(void* d, const void* s, unsigned n) { uint8_t* p = d; const uint8_t* q = s; while (n--) *p++ = *q++; return d; }

/* ------------------------------------------------------------------------ */
/* filled in by achievements.py */
struct ra_cfg {
	uint32_t menu_index;      /* field menu choice of our item */
	uint32_t menu_next;       /* where other choices past the table go */
	uint32_t menu_loop_end;   /* the menu loop's end (back to the chooser while $s0 != 0) */
	uint32_t items_prev;      /* the call our item text call replaced */
	uint32_t item_row;        /* our item's row in the field menu window */
	uint32_t vblank_prev;     /* the call our vblank hook replaced */
	uint32_t boot_prev;       /* the call our boot hook replaced */
};
struct ra_cfg ra_cfg __attribute__((section(".cfg")));

/* the game */
#define WIN_OPEN   0x8004673Cu    /* (x, y, w, h, 0, 0) -> handle or -1; cells of 8x8 pixels */
#define WIN_TEXT   0x80047330u    /* (handle, col, row, text, attr) */
#define WIN_CLEAR  0x80046A18u    /* (handle, 0): border and blanks */
#define WIN_FREE   0x80046928u    /* (handle) */
#define WIN_DIRTY  0x80046FECu    /* (): the renderer redraws the windows' cells */
#define WIN_TABLE  0x800FC580u    /* 16 x 12 bytes: +0 cells, +4 w, +5 h, +6 x, +7 y */
#define WAIT       0x8001177Cu    /* (vblanks) */
#define SFX        0x800A8DA4u    /* (id, volume) */
#define CARD_OPEN  0x8007C560u    /* the game's card event open / close */
#define CARD_CLOSE 0x8007C6F4u
#define PAD_PRESS  (*(volatile uint16_t*)0x800C9078u)
#define PAD_REPEAT (*(volatile uint16_t*)0x800C9074u)
#define CALLBACKS  ((volatile uint32_t*)0x800DB4E0u)   /* the 30 Hz callbacks, enable bytes at +0x40 */
#define WIN_DRAW   0x80047684u    /* the window renderer, one of the callbacks while windows show */
#define B_CONFIRM  0x005C
#define B_CANCEL   0x0021
#define B_START    0x0800
#define B_UP       0x1000
#define B_RIGHT    0x2000
#define B_DOWN     0x4000
#define B_LEFT     0x8000
#define SE_CURSOR  0
#define SE_CANCEL  2
#define SE_CONFIRM 0xE

typedef int (*f_open)(int, int, int, int, int, int);
typedef void (*f_text)(int, int, int, const char*, int);
typedef void (*f_h)(int, int);
typedef void (*f_1)(int);
typedef void (*f_0)(void);
#define win_open(x, y, w, h) (int16_t)((f_open)WIN_OPEN)((x), (y), (w), (h), 0, 0)
#define win_text(h, c, r, s, a) ((f_text)WIN_TEXT)((h), (c), (r), (s), (a))
#define win_clear(h) ((f_h)WIN_CLEAR)((h), 0)
#define win_free(h) ((f_1)WIN_FREE)(h)
#define wait(n) ((f_1)WAIT)(n)
#define sfx(id) ((f_h)SFX)((id), 0x7F)

/* ------------------------------------------------------------------------ */
#define NACH_MAX  64
#define NBYTES    (NACH_MAX / 8)
static uint8_t bits[NBYTES];
static int bit(uint32_t i) { return bits[i >> 3] >> (i & 7) & 1; }
static void set_bit(uint32_t i) { bits[i >> 3] |= (uint8_t)(1u << (i & 7)); ra_st[i] = ST_OFF; }

static void fmt_num(char* p, uint32_t v) {
	char t[10]; int n = 0;
	do { t[n++] = (char)('0' + v % 10); v /= 10; } while (v);
	while (n) *p++ = t[--n];
	*p = 0;
}
static char* cat(char* d, const char* s) { while (*s) *d++ = *s++; *d = 0; return d; }
/* the n-th of a run of NUL-terminated strings */
static const uint8_t* nth(const uint8_t* p, uint32_t n) { while (n--) while (*p++) ; return p; }
/* a packed text (meta.h) */
static char* unpack(char* d, const uint8_t* s) {
	for (; *s; s++) d = *s >= 0x80 ? cat(d, (const char*)nth((const uint8_t*)ra_dict, *s - 0x80)) : (*d++ = (char)*s, d);
	*d = 0;
	return d;
}
#define RA_TITLE(i) nth(ra_text, 2 * (i))
#define RA_DESC(i)  nth(ra_text, 2 * (i) + 1)
static int len(const char* s) { int n = 0; while (s[n]) n++; return n; }
static uint32_t unlocked(uint32_t* pts) {
	uint32_t i, n = 0, p = 0;
	for (i = 0; i < ra_nach; i++) if (bit(i)) { n++; p += ra_points[i]; }
	if (pts) *pts = p;
	return n;
}

/* ------------------------------------------------------------------------ */
/* the achievements file */
#define FILE_NAME "BASCUS-94702ACH"
#define BLK_MAGIC 0x43414242u     /* "BBAC" */
#define BLK_OFF   0x200           /* our block: the file's 5th sector */
struct ra_block { uint32_t magic; uint16_t n, version; uint8_t bits[NBYTES]; uint32_t sum; };
static const char* const path[2] = { "bu00:" FILE_NAME, "bu10:" FILE_NAME };
extern const uint8_t ra_icon[];   /* palette (32 bytes) + 16x16 4-bit trophy (128) */
static const uint8_t file_title[] = {   /* Shift-JIS "BtB ACHIEVEMENTS" */
	0x82,0x61, 0x82,0x94, 0x82,0x61, 0x81,0x40, 0x82,0x60, 0x82,0x62, 0x82,0x67, 0x82,0x68,
	0x82,0x64, 0x82,0x75, 0x82,0x64, 0x82,0x6C, 0x82,0x64, 0x82,0x6D, 0x82,0x73, 0x82,0x72, 0 };

struct ps_dirent { char name[20]; int attr; int size; void* next; int head; char sys[4]; };
int bios_open(const char* name, int mode);
int bios_lseek(int fd, int off, int whence);
int bios_read(int fd, void* buf, int n);
int bios_write(int fd, const void* buf, int n);
int bios_close(int fd);
void* bios_firstfile(const char* name, struct ps_dirent* d);
int bios_card_write(int port, int sector, const void* buf);

static uint8_t sec[0x80] __attribute__((aligned(4)));
static int rt_port = -1, rt_sector, rt_pending, rt_wait, rt_tries, card_busy, card_in_use;

static uint32_t block_sum(const struct ra_block* b) {
	const uint8_t* p = (const uint8_t*)b;
	uint32_t s = 0x1234567u, i;
	for (i = 0; i < sizeof(*b) - 4; i++) s = (s << 5 | s >> 27) + p[i];
	return s;
}
static void make_block(void* buf) {
	struct ra_block* b = buf;
	memset(buf, 0, 0x80);
	b->magic = BLK_MAGIC; b->n = ra_nach; b->version = 1;
	memcpy(b->bits, bits, NBYTES);
	b->sum = block_sum(b);
}
static int block_ok(const struct ra_block* b) {
	return b->magic == BLK_MAGIC && b->n == ra_nach && b->version == 1 && b->sum == block_sum(b);
}

/* the sector of our block, from the directory (firstfile fills the entry; its return
   value is not reliable on every BIOS, so the name is checked) */
static void locate(void) {
	struct ps_dirent d;
	int k, i;
	rt_port = -1;
	for (k = 0; k < 2; k++) {
		memset(&d, 0, sizeof(d));
		bios_firstfile(path[k], &d);
		for (i = 0; FILE_NAME[i] && d.name[i] == FILE_NAME[i]; i++) ;
		if (FILE_NAME[i] || d.name[i] || d.head < 64 || d.head >= 1024 || (d.head & 63)) continue;
		rt_port = k ? 0x10 : 0x00; rt_sector = d.head + BLK_OFF / 0x80;
		return;
	}
}

/* no file on either card: make one in slot 1, else slot 2 (header with the icon, our block) */
static void create(void) {
	uint8_t buf[BLK_OFF + 0x80] __attribute__((aligned(4)));
	int k, fd = -1;
	for (k = 0; k < 2 && fd < 0; k++) fd = bios_open(path[k], (1 << 16) | 0x200);   /* create, 1 block */
	if (fd < 0) return;
	bios_close(fd);
	memset(buf, 0, sizeof(buf));
	buf[0] = 'S'; buf[1] = 'C'; buf[2] = 0x11; buf[3] = 1;   /* 1 icon frame, 1 block */
	memcpy(buf + 4, file_title, sizeof(file_title));
	memcpy(buf + 0x60, ra_icon, 32 + 128);
	make_block(buf + BLK_OFF);
	fd = bios_open(path[k - 1], 2);
	if (fd >= 0) { bios_write(fd, buf, sizeof(buf)); bios_close(fd); }
}

/* boot: the memory card module is up; read the file of both slots, make one if none */
void ra_boot(void) {
	int k, found = 0;
	((f_0)ra_cfg.boot_prev)();
	for (k = 0; k < 2; k++) {
		const int fd = bios_open(path[k], 1);
		if (fd < 0) continue;
		found = 1;
		if (bios_lseek(fd, BLK_OFF, 0) == BLK_OFF && bios_read(fd, sec, 0x80) == 0x80 && block_ok((struct ra_block*)sec)) {
			const struct ra_block* b = (const struct ra_block*)sec;
			uint32_t i;
			for (i = 0; i < NBYTES; i++) bits[i] |= b->bits[i];
		}
		bios_close(fd);
	}
	if (!found) create();
	locate();
	ra_eval_reset();
	{ uint32_t i; for (i = 0; i < ra_nach; i++) if (bit(i)) ra_st[i] = ST_OFF; }
}

/* the game's card event open/close: none of our card writes while it uses the card */
void ra_card_open(void) {
	while (rt_wait > 110) wait(1);      /* a write of ours just started: let it finish */
	card_in_use = 1;
	((f_0)CARD_OPEN)();
}
void ra_card_close(void) {
	((f_0)CARD_CLOSE)();
	card_in_use = 0;
	card_busy = 30;
	rt_tries = 0;                       /* a card may have been put in: try again */
}

/* once per vblank: the queued unlock write */
static void rt_save(void) {
	if (card_busy) card_busy--;
	if (rt_wait) { rt_wait--; return; }
	if (!rt_pending || card_in_use || card_busy || rt_tries >= 3) return;
	locate();                           /* the card may have been changed */
	if (rt_port < 0) { create(); locate(); }
	/* no card / no room: a few more tries, then only after the game used the card */
	if (rt_port < 0) { rt_wait = 600; rt_tries++; return; }
	make_block(sec);
	if (bios_card_write(rt_port, rt_sector, sec) == 1) { rt_pending = 0; rt_wait = 120; }
	else rt_wait = 60;
}

/* ------------------------------------------------------------------------ */
/* the unlock popup: a window at the top, "Achievement unlocked!" and the title, for
   POP_FRAMES vblanks; it waits while windows aren't drawn (loading, movies) or the
   list is open */
#define POP_FRAMES 210
#define POP_Y      1
static uint8_t queue[8];
static int nqueue, pop_frames, page_open;
static int16_t pop_h = -1;
static uint32_t pop_win[2];          /* the window's table entry as we made it */

static volatile uint8_t* win_entry(int h) { return (volatile uint8_t*)(WIN_TABLE + 12 * h); }
static int windows_drawn(void) {
	int i;
	for (i = 0; i < 4; i++) if (CALLBACKS[i] == WIN_DRAW && ((volatile uint8_t*)CALLBACKS)[0x40 + i]) return 1;
	return 0;
}
static void popup_close(void) {
	volatile uint8_t* e = win_entry(pop_h);
	/* free it only if it's still ours (a scene change may have dropped all windows) */
	if (((volatile uint32_t*)e)[0] == pop_win[0] && ((volatile uint32_t*)e)[1] == pop_win[1]) win_free(pop_h);
	pop_h = -1;
}
static void popup_open(uint32_t i) {
	static const char head[] = "Achievement unlocked!";
	char line[48], *p;
	int w;
	p = unpack(line, RA_TITLE(i));
	p = cat(p, " ("); fmt_num(p, ra_points[i]); while (*p) p++; cat(p, ")");
	w = len(line) > len(head) ? len(line) : len(head);
	w += 3;
	pop_h = win_open((40 - w) / 2, POP_Y, w, 5);
	if (pop_h < 0) return;
	win_text(pop_h, 1, 0, head, 0);
	win_text(pop_h, 1, 2, line, 0);
	((f_0)WIN_DIRTY)();
	pop_win[0] = ((volatile uint32_t*)win_entry(pop_h))[0];
	pop_win[1] = ((volatile uint32_t*)win_entry(pop_h))[1];
	pop_frames = POP_FRAMES;
	sfx(SE_CONFIRM);
}
static void popup_tick(void) {
	if (pop_h >= 0) {
		if (--pop_frames <= 0 || page_open) popup_close();
		return;
	}
	if (!nqueue || page_open || !windows_drawn()) return;
	popup_open(queue[0]);
	if (pop_h < 0) return;               /* no room for the window: next vblank */
	nqueue--;
	memcpy(queue, queue + 1, sizeof(queue) - 1);
}

/* ------------------------------------------------------------------------ */
static int in_vblank;
uint16_t ra_cost, ra_cost_max;           /* evaluation time in hblanks (root counter 1), for tuning */
void ra_vblank(void) {
	static uint8_t out[NACH_MAX];
	uint32_t n, k;
	uint16_t t;
	((f_0)ra_cfg.vblank_prev)();
	if (in_vblank) return;               /* our own waits (the list) come through here */
	in_vblank = 1;
	t = *(volatile uint16_t*)0x1F801110u;
	n = ra_eval_frame(out);
	ra_cost = (uint16_t)(*(volatile uint16_t*)0x1F801110u - t);
	if (ra_cost > ra_cost_max) ra_cost_max = ra_cost;
	for (k = 0; k < n; k++) {
		set_bit(out[k]);
		if (nqueue < (int)sizeof(queue)) queue[nqueue++] = out[k];
		rt_pending = 1;
	}
	rt_save();
	popup_tick();
	in_vblank = 0;
}

/* ------------------------------------------------------------------------ */
/* field menu: our item under the last one */
void ra_items(int h, int col, int row, const char* s, int attr) {
	((void (*)(int, int, int, const char*, int))ra_cfg.items_prev)(h, col, row, s, attr);
	win_text(h, 1, ra_cfg.item_row, "Achievements", 0);
}

/* the list: 6 rows of titles (unlocked ones marked), and the selected one's text.
   Windows must stay within rows 1..26 and columns 1..39: the renderer composes them
   into a cell map (0x800FD900..0x800FE600) and doesn't clip. */
#define LIST_X 1
#define LIST_Y 1
#define LIST_W 38
#define LIST_H 15
#define ROWS   6
#define DESC_Y (LIST_Y + LIST_H)
#define DESC_H 11
#define ATTR_LOCKED   3     /* text colours: 0 white, 1 red, 2 gold, 3 lilac grey, ... */
#define ATTR_UNLOCKED 2

static void page_draw(int hl, int hd, int sel, int top) {
	char line[48], desc[160], *p;
	uint32_t pts, n = unlocked(&pts);
	int i;
	const char* d;
	win_clear(hl);
	win_clear(hd);
	p = cat(line, "Achievements  "); fmt_num(p, n); while (*p) p++;
	p = cat(p, "/"); fmt_num(p, ra_nach);
	win_text(hl, 1, 0, line, 0);
	fmt_num(line, pts); p = line; while (*p) p++;
	p = cat(p, "/"); fmt_num(p, ra_total_points); while (*p) p++;
	cat(p, " pts");
	win_text(hl, LIST_W - 3 - len(line), 0, line, 0);
	for (i = 0; i < ROWS && top + i < ra_nach; i++) {
		const int j = top + i;
		p = cat(line, j == sel ? ">" : " ");
		p = cat(p, bit(j) ? "+" : " ");     /* the font draws '*' as a cross */
		unpack(p, RA_TITLE(j));
		win_text(hl, 0, 2 + 2 * i, line, bit(j) ? ATTR_UNLOCKED : ATTR_LOCKED);
	}
	p = cat(line, bit(sel) ? "Unlocked" : "Locked");
	win_text(hd, 1, 0, line, bit(sel) ? ATTR_UNLOCKED : ATTR_LOCKED);
	fmt_num(line, ra_points[sel]); p = line; while (*p) p++;
	cat(p, ra_points[sel] == 1 ? " pt" : " pts");
	win_text(hd, LIST_W - 3 - len(line), 0, line, 0);
	unpack(desc, RA_DESC(sel));
	d = desc;
	for (i = 0; i < 4 && *d; i++) {
		char* q = line;
		while (*d && *d != '\n') *q++ = *d++;
		*q = 0;
		if (*d == '\n') d++;
		win_text(hd, 1, 2 + 2 * i, line, 0);
	}
}

void ra_page(void) {
	int hl, hd, sel = 0, top = 0, redraw = 1;
	hl = win_open(LIST_X, LIST_Y, LIST_W, LIST_H);
	if (hl < 0) return;
	hd = win_open(LIST_X, DESC_Y, LIST_W, DESC_H);
	if (hd < 0) { win_free(hl); return; }
	page_open = 1;
	sfx(SE_CONFIRM);
	for (;;) {
		uint16_t press, rep;
		int s = sel;
		if (redraw) { page_draw(hl, hd, sel, top); ((f_0)WIN_DIRTY)(); redraw = 0; }
		wait(1);
		press = PAD_PRESS; rep = PAD_REPEAT;
		if (press & (B_CANCEL | B_START)) { sfx(SE_CANCEL); break; }
		if (rep & B_UP) s = s > 0 ? s - 1 : ra_nach - 1;
		if (rep & B_DOWN) s = s < ra_nach - 1 ? s + 1 : 0;
		if (rep & B_LEFT) s = s >= ROWS ? s - ROWS : 0;
		if (rep & B_RIGHT) s = s + ROWS < ra_nach ? s + ROWS : ra_nach - 1;
		if (s != sel) {
			sel = s;
			if (sel < top) top = sel;
			if (sel >= top + ROWS) top = sel - ROWS + 1;
			sfx(SE_CURSOR);
			redraw = 1;
		}
	}
	win_free(hd);
	win_free(hl);
	page_open = 0;
}
