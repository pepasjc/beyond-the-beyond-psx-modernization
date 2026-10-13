OUTPUT_ARCH(mips)
ENTRY(_start)
SECTIONS {
	. = BASE;
	.text : { *(.text.entry) *(.text*) }
	.cfg : { *(.cfg) }
	.rodata : { *(.rodata*) }
	__data_start = .;
	.data : { *(.data*) *(.sdata*) }
	__bss_start = .;
	.bss : { *(.sbss*) *(.bss*) *(COMMON) }
	. = ALIGN(4);
	_end = .;
	/DISCARD/ : { *(.comment) *(.pdr) *(.reginfo) *(.MIPS.*) *(.gnu.*) *(.note*) }
}
