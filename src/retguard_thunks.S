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
   hook runs. The top byte stores an eight-bit tag in that existing slot. */
	.p2align 4
	.globl __retguard_fentry
	.hidden __retguard_fentry
	.type __retguard_fentry, @function
__retguard_fentry:
	.cfi_startproc
	.cfi_def_cfa %rsp, 16
	.cfi_offset %rip, -8
	endbr64
	cmpb $0, 15(%rsp)
	jne .Lauto_corrupt
	leaq 8(%rsp), %r10
	shrq $4, %r10
	andl $15, %r10d
	leaq retguard_auto_cookies(%rip), %r11
	movq (%r11,%r10,8), %r10
	leaq 8(%rsp), %r11
	xorq 8(%rsp), %r11
	imulq %r10, %r11
	shrq $56, %r11
	shlq $56, %r11
	orq 8(%rsp), %r11
	movq %r11, 8(%rsp)
	ret
	.cfi_endproc
	.size __retguard_fentry, .-__retguard_fentry

/* The object patcher redirects automatic return relocations here. It has a
   different entry contract from __x86_return_thunk: the tag lives on the
   stack, while r11 contains arbitrary function state. */
	.p2align 4
	.globl __retguard_auto_return_thunk
	.hidden __retguard_auto_return_thunk
	.type __retguard_auto_return_thunk, @function
__retguard_auto_return_thunk:
	.cfi_startproc
	endbr64
	movq (%rsp), %rcx
	shlq $8, %rcx
	shrq $8, %rcx
	movq %rsp, %r10
	shrq $4, %r10
	andl $15, %r10d
	leaq retguard_auto_cookies(%rip), %r11
	movq (%r11,%r10,8), %r10
	movq %rcx, %r11
	xorq %rsp, %r11
	imulq %r10, %r11
	shrq $56, %r11
	cmpb %r11b, 7(%rsp)
	jne .Lauto_corrupt
	/* ret reads eight bytes; restore the complete untagged word. */
	movq %rcx, (%rsp)
	ret
.Lauto_corrupt:
	ud2
	.rept 16
	int3
	.endr
	.cfi_endproc
	.size __retguard_auto_return_thunk, .-__retguard_auto_return_thunk
	.section .note.GNU-stack,"",@progbits
