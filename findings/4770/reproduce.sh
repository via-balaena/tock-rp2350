#!/bin/sh
# Reproduce tock/tock#4770 and measure every candidate fix.
#
#   ./reproduce.sh path/to/raspberry_pi_pico.elf
#
# Builds nothing and needs no board. It runs the two objcopy steps from
# boards/raspberry_pi_pico/Makefile against a kernel you have already built,
# then reports, for each variant:
#
#   stack     the LOAD segment at 0x20000000, as FileSiz/MemSiz. This is the
#             bug: the section is NOBITS, so FileSiz must be 0.
#   uf2       whether elf2uf2-rs will convert the result
#   app       whether the application bytes are really in the UF2, decoded
#             from the block headers rather than assumed from an exit code
#   _estack   whether the stack symbols survive, which some fixes cost
#
# Needs arm-none-eabi-objcopy, arm-none-eabi-readelf, elf2uf2-rs and python3.

set -eu

KERNEL=${1:?usage: reproduce.sh path/to/raspberry_pi_pico.elf}
OC=${OBJCOPY:-arm-none-eabi-objcopy}
RE=${READELF:-arm-none-eabi-readelf}
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# A stand-in for a real .tbf. The bug is in the section flags, not the
# payload, so any 4096 bytes reproduce it -- and a recognisable filler is
# what lets the decoder below prove the app reached the image.
python3 -c "open('$WORK/app.tbf','wb').write(b'\xAA'*4096)"

# Decode the UF2 and report which blocks carry the filler, so "it converted"
# is never mistaken for "the app is in there". llvm-objcopy passes the first
# test and fails this one.
cat > "$WORK/decode.py" <<'PY'
import struct, sys
data = open(sys.argv[1], 'rb').read()
addrs = []
for i in range(len(data) // 512):
    block = data[i * 512:(i + 1) * 512]
    length, addr = struct.unpack('<I', block[16:20])[0], struct.unpack('<I', block[12:16])[0]
    payload = block[32:32 + length]
    if length and payload.count(0xAA) == length:
        addrs.append(addr)
print('%d blocks, app in %d at %s' % (len(data) // 512, len(addrs),
      ('%#x-%#x' % (min(addrs), max(addrs))) if addrs else 'nowhere'))
PY

variant() {
    label=$1; shift
    elf="$WORK/v.elf"; uf2="$WORK/v.uf2"
    rm -f "$elf" "$uf2"
    # The two steps from the Makefile, in order. The first must be its own
    # invocation: --update-section on its own fails with "section has no
    # contents", because .apps is NOBITS until the flags change.
    $OC --set-section-flags .apps=LOAD,ALLOC "$KERNEL" "$elf" 2>/dev/null
    $OC --update-section .apps="$WORK/app.tbf" "$elf" 2>/dev/null
    "$@" >/dev/null 2>&1 || true          # the candidate fix, if any
    stack=$($RE -lW "$elf" | awk '$1=="LOAD" && $3=="0x20000000"{print $5"/"$6}')
    if elf2uf2-rs "$elf" "$uf2" >/dev/null 2>&1; then
        uf2res=ok; app=$(python3 "$WORK/decode.py" "$uf2")
    else
        uf2res=REFUSED; app='-'
    fi
    sym=$($RE -sW "$elf" | grep -c ' _estack$' || true)
    printf '%-30s %-15s %-8s %-8s %s\n' "$label" "${stack:-removed}" "$uf2res" \
        "$([ "$sym" -gt 0 ] && echo kept || echo lost)" "$app"
}

printf '%-30s %-15s %-8s %-8s %s\n' VARIANT STACK-FILE/MEM UF2 _ESTACK APP
printf '%-30s %-15s %-8s %-8s %s\n' ------- -------------- --- ------- ---
variant 'Makefile as it stands'      true
variant '-R .stack'                  $OC -R .stack "$WORK/v.elf"
variant '-R .stack -R .relocate -R .bss' $OC -R .stack -R .relocate -R .bss "$WORK/v.elf"
variant 'set .stack=alloc,noload'    $OC --set-section-flags .stack=alloc,noload "$WORK/v.elf"
variant 'set .stack=noload'          $OC --set-section-flags .stack=noload "$WORK/v.elf"

# The flag spelling has to be varied by rebuilding from the kernel rather
# than post-processing, so it does not fit the helper above.
rm -f "$WORK/v.elf"
$OC --set-section-flags .apps=alloc,load,contents "$KERNEL" "$WORK/v.elf" 2>/dev/null
$OC --update-section .apps="$WORK/app.tbf" "$WORK/v.elf" 2>/dev/null
stack=$($RE -lW "$WORK/v.elf" | awk '$1=="LOAD" && $3=="0x20000000"{print $5"/"$6}')
elf2uf2-rs "$WORK/v.elf" "$WORK/v.uf2" >/dev/null 2>&1 \
    && res=ok || res=REFUSED
printf '%-30s %-15s %-8s %-8s %s\n' 'set .apps=alloc,load,contents' \
    "${stack:-removed}" "$res" '-' '-'

echo
echo "The control: the same kernel with no objcopy at all."
rm -f "$WORK/k.uf2"
elf2uf2-rs "$KERNEL" "$WORK/k.uf2" >/dev/null 2>&1 \
    && echo "  converts, $(python3 "$WORK/decode.py" "$WORK/k.uf2")" \
    || echo "  REFUSED -- then the kernel itself is the problem, not .apps"
