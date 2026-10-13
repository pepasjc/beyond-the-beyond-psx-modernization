	.set noreorder
	.section .text.entry,"ax"
	.globl _start
/* jump table: the patched exe calls (jal) or jumps (j) here; achievements.py has the offsets */
_start:
	j	ra_vblank		/* +0x00 every vblank, in place of the frame counter call */
	nop
	j	ra_boot			/* +0x08 boot, in place of the memory card module init */
	nop
	j	ra_items		/* +0x10 field menu: in place of the last item's text call */
	nop
	j	menu_choice		/* +0x18 field menu: a choice past the jump table (from a trampoline) */
	nop
	j	ra_card_open		/* +0x20 the game's memory card event open */
	nop
	j	ra_card_close		/* +0x28 the game's memory card event close */
	nop
	.word	ra_cfg			/* +0x30 */
	.word	_end			/* +0x34 */

/* field menu dispatch: $s2 = the choice. Ours opens the page and goes back to the menu
   (its loop keeps $s0 = 1, the cursor stays on the item); anything else goes on to the
   handler that was there before (save anywhere's, or the loop end) */
menu_choice:
	la	$t0, ra_cfg
	lw	$t1, 0($t0)		/* menu_index */
	nop
	bne	$s2, $t1, 1f
	nop
	jal	ra_page
	nop
	la	$t0, ra_cfg
	lw	$t1, 8($t0)		/* menu_loop_end */
	nop
	jr	$t1
	nop
1:	lw	$t1, 4($t0)		/* menu_next */
	nop
	jr	$t1
	nop

/* BIOS calls (B table) */
	.globl	bios_open, bios_read, bios_write, bios_close, bios_lseek, bios_firstfile, bios_card_write
bios_open:
	addiu	$t2, $zero, 0xB0
	jr	$t2
	addiu	$t1, $zero, 0x32
bios_lseek:
	addiu	$t2, $zero, 0xB0
	jr	$t2
	addiu	$t1, $zero, 0x33
bios_read:
	addiu	$t2, $zero, 0xB0
	jr	$t2
	addiu	$t1, $zero, 0x34
bios_write:
	addiu	$t2, $zero, 0xB0
	jr	$t2
	addiu	$t1, $zero, 0x35
bios_close:
	addiu	$t2, $zero, 0xB0
	jr	$t2
	addiu	$t1, $zero, 0x36
bios_firstfile:
	addiu	$t2, $zero, 0xB0
	jr	$t2
	addiu	$t1, $zero, 0x42
bios_card_write:			/* _card_write(port, sector, buf): queued, returns at once */
	addiu	$t2, $zero, 0xB0
	jr	$t2
	addiu	$t1, $zero, 0x4E
