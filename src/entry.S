.section .text
.global _start
_start:
  ldr x3, [sp]
  add x2, sp, #16
  add x2, x2, x3, lsl #3
  adr x0, bash_path
  adr x4, bash_flag
  adr x5, script
  sub sp, sp, #32
  stp x0, x4, [sp]
  stp x5, xzr, [sp, #16]
  mov x1, sp
  mov x8, #221
  svc #0
  mov x0, #127
  mov x8, #93
  svc #0
bash_path: .asciz "/bin/bash"
bash_flag: .asciz "-c"
script:
.incbin "install.sh"
.byte 0
