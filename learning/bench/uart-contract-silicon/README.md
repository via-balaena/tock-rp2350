# The uart conformance test on RP2350 silicon

2026-09-13. Two console transcripts from a Pico 2 W over the Debug Probe,
flashed by SWD. The test is `capsules/core/src/test/uart_contract.rs` behind
`--features uart_contract_test`, pointed at `peripherals.uart1` -- the chip
driver, not the mux.

Both kernels are `main` at `573f393e9`. The only difference between them is
one line in `chips/rp2350/src/uart.rs`.

## The runs

| file | what differs | result |
|---|---|---|
| `cap-green.txt` | nothing; as shipped | `13 clauses, all kept` |
| `cap-mutated.txt` | `transmit_word` answers `Err(NODEVICE)` | `13 clauses, 1 BROKEN` |
| `cap-loopback-green.txt` | UART1 in internal loopback | `16 clauses, all kept` |
| `cap-loopback-bitflip.txt` | loopback, one bit flipped on send | `16 clauses, 1 BROKEN` |

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

## The loopback pair

`UARTCR.LBE` feeds the transmit path into the receive path inside the
peripheral (datasheet 12.1.3.2.6), so the test can compare what came back
against what it sent. **No jumper**: the loop sits ahead of the pads, which is
what makes it usable on a board whose free pins are already spoken for. The
same fact bounds what it shows -- the pads and the pin mux are not exercised.

The bit-flip run is the control, and it establishes more than "the clause can
fail". With `tx_buf[0] = PATTERN[i] ^ 0x01` the board reported:

    sent [85, 170, 0, 255] got [84, 171, 1, 254]

Every received byte is exactly the transmitted byte with bit 0 flipped. So the
bytes genuinely travelled the transmit path into the receive path -- a green
run could otherwise have meant the comparison was against something the test
had itself written into the buffer.

**The first attempt at this failed, and how it failed is worth keeping.** It
sent all four bytes back to back and the test simply never reported. Reading
the peripheral on the stuck board gave `UARTFR = 0x90` (RXFE set, receive
register empty), `UARTIMSC = 0x10` (RXIM still armed) and `UARTRIS = 0x42f`
-- **bit 10, OE, overrun**. The rp2350 runs with FIFOs disabled, because its
receive path tests `RXFF`, which with FIFOs enabled would need 32 queued bytes
to fire; so the receive side holds one byte, four arrived, and the surplus was
dropped with no further interrupt. The test now sends one byte per round trip
and starts the next only from the receive callback.

Nothing here exercises the `MuxUart` word-transmit wedge fixed the same day.
That path is pinned by a host test instead --
`capsules/core/tests/virtual_uart_word.rs` -- because reproducing it on
hardware means deliberately wedging the console the test reports through.
