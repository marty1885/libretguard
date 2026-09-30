/* This uninstrumented bridge calls the real hooks on a controlled stack slot.
   r12/r13 hold the original stack/context, both callee-saved by SysV. */
.text
.globl arithmetic_bridge
.type arithmetic_bridge, @function
arithmetic_bridge:
    pushq %r12
    pushq %r13
    movq %rsp, %r12
    movq %rdi, %r13
    movq %rsi, %rsp
    leaq arithmetic_return_label(%rip), %r10
    movq %r10, (%rsp)
    movq $11, %rdi
    movq $22, %rsi
    movq $33, %rdx
    movq $44, %rcx
    movq $55, %r8
    movq $66, %r9
    movq $7, %rax
    call __retguard_fentry
    movq (%rsp), %r10
    movq %r10, 0(%r13)
    movq %rdi, 8(%r13)
    movq %rsi, 16(%r13)
    movq %rdx, 24(%r13)
    movq %rcx, 32(%r13)
    movq %r8, 40(%r13)
    movq %r9, 48(%r13)
    movq %rax, 56(%r13)
    cmpq $0, 96(%r13)
    je 1f
    xorb $1, 7(%rsp)
1:
    movabsq $0x123456789abcdef0, %rax
    movabsq $0xfedcba9876543210, %rdx
    movabsq $0x4029000000000000, %r10 /* 12.5 */
    movq %r10, %xmm0
    movabsq $0xc011000000000000, %r10 /* -4.25 */
    movq %r10, %xmm1
    jmp __retguard_auto_return_thunk
.globl arithmetic_return_label
arithmetic_return_label:
    movq %rax, 64(%r13)
    movq %rdx, 72(%r13)
    movq %xmm0, 80(%r13)
    movq %xmm1, 88(%r13)
    movq %rsp, 104(%r13)
    movq %r12, %rsp
    popq %r13
    popq %r12
    ret
.size arithmetic_bridge, .-arithmetic_bridge
.section .note.GNU-stack,"",@progbits
