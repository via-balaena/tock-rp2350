# The uart conformance test on RP2350 silicon

2026-09-13. Two console transcripts from a Pico 2 W over the Debug Probe,
flashed by SWD. The test is `capsules/core/src/test/uart_contract.rs` behind
`--features uart_contract_test`, pointed at `peripherals.uart1` -- the chip
driver, not the mux.

Both kernels are `main` at `573f393e9`. The only difference between them is
one line in `chips/rp2350/src/uart.rs`.

## The two runs

| file | `transmit_word` answers | result |
|---|---|---|
| `cap-green.txt` | `Err(FAIL)`, as shipped | `13 clauses, all kept` |
| `cap-mutated.txt` | `Err(NODEVICE)` | `13 clauses, 1 BROKEN` |

## Why the second run exists

The first run is thirteen passing clauses, which on its own does not
distinguish "the contract holds" from "the clause never ran". `NODEVICE` is a
real `ErrorCode` that the `hil::uart` documentation does not list among the
answers `transmit_word` may give, so the mutation changes only whether the
answer is enumerated -- not whether the call succeeds, not what the driver
does, not anything the other twelve clauses look at.

The mutated run fails **that clause and only that clause**: `receive_word`,
which was not mutated, still passes. So the two word clauses are independent
of each other, and both reach the driver.

## What this establishes and what it does not

**Establishes.** The two clauses added with the `NOSUPPORT` enumeration run on
hardware, reach the chip driver, and can fail. Reaching them at all is also
the check that neither word method panics -- the reason they were added is
that `x86_q35` answered `unimplemented!()` and `litex` asserted.

**Does not establish.** Only the rp2350 driver was exercised. The clauses are
generic over `uart::UartData`, so pointing the test at another driver is a
board wiring change rather than a code change, but no other board is here.

Nothing here exercises the `MuxUart` word-transmit wedge fixed the same day.
That path is pinned by a host test instead --
`capsules/core/tests/virtual_uart_word.rs` -- because reproducing it on
hardware means deliberately wedging the console the test reports through.
