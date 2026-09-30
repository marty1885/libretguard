/* Manual checked-return path. r11 carries the frame's seal;
   the function body was compiled with -ffixed-r11. Do not call this thunk:
   GCC jumps here after restoring the protected function's stack frame. */
	.text
	.globl __x86_return_thunk
	.hidden __x86_return_thunk
	.type __x86_return_thunk, @function
__x86_return_thunk:
	.cfi_startproc
	endbr64
#ifdef RETGUARD_TEST_SIGNAL_GAP
	int3
#endif
	movq %rsp, %r10
	shrq $4, %r10
	andl $15, %r10d
	leaq retguard_auto_cookies(%rip), %rcx
	movq (%rcx,%r10,8), %r10
	movq (%rsp), %rcx
	xorq %rsp, %rcx
	imulq %r10, %rcx
	cmpq %rcx, %r11
	jne 2f
	xorl %r11d, %r11d
	jmp 1f
2:	ud2
	.rept 16
	int3
	.endr
1:	/* The only intended ret is separated from the check by traps. */
	ret
	.cfi_endproc
	.size __x86_return_thunk, .-__x86_return_thunk

/* Automatic entry hook. Its caller's return address is at rsp+8 while the
   hook runs. Mask the address, then tag the low 56 bits of that payload. */
	.p2align 4
	.globl __retguard_fentry
	.hidden __retguard_fentry
	.type __retguard_fentry, @function
__retguard_fentry:
	.cfi_startproc
	.cfi_def_cfa %rsp, 16
	.cfi_offset %rip, -8
	endbr64
	pushq %rcx
	.cfi_def_cfa_offset 24
	.cfi_offset %rcx, -24
	cmpb $0, 23(%rsp)
	jne .Lauto_corrupt
	leaq 16(%rsp), %r10
	movq %r10, %rcx
	shrq $4, %r10
	shrq $12, %rcx
	xorq %r10, %rcx
	andl $15, %r10d
	andl $15, %ecx
	leaq retguard_auto_cookies(%rip), %r11
	movq (%r11,%r10,8), %r11
	leaq retguard_auto_masks(%rip), %r10
	movq (%r10,%rcx,8), %rcx
	movq 16(%rsp), %r10
	xorq %rcx, %r10
	leaq 16(%rsp), %rcx
	xorq %r10, %rcx
	imulq %r11, %rcx
	shrq $56, %rcx
	shlq $56, %rcx
	orq %rcx, %r10
	movq %r10, 16(%rsp)
	popq %rcx
	.cfi_def_cfa_offset 16
	.cfi_restore %rcx
	jmp .Lauto_entry_ret
	.rept 16
	int3
	.endr
.Lauto_entry_ret:
	ret
	.cfi_endproc
	.size __retguard_fentry, .-__retguard_fentry

/* The assembly compiler redirects automatic returns here. The tag check
   uses the stored payload, independent of unmasking the return address. */
	.p2align 4
	.globl __retguard_auto_return_thunk
	.hidden __retguard_auto_return_thunk
	.type __retguard_auto_return_thunk, @function
__retguard_auto_return_thunk:
	.cfi_startproc
	endbr64
	movq (%rsp), %r9
	shlq $8, %r9
	shrq $8, %r9
	movq %rsp, %r10
	movq %r10, %r11
	shrq $4, %r10
	shrq $12, %r11
	xorq %r10, %r11
	andl $15, %r10d
	andl $15, %r11d
	leaq retguard_auto_cookies(%rip), %r8
	movq (%r8,%r10,8), %r10
	leaq retguard_auto_masks(%rip), %r8
	movq (%r8,%r11,8), %r11
	movq %r9, %r8
	xorq %rsp, %r9
	imulq %r10, %r9
	xorq %r11, %r8
	shrq $56, %r9
	cmpb %r9b, 7(%rsp)
	jne .Lauto_corrupt
	/* ret reads eight bytes; restore the complete unmasked address. */
	movq %r8, (%rsp)
	jmp .Lauto_checked_ret
.Lauto_corrupt:
	ud2
	.rept 16
	int3
	.endr
.Lauto_checked_ret:
	ret
	.cfi_endproc
	.size __retguard_auto_return_thunk, .-__retguard_auto_return_thunk
	.section .note.GNU-stack,"",@progbits
