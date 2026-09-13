# The UART abort defect, on RP2350 silicon

2026-09-13. Four console transcripts from a Pico 2 W over the Debug Probe,
flashed by SWD. **The first time this defect has been observed on RP2350
hardware** -- the prior A/B was under QEMU on a pinned hifive1 kernel, a
different chip and a different driver.

## What differs between the two kernels

Both built from `pico2w-typed` (`40695eaf0`). The fixed one is that tree with
`rp2-uart-abort-fix` (`660b708e0`) merged and nothing else, so the only
difference on the RP2350 path is where `rx_status` returns to `Idle` in
`chips/rp2350/src/uart.rs`. Both build to `text=323116`.

The application is `console_read_busy` from libtock-rs `hw/pico2w-async`,
built for `raspberry_pi_pico_2_w` and loaded at `0x10090000`. It writes a
line, sleeps 500 ms to outlast `ProcessConsole`'s 100 ms startup alarm, then
issues one blocking 16-byte read.

## The four runs

| file | kernel | typed | result |
|---|---|---|---|
| `cap-unfixed.txt` | unfixed | nothing | `read -> 0 bytes, Err(BUSY)` |
| `cap-unfixed-typed.txt` | unfixed | `help\r` | `read -> 0 bytes, Err(BUSY)`, **and no echo, no prompt** |
| `cap-fixed.txt` | fixed | nothing | read issued, stays outstanding |
| `cap-fixed-typed.txt` | fixed | `ABCDEFGHIJKLMNOP` | `read -> 16 bytes, Ok(())`, **input echoed** |

## What each half establishes

**The application's read is killed.** `Err(BUSY)` on the unfixed build,
matching what the example's own header predicted before any of this ran.

**The process console dies with it.** On the unfixed build `help\r` produced
no echo and no returning `tock$` prompt. That is the second half of the
claim in the commit message -- *"the process console stops receiving at the
same moment"* -- and it had never been measured until now; the QEMU run only
covered the application's read.

**The fix is positively confirmed, not merely symptom-free.** An absent error
line only shows the read did not fail. Typing sixteen bytes and getting
`read -> 16 bytes, Ok(())` back, with the input echoed by the process console,
shows the read was live and both clients were receiving.

## What this does not establish

- **Only rp2040/rp2350 were exercised.** The same commit fixes sifive,
  stm32f303xc, stm32f4xx and stm32wle5xx by the same edit; none of those
  boards is here, so for them the argument is still that the code is the same
  block.
- **One run each.** Nothing here speaks to intermittency.
- The example cannot demonstrate its own ability to fail without a kernel that
  has no `ProcessConsole` on that mux, which is a board change. Its header
  states this limitation; it is not resolved by moving to hardware.
